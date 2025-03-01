# Copyright (C) 2005-2012 Canonical Ltd
# Copyright (C) 2017 Breezy Developers
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

from io import BytesIO
from typing import TYPE_CHECKING, Union

from ..lazy_import import lazy_import

lazy_import(
    globals(),
    """
from breezy import (
    cache_utf8,
    config as _mod_config,
    lockdir,
    shelf,
    ui,
    )
from breezy.bzr import (
    tag as _mod_tag,
    vf_search,
    )
""",
)

from .. import errors, lockable_files, urlutils
from .. import revision as _mod_revision
from .. import transport as _mod_transport
from ..branch import (
    Branch,
    BranchFormat,
    BranchWriteLockResult,
    UnstackableBranchFormat,
    format_registry,
)
from ..controldir import ControlDir
from ..decorators import only_raises
from ..lock import LogicalLockResult, _RelockDebugMixin
from ..trace import mutter
from . import bzrdir, rio
from .repository import MetaDirRepository

if TYPE_CHECKING:
    from .remote import RemoteRepository


class BzrBranch(Branch, _RelockDebugMixin):
    """A branch stored in the actual filesystem.

    Note that it's "local" in the context of the filesystem; it doesn't
    really matter if it's on an nfs/smb/afs/coda/... share, as long as
    it's writable, and can be accessed via the normal filesystem API.

    :ivar _transport: Transport for file operations on this branch's
        control files, typically pointing to the .bzr/branch directory.
    :ivar repository: Repository for this branch.
    :ivar base: The url of the base directory for this branch; the one
        containing the .bzr directory.
    :ivar name: Optional colocated branch name as it exists in the control
        directory.
    """

    repository: Union[MetaDirRepository, "RemoteRepository"]
    controldir: bzrdir.BzrDir

    @property
    def control_transport(self) -> _mod_transport.Transport:
        return self._transport

    def __init__(
        self,
        *,
        a_controldir: bzrdir.BzrDir,
        name: str,
        _repository: MetaDirRepository,
        _control_files: lockable_files.LockableFiles,
        _format=None,
        ignore_fallbacks=False,
        possible_transports=None,
    ):
        """Create new branch object at a particular location."""
        self.controldir = a_controldir
        self._user_transport = self.controldir.transport.clone("..")
        if name != "":
            self._user_transport.set_segment_parameter("branch", urlutils.escape(name))
        self._base = self._user_transport.base
        self.name = name
        self._format = _format
        self.control_files = _control_files
        self._transport = _control_files._transport
        self.repository = _repository
        self.conf_store = None
        Branch.__init__(self, possible_transports)
        self._tags_bytes = None

    def __str__(self):
        return "{}({})".format(self.__class__.__name__, self.user_url)

    __repr__ = __str__

    def _get_base(self):
        """Returns the directory containing the control directory."""
        return self._base

    base = property(_get_base, doc="The URL for the root of this branch.")  # type: ignore

    @property
    def user_transport(self):
        return self._user_transport

    def _get_config(self):
        """Get the concrete config for just the config in this branch.

        This is not intended for client use; see Branch.get_config for the
        public API.

        Added in 1.14.

        :return: An object supporting get_option and set_option.
        """
        return _mod_config.TransportConfig(self._transport, "branch.conf")

    def _get_config_store(self):
        if self.conf_store is None:
            self.conf_store = _mod_config.BranchStore(self)
        return self.conf_store

    def _uncommitted_branch(self):
        """Return the branch that may contain uncommitted changes."""
        master = self.get_master_branch()
        if master is not None:
            return master
        else:
            return self

    def store_uncommitted(self, creator):
        """Store uncommitted changes from a ShelfCreator.

        :param creator: The ShelfCreator containing uncommitted changes, or
            None to delete any stored changes.
        :raises: ChangesAlreadyStored if the branch already has changes.
        """
        branch = self._uncommitted_branch()
        if creator is None:
            branch._transport.delete("stored-transform")
            return
        if branch._transport.has("stored-transform"):
            raise errors.ChangesAlreadyStored
        transform = BytesIO()
        creator.write_shelf(transform)
        transform.seek(0)
        branch._transport.put_file("stored-transform", transform)

    def get_unshelver(self, tree):
        """Return a shelf.Unshelver for this branch and tree.

        :param tree: The tree to use to construct the Unshelver.
        :return: an Unshelver or None if no changes are stored.
        """
        branch = self._uncommitted_branch()
        try:
            transform = branch._transport.get("stored-transform")
        except _mod_transport.NoSuchFile:
            return None
        return shelf.Unshelver.from_tree_and_shelf(tree, transform)

    def is_locked(self) -> bool:
        return self.control_files.is_locked()

    def lock_write(self, token=None):
        """Lock the branch for write operations.

        :param token: A token to permit reacquiring a previously held and
            preserved lock.
        :return: A BranchWriteLockResult.
        """
        if not self.is_locked():
            self._note_lock("w")
            self.repository._warn_if_deprecated(self)
            self.repository.lock_write()
            took_lock = True
        else:
            took_lock = False
        try:
            return BranchWriteLockResult(
                self.unlock, self.control_files.lock_write(token=token)
            )
        except BaseException:
            if took_lock:
                self.repository.unlock()
            raise

    def lock_read(self):
        """Lock the branch for read operations.

        :return: A breezy.lock.LogicalLockResult.
        """
        if not self.is_locked():
            self._note_lock("r")
            self.repository._warn_if_deprecated(self)
            self.repository.lock_read()
            took_lock = True
        else:
            took_lock = False
        try:
            self.control_files.lock_read()
            return LogicalLockResult(self.unlock)
        except BaseException:
            if took_lock:
                self.repository.unlock()
            raise

    @only_raises(errors.LockNotHeld, errors.LockBroken)
    def unlock(self):
        if self.control_files._lock_count == 1 and self.conf_store is not None:
            self.conf_store.save_changes()
        try:
            self.control_files.unlock()
        finally:
            if not self.control_files.is_locked():
                self.repository.unlock()
                # we just released the lock
                self._clear_cached_state()

    def peek_lock_mode(self):
        if self.control_files._lock_count == 0:
            return None
        else:
            return self.control_files._lock_mode

    def get_physical_lock_status(self):
        return self.control_files.get_physical_lock_status()

    def set_last_revision_info(self, revno, revision_id):
        if not revision_id or not isinstance(revision_id, bytes):
            raise errors.InvalidRevisionId(revision_id=revision_id, branch=self)
        with self.lock_write():
            old_revno, old_revid = self.last_revision_info()
            if self.get_append_revisions_only():
                self._check_history_violation(revision_id)
            self._run_pre_change_branch_tip_hooks(revno, revision_id)
            self._write_last_revision_info(revno, revision_id)
            self._clear_cached_state()
            self._last_revision_info_cache = revno, revision_id
            self._run_post_change_branch_tip_hooks(old_revno, old_revid)

    def basis_tree(self):
        """See Branch.basis_tree."""
        return self.repository.revision_tree(self.last_revision())

    def _get_parent_location(self):
        _locs = ["parent", "pull", "x-pull"]
        for l in _locs:
            try:
                contents = self._transport.get_bytes(l)
            except _mod_transport.NoSuchFile:
                pass
            else:
                return contents.strip(b"\n").decode("utf-8")
        return None

    def get_stacked_on_url(self):
        raise UnstackableBranchFormat(self._format, self.user_url)

    def set_push_location(self, location):
        """See Branch.set_push_location."""
        self.get_config().set_user_option(
            "push_location", location, store=_mod_config.STORE_LOCATION_NORECURSE
        )

    def _set_parent_location(self, url):
        if url is None:
            self._transport.delete("parent")
        else:
            if isinstance(url, str):
                url = url.encode("utf-8")
            self._transport.put_bytes(
                "parent", url + b"\n", mode=self.controldir._get_file_mode()
            )

    def unbind(self):
        """If bound, unbind"""
        with self.lock_write():
            return self.set_bound_location(None)

    def bind(self, other):
        """Bind this branch to the branch other.

        This does not push or pull data between the branches, though it does
        check for divergence to raise an error when the branches are not
        either the same, or one a prefix of the other. That behaviour may not
        be useful, so that check may be removed in future.

        :param other: The branch to bind to
        :type other: Branch
        """
        # TODO: jam 20051230 Consider checking if the target is bound
        #       It is debatable whether you should be able to bind to
        #       a branch which is itself bound.
        #       Committing is obviously forbidden,
        #       but binding itself may not be.
        #       Since we *have* to check at commit time, we don't
        #       *need* to check here

        # we want to raise diverged if:
        # last_rev is not in the other_last_rev history, AND
        # other_last_rev is not in our history, and do it without pulling
        # history around
        with self.lock_write():
            self.set_bound_location(other.base)

    def get_bound_location(self):
        try:
            return self._transport.get_bytes("bound")[:-1].decode("utf-8")
        except _mod_transport.NoSuchFile:
            return None

    def get_master_branch(self, possible_transports=None):
        """Return the branch we are bound to.

        :return: Either a Branch, or None
        """
        with self.lock_read():
            if self._master_branch_cache is None:
                self._master_branch_cache = self._get_master_branch(possible_transports)
            return self._master_branch_cache

    def _get_master_branch(self, possible_transports):
        bound_loc = self.get_bound_location()
        if not bound_loc:
            return None
        try:
            return Branch.open(bound_loc, possible_transports=possible_transports)
        except (errors.NotBranchError, errors.ConnectionError) as exc:
            raise errors.BoundBranchConnectionFailure(self, bound_loc, exc) from exc

    def set_bound_location(self, location):
        """Set the target where this branch is bound to.

        :param location: URL to the target branch
        """
        with self.lock_write():
            self._master_branch_cache = None
            if location:
                self._transport.put_bytes(
                    "bound",
                    location.encode("utf-8") + b"\n",
                    mode=self.controldir._get_file_mode(),
                )
            else:
                try:
                    self._transport.delete("bound")
                except _mod_transport.NoSuchFile:
                    return False
                return True

    def update(self, possible_transports=None):
        """Synchronise this branch with the master branch if any.

        :return: None or the last_revision that was pivoted out during the
                 update.
        """
        with self.lock_write():
            master = self.get_master_branch(possible_transports)
            if master is not None:
                old_tip = self.last_revision()
                self.pull(master, overwrite=True)
                if self.repository.get_graph().is_ancestor(
                    old_tip, self.last_revision()
                ):
                    return None
                return old_tip
            return None

    def _read_last_revision_info(self):
        revision_string = self._transport.get_bytes("last-revision")
        revno, revision_id = revision_string.rstrip(b"\n").split(b" ", 1)
        revision_id = cache_utf8.get_cached_utf8(revision_id)
        revno = int(revno)
        return revno, revision_id

    def _write_last_revision_info(self, revno, revision_id):
        """Simply write out the revision id, with no checks.

        Use set_last_revision_info to perform this safely.

        Does not update the revision_history cache.
        """
        out_string = b"%d %s\n" % (revno, revision_id)
        self._transport.put_bytes(
            "last-revision", out_string, mode=self.controldir._get_file_mode()
        )

    def update_feature_flags(self, updated_flags):
        """Update the feature flags for this branch.

        :param updated_flags: Dictionary mapping feature names to necessities
            A necessity can be None to indicate the feature should be removed
        """
        with self.lock_write():
            self._format._update_feature_flags(updated_flags)
            self.control_transport.put_bytes("format", self._format.as_string())

    def _get_tags_bytes(self):
        """Get the bytes of a serialised tags dict.

        Note that not all branches support tags, nor do all use the same tags
        logic: this method is specific to BasicTags. Other tag implementations
        may use the same method name and behave differently, safely, because
        of the double-dispatch via
        format.make_tags->tags_instance->get_tags_dict.

        :return: The bytes of the tags file.
        :seealso: Branch._set_tags_bytes.
        """
        with self.lock_read():
            if self._tags_bytes is None:
                self._tags_bytes = self._transport.get_bytes("tags")
            return self._tags_bytes

    def _set_tags_bytes(self, bytes):
        """Mirror method for _get_tags_bytes.

        :seealso: Branch._get_tags_bytes.
        """
        with self.lock_write():
            self._tags_bytes = bytes
            return self._transport.put_bytes("tags", bytes)

    def _clear_cached_state(self):
        super()._clear_cached_state()
        self._tags_bytes = None

    def reconcile(self, thorough=True):
        """Make sure the data stored in this branch is consistent."""
        from .reconcile import BranchReconciler

        with self.lock_write():
            reconciler = BranchReconciler(self, thorough=thorough)
            return reconciler.reconcile()

    def set_reference_info(self, file_id, branch_location, path=None):
        """Set the branch location to use for a tree reference."""
        raise errors.UnsupportedOperation(self.set_reference_info, self)

    def get_reference_info(self, file_id, path=None):
        """Get the tree_path and branch_location for a tree reference."""
        raise errors.UnsupportedOperation(self.get_reference_info, self)

    def reference_parent(self, file_id, path, possible_transports=None):
        """Return the parent branch for a tree-reference.

        :param path: The path of the nested tree in the tree
        :return: A branch associated with the nested tree
        """
        try:
            branch_location = self.get_reference_info(file_id)[0]
        except errors.UnsupportedOperation:
            branch_location = None
        if branch_location is None:
            try:
                return Branch.open_from_transport(
                    self.controldir.root_transport.clone(path),
                    possible_transports=possible_transports,
                )
            except errors.NotBranchError:
                return None
        return Branch.open(
            urlutils.join(
                urlutils.strip_segment_parameters(self.user_url), branch_location
            ),
            possible_transports=possible_transports,
        )

    def set_stacked_on_url(self, url: str) -> None:
        """Set the URL this branch is stacked against.

        :raises UnstackableBranchFormat: If the branch does not support
            stacking.
        :raises UnstackableRepositoryFormat: If the repository does not support
            stacking.
        """
        if not self._format.supports_stacking():
            raise UnstackableBranchFormat(self._format, self.user_url)
        with self.lock_write():
            # XXX: Changing from one fallback repository to another does not
            # check that all the data you need is present in the new fallback.
            # Possibly it should.
            self._check_stackable_repo()
            if not url:
                try:
                    self.get_stacked_on_url()
                except (
                    errors.NotStacked,
                    UnstackableBranchFormat,
                    errors.UnstackableRepositoryFormat,
                ):
                    return
                self._unstack()
            else:
                self._activate_fallback_location(
                    url, possible_transports=[self.controldir.root_transport]
                )
            # write this out after the repository is stacked to avoid setting a
            # stacked config that doesn't work.
            self._set_config_location("stacked_on_location", url)

    def _check_stackable_repo(self) -> None:
        if not self.repository._format.supports_external_lookups:
            raise errors.UnstackableRepositoryFormat(
                self.repository._format, self.repository.user_url
            )

    def _unstack(self):
        """Change a branch to be unstacked, copying data as needed.

        Don't call this directly, use set_stacked_on_url(None).
        """
        with ui.ui_factory.nested_progress_bar() as pb:
            # The basic approach here is to fetch the tip of the branch,
            # including all available ghosts, from the existing stacked
            # repository into a new repository object without the fallbacks.
            #
            # XXX: See <https://launchpad.net/bugs/397286> - this may not be
            # correct for CHKMap repostiories
            old_repository = self.repository
            if len(old_repository._fallback_repositories) != 1:
                raise AssertionError(
                    "can't cope with fallback repositories "
                    "of %r (fallbacks: %r)"
                    % (old_repository, old_repository._fallback_repositories)
                )
            # Open the new repository object.
            # Repositories don't offer an interface to remove fallback
            # repositories today; take the conceptually simpler option and just
            # reopen it.  We reopen it starting from the URL so that we
            # get a separate connection for RemoteRepositories and can
            # stream from one of them to the other.  This does mean doing
            # separate SSH connection setup, but unstacking is not a
            # common operation so it's tolerable.
            new_bzrdir = ControlDir.open(self.controldir.root_transport.base)
            new_repository = new_bzrdir.find_repository()
            if new_repository._fallback_repositories:
                raise AssertionError(
                    "didn't expect %r to have fallback_repositories"
                    % (self.repository,)
                )
            # Replace self.repository with the new repository.
            # Do our best to transfer the lock state (i.e. lock-tokens and
            # lock count) of self.repository to the new repository.
            lock_token = old_repository.lock_write().repository_token
            self.repository = new_repository
            self.repository.lock_write(token=lock_token)
            if lock_token is not None:
                old_repository.leave_lock_in_place()
            old_repository.unlock()
            if lock_token is not None:
                # XXX: self.repository.leave_lock_in_place() before this
                # function will not be preserved.  Fortunately that doesn't
                # affect the current default format (2a), and would be a
                # corner-case anyway.
                #  - Andrew Bennetts, 2010/06/30
                self.repository.dont_leave_lock_in_place()
            old_lock_count = 0
            while True:
                try:
                    old_repository.unlock()
                except errors.LockNotHeld:
                    break
                old_lock_count += 1
            if old_lock_count == 0:
                raise AssertionError(
                    "old_repository should have been locked at least once."
                )
            for i in range(old_lock_count - 1):
                self.repository.lock_write()
            # Fetch from the old repository into the new.
            with old_repository.lock_read():
                # XXX: If you unstack a branch while it has a working tree
                # with a pending merge, the pending-merged revisions will no
                # longer be present.  You can (probably) revert and remerge.
                try:
                    tags_to_fetch = set(self.tags.get_reverse_tag_dict())
                except errors.TagsNotSupported:
                    tags_to_fetch = set()
                fetch_spec = vf_search.NotInOtherForRevs(
                    self.repository,
                    old_repository,
                    required_ids=[self.last_revision()],
                    if_present_ids=tags_to_fetch,
                    find_ghosts=True,
                ).execute()
                self.repository.fetch(old_repository, fetch_spec=fetch_spec)

    def break_lock(self) -> None:
        """Break a lock if one is present from another instance.

        Uses the ui factory to ask for confirmation if the lock may be from
        an active process.

        This will probe the repository for its lock as well.
        """
        self.control_files.break_lock()
        self.repository.break_lock()
        master = self.get_master_branch()
        if master is not None:
            master.break_lock()


class BzrBranch8(BzrBranch):
    """A branch that stores tree-reference locations."""

    def _open_hook(self, possible_transports=None):
        if self._ignore_fallbacks:
            return
        if possible_transports is None:
            possible_transports = [self.controldir.root_transport]
        try:
            url = self.get_stacked_on_url()
        except (
            errors.UnstackableRepositoryFormat,
            errors.NotStacked,
            UnstackableBranchFormat,
        ):
            pass
        else:
            for hook in Branch.hooks["transform_fallback_location"]:
                url = hook(self, url)
                if url is None:
                    hook_name = Branch.hooks.get_hook_name(hook)
                    raise AssertionError(
                        "'transform_fallback_location' hook %s returned "
                        "None, not a URL." % hook_name
                    )
            self._activate_fallback_location(
                url, possible_transports=possible_transports
            )

    def __init__(self, *args, **kwargs):
        self._ignore_fallbacks = kwargs.get("ignore_fallbacks", False)
        super().__init__(*args, **kwargs)
        self._last_revision_info_cache = None
        self._reference_info = None

    def _clear_cached_state(self):
        super()._clear_cached_state()
        self._last_revision_info_cache = None
        self._reference_info = None

    def _check_history_violation(self, revision_id):
        last_revision = self.last_revision()
        if _mod_revision.is_null(last_revision):
            return
        graph = self.repository.get_graph()
        for lh_ancestor in graph.iter_lefthand_ancestry(revision_id):
            if lh_ancestor == last_revision:
                return
        raise errors.AppendRevisionsOnlyViolation(self.user_url)

    def _gen_revision_history(self):
        """Generate the revision history from last revision"""
        last_revno, last_revision = self.last_revision_info()
        self._extend_partial_history(stop_index=last_revno - 1)
        return list(reversed(self._partial_revision_history_cache))

    def _set_parent_location(self, url):
        """Set the parent branch"""
        with self.lock_write():
            self._set_config_location("parent_location", url, make_relative=True)

    def _get_parent_location(self):
        """Set the parent branch"""
        with self.lock_read():
            return self._get_config_location("parent_location")

    def _set_all_reference_info(self, info_dict):
        """Replace all reference info stored in a branch.

        :param info_dict: A dict of {file_id: (branch_location, tree_path)}
        """
        s = BytesIO()
        writer = rio.RioWriter(s)
        for file_id, (branch_location, tree_path) in info_dict.items():
            stanza = rio.Stanza(file_id=file_id, branch_location=branch_location)
            if tree_path is not None:
                stanza.add("tree_path", tree_path)
            writer.write_stanza(stanza)
        with self.lock_write():
            self._transport.put_bytes("references", s.getvalue())
            self._reference_info = info_dict

    def _get_all_reference_info(self):
        """Return all the reference info stored in a branch.

        :return: A dict of {tree_path: (branch_location, file_id)}
        """
        with self.lock_read():
            if self._reference_info is not None:
                return self._reference_info
            try:
                with self._transport.get("references") as rio_file:
                    stanzas = rio.read_stanzas(rio_file)
                    info_dict = {
                        s["file_id"].encode("utf-8"): (
                            s["branch_location"],
                            s["tree_path"] if "tree_path" in s else None,
                        )
                        for s in stanzas
                    }
            except _mod_transport.NoSuchFile:
                info_dict = {}
            self._reference_info = info_dict
            return info_dict

    def set_reference_info(self, file_id, branch_location, tree_path=None):
        """Set the branch location to use for a tree reference.

        :param branch_location: The location of the branch to retrieve tree
            references from.
        :param file_id: The file-id of the tree reference.
        :param tree_path: The path of the tree reference in the tree.
        """
        info_dict = self._get_all_reference_info()
        info_dict[file_id] = (branch_location, tree_path)
        if branch_location is None:
            del info_dict[file_id]
        self._set_all_reference_info(info_dict)

    def get_reference_info(self, file_id):
        """Get the tree_path and branch_location for a tree reference.

        :return: a tuple of (branch_location, tree_path)
        """
        return self._get_all_reference_info().get(file_id, (None, None))

    def set_push_location(self, location):
        """See Branch.set_push_location."""
        self._set_config_location("push_location", location)

    def set_bound_location(self, location):
        """See Branch.set_push_location."""
        self._master_branch_cache = None
        conf = self.get_config_stack()
        if location is None:
            if not conf.get("bound"):
                return False
            else:
                conf.set("bound", "False")
                return True
        else:
            self._set_config_location("bound_location", location, config=conf)
            conf.set("bound", "True")
        return True

    def _get_bound_location(self, bound):
        """Return the bound location in the config file.

        Return None if the bound parameter does not match
        """
        conf = self.get_config_stack()
        if conf.get("bound") != bound:
            return None
        return self._get_config_location("bound_location", config=conf)

    def get_bound_location(self):
        """See Branch.get_bound_location."""
        return self._get_bound_location(True)

    def get_old_bound_location(self):
        """See Branch.get_old_bound_location"""
        return self._get_bound_location(False)

    def get_stacked_on_url(self):
        # you can always ask for the URL; but you might not be able to use it
        # if the repo can't support stacking.
        # self._check_stackable_repo()
        # stacked_on_location is only ever defined in branch.conf, so don't
        # waste effort reading the whole stack of config files.
        conf = _mod_config.BranchOnlyStack(self)
        stacked_url = self._get_config_location("stacked_on_location", config=conf)
        if stacked_url is None:
            raise errors.NotStacked(self)
        # TODO(jelmer): Clean this up for pad.lv/1696545
        return stacked_url

    def get_rev_id(self, revno, history=None):
        """Find the revision id of the specified revno."""
        if revno == 0:
            return _mod_revision.NULL_REVISION

        with self.lock_read():
            last_revno, last_revision_id = self.last_revision_info()
            if revno <= 0 or revno > last_revno:
                raise errors.RevnoOutOfBounds(revno, (0, last_revno))

            if history is not None:
                return history[revno - 1]

            index = last_revno - revno
            if len(self._partial_revision_history_cache) <= index:
                self._extend_partial_history(stop_index=index)
            if len(self._partial_revision_history_cache) > index:
                return self._partial_revision_history_cache[index]
            else:
                raise errors.NoSuchRevision(self, revno)

    def revision_id_to_revno(self, revision_id):
        """Given a revision id, return its revno"""
        if _mod_revision.is_null(revision_id):
            return 0
        with self.lock_read():
            try:
                index = self._partial_revision_history_cache.index(revision_id)
            except ValueError:
                try:
                    self._extend_partial_history(stop_revision=revision_id)
                except errors.RevisionNotPresent as exc:
                    raise errors.GhostRevisionsHaveNoRevno(
                        revision_id, exc.revision_id
                    ) from exc
                index = len(self._partial_revision_history_cache) - 1
                if index < 0:
                    raise errors.NoSuchRevision(self, revision_id)
                if self._partial_revision_history_cache[index] != revision_id:
                    raise errors.NoSuchRevision(self, revision_id)
            return self.revno() - index


class BzrBranch7(BzrBranch8):
    """A branch with support for a fallback repository."""

    def set_reference_info(self, file_id, branch_location, tree_path=None):
        super().set_reference_info(file_id, branch_location, tree_path)
        format_string = BzrBranchFormat8.get_format_string()
        mutter("Upgrading branch to format %r", format_string)
        self._transport.put_bytes("format", format_string)


class BzrBranch6(BzrBranch7):
    """See BzrBranchFormat6 for the capabilities of this branch.

    This subclass of BzrBranch7 disables the new features BzrBranch7 added,
    i.e. stacking.
    """

    def get_stacked_on_url(self):
        raise UnstackableBranchFormat(self._format, self.user_url)


class BranchFormatMetadir(bzrdir.BzrFormat, BranchFormat):
    """Base class for branch formats that live in meta directories."""

    def __init__(self):
        BranchFormat.__init__(self)
        bzrdir.BzrFormat.__init__(self)

    @classmethod
    def find_format(klass, controldir, name=None):
        """Return the format for the branch object in controldir."""
        try:
            transport = controldir.get_branch_transport(None, name=name)
        except _mod_transport.NoSuchFile as exc:
            raise errors.NotBranchError(path=name, controldir=controldir) from exc
        try:
            format_string = transport.get_bytes("format")
        except _mod_transport.NoSuchFile as exc:
            raise errors.NotBranchError(
                path=transport.base, controldir=controldir
            ) from exc
        return klass._find_format(format_registry, "branch", format_string)

    def _branch_class(self):
        """What class to instantiate on open calls."""
        raise NotImplementedError(self._branch_class)

    def _get_initial_config(self, append_revisions_only=None):
        if append_revisions_only:
            return b"append_revisions_only = True\n"
        else:
            # Avoid writing anything if append_revisions_only is disabled,
            # as that is the default.
            return b""

    def _initialize_helper(self, a_controldir, utf8_files, name=None, repository=None):
        """Initialize a branch in a control dir, with specified files

        :param a_controldir: The bzrdir to initialize the branch in
        :param utf8_files: The files to create as a list of
            (filename, content) tuples
        :param name: Name of colocated branch to create, if any
        :return: a branch in this format
        """
        if name is None:
            name = a_controldir._get_selected_branch()
        mutter("creating branch %r in %s", self, a_controldir.user_url)
        branch_transport = a_controldir.get_branch_transport(self, name=name)
        control_files = lockable_files.LockableFiles(
            branch_transport, "lock", lockdir.LockDir
        )
        control_files.create_lock()
        control_files.lock_write()
        try:
            utf8_files += [("format", self.as_string())]
            for filename, content in utf8_files:
                branch_transport.put_bytes(
                    filename, content, mode=a_controldir._get_file_mode()
                )
        finally:
            control_files.unlock()
        branch = self.open(a_controldir, name, _found=True, found_repository=repository)
        self._run_post_branch_init_hooks(a_controldir, name, branch)
        return branch

    def open(
        self,
        a_controldir,
        name=None,
        _found=False,
        ignore_fallbacks=False,
        found_repository=None,
        possible_transports=None,
    ):
        """See BranchFormat.open()."""
        if name is None:
            name = a_controldir._get_selected_branch()
        if not _found:
            format = BranchFormatMetadir.find_format(a_controldir, name=name)
            if format.__class__ != self.__class__:
                raise AssertionError("wrong format %r found for %r" % (format, self))
        transport = a_controldir.get_branch_transport(None, name=name)
        try:
            control_files = lockable_files.LockableFiles(
                transport, "lock", lockdir.LockDir
            )
            if found_repository is None:
                found_repository = a_controldir.find_repository()
            return self._branch_class()(
                _format=self,
                _control_files=control_files,
                name=name,
                a_controldir=a_controldir,
                _repository=found_repository,
                ignore_fallbacks=ignore_fallbacks,
                possible_transports=possible_transports,
            )
        except _mod_transport.NoSuchFile as exc:
            raise errors.NotBranchError(
                path=transport.base, controldir=a_controldir
            ) from exc

    @property
    def _matchingcontroldir(self):
        ret = bzrdir.BzrDirMetaFormat1()
        ret.set_branch_format(self)
        return ret

    def supports_tags(self):
        return True

    def supports_leaving_lock(self):
        return True

    def check_support_status(
        self, allow_unsupported, recommend_upgrade=True, basedir=None
    ):
        BranchFormat.check_support_status(
            self,
            allow_unsupported=allow_unsupported,
            recommend_upgrade=recommend_upgrade,
            basedir=basedir,
        )
        bzrdir.BzrFormat.check_support_status(
            self,
            allow_unsupported=allow_unsupported,
            recommend_upgrade=recommend_upgrade,
            basedir=basedir,
        )


class BzrBranchFormat6(BranchFormatMetadir):
    """Branch format with last-revision and tags.

    Unlike previous formats, this has no explicit revision history. Instead,
    this just stores the last-revision, and the left-hand history leading
    up to there is the history.

    This format was introduced in bzr 0.15
    and became the default in 0.91.
    """

    def _branch_class(self):
        return BzrBranch6

    @classmethod
    def get_format_string(cls):
        """See BranchFormat.get_format_string()."""
        return b"Bazaar Branch Format 6 (bzr 0.15)\n"

    def get_format_description(self):
        """See BranchFormat.get_format_description()."""
        return "Branch format 6"

    def initialize(
        self, a_controldir, name=None, repository=None, append_revisions_only=None
    ):
        """Create a branch of this format in a_controldir."""
        utf8_files = [
            ("last-revision", b"0 null:\n"),
            ("branch.conf", self._get_initial_config(append_revisions_only)),
            ("tags", b""),
        ]
        return self._initialize_helper(a_controldir, utf8_files, name, repository)

    def make_tags(self, branch):
        """See breezy.branch.BranchFormat.make_tags()."""
        return _mod_tag.BasicTags(branch)

    def supports_set_append_revisions_only(self):
        return True

    supports_reference_locations = True


class BzrBranchFormat8(BranchFormatMetadir):
    """Metadir format supporting storing locations of subtree branches."""

    def _branch_class(self):
        return BzrBranch8

    @classmethod
    def get_format_string(cls):
        """See BranchFormat.get_format_string()."""
        return b"Bazaar Branch Format 8 (needs bzr 1.15)\n"

    def get_format_description(self):
        """See BranchFormat.get_format_description()."""
        return "Branch format 8"

    def initialize(
        self, a_controldir, name=None, repository=None, append_revisions_only=None
    ):
        """Create a branch of this format in a_controldir."""
        utf8_files = [
            ("last-revision", b"0 null:\n"),
            ("branch.conf", self._get_initial_config(append_revisions_only)),
            ("tags", b""),
            ("references", b""),
        ]
        return self._initialize_helper(a_controldir, utf8_files, name, repository)

    def make_tags(self, branch):
        """See breezy.branch.BranchFormat.make_tags()."""
        return _mod_tag.BasicTags(branch)

    def supports_set_append_revisions_only(self):
        return True

    def supports_stacking(self):
        return True

    supports_reference_locations = True


class BzrBranchFormat7(BranchFormatMetadir):
    """Branch format with last-revision, tags, and a stacked location pointer.

    The stacked location pointer is passed down to the repository and requires
    a repository format with supports_external_lookups = True.

    This format was introduced in bzr 1.6.
    """

    def initialize(
        self, a_controldir, name=None, repository=None, append_revisions_only=None
    ):
        """Create a branch of this format in a_controldir."""
        utf8_files = [
            ("last-revision", b"0 null:\n"),
            ("branch.conf", self._get_initial_config(append_revisions_only)),
            ("tags", b""),
        ]
        return self._initialize_helper(a_controldir, utf8_files, name, repository)

    def _branch_class(self):
        return BzrBranch7

    @classmethod
    def get_format_string(cls):
        """See BranchFormat.get_format_string()."""
        return b"Bazaar Branch Format 7 (needs bzr 1.6)\n"

    def get_format_description(self):
        """See BranchFormat.get_format_description()."""
        return "Branch format 7"

    def supports_set_append_revisions_only(self):
        return True

    def supports_stacking(self):
        return True

    def make_tags(self, branch):
        """See breezy.branch.BranchFormat.make_tags()."""
        return _mod_tag.BasicTags(branch)

    # This is a white lie; as soon as you set a reference location, we upgrade
    # you to BzrBranchFormat8.
    supports_reference_locations = True


class BranchReferenceFormat(BranchFormatMetadir):
    """Bzr branch reference format.

    Branch references are used in implementing checkouts, they
    act as an alias to the real branch which is at some other url.

    This format has:
     - A location file
     - a format string
    """

    @classmethod
    def get_format_string(cls):
        """See BranchFormat.get_format_string()."""
        return b"Bazaar-NG Branch Reference Format 1\n"

    def get_format_description(self):
        """See BranchFormat.get_format_description()."""
        return "Checkout reference format 1"

    def get_reference(self, a_controldir, name=None):
        """See BranchFormat.get_reference()."""
        transport = a_controldir.get_branch_transport(None, name=name)
        url = urlutils.strip_segment_parameters(a_controldir.user_url)
        return urlutils.join(url, transport.get_bytes("location").decode("utf-8"))

    def _write_reference(self, a_controldir, transport, to_branch):
        to_url = to_branch.user_url
        # Ideally, we'd write a relative path here for the benefit of colocated
        # branches - so that moving a control directory doesn't break
        # any references to colocated branches. Unfortunately, bzr
        # does not support relative URLs. See pad.lv/1803845 -- jelmer
        # to_url = urlutils.relative_url(
        #    a_controldir.user_url, to_branch.user_url)
        transport.put_bytes("location", to_url.encode("utf-8"))

    def set_reference(self, a_controldir, name, to_branch):
        """See BranchFormat.set_reference()."""
        transport = a_controldir.get_branch_transport(None, name=name)
        self._write_reference(a_controldir, transport, to_branch)

    def initialize(
        self,
        a_controldir,
        name=None,
        target_branch=None,
        repository=None,
        append_revisions_only=None,
    ):
        """Create a branch of this format in a_controldir."""
        if target_branch is None:
            # this format does not implement branch itself, thus the implicit
            # creation contract must see it as uninitializable
            raise errors.UninitializableFormat(self)
        mutter("creating branch reference in %s", a_controldir.user_url)
        if a_controldir._format.fixed_components:
            raise errors.IncompatibleFormat(self, a_controldir._format)
        if name is None:
            name = a_controldir._get_selected_branch()
        branch_transport = a_controldir.get_branch_transport(self, name=name)
        self._write_reference(a_controldir, branch_transport, target_branch)
        branch_transport.put_bytes("format", self.as_string())
        branch = self.open(
            a_controldir,
            name,
            _found=True,
            possible_transports=[target_branch.controldir.root_transport],
        )
        self._run_post_branch_init_hooks(a_controldir, name, branch)
        return branch

    def _make_reference_clone_function(format, a_branch):
        """Create a clone() routine for a branch dynamically."""

        def clone(
            to_bzrdir,
            revision_id=None,
            repository_policy=None,
            name=None,
            tag_selector=None,
        ):
            """See Branch.clone()."""
            return format.initialize(to_bzrdir, target_branch=a_branch, name=name)
            # cannot obey revision_id limits when cloning a reference ...
            # FIXME RBC 20060210 either nuke revision_id for clone, or
            # emit some sort of warning/error to the caller ?!

        return clone

    def open(
        self,
        a_controldir,
        name=None,
        _found=False,
        location=None,
        possible_transports=None,
        ignore_fallbacks=False,
        found_repository=None,
    ):
        """Return the branch that the branch reference in a_controldir points at.

        :param a_controldir: A BzrDir that contains a branch.
        :param name: Name of colocated branch to open, if any
        :param _found: a private parameter, do not use it. It is used to
            indicate if format probing has already be done.
        :param ignore_fallbacks: when set, no fallback branches will be opened
            (if there are any).  Default is to open fallbacks.
        :param location: The location of the referenced branch.  If
            unspecified, this will be determined from the branch reference in
            a_controldir.
        :param possible_transports: An optional reusable transports list.
        """
        if name is None:
            name = a_controldir._get_selected_branch()
        if not _found:
            format = BranchFormatMetadir.find_format(a_controldir, name=name)
            if format.__class__ != self.__class__:
                raise AssertionError("wrong format %r found for %r" % (format, self))
        if location is None:
            location = self.get_reference(a_controldir, name)
        real_bzrdir = ControlDir.open(location, possible_transports=possible_transports)
        result = real_bzrdir.open_branch(
            ignore_fallbacks=ignore_fallbacks, possible_transports=possible_transports
        )
        # this changes the behaviour of result.clone to create a new reference
        # rather than a copy of the content of the branch.
        # I did not use a proxy object because that needs much more extensive
        # testing, and we are only changing one behaviour at the moment.
        # If we decide to alter more behaviours - i.e. the implicit nickname
        # then this should be refactored to introduce a tested proxy branch
        # and a subclass of that for use in overriding clone() and ....
        # - RBC 20060210
        result.clone = self._make_reference_clone_function(result)
        return result


class Converter5to6:
    """Perform an in-place upgrade of format 5 to format 6"""

    def convert(self, branch):
        # Data for 5 and 6 can peacefully coexist.
        format = BzrBranchFormat6()
        new_branch = format.open(branch.controldir, _found=True)

        # Copy source data into target
        new_branch._write_last_revision_info(*branch.last_revision_info())
        with new_branch.lock_write():
            new_branch.set_parent(branch.get_parent())
            new_branch.set_bound_location(branch.get_bound_location())
            new_branch.set_push_location(branch.get_push_location())

        # New branch has no tags by default
        new_branch.tags._set_tag_dict({})

        # Copying done; now update target format
        new_branch._transport.put_bytes(
            "format", format.as_string(), mode=new_branch.controldir._get_file_mode()
        )

        # Clean up old files
        new_branch._transport.delete("revision-history")
        with branch.lock_write():
            try:
                branch.set_parent(None)
            except _mod_transport.NoSuchFile:
                pass
            branch.set_bound_location(None)


class Converter6to7:
    """Perform an in-place upgrade of format 6 to format 7"""

    def convert(self, branch):
        format = BzrBranchFormat7()
        branch._set_config_location("stacked_on_location", "")
        # update target format
        branch._transport.put_bytes("format", format.as_string())


class Converter7to8:
    """Perform an in-place upgrade of format 7 to format 8"""

    def convert(self, branch):
        format = BzrBranchFormat8()
        branch._transport.put_bytes("references", b"")
        # update target format
        branch._transport.put_bytes("format", format.as_string())
