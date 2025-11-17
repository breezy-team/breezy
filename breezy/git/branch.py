# Copyright (C) 2007,2012 Canonical Ltd
# Copyright (C) 2009-2018 Jelmer Vernooij <jelmer@jelmer.uk>
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

"""An adapter between a Git Branch and a Bazaar Branch."""

import contextlib
from collections import defaultdict
from functools import partial
from io import BytesIO

from dulwich.config import ConfigFile as GitConfigFile
from dulwich.config import parse_submodules
from dulwich.objects import ZERO_SHA, NotCommitError
from dulwich.repo import check_ref_format

from .. import (
    branch,
    config,
    controldir,
    errors,
    lock,
    revision,
    trace,
    transport,
    urlutils,
)
from .. import repository as _mod_repository
from ..foreign import ForeignBranch
from ..revision import NULL_REVISION
from ..tag import InterTags, TagConflict, Tags, TagSelector, TagUpdates
from ..trace import is_quiet, warning
from .errors import NoPushSupport
from .mapping import decode_git_path
from .push import remote_divergence
from .refs import (
    branch_name_to_ref,
    is_tag,
    ref_to_branch_name,
    ref_to_tag_name,
    tag_name_to_ref,
)
from .unpeel_map import UnpeelMap
from .urls import bzr_url_to_git_url, git_url_to_bzr_url


def _update_tip(source, target, revid, overwrite=False):
    if not overwrite:
        last_rev = target.last_revision()
        graph = target.repository.get_graph(source.repository)
        if graph.is_ancestor(revid, last_rev):
            # target is ahead of revid
            return
        target.generate_revision_history(revid, last_rev, other_branch=source)
    else:
        target.generate_revision_history(revid)


def _calculate_revnos(branch):
    if branch._format.stores_revno():
        return True
    config = branch.get_config_stack()
    return config.get("calculate_revnos")


class GitPullResult(branch.PullResult):
    """Result of a pull from a Git branch."""

    def _lookup_revno(self, revid):
        if not isinstance(revid, bytes):
            raise TypeError(revid)
        if not _calculate_revnos(self.target_branch):
            return None
        # Try in source branch first, it'll be faster
        with self.target_branch.lock_read():
            return self.target_branch.revision_id_to_revno(revid)

    @property
    def old_revno(self):
        return self._lookup_revno(self.old_revid)

    @property
    def new_revno(self):
        return self._lookup_revno(self.new_revid)


class InterTagsFromGitToRemoteGit(InterTags):
    @classmethod
    def is_compatible(klass, source, target):
        if not isinstance(source, GitTags):
            return False
        if not isinstance(target, GitTags):
            return False
        return not getattr(target.branch.repository, "_git", None) is not None

    def merge(
        self,
        overwrite: bool = False,
        ignore_master: bool = False,
        selector: TagSelector | None = None,
    ) -> tuple[TagUpdates, set[TagConflict]]:
        if self.source.branch.repository.has_same_location(
            self.target.branch.repository
        ):
            return {}, set()
        updates = {}
        conflicts = []
        source_tag_refs = self.source.branch.get_tag_refs()
        ref_to_tag_map = {}

        def get_changed_refs(old_refs):
            ret = dict(old_refs)
            for ref_name, tag_name, peeled, unpeeled in source_tag_refs.iteritems():
                if selector and not selector(tag_name):
                    continue
                if old_refs.get(ref_name) == unpeeled:
                    pass
                elif overwrite or ref_name not in old_refs:
                    ret[ref_name] = unpeeled
                    updates[tag_name] = (
                        self.target.branch.repository.lookup_foreign_revision_id(peeled)
                    )
                    ref_to_tag_map[ref_name] = tag_name
                    self.target.branch._tag_refs = None
                else:
                    conflicts.append(
                        (
                            tag_name,
                            self.source.branch.repository.lookup_foreign_revision_id(
                                peeled
                            ),
                            self.target.branch.repository.lookup_foreign_revision_id(
                                old_refs[ref_name]
                            ),
                        )
                    )
            return ret

        result = self.target.branch.repository.controldir.send_pack(
            get_changed_refs, lambda have, want: []
        )
        if result is not None and not isinstance(result, dict):
            for ref, error in result.ref_status.items():
                if error:
                    warning("unable to update ref %s: %s", ref, error)
                    del updates[ref_to_tag_map[ref]]
        return updates, set(conflicts)


class InterTagsFromGitToLocalGit(InterTags):
    @classmethod
    def is_compatible(klass, source, target):
        if not isinstance(source, GitTags):
            return False
        if not isinstance(target, GitTags):
            return False
        return getattr(target.branch.repository, "_git", None) is not None

    def merge(self, overwrite=False, ignore_master=False, selector=None):
        if self.source.branch.repository.has_same_location(
            self.target.branch.repository
        ):
            return {}, []

        conflicts = []
        updates = {}
        source_tag_refs = self.source.branch.get_tag_refs()

        target_repo = self.target.branch.repository

        for ref_name, tag_name, peeled, unpeeled in source_tag_refs:
            if selector and not selector(tag_name):
                continue
            if target_repo._git.refs.get(ref_name) == unpeeled:
                pass
            elif overwrite or ref_name not in target_repo._git.refs:
                try:
                    updates[tag_name] = target_repo.lookup_foreign_revision_id(peeled)
                except KeyError:
                    trace.warning("%s does not point to a valid object", tag_name)
                    continue
                except NotCommitError:
                    trace.warning("%s points to a non-commit object", tag_name)
                    continue
                target_repo._git.refs[ref_name] = unpeeled or peeled
                self.target.branch._tag_refs = None
            else:
                try:
                    source_revid = (
                        self.source.branch.repository.lookup_foreign_revision_id(peeled)
                    )
                    target_revid = target_repo.lookup_foreign_revision_id(
                        target_repo._git.refs[ref_name]
                    )
                except KeyError:
                    trace.warning("%s does not point to a valid object", ref_name)
                    continue
                except NotCommitError:
                    trace.warning("%s points to a non-commit object", tag_name)
                    continue
                conflicts.append((tag_name, source_revid, target_revid))
        return updates, set(conflicts)


class InterTagsFromGitToNonGit(InterTags):
    @classmethod
    def is_compatible(klass, source: Tags, target: Tags):
        if not isinstance(source, GitTags):
            return False
        return not isinstance(target, GitTags)

    def merge(self, overwrite=False, ignore_master=False, selector=None):
        """See Tags.merge_to."""
        source_tag_refs = self.source.branch.get_tag_refs()
        if ignore_master:
            master = None
        else:
            master = self.target.branch.get_master_branch()
        with contextlib.ExitStack() as es:
            if master is not None:
                es.enter_context(master.lock_write())
            updates, conflicts = self._merge_to(
                self.target, source_tag_refs, overwrite=overwrite, selector=selector
            )
            if master is not None:
                extra_updates, extra_conflicts = self._merge_to(
                    master.tags,
                    overwrite=overwrite,
                    source_tag_refs=source_tag_refs,
                    ignore_master=ignore_master,
                    selector=selector,
                )
                updates.update(extra_updates)
                conflicts.update(extra_conflicts)
            return updates, conflicts

    def _merge_to(
        self,
        to_tags,
        source_tag_refs,
        overwrite=False,
        selector=None,
        ignore_master=False,
    ):
        unpeeled_map = defaultdict(set)
        conflicts = []
        updates = {}
        result = dict(to_tags.get_tag_dict())
        for _ref_name, tag_name, peeled, unpeeled in source_tag_refs:
            if selector and not selector(tag_name):
                continue
            if unpeeled is not None:
                unpeeled_map[peeled].add(unpeeled)
            try:
                bzr_revid = self.source.branch.lookup_foreign_revision_id(peeled)
            except NotCommitError:
                continue
            if result.get(tag_name) == bzr_revid:
                pass
            elif tag_name not in result or overwrite:
                result[tag_name] = bzr_revid
                updates[tag_name] = bzr_revid
            else:
                conflicts.append((tag_name, bzr_revid, result[tag_name]))
        to_tags._set_tag_dict(result)
        if len(unpeeled_map) > 0:
            map_file = UnpeelMap.from_repository(to_tags.branch.repository)
            map_file.update(unpeeled_map)
            map_file.save_in_repository(to_tags.branch.repository)
        return updates, set(conflicts)


InterTags.register_optimiser(InterTagsFromGitToRemoteGit)
InterTags.register_optimiser(InterTagsFromGitToLocalGit)
InterTags.register_optimiser(InterTagsFromGitToNonGit)


class GitTags(Tags):
    """Ref-based tag dictionary."""

    def __init__(self, branch):
        self.branch = branch
        self.repository = branch.repository

    def get_tag_dict(self):
        ret = {}
        for _ref_name, tag_name, peeled, _unpeeled in self.branch.get_tag_refs():
            try:
                bzr_revid = self.branch.lookup_foreign_revision_id(peeled)
            except NotCommitError:
                continue
            else:
                ret[tag_name] = bzr_revid
        return ret

    def lookup_tag(self, tag_name):
        """Return the referent string of a tag."""
        # TODO(jelmer): Replace with something more efficient for local tags.
        td = self.get_tag_dict()
        try:
            return td[tag_name]
        except KeyError:
            raise errors.NoSuchTag(tag_name)


class LocalGitTagDict(GitTags):
    """Dictionary with tags in a local repository."""

    def __init__(self, branch):
        super().__init__(branch)
        self.refs = self.repository.controldir._git.refs

    def _set_tag_dict(self, to_dict):
        extra = set(self.refs.allkeys())
        for k, revid in to_dict.items():
            name = tag_name_to_ref(k)
            if name in extra:
                extra.remove(name)
            try:
                self.set_tag(k, revid)
            except errors.GhostTagsNotSupported:
                pass
        for name in extra:
            if is_tag(name):
                del self.repository._git[name]

    def set_tag(self, name, revid):
        try:
            git_sha, mapping = self.branch.lookup_bzr_revision_id(revid)
        except errors.NoSuchRevision:
            raise errors.GhostTagsNotSupported(self)
        self.refs[tag_name_to_ref(name)] = git_sha
        self.branch._tag_refs = None

    def delete_tag(self, name):
        ref = tag_name_to_ref(name)
        if ref not in self.refs:
            raise errors.NoSuchTag(name)
        del self.refs[ref]
        self.branch._tag_refs = None


class GitBranchFormat(branch.BranchFormat):
    def network_name(self):
        return b"git"

    def supports_tags(self):
        return True

    def supports_leaving_lock(self):
        return False

    def supports_tags_referencing_ghosts(self):
        return False

    def tags_are_versioned(self):
        return False

    def get_foreign_tests_branch_factory(self):
        from .tests.test_branch import ForeignTestsBranchFactory

        return ForeignTestsBranchFactory()

    def make_tags(self, branch):
        try:
            return branch.tags
        except AttributeError:
            pass
        if getattr(branch.repository, "_git", None) is None:
            from .remote import RemoteGitTagDict

            return RemoteGitTagDict(branch)
        else:
            return LocalGitTagDict(branch)

    def initialize(
        self, a_controldir, name=None, repository=None, append_revisions_only=None
    ):
        raise NotImplementedError(self.initialize)

    def get_reference(self, controldir, name=None):
        return controldir.get_branch_reference(name=name)

    def set_reference(self, controldir, name, target):
        return controldir.set_branch_reference(target, name)

    def stores_revno(self):
        """True if this branch format store revision numbers."""
        return False

    supports_reference_locations = False


class LocalGitBranchFormat(GitBranchFormat):
    def get_format_description(self):
        return "Local Git Branch"

    @property
    def _matchingcontroldir(self):
        from .dir import LocalGitControlDirFormat

        return LocalGitControlDirFormat()

    def initialize(
        self, a_controldir, name=None, repository=None, append_revisions_only=None
    ):
        from .dir import LocalGitDir

        if not isinstance(a_controldir, LocalGitDir):
            raise errors.IncompatibleFormat(self, a_controldir._format)
        return a_controldir.create_branch(
            repository=repository,
            name=name,
            append_revisions_only=append_revisions_only,
        )


class GitBranch(ForeignBranch):
    """An adapter to git repositories for bzr Branch objects."""

    @property
    def control_transport(self):
        return self._control_transport

    @property
    def user_transport(self):
        return self._user_transport

    def __init__(self, controldir, repository, ref: bytes, format):
        self.repository = repository
        self._format = format
        self.controldir = controldir
        self._lock_mode = None
        self._lock_count = 0
        super().__init__(repository.get_mapping())
        if not isinstance(ref, bytes):
            raise TypeError("ref is invalid: {!r}".format(ref))
        self.ref = ref
        self._head = None
        self._user_transport = controldir.user_transport.clone(".")
        self._control_transport = controldir.control_transport.clone(".")
        self._tag_refs = None
        params: dict[str, str] = {}
        try:
            self.name = ref_to_branch_name(ref)
        except ValueError:
            self.name = None
            if self.ref is not None:
                params = {"ref": urlutils.escape(self.ref, safe="")}
        else:
            if self.name:
                params = {"branch": urlutils.escape(self.name, safe="")}
        for k, v in params.items():
            self._user_transport.set_segment_parameter(k, v)
            self._control_transport.set_segment_parameter(k, v)
        self.base = controldir.user_transport.base

    def _get_checkout_format(self, lightweight=False):
        """Return the most suitable metadir for a checkout of this branch.
        Weaves are used if this branch's repository uses weaves.
        """
        if lightweight:
            return controldir.format_registry.make_controldir("git")
        else:
            return controldir.format_registry.make_controldir("default")

    def set_stacked_on_url(self, url):
        raise branch.UnstackableBranchFormat(self._format, self.base)

    def get_child_submit_format(self):
        """Return the preferred format of submissions to this branch."""
        ret = self.get_config_stack().get("child_submit_format")
        if ret is not None:
            return ret
        return "git"

    def get_config(self):
        from .config import GitBranchConfig

        return GitBranchConfig(self)

    def get_config_stack(self):
        from .config import GitBranchStack

        return GitBranchStack(self)

    def _get_nick(self, local=False, possible_master_transports=None):
        """Find the nick name for this branch.

        :return: Branch nick
        """
        if getattr(self.repository, "_git", None):
            cs = self.repository._git.get_config_stack()
            try:
                return cs.get((b"branch", self.name.encode("utf-8")), b"nick").decode(
                    "utf-8"
                )
            except KeyError:
                pass
        return self.name or "HEAD"

    def _set_nick(self, nick):
        cf = self.repository._git.get_config()
        cf.set((b"branch", self.name.encode("utf-8")), b"nick", nick.encode("utf-8"))
        f = BytesIO()
        cf.write_to_file(f)
        self.repository._git._put_named_file("config", f.getvalue())

    nick = property(_get_nick, _set_nick)

    def __repr__(self):
        return "<{}({!r}, {!r})>".format(
            self.__class__.__name__, self.repository.base, self.name
        )

    def set_last_revision(self, revid):
        raise NotImplementedError(self.set_last_revision)

    def generate_revision_history(self, revid, last_rev=None, other_branch=None):
        if last_rev is not None:
            graph = self.repository.get_graph()
            if not graph.is_ancestor(last_rev, revid):
                # our previous tip is not merged into stop_revision
                raise errors.DivergedBranches(self, other_branch)

        self.set_last_revision(revid)

    def lock_write(self, token=None):
        if token is not None:
            raise errors.TokenLockingNotSupported(self)
        if self._lock_mode:
            if self._lock_mode == "r":
                raise errors.ReadOnlyError(self)
            self._lock_count += 1
        else:
            self._lock_ref()
            self._lock_mode = "w"
            self._lock_count = 1
        self.repository.lock_write()
        return lock.LogicalLockResult(self.unlock)

    def leave_lock_in_place(self):
        raise NotImplementedError(self.leave_lock_in_place)

    def dont_leave_lock_in_place(self):
        raise NotImplementedError(self.dont_leave_lock_in_place)

    def get_stacked_on_url(self):
        # Git doesn't do stacking (yet...)
        raise branch.UnstackableBranchFormat(self._format, self.base)

    def _get_push_origin(self, cs):
        """Get the name for the push origin.

        The exact behaviour is documented in the git-config(1) manpage.
        """
        try:
            return cs.get((b"branch", self.name.encode("utf-8")), b"pushRemote")
        except KeyError:
            try:
                return cs.get((b"branch",), b"remote")
            except KeyError:
                try:
                    return cs.get((b"branch", self.name.encode("utf-8")), b"remote")
                except KeyError:
                    return b"origin"

    def _get_origin(self, cs):
        try:
            return cs.get((b"branch", self.name.encode("utf-8")), b"remote")
        except KeyError:
            return b"origin"

    def _get_related_push_branch(self, cs):
        remote = self._get_push_origin(cs)
        try:
            location = cs.get((b"remote", remote), b"url")
        except KeyError:
            return None

        return git_url_to_bzr_url(location.decode("utf-8"), ref=self.ref)

    def _get_related_merge_branch(self, cs):
        remote = self._get_origin(cs)
        try:
            location = cs.get((b"remote", remote), b"url")
        except KeyError:
            return None

        try:
            ref = cs.get((b"branch", remote), b"merge")
        except KeyError:
            ref = b"HEAD"

        return git_url_to_bzr_url(location.decode("utf-8"), ref=ref)

    def _get_parent_location(self):
        """See Branch.get_parent()."""
        cs = self.repository._git.get_config_stack()
        return self._get_related_merge_branch(cs)

    def set_parent(self, location):
        cs = self.repository._git.get_config()
        remote = self._get_origin(cs)
        this_url = urlutils.strip_segment_parameters(self.user_url)
        target_url, branch, ref = bzr_url_to_git_url(location)
        location = urlutils.relative_url(this_url, target_url)
        cs.set((b"remote", remote), b"url", location)
        cs.set(
            (b"remote", remote), b"fetch", b"+refs/heads/*:refs/remotes/%s/*" % remote
        )
        if self.name:
            if branch:
                cs.set(
                    (b"branch", self.name.encode()),
                    b"merge",
                    branch_name_to_ref(branch),
                )
            elif ref:
                cs.set((b"branch", self.name.encode()), b"merge", ref)
            else:
                # TODO(jelmer): Maybe unset rather than setting to HEAD?
                cs.set((b"branch", self.name.encode()), b"merge", b"HEAD")
        self.repository._write_git_config(cs)

    def break_lock(self):
        raise NotImplementedError(self.break_lock)

    def lock_read(self):
        if self._lock_mode:
            if self._lock_mode not in ("r", "w"):
                raise ValueError(self._lock_mode)
            self._lock_count += 1
        else:
            self._lock_mode = "r"
            self._lock_count = 1
        self.repository.lock_read()
        return lock.LogicalLockResult(self.unlock)

    def peek_lock_mode(self):
        return self._lock_mode

    def is_locked(self):
        return self._lock_mode is not None

    def _lock_ref(self):
        pass

    def _unlock_ref(self):
        pass

    def unlock(self):
        """See Branch.unlock()."""
        if self._lock_count == 0:
            raise errors.LockNotHeld(self)
        try:
            self._lock_count -= 1
            if self._lock_count == 0:
                if self._lock_mode == "w":
                    self._unlock_ref()
                self._lock_mode = None
                self._clear_cached_state()
        finally:
            self.repository.unlock()

    def get_physical_lock_status(self):
        return False

    def last_revision(self):
        with self.lock_read():
            # perhaps should escape this ?
            if self.head is None:
                return revision.NULL_REVISION
            return self.lookup_foreign_revision_id(self.head)

    def _basic_push(
        self, target, overwrite=False, stop_revision=None, tag_selector=None
    ):
        return branch.InterBranch.get(self, target)._basic_push(
            overwrite, stop_revision, tag_selector=tag_selector
        )

    def lookup_foreign_revision_id(self, foreign_revid):
        try:
            return self.repository.lookup_foreign_revision_id(
                foreign_revid, self.mapping
            )
        except KeyError:
            # Let's try..
            return self.mapping.revision_id_foreign_to_bzr(foreign_revid)

    def lookup_bzr_revision_id(self, revid):
        return self.repository.lookup_bzr_revision_id(revid, mapping=self.mapping)

    def get_unshelver(self, tree):
        raise errors.StoringUncommittedNotSupported(self)

    def _clear_cached_state(self):
        super()._clear_cached_state()
        self._tag_refs = None

    def _iter_tag_refs(self, refs):
        """Iterate over the tag refs.

        :param refs: Refs dictionary (name -> git sha1)
        :return: iterator over (ref_name, tag_name, peeled_sha1, unpeeled_sha1)
        """
        raise NotImplementedError(self._iter_tag_refs)

    def get_tag_refs(self):
        with self.lock_read():
            if self._tag_refs is None:
                self._tag_refs = list(self._iter_tag_refs())
            return self._tag_refs

    def import_last_revision_info_and_tags(self, source, revno, revid, lossy=False):
        """Set the last revision info, importing from another repo if necessary.

        This is used by the bound branch code to upload a revision to
        the master branch first before updating the tip of the local branch.
        Revisions referenced by source's tags are also transferred.

        :param source: Source branch to optionally fetch from
        :param revno: Revision number of the new tip
        :param revid: Revision id of the new tip
        :param lossy: Whether to discard metadata that can not be
            natively represented
        :return: Tuple with the new revision number and revision id
            (should only be different from the arguments when lossy=True)
        """
        push_result = source.push(
            self, stop_revision=revid, lossy=lossy, _stop_revno=revno
        )
        return (push_result.new_revno, push_result.new_revid)

    def reconcile(self, thorough=True):
        """Make sure the data stored in this branch is consistent."""
        from ..reconcile import ReconcileResult

        # Nothing to do here
        return ReconcileResult()


class LocalGitBranch(GitBranch):
    """A local Git branch."""

    def __init__(self, controldir, repository, ref):
        super().__init__(controldir, repository, ref, LocalGitBranchFormat())

    def create_checkout(
        self,
        to_location,
        revision_id=None,
        lightweight=False,
        accelerator_tree=None,
        hardlink=False,
    ):
        t = transport.get_transport(to_location)
        t.ensure_base()
        format = self._get_checkout_format(lightweight=lightweight)
        checkout = format.initialize_on_transport(t)
        if lightweight:
            from_branch = checkout.set_branch_reference(target_branch=self)
        else:
            policy = checkout.determine_repository_policy()
            policy.acquire_repository()
            checkout_branch = checkout.create_branch()
            checkout_branch.bind(self)
            checkout_branch.pull(self, stop_revision=revision_id)
            from_branch = None
        return checkout.create_workingtree(
            revision_id, from_branch=from_branch, hardlink=hardlink
        )

    def _lock_ref(self):
        self._ref_lock = self.repository._git.refs.lock_ref(self.ref)

    def _unlock_ref(self):
        self._ref_lock.unlock()

    def break_lock(self):
        self.repository._git.refs.unlock_ref(self.ref)

    def _gen_revision_history(self):
        if self.head is None:
            return []
        last_revid = self.last_revision()
        graph = self.repository.get_graph()
        try:
            ret = list(
                graph.iter_lefthand_ancestry(last_revid, (revision.NULL_REVISION,))
            )
        except errors.RevisionNotPresent as e:
            raise errors.GhostRevisionsHaveNoRevno(last_revid, e.revision_id)
        ret.reverse()
        return ret

    def _get_head(self):
        try:
            return self.repository._git.refs[self.ref]
        except KeyError:
            return None

    def _read_last_revision_info(self):
        last_revid = self.last_revision()
        graph = self.repository.get_graph()
        try:
            revno = graph.find_distance_to_null(
                last_revid, [(revision.NULL_REVISION, 0)]
            )
        except errors.GhostRevisionsHaveNoRevno:
            revno = None
        return revno, last_revid

    def set_last_revision_info(self, revno, revision_id):
        self.set_last_revision(revision_id)
        self._last_revision_info_cache = revno, revision_id

    def set_last_revision(self, revid):
        if not revid or not isinstance(revid, bytes):
            raise errors.InvalidRevisionId(revision_id=revid, branch=self)
        if revid == NULL_REVISION:
            newhead = None
        else:
            (newhead, self.mapping) = self.repository.lookup_bzr_revision_id(revid)
            if self.mapping is None:
                raise AssertionError
        self._set_head(newhead)

    def _set_head(self, value):
        if value == ZERO_SHA:
            raise ValueError(value)
        self._head = value
        if value is None:
            del self.repository._git.refs[self.ref]
        else:
            self.repository._git.refs[self.ref] = self._head
        self._clear_cached_state()

    head = property(_get_head, _set_head)

    def get_push_location(self):
        """See Branch.get_push_location."""
        push_loc = self.get_config_stack().get("push_location")
        if push_loc is not None:
            return push_loc
        cs = self.repository._git.get_config_stack()
        return self._get_related_push_branch(cs)

    def set_push_location(self, location):
        """See Branch.set_push_location."""
        self.get_config().set_user_option(
            "push_location", location, store=config.STORE_LOCATION
        )

    def supports_tags(self):
        return True

    def store_uncommitted(self, creator):
        raise errors.StoringUncommittedNotSupported(self)

    def _iter_tag_refs(self):
        """Iterate over the tag refs.

        :param refs: Refs dictionary (name -> git sha1)
        :return: iterator over (ref_name, tag_name, peeled_sha1, unpeeled_sha1)
        """
        refs = self.repository.controldir.get_refs_container()
        for ref_name, unpeeled in refs.as_dict().items():
            try:
                tag_name = ref_to_tag_name(ref_name)
            except (ValueError, UnicodeDecodeError):
                continue
            peeled = refs.get_peeled(ref_name)
            if peeled is None:
                peeled = unpeeled
            if not isinstance(tag_name, str):
                raise TypeError(tag_name)
            yield (ref_name, tag_name, peeled, unpeeled)

    def create_memorytree(self):
        from .memorytree import GitMemoryTree

        return GitMemoryTree(self, self.repository._git.object_store, self.head)


def _quick_lookup_revno(local_branch, remote_branch, revid):
    if not isinstance(revid, bytes):
        raise TypeError(revid)
    # Try in source branch first, it'll be faster
    with local_branch.lock_read():
        if not _calculate_revnos(local_branch):
            return None
        try:
            return local_branch.revision_id_to_revno(revid)
        except errors.NoSuchRevision:
            graph = local_branch.repository.get_graph()
            try:
                return graph.find_distance_to_null(revid, [(revision.NULL_REVISION, 0)])
            except errors.GhostRevisionsHaveNoRevno:
                if not _calculate_revnos(remote_branch):
                    return None
                # FIXME: Check using graph.find_distance_to_null() ?
                with remote_branch.lock_read():
                    return remote_branch.revision_id_to_revno(revid)


class GitBranchPullResult(branch.PullResult):
    def __init__(self):
        super().__init__()
        self.new_git_head = None
        self._old_revno = None
        self._new_revno = None

    def report(self, to_file):
        if not is_quiet():
            if self.old_revid == self.new_revid:
                to_file.write("No revisions to pull.\n")
            elif self.new_git_head is not None:
                to_file.write(
                    f"Now on revision {self.new_revno} (git sha: {self.new_git_head}).\n"
                )
            else:
                to_file.write(f"Now on revision {self.new_revno}.\n")
        self._show_tag_conficts(to_file)

    def _lookup_revno(self, revid):
        return _quick_lookup_revno(self.target_branch, self.source_branch, revid)

    def _get_old_revno(self):
        if self._old_revno is not None:
            return self._old_revno
        return self._lookup_revno(self.old_revid)

    def _set_old_revno(self, revno):
        self._old_revno = revno

    old_revno = property(_get_old_revno, _set_old_revno)

    def _get_new_revno(self):
        if self._new_revno is not None:
            return self._new_revno
        return self._lookup_revno(self.new_revid)

    def _set_new_revno(self, revno):
        self._new_revno = revno

    new_revno = property(_get_new_revno, _set_new_revno)


class GitBranchPushResult(branch.BranchPushResult):
    def _lookup_revno(self, revid):
        return _quick_lookup_revno(self.source_branch, self.target_branch, revid)

    @property
    def old_revno(self):
        return self._lookup_revno(self.old_revid)

    @property
    def new_revno(self):
        new_original_revno = getattr(self, "new_original_revno", None)
        if new_original_revno:
            return new_original_revno
        if getattr(self, "new_original_revid", None) is not None:
            return self._lookup_revno(self.new_original_revid)
        return self._lookup_revno(self.new_revid)


class InterFromGitBranch(branch.GenericInterBranch):
    """InterBranch implementation that pulls from Git into bzr."""

    @staticmethod
    def _get_branch_formats_to_test():
        try:
            default_format = branch.format_registry.get_default()
        except AttributeError:
            default_format = branch.BranchFormat._default_format
        from .remote import RemoteGitBranchFormat

        return [
            (RemoteGitBranchFormat(), default_format),
            (LocalGitBranchFormat(), default_format),
        ]

    @classmethod
    def _get_interrepo(self, source, target):
        return _mod_repository.InterRepository.get(source.repository, target.repository)

    @classmethod
    def is_compatible(cls, source, target):
        if not isinstance(source, GitBranch):
            return False
        if isinstance(target, GitBranch):
            # InterLocalGitRemoteGitBranch or InterToGitBranch should be used
            return False
        if getattr(cls._get_interrepo(source, target), "fetch_objects", None) is None:  # noqa: SIM103
            # fetch_objects is necessary for this to work
            return False
        return True

    def fetch(self, stop_revision=None, fetch_tags=None, limit=None, lossy=False):
        self.fetch_objects(
            stop_revision, fetch_tags=fetch_tags, limit=limit, lossy=lossy
        )
        return _mod_repository.FetchResult()

    def fetch_objects(
        self, stop_revision, fetch_tags, limit=None, lossy=False, tag_selector=None
    ):
        interrepo = self._get_interrepo(self.source, self.target)
        if fetch_tags is None:
            c = self.source.get_config_stack()
            fetch_tags = c.get("branch.fetch_tags")

        def determine_wants(heads, depth=None):
            if stop_revision is None:
                try:
                    head = heads[self.source.ref]
                except KeyError:
                    self._last_revid = revision.NULL_REVISION
                else:
                    self._last_revid = self.source.lookup_foreign_revision_id(head)
            else:
                self._last_revid = stop_revision
            real = interrepo.get_determine_wants_revids(
                [self._last_revid], include_tags=fetch_tags, tag_selector=tag_selector
            )
            return real(heads)

        pack_hint, head, refs = interrepo.fetch_objects(
            determine_wants, self.source.mapping, limit=limit, lossy=lossy
        )
        if pack_hint is not None and self.target.repository._format.pack_compresses:
            self.target.repository.pack(hint=pack_hint)
        return head, refs

    def _update_revisions(self, stop_revision=None, overwrite=False, tag_selector=None):
        head, refs = self.fetch_objects(
            stop_revision, fetch_tags=None, tag_selector=tag_selector
        )
        _update_tip(self.source, self.target, self._last_revid, overwrite)
        return head, refs

    def update_references(self, revid=None):
        if revid is None:
            revid = self.target.last_revision()
        tree = self.target.repository.revision_tree(revid)
        try:
            with tree.get_file(".gitmodules") as f:
                for path, url, _section in parse_submodules(GitConfigFile.from_file(f)):
                    self.target.set_reference_info(
                        tree.path2id(decode_git_path(path)),
                        url.decode("utf-8"),
                        decode_git_path(path),
                    )
        except transport.NoSuchFile:
            pass

    def _basic_pull(
        self,
        stop_revision,
        overwrite,
        run_hooks,
        _override_hook_target,
        _hook_master,
        tag_selector=None,
    ):
        if overwrite is True:
            overwrite = {"history", "tags"}
        elif not overwrite:
            overwrite = set()
        result = GitBranchPullResult()
        result.source_branch = self.source
        if _override_hook_target is None:
            result.target_branch = self.target
        else:
            result.target_branch = _override_hook_target
        with self.target.lock_write(), self.source.lock_read():
            # We assume that during 'pull' the target repository is closer than
            # the source one.
            (result.old_revno, result.old_revid) = self.target.last_revision_info()
            result.new_git_head, remote_refs = self._update_revisions(
                stop_revision,
                overwrite=("history" in overwrite),
                tag_selector=tag_selector,
            )
            tags_ret = self.source.tags.merge_to(
                self.target.tags, ("tags" in overwrite), ignore_master=True
            )
            if isinstance(tags_ret, tuple):
                result.tag_updates, result.tag_conflicts = tags_ret
            else:
                result.tag_conflicts = tags_ret
            (result.new_revno, result.new_revid) = self.target.last_revision_info()
            self.update_references(revid=result.new_revid)
            if _hook_master:
                result.master_branch = _hook_master
                result.local_branch = result.target_branch
            else:
                result.master_branch = result.target_branch
                result.local_branch = None
            if run_hooks:
                for hook in branch.Branch.hooks["post_pull"]:
                    hook(result)
            return result

    def pull(
        self,
        overwrite=False,
        stop_revision=None,
        possible_transports=None,
        _hook_master=None,
        run_hooks=True,
        _override_hook_target=None,
        local=False,
        tag_selector=None,
    ):
        """See Branch.pull.

        :param _hook_master: Private parameter - set the branch to
            be supplied as the master to pull hooks.
        :param run_hooks: Private parameter - if false, this branch
            is being called because it's the master of the primary branch,
            so it should not run its hooks.
        :param _override_hook_target: Private parameter - set the branch to be
            supplied as the target_branch to pull hooks.
        """
        # This type of branch can't be bound.
        bound_location = self.target.get_bound_location()
        if local and not bound_location:
            raise errors.LocalRequiresBoundBranch()
        source_is_master = False
        with contextlib.ExitStack() as es:
            es.enter_context(self.source.lock_read())
            if bound_location:
                # bound_location comes from a config file, some care has to be
                # taken to relate it to source.user_url
                normalized = urlutils.normalize_url(bound_location)
                try:
                    relpath = self.source.user_transport.relpath(normalized)
                    source_is_master = relpath == ""
                except (errors.PathNotChild, urlutils.InvalidURL):
                    source_is_master = False
            if not local and bound_location and not source_is_master:
                # not pulling from master, so we need to update master.
                master_branch = self.target.get_master_branch(possible_transports)
                es.enter_context(master_branch.lock_write())
                # pull from source into master.
                master_branch.pull(
                    self.source,
                    overwrite=overwrite,
                    stop_revision=stop_revision,
                    run_hooks=False,
                )
            else:
                master_branch = None
            return self._basic_pull(
                stop_revision,
                overwrite,
                run_hooks,
                _override_hook_target,
                _hook_master=master_branch,
                tag_selector=tag_selector,
            )

    def _basic_push(self, overwrite, stop_revision, tag_selector=None):
        if overwrite is True:
            overwrite = {"history", "tags"}
        elif not overwrite:
            overwrite = set()
        result = branch.BranchPushResult()
        result.source_branch = self.source
        result.target_branch = self.target
        result.old_revno, result.old_revid = self.target.last_revision_info()
        result.new_git_head, remote_refs = self._update_revisions(
            stop_revision, overwrite=("history" in overwrite), tag_selector=tag_selector
        )
        tags_ret = self.source.tags.merge_to(
            self.target.tags,
            "tags" in overwrite,
            ignore_master=True,
            selector=tag_selector,
        )
        (result.tag_updates, result.tag_conflicts) = tags_ret
        result.new_revno, result.new_revid = self.target.last_revision_info()
        self.update_references(revid=result.new_revid)
        return result


class InterGitBranch(branch.GenericInterBranch):
    """InterBranch implementation that pulls between Git branches."""

    def fetch(self, stop_revision=None, fetch_tags=None, limit=None, lossy=False):
        raise NotImplementedError(self.fetch)


class InterLocalGitRemoteGitBranch(InterGitBranch):
    """InterBranch that copies from a local to a remote git branch."""

    @staticmethod
    def _get_branch_formats_to_test():
        from .remote import RemoteGitBranchFormat

        return [(LocalGitBranchFormat(), RemoteGitBranchFormat())]

    @classmethod
    def is_compatible(self, source, target):
        from .remote import RemoteGitBranch

        return isinstance(source, LocalGitBranch) and isinstance(
            target, RemoteGitBranch
        )

    def _basic_push(self, overwrite, stop_revision, tag_selector=None):
        from .remote import parse_git_error

        result = GitBranchPushResult()
        result.source_branch = self.source
        result.target_branch = self.target
        if stop_revision is None:
            stop_revision = self.source.last_revision()

        def get_changed_refs(old_refs):
            old_ref = old_refs.get(self.target.ref, None)
            if old_ref is None:
                result.old_revid = revision.NULL_REVISION
            else:
                result.old_revid = self.target.lookup_foreign_revision_id(old_ref)
            new_ref = self.source.repository.lookup_bzr_revision_id(stop_revision)[0]
            if not overwrite:
                if remote_divergence(
                    old_ref, new_ref, self.source.repository._git.object_store
                ):
                    raise errors.DivergedBranches(self.source, self.target)
            refs = {self.target.ref: new_ref}
            result.new_revid = stop_revision
            for name, sha in self.source.repository._git.refs.as_dict(
                b"refs/tags"
            ).items():
                if tag_selector and not tag_selector(name.decode("utf-8")):
                    continue
                if sha not in self.source.repository._git:
                    trace.mutter("Ignoring missing SHA: %s", sha)
                    continue
                refs[tag_name_to_ref(name)] = sha
            return refs

        dw_result = self.target.repository.send_pack(
            get_changed_refs, self.source.repository._git.generate_pack_data
        )
        if dw_result is not None and not isinstance(dw_result, dict):
            error = dw_result.ref_status.get(self.target.ref)
            if error:
                raise parse_git_error(self.target.user_url, error)
            for ref, error in dw_result.ref_status.items():
                if error:
                    trace.warning("unable to open ref %s: %s", ref, error)
        return result


class InterGitLocalGitBranch(InterGitBranch):
    """InterBranch that copies from a remote to a local git branch."""

    @staticmethod
    def _get_branch_formats_to_test():
        from .remote import RemoteGitBranchFormat

        return [
            (RemoteGitBranchFormat(), LocalGitBranchFormat()),
            (LocalGitBranchFormat(), LocalGitBranchFormat()),
        ]

    @classmethod
    def is_compatible(self, source, target):
        return isinstance(source, GitBranch) and isinstance(target, LocalGitBranch)

    def fetch(self, stop_revision=None, fetch_tags=None, limit=None, lossy=False):
        if lossy:
            raise errors.LossyPushToSameVCS(
                source_branch=self.source, target_branch=self.target
            )
        interrepo = _mod_repository.InterRepository.get(
            self.source.repository, self.target.repository
        )
        if stop_revision is None:
            stop_revision = self.source.last_revision()
        if fetch_tags is None:
            c = self.source.get_config_stack()
            fetch_tags = c.get("branch.fetch_tags")
        determine_wants = interrepo.get_determine_wants_revids(
            [stop_revision], include_tags=fetch_tags
        )
        interrepo.fetch_objects(determine_wants, limit=limit)
        return _mod_repository.FetchResult()

    def _basic_push(self, overwrite=False, stop_revision=None, tag_selector=None):
        if overwrite is True:
            overwrite = {"history", "tags"}
        elif not overwrite:
            overwrite = set()
        result = GitBranchPushResult()
        result.source_branch = self.source
        result.target_branch = self.target
        result.old_revid = self.target.last_revision()
        refs, stop_revision = self.update_refs(stop_revision)
        _update_tip(self.source, self.target, stop_revision, "history" in overwrite)
        tags_ret = self.source.tags.merge_to(
            self.target.tags, overwrite=("tags" in overwrite), selector=tag_selector
        )
        if isinstance(tags_ret, tuple):
            (result.tag_updates, result.tag_conflicts) = tags_ret
        else:
            result.tag_conflicts = tags_ret
        result.new_revid = self.target.last_revision()
        return result

    def update_refs(self, stop_revision=None):
        interrepo = _mod_repository.InterRepository.get(
            self.source.repository, self.target.repository
        )
        c = self.source.get_config_stack()
        fetch_tags = c.get("branch.fetch_tags")
        # Default to True for local operations to match remote behavior
        if fetch_tags is None:
            fetch_tags = True

        if stop_revision is None:
            result = interrepo.fetch(
                branches=[self.source.ref], include_tags=fetch_tags
            )
            try:
                head = result.refs[self.source.ref]
            except KeyError:
                stop_revision = revision.NULL_REVISION
            else:
                stop_revision = self.target.lookup_foreign_revision_id(head)
        else:
            result = interrepo.fetch(revision_id=stop_revision, include_tags=fetch_tags)
        return result.refs, stop_revision

    def pull(
        self,
        stop_revision=None,
        overwrite=False,
        possible_transports=None,
        run_hooks=True,
        local=False,
        tag_selector=None,
    ):
        # This type of branch can't be bound.
        if local:
            raise errors.LocalRequiresBoundBranch()
        if overwrite is True:
            overwrite = {"history", "tags"}
        elif not overwrite:
            overwrite = set()

        result = GitPullResult()
        result.source_branch = self.source
        result.target_branch = self.target
        with self.target.lock_write(), self.source.lock_read():
            result.old_revid = self.target.last_revision()
            refs, stop_revision = self.update_refs(stop_revision)
            _update_tip(self.source, self.target, stop_revision, "history" in overwrite)
            tags_ret = self.source.tags.merge_to(
                self.target.tags, overwrite=("tags" in overwrite), selector=tag_selector
            )
            if isinstance(tags_ret, tuple):
                (result.tag_updates, result.tag_conflicts) = tags_ret
            else:
                result.tag_conflicts = tags_ret
            result.new_revid = self.target.last_revision()
            result.local_branch = None
            result.master_branch = result.target_branch
            if run_hooks:
                for hook in branch.Branch.hooks["post_pull"]:
                    hook(result)
        return result


def _update_pure_git_refs(result, new_refs, overwrite, tag_selector, old_refs):
    result.tag_updates = {}
    result.tag_conflicts = []
    ret = {}

    def ref_equals(refs, name, git_sha, revid):
        try:
            value = refs[name]
        except KeyError:
            return False
        if value[0] is not None and git_sha is not None:
            return value[0] == git_sha
        if value[1] is not None and revid is not None:
            return value[1] == revid

        # FIXME: If one side only has the git sha available and the other only
        # has the bzr revid, then this will cause us to show a tag as updated
        # that hasn't actually been updated.
        return False

    # FIXME: Check for diverged branches
    for ref, (git_sha, revid) in new_refs.items():
        if ref_equals(ret, ref, git_sha, revid):
            # Already up to date
            if git_sha is None:
                git_sha = old_refs[ref][0]
            if revid is None:
                revid = old_refs[ref][1]
            ret[ref] = new_refs[ref] = (git_sha, revid)
        elif ref not in ret or overwrite:
            try:
                tag_name = ref_to_tag_name(ref)
            except ValueError:
                pass
            else:
                if tag_selector and not tag_selector(tag_name):
                    continue
                result.tag_updates[tag_name] = revid
            ret[ref] = (git_sha, revid)
        else:
            # FIXME: Check diverged
            diverged = False
            if diverged:
                try:
                    name = ref_to_tag_name(ref)
                except ValueError:
                    pass
                else:
                    result.tag_conflicts.append((name, revid, ret[name][1]))
            else:
                ret[ref] = (git_sha, revid)
    return ret


class InterToGitBranch(branch.GenericInterBranch):
    """InterBranch implementation that pulls into a Git branch."""

    def __init__(self, source, target):
        super().__init__(source, target)
        self.interrepo = _mod_repository.InterRepository.get(
            source.repository, target.repository
        )

    @staticmethod
    def _get_branch_formats_to_test():
        try:
            default_format = branch.format_registry.get_default()
        except AttributeError:
            default_format = branch.BranchFormat._default_format
        from .remote import RemoteGitBranchFormat

        return [
            (default_format, LocalGitBranchFormat()),
            (default_format, RemoteGitBranchFormat()),
        ]

    @classmethod
    def is_compatible(self, source, target):
        return not isinstance(source, GitBranch) and isinstance(target, GitBranch)

    def _get_new_refs(self, stop_revision=None, fetch_tags=None, stop_revno=None):
        if not self.source.is_locked():
            raise errors.ObjectNotLocked(self.source)
        if stop_revision is None:
            (stop_revno, stop_revision) = self.source.last_revision_info()
        elif stop_revno is None:
            try:
                stop_revno = self.source.revision_id_to_revno(stop_revision)
            except errors.NoSuchRevision:
                stop_revno = None
        if not isinstance(stop_revision, bytes):
            raise TypeError(stop_revision)
        main_ref = self.target.ref
        refs = {main_ref: (None, stop_revision)}
        if fetch_tags is None:
            # First check branch-specific config
            branch_config = self.source.get_config()
            branch_val = branch_config.get_user_option("branch.fetch_tags")
            if branch_val is not None:
                # Convert string value to boolean using the standard converter
                from .. import ui

                fetch_tags = ui.bool_from_string(branch_val)
            else:
                # Fall back to config stack for global/default settings
                c = self.source.get_config_stack()
                fetch_tags = c.get("branch.fetch_tags")
        # For local pushes, respect the breezy configuration default
        if fetch_tags is None:
            fetch_tags = True
        for name, revid in self.source.tags.get_tag_dict().items():
            if self.source.repository.has_revision(revid):
                ref = tag_name_to_ref(name)
                if not check_ref_format(ref):
                    warning("skipping tag with invalid characters %s (%s)", name, ref)
                    continue
                if fetch_tags:
                    # FIXME: Skip tags that are not in the ancestry
                    refs[ref] = (None, revid)
        return refs, main_ref, (stop_revno, stop_revision)

    def fetch(self, stop_revision=None, fetch_tags=None, lossy=False, limit=None):
        if stop_revision is None:
            stop_revision = self.source.last_revision()
        # Default to True for local fetches to match remote behavior
        if fetch_tags is None:
            c = self.source.get_config_stack()
            fetch_tags = c.get("branch.fetch_tags")
            if fetch_tags is None:
                fetch_tags = True
        ret = []
        if fetch_tags:
            for _k, v in self.source.tags.get_tag_dict().items():
                ret.append((None, v))
        ret.append((None, stop_revision))
        if getattr(self.interrepo, "fetch_revs", None):
            try:
                revidmap = self.interrepo.fetch_revs(ret, lossy=lossy, limit=limit)
            except NoPushSupport:
                raise errors.NoRoundtrippingSupport(self.source, self.target)
            return _mod_repository.FetchResult(
                revidmap={
                    old_revid: new_revid
                    for (old_revid, (new_sha, new_revid)) in revidmap.items()
                }
            )
        else:

            def determine_wants(refs, depth=None):
                wants = []
                for git_sha, revid in ret:
                    if git_sha is None:
                        git_sha, mapping = self.target.lookup_bzr_revision_id(revid)
                    wants.append(git_sha)
                return wants

            self.interrepo.fetch_objects(determine_wants, lossy=lossy, limit=limit)
            return _mod_repository.FetchResult()

    def pull(
        self,
        overwrite=False,
        stop_revision=None,
        local=False,
        possible_transports=None,
        run_hooks=True,
        _stop_revno=None,
        tag_selector=None,
    ):
        result = GitBranchPullResult()
        result.source_branch = self.source
        result.target_branch = self.target
        with self.source.lock_read(), self.target.lock_write():
            new_refs, main_ref, stop_revinfo = self._get_new_refs(
                stop_revision, stop_revno=_stop_revno
            )

            update_refs = partial(
                _update_pure_git_refs, result, new_refs, overwrite, tag_selector
            )
            try:
                result.revidmap, old_refs, new_refs = self.interrepo.fetch_refs(
                    update_refs, lossy=False
                )
            except NoPushSupport:
                raise errors.NoRoundtrippingSupport(self.source, self.target)
            (old_sha1, result.old_revid) = old_refs.get(
                main_ref, (ZERO_SHA, NULL_REVISION)
            )
            if result.old_revid is None:
                result.old_revid = self.target.lookup_foreign_revision_id(old_sha1)
            result.new_revid = new_refs[main_ref][1]
            result.local_branch = None
            result.master_branch = self.target
            if run_hooks:
                for hook in branch.Branch.hooks["post_pull"]:
                    hook(result)
        return result

    def push(
        self,
        overwrite=False,
        stop_revision=None,
        lossy=False,
        _override_hook_source_branch=None,
        _stop_revno=None,
        tag_selector=None,
    ):
        result = GitBranchPushResult()
        result.source_branch = self.source
        result.target_branch = self.target
        result.local_branch = None
        result.master_branch = result.target_branch
        with self.source.lock_read(), self.target.lock_write():
            new_refs, main_ref, stop_revinfo = self._get_new_refs(
                stop_revision, stop_revno=_stop_revno
            )

            update_refs = partial(
                _update_pure_git_refs, result, new_refs, overwrite, tag_selector
            )
            try:
                result.revidmap, old_refs, new_refs = self.interrepo.fetch_refs(
                    update_refs, lossy=lossy, overwrite=overwrite
                )
            except NoPushSupport:
                raise errors.NoRoundtrippingSupport(self.source, self.target)
            (old_sha1, result.old_revid) = old_refs.get(
                main_ref, (ZERO_SHA, NULL_REVISION)
            )
            if lossy or result.old_revid is None:
                result.old_revid = self.target.lookup_foreign_revision_id(old_sha1)
            result.new_revid = new_refs[main_ref][1]
            (result.new_original_revno, result.new_original_revid) = stop_revinfo
            for hook in branch.Branch.hooks["post_push"]:
                hook(result)
        return result


branch.InterBranch.register_optimiser(InterGitLocalGitBranch)
branch.InterBranch.register_optimiser(InterFromGitBranch)
branch.InterBranch.register_optimiser(InterToGitBranch)
branch.InterBranch.register_optimiser(InterLocalGitRemoteGitBranch)
