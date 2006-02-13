# Copyright (C) 2005 Canonical Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


from copy import deepcopy
from cStringIO import StringIO
import errno
import os
import shutil
import sys
from unittest import TestSuite
from warnings import warn
try:
    import xml.sax.saxutils
except ImportError:
    raise ImportError("We were unable to import 'xml.sax.saxutils',"
                      " most likely you have an xml.pyc or xml.pyo file"
                      " lying around in your bzrlib directory."
                      " Please remove it.")
from cStringIO import StringIO


import bzrlib
from bzrlib.config import TreeConfig
from bzrlib.decorators import needs_read_lock, needs_write_lock
from bzrlib.delta import compare_trees
import bzrlib.errors as errors
from bzrlib.errors import (BzrError, InvalidRevisionNumber, InvalidRevisionId,
                           NoSuchRevision, HistoryMissing, NotBranchError,
                           DivergedBranches, LockError,
                           UninitializableFormat,
                           UnlistableStore,
                           UnlistableBranch, NoSuchFile, NotVersionedError,
                           NoWorkingTree)
import bzrlib.inventory as inventory
from bzrlib.inventory import Inventory
from bzrlib.lockable_files import LockableFiles
from bzrlib.osutils import (isdir, quotefn,
                            rename, splitpath, sha_file,
                            file_kind, abspath, normpath, pathjoin,
                            safe_unicode,
                            )
from bzrlib.textui import show_status
from bzrlib.trace import mutter, note
from bzrlib.tree import EmptyTree, RevisionTree
from bzrlib.repository import Repository
from bzrlib.revision import (Revision, is_ancestor, get_intervening_revisions)
from bzrlib.store import copy_all
from bzrlib.symbol_versioning import *
import bzrlib.transactions as transactions
from bzrlib.transport import Transport, get_transport
from bzrlib.tree import EmptyTree, RevisionTree
import bzrlib.ui
import bzrlib.xml5


BZR_BRANCH_FORMAT_4 = "Bazaar-NG branch, format 0.0.4\n"
BZR_BRANCH_FORMAT_5 = "Bazaar-NG branch, format 5\n"
BZR_BRANCH_FORMAT_6 = "Bazaar-NG branch, format 6\n"


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
    """
    # this is really an instance variable - FIXME move it there
    # - RBC 20060112
    base = None

    _default_initializer = None
    """The default initializer for making new branches."""

    def __init__(self, *ignored, **ignored_too):
        raise NotImplementedError('The Branch class is abstract')

    @staticmethod
    def open_downlevel(base):
        """Open a branch which may be of an old format."""
        return Branch.open(base, _unsupported=True)
        
    @staticmethod
    def open(base, _unsupported=False):
        """Open an existing branch, rooted at 'base' (url)
        
        _unsupported is a private parameter to the Branch class.
        """
        t = get_transport(base)
        mutter("trying to open %r with transport %r", base, t)
        format = BzrBranchFormat.find_format(t)
        if not _unsupported and not format.is_supported():
            # see open_downlevel to open legacy branches.
            raise errors.UnsupportedFormatError(
                    'sorry, branch format %s not supported' % format,
                    ['use a different bzr version',
                     'or remove the .bzr directory'
                     ' and "bzr init" again'])
        return format.open(t)

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
        t = get_transport(url)
        # this gets the normalised url back. I.e. '.' -> the full path.
        url = t.base
        while True:
            try:
                format = BzrBranchFormat.find_format(t)
                return format.open(t), t.relpath(url)
            except NotBranchError, e:
                mutter('not a branch in: %r %s', t.base, e)
            new_t = t.clone('..')
            if new_t.base == t.base:
                # reached the root, whatever that may be
                raise NotBranchError(path=url)
            t = new_t

    @staticmethod
    def create(base):
        """Create a new Branch at the url 'bzr'.
        
        This will call the current default initializer with base
        as the only parameter.
        """
        return Branch._default_initializer(safe_unicode(base))

    @staticmethod
    @deprecated_function(zero_eight)
    def initialize(base):
        """Create a new working tree and branch, rooted at 'base' (url)

        NOTE: This will soon be deprecated in favour of creation
        through a BzrDir.
        """
        # imported here to prevent scope creep as this is going.
        from bzrlib.workingtree import WorkingTree
        return WorkingTree.create_standalone(safe_unicode(base)).branch

    @staticmethod
    def get_default_initializer():
        """Return the initializer being used for new branches."""
        return Branch._default_initializer

    @staticmethod
    def set_default_initializer(initializer):
        """Set the initializer to be used for new branches."""
        Branch._default_initializer = staticmethod(initializer)

    def setup_caching(self, cache_root):
        """Subclasses that care about caching should override this, and set
        up cached stores located under cache_root.
        """
        # seems to be unused, 2006-01-13 mbp
        warn('%s is deprecated' % self.setup_caching)
        self.cache_root = cache_root

    def _get_nick(self):
        cfg = self.tree_config()
        return cfg.get_option(u"nickname", default=self.base.split('/')[-2])

    def _set_nick(self, nick):
        cfg = self.tree_config()
        cfg.set_option(nick, "nickname")
        assert cfg.get_option("nickname") == nick

    nick = property(_get_nick, _set_nick)
        
    def push_stores(self, branch_to):
        """Copy the content of this branches store to branch_to."""
        raise NotImplementedError('push_stores is abstract')

    def lock_write(self):
        raise NotImplementedError('lock_write is abstract')
        
    def lock_read(self):
        raise NotImplementedError('lock_read is abstract')

    def unlock(self):
        raise NotImplementedError('unlock is abstract')

    def peek_lock_mode(self):
        """Return lock mode for the Branch: 'r', 'w' or None"""
        raise NotImplementedError(self.peek_lock_mode)

    def abspath(self, name):
        """Return absolute filename for something in the branch
        
        XXX: Robert Collins 20051017 what is this used for? why is it a branch
        method and not a tree method.
        """
        raise NotImplementedError('abspath is abstract')

    def get_root_id(self):
        """Return the id of this branches root"""
        raise NotImplementedError('get_root_id is abstract')

    def print_file(self, file, revision_id):
        """Print `file` to stdout."""
        raise NotImplementedError('print_file is abstract')

    def append_revision(self, *revision_ids):
        raise NotImplementedError('append_revision is abstract')

    def set_revision_history(self, rev_history):
        raise NotImplementedError('set_revision_history is abstract')

    def revision_history(self):
        """Return sequence of revision hashes on to this branch."""
        raise NotImplementedError('revision_history is abstract')

    def revno(self):
        """Return current revision number for this branch.

        That is equivalent to the number of revisions committed to
        this branch.
        """
        return len(self.revision_history())

    def last_revision(self):
        """Return last patch hash, or None if no history."""
        ph = self.revision_history()
        if ph:
            return ph[-1]
        else:
            return None

    def missing_revisions(self, other, stop_revision=None, diverged_ok=False):
        """Return a list of new revisions that would perfectly fit.
        
        If self and other have not diverged, return a list of the revisions
        present in other, but missing from self.

        >>> bzrlib.trace.silent = True
        >>> br1 = ScratchBranch()
        >>> br2 = ScratchBranch()
        >>> br1.missing_revisions(br2)
        []
        >>> br2.working_tree().commit("lala!", rev_id="REVISION-ID-1")
        >>> br1.missing_revisions(br2)
        [u'REVISION-ID-1']
        >>> br2.missing_revisions(br1)
        []
        >>> br1.working_tree().commit("lala!", rev_id="REVISION-ID-1")
        >>> br1.missing_revisions(br2)
        []
        >>> br2.working_tree().commit("lala!", rev_id="REVISION-ID-2A")
        >>> br1.missing_revisions(br2)
        [u'REVISION-ID-2A']
        >>> br1.working_tree().commit("lala!", rev_id="REVISION-ID-2B")
        >>> br1.missing_revisions(br2)
        Traceback (most recent call last):
        DivergedBranches: These branches have diverged.  Try merge.
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
                raise bzrlib.errors.NoSuchRevision(self, stop_revision)
        return other_history[self_len:stop_revision]

    def update_revisions(self, other, stop_revision=None):
        """Pull in new perfect-fit revisions."""
        raise NotImplementedError('update_revisions is abstract')

    def pullable_revisions(self, other, stop_revision):
        raise NotImplementedError('pullable_revisions is abstract')
        
    def revision_id_to_revno(self, revision_id):
        """Given a revision id, return its revno"""
        if revision_id is None:
            return 0
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
        elif revno <= 0 or revno > len(history):
            raise bzrlib.errors.NoSuchRevision(self, revno)
        return history[revno - 1]

    def working_tree(self):
        """Return a `Tree` for the working copy if this is a local branch."""
        raise NotImplementedError('working_tree is abstract')

    def pull(self, source, overwrite=False):
        raise NotImplementedError('pull is abstract')

    def basis_tree(self):
        """Return `Tree` object for last revision.

        If there are no revisions yet, return an `EmptyTree`.
        """
        return self.repository.revision_tree(self.last_revision())

    def rename_one(self, from_rel, to_rel):
        """Rename one file.

        This can change the directory or the filename or both.
        """
        raise NotImplementedError('rename_one is abstract')

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
        raise NotImplementedError('move is abstract')

    def get_parent(self):
        """Return the parent location of the branch.

        This is the default location for push/pull/missing.  The usual
        pattern is that the user can override it by specifying a
        location.
        """
        raise NotImplementedError('get_parent is abstract')

    def get_push_location(self):
        """Return the None or the location to push this branch to."""
        raise NotImplementedError('get_push_location is abstract')

    def set_push_location(self, location):
        """Set a new push location for this branch."""
        raise NotImplementedError('set_push_location is abstract')

    def set_parent(self, url):
        raise NotImplementedError('set_parent is abstract')

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
        
    def clone(self, to_location, revision=None, basis_branch=None, to_branch_type=None):
        """Copy this branch into the existing directory to_location.

        Returns the newly created branch object.

        revision
            If not None, only revisions up to this point will be copied.
            The head of the new branch will be that revision.  Must be a
            revid or None.
    
        to_location -- The destination directory; must either exist and be 
            empty, or not exist, in which case it is created.
    
        basis_branch
            A local branch to copy revisions from, related to this branch. 
            This is used when branching from a remote (slow) branch, and we have
            a local branch that might contain some relevant revisions.
    
        to_branch_type
            Branch type of destination branch
        """
        from bzrlib.workingtree import WorkingTree
        assert isinstance(to_location, basestring)
        if not bzrlib.osutils.lexists(to_location):
            os.mkdir(to_location)
        if to_branch_type is None:
            to_branch_type = BzrBranch
        # FIXME use a branch format here
        br_to = to_branch_type.initialize(to_location)
        mutter("copy branch from %s to %s", self, br_to)
        if basis_branch is not None:
            basis_branch.push_stores(br_to)
        if revision is None:
            revision = self.last_revision()
        br_to.update_revisions(self, stop_revision=revision)
        br_to.set_parent(self.base)
        WorkingTree.create(br_to, to_location).set_root_id(self.get_root_id())
        mutter("copied")
        return br_to

    def fileid_involved_between_revs(self, from_revid, to_revid):
        """ This function returns the file_id(s) involved in the
            changes between the from_revid revision and the to_revid
            revision
        """
        raise NotImplementedError('fileid_involved_between_revs is abstract')

    def fileid_involved(self, last_revid=None):
        """ This function returns the file_id(s) involved in the
            changes up to the revision last_revid
            If no parametr is passed, then all file_id[s] present in the
            repository are returned
        """
        raise NotImplementedError('fileid_involved is abstract')

    def fileid_involved_by_set(self, changes):
        """ This function returns the file_id(s) involved in the
            changes present in the set 'changes'
        """
        raise NotImplementedError('fileid_involved_by_set is abstract')

    def fileid_involved_between_revs(self, from_revid, to_revid):
        """ This function returns the file_id(s) involved in the
            changes between the from_revid revision and the to_revid
            revision
        """
        raise NotImplementedError('fileid_involved_between_revs is abstract')

    def fileid_involved(self, last_revid=None):
        """ This function returns the file_id(s) involved in the
            changes up to the revision last_revid
            If no parametr is passed, then all file_id[s] present in the
            repository are returned
        """
        raise NotImplementedError('fileid_involved is abstract')

    def fileid_involved_by_set(self, changes):
        """ This function returns the file_id(s) involved in the
            changes present in the set 'changes'
        """
        raise NotImplementedError('fileid_involved_by_set is abstract')

class BzrBranchFormat(object):
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

    _formats = {}
    """The known formats."""

    @classmethod
    def find_format(klass, transport):
        """Return the format registered for URL."""
        try:
            format_string = transport.get(".bzr/branch-format").read()
            return klass._formats[format_string]
        except NoSuchFile:
            raise NotBranchError(path=transport.base)
        except KeyError:
            raise errors.UnknownFormatError(format_string)

    def get_format_string(self):
        """Return the ASCII format string that identifies this format."""
        raise NotImplementedError(self.get_format_string)

    def _find_modes(self, t):
        """Determine the appropriate modes for files and directories.
        
        FIXME: When this merges into, or from storage,
        this code becomes delgatable to a LockableFiles instance.

        For now its cribbed and returns (dir_mode, file_mode)
        """
        try:
            st = t.stat('.')
        except errors.TransportNotPossible:
            dir_mode = 0755
            file_mode = 0644
        else:
            dir_mode = st.st_mode & 07777
            # Remove the sticky and execute bits for files
            file_mode = dir_mode & ~07111
        if not BzrBranch._set_dir_mode:
            dir_mode = None
        if not BzrBranch._set_file_mode:
            file_mode = None
        return dir_mode, file_mode

    def initialize(self, url):
        """Create a branch of this format at url and return an open branch."""
        t = get_transport(url)
        from bzrlib.weavefile import write_weave_v5
        from bzrlib.weave import Weave
        
        # Create an empty weave
        sio = StringIO()
        bzrlib.weavefile.write_weave_v5(Weave(), sio)
        empty_weave = sio.getvalue()

        # Since we don't have a .bzr directory, inherit the
        # mode from the root directory
        temp_control = LockableFiles(t, '')
        temp_control._transport.mkdir('.bzr',
                                      mode=temp_control._dir_mode)
        file_mode = temp_control._file_mode
        del temp_control
        mutter('created control directory in ' + t.base)
        control = t.clone('.bzr')
        dirs = ['revision-store', 'weaves']
        lock_file = 'branch-lock'
        utf8_files = [('README', 
                       "This is a Bazaar-NG control directory.\n"
                       "Do not change any files in this directory.\n"),
                      ('branch-format', self.get_format_string()),
                      ('revision-history', ''),
                      ('branch-name', ''),
                      ]
        files = [('inventory.weave', StringIO(empty_weave)), 
                 ]
        
        # FIXME: RBC 20060125 dont peek under the covers
        # NB: no need to escape relative paths that are url safe.
        control.put(lock_file, StringIO(), mode=file_mode)
        control_files = LockableFiles(control, lock_file)
        control_files.lock_write()
        control_files._transport.mkdir_multi(dirs,
                mode=control_files._dir_mode)
        try:
            for file, content in utf8_files:
                control_files.put_utf8(file, content)
            for file, content in files:
                control_files.put(file, content)
        finally:
            control_files.unlock()
        return BzrBranch(t, _format=self, _control_files=control_files)

    def is_supported(self):
        """Is this format supported?

        Supported formats can be initialized and opened.
        Unsupported formats may not support initialization or committing or 
        some other features depending on the reason for not being supported.
        """
        return True

    def open(self, transport):
        """Fill out the data in branch for the branch at url."""
        return BzrBranch(transport, _format=self)

    @classmethod
    def register_format(klass, format):
        klass._formats[format.get_format_string()] = format

    @classmethod
    def unregister_format(klass, format):
        assert klass._formats[format.get_format_string()] is format
        del klass._formats[format.get_format_string()]


class BzrBranchFormat4(BzrBranchFormat):
    """Bzr branch format 4.

    This format has:
     - flat stores
     - TextStores for texts, inventories,revisions.

    This format is deprecated: it indexes texts using a text it which is
    removed in format 5; write support for this format has been removed.
    """

    def get_format_string(self):
        """See BzrBranchFormat.get_format_string()."""
        return BZR_BRANCH_FORMAT_4

    def initialize(self, url):
        """Format 4 branches cannot be created."""
        raise UninitializableFormat(self)

    def is_supported(self):
        """Format 4 is not supported.

        It is not supported because the model changed from 4 to 5 and the
        conversion logic is expensive - so doing it on the fly was not 
        feasible.
        """
        return False


class BzrBranchFormat5(BzrBranchFormat):
    """Bzr branch format 5.

    This format has:
     - weaves for file texts and inventory
     - flat stores
     - TextStores for revisions and signatures.
    """

    def get_format_string(self):
        """See BzrBranchFormat.get_format_string()."""
        return BZR_BRANCH_FORMAT_5


class BzrBranchFormat6(BzrBranchFormat):
    """Bzr branch format 6.

    This format has:
     - weaves for file texts and inventory
     - hash subdirectory based stores.
     - TextStores for revisions and signatures.
    """

    def get_format_string(self):
        """See BzrBranchFormat.get_format_string()."""
        return BZR_BRANCH_FORMAT_6


BzrBranchFormat.register_format(BzrBranchFormat4())
BzrBranchFormat.register_format(BzrBranchFormat5())
BzrBranchFormat.register_format(BzrBranchFormat6())

# TODO: jam 20060108 Create a new branch format, and as part of upgrade
#       make sure that ancestry.weave is deleted (it is never used, but
#       used to be created)


class BzrBranch(Branch):
    """A branch stored in the actual filesystem.

    Note that it's "local" in the context of the filesystem; it doesn't
    really matter if it's on an nfs/smb/afs/coda/... share, as long as
    it's writable, and can be accessed via the normal filesystem API.

    """
    # We actually expect this class to be somewhat short-lived; part of its
    # purpose is to try to isolate what bits of the branch logic are tied to
    # filesystem access, so that in a later step, we can extricate them to
    # a separarte ("storage") class.
    _inventory_weave = None
    
    # Map some sort of prefix into a namespace
    # stuff like "revno:10", "revid:", etc.
    # This should match a prefix with a function which accepts
    REVISION_NAMESPACES = {}

    def push_stores(self, branch_to):
        """See Branch.push_stores."""
        if (not isinstance(self._branch_format, BzrBranchFormat4) or
            self._branch_format != branch_to._branch_format):
            from bzrlib.fetch import greedy_fetch
            mutter("Using fetch logic to push between %s(%s) and %s(%s)",
                   self, self._branch_format, branch_to, branch_to._branch_format)
            greedy_fetch(to_branch=branch_to, from_branch=self,
                         revision=self.last_revision())
            return

        # format 4 to format 4 logic only.
        store_pairs = ((self.text_store,      branch_to.text_store),
                       (self.inventory_store, branch_to.inventory_store),
                       (self.revision_store,  branch_to.revision_store))
        try:
            for from_store, to_store in store_pairs: 
                copy_all(from_store, to_store)
        except UnlistableStore:
            raise UnlistableBranch(from_store)

    def __init__(self, transport, init=DEPRECATED_PARAMETER,
                 relax_version_check=DEPRECATED_PARAMETER, _format=None,
                 _control_files=None):
        """Create new branch object at a particular location.

        transport -- A Transport object, defining how to access files.
        
        init -- If True, create new control files in a previously
             unversioned directory.  If False, the branch must already
             be versioned.

        relax_version_check -- If true, the usual check for the branch
            version is not applied.  This is intended only for
            upgrade/recovery type use; it's not guaranteed that
            all operations will work on old format branches.

        In the test suite, creation of new trees is tested using the
        `ScratchBranch` class.
        """
        assert isinstance(transport, Transport), \
            "%r is not a Transport" % transport
        self._transport = transport
        self._base = self._transport.base
        if _control_files is None:
            _control_files = LockableFiles(self._transport.clone(bzrlib.BZRDIR),
                                           'branch-lock')
        self.control_files = _control_files
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
                 "Please use Branch.open_downlevel, or a BzrBranchFormat's "
                 "open() method.",
                 DeprecationWarning,
                 stacklevel=2)
            if (not relax_version_check
                and not self._branch_format.is_supported()):
                raise errors.UnsupportedFormatError(
                        'sorry, branch format %r not supported' % fmt,
                        ['use a different bzr version',
                         'or remove the .bzr directory'
                         ' and "bzr init" again'])
        self.repository = Repository(transport, self._branch_format)


    @staticmethod
    def _initialize(base):
        """Create a bzr branch in the latest format."""
        return BzrBranchFormat6().initialize(base)

    def __str__(self):
        return '%s(%r)' % (self.__class__.__name__, self.base)

    __repr__ = __str__

    def __del__(self):
        # TODO: It might be best to do this somewhere else,
        # but it is nice for a Branch object to automatically
        # cache it's information.
        # Alternatively, we could have the Transport objects cache requests
        # See the earlier discussion about how major objects (like Branch)
        # should never expect their __del__ function to run.
        # XXX: cache_root seems to be unused, 2006-01-13 mbp
        if hasattr(self, 'cache_root') and self.cache_root is not None:
            try:
                shutil.rmtree(self.cache_root)
            except:
                pass
            self.cache_root = None

    def _get_base(self):
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
        self._branch_format for code that needs to check it later.

        The format parameter is either None or the branch format class
        used to open this branch.
        """
        if format is None:
            format = BzrBranchFormat.find_format(self._transport)
        self._branch_format = format
        mutter("got branch format %s", self._branch_format)

    @needs_read_lock
    def get_root_id(self):
        """See Branch.get_root_id."""
        tree = self.repository.revision_tree(self.last_revision())
        return tree.inventory.root.file_id

    def lock_write(self):
        # TODO: test for failed two phase locks. This is known broken.
        self.control_files.lock_write()
        self.repository.lock_write()

    def lock_read(self):
        # TODO: test for failed two phase locks. This is known broken.
        self.control_files.lock_read()
        self.repository.lock_read()

    def unlock(self):
        # TODO: test for failed two phase locks. This is known broken.
        self.repository.unlock()
        self.control_files.unlock()

    def peek_lock_mode(self):
        if self.control_files._lock_count == 0:
            return None
        else:
            return self.control_files._lock_mode

    @needs_read_lock
    def print_file(self, file, revision_id):
        """See Branch.print_file."""
        return self.repository.print_file(file, revision_id)

    @needs_write_lock
    def append_revision(self, *revision_ids):
        """See Branch.append_revision."""
        for revision_id in revision_ids:
            mutter("add {%s} to revision-history" % revision_id)
        rev_history = self.revision_history()
        rev_history.extend(revision_ids)
        self.set_revision_history(rev_history)

    @needs_write_lock
    def set_revision_history(self, rev_history):
        """See Branch.set_revision_history."""
        self.control_files.put_utf8(
            'revision-history', '\n'.join(rev_history))

    def get_revision_delta(self, revno):
        """Return the delta for one revision.

        The delta is relative to its mainline predecessor, or the
        empty tree for revision 1.
        """
        assert isinstance(revno, int)
        rh = self.revision_history()
        if not (1 <= revno <= len(rh)):
            raise InvalidRevisionNumber(revno)

        # revno is 1-based; list is 0-based

        new_tree = self.repository.revision_tree(rh[revno-1])
        if revno == 1:
            old_tree = EmptyTree()
        else:
            old_tree = self.repository.revision_tree(rh[revno-2])
        return compare_trees(old_tree, new_tree)

    @needs_read_lock
    def revision_history(self):
        """See Branch.revision_history."""
        # FIXME are transactions bound to control files ? RBC 20051121
        transaction = self.get_transaction()
        history = transaction.map.find_revision_history()
        if history is not None:
            mutter("cache hit for revision-history in %s", self)
            return list(history)
        history = [l.rstrip('\r\n') for l in
                self.control_files.get_utf8('revision-history').readlines()]
        transaction.map.add_revision_history(history)
        # this call is disabled because revision_history is 
        # not really an object yet, and the transaction is for objects.
        # transaction.register_clean(history, precious=True)
        return list(history)

    def update_revisions(self, other, stop_revision=None):
        """See Branch.update_revisions."""
        from bzrlib.fetch import greedy_fetch
        if stop_revision is None:
            stop_revision = other.last_revision()
        ### Should this be checking is_ancestor instead of revision_history?
        if (stop_revision is not None and 
            stop_revision in self.revision_history()):
            return
        greedy_fetch(to_branch=self, from_branch=other,
                     revision=stop_revision)
        pullable_revs = self.pullable_revisions(other, stop_revision)
        if len(pullable_revs) > 0:
            self.append_revision(*pullable_revs)

    def pullable_revisions(self, other, stop_revision):
        """See Branch.pullable_revisions."""
        other_revno = other.revision_id_to_revno(stop_revision)
        try:
            return self.missing_revisions(other, other_revno)
        except DivergedBranches, e:
            try:
                pullable_revs = get_intervening_revisions(self.last_revision(),
                                                          stop_revision, 
                                                          self.repository)
                assert self.last_revision() not in pullable_revs
                return pullable_revs
            except bzrlib.errors.NotAncestor:
                if is_ancestor(self.last_revision(), stop_revision, self):
                    return []
                else:
                    raise e
        
    def basis_tree(self):
        """See Branch.basis_tree."""
        try:
            revision_id = self.revision_history()[-1]
            # FIXME: This is an abstraction violation, the basis tree 
            # here as defined is on the working tree, the method should
            # be too. The basis tree for a branch can be different than
            # that for a working tree. RBC 20051207
            xml = self.working_tree().read_basis_inventory(revision_id)
            inv = bzrlib.xml5.serializer_v5.read_inventory_from_string(xml)
            return RevisionTree(self.repository, inv, revision_id)
        except (IndexError, NoSuchFile, NoWorkingTree), e:
            return self.repository.revision_tree(self.last_revision())

    def working_tree(self):
        """See Branch.working_tree."""
        from bzrlib.workingtree import WorkingTree
        from bzrlib.transport.local import LocalTransport
        if (self.base.find('://') != -1 or 
            not isinstance(self._transport, LocalTransport)):
            raise NoWorkingTree(self.base)
        return WorkingTree(self.base, branch=self)

    @needs_write_lock
    def pull(self, source, overwrite=False):
        """See Branch.pull."""
        source.lock_read()
        try:
            old_count = len(self.revision_history())
            try:
                self.update_revisions(source)
            except DivergedBranches:
                if not overwrite:
                    raise
            if overwrite:
                self.set_revision_history(source.revision_history())
            new_count = len(self.revision_history())
            return new_count - old_count
        finally:
            source.unlock()

    def get_parent(self):
        """See Branch.get_parent."""
        import errno
        _locs = ['parent', 'pull', 'x-pull']
        for l in _locs:
            try:
                return self.control_files.get_utf8(l).read().strip('\n')
            except NoSuchFile:
                pass
        return None

    def get_push_location(self):
        """See Branch.get_push_location."""
        config = bzrlib.config.BranchConfig(self)
        push_loc = config.get_user_option('push_location')
        return push_loc

    def set_push_location(self, location):
        """See Branch.set_push_location."""
        config = bzrlib.config.LocationConfig(self.base)
        config.set_user_option('push_location', location)

    @needs_write_lock
    def set_parent(self, url):
        """See Branch.set_parent."""
        # TODO: Maybe delete old location files?
        # URLs should never be unicode, even on the local fs,
        # FIXUP this and get_parent in a future branch format bump:
        # read and rewrite the file, and have the new format code read
        # using .get not .get_utf8. RBC 20060125
        self.control_files.put_utf8('parent', url + '\n')

    def tree_config(self):
        return TreeConfig(self)

    def _get_truncated_history(self, revision_id):
        history = self.revision_history()
        if revision_id is None:
            return history
        try:
            idx = history.index(revision_id)
        except ValueError:
            raise InvalidRevisionId(revision_id=revision, branch=self)
        return history[:idx+1]

    @needs_read_lock
    def _clone_weave(self, to_location, revision=None, basis_branch=None):
        # prevent leakage
        from bzrlib.workingtree import WorkingTree
        assert isinstance(to_location, basestring)
        if basis_branch is not None:
            note("basis_branch is not supported for fast weave copy yet.")

        history = self._get_truncated_history(revision)
        if not bzrlib.osutils.lexists(to_location):
            os.mkdir(to_location)
        branch_to = Branch.initialize(to_location)
        mutter("copy branch from %s to %s", self, branch_to)

        self.repository.copy(branch_to.repository)
        
        # must be done *after* history is copied across
        # FIXME duplicate code with base .clone().
        # .. would template method be useful here?  RBC 20051207
        branch_to.set_parent(self.base)
        branch_to.append_revision(*history)
        # FIXME: this should be in workingtree.clone
        WorkingTree.create(branch_to, to_location).set_root_id(self.get_root_id())
        mutter("copied")
        return branch_to

    def clone(self, to_location, revision=None, basis_branch=None, to_branch_type=None):
        # FIXME: clone via create and fetch is probably faster when versioned
        # file comes in.
        if to_branch_type is None:
            to_branch_type = BzrBranch

        if to_branch_type == BzrBranch \
            and self.repository.weave_store.listable() \
            and self.repository.revision_store.listable():
            return self._clone_weave(to_location, revision, basis_branch)

        return Branch.clone(self, to_location, revision, basis_branch, to_branch_type)

    def fileid_involved_between_revs(self, from_revid, to_revid):
        """Find file_id(s) which are involved in the changes between revisions.

        This determines the set of revisions which are involved, and then
        finds all file ids affected by those revisions.
        """
        # TODO: jam 20060119 This code assumes that w.inclusions will
        #       always be correct. But because of the presence of ghosts
        #       it is possible to be wrong.
        #       One specific example from Robert Collins:
        #       Two branches, with revisions ABC, and AD
        #       C is a ghost merge of D.
        #       Inclusions doesn't recognize D as an ancestor.
        #       If D is ever merged in the future, the weave
        #       won't be fixed, because AD never saw revision C
        #       to cause a conflict which would force a reweave.
        w = self.repository.get_inventory_weave()
        from_set = set(w.inclusions([w.lookup(from_revid)]))
        to_set = set(w.inclusions([w.lookup(to_revid)]))
        included = to_set.difference(from_set)
        changed = map(w.idx_to_name, included)
        return self._fileid_involved_by_set(changed)

    def fileid_involved(self, last_revid=None):
        """Find all file_ids modified in the ancestry of last_revid.

        :param last_revid: If None, last_revision() will be used.
        """
        w = self.repository.get_inventory_weave()
        if not last_revid:
            changed = set(w._names)
        else:
            included = w.inclusions([w.lookup(last_revid)])
            changed = map(w.idx_to_name, included)
        return self._fileid_involved_by_set(changed)

    def fileid_involved_by_set(self, changes):
        """Find all file_ids modified by the set of revisions passed in.

        :param changes: A set() of revision ids
        """
        # TODO: jam 20060119 This line does *nothing*, remove it.
        #       or better yet, change _fileid_involved_by_set so
        #       that it takes the inventory weave, rather than
        #       pulling it out by itself.
        w = self.repository.get_inventory_weave()
        return self._fileid_involved_by_set(changes)

    def _fileid_involved_by_set(self, changes):
        """Find the set of file-ids affected by the set of revisions.

        :param changes: A set() of revision ids.
        :return: A set() of file ids.
        
        This peaks at the Weave, interpreting each line, looking to
        see if it mentions one of the revisions. And if so, includes
        the file id mentioned.
        This expects both the Weave format, and the serialization
        to have a single line per file/directory, and to have
        fileid="" and revision="" on that line.
        """
        assert (isinstance(self._branch_format, BzrBranchFormat5) or
                isinstance(self._branch_format, BzrBranchFormat6)), \
            "fileid_involved only supported for branches which store inventory as xml"

        w = self.repository.get_inventory_weave()
        file_ids = set()
        for line in w._weave:

            # it is ugly, but it is due to the weave structure
            if not isinstance(line, basestring): continue

            start = line.find('file_id="')+9
            if start < 9: continue
            end = line.find('"', start)
            assert end>= 0
            file_id = xml.sax.saxutils.unescape(line[start:end])

            # check if file_id is already present
            if file_id in file_ids: continue

            start = line.find('revision="')+10
            if start < 10: continue
            end = line.find('"', start)
            assert end>= 0
            revision_id = xml.sax.saxutils.unescape(line[start:end])

            if revision_id in changes:
                file_ids.add(file_id)

        return file_ids


Branch.set_default_initializer(BzrBranch._initialize)


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
        for format in self._formats:
            new_test = deepcopy(test)
            new_test.transport_server = self._transport_server
            new_test.transport_readonly_server = self._transport_readonly_server
            new_test.branch_format = format
            def make_new_test_id():
                new_id = "%s(%s)" % (new_test.id(), format.__class__.__name__)
                return lambda: new_id
            new_test.id = make_new_test_id()
            result.addTest(new_test)
        return result


class ScratchBranch(BzrBranch):
    """Special test class: a branch that cleans up after itself.

    >>> b = ScratchBranch()
    >>> isdir(b.base)
    True
    >>> bd = b.base
    >>> b._transport.__del__()
    >>> isdir(bd)
    False
    """

    def __init__(self, files=[], dirs=[], transport=None):
        """Make a test branch.

        This creates a temporary directory and runs init-tree in it.

        If any files are listed, they are created in the working copy.
        """
        if transport is None:
            transport = bzrlib.transport.local.ScratchTransport()
            # local import for scope restriction
            from bzrlib.workingtree import WorkingTree
            WorkingTree.create_standalone(transport.base)
            super(ScratchBranch, self).__init__(transport)
        else:
            super(ScratchBranch, self).__init__(transport)

        # BzrBranch creates a clone to .bzr and then forgets about the
        # original transport. A ScratchTransport() deletes itself and
        # everything underneath it when it goes away, so we need to
        # grab a local copy to prevent that from happening
        self._transport = transport

        for d in dirs:
            self._transport.mkdir(d)
            
        for f in files:
            self._transport.put(f, 'content of %s' % f)

    def clone(self):
        """
        >>> orig = ScratchBranch(files=["file1", "file2"])
        >>> os.listdir(orig.base)
        [u'.bzr', u'file1', u'file2']
        >>> clone = orig.clone()
        >>> if os.name != 'nt':
        ...   os.path.samefile(orig.base, clone.base)
        ... else:
        ...   orig.base == clone.base
        ...
        False
        >>> os.listdir(clone.base)
        [u'.bzr', u'file1', u'file2']
        """
        from shutil import copytree
        from bzrlib.osutils import mkdtemp
        base = mkdtemp()
        os.rmdir(base)
        copytree(self.base, base, symlinks=True)
        return ScratchBranch(
            transport=bzrlib.transport.local.ScratchTransport(base))
    

######################################################################
# predicates


def is_control_file(filename):
    ## FIXME: better check
    filename = normpath(filename)
    while filename != '':
        head, tail = os.path.split(filename)
        ## mutter('check %r for control file' % ((head, tail),))
        if tail == bzrlib.BZRDIR:
            return True
        if filename == head:
            break
        filename = head
    return False
