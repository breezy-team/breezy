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

"""WorkingTree object and friends.

A WorkingTree represents the editable working copy of a branch.
Operations which represent the WorkingTree are also done here, 
such as renaming or adding files.  The WorkingTree has an inventory 
which is updated by these operations.  A commit produces a 
new revision based on the workingtree and its inventory.

At the moment every WorkingTree has its own branch.  Remote
WorkingTrees aren't supported.

To get a WorkingTree, call bzrdir.open_workingtree() or
WorkingTree.open(dir).
"""

MERGE_MODIFIED_HEADER_1 = "BZR merge-modified list format 1"
CONFLICT_HEADER_1 = "BZR conflict list format 1"

# TODO: Give the workingtree sole responsibility for the working inventory;
# remove the variable and references to it from the branch.  This may require
# updating the commit code so as to update the inventory within the working
# copy, and making sure there's only one WorkingTree for any directory on disk.
# At the moment they may alias the inventory and have old copies of it in
# memory.  (Now done? -- mbp 20060309)

from binascii import hexlify
import collections
from copy import deepcopy
from cStringIO import StringIO
import errno
import fnmatch
import os
import re
import stat
from time import time
import warnings

import bzrlib
from bzrlib import bzrdir, errors, ignores, osutils, urlutils
from bzrlib.atomicfile import AtomicFile
import bzrlib.branch
from bzrlib.conflicts import Conflict, ConflictList, CONFLICT_SUFFIXES
from bzrlib.decorators import needs_read_lock, needs_write_lock
from bzrlib.errors import (BzrCheckError,
                           BzrError,
                           ConflictFormatError,
                           WeaveRevisionNotPresent,
                           NotBranchError,
                           NoSuchFile,
                           NotVersionedError,
                           MergeModifiedFormatError,
                           UnsupportedOperation,
                           )
from bzrlib.inventory import InventoryEntry, Inventory
from bzrlib.lockable_files import LockableFiles, TransportLock
from bzrlib.lockdir import LockDir
from bzrlib.merge import merge_inner, transform_tree
import bzrlib.mutabletree
from bzrlib.mutabletree import needs_tree_write_lock
from bzrlib.osutils import (
                            abspath,
                            compact_date,
                            file_kind,
                            isdir,
                            getcwd,
                            pathjoin,
                            pumpfile,
                            safe_unicode,
                            splitpath,
                            rand_chars,
                            normpath,
                            realpath,
                            relpath,
                            rename,
                            supports_executable,
                            )
from bzrlib.progress import DummyProgress, ProgressPhase
from bzrlib.revision import NULL_REVISION
import bzrlib.revisiontree
from bzrlib.rio import RioReader, rio_file, Stanza
from bzrlib.symbol_versioning import (deprecated_passed,
        deprecated_method,
        deprecated_function,
        DEPRECATED_PARAMETER,
        zero_eight,
        zero_eleven,
        )
from bzrlib.trace import mutter, note
from bzrlib.transform import build_tree
from bzrlib.transport import get_transport
from bzrlib.transport.local import LocalTransport
from bzrlib.textui import show_status
import bzrlib.ui
import bzrlib.xml5


# the regex removes any weird characters; we don't escape them 
# but rather just pull them out
_gen_file_id_re = re.compile(r'[^\w.]')
_gen_id_suffix = None
_gen_id_serial = 0


def _next_id_suffix():
    """Create a new file id suffix that is reasonably unique.
    
    On the first call we combine the current time with 64 bits of randomness
    to give a highly probably globally unique number. Then each call in the same
    process adds 1 to a serial number we append to that unique value.
    """
    # XXX TODO: change bzrlib.add.smart_add to call workingtree.add() rather 
    # than having to move the id randomness out of the inner loop like this.
    # XXX TODO: for the global randomness this uses we should add the thread-id
    # before the serial #.
    global _gen_id_suffix, _gen_id_serial
    if _gen_id_suffix is None:
        _gen_id_suffix = "-%s-%s-" % (compact_date(time()), rand_chars(16))
    _gen_id_serial += 1
    return _gen_id_suffix + str(_gen_id_serial)


def gen_file_id(name):
    """Return new file id for the basename 'name'.

    The uniqueness is supplied from _next_id_suffix.
    """
    # The real randomness is in the _next_id_suffix, the
    # rest of the identifier is just to be nice.
    # So we:
    # 1) Remove non-ascii word characters to keep the ids portable
    # 2) squash to lowercase, so the file id doesn't have to
    #    be escaped (case insensitive filesystems would bork for ids
    #    that only differred in case without escaping).
    # 3) truncate the filename to 20 chars. Long filenames also bork on some
    #    filesystems
    # 4) Removing starting '.' characters to prevent the file ids from
    #    being considered hidden.
    ascii_word_only = _gen_file_id_re.sub('', name.lower())
    short_no_dots = ascii_word_only.lstrip('.')[:20]
    return short_no_dots + _next_id_suffix()


def gen_root_id():
    """Return a new tree-root file id."""
    return gen_file_id('TREE_ROOT')


class TreeEntry(object):
    """An entry that implements the minimum interface used by commands.

    This needs further inspection, it may be better to have 
    InventoryEntries without ids - though that seems wrong. For now,
    this is a parallel hierarchy to InventoryEntry, and needs to become
    one of several things: decorates to that hierarchy, children of, or
    parents of it.
    Another note is that these objects are currently only used when there is
    no InventoryEntry available - i.e. for unversioned objects.
    Perhaps they should be UnversionedEntry et al. ? - RBC 20051003
    """
 
    def __eq__(self, other):
        # yes, this us ugly, TODO: best practice __eq__ style.
        return (isinstance(other, TreeEntry)
                and other.__class__ == self.__class__)
 
    def kind_character(self):
        return "???"


class TreeDirectory(TreeEntry):
    """See TreeEntry. This is a directory in a working tree."""

    def __eq__(self, other):
        return (isinstance(other, TreeDirectory)
                and other.__class__ == self.__class__)

    def kind_character(self):
        return "/"


class TreeFile(TreeEntry):
    """See TreeEntry. This is a regular file in a working tree."""

    def __eq__(self, other):
        return (isinstance(other, TreeFile)
                and other.__class__ == self.__class__)

    def kind_character(self):
        return ''


class TreeLink(TreeEntry):
    """See TreeEntry. This is a symlink in a working tree."""

    def __eq__(self, other):
        return (isinstance(other, TreeLink)
                and other.__class__ == self.__class__)

    def kind_character(self):
        return ''


class WorkingTree(bzrlib.mutabletree.MutableTree):
    """Working copy tree.

    The inventory is held in the `Branch` working-inventory, and the
    files are in a directory on disk.

    It is possible for a `WorkingTree` to have a filename which is
    not listed in the Inventory and vice versa.
    """

    def __init__(self, basedir='.',
                 branch=DEPRECATED_PARAMETER,
                 _inventory=None,
                 _control_files=None,
                 _internal=False,
                 _format=None,
                 _bzrdir=None):
        """Construct a WorkingTree for basedir.

        If the branch is not supplied, it is opened automatically.
        If the branch is supplied, it must be the branch for this basedir.
        (branch.base is not cross checked, because for remote branches that
        would be meaningless).
        """
        self._format = _format
        self.bzrdir = _bzrdir
        if not _internal:
            # not created via open etc.
            warnings.warn("WorkingTree() is deprecated as of bzr version 0.8. "
                 "Please use bzrdir.open_workingtree or WorkingTree.open().",
                 DeprecationWarning,
                 stacklevel=2)
            wt = WorkingTree.open(basedir)
            self._branch = wt.branch
            self.basedir = wt.basedir
            self._control_files = wt._control_files
            self._hashcache = wt._hashcache
            self._set_inventory(wt._inventory)
            self._format = wt._format
            self.bzrdir = wt.bzrdir
        from bzrlib.hashcache import HashCache
        from bzrlib.trace import note, mutter
        assert isinstance(basedir, basestring), \
            "base directory %r is not a string" % basedir
        basedir = safe_unicode(basedir)
        mutter("opening working tree %r", basedir)
        if deprecated_passed(branch):
            if not _internal:
                warnings.warn("WorkingTree(..., branch=XXX) is deprecated as of bzr 0.8."
                     " Please use bzrdir.open_workingtree() or"
                     " WorkingTree.open().",
                     DeprecationWarning,
                     stacklevel=2
                     )
            self._branch = branch
        else:
            self._branch = self.bzrdir.open_branch()
        self.basedir = realpath(basedir)
        # if branch is at our basedir and is a format 6 or less
        if isinstance(self._format, WorkingTreeFormat2):
            # share control object
            self._control_files = self.branch.control_files
        else:
            # assume all other formats have their own control files.
            assert isinstance(_control_files, LockableFiles), \
                    "_control_files must be a LockableFiles, not %r" \
                    % _control_files
            self._control_files = _control_files
        # update the whole cache up front and write to disk if anything changed;
        # in the future we might want to do this more selectively
        # two possible ways offer themselves : in self._unlock, write the cache
        # if needed, or, when the cache sees a change, append it to the hash
        # cache file, and have the parser take the most recent entry for a
        # given path only.
        cache_filename = self.bzrdir.get_workingtree_transport(None).local_abspath('stat-cache')
        hc = self._hashcache = HashCache(basedir, cache_filename, self._control_files._file_mode)
        hc.read()
        # is this scan needed ? it makes things kinda slow.
        #hc.scan()

        if hc.needs_write:
            mutter("write hc")
            hc.write()

        if _inventory is None:
            self._set_inventory(self.read_working_inventory())
        else:
            self._set_inventory(_inventory)

    branch = property(
        fget=lambda self: self._branch,
        doc="""The branch this WorkingTree is connected to.

            This cannot be set - it is reflective of the actual disk structure
            the working tree has been constructed from.
            """)

    def break_lock(self):
        """Break a lock if one is present from another instance.

        Uses the ui factory to ask for confirmation if the lock may be from
        an active process.

        This will probe the repository for its lock as well.
        """
        self._control_files.break_lock()
        self.branch.break_lock()

    def _set_inventory(self, inv):
        assert inv.root is not None
        self._inventory = inv

    @staticmethod
    def open(path=None, _unsupported=False):
        """Open an existing working tree at path.

        """
        if path is None:
            path = os.path.getcwdu()
        control = bzrdir.BzrDir.open(path, _unsupported)
        return control.open_workingtree(_unsupported)
        
    @staticmethod
    def open_containing(path=None):
        """Open an existing working tree which has its root about path.
        
        This probes for a working tree at path and searches upwards from there.

        Basically we keep looking up until we find the control directory or
        run into /.  If there isn't one, raises NotBranchError.
        TODO: give this a new exception.
        If there is one, it is returned, along with the unused portion of path.

        :return: The WorkingTree that contains 'path', and the rest of path
        """
        if path is None:
            path = osutils.getcwd()
        control, relpath = bzrdir.BzrDir.open_containing(path)

        return control.open_workingtree(), relpath

    @staticmethod
    def open_downlevel(path=None):
        """Open an unsupported working tree.

        Only intended for advanced situations like upgrading part of a bzrdir.
        """
        return WorkingTree.open(path, _unsupported=True)

    def __iter__(self):
        """Iterate through file_ids for this tree.

        file_ids are in a WorkingTree if they are in the working inventory
        and the working file exists.
        """
        inv = self._inventory
        for path, ie in inv.iter_entries():
            if osutils.lexists(self.abspath(path)):
                yield ie.file_id

    def __repr__(self):
        return "<%s of %s>" % (self.__class__.__name__,
                               getattr(self, 'basedir', None))

    def abspath(self, filename):
        return pathjoin(self.basedir, filename)
    
    def basis_tree(self):
        """Return RevisionTree for the current last revision.
        
        If the left most parent is a ghost then the returned tree will be an
        empty tree - one obtained by calling repository.revision_tree(None).
        """
        try:
            revision_id = self.get_parent_ids()[0]
        except IndexError:
            # no parents, return an empty revision tree.
            # in the future this should return the tree for
            # 'empty:' - the implicit root empty tree.
            return self.branch.repository.revision_tree(None)
        else:
            try:
                xml = self.read_basis_inventory()
                inv = bzrlib.xml6.serializer_v6.read_inventory_from_string(xml)
                if inv is not None and inv.revision_id == revision_id:
                    return bzrlib.tree.RevisionTree(self.branch.repository, 
                                                    inv, revision_id)
            except (NoSuchFile, errors.BadInventoryFormat):
                pass
        # No cached copy available, retrieve from the repository.
        # FIXME? RBC 20060403 should we cache the inventory locally
        # at this point ?
        try:
            return self.branch.repository.revision_tree(revision_id)
        except errors.RevisionNotPresent:
            # the basis tree *may* be a ghost or a low level error may have
            # occured. If the revision is present, its a problem, if its not
            # its a ghost.
            if self.branch.repository.has_revision(revision_id):
                raise
            # the basis tree is a ghost so return an empty tree.
            return self.branch.repository.revision_tree(None)

    @staticmethod
    @deprecated_method(zero_eight)
    def create(branch, directory):
        """Create a workingtree for branch at directory.

        If existing_directory already exists it must have a .bzr directory.
        If it does not exist, it will be created.

        This returns a new WorkingTree object for the new checkout.

        TODO FIXME RBC 20060124 when we have checkout formats in place this
        should accept an optional revisionid to checkout [and reject this if
        checking out into the same dir as a pre-checkout-aware branch format.]

        XXX: When BzrDir is present, these should be created through that 
        interface instead.
        """
        warnings.warn('delete WorkingTree.create', stacklevel=3)
        transport = get_transport(directory)
        if branch.bzrdir.root_transport.base == transport.base:
            # same dir 
            return branch.bzrdir.create_workingtree()
        # different directory, 
        # create a branch reference
        # and now a working tree.
        raise NotImplementedError
 
    @staticmethod
    @deprecated_method(zero_eight)
    def create_standalone(directory):
        """Create a checkout and a branch and a repo at directory.

        Directory must exist and be empty.

        please use BzrDir.create_standalone_workingtree
        """
        return bzrdir.BzrDir.create_standalone_workingtree(directory)

    def relpath(self, path):
        """Return the local path portion from a given path.
        
        The path may be absolute or relative. If its a relative path it is 
        interpreted relative to the python current working directory.
        """
        return relpath(self.basedir, path)

    def has_filename(self, filename):
        return osutils.lexists(self.abspath(filename))

    def get_file(self, file_id):
        return self.get_file_byname(self.id2path(file_id))

    def get_file_text(self, file_id):
        return self.get_file(file_id).read()

    def get_file_byname(self, filename):
        return file(self.abspath(filename), 'rb')

    def get_parent_ids(self):
        """See Tree.get_parent_ids.
        
        This implementation reads the pending merges list and last_revision
        value and uses that to decide what the parents list should be.
        """
        last_rev = self._last_revision()
        if last_rev is None:
            parents = []
        else:
            parents = [last_rev]
        try:
            merges_file = self._control_files.get_utf8('pending-merges')
        except NoSuchFile:
            pass
        else:
            for l in merges_file.readlines():
                parents.append(l.rstrip('\n'))
        return parents

    def get_root_id(self):
        """Return the id of this trees root"""
        inv = self.read_working_inventory()
        return inv.root.file_id
        
    def _get_store_filename(self, file_id):
        ## XXX: badly named; this is not in the store at all
        return self.abspath(self.id2path(file_id))

    @needs_read_lock
    def clone(self, to_bzrdir, revision_id=None, basis=None):
        """Duplicate this working tree into to_bzr, including all state.
        
        Specifically modified files are kept as modified, but
        ignored and unknown files are discarded.

        If you want to make a new line of development, see bzrdir.sprout()

        revision
            If not None, the cloned tree will have its last revision set to 
            revision, and and difference between the source trees last revision
            and this one merged in.

        basis
            If not None, a closer copy of a tree which may have some files in
            common, and which file content should be preferentially copied from.
        """
        # assumes the target bzr dir format is compatible.
        result = self._format.initialize(to_bzrdir)
        self.copy_content_into(result, revision_id)
        return result

    @needs_read_lock
    def copy_content_into(self, tree, revision_id=None):
        """Copy the current content and user files of this tree into tree."""
        tree.set_root_id(self.get_root_id())
        if revision_id is None:
            transform_tree(tree, self)
        else:
            # TODO now merge from tree.last_revision to revision (to preserve
            # user local changes)
            transform_tree(tree, self)
            tree.set_parent_ids([revision_id])

    def id2abspath(self, file_id):
        return self.abspath(self.id2path(file_id))

    def has_id(self, file_id):
        # files that have been deleted are excluded
        inv = self._inventory
        if not inv.has_id(file_id):
            return False
        path = inv.id2path(file_id)
        return osutils.lexists(self.abspath(path))

    def has_or_had_id(self, file_id):
        if file_id == self.inventory.root.file_id:
            return True
        return self.inventory.has_id(file_id)

    __contains__ = has_id

    def get_file_size(self, file_id):
        return os.path.getsize(self.id2abspath(file_id))

    @needs_read_lock
    def get_file_sha1(self, file_id, path=None):
        if not path:
            path = self._inventory.id2path(file_id)
        return self._hashcache.get_sha1(path)

    def get_file_mtime(self, file_id, path=None):
        if not path:
            path = self._inventory.id2path(file_id)
        return os.lstat(self.abspath(path)).st_mtime

    if not supports_executable():
        def is_executable(self, file_id, path=None):
            return self._inventory[file_id].executable
    else:
        def is_executable(self, file_id, path=None):
            if not path:
                path = self._inventory.id2path(file_id)
            mode = os.lstat(self.abspath(path)).st_mode
            return bool(stat.S_ISREG(mode) and stat.S_IEXEC & mode)

    @needs_write_lock
    def _add(self, files, ids, kinds):
        """See MutableTree._add."""
        # TODO: Re-adding a file that is removed in the working copy
        # should probably put it back with the previous ID.
        # the read and write working inventory should not occur in this 
        # function - they should be part of lock_write and unlock.
        inv = self.read_working_inventory()
        for f, file_id, kind in zip(files, ids, kinds):
            assert kind is not None
            if file_id is None:
                inv.add_path(f, kind=kind)
            else:
                inv.add_path(f, kind=kind, file_id=file_id)
        self._write_inventory(inv)

    @needs_tree_write_lock
    def _gather_kinds(self, files, kinds):
        """See MutableTree._gather_kinds."""
        for pos, f in enumerate(files):
            if kinds[pos] is None:
                fullpath = normpath(self.abspath(f))
                try:
                    kinds[pos] = file_kind(fullpath)
                except OSError, e:
                    if e.errno == errno.ENOENT:
                        raise NoSuchFile(fullpath)

    @needs_write_lock
    def add_parent_tree_id(self, revision_id, allow_leftmost_as_ghost=False):
        """Add revision_id as a parent.

        This is equivalent to retrieving the current list of parent ids
        and setting the list to its value plus revision_id.

        :param revision_id: The revision id to add to the parent list. It may
        be a ghost revision as long as its not the first parent to be added,
        or the allow_leftmost_as_ghost parameter is set True.
        :param allow_leftmost_as_ghost: Allow the first parent to be a ghost.
        """
        parents = self.get_parent_ids() + [revision_id]
        self.set_parent_ids(parents,
            allow_leftmost_as_ghost=len(parents) > 1 or allow_leftmost_as_ghost)

    @needs_tree_write_lock
    def add_parent_tree(self, parent_tuple, allow_leftmost_as_ghost=False):
        """Add revision_id, tree tuple as a parent.

        This is equivalent to retrieving the current list of parent trees
        and setting the list to its value plus parent_tuple. See also
        add_parent_tree_id - if you only have a parent id available it will be
        simpler to use that api. If you have the parent already available, using
        this api is preferred.

        :param parent_tuple: The (revision id, tree) to add to the parent list.
            If the revision_id is a ghost, pass None for the tree.
        :param allow_leftmost_as_ghost: Allow the first parent to be a ghost.
        """
        parent_ids = self.get_parent_ids() + [parent_tuple[0]]
        if len(parent_ids) > 1:
            # the leftmost may have already been a ghost, preserve that if it
            # was.
            allow_leftmost_as_ghost = True
        self.set_parent_ids(parent_ids,
            allow_leftmost_as_ghost=allow_leftmost_as_ghost)

    @needs_tree_write_lock
    def add_pending_merge(self, *revision_ids):
        # TODO: Perhaps should check at this point that the
        # history of the revision is actually present?
        parents = self.get_parent_ids()
        updated = False
        for rev_id in revision_ids:
            if rev_id in parents:
                continue
            parents.append(rev_id)
            updated = True
        if updated:
            self.set_parent_ids(parents, allow_leftmost_as_ghost=True)

    @deprecated_method(zero_eleven)
    @needs_read_lock
    def pending_merges(self):
        """Return a list of pending merges.

        These are revisions that have been merged into the working
        directory but not yet committed.

        As of 0.11 this is deprecated. Please see WorkingTree.get_parent_ids()
        instead - which is available on all tree objects.
        """
        return self.get_parent_ids()[1:]

    def _check_parents_for_ghosts(self, revision_ids, allow_leftmost_as_ghost):
        """Common ghost checking functionality from set_parent_*.

        This checks that the left hand-parent exists if there are any
        revisions present.
        """
        if len(revision_ids) > 0:
            leftmost_id = revision_ids[0]
            if (not allow_leftmost_as_ghost and not
                self.branch.repository.has_revision(leftmost_id)):
                raise errors.GhostRevisionUnusableHere(leftmost_id)

    def _set_merges_from_parent_ids(self, parent_ids):
        merges = parent_ids[1:]
        self._control_files.put_utf8('pending-merges', '\n'.join(merges))

    @needs_tree_write_lock
    def set_parent_ids(self, revision_ids, allow_leftmost_as_ghost=False):
        """Set the parent ids to revision_ids.
        
        See also set_parent_trees. This api will try to retrieve the tree data
        for each element of revision_ids from the trees repository. If you have
        tree data already available, it is more efficient to use
        set_parent_trees rather than set_parent_ids. set_parent_ids is however
        an easier API to use.

        :param revision_ids: The revision_ids to set as the parent ids of this
            working tree. Any of these may be ghosts.
        """
        self._check_parents_for_ghosts(revision_ids,
            allow_leftmost_as_ghost=allow_leftmost_as_ghost)

        if len(revision_ids) > 0:
            self.set_last_revision(revision_ids[0])
        else:
            self.set_last_revision(None)

        self._set_merges_from_parent_ids(revision_ids)

    @needs_tree_write_lock
    def set_parent_trees(self, parents_list, allow_leftmost_as_ghost=False):
        """See MutableTree.set_parent_trees."""
        parent_ids = [rev for (rev, tree) in parents_list]

        self._check_parents_for_ghosts(parent_ids,
            allow_leftmost_as_ghost=allow_leftmost_as_ghost)

        if len(parent_ids) == 0:
            leftmost_parent_id = None
            leftmost_parent_tree = None
        else:
            leftmost_parent_id, leftmost_parent_tree = parents_list[0]

        if self._change_last_revision(leftmost_parent_id):
            if leftmost_parent_tree is None:
                # If we don't have a tree, fall back to reading the
                # parent tree from the repository.
                self._cache_basis_inventory(leftmost_parent_id)
            else:
                inv = leftmost_parent_tree.inventory
                xml = self._create_basis_xml_from_inventory(
                                        leftmost_parent_id, inv)
                self._write_basis_inventory(xml)
        self._set_merges_from_parent_ids(parent_ids)

    @needs_tree_write_lock
    def set_pending_merges(self, rev_list):
        parents = self.get_parent_ids()
        leftmost = parents[:1]
        new_parents = leftmost + rev_list
        self.set_parent_ids(new_parents)

    @needs_tree_write_lock
    def set_merge_modified(self, modified_hashes):
        def iter_stanzas():
            for file_id, hash in modified_hashes.iteritems():
                yield Stanza(file_id=file_id, hash=hash)
        self._put_rio('merge-hashes', iter_stanzas(), MERGE_MODIFIED_HEADER_1)

    @needs_tree_write_lock
    def _put_rio(self, filename, stanzas, header):
        my_file = rio_file(stanzas, header)
        self._control_files.put(filename, my_file)

    @needs_write_lock # because merge pulls data into the branch.
    def merge_from_branch(self, branch, to_revision=None):
        """Merge from a branch into this working tree.

        :param branch: The branch to merge from.
        :param to_revision: If non-None, the merge will merge to to_revision, but 
            not beyond it. to_revision does not need to be in the history of
            the branch when it is supplied. If None, to_revision defaults to
            branch.last_revision().
        """
        from bzrlib.merge import Merger, Merge3Merger
        pb = bzrlib.ui.ui_factory.nested_progress_bar()
        try:
            merger = Merger(self.branch, this_tree=self, pb=pb)
            merger.pp = ProgressPhase("Merge phase", 5, pb)
            merger.pp.next_phase()
            # check that there are no
            # local alterations
            merger.check_basis(check_clean=True, require_commits=False)
            if to_revision is None:
                to_revision = branch.last_revision()
            merger.other_rev_id = to_revision
            if merger.other_rev_id is None:
                raise error.NoCommits(branch)
            self.branch.fetch(branch, last_revision=merger.other_rev_id)
            merger.other_basis = merger.other_rev_id
            merger.other_tree = self.branch.repository.revision_tree(
                merger.other_rev_id)
            merger.pp.next_phase()
            merger.find_base()
            if merger.base_rev_id == merger.other_rev_id:
                raise errors.PointlessMerge
            merger.backup_files = False
            merger.merge_type = Merge3Merger
            merger.set_interesting_files(None)
            merger.show_base = False
            merger.reprocess = False
            conflicts = merger.do_merge()
            merger.set_pending()
        finally:
            pb.finished()
        return conflicts

    @needs_read_lock
    def merge_modified(self):
        try:
            hashfile = self._control_files.get('merge-hashes')
        except NoSuchFile:
            return {}
        merge_hashes = {}
        try:
            if hashfile.next() != MERGE_MODIFIED_HEADER_1 + '\n':
                raise MergeModifiedFormatError()
        except StopIteration:
            raise MergeModifiedFormatError()
        for s in RioReader(hashfile):
            file_id = s.get("file_id")
            if file_id not in self.inventory:
                continue
            hash = s.get("hash")
            if hash == self.get_file_sha1(file_id):
                merge_hashes[file_id] = hash
        return merge_hashes

    @needs_write_lock
    def mkdir(self, path, file_id=None):
        """See MutableTree.mkdir()."""
        if file_id is None:
            file_id = gen_file_id(os.path.basename(path))
        os.mkdir(self.abspath(path))
        self.add(path, file_id, 'directory')
        return file_id

    def get_symlink_target(self, file_id):
        return os.readlink(self.id2abspath(file_id))

    def file_class(self, filename):
        if self.path2id(filename):
            return 'V'
        elif self.is_ignored(filename):
            return 'I'
        else:
            return '?'

    def list_files(self, include_root=False):
        """Recursively list all files as (path, class, kind, id, entry).

        Lists, but does not descend into unversioned directories.

        This does not include files that have been deleted in this
        tree.

        Skips the control directory.
        """
        inv = self._inventory
        if include_root is True:
            yield ('', 'V', 'directory', inv.root.file_id, inv.root)
        # Convert these into local objects to save lookup times
        pathjoin = osutils.pathjoin
        file_kind = osutils.file_kind

        # transport.base ends in a slash, we want the piece
        # between the last two slashes
        transport_base_dir = self.bzrdir.transport.base.rsplit('/', 2)[1]

        fk_entries = {'directory':TreeDirectory, 'file':TreeFile, 'symlink':TreeLink}

        # directory file_id, relative path, absolute path, reverse sorted children
        children = os.listdir(self.basedir)
        children.sort()
        # jam 20060527 The kernel sized tree seems equivalent whether we 
        # use a deque and popleft to keep them sorted, or if we use a plain
        # list and just reverse() them.
        children = collections.deque(children)
        stack = [(inv.root.file_id, u'', self.basedir, children)]
        if include_root:
            yield u'', 'V', 'directory', inv.root.file_id, inv.root
        while stack:
            from_dir_id, from_dir_relpath, from_dir_abspath, children = stack[-1]

            while children:
                f = children.popleft()
                ## TODO: If we find a subdirectory with its own .bzr
                ## directory, then that is a separate tree and we
                ## should exclude it.

                # the bzrdir for this tree
                if transport_base_dir == f:
                    continue

                # we know that from_dir_relpath and from_dir_abspath never end in a slash
                # and 'f' doesn't begin with one, we can do a string op, rather
                # than the checks of pathjoin(), all relative paths will have an extra slash
                # at the beginning
                fp = from_dir_relpath + '/' + f

                # absolute path
                fap = from_dir_abspath + '/' + f
                
                f_ie = inv.get_child(from_dir_id, f)
                if f_ie:
                    c = 'V'
                elif self.is_ignored(fp[1:]):
                    c = 'I'
                else:
                    # we may not have found this file, because of a unicode issue
                    f_norm, can_access = osutils.normalized_filename(f)
                    if f == f_norm or not can_access:
                        # No change, so treat this file normally
                        c = '?'
                    else:
                        # this file can be accessed by a normalized path
                        # check again if it is versioned
                        # these lines are repeated here for performance
                        f = f_norm
                        fp = from_dir_relpath + '/' + f
                        fap = from_dir_abspath + '/' + f
                        f_ie = inv.get_child(from_dir_id, f)
                        if f_ie:
                            c = 'V'
                        elif self.is_ignored(fp[1:]):
                            c = 'I'
                        else:
                            c = '?'

                fk = file_kind(fap)

                if f_ie:
                    if f_ie.kind != fk:
                        raise BzrCheckError("file %r entered as kind %r id %r, "
                                            "now of kind %r"
                                            % (fap, f_ie.kind, f_ie.file_id, fk))

                # make a last minute entry
                if f_ie:
                    yield fp[1:], c, fk, f_ie.file_id, f_ie
                else:
                    try:
                        yield fp[1:], c, fk, None, fk_entries[fk]()
                    except KeyError:
                        yield fp[1:], c, fk, None, TreeEntry()
                    continue
                
                if fk != 'directory':
                    continue

                # But do this child first
                new_children = os.listdir(fap)
                new_children.sort()
                new_children = collections.deque(new_children)
                stack.append((f_ie.file_id, fp, fap, new_children))
                # Break out of inner loop, so that we start outer loop with child
                break
            else:
                # if we finished all children, pop it off the stack
                stack.pop()

    @needs_tree_write_lock
    def move(self, from_paths, to_name):
        """Rename files.

        to_name must exist in the inventory.

        If to_name exists and is a directory, the files are moved into
        it, keeping their old names.  

        Note that to_name is only the last component of the new name;
        this doesn't change the directory.

        This returns a list of (from_path, to_path) pairs for each
        entry that is moved.
        """
        result = []
        ## TODO: Option to move IDs only
        assert not isinstance(from_paths, basestring)
        inv = self.inventory
        to_abs = self.abspath(to_name)
        if not isdir(to_abs):
            raise BzrError("destination %r is not a directory" % to_abs)
        if not self.has_filename(to_name):
            raise BzrError("destination %r not in working directory" % to_abs)
        to_dir_id = inv.path2id(to_name)
        if to_dir_id is None and to_name != '':
            raise BzrError("destination %r is not a versioned directory" % to_name)
        to_dir_ie = inv[to_dir_id]
        if to_dir_ie.kind != 'directory':
            raise BzrError("destination %r is not a directory" % to_abs)

        to_idpath = inv.get_idpath(to_dir_id)

        for f in from_paths:
            if not self.has_filename(f):
                raise BzrError("%r does not exist in working tree" % f)
            f_id = inv.path2id(f)
            if f_id is None:
                raise BzrError("%r is not versioned" % f)
            name_tail = splitpath(f)[-1]
            dest_path = pathjoin(to_name, name_tail)
            if self.has_filename(dest_path):
                raise BzrError("destination %r already exists" % dest_path)
            if f_id in to_idpath:
                raise BzrError("can't move %r to a subdirectory of itself" % f)

        # OK, so there's a race here, it's possible that someone will
        # create a file in this interval and then the rename might be
        # left half-done.  But we should have caught most problems.
        orig_inv = deepcopy(self.inventory)
        try:
            for f in from_paths:
                name_tail = splitpath(f)[-1]
                dest_path = pathjoin(to_name, name_tail)
                result.append((f, dest_path))
                inv.rename(inv.path2id(f), to_dir_id, name_tail)
                try:
                    rename(self.abspath(f), self.abspath(dest_path))
                except OSError, e:
                    raise BzrError("failed to rename %r to %r: %s" %
                                   (f, dest_path, e[1]),
                            ["rename rolled back"])
        except:
            # restore the inventory on error
            self._set_inventory(orig_inv)
            raise
        self._write_inventory(inv)
        return result

    @needs_tree_write_lock
    def rename_one(self, from_rel, to_rel):
        """Rename one file.

        This can change the directory or the filename or both.
        """
        inv = self.inventory
        if not self.has_filename(from_rel):
            raise BzrError("can't rename: old working file %r does not exist" % from_rel)
        if self.has_filename(to_rel):
            raise BzrError("can't rename: new working file %r already exists" % to_rel)

        file_id = inv.path2id(from_rel)
        if file_id is None:
            raise BzrError("can't rename: old name %r is not versioned" % from_rel)

        entry = inv[file_id]
        from_parent = entry.parent_id
        from_name = entry.name
        
        if inv.path2id(to_rel):
            raise BzrError("can't rename: new name %r is already versioned" % to_rel)

        to_dir, to_tail = os.path.split(to_rel)
        to_dir_id = inv.path2id(to_dir)
        if to_dir_id is None and to_dir != '':
            raise BzrError("can't determine destination directory id for %r" % to_dir)

        mutter("rename_one:")
        mutter("  file_id    {%s}" % file_id)
        mutter("  from_rel   %r" % from_rel)
        mutter("  to_rel     %r" % to_rel)
        mutter("  to_dir     %r" % to_dir)
        mutter("  to_dir_id  {%s}" % to_dir_id)

        inv.rename(file_id, to_dir_id, to_tail)

        from_abs = self.abspath(from_rel)
        to_abs = self.abspath(to_rel)
        try:
            rename(from_abs, to_abs)
        except OSError, e:
            inv.rename(file_id, from_parent, from_name)
            raise BzrError("failed to rename %r to %r: %s"
                    % (from_abs, to_abs, e[1]),
                    ["rename rolled back"])
        self._write_inventory(inv)

    @needs_read_lock
    def unknowns(self):
        """Return all unknown files.

        These are files in the working directory that are not versioned or
        control files or ignored.
        """
        for subp in self.extras():
            if not self.is_ignored(subp):
                yield subp
    
    @needs_tree_write_lock
    def unversion(self, file_ids):
        """Remove the file ids in file_ids from the current versioned set.

        When a file_id is unversioned, all of its children are automatically
        unversioned.

        :param file_ids: The file ids to stop versioning.
        :raises: NoSuchId if any fileid is not currently versioned.
        """
        for file_id in file_ids:
            if self._inventory.has_id(file_id):
                self._inventory.remove_recursive_id(file_id)
            else:
                raise errors.NoSuchId(self, file_id)
        if len(file_ids):
            # in the future this should just set a dirty bit to wait for the 
            # final unlock. However, until all methods of workingtree start
            # with the current in -memory inventory rather than triggering 
            # a read, it is more complex - we need to teach read_inventory
            # to know when to read, and when to not read first... and possibly
            # to save first when the in memory one may be corrupted.
            # so for now, we just only write it if it is indeed dirty.
            # - RBC 20060907
            self._write_inventory(self._inventory)
    
    @deprecated_method(zero_eight)
    def iter_conflicts(self):
        """List all files in the tree that have text or content conflicts.
        DEPRECATED.  Use conflicts instead."""
        return self._iter_conflicts()

    def _iter_conflicts(self):
        conflicted = set()
        for info in self.list_files():
            path = info[0]
            stem = get_conflicted_stem(path)
            if stem is None:
                continue
            if stem not in conflicted:
                conflicted.add(stem)
                yield stem

    @needs_write_lock
    def pull(self, source, overwrite=False, stop_revision=None):
        top_pb = bzrlib.ui.ui_factory.nested_progress_bar()
        source.lock_read()
        try:
            pp = ProgressPhase("Pull phase", 2, top_pb)
            pp.next_phase()
            old_revision_history = self.branch.revision_history()
            basis_tree = self.basis_tree()
            count = self.branch.pull(source, overwrite, stop_revision)
            new_revision_history = self.branch.revision_history()
            if new_revision_history != old_revision_history:
                pp.next_phase()
                if len(old_revision_history):
                    other_revision = old_revision_history[-1]
                else:
                    other_revision = None
                repository = self.branch.repository
                pb = bzrlib.ui.ui_factory.nested_progress_bar()
                try:
                    new_basis_tree = self.branch.basis_tree()
                    merge_inner(self.branch,
                                new_basis_tree,
                                basis_tree,
                                this_tree=self,
                                pb=pb)
                    if (basis_tree.inventory.root is None and
                        new_basis_tree.inventory.root is not None):
                        self.set_root_id(new_basis_tree.inventory.root.file_id)
                finally:
                    pb.finished()
                # TODO - dedup parents list with things merged by pull ?
                # reuse the revisiontree we merged against to set the new
                # tree data.
                parent_trees = [(self.branch.last_revision(), new_basis_tree)]
                # we have to pull the merge trees out again, because 
                # merge_inner has set the ids. - this corner is not yet 
                # layered well enough to prevent double handling.
                merges = self.get_parent_ids()[1:]
                parent_trees.extend([
                    (parent, repository.revision_tree(parent)) for
                     parent in merges])
                self.set_parent_trees(parent_trees)
            return count
        finally:
            source.unlock()
            top_pb.finished()

    @needs_write_lock
    def put_file_bytes_non_atomic(self, file_id, bytes):
        """See MutableTree.put_file_bytes_non_atomic."""
        stream = file(self.id2abspath(file_id), 'wb')
        try:
            stream.write(bytes)
        finally:
            stream.close()
        # TODO: update the hashcache here ?

    def extras(self):
        """Yield all unknown files in this WorkingTree.

        If there are any unknown directories then only the directory is
        returned, not all its children.  But if there are unknown files
        under a versioned subdirectory, they are returned.

        Currently returned depth-first, sorted by name within directories.
        """
        ## TODO: Work from given directory downwards
        for path, dir_entry in self.inventory.directories():
            # mutter("search for unknowns in %r", path)
            dirabs = self.abspath(path)
            if not isdir(dirabs):
                # e.g. directory deleted
                continue

            fl = []
            for subf in os.listdir(dirabs):
                if subf == '.bzr':
                    continue
                if subf not in dir_entry.children:
                    subf_norm, can_access = osutils.normalized_filename(subf)
                    if subf_norm != subf and can_access:
                        if subf_norm not in dir_entry.children:
                            fl.append(subf_norm)
                    else:
                        fl.append(subf)
            
            fl.sort()
            for subf in fl:
                subp = pathjoin(path, subf)
                yield subp

    def _translate_ignore_rule(self, rule):
        """Translate a single ignore rule to a regex.

        There are two types of ignore rules.  Those that do not contain a / are
        matched against the tail of the filename (that is, they do not care
        what directory the file is in.)  Rules which do contain a slash must
        match the entire path.  As a special case, './' at the start of the
        string counts as a slash in the string but is removed before matching
        (e.g. ./foo.c, ./src/foo.c)

        :return: The translated regex.
        """
        if rule[:2] in ('./', '.\\'):
            # rootdir rule
            result = fnmatch.translate(rule[2:])
        elif '/' in rule or '\\' in rule:
            # path prefix 
            result = fnmatch.translate(rule)
        else:
            # default rule style.
            result = "(?:.*/)?(?!.*/)" + fnmatch.translate(rule)
        assert result[-1] == '$', "fnmatch.translate did not add the expected $"
        return "(" + result + ")"

    def _combine_ignore_rules(self, rules):
        """Combine a list of ignore rules into a single regex object.

        Each individual rule is combined with | to form a big regex, which then
        has $ added to it to form something like ()|()|()$. The group index for
        each subregex's outermost group is placed in a dictionary mapping back 
        to the rule. This allows quick identification of the matching rule that
        triggered a match.
        :return: a list of the compiled regex and the matching-group index 
        dictionaries. We return a list because python complains if you try to 
        combine more than 100 regexes.
        """
        result = []
        groups = {}
        next_group = 0
        translated_rules = []
        for rule in rules:
            translated_rule = self._translate_ignore_rule(rule)
            compiled_rule = re.compile(translated_rule)
            groups[next_group] = rule
            next_group += compiled_rule.groups
            translated_rules.append(translated_rule)
            if next_group == 99:
                result.append((re.compile("|".join(translated_rules)), groups))
                groups = {}
                next_group = 0
                translated_rules = []
        if len(translated_rules):
            result.append((re.compile("|".join(translated_rules)), groups))
        return result

    def ignored_files(self):
        """Yield list of PATH, IGNORE_PATTERN"""
        for subp in self.extras():
            pat = self.is_ignored(subp)
            if pat is not None:
                yield subp, pat

    def get_ignore_list(self):
        """Return list of ignore patterns.

        Cached in the Tree object after the first call.
        """
        ignoreset = getattr(self, '_ignoreset', None)
        if ignoreset is not None:
            return ignoreset

        ignore_globs = set(bzrlib.DEFAULT_IGNORE)
        ignore_globs.update(ignores.get_runtime_ignores())

        ignore_globs.update(ignores.get_user_ignores())

        if self.has_filename(bzrlib.IGNORE_FILENAME):
            f = self.get_file_byname(bzrlib.IGNORE_FILENAME)
            try:
                ignore_globs.update(ignores.parse_ignore_file(f))
            finally:
                f.close()

        self._ignoreset = ignore_globs
        self._ignore_regex = self._combine_ignore_rules(ignore_globs)
        return ignore_globs

    def _get_ignore_rules_as_regex(self):
        """Return a regex of the ignore rules and a mapping dict.

        :return: (ignore rules compiled regex, dictionary mapping rule group 
        indices to original rule.)
        """
        if getattr(self, '_ignoreset', None) is None:
            self.get_ignore_list()
        return self._ignore_regex

    def is_ignored(self, filename):
        r"""Check whether the filename matches an ignore pattern.

        Patterns containing '/' or '\' need to match the whole path;
        others match against only the last component.

        If the file is ignored, returns the pattern which caused it to
        be ignored, otherwise None.  So this can simply be used as a
        boolean if desired."""

        # TODO: Use '**' to match directories, and other extended
        # globbing stuff from cvs/rsync.

        # XXX: fnmatch is actually not quite what we want: it's only
        # approximately the same as real Unix fnmatch, and doesn't
        # treat dotfiles correctly and allows * to match /.
        # Eventually it should be replaced with something more
        # accurate.
    
        rules = self._get_ignore_rules_as_regex()
        for regex, mapping in rules:
            match = regex.match(filename)
            if match is not None:
                # one or more of the groups in mapping will have a non-None
                # group match.
                groups = match.groups()
                rules = [mapping[group] for group in 
                    mapping if groups[group] is not None]
                return rules[0]
        return None

    def kind(self, file_id):
        return file_kind(self.id2abspath(file_id))

    def last_revision(self):
        """Return the last revision of the branch for this tree.

        This format tree does not support a separate marker for last-revision
        compared to the branch.

        See MutableTree.last_revision
        """
        return self._last_revision()

    @needs_read_lock
    def _last_revision(self):
        """helper for get_parent_ids."""
        return self.branch.last_revision()

    def is_locked(self):
        return self._control_files.is_locked()

    def lock_read(self):
        """See Branch.lock_read, and WorkingTree.unlock."""
        self.branch.lock_read()
        try:
            return self._control_files.lock_read()
        except:
            self.branch.unlock()
            raise

    def lock_tree_write(self):
        """See MutableTree.lock_tree_write, and WorkingTree.unlock."""
        self.branch.lock_read()
        try:
            return self._control_files.lock_write()
        except:
            self.branch.unlock()
            raise

    def lock_write(self):
        """See MutableTree.lock_write, and WorkingTree.unlock."""
        self.branch.lock_write()
        try:
            return self._control_files.lock_write()
        except:
            self.branch.unlock()
            raise

    def get_physical_lock_status(self):
        return self._control_files.get_physical_lock_status()

    def _basis_inventory_name(self):
        return 'basis-inventory-cache'

    @needs_tree_write_lock
    def set_last_revision(self, new_revision):
        """Change the last revision in the working tree."""
        if self._change_last_revision(new_revision):
            self._cache_basis_inventory(new_revision)

    def _change_last_revision(self, new_revision):
        """Template method part of set_last_revision to perform the change.
        
        This is used to allow WorkingTree3 instances to not affect branch
        when their last revision is set.
        """
        if new_revision is None:
            self.branch.set_revision_history([])
            return False
        try:
            self.branch.generate_revision_history(new_revision)
        except errors.NoSuchRevision:
            # not present in the repo - dont try to set it deeper than the tip
            self.branch.set_revision_history([new_revision])
        return True

    def _write_basis_inventory(self, xml):
        """Write the basis inventory XML to the basis-inventory file"""
        assert isinstance(xml, str), 'serialised xml must be bytestring.'
        path = self._basis_inventory_name()
        sio = StringIO(xml)
        self._control_files.put(path, sio)

    def _create_basis_xml_from_inventory(self, revision_id, inventory):
        """Create the text that will be saved in basis-inventory"""
        inventory.revision_id = revision_id
        return bzrlib.xml6.serializer_v6.write_inventory_to_string(inventory)

    def _cache_basis_inventory(self, new_revision):
        """Cache new_revision as the basis inventory."""
        # TODO: this should allow the ready-to-use inventory to be passed in,
        # as commit already has that ready-to-use [while the format is the
        # same, that is].
        try:
            # this double handles the inventory - unpack and repack - 
            # but is easier to understand. We can/should put a conditional
            # in here based on whether the inventory is in the latest format
            # - perhaps we should repack all inventories on a repository
            # upgrade ?
            # the fast path is to copy the raw xml from the repository. If the
            # xml contains 'revision_id="', then we assume the right 
            # revision_id is set. We must check for this full string, because a
            # root node id can legitimately look like 'revision_id' but cannot
            # contain a '"'.
            xml = self.branch.repository.get_inventory_xml(new_revision)
            firstline = xml.split('\n', 1)[0]
            if (not 'revision_id="' in firstline or 
                'format="6"' not in firstline):
                inv = self.branch.repository.deserialise_inventory(
                    new_revision, xml)
                xml = self._create_basis_xml_from_inventory(new_revision, inv)
            self._write_basis_inventory(xml)
        except (errors.NoSuchRevision, errors.RevisionNotPresent):
            pass

    def read_basis_inventory(self):
        """Read the cached basis inventory."""
        path = self._basis_inventory_name()
        return self._control_files.get(path).read()
        
    @needs_read_lock
    def read_working_inventory(self):
        """Read the working inventory."""
        # ElementTree does its own conversion from UTF-8, so open in
        # binary.
        result = bzrlib.xml5.serializer_v5.read_inventory(
            self._control_files.get('inventory'))
        self._set_inventory(result)
        return result

    @needs_tree_write_lock
    def remove(self, files, verbose=False, to_file=None):
        """Remove nominated files from the working inventory..

        This does not remove their text.  This does not run on XXX on what? RBC

        TODO: Refuse to remove modified files unless --force is given?

        TODO: Do something useful with directories.

        TODO: Should this remove the text or not?  Tough call; not
        removing may be useful and the user can just use use rm, and
        is the opposite of add.  Removing it is consistent with most
        other tools.  Maybe an option.
        """
        ## TODO: Normalize names
        ## TODO: Remove nested loops; better scalability
        if isinstance(files, basestring):
            files = [files]

        inv = self.inventory

        # do this before any modifications
        for f in files:
            fid = inv.path2id(f)
            if not fid:
                # TODO: Perhaps make this just a warning, and continue?
                # This tends to happen when 
                raise NotVersionedError(path=f)
            if verbose:
                # having remove it, it must be either ignored or unknown
                if self.is_ignored(f):
                    new_status = 'I'
                else:
                    new_status = '?'
                show_status(new_status, inv[fid].kind, f, to_file=to_file)
            del inv[fid]

        self._write_inventory(inv)

    @needs_tree_write_lock
    def revert(self, filenames, old_tree=None, backups=True, 
               pb=DummyProgress()):
        from transform import revert
        from conflicts import resolve
        if old_tree is None:
            old_tree = self.basis_tree()
        conflicts = revert(self, old_tree, filenames, backups, pb)
        if not len(filenames):
            self.set_parent_ids(self.get_parent_ids()[:1])
            resolve(self)
        else:
            resolve(self, filenames, ignore_misses=True)
        return conflicts

    # XXX: This method should be deprecated in favour of taking in a proper
    # new Inventory object.
    @needs_tree_write_lock
    def set_inventory(self, new_inventory_list):
        from bzrlib.inventory import (Inventory,
                                      InventoryDirectory,
                                      InventoryEntry,
                                      InventoryFile,
                                      InventoryLink)
        inv = Inventory(self.get_root_id())
        for path, file_id, parent, kind in new_inventory_list:
            name = os.path.basename(path)
            if name == "":
                continue
            # fixme, there should be a factory function inv,add_?? 
            if kind == 'directory':
                inv.add(InventoryDirectory(file_id, name, parent))
            elif kind == 'file':
                inv.add(InventoryFile(file_id, name, parent))
            elif kind == 'symlink':
                inv.add(InventoryLink(file_id, name, parent))
            else:
                raise BzrError("unknown kind %r" % kind)
        self._write_inventory(inv)

    @needs_tree_write_lock
    def set_root_id(self, file_id):
        """Set the root id for this tree."""
        inv = self.read_working_inventory()
        orig_root_id = inv.root.file_id
        del inv._byid[inv.root.file_id]
        inv.root.file_id = file_id
        inv._byid[inv.root.file_id] = inv.root
        for fid in inv:
            entry = inv[fid]
            if entry.parent_id == orig_root_id:
                entry.parent_id = inv.root.file_id
        self._write_inventory(inv)

    def unlock(self):
        """See Branch.unlock.
        
        WorkingTree locking just uses the Branch locking facilities.
        This is current because all working trees have an embedded branch
        within them. IF in the future, we were to make branch data shareable
        between multiple working trees, i.e. via shared storage, then we 
        would probably want to lock both the local tree, and the branch.
        """
        raise NotImplementedError(self.unlock)

    @needs_write_lock
    def update(self):
        """Update a working tree along its branch.

        This will update the branch if its bound too, which means we have
        multiple trees involved:

        - The new basis tree of the master.
        - The old basis tree of the branch.
        - The old basis tree of the working tree.
        - The current working tree state.

        Pathologically, all three may be different, and non-ancestors of each
        other.  Conceptually we want to:

        - Preserve the wt.basis->wt.state changes
        - Transform the wt.basis to the new master basis.
        - Apply a merge of the old branch basis to get any 'local' changes from
          it into the tree.
        - Restore the wt.basis->wt.state changes.

        There isn't a single operation at the moment to do that, so we:
        - Merge current state -> basis tree of the master w.r.t. the old tree
          basis.
        - Do a 'normal' merge of the old branch basis if it is relevant.
        """
        old_tip = self.branch.update()

        # here if old_tip is not None, it is the old tip of the branch before
        # it was updated from the master branch. This should become a pending
        # merge in the working tree to preserve the user existing work.  we
        # cant set that until we update the working trees last revision to be
        # one from the new branch, because it will just get absorbed by the
        # parent de-duplication logic.
        # 
        # We MUST save it even if an error occurs, because otherwise the users
        # local work is unreferenced and will appear to have been lost.
        # 
        result = 0
        try:
            last_rev = self.get_parent_ids()[0]
        except IndexError:
            last_rev = None
        if last_rev != self.branch.last_revision():
            # merge tree state up to new branch tip.
            basis = self.basis_tree()
            to_tree = self.branch.basis_tree()
            if basis.inventory.root is None:
                self.set_root_id(to_tree.inventory.root.file_id)
            result += merge_inner(self.branch,
                                  to_tree,
                                  basis,
                                  this_tree=self)
            # TODO - dedup parents list with things merged by pull ?
            # reuse the tree we've updated to to set the basis:
            parent_trees = [(self.branch.last_revision(), to_tree)]
            merges = self.get_parent_ids()[1:]
            # Ideally we ask the tree for the trees here, that way the working
            # tree can decide whether to give us teh entire tree or give us a
            # lazy initialised tree. dirstate for instance will have the trees
            # in ram already, whereas a last-revision + basis-inventory tree
            # will not, but also does not need them when setting parents.
            for parent in merges:
                parent_trees.append(
                    (parent, self.branch.repository.revision_tree(parent)))
            if old_tip is not None:
                parent_trees.append(
                    (old_tip, self.branch.repository.revision_tree(old_tip)))
            self.set_parent_trees(parent_trees)
            last_rev = parent_trees[0][0]
        else:
            # the working tree had the same last-revision as the master
            # branch did. We may still have pivot local work from the local
            # branch into old_tip:
            if old_tip is not None:
                self.add_parent_tree_id(old_tip)
        if old_tip and old_tip != last_rev:
            # our last revision was not the prior branch last revision
            # and we have converted that last revision to a pending merge.
            # base is somewhere between the branch tip now
            # and the now pending merge
            from bzrlib.revision import common_ancestor
            try:
                base_rev_id = common_ancestor(self.branch.last_revision(),
                                              old_tip,
                                              self.branch.repository)
            except errors.NoCommonAncestor:
                base_rev_id = None
            base_tree = self.branch.repository.revision_tree(base_rev_id)
            other_tree = self.branch.repository.revision_tree(old_tip)
            result += merge_inner(self.branch,
                                  other_tree,
                                  base_tree,
                                  this_tree=self)
        return result

    @needs_tree_write_lock
    def _write_inventory(self, inv):
        """Write inventory as the current inventory."""
        sio = StringIO()
        bzrlib.xml5.serializer_v5.write_inventory(inv, sio)
        sio.seek(0)
        self._control_files.put('inventory', sio)
        self._set_inventory(inv)
        mutter('wrote working inventory')

    def set_conflicts(self, arg):
        raise UnsupportedOperation(self.set_conflicts, self)

    def add_conflicts(self, arg):
        raise UnsupportedOperation(self.add_conflicts, self)

    @needs_read_lock
    def conflicts(self):
        conflicts = ConflictList()
        for conflicted in self._iter_conflicts():
            text = True
            try:
                if file_kind(self.abspath(conflicted)) != "file":
                    text = False
            except errors.NoSuchFile:
                text = False
            if text is True:
                for suffix in ('.THIS', '.OTHER'):
                    try:
                        kind = file_kind(self.abspath(conflicted+suffix))
                        if kind != "file":
                            text = False
                    except errors.NoSuchFile:
                        text = False
                    if text == False:
                        break
            ctype = {True: 'text conflict', False: 'contents conflict'}[text]
            conflicts.append(Conflict.factory(ctype, path=conflicted,
                             file_id=self.path2id(conflicted)))
        return conflicts


class WorkingTree2(WorkingTree):
    """This is the Format 2 working tree.

    This was the first weave based working tree. 
     - uses os locks for locking.
     - uses the branch last-revision.
    """

    def lock_tree_write(self):
        """See WorkingTree.lock_tree_write().

        In Format2 WorkingTrees we have a single lock for the branch and tree
        so lock_tree_write() degrades to lock_write().
        """
        self.branch.lock_write()
        try:
            return self._control_files.lock_write()
        except:
            self.branch.unlock()
            raise

    def unlock(self):
        # we share control files:
        if self._hashcache.needs_write and self._control_files._lock_count==3:
            self._hashcache.write()
        # reverse order of locking.
        try:
            return self._control_files.unlock()
        finally:
            self.branch.unlock()


class WorkingTree3(WorkingTree):
    """This is the Format 3 working tree.

    This differs from the base WorkingTree by:
     - having its own file lock
     - having its own last-revision property.

    This is new in bzr 0.8
    """

    @needs_read_lock
    def _last_revision(self):
        """See Mutable.last_revision."""
        try:
            return self._control_files.get_utf8('last-revision').read()
        except NoSuchFile:
            return None

    def _change_last_revision(self, revision_id):
        """See WorkingTree._change_last_revision."""
        if revision_id is None or revision_id == NULL_REVISION:
            try:
                self._control_files._transport.delete('last-revision')
            except errors.NoSuchFile:
                pass
            return False
        else:
            self._control_files.put_utf8('last-revision', revision_id)
            return True

    @needs_tree_write_lock
    def set_conflicts(self, conflicts):
        self._put_rio('conflicts', conflicts.to_stanzas(), 
                      CONFLICT_HEADER_1)

    @needs_tree_write_lock
    def add_conflicts(self, new_conflicts):
        conflict_set = set(self.conflicts())
        conflict_set.update(set(list(new_conflicts)))
        self.set_conflicts(ConflictList(sorted(conflict_set,
                                               key=Conflict.sort_key)))

    @needs_read_lock
    def conflicts(self):
        try:
            confile = self._control_files.get('conflicts')
        except NoSuchFile:
            return ConflictList()
        try:
            if confile.next() != CONFLICT_HEADER_1 + '\n':
                raise ConflictFormatError()
        except StopIteration:
            raise ConflictFormatError()
        return ConflictList.from_stanzas(RioReader(confile))

    def unlock(self):
        if self._hashcache.needs_write and self._control_files._lock_count==1:
            self._hashcache.write()
        # reverse order of locking.
        try:
            return self._control_files.unlock()
        finally:
            self.branch.unlock()


def get_conflicted_stem(path):
    for suffix in CONFLICT_SUFFIXES:
        if path.endswith(suffix):
            return path[:-len(suffix)]

@deprecated_function(zero_eight)
def is_control_file(filename):
    """See WorkingTree.is_control_filename(filename)."""
    ## FIXME: better check
    filename = normpath(filename)
    while filename != '':
        head, tail = os.path.split(filename)
        ## mutter('check %r for control file' % ((head, tail),))
        if tail == '.bzr':
            return True
        if filename == head:
            break
        filename = head
    return False


class WorkingTreeFormat(object):
    """An encapsulation of the initialization and open routines for a format.

    Formats provide three things:
     * An initialization routine,
     * a format string,
     * an open routine.

    Formats are placed in an dict by their format string for reference 
    during workingtree opening. Its not required that these be instances, they
    can be classes themselves with class methods - it simply depends on 
    whether state is needed for a given format or not.

    Once a format is deprecated, just deprecate the initialize and open
    methods on the format class. Do not deprecate the object, as the 
    object will be created every time regardless.
    """

    _default_format = None
    """The default format used for new trees."""

    _formats = {}
    """The known formats."""

    @classmethod
    def find_format(klass, a_bzrdir):
        """Return the format for the working tree object in a_bzrdir."""
        try:
            transport = a_bzrdir.get_workingtree_transport(None)
            format_string = transport.get("format").read()
            return klass._formats[format_string]
        except NoSuchFile:
            raise errors.NoWorkingTree(base=transport.base)
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
        """Return the short description for this format."""
        raise NotImplementedError(self.get_format_description)

    def is_supported(self):
        """Is this format supported?

        Supported formats can be initialized and opened.
        Unsupported formats may not support initialization or committing or 
        some other features depending on the reason for not being supported.
        """
        return True

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



class WorkingTreeFormat2(WorkingTreeFormat):
    """The second working tree format. 

    This format modified the hash cache from the format 1 hash cache.
    """

    def get_format_description(self):
        """See WorkingTreeFormat.get_format_description()."""
        return "Working tree format 2"

    def stub_initialize_remote(self, control_files):
        """As a special workaround create critical control files for a remote working tree
        
        This ensures that it can later be updated and dealt with locally,
        since BzrDirFormat6 and BzrDirFormat5 cannot represent dirs with 
        no working tree.  (See bug #43064).
        """
        sio = StringIO()
        inv = Inventory()
        bzrlib.xml5.serializer_v5.write_inventory(inv, sio)
        sio.seek(0)
        control_files.put('inventory', sio)

        control_files.put_utf8('pending-merges', '')
        

    def initialize(self, a_bzrdir, revision_id=None):
        """See WorkingTreeFormat.initialize()."""
        if not isinstance(a_bzrdir.transport, LocalTransport):
            raise errors.NotLocalUrl(a_bzrdir.transport.base)
        branch = a_bzrdir.open_branch()
        if revision_id is not None:
            branch.lock_write()
            try:
                revision_history = branch.revision_history()
                try:
                    position = revision_history.index(revision_id)
                except ValueError:
                    raise errors.NoSuchRevision(branch, revision_id)
                branch.set_revision_history(revision_history[:position + 1])
            finally:
                branch.unlock()
        revision = branch.last_revision()
        inv = Inventory()
        wt = WorkingTree2(a_bzrdir.root_transport.local_abspath('.'),
                         branch,
                         inv,
                         _internal=True,
                         _format=self,
                         _bzrdir=a_bzrdir)
        wt.set_last_revision(revision)
        basis_tree = wt.basis_tree()
        if basis_tree.inventory.root is not None:
            inv.root.file_id = basis_tree.inventory.root.file_id
        wt._write_inventory(inv)
        wt.set_parent_trees([(revision, basis_tree)])
        build_tree(basis_tree, wt)
        return wt

    def __init__(self):
        super(WorkingTreeFormat2, self).__init__()
        self._matchingbzrdir = bzrdir.BzrDirFormat6()

    def open(self, a_bzrdir, _found=False):
        """Return the WorkingTree object for a_bzrdir

        _found is a private parameter, do not use it. It is used to indicate
               if format probing has already been done.
        """
        if not _found:
            # we are being called directly and must probe.
            raise NotImplementedError
        if not isinstance(a_bzrdir.transport, LocalTransport):
            raise errors.NotLocalUrl(a_bzrdir.transport.base)
        return WorkingTree2(a_bzrdir.root_transport.local_abspath('.'),
                           _internal=True,
                           _format=self,
                           _bzrdir=a_bzrdir)


class WorkingTreeFormat3(WorkingTreeFormat):
    """The second working tree format updated to record a format marker.

    This format:
        - exists within a metadir controlling .bzr
        - includes an explicit version marker for the workingtree control
          files, separate from the BzrDir format
        - modifies the hash cache format
        - is new in bzr 0.8
        - uses a LockDir to guard access for writes.
    """

    def get_format_string(self):
        """See WorkingTreeFormat.get_format_string()."""
        return "Bazaar-NG Working Tree format 3"

    def get_format_description(self):
        """See WorkingTreeFormat.get_format_description()."""
        return "Working tree format 3"

    _lock_file_name = 'lock'
    _lock_class = LockDir

    def _open_control_files(self, a_bzrdir):
        transport = a_bzrdir.get_workingtree_transport(None)
        return LockableFiles(transport, self._lock_file_name, 
                             self._lock_class)

    def initialize(self, a_bzrdir, revision_id=None):
        """See WorkingTreeFormat.initialize().
        
        revision_id allows creating a working tree at a different
        revision than the branch is at.
        """
        if not isinstance(a_bzrdir.transport, LocalTransport):
            raise errors.NotLocalUrl(a_bzrdir.transport.base)
        transport = a_bzrdir.get_workingtree_transport(self)
        control_files = self._open_control_files(a_bzrdir)
        control_files.create_lock()
        control_files.lock_write()
        control_files.put_utf8('format', self.get_format_string())
        branch = a_bzrdir.open_branch()
        if revision_id is None:
            revision_id = branch.last_revision()
        inv = Inventory(root_id=gen_root_id()) 
        wt = WorkingTree3(a_bzrdir.root_transport.local_abspath('.'),
                         branch,
                         inv,
                         _internal=True,
                         _format=self,
                         _bzrdir=a_bzrdir,
                         _control_files=control_files)
        wt.lock_tree_write()
        try:
            wt.set_last_revision(revision_id)
            basis_tree = wt.basis_tree()
            wt._write_inventory(inv)
            wt.set_pending_merges([])
            if revision_id == bzrlib.revision.NULL_REVISION:
                wt.set_parent_trees([])
            else:
                wt.set_parent_trees([(revision_id, basis_tree)])
            build_tree(basis_tree, wt)
        finally:
            wt.unlock()
            control_files.unlock()
        return wt

    def __init__(self):
        super(WorkingTreeFormat3, self).__init__()
        self._matchingbzrdir = bzrdir.BzrDirMetaFormat1()

    def open(self, a_bzrdir, _found=False):
        """Return the WorkingTree object for a_bzrdir

        _found is a private parameter, do not use it. It is used to indicate
               if format probing has already been done.
        """
        if not _found:
            # we are being called directly and must probe.
            raise NotImplementedError
        if not isinstance(a_bzrdir.transport, LocalTransport):
            raise errors.NotLocalUrl(a_bzrdir.transport.base)
        return self._open(a_bzrdir, self._open_control_files(a_bzrdir))

    def _open(self, a_bzrdir, control_files):
        """Open the tree itself.
        
        :param a_bzrdir: the dir for the tree.
        :param control_files: the control files for the tree.
        """
        return WorkingTree3(a_bzrdir.root_transport.local_abspath('.'),
                           _internal=True,
                           _format=self,
                           _bzrdir=a_bzrdir,
                           _control_files=control_files)

    def __str__(self):
        return self.get_format_string()


# formats which have no format string are not discoverable
# and not independently creatable, so are not registered.
__default_format = WorkingTreeFormat3()
WorkingTreeFormat.register_format(__default_format)
WorkingTreeFormat.set_default_format(__default_format)
_legacy_formats = [WorkingTreeFormat2(),
                   ]


class WorkingTreeTestProviderAdapter(object):
    """A tool to generate a suite testing multiple workingtree formats at once.

    This is done by copying the test once for each transport and injecting
    the transport_server, transport_readonly_server, and workingtree_format
    classes into each copy. Each copy is also given a new id() to make it
    easy to identify.
    """

    def __init__(self, transport_server, transport_readonly_server, formats):
        self._transport_server = transport_server
        self._transport_readonly_server = transport_readonly_server
        self._formats = formats
    
    def _clone_test(self, test, bzrdir_format, workingtree_format, variation):
        """Clone test for adaption."""
        new_test = deepcopy(test)
        new_test.transport_server = self._transport_server
        new_test.transport_readonly_server = self._transport_readonly_server
        new_test.bzrdir_format = bzrdir_format
        new_test.workingtree_format = workingtree_format
        def make_new_test_id():
            new_id = "%s(%s)" % (test.id(), variation)
            return lambda: new_id
        new_test.id = make_new_test_id()
        return new_test
    
    def adapt(self, test):
        from bzrlib.tests import TestSuite
        result = TestSuite()
        for workingtree_format, bzrdir_format in self._formats:
            new_test = self._clone_test(
                test,
                bzrdir_format,
                workingtree_format, workingtree_format.__class__.__name__)
            result.addTest(new_test)
        return result
