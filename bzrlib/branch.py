# Copyright (C) 2005, 2006, 2007 Canonical Ltd
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


from cStringIO import StringIO

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
from copy import deepcopy
from unittest import TestSuite
from warnings import warn

import bzrlib
from bzrlib import (
        bzrdir,
        cache_utf8,
        config as _mod_config,
        errors,
        lockdir,
        lockable_files,
        osutils,
        revision as _mod_revision,
        transport,
        tree,
        ui,
        urlutils,
        )
from bzrlib.config import BranchConfig, TreeConfig
from bzrlib.lockable_files import LockableFiles, TransportLock
from bzrlib.tag import (
    BasicTags,
    DisabledTags,
    )
""")

from bzrlib.decorators import needs_read_lock, needs_write_lock
from bzrlib.errors import (BzrError, BzrCheckError, DivergedBranches,
                           HistoryMissing, InvalidRevisionId,
                           InvalidRevisionNumber, LockError, NoSuchFile,
                           NoSuchRevision, NoWorkingTree, NotVersionedError,
                           NotBranchError, UninitializableFormat,
                           UnlistableStore, UnlistableBranch,
                           )
from bzrlib.symbol_versioning import (deprecated_function,
                                      deprecated_method,
                                      DEPRECATED_PARAMETER,
                                      deprecated_passed,
                                      zero_eight, zero_nine,
                                      )
from bzrlib.trace import mutter, note


BZR_BRANCH_FORMAT_4 = "Bazaar-NG branch, format 0.0.4\n"
BZR_BRANCH_FORMAT_5 = "Bazaar-NG branch, format 5\n"
BZR_BRANCH_FORMAT_6 = "Bazaar Branch Format 6 (bzr 0.15)\n"


# TODO: Maybe include checks for common corruption of newlines, etc?

# TODO: Some operations like log might retrieve the same revisions
# repeatedly to calculate deltas.  We could perhaps have a weakref
# cache in memory to make this faster.  In general anything can be
# cached in memory between lock and unlock operations. .. nb thats
# what the transaction identity map provides


######################################################################
# branch objects

class Branch(object):
    """Branch holding a history of revisions.

    base
        Base directory/url of the branch.

    hooks: An instance of BranchHooks.
    """
    # this is really an instance variable - FIXME move it there
    # - RBC 20060112
    base = None

    # override this to set the strategy for storing tags
    def _make_tags(self):
        return DisabledTags(self)

    def __init__(self, *ignored, **ignored_too):
        self.tags = self._make_tags()

    def break_lock(self):
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

    @staticmethod
    @deprecated_method(zero_eight)
    def open_downlevel(base):
        """Open a branch which may be of an old format."""
        return Branch.open(base, _unsupported=True)
        
    @staticmethod
    def open(base, _unsupported=False):
        """Open the branch rooted at base.

        For instance, if the branch is at URL/.bzr/branch,
        Branch.open(URL) -> a Branch instance.
        """
        control = bzrdir.BzrDir.open(base, _unsupported)
        return control.open_branch(_unsupported)

    @staticmethod
    def open_containing(url):
        """Open an existing branch which contains url.
        
        This probes for a branch at url, and searches upwards from there.

        Basically we keep looking up until we find the control directory or
        run into the root.  If there isn't one, raises NotBranchError.
        If there is one and it is either an unrecognised format or an unsupported 
        format, UnknownFormatError or UnsupportedFormatError are raised.
        If there is one, it is returned, along with the unused portion of url.
        """
        control, relpath = bzrdir.BzrDir.open_containing(url)
        return control.open_branch(), relpath

    @staticmethod
    @deprecated_function(zero_eight)
    def initialize(base):
        """Create a new working tree and branch, rooted at 'base' (url)

        NOTE: This will soon be deprecated in favour of creation
        through a BzrDir.
        """
        return bzrdir.BzrDir.create_standalone_workingtree(base).branch

    @deprecated_function(zero_eight)
    def setup_caching(self, cache_root):
        """Subclasses that care about caching should override this, and set
        up cached stores located under cache_root.
        
        NOTE: This is unused.
        """
        pass

    def get_config(self):
        return BranchConfig(self)

    def _get_nick(self):
        return self.get_config().get_nickname()

    def _set_nick(self, nick):
        self.get_config().set_user_option('nickname', nick)

    nick = property(_get_nick, _set_nick)

    def is_locked(self):
        raise NotImplementedError(self.is_locked)

    def lock_write(self):
        raise NotImplementedError(self.lock_write)

    def lock_read(self):
        raise NotImplementedError(self.lock_read)

    def unlock(self):
        raise NotImplementedError(self.unlock)

    def peek_lock_mode(self):
        """Return lock mode for the Branch: 'r', 'w' or None"""
        raise NotImplementedError(self.peek_lock_mode)

    def get_physical_lock_status(self):
        raise NotImplementedError(self.get_physical_lock_status)

    def abspath(self, name):
        """Return absolute filename for something in the branch
        
        XXX: Robert Collins 20051017 what is this used for? why is it a branch
        method and not a tree method.
        """
        raise NotImplementedError(self.abspath)

    def bind(self, other):
        """Bind the local branch the other branch.

        :param other: The branch to bind to
        :type other: Branch
        """
        raise errors.UpgradeRequired(self.base)

    @needs_write_lock
    def fetch(self, from_branch, last_revision=None, pb=None):
        """Copy revisions from from_branch into this branch.

        :param from_branch: Where to copy from.
        :param last_revision: What revision to stop at (None for at the end
                              of the branch.
        :param pb: An optional progress bar to use.

        Returns the copied revision count and the failed revisions in a tuple:
        (copied, failures).
        """
        if self.base == from_branch.base:
            return (0, [])
        if pb is None:
            nested_pb = ui.ui_factory.nested_progress_bar()
            pb = nested_pb
        else:
            nested_pb = None

        from_branch.lock_read()
        try:
            if last_revision is None:
                pb.update('get source history')
                last_revision = from_branch.last_revision()
                if last_revision is None:
                    last_revision = _mod_revision.NULL_REVISION
            return self.repository.fetch(from_branch.repository,
                                         revision_id=last_revision,
                                         pb=nested_pb)
        finally:
            if nested_pb is not None:
                nested_pb.finished()
            from_branch.unlock()

    def get_bound_location(self):
        """Return the URL of the branch we are bound to.

        Older format branches cannot bind, please be sure to use a metadir
        branch.
        """
        return None
    
    def get_old_bound_location(self):
        """Return the URL of the branch we used to be bound to
        """
        raise errors.UpgradeRequired(self.base)

    def get_commit_builder(self, parents, config=None, timestamp=None, 
                           timezone=None, committer=None, revprops=None, 
                           revision_id=None):
        """Obtain a CommitBuilder for this branch.
        
        :param parents: Revision ids of the parents of the new revision.
        :param config: Optional configuration to use.
        :param timestamp: Optional timestamp recorded for commit.
        :param timezone: Optional timezone for timestamp.
        :param committer: Optional committer to set for commit.
        :param revprops: Optional dictionary of revision properties.
        :param revision_id: Optional revision id.
        """

        if config is None:
            config = self.get_config()
        
        return self.repository.get_commit_builder(self, parents, config,
            timestamp, timezone, committer, revprops, revision_id)

    def get_master_branch(self):
        """Return the branch we are bound to.
        
        :return: Either a Branch, or None
        """
        return None

    def get_revision_delta(self, revno):
        """Return the delta for one revision.

        The delta is relative to its mainline predecessor, or the
        empty tree for revision 1.
        """
        assert isinstance(revno, int)
        rh = self.revision_history()
        if not (1 <= revno <= len(rh)):
            raise InvalidRevisionNumber(revno)
        return self.repository.get_revision_delta(rh[revno-1])

    def get_root_id(self):
        """Return the id of this branches root"""
        raise NotImplementedError(self.get_root_id)

    def print_file(self, file, revision_id):
        """Print `file` to stdout."""
        raise NotImplementedError(self.print_file)

    def append_revision(self, *revision_ids):
        raise NotImplementedError(self.append_revision)

    def set_revision_history(self, rev_history):
        raise NotImplementedError(self.set_revision_history)

    def revision_history(self):
        """Return sequence of revision hashes on to this branch."""
        raise NotImplementedError(self.revision_history)

    def revno(self):
        """Return current revision number for this branch.

        That is equivalent to the number of revisions committed to
        this branch.
        """
        return len(self.revision_history())

    def unbind(self):
        """Older format branches cannot bind or unbind."""
        raise errors.UpgradeRequired(self.base)

    def set_append_revisions_only(self, enabled):
        """Older format branches are never restricted to append-only"""
        raise errors.UpgradeRequired(self.base)

    def last_revision(self):
        """Return last revision id, or None"""
        ph = self.revision_history()
        if ph:
            return ph[-1]
        else:
            return None

    def last_revision_info(self):
        """Return information about the last revision.

        :return: A tuple (revno, last_revision_id).
        """
        rh = self.revision_history()
        revno = len(rh)
        if revno:
            return (revno, rh[-1])
        else:
            return (0, _mod_revision.NULL_REVISION)

    def missing_revisions(self, other, stop_revision=None):
        """Return a list of new revisions that would perfectly fit.
        
        If self and other have not diverged, return a list of the revisions
        present in other, but missing from self.
        """
        self_history = self.revision_history()
        self_len = len(self_history)
        other_history = other.revision_history()
        other_len = len(other_history)
        common_index = min(self_len, other_len) -1
        if common_index >= 0 and \
            self_history[common_index] != other_history[common_index]:
            raise DivergedBranches(self, other)

        if stop_revision is None:
            stop_revision = other_len
        else:
            assert isinstance(stop_revision, int)
            if stop_revision > other_len:
                raise errors.NoSuchRevision(self, stop_revision)
        return other_history[self_len:stop_revision]

    def update_revisions(self, other, stop_revision=None):
        """Pull in new perfect-fit revisions.

        :param other: Another Branch to pull from
        :param stop_revision: Updated until the given revision
        :return: None
        """
        raise NotImplementedError(self.update_revisions)

    def revision_id_to_revno(self, revision_id):
        """Given a revision id, return its revno"""
        if revision_id is None:
            return 0
        revision_id = osutils.safe_revision_id(revision_id)
        history = self.revision_history()
        try:
            return history.index(revision_id) + 1
        except ValueError:
            raise bzrlib.errors.NoSuchRevision(self, revision_id)

    def get_rev_id(self, revno, history=None):
        """Find the revision id of the specified revno."""
        if revno == 0:
            return None
        if history is None:
            history = self.revision_history()
        if revno <= 0 or revno > len(history):
            raise bzrlib.errors.NoSuchRevision(self, revno)
        return history[revno - 1]

    def pull(self, source, overwrite=False, stop_revision=None):
        """Mirror source into this branch.

        This branch is considered to be 'local', having low latency.

        :returns: PullResult instance
        """
        raise NotImplementedError(self.pull)

    def push(self, target, overwrite=False, stop_revision=None):
        """Mirror this branch into target.

        This branch is considered to be 'local', having low latency.
        """
        raise NotImplementedError(self.push)

    def basis_tree(self):
        """Return `Tree` object for last revision."""
        return self.repository.revision_tree(self.last_revision())

    def rename_one(self, from_rel, to_rel):
        """Rename one file.

        This can change the directory or the filename or both.
        """
        raise NotImplementedError(self.rename_one)

    def move(self, from_paths, to_name):
        """Rename files.

        to_name must exist as a versioned directory.

        If to_name exists and is a directory, the files are moved into
        it, keeping their old names.  If it is a directory, 

        Note that to_name is only the last component of the new name;
        this doesn't change the directory.

        This returns a list of (from_path, to_path) pairs for each
        entry that is moved.
        """
        raise NotImplementedError(self.move)

    def get_parent(self):
        """Return the parent location of the branch.

        This is the default location for push/pull/missing.  The usual
        pattern is that the user can override it by specifying a
        location.
        """
        raise NotImplementedError(self.get_parent)

    def get_submit_branch(self):
        """Return the submit location of the branch.

        This is the default location for bundle.  The usual
        pattern is that the user can override it by specifying a
        location.
        """
        return self.get_config().get_user_option('submit_branch')

    def set_submit_branch(self, location):
        """Return the submit location of the branch.

        This is the default location for bundle.  The usual
        pattern is that the user can override it by specifying a
        location.
        """
        self.get_config().set_user_option('submit_branch', location)

    def get_push_location(self):
        """Return the None or the location to push this branch to."""
        raise NotImplementedError(self.get_push_location)

    def set_push_location(self, location):
        """Set a new push location for this branch."""
        raise NotImplementedError(self.set_push_location)

    def set_parent(self, url):
        raise NotImplementedError(self.set_parent)

    @needs_write_lock
    def update(self):
        """Synchronise this branch with the master branch if any. 

        :return: None or the last_revision pivoted out during the update.
        """
        return None

    def check_revno(self, revno):
        """\
        Check whether a revno corresponds to any revision.
        Zero (the NULL revision) is considered valid.
        """
        if revno != 0:
            self.check_real_revno(revno)
            
    def check_real_revno(self, revno):
        """\
        Check whether a revno corresponds to a real revision.
        Zero (the NULL revision) is considered invalid
        """
        if revno < 1 or revno > self.revno():
            raise InvalidRevisionNumber(revno)

    @needs_read_lock
    def clone(self, *args, **kwargs):
        """Clone this branch into to_bzrdir preserving all semantic values.
        
        revision_id: if not None, the revision history in the new branch will
                     be truncated to end with revision_id.
        """
        # for API compatibility, until 0.8 releases we provide the old api:
        # def clone(self, to_location, revision=None, basis_branch=None, to_branch_format=None):
        # after 0.8 releases, the *args and **kwargs should be changed:
        # def clone(self, to_bzrdir, revision_id=None):
        if (kwargs.get('to_location', None) or
            kwargs.get('revision', None) or
            kwargs.get('basis_branch', None) or
            (len(args) and isinstance(args[0], basestring))):
            # backwards compatibility api:
            warn("Branch.clone() has been deprecated for BzrDir.clone() from"
                 " bzrlib 0.8.", DeprecationWarning, stacklevel=3)
            # get basis_branch
            if len(args) > 2:
                basis_branch = args[2]
            else:
                basis_branch = kwargs.get('basis_branch', None)
            if basis_branch:
                basis = basis_branch.bzrdir
            else:
                basis = None
            # get revision
            if len(args) > 1:
                revision_id = args[1]
            else:
                revision_id = kwargs.get('revision', None)
            # get location
            if len(args):
                url = args[0]
            else:
                # no default to raise if not provided.
                url = kwargs.get('to_location')
            return self.bzrdir.clone(url,
                                     revision_id=revision_id,
                                     basis=basis).open_branch()
        # new cleaner api.
        # generate args by hand 
        if len(args) > 1:
            revision_id = args[1]
        else:
            revision_id = kwargs.get('revision_id', None)
        if len(args):
            to_bzrdir = args[0]
        else:
            # no default to raise if not provided.
            to_bzrdir = kwargs.get('to_bzrdir')
        result = self._format.initialize(to_bzrdir)
        self.copy_content_into(result, revision_id=revision_id)
        return  result

    @needs_read_lock
    def sprout(self, to_bzrdir, revision_id=None):
        """Create a new line of development from the branch, into to_bzrdir.
        
        revision_id: if not None, the revision history in the new branch will
                     be truncated to end with revision_id.
        """
        result = self._format.initialize(to_bzrdir)
        self.copy_content_into(result, revision_id=revision_id)
        result.set_parent(self.bzrdir.root_transport.base)
        return result

    def _synchronize_history(self, destination, revision_id):
        """Synchronize last revision and revision history between branches.

        This version is most efficient when the destination is also a
        BzrBranch5, but works for BzrBranch6 as long as the revision
        history is the true lefthand parent history, and all of the revisions
        are in the destination's repository.  If not, set_revision_history
        will fail.

        :param destination: The branch to copy the history into
        :param revision_id: The revision-id to truncate history at.  May
          be None to copy complete history.
        """
        new_history = self.revision_history()
        if revision_id is not None:
            revision_id = osutils.safe_revision_id(revision_id)
            try:
                new_history = new_history[:new_history.index(revision_id) + 1]
            except ValueError:
                rev = self.repository.get_revision(revision_id)
                new_history = rev.get_history(self.repository)[1:]
        destination.set_revision_history(new_history)

    @needs_read_lock
    def copy_content_into(self, destination, revision_id=None):
        """Copy the content of self into destination.

        revision_id: if not None, the revision history in the new branch will
                     be truncated to end with revision_id.
        """
        self._synchronize_history(destination, revision_id)
        try:
            parent = self.get_parent()
        except errors.InaccessibleParent, e:
            mutter('parent was not accessible to copy: %s', e)
        else:
            if parent:
                destination.set_parent(parent)

    @needs_read_lock
    def check(self):
        """Check consistency of the branch.

        In particular this checks that revisions given in the revision-history
        do actually match up in the revision graph, and that they're all 
        present in the repository.
        
        Callers will typically also want to check the repository.

        :return: A BranchCheckResult.
        """
        mainline_parent_id = None
        for revision_id in self.revision_history():
            try:
                revision = self.repository.get_revision(revision_id)
            except errors.NoSuchRevision, e:
                raise errors.BzrCheckError("mainline revision {%s} not in repository"
                            % revision_id)
            # In general the first entry on the revision history has no parents.
            # But it's not illegal for it to have parents listed; this can happen
            # in imports from Arch when the parents weren't reachable.
            if mainline_parent_id is not None:
                if mainline_parent_id not in revision.parent_ids:
                    raise errors.BzrCheckError("previous revision {%s} not listed among "
                                        "parents of {%s}"
                                        % (mainline_parent_id, revision_id))
            mainline_parent_id = revision_id
        return BranchCheckResult(self)

    def _get_checkout_format(self):
        """Return the most suitable metadir for a checkout of this branch.
        Weaves are used if this branch's repostory uses weaves.
        """
        if isinstance(self.bzrdir, bzrdir.BzrDirPreSplitOut):
            from bzrlib.repofmt import weaverepo
            format = bzrdir.BzrDirMetaFormat1()
            format.repository_format = weaverepo.RepositoryFormat7()
        else:
            format = self.repository.bzrdir.checkout_metadir()
            format.branch_format = self._format
        return format

    def create_checkout(self, to_location, revision_id=None,
                        lightweight=False):
        """Create a checkout of a branch.
        
        :param to_location: The url to produce the checkout at
        :param revision_id: The revision to check out
        :param lightweight: If True, produce a lightweight checkout, otherwise,
        produce a bound branch (heavyweight checkout)
        :return: The tree of the created checkout
        """
        t = transport.get_transport(to_location)
        try:
            t.mkdir('.')
        except errors.FileExists:
            pass
        if lightweight:
            format = self._get_checkout_format()
            checkout = format.initialize_on_transport(t)
            BranchReferenceFormat().initialize(checkout, self)
        else:
            format = self._get_checkout_format()
            checkout_branch = bzrdir.BzrDir.create_branch_convenience(
                to_location, force_new_tree=False, format=format)
            checkout = checkout_branch.bzrdir
            checkout_branch.bind(self)
            # pull up to the specified revision_id to set the initial 
            # branch tip correctly, and seed it with history.
            checkout_branch.pull(self, stop_revision=revision_id)
        tree = checkout.create_workingtree(revision_id)
        basis_tree = tree.basis_tree()
        basis_tree.lock_read()
        try:
            for path, file_id in basis_tree.iter_references():
                reference_parent = self.reference_parent(file_id, path)
                reference_parent.create_checkout(tree.abspath(path),
                    basis_tree.get_reference_revision(file_id, path),
                    lightweight)
        finally:
            basis_tree.unlock()
        return tree

    def reference_parent(self, file_id, path):
        """Return the parent branch for a tree-reference file_id
        :param file_id: The file_id of the tree reference
        :param path: The path of the file_id in the tree
        :return: A branch associated with the file_id
        """
        # FIXME should provide multiple branches, based on config
        return Branch.open(self.bzrdir.root_transport.clone(path).base)

    def supports_tags(self):
        return self._format.supports_tags()


class BranchFormat(object):
    """An encapsulation of the initialization and open routines for a format.

    Formats provide three things:
     * An initialization routine,
     * a format string,
     * an open routine.

    Formats are placed in an dict by their format string for reference 
    during branch opening. Its not required that these be instances, they
    can be classes themselves with class methods - it simply depends on 
    whether state is needed for a given format or not.

    Once a format is deprecated, just deprecate the initialize and open
    methods on the format class. Do not deprecate the object, as the 
    object will be created every time regardless.
    """

    _default_format = None
    """The default format used for new branches."""

    _formats = {}
    """The known formats."""

    @classmethod
    def find_format(klass, a_bzrdir):
        """Return the format for the branch object in a_bzrdir."""
        try:
            transport = a_bzrdir.get_branch_transport(None)
            format_string = transport.get("format").read()
            return klass._formats[format_string]
        except NoSuchFile:
            raise NotBranchError(path=transport.base)
        except KeyError:
            raise errors.UnknownFormatError(format=format_string)

    @classmethod
    def get_default_format(klass):
        """Return the current default format."""
        return klass._default_format

    def get_format_string(self):
        """Return the ASCII format string that identifies this format."""
        raise NotImplementedError(self.get_format_string)

    def get_format_description(self):
        """Return the short format description for this format."""
        raise NotImplementedError(self.get_format_description)

    def _initialize_helper(self, a_bzrdir, utf8_files, lock_type='metadir',
                           set_format=True):
        """Initialize a branch in a bzrdir, with specified files

        :param a_bzrdir: The bzrdir to initialize the branch in
        :param utf8_files: The files to create as a list of
            (filename, content) tuples
        :param set_format: If True, set the format with
            self.get_format_string.  (BzrBranch4 has its format set
            elsewhere)
        :return: a branch in this format
        """
        mutter('creating branch %r in %s', self, a_bzrdir.transport.base)
        branch_transport = a_bzrdir.get_branch_transport(self)
        lock_map = {
            'metadir': ('lock', lockdir.LockDir),
            'branch4': ('branch-lock', lockable_files.TransportLock),
        }
        lock_name, lock_class = lock_map[lock_type]
        control_files = lockable_files.LockableFiles(branch_transport,
            lock_name, lock_class)
        control_files.create_lock()
        control_files.lock_write()
        if set_format:
            control_files.put_utf8('format', self.get_format_string())
        try:
            for file, content in utf8_files:
                control_files.put_utf8(file, content)
        finally:
            control_files.unlock()
        return self.open(a_bzrdir, _found=True)

    def initialize(self, a_bzrdir):
        """Create a branch of this format in a_bzrdir."""
        raise NotImplementedError(self.initialize)

    def is_supported(self):
        """Is this format supported?

        Supported formats can be initialized and opened.
        Unsupported formats may not support initialization or committing or 
        some other features depending on the reason for not being supported.
        """
        return True

    def open(self, a_bzrdir, _found=False):
        """Return the branch object for a_bzrdir

        _found is a private parameter, do not use it. It is used to indicate
               if format probing has already be done.
        """
        raise NotImplementedError(self.open)

    @classmethod
    def register_format(klass, format):
        klass._formats[format.get_format_string()] = format

    @classmethod
    def set_default_format(klass, format):
        klass._default_format = format

    @classmethod
    def unregister_format(klass, format):
        assert klass._formats[format.get_format_string()] is format
        del klass._formats[format.get_format_string()]

    def __str__(self):
        return self.get_format_string().rstrip()

    def supports_tags(self):
        """True if this format supports tags stored in the branch"""
        return False  # by default

    # XXX: Probably doesn't really belong here -- mbp 20070212
    def _initialize_control_files(self, a_bzrdir, utf8_files, lock_filename,
            lock_class):
        branch_transport = a_bzrdir.get_branch_transport(self)
        control_files = lockable_files.LockableFiles(branch_transport,
            lock_filename, lock_class)
        control_files.create_lock()
        control_files.lock_write()
        try:
            for filename, content in utf8_files:
                control_files.put_utf8(filename, content)
        finally:
            control_files.unlock()


class BranchHooks(dict):
    """A dictionary mapping hook name to a list of callables for branch hooks.
    
    e.g. ['set_rh'] Is the list of items to be called when the
    set_revision_history function is invoked.
    """

    def __init__(self):
        """Create the default hooks.

        These are all empty initially, because by default nothing should get
        notified.
        """
        dict.__init__(self)
        # Introduced in 0.15:
        # invoked whenever the revision history has been set
        # with set_revision_history. The api signature is
        # (branch, revision_history), and the branch will
        # be write-locked.
        self['set_rh'] = []
        # invoked after a push operation completes.
        # the api signature is
        # (push_result)
        # containing the members
        # (source, local, master, old_revno, old_revid, new_revno, new_revid)
        # where local is the local branch or None, master is the target 
        # master branch, and the rest should be self explanatory. The source
        # is read locked and the target branches write locked. Source will
        # be the local low-latency branch.
        self['post_push'] = []
        # invoked after a pull operation completes.
        # the api signature is
        # (pull_result)
        # containing the members
        # (source, local, master, old_revno, old_revid, new_revno, new_revid)
        # where local is the local branch or None, master is the target 
        # master branch, and the rest should be self explanatory. The source
        # is read locked and the target branches write locked. The local
        # branch is the low-latency branch.
        self['post_pull'] = []
        # invoked after a commit operation completes.
        # the api signature is 
        # (local, master, old_revno, old_revid, new_revno, new_revid)
        # old_revid is NULL_REVISION for the first commit to a branch.
        self['post_commit'] = []
        # invoked after a uncommit operation completes.
        # the api signature is
        # (local, master, old_revno, old_revid, new_revno, new_revid) where
        # local is the local branch or None, master is the target branch,
        # and an empty branch recieves new_revno of 0, new_revid of None.
        self['post_uncommit'] = []

    def install_hook(self, hook_name, a_callable):
        """Install a_callable in to the hook hook_name.

        :param hook_name: A hook name. See the __init__ method of BranchHooks
            for the complete list of hooks.
        :param a_callable: The callable to be invoked when the hook triggers.
            The exact signature will depend on the hook - see the __init__ 
            method of BranchHooks for details on each hook.
        """
        try:
            self[hook_name].append(a_callable)
        except KeyError:
            raise errors.UnknownHook('branch', hook_name)


# install the default hooks into the Branch class.
Branch.hooks = BranchHooks()


class BzrBranchFormat4(BranchFormat):
    """Bzr branch format 4.

    This format has:
     - a revision-history file.
     - a branch-lock lock file [ to be shared with the bzrdir ]
    """

    def get_format_description(self):
        """See BranchFormat.get_format_description()."""
        return "Branch format 4"

    def initialize(self, a_bzrdir):
        """Create a branch of this format in a_bzrdir."""
        utf8_files = [('revision-history', ''),
                      ('branch-name', ''),
                      ]
        return self._initialize_helper(a_bzrdir, utf8_files,
                                       lock_type='branch4', set_format=False)

    def __init__(self):
        super(BzrBranchFormat4, self).__init__()
        self._matchingbzrdir = bzrdir.BzrDirFormat6()

    def open(self, a_bzrdir, _found=False):
        """Return the branch object for a_bzrdir

        _found is a private parameter, do not use it. It is used to indicate
               if format probing has already be done.
        """
        if not _found:
            # we are being called directly and must probe.
            raise NotImplementedError
        return BzrBranch(_format=self,
                         _control_files=a_bzrdir._control_files,
                         a_bzrdir=a_bzrdir,
                         _repository=a_bzrdir.open_repository())

    def __str__(self):
        return "Bazaar-NG branch format 4"


class BzrBranchFormat5(BranchFormat):
    """Bzr branch format 5.

    This format has:
     - a revision-history file.
     - a format string
     - a lock dir guarding the branch itself
     - all of this stored in a branch/ subdirectory
     - works with shared repositories.

    This format is new in bzr 0.8.
    """

    def get_format_string(self):
        """See BranchFormat.get_format_string()."""
        return "Bazaar-NG branch format 5\n"

    def get_format_description(self):
        """See BranchFormat.get_format_description()."""
        return "Branch format 5"
        
    def initialize(self, a_bzrdir):
        """Create a branch of this format in a_bzrdir."""
        utf8_files = [('revision-history', ''),
                      ('branch-name', ''),
                      ]
        return self._initialize_helper(a_bzrdir, utf8_files)

    def __init__(self):
        super(BzrBranchFormat5, self).__init__()
        self._matchingbzrdir = bzrdir.BzrDirMetaFormat1()

    def open(self, a_bzrdir, _found=False):
        """Return the branch object for a_bzrdir

        _found is a private parameter, do not use it. It is used to indicate
               if format probing has already be done.
        """
        if not _found:
            format = BranchFormat.find_format(a_bzrdir)
            assert format.__class__ == self.__class__
        transport = a_bzrdir.get_branch_transport(None)
        control_files = lockable_files.LockableFiles(transport, 'lock',
                                                     lockdir.LockDir)
        return BzrBranch5(_format=self,
                          _control_files=control_files,
                          a_bzrdir=a_bzrdir,
                          _repository=a_bzrdir.find_repository())


class BzrBranchFormat6(BzrBranchFormat5):
    """Branch format with last-revision

    Unlike previous formats, this has no explicit revision history. Instead,
    this just stores the last-revision, and the left-hand history leading
    up to there is the history.

    This format was introduced in bzr 0.15
    """

    def get_format_string(self):
        """See BranchFormat.get_format_string()."""
        return "Bazaar Branch Format 6 (bzr 0.15)\n"

    def get_format_description(self):
        """See BranchFormat.get_format_description()."""
        return "Branch format 6"

    def initialize(self, a_bzrdir):
        """Create a branch of this format in a_bzrdir."""
        utf8_files = [('last-revision', '0 null:\n'),
                      ('branch-name', ''),
                      ('branch.conf', ''),
                      ('tags', ''),
                      ]
        return self._initialize_helper(a_bzrdir, utf8_files)

    def open(self, a_bzrdir, _found=False):
        """Return the branch object for a_bzrdir

        _found is a private parameter, do not use it. It is used to indicate
               if format probing has already be done.
        """
        if not _found:
            format = BranchFormat.find_format(a_bzrdir)
            assert format.__class__ == self.__class__
        transport = a_bzrdir.get_branch_transport(None)
        control_files = lockable_files.LockableFiles(transport, 'lock',
                                                     lockdir.LockDir)
        return BzrBranch6(_format=self,
                          _control_files=control_files,
                          a_bzrdir=a_bzrdir,
                          _repository=a_bzrdir.find_repository())

    def supports_tags(self):
        return True


class BranchReferenceFormat(BranchFormat):
    """Bzr branch reference format.

    Branch references are used in implementing checkouts, they
    act as an alias to the real branch which is at some other url.

    This format has:
     - A location file
     - a format string
    """

    def get_format_string(self):
        """See BranchFormat.get_format_string()."""
        return "Bazaar-NG Branch Reference Format 1\n"

    def get_format_description(self):
        """See BranchFormat.get_format_description()."""
        return "Checkout reference format 1"
        
    def initialize(self, a_bzrdir, target_branch=None):
        """Create a branch of this format in a_bzrdir."""
        if target_branch is None:
            # this format does not implement branch itself, thus the implicit
            # creation contract must see it as uninitializable
            raise errors.UninitializableFormat(self)
        mutter('creating branch reference in %s', a_bzrdir.transport.base)
        branch_transport = a_bzrdir.get_branch_transport(self)
        branch_transport.put_bytes('location',
            target_branch.bzrdir.root_transport.base)
        branch_transport.put_bytes('format', self.get_format_string())
        return self.open(a_bzrdir, _found=True)

    def __init__(self):
        super(BranchReferenceFormat, self).__init__()
        self._matchingbzrdir = bzrdir.BzrDirMetaFormat1()

    def _make_reference_clone_function(format, a_branch):
        """Create a clone() routine for a branch dynamically."""
        def clone(to_bzrdir, revision_id=None):
            """See Branch.clone()."""
            return format.initialize(to_bzrdir, a_branch)
            # cannot obey revision_id limits when cloning a reference ...
            # FIXME RBC 20060210 either nuke revision_id for clone, or
            # emit some sort of warning/error to the caller ?!
        return clone

    def open(self, a_bzrdir, _found=False):
        """Return the branch that the branch reference in a_bzrdir points at.

        _found is a private parameter, do not use it. It is used to indicate
               if format probing has already be done.
        """
        if not _found:
            format = BranchFormat.find_format(a_bzrdir)
            assert format.__class__ == self.__class__
        transport = a_bzrdir.get_branch_transport(None)
        real_bzrdir = bzrdir.BzrDir.open(transport.get('location').read())
        result = real_bzrdir.open_branch()
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


# formats which have no format string are not discoverable
# and not independently creatable, so are not registered.
__default_format = BzrBranchFormat5()
BranchFormat.register_format(__default_format)
BranchFormat.register_format(BranchReferenceFormat())
BranchFormat.register_format(BzrBranchFormat6())
BranchFormat.set_default_format(__default_format)
_legacy_formats = [BzrBranchFormat4(),
                   ]

class BzrBranch(Branch):
    """A branch stored in the actual filesystem.

    Note that it's "local" in the context of the filesystem; it doesn't
    really matter if it's on an nfs/smb/afs/coda/... share, as long as
    it's writable, and can be accessed via the normal filesystem API.
    """
    
    def __init__(self, transport=DEPRECATED_PARAMETER, init=DEPRECATED_PARAMETER,
                 relax_version_check=DEPRECATED_PARAMETER, _format=None,
                 _control_files=None, a_bzrdir=None, _repository=None):
        """Create new branch object at a particular location.

        transport -- A Transport object, defining how to access files.
        
        init -- If True, create new control files in a previously
             unversioned directory.  If False, the branch must already
             be versioned.

        relax_version_check -- If true, the usual check for the branch
            version is not applied.  This is intended only for
            upgrade/recovery type use; it's not guaranteed that
            all operations will work on old format branches.
        """
        Branch.__init__(self)
        if a_bzrdir is None:
            self.bzrdir = bzrdir.BzrDir.open(transport.base)
        else:
            self.bzrdir = a_bzrdir
        # self._transport used to point to the directory containing the
        # control directory, but was not used - now it's just the transport
        # for the branch control files.  mbp 20070212
        self._base = self.bzrdir.transport.clone('..').base
        self._format = _format
        if _control_files is None:
            raise ValueError('BzrBranch _control_files is None')
        self.control_files = _control_files
        self._transport = _control_files._transport
        if deprecated_passed(init):
            warn("BzrBranch.__init__(..., init=XXX): The init parameter is "
                 "deprecated as of bzr 0.8. Please use Branch.create().",
                 DeprecationWarning,
                 stacklevel=2)
            if init:
                # this is slower than before deprecation, oh well never mind.
                # -> its deprecated.
                self._initialize(transport.base)
        self._check_format(_format)
        if deprecated_passed(relax_version_check):
            warn("BzrBranch.__init__(..., relax_version_check=XXX_: The "
                 "relax_version_check parameter is deprecated as of bzr 0.8. "
                 "Please use BzrDir.open_downlevel, or a BzrBranchFormat's "
                 "open() method.",
                 DeprecationWarning,
                 stacklevel=2)
            if (not relax_version_check
                and not self._format.is_supported()):
                raise errors.UnsupportedFormatError(format=fmt)
        if deprecated_passed(transport):
            warn("BzrBranch.__init__(transport=XXX...): The transport "
                 "parameter is deprecated as of bzr 0.8. "
                 "Please use Branch.open, or bzrdir.open_branch().",
                 DeprecationWarning,
                 stacklevel=2)
        self.repository = _repository

    def __str__(self):
        return '%s(%r)' % (self.__class__.__name__, self.base)

    __repr__ = __str__

    def _get_base(self):
        """Returns the directory containing the control directory."""
        return self._base

    base = property(_get_base, doc="The URL for the root of this branch.")

    def _finish_transaction(self):
        """Exit the current transaction."""
        return self.control_files._finish_transaction()

    def get_transaction(self):
        """Return the current active transaction.

        If no transaction is active, this returns a passthrough object
        for which all data is immediately flushed and no caching happens.
        """
        # this is an explicit function so that we can do tricky stuff
        # when the storage in rev_storage is elsewhere.
        # we probably need to hook the two 'lock a location' and 
        # 'have a transaction' together more delicately, so that
        # we can have two locks (branch and storage) and one transaction
        # ... and finishing the transaction unlocks both, but unlocking
        # does not. - RBC 20051121
        return self.control_files.get_transaction()

    def _set_transaction(self, transaction):
        """Set a new active transaction."""
        return self.control_files._set_transaction(transaction)

    def abspath(self, name):
        """See Branch.abspath."""
        return self.control_files._transport.abspath(name)

    def _check_format(self, format):
        """Identify the branch format if needed.

        The format is stored as a reference to the format object in
        self._format for code that needs to check it later.

        The format parameter is either None or the branch format class
        used to open this branch.

        FIXME: DELETE THIS METHOD when pre 0.8 support is removed.
        """
        if format is None:
            format = BranchFormat.find_format(self.bzrdir)
        self._format = format
        mutter("got branch format %s", self._format)

    @needs_read_lock
    def get_root_id(self):
        """See Branch.get_root_id."""
        tree = self.repository.revision_tree(self.last_revision())
        return tree.inventory.root.file_id

    def is_locked(self):
        return self.control_files.is_locked()

    def lock_write(self):
        self.repository.lock_write()
        try:
            self.control_files.lock_write()
        except:
            self.repository.unlock()
            raise

    def lock_read(self):
        self.repository.lock_read()
        try:
            self.control_files.lock_read()
        except:
            self.repository.unlock()
            raise

    def unlock(self):
        # TODO: test for failed two phase locks. This is known broken.
        try:
            self.control_files.unlock()
        finally:
            self.repository.unlock()
        
    def peek_lock_mode(self):
        if self.control_files._lock_count == 0:
            return None
        else:
            return self.control_files._lock_mode

    def get_physical_lock_status(self):
        return self.control_files.get_physical_lock_status()

    @needs_read_lock
    def print_file(self, file, revision_id):
        """See Branch.print_file."""
        return self.repository.print_file(file, revision_id)

    @needs_write_lock
    def append_revision(self, *revision_ids):
        """See Branch.append_revision."""
        revision_ids = [osutils.safe_revision_id(r) for r in revision_ids]
        for revision_id in revision_ids:
            _mod_revision.check_not_reserved_id(revision_id)
            mutter("add {%s} to revision-history" % revision_id)
        rev_history = self.revision_history()
        rev_history.extend(revision_ids)
        self.set_revision_history(rev_history)

    def _write_revision_history(self, history):
        """Factored out of set_revision_history.

        This performs the actual writing to disk.
        It is intended to be called by BzrBranch5.set_revision_history."""
        self.control_files.put_bytes(
            'revision-history', '\n'.join(history))

    @needs_write_lock
    def set_revision_history(self, rev_history):
        """See Branch.set_revision_history."""
        rev_history = [osutils.safe_revision_id(r) for r in rev_history]
        self._write_revision_history(rev_history)
        transaction = self.get_transaction()
        history = transaction.map.find_revision_history()
        if history is not None:
            # update the revision history in the identity map.
            history[:] = list(rev_history)
            # this call is disabled because revision_history is 
            # not really an object yet, and the transaction is for objects.
            # transaction.register_dirty(history)
        else:
            transaction.map.add_revision_history(rev_history)
            # this call is disabled because revision_history is 
            # not really an object yet, and the transaction is for objects.
            # transaction.register_clean(history)
        for hook in Branch.hooks['set_rh']:
            hook(self, rev_history)

    @needs_write_lock
    def set_last_revision_info(self, revno, revision_id):
        revision_id = osutils.safe_revision_id(revision_id)
        history = self._lefthand_history(revision_id)
        assert len(history) == revno, '%d != %d' % (len(history), revno)
        self.set_revision_history(history)

    def _gen_revision_history(self):
        history = self.control_files.get('revision-history').read().split('\n')
        if history[-1:] == ['']:
            # There shouldn't be a trailing newline, but just in case.
            history.pop()
        return history

    @needs_read_lock
    def revision_history(self):
        """See Branch.revision_history."""
        transaction = self.get_transaction()
        history = transaction.map.find_revision_history()
        if history is not None:
            # mutter("cache hit for revision-history in %s", self)
            return list(history)
        history = self._gen_revision_history()
        transaction.map.add_revision_history(history)
        # this call is disabled because revision_history is 
        # not really an object yet, and the transaction is for objects.
        # transaction.register_clean(history, precious=True)
        return list(history)

    def _lefthand_history(self, revision_id, last_rev=None,
                          other_branch=None):
        # stop_revision must be a descendant of last_revision
        stop_graph = self.repository.get_revision_graph(revision_id)
        if last_rev is not None and last_rev not in stop_graph:
            # our previous tip is not merged into stop_revision
            raise errors.DivergedBranches(self, other_branch)
        # make a new revision history from the graph
        current_rev_id = revision_id
        new_history = []
        while current_rev_id not in (None, _mod_revision.NULL_REVISION):
            new_history.append(current_rev_id)
            current_rev_id_parents = stop_graph[current_rev_id]
            try:
                current_rev_id = current_rev_id_parents[0]
            except IndexError:
                current_rev_id = None
        new_history.reverse()
        return new_history

    @needs_write_lock
    def generate_revision_history(self, revision_id, last_rev=None,
        other_branch=None):
        """Create a new revision history that will finish with revision_id.

        :param revision_id: the new tip to use.
        :param last_rev: The previous last_revision. If not None, then this
            must be a ancestory of revision_id, or DivergedBranches is raised.
        :param other_branch: The other branch that DivergedBranches should
            raise with respect to.
        """
        revision_id = osutils.safe_revision_id(revision_id)
        self.set_revision_history(self._lefthand_history(revision_id,
            last_rev, other_branch))

    @needs_write_lock
    def update_revisions(self, other, stop_revision=None):
        """See Branch.update_revisions."""
        other.lock_read()
        try:
            if stop_revision is None:
                stop_revision = other.last_revision()
                if stop_revision is None:
                    # if there are no commits, we're done.
                    return
            else:
                stop_revision = osutils.safe_revision_id(stop_revision)
            # whats the current last revision, before we fetch [and change it
            # possibly]
            last_rev = self.last_revision()
            # we fetch here regardless of whether we need to so that we pickup
            # filled in ghosts.
            self.fetch(other, stop_revision)
            my_ancestry = self.repository.get_ancestry(last_rev)
            if stop_revision in my_ancestry:
                # last_revision is a descendant of stop_revision
                return
            self.generate_revision_history(stop_revision, last_rev=last_rev,
                other_branch=other)
        finally:
            other.unlock()

    def basis_tree(self):
        """See Branch.basis_tree."""
        return self.repository.revision_tree(self.last_revision())

    @deprecated_method(zero_eight)
    def working_tree(self):
        """Create a Working tree object for this branch."""

        from bzrlib.transport.local import LocalTransport
        if (self.base.find('://') != -1 or 
            not isinstance(self._transport, LocalTransport)):
            raise NoWorkingTree(self.base)
        return self.bzrdir.open_workingtree()

    @needs_write_lock
    def pull(self, source, overwrite=False, stop_revision=None,
        _hook_master=None, _run_hooks=True):
        """See Branch.pull.

        :param _hook_master: Private parameter - set the branch to 
            be supplied as the master to push hooks.
        :param _run_hooks: Private parameter - allow disabling of
            hooks, used when pushing to a master branch.
        """
        result = PullResult()
        result.source_branch = source
        result.target_branch = self
        source.lock_read()
        try:
            result.old_revno, result.old_revid = self.last_revision_info()
            try:
                self.update_revisions(source, stop_revision)
            except DivergedBranches:
                if not overwrite:
                    raise
            if overwrite:
                if stop_revision is None:
                    stop_revision = source.last_revision()
                self.generate_revision_history(stop_revision)
            result.tag_conflicts = source.tags.merge_to(self.tags)
            result.new_revno, result.new_revid = self.last_revision_info()
            if _hook_master:
                result.master_branch = _hook_master
                result.local_branch = self
            else:
                result.master_branch = self
                result.local_branch = None
            if _run_hooks:
                for hook in Branch.hooks['post_pull']:
                    hook(result)
        finally:
            source.unlock()
        return result

    def _get_parent_location(self):
        _locs = ['parent', 'pull', 'x-pull']
        for l in _locs:
            try:
                return self.control_files.get(l).read().strip('\n')
            except NoSuchFile:
                pass
        return None

    @needs_read_lock
    def push(self, target, overwrite=False, stop_revision=None,
        _hook_master=None, _run_hooks=True):
        """See Branch.push.
        
        :param _hook_master: Private parameter - set the branch to 
            be supplied as the master to push hooks.
        :param _run_hooks: Private parameter - allow disabling of
            hooks, used when pushing to a master branch.
        """
        result = PushResult()
        result.source_branch = self
        result.target_branch = target
        target.lock_write()
        try:
            result.old_revno, result.old_revid = target.last_revision_info()
            try:
                target.update_revisions(self, stop_revision)
            except DivergedBranches:
                if not overwrite:
                    raise
            if overwrite:
                target.set_revision_history(self.revision_history())
            result.tag_conflicts = self.tags.merge_to(target.tags)
            result.new_revno, result.new_revid = target.last_revision_info()
            if _hook_master:
                result.master_branch = _hook_master
                result.local_branch = target
            else:
                result.master_branch = target
                result.local_branch = None
            if _run_hooks:
                for hook in Branch.hooks['post_push']:
                    hook(result)
        finally:
            target.unlock()
        return result

    def get_parent(self):
        """See Branch.get_parent."""

        assert self.base[-1] == '/'
        parent = self._get_parent_location()
        if parent is None:
            return parent
        # This is an old-format absolute path to a local branch
        # turn it into a url
        if parent.startswith('/'):
            parent = urlutils.local_path_to_url(parent.decode('utf8'))
        try:
            return urlutils.join(self.base[:-1], parent)
        except errors.InvalidURLJoin, e:
            raise errors.InaccessibleParent(parent, self.base)

    def get_push_location(self):
        """See Branch.get_push_location."""
        push_loc = self.get_config().get_user_option('push_location')
        return push_loc

    def set_push_location(self, location):
        """See Branch.set_push_location."""
        self.get_config().set_user_option(
            'push_location', location,
            store=_mod_config.STORE_LOCATION_NORECURSE)

    @needs_write_lock
    def set_parent(self, url):
        """See Branch.set_parent."""
        # TODO: Maybe delete old location files?
        # URLs should never be unicode, even on the local fs,
        # FIXUP this and get_parent in a future branch format bump:
        # read and rewrite the file, and have the new format code read
        # using .get not .get_utf8. RBC 20060125
        if url is not None:
            if isinstance(url, unicode):
                try: 
                    url = url.encode('ascii')
                except UnicodeEncodeError:
                    raise bzrlib.errors.InvalidURL(url,
                        "Urls must be 7-bit ascii, "
                        "use bzrlib.urlutils.escape")
            url = urlutils.relative_url(self.base, url)
        self._set_parent_location(url)

    def _set_parent_location(self, url):
        if url is None:
            self.control_files._transport.delete('parent')
        else:
            assert isinstance(url, str)
            self.control_files.put_bytes('parent', url + '\n')

    @deprecated_function(zero_nine)
    def tree_config(self):
        """DEPRECATED; call get_config instead.  
        TreeConfig has become part of BranchConfig."""
        return TreeConfig(self)


class BzrBranch5(BzrBranch):
    """A format 5 branch. This supports new features over plan branches.

    It has support for a master_branch which is the data for bound branches.
    """

    def __init__(self,
                 _format,
                 _control_files,
                 a_bzrdir,
                 _repository):
        super(BzrBranch5, self).__init__(_format=_format,
                                         _control_files=_control_files,
                                         a_bzrdir=a_bzrdir,
                                         _repository=_repository)
        
    @needs_write_lock
    def pull(self, source, overwrite=False, stop_revision=None,
        _run_hooks=True):
        """Extends branch.pull to be bound branch aware.
        
        :param _run_hooks: Private parameter used to force hook running
            off during bound branch double-pushing.
        """
        bound_location = self.get_bound_location()
        master_branch = None
        if bound_location and source.base != bound_location:
            # not pulling from master, so we need to update master.
            master_branch = self.get_master_branch()
            master_branch.lock_write()
        try:
            if master_branch:
                # pull from source into master.
                master_branch.pull(source, overwrite, stop_revision,
                    _run_hooks=False)
            return super(BzrBranch5, self).pull(source, overwrite,
                stop_revision, _hook_master=master_branch,
                _run_hooks=_run_hooks)
        finally:
            if master_branch:
                master_branch.unlock()

    @needs_read_lock
    def push(self, target, overwrite=False, stop_revision=None):
        """Updates branch.push to be bound branch aware."""
        bound_location = target.get_bound_location()
        master_branch = None
        if bound_location and target.base != bound_location:
            # not pushing to master, so we need to update master.
            master_branch = target.get_master_branch()
            master_branch.lock_write()
        try:
            if master_branch:
                # push into the master from this branch.
                super(BzrBranch5, self).push(master_branch, overwrite,
                    stop_revision, _run_hooks=False)
            # and push into the target branch from this. Note that we push from
            # this branch again, because its considered the highest bandwidth
            # repository.
            return super(BzrBranch5, self).push(target, overwrite,
                stop_revision, _hook_master=master_branch)
        finally:
            if master_branch:
                master_branch.unlock()

    def get_bound_location(self):
        try:
            return self.control_files.get_utf8('bound').read()[:-1]
        except errors.NoSuchFile:
            return None

    @needs_read_lock
    def get_master_branch(self):
        """Return the branch we are bound to.
        
        :return: Either a Branch, or None

        This could memoise the branch, but if thats done
        it must be revalidated on each new lock.
        So for now we just don't memoise it.
        # RBC 20060304 review this decision.
        """
        bound_loc = self.get_bound_location()
        if not bound_loc:
            return None
        try:
            return Branch.open(bound_loc)
        except (errors.NotBranchError, errors.ConnectionError), e:
            raise errors.BoundBranchConnectionFailure(
                    self, bound_loc, e)

    @needs_write_lock
    def set_bound_location(self, location):
        """Set the target where this branch is bound to.

        :param location: URL to the target branch
        """
        if location:
            self.control_files.put_utf8('bound', location+'\n')
        else:
            try:
                self.control_files._transport.delete('bound')
            except NoSuchFile:
                return False
            return True

    @needs_write_lock
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
        last_rev = self.last_revision()
        if last_rev is not None:
            other.lock_read()
            try:
                other_last_rev = other.last_revision()
                if other_last_rev is not None:
                    # neither branch is new, we have to do some work to
                    # ascertain diversion.
                    remote_graph = other.repository.get_revision_graph(
                        other_last_rev)
                    local_graph = self.repository.get_revision_graph(last_rev)
                    if (last_rev not in remote_graph and
                        other_last_rev not in local_graph):
                        raise errors.DivergedBranches(self, other)
            finally:
                other.unlock()
        self.set_bound_location(other.base)

    @needs_write_lock
    def unbind(self):
        """If bound, unbind"""
        return self.set_bound_location(None)

    @needs_write_lock
    def update(self):
        """Synchronise this branch with the master branch if any. 

        :return: None or the last_revision that was pivoted out during the
                 update.
        """
        master = self.get_master_branch()
        if master is not None:
            old_tip = self.last_revision()
            self.pull(master, overwrite=True)
            if old_tip in self.repository.get_ancestry(self.last_revision()):
                return None
            return old_tip
        return None


class BzrBranchExperimental(BzrBranch5):
    """Bzr experimental branch format

    This format has:
     - a revision-history file.
     - a format string
     - a lock dir guarding the branch itself
     - all of this stored in a branch/ subdirectory
     - works with shared repositories.
     - a tag dictionary in the branch

    This format is new in bzr 0.15, but shouldn't be used for real data, 
    only for testing.

    This class acts as it's own BranchFormat.
    """

    _matchingbzrdir = bzrdir.BzrDirMetaFormat1()

    @classmethod
    def get_format_string(cls):
        """See BranchFormat.get_format_string()."""
        return "Bazaar-NG branch format experimental\n"

    @classmethod
    def get_format_description(cls):
        """See BranchFormat.get_format_description()."""
        return "Experimental branch format"

    @classmethod
    def _initialize_control_files(cls, a_bzrdir, utf8_files, lock_filename,
            lock_class):
        branch_transport = a_bzrdir.get_branch_transport(cls)
        control_files = lockable_files.LockableFiles(branch_transport,
            lock_filename, lock_class)
        control_files.create_lock()
        control_files.lock_write()
        try:
            for filename, content in utf8_files:
                control_files.put_utf8(filename, content)
        finally:
            control_files.unlock()
        
    @classmethod
    def initialize(cls, a_bzrdir):
        """Create a branch of this format in a_bzrdir."""
        utf8_files = [('format', cls.get_format_string()),
                      ('revision-history', ''),
                      ('branch-name', ''),
                      ('tags', ''),
                      ]
        cls._initialize_control_files(a_bzrdir, utf8_files,
            'lock', lockdir.LockDir)
        return cls.open(a_bzrdir, _found=True)

    @classmethod
    def open(cls, a_bzrdir, _found=False):
        """Return the branch object for a_bzrdir

        _found is a private parameter, do not use it. It is used to indicate
               if format probing has already be done.
        """
        if not _found:
            format = BranchFormat.find_format(a_bzrdir)
            assert format.__class__ == cls
        transport = a_bzrdir.get_branch_transport(None)
        control_files = lockable_files.LockableFiles(transport, 'lock',
                                                     lockdir.LockDir)
        return cls(_format=cls,
            _control_files=control_files,
            a_bzrdir=a_bzrdir,
            _repository=a_bzrdir.find_repository())

    @classmethod
    def is_supported(cls):
        return True

    def _make_tags(self):
        return BasicTags(self)

    @classmethod
    def supports_tags(cls):
        return True


BranchFormat.register_format(BzrBranchExperimental)


class BzrBranch6(BzrBranch5):

    @needs_read_lock
    def last_revision_info(self):
        revision_string = self.control_files.get('last-revision').read()
        revno, revision_id = revision_string.rstrip('\n').split(' ', 1)
        revision_id = cache_utf8.get_cached_utf8(revision_id)
        revno = int(revno)
        return revno, revision_id

    def last_revision(self):
        """Return last revision id, or None"""
        revision_id = self.last_revision_info()[1]
        if revision_id == _mod_revision.NULL_REVISION:
            revision_id = None
        return revision_id

    def _write_last_revision_info(self, revno, revision_id):
        """Simply write out the revision id, with no checks.

        Use set_last_revision_info to perform this safely.

        Does not update the revision_history cache.
        Intended to be called by set_last_revision_info and
        _write_revision_history.
        """
        if revision_id is None:
            revision_id = 'null:'
        out_string = '%d %s\n' % (revno, revision_id)
        self.control_files.put_bytes('last-revision', out_string)

    @needs_write_lock
    def set_last_revision_info(self, revno, revision_id):
        revision_id = osutils.safe_revision_id(revision_id)
        if self._get_append_revisions_only():
            self._check_history_violation(revision_id)
        self._write_last_revision_info(revno, revision_id)
        transaction = self.get_transaction()
        cached_history = transaction.map.find_revision_history()
        if cached_history is not None:
            transaction.map.remove_object(cached_history)

    def _check_history_violation(self, revision_id):
        last_revision = self.last_revision()
        if last_revision is None:
            return
        if last_revision not in self._lefthand_history(revision_id):
            raise errors.AppendRevisionsOnlyViolation(self.base)

    def _gen_revision_history(self):
        """Generate the revision history from last revision
        """
        history = list(self.repository.iter_reverse_revision_history(
            self.last_revision()))
        history.reverse()
        return history

    def _write_revision_history(self, history):
        """Factored out of set_revision_history.

        This performs the actual writing to disk, with format-specific checks.
        It is intended to be called by BzrBranch5.set_revision_history.
        """
        if len(history) == 0:
            last_revision = 'null:'
        else:
            if history != self._lefthand_history(history[-1]):
                raise errors.NotLefthandHistory(history)
            last_revision = history[-1]
        if self._get_append_revisions_only():
            self._check_history_violation(last_revision)
        self._write_last_revision_info(len(history), last_revision)

    @needs_write_lock
    def append_revision(self, *revision_ids):
        revision_ids = [osutils.safe_revision_id(r) for r in revision_ids]
        if len(revision_ids) == 0:
            return
        prev_revno, prev_revision = self.last_revision_info()
        for revision in self.repository.get_revisions(revision_ids):
            if prev_revision == _mod_revision.NULL_REVISION:
                if revision.parent_ids != []:
                    raise errors.NotLeftParentDescendant(self, prev_revision,
                                                         revision.revision_id)
            else:
                if revision.parent_ids[0] != prev_revision:
                    raise errors.NotLeftParentDescendant(self, prev_revision,
                                                         revision.revision_id)
            prev_revision = revision.revision_id
        self.set_last_revision_info(prev_revno + len(revision_ids),
                                    revision_ids[-1])

    def _set_config_location(self, name, url, config=None,
                             make_relative=False):
        if config is None:
            config = self.get_config()
        if url is None:
            url = ''
        elif make_relative:
            url = urlutils.relative_url(self.base, url)
        config.set_user_option(name, url)


    def _get_config_location(self, name, config=None):
        if config is None:
            config = self.get_config()
        location = config.get_user_option(name)
        if location == '':
            location = None
        return location

    @needs_write_lock
    def _set_parent_location(self, url):
        """Set the parent branch"""
        self._set_config_location('parent_location', url, make_relative=True)

    @needs_read_lock
    def _get_parent_location(self):
        """Set the parent branch"""
        return self._get_config_location('parent_location')

    def set_push_location(self, location):
        """See Branch.set_push_location."""
        self._set_config_location('push_location', location)

    def set_bound_location(self, location):
        """See Branch.set_push_location."""
        result = None
        config = self.get_config()
        if location is None:
            if config.get_user_option('bound') != 'True':
                return False
            else:
                config.set_user_option('bound', 'False')
                return True
        else:
            self._set_config_location('bound_location', location,
                                      config=config)
            config.set_user_option('bound', 'True')
        return True

    def _get_bound_location(self, bound):
        """Return the bound location in the config file.

        Return None if the bound parameter does not match"""
        config = self.get_config()
        config_bound = (config.get_user_option('bound') == 'True')
        if config_bound != bound:
            return None
        return self._get_config_location('bound_location', config=config)

    def get_bound_location(self):
        """See Branch.set_push_location."""
        return self._get_bound_location(True)

    def get_old_bound_location(self):
        """See Branch.get_old_bound_location"""
        return self._get_bound_location(False)

    def set_append_revisions_only(self, enabled):
        if enabled:
            value = 'True'
        else:
            value = 'False'
        self.get_config().set_user_option('append_revisions_only', value)

    def _get_append_revisions_only(self):
        value = self.get_config().get_user_option('append_revisions_only')
        return value == 'True'

    def _synchronize_history(self, destination, revision_id):
        """Synchronize last revision and revision history between branches.

        This version is most efficient when the destination is also a
        BzrBranch6, but works for BzrBranch5, as long as the destination's
        repository contains all the lefthand ancestors of the intended
        last_revision.  If not, set_last_revision_info will fail.

        :param destination: The branch to copy the history into
        :param revision_id: The revision-id to truncate history at.  May
          be None to copy complete history.
        """
        if revision_id is None:
            revno, revision_id = self.last_revision_info()
        else:
            revno = self.revision_id_to_revno(revision_id)
        destination.set_last_revision_info(revno, revision_id)

    def _make_tags(self):
        return BasicTags(self)


class BranchTestProviderAdapter(object):
    """A tool to generate a suite testing multiple branch formats at once.

    This is done by copying the test once for each transport and injecting
    the transport_server, transport_readonly_server, and branch_format
    classes into each copy. Each copy is also given a new id() to make it
    easy to identify.
    """

    def __init__(self, transport_server, transport_readonly_server, formats):
        self._transport_server = transport_server
        self._transport_readonly_server = transport_readonly_server
        self._formats = formats
    
    def adapt(self, test):
        result = TestSuite()
        for branch_format, bzrdir_format in self._formats:
            new_test = deepcopy(test)
            new_test.transport_server = self._transport_server
            new_test.transport_readonly_server = self._transport_readonly_server
            new_test.bzrdir_format = bzrdir_format
            new_test.branch_format = branch_format
            def make_new_test_id():
                # the format can be either a class or an instance
                name = getattr(branch_format, '__name__',
                        branch_format.__class__.__name__)
                new_id = "%s(%s)" % (new_test.id(), name)
                return lambda: new_id
            new_test.id = make_new_test_id()
            result.addTest(new_test)
        return result


######################################################################
# results of operations


class _Result(object):

    def _show_tag_conficts(self, to_file):
        if not getattr(self, 'tag_conflicts', None):
            return
        to_file.write('Conflicting tags:\n')
        for name, value1, value2 in self.tag_conflicts:
            to_file.write('    %s\n' % (name, ))


class PullResult(_Result):
    """Result of a Branch.pull operation.

    :ivar old_revno: Revision number before pull.
    :ivar new_revno: Revision number after pull.
    :ivar old_revid: Tip revision id before pull.
    :ivar new_revid: Tip revision id after pull.
    :ivar source_branch: Source (local) branch object.
    :ivar master_branch: Master branch of the target, or None.
    :ivar target_branch: Target/destination branch object.
    """

    def __int__(self):
        # DEPRECATED: pull used to return the change in revno
        return self.new_revno - self.old_revno

    def report(self, to_file):
        if self.old_revid == self.new_revid:
            to_file.write('No revisions to pull.\n')
        else:
            to_file.write('Now on revision %d.\n' % self.new_revno)
        self._show_tag_conficts(to_file)


class PushResult(_Result):
    """Result of a Branch.push operation.

    :ivar old_revno: Revision number before push.
    :ivar new_revno: Revision number after push.
    :ivar old_revid: Tip revision id before push.
    :ivar new_revid: Tip revision id after push.
    :ivar source_branch: Source branch object.
    :ivar master_branch: Master branch of the target, or None.
    :ivar target_branch: Target/destination branch object.
    """

    def __int__(self):
        # DEPRECATED: push used to return the change in revno
        return self.new_revno - self.old_revno

    def report(self, to_file):
        """Write a human-readable description of the result."""
        if self.old_revid == self.new_revid:
            to_file.write('No new revisions to push.\n')
        else:
            to_file.write('Pushed up to revision %d.\n' % self.new_revno)
        self._show_tag_conficts(to_file)


class BranchCheckResult(object):
    """Results of checking branch consistency.

    :see: Branch.check
    """

    def __init__(self, branch):
        self.branch = branch

    def report_results(self, verbose):
        """Report the check results via trace.note.
        
        :param verbose: Requests more detailed display of what was checked,
            if any.
        """
        note('checked branch %s format %s',
             self.branch.base,
             self.branch._format)


class Converter5to6(object):
    """Perform an in-place upgrade of format 5 to format 6"""

    def convert(self, branch):
        # Data for 5 and 6 can peacefully coexist.
        format = BzrBranchFormat6()
        new_branch = format.open(branch.bzrdir, _found=True)

        # Copy source data into target
        new_branch.set_last_revision_info(*branch.last_revision_info())
        new_branch.set_parent(branch.get_parent())
        new_branch.set_bound_location(branch.get_bound_location())
        new_branch.set_push_location(branch.get_push_location())

        # New branch has no tags by default
        new_branch.tags._set_tag_dict({})

        # Copying done; now update target format
        new_branch.control_files.put_utf8('format',
            format.get_format_string())

        # Clean up old files
        new_branch.control_files._transport.delete('revision-history')
        try:
            branch.set_parent(None)
        except NoSuchFile:
            pass
        branch.set_bound_location(None)
