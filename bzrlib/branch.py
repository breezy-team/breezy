# Copyright (C) 2005, 2006 Canonical Ltd
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


from copy import deepcopy
from cStringIO import StringIO
import errno
import os
import shutil
import sys
from unittest import TestSuite
from warnings import warn

import bzrlib
import bzrlib.bzrdir as bzrdir
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
from bzrlib.lockable_files import LockableFiles, TransportLock
from bzrlib.lockdir import LockDir
from bzrlib.osutils import (isdir, quotefn,
                            rename, splitpath, sha_file,
                            file_kind, abspath, normpath, pathjoin,
                            safe_unicode,
                            )
from bzrlib.textui import show_status
from bzrlib.trace import mutter, note
from bzrlib.tree import EmptyTree, RevisionTree
from bzrlib.repository import Repository
from bzrlib.revision import (
                             get_intervening_revisions,
                             is_ancestor,
                             NULL_REVISION,
                             Revision,
                             )
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

    def __init__(self, *ignored, **ignored_too):
        raise NotImplementedError('The Branch class is abstract')

    @staticmethod
    @deprecated_method(zero_eight)
    def open_downlevel(base):
        """Open a branch which may be of an old format."""
        return Branch.open(base, _unsupported=True)
        
    @staticmethod
    def open(base, _unsupported=False):
        """Open the repository rooted at base.

        For instance, if the repository is at URL/.bzr/repository,
        Repository.open(URL) -> a Repository instance.
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
            nested_pb = bzrlib.ui.ui_factory.nested_progress_bar()
            pb = nested_pb
        else:
            nested_pb = None

        from_branch.lock_read()
        try:
            if last_revision is None:
                pb.update('get source history')
                from_history = from_branch.revision_history()
                if from_history:
                    last_revision = from_history[-1]
                else:
                    # no history in the source branch
                    last_revision = NULL_REVISION
            return self.repository.fetch(from_branch.repository,
                                         revision_id=last_revision,
                                         pb=nested_pb)
        finally:
            if nested_pb is not None:
                nested_pb.finished()
            from_branch.unlock()

    def get_bound_location(self):
        """Return the URL of the rbanch we are bound to.

        Older format branches cannot bind, please be sure to use a metadir
        branch.
        """
        return None

    def get_master_branch(self):
        """Return the branch we are bound to.
        
        :return: Either a Branch, or None
        """
        return None

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

    def unbind(self):
        """Older format branches cannot bind or unbind."""
        raise errors.UpgradeRequired(self.base)

    def last_revision(self):
        """Return last patch hash, or None if no history."""
        ph = self.revision_history()
        if ph:
            return ph[-1]
        else:
            return None

    def missing_revisions(self, other, stop_revision=None):
        """Return a list of new revisions that would perfectly fit.
        
        If self and other have not diverged, return a list of the revisions
        present in other, but missing from self.

        >>> from bzrlib.workingtree import WorkingTree
        >>> bzrlib.trace.silent = True
        >>> d1 = bzrdir.ScratchDir()
        >>> br1 = d1.open_branch()
        >>> wt1 = d1.open_workingtree()
        >>> d2 = bzrdir.ScratchDir()
        >>> br2 = d2.open_branch()
        >>> wt2 = d2.open_workingtree()
        >>> br1.missing_revisions(br2)
        []
        >>> wt2.commit("lala!", rev_id="REVISION-ID-1")
        >>> br1.missing_revisions(br2)
        [u'REVISION-ID-1']
        >>> br2.missing_revisions(br1)
        []
        >>> wt1.commit("lala!", rev_id="REVISION-ID-1")
        >>> br1.missing_revisions(br2)
        []
        >>> wt2.commit("lala!", rev_id="REVISION-ID-2A")
        >>> br1.missing_revisions(br2)
        [u'REVISION-ID-2A']
        >>> wt1.commit("lala!", rev_id="REVISION-ID-2B")
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
        """Pull in new perfect-fit revisions.

        :param other: Another Branch to pull from
        :param stop_revision: Updated until the given revision
        :return: None
        """
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

    def pull(self, source, overwrite=False, stop_revision=None):
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
        # for API compatability, until 0.8 releases we provide the old api:
        # def clone(self, to_location, revision=None, basis_branch=None, to_branch_format=None):
        # after 0.8 releases, the *args and **kwargs should be changed:
        # def clone(self, to_bzrdir, revision_id=None):
        if (kwargs.get('to_location', None) or
            kwargs.get('revision', None) or
            kwargs.get('basis_branch', None) or
            (len(args) and isinstance(args[0], basestring))):
            # backwards compatability api:
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

    @needs_read_lock
    def copy_content_into(self, destination, revision_id=None):
        """Copy the content of self into destination.

        revision_id: if not None, the revision history in the new branch will
                     be truncated to end with revision_id.
        """
        new_history = self.revision_history()
        if revision_id is not None:
            try:
                new_history = new_history[:new_history.index(revision_id) + 1]
            except ValueError:
                rev = self.repository.get_revision(revision_id)
                new_history = rev.get_history(self.repository)[1:]
        destination.set_revision_history(new_history)
        parent = self.get_parent()
        if parent:
            destination.set_parent(parent)


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
            raise errors.UnknownFormatError(format_string)

    @classmethod
    def get_default_format(klass):
        """Return the current default format."""
        return klass._default_format

    def get_format_string(self):
        """Return the ASCII format string that identifies this format."""
        raise NotImplementedError(self.get_format_string)

    def initialize(self, a_bzrdir):
        """Create a branch of this format in a_bzrdir."""
        raise NotImplementedError(self.initialized)

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


class BzrBranchFormat4(BranchFormat):
    """Bzr branch format 4.

    This format has:
     - a revision-history file.
     - a branch-lock lock file [ to be shared with the bzrdir ]
    """

    def initialize(self, a_bzrdir):
        """Create a branch of this format in a_bzrdir."""
        mutter('creating branch in %s', a_bzrdir.transport.base)
        branch_transport = a_bzrdir.get_branch_transport(self)
        utf8_files = [('revision-history', ''),
                      ('branch-name', ''),
                      ]
        control_files = LockableFiles(branch_transport, 'branch-lock',
                                      TransportLock)
        control_files.create_lock()
        control_files.lock_write()
        try:
            for file, content in utf8_files:
                control_files.put_utf8(file, content)
        finally:
            control_files.unlock()
        return self.open(a_bzrdir, _found=True)

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
        
    def initialize(self, a_bzrdir):
        """Create a branch of this format in a_bzrdir."""
        mutter('creating branch %r in %s', self, a_bzrdir.transport.base)
        branch_transport = a_bzrdir.get_branch_transport(self)
        utf8_files = [('revision-history', ''),
                      ('branch-name', ''),
                      ]
        control_files = LockableFiles(branch_transport, 'lock', LockDir)
        control_files.create_lock()
        control_files.lock_write()
        control_files.put_utf8('format', self.get_format_string())
        try:
            for file, content in utf8_files:
                control_files.put_utf8(file, content)
        finally:
            control_files.unlock()
        return self.open(a_bzrdir, _found=True, )

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
        control_files = LockableFiles(transport, 'lock', LockDir)
        return BzrBranch5(_format=self,
                          _control_files=control_files,
                          a_bzrdir=a_bzrdir,
                          _repository=a_bzrdir.find_repository())

    def __str__(self):
        return "Bazaar-NG Metadir branch format 5"


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
        
    def initialize(self, a_bzrdir, target_branch=None):
        """Create a branch of this format in a_bzrdir."""
        if target_branch is None:
            # this format does not implement branch itself, thus the implicit
            # creation contract must see it as uninitializable
            raise errors.UninitializableFormat(self)
        mutter('creating branch reference in %s', a_bzrdir.transport.base)
        branch_transport = a_bzrdir.get_branch_transport(self)
        # FIXME rbc 20060209 one j-a-ms encoding branch lands this str() cast is not needed.
        branch_transport.put('location', StringIO(str(target_branch.bzrdir.root_transport.base)))
        branch_transport.put('format', StringIO(self.get_format_string()))
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
        if a_bzrdir is None:
            self.bzrdir = bzrdir.BzrDir.open(transport.base)
        else:
            self.bzrdir = a_bzrdir
        self._transport = self.bzrdir.transport.clone('..')
        self._base = self._transport.base
        self._format = _format
        if _control_files is None:
            raise BzrBadParameterMissing('_control_files')
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
                 "Please use BzrDir.open_downlevel, or a BzrBranchFormat's "
                 "open() method.",
                 DeprecationWarning,
                 stacklevel=2)
            if (not relax_version_check
                and not self._format.is_supported()):
                raise errors.UnsupportedFormatError(
                        'sorry, branch format %r not supported' % fmt,
                        ['use a different bzr version',
                         'or remove the .bzr directory'
                         ' and "bzr init" again'])
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
        self._format for code that needs to check it later.

        The format parameter is either None or the branch format class
        used to open this branch.

        FIXME: DELETE THIS METHOD when pre 0.8 support is removed.
        """
        if format is None:
            format = BzrBranchFormat.find_format(self.bzrdir)
        self._format = format
        mutter("got branch format %s", self._format)

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
        if stop_revision is None:
            stop_revision = other.last_revision()
        ### Should this be checking is_ancestor instead of revision_history?
        if (stop_revision is not None and 
            stop_revision in self.revision_history()):
            return
        self.fetch(other, stop_revision)
        pullable_revs = self.pullable_revisions(other, stop_revision)
        if len(pullable_revs) > 0:
            self.append_revision(*pullable_revs)

    def pullable_revisions(self, other, stop_revision):
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
        return self.repository.revision_tree(self.last_revision())

    @deprecated_method(zero_eight)
    def working_tree(self):
        """Create a Working tree object for this branch."""
        from bzrlib.workingtree import WorkingTree
        from bzrlib.transport.local import LocalTransport
        if (self.base.find('://') != -1 or 
            not isinstance(self._transport, LocalTransport)):
            raise NoWorkingTree(self.base)
        return self.bzrdir.open_workingtree()

    @needs_write_lock
    def pull(self, source, overwrite=False, stop_revision=None):
        """See Branch.pull."""
        source.lock_read()
        try:
            old_count = len(self.revision_history())
            try:
                self.update_revisions(source,stop_revision)
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
    def pull(self, source, overwrite=False, stop_revision=None):
        """Updates branch.pull to be bound branch aware."""
        bound_location = self.get_bound_location()
        if source.base != bound_location:
            # not pulling from master, so we need to update master.
            master_branch = self.get_master_branch()
            if master_branch:
                master_branch.pull(source)
                source = master_branch
        return super(BzrBranch5, self).pull(source, overwrite, stop_revision)

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
        So for now we just dont memoise it.
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
        """Bind the local branch the other branch.

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
        self.pull(other)

        # we are now equal to or a suffix of other.

        # Since we have 'pulled' from the remote location,
        # now we should try to pull in the opposite direction
        # in case the local tree has more revisions than the
        # remote one.
        # There may be a different check you could do here
        # rather than actually trying to install revisions remotely.
        # TODO: capture an exception which indicates the remote branch
        #       is not writeable. 
        #       If it is up-to-date, this probably should not be a failure
        
        # lock other for write so the revision-history syncing cannot race
        other.lock_write()
        try:
            other.pull(self)
            # if this does not error, other now has the same last rev we do
            # it can only error if the pull from other was concurrent with
            # a commit to other from someone else.

            # until we ditch revision-history, we need to sync them up:
            self.set_revision_history(other.revision_history())
            # now other and self are up to date with each other and have the
            # same revision-history.
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
                new_id = "%s(%s)" % (new_test.id(), branch_format.__class__.__name__)
                return lambda: new_id
            new_test.id = make_new_test_id()
            result.addTest(new_test)
        return result


######################################################################
# predicates


@deprecated_function(zero_eight)
def ScratchBranch(*args, **kwargs):
    """See bzrlib.bzrdir.ScratchDir."""
    d = ScratchDir(*args, **kwargs)
    return d.open_branch()


@deprecated_function(zero_eight)
def is_control_file(*args, **kwargs):
    """See bzrlib.workingtree.is_control_file."""
    return bzrlib.workingtree.is_control_file(*args, **kwargs)
