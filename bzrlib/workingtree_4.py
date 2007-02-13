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

"""WorkingTree4 format and implementation.

WorkingTree4 provides the dirstate based working tree logic.

To get a WorkingTree, call bzrdir.open_workingtree() or
WorkingTree.open(dir).
"""

import os

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
from bisect import bisect_left
import collections
from copy import deepcopy
import errno
import itertools
import operator
import stat
from time import time
import warnings

import bzrlib
from bzrlib import (
    bzrdir,
    conflicts as _mod_conflicts,
    dirstate,
    errors,
    generate_ids,
    globbing,
    hashcache,
    ignores,
    merge,
    osutils,
    textui,
    transform,
    urlutils,
    xml5,
    xml6,
    )
import bzrlib.branch
from bzrlib.transport import get_transport
import bzrlib.ui
""")

from bzrlib import symbol_versioning
from bzrlib.decorators import needs_read_lock, needs_write_lock
from bzrlib.inventory import InventoryEntry, Inventory, ROOT_ID, make_entry
from bzrlib.lockable_files import LockableFiles, TransportLock
from bzrlib.lockdir import LockDir
import bzrlib.mutabletree
from bzrlib.mutabletree import needs_tree_write_lock
from bzrlib.osutils import (
    compact_date,
    file_kind,
    isdir,
    normpath,
    pathjoin,
    rand_chars,
    realpath,
    safe_unicode,
    splitpath,
    supports_executable,
    )
from bzrlib.trace import mutter, note
from bzrlib.transport.local import LocalTransport
from bzrlib.progress import DummyProgress, ProgressPhase
from bzrlib.revision import NULL_REVISION, CURRENT_REVISION
from bzrlib.rio import RioReader, rio_file, Stanza
from bzrlib.symbol_versioning import (deprecated_passed,
        deprecated_method,
        deprecated_function,
        DEPRECATED_PARAMETER,
        zero_eight,
        zero_eleven,
        zero_thirteen,
        )
from bzrlib.tree import Tree
from bzrlib.workingtree import WorkingTree3, WorkingTreeFormat3


class WorkingTree4(WorkingTree3):
    """This is the Format 4 working tree.

    This differs from WorkingTree3 by:
     - having a consolidated internal dirstate.
     - not having a regular inventory attribute.

    This is new in bzr TODO FIXME SETMEBEFORE MERGE.
    """

    def __init__(self, basedir,
                 branch,
                 _control_files=None,
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
        from bzrlib.hashcache import HashCache
        from bzrlib.trace import note, mutter
        assert isinstance(basedir, basestring), \
            "base directory %r is not a string" % basedir
        basedir = safe_unicode(basedir)
        mutter("opening working tree %r", basedir)
        self._branch = branch
        assert isinstance(self.branch, bzrlib.branch.Branch), \
            "branch %r is not a Branch" % self.branch
        self.basedir = realpath(basedir)
        # if branch is at our basedir and is a format 6 or less
        # assume all other formats have their own control files.
        assert isinstance(_control_files, LockableFiles), \
            "_control_files must be a LockableFiles, not %r" % _control_files
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

        self._dirty = None
        self._parent_revisions = None
        #-------------
        # during a read or write lock these objects are set, and are
        # None the rest of the time.
        self._dirstate = None
        self._inventory = None
        #-------------

    @needs_tree_write_lock
    def _add(self, files, ids, kinds):
        """See MutableTree._add."""
        state = self.current_dirstate()
        for f, file_id, kind in zip(files, ids, kinds):
            f = f.strip('/')
            assert '//' not in f
            assert '..' not in f
            if file_id is None:
                file_id = generate_ids.gen_file_id(f)
            stat = os.lstat(self.abspath(f))
            sha1 = '1' * 20 # FIXME: DIRSTATE MERGE BLOCKER
            state.add(f, file_id, kind, stat, sha1)
        self._dirty = True

    def current_dirstate(self):
        """Return the current dirstate object. 

        This is not part of the tree interface and only exposed for ease of
        testing.

        :raises errors.NotWriteLocked: when not in a lock. 
            XXX: This should probably be errors.NotLocked.
        """
        if not self._control_files._lock_count:
            raise errors.ObjectNotLocked(self)
        if self._dirstate is not None:
            return self._dirstate
        local_path = self.bzrdir.get_workingtree_transport(None
            ).local_abspath('dirstate')
        self._dirstate = dirstate.DirState.on_file(local_path)
        return self._dirstate

    def flush(self):
        """Write all cached data to disk."""
        self.current_dirstate().save()
        self._inventory = None
        self._dirty = False

    def _generate_inventory(self):
        """Create and set self.inventory from the dirstate object.
        
        This is relatively expensive: we have to walk the entire dirstate.
        Ideally we would not, and can deprecate this function.
        """
        dirstate = self.current_dirstate()
        rows = self._dirstate._iter_rows()
        root_row = rows.next()
        inv = Inventory(root_id=root_row[0][3].decode('utf8'))
        for line in rows:
            dirname, name, kind, fileid_utf8, size, stat, link_or_sha1 = line[0]
            if dirname == '/':
                # not in this revision tree.
                continue
            parent_id = inv[inv.path2id(dirname.decode('utf8'))].file_id
            file_id = fileid_utf8.decode('utf8')
            entry = make_entry(kind, name.decode('utf8'), parent_id, file_id)
            if kind == 'file':
                #entry.executable = executable
                #entry.text_size = size
                #entry.text_sha1 = sha1
                pass
            inv.add(entry)
        self._inventory = inv

    def _get_inventory(self):
        """Get the inventory for the tree. This is only valid within a lock."""
        if self._inventory is not None:
            return self._inventory
        self._generate_inventory()
        return self._inventory

    inventory = property(_get_inventory,
                         doc="Inventory of this Tree")

    @needs_read_lock
    def get_root_id(self):
        """Return the id of this trees root"""
        return self.current_dirstate()._iter_rows().next()[0][3].decode('utf8')

    def has_id(self, file_id):
        state = self.current_dirstate()
        fileid_utf8 = file_id.encode('utf8')
        for row, parents in state._iter_rows():
            if row[3] == fileid_utf8:
                return osutils.lexists(pathjoin(
                    self.basedir, row[0].decode('utf8'), row[1].decode('utf8')))
        return False

    @needs_read_lock
    def id2path(self, fileid):
        state = self.current_dirstate()
        fileid_utf8 = fileid.encode('utf8')
        for row, parents in state._iter_rows():
            if row[3] == fileid_utf8:
                return (row[0] + '/' + row[1]).decode('utf8').strip('/')

    @needs_read_lock
    def __iter__(self):
        """Iterate through file_ids for this tree.

        file_ids are in a WorkingTree if they are in the working inventory
        and the working file exists.
        """
        result = []
        for row, parents in self.current_dirstate()._iter_rows():
            if row[0] == '/':
                continue
            path = pathjoin(self.basedir, row[0].decode('utf8'), row[1].decode('utf8'))
            if osutils.lexists(path):
                result.append(row[3].decode('utf8'))
        return iter(result)

    @needs_read_lock
    def _last_revision(self):
        """See Mutable.last_revision."""
        parent_ids = self.current_dirstate().get_parent_ids()
        if parent_ids:
            return parent_ids[0].decode('utf8')
        else:
            return None

    def _new_tree(self):
        """Initialize the state in this tree to be a new tree."""
        self._parent_revisions = [NULL_REVISION]
        self._dirty = True

    @needs_read_lock
    def path2id(self, path):
        """Return the id for path in this tree."""
        state = self.current_dirstate()
        path_utf8 = os.path.split(path.encode('utf8'))
        for row, parents in state._iter_rows():
            if row[0:2] == path_utf8:
                return row[3].decode('utf8')
        return None

    @needs_read_lock
    def revision_tree(self, revision_id):
        """See Tree.revision_tree.

        WorkingTree4 supplies revision_trees for any basis tree.
        """
        dirstate = self.current_dirstate()
        parent_ids = dirstate.get_parent_ids()
        if revision_id not in parent_ids:
            raise errors.NoSuchRevisionInTree(self, revision_id)
        return DirStateRevisionTree(dirstate, revision_id,
            self.branch.repository)

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
        trees = []
        for revision_id in revision_ids:
            try:
                revtree = self.branch.repository.revision_tree(revision_id)
                # TODO: jam 20070213 KnitVersionedFile raises
                #       RevisionNotPresent rather than NoSuchRevision if a
                #       given revision_id is not present. Should Repository be
                #       catching it and re-raising NoSuchRevision?
            except (errors.NoSuchRevision, errors.RevisionNotPresent):
                revtree = None
            trees.append((revision_id, revtree))
        self.set_parent_trees(trees,
            allow_leftmost_as_ghost=allow_leftmost_as_ghost)

    @needs_tree_write_lock
    def set_parent_trees(self, parents_list, allow_leftmost_as_ghost=False):
        """Set the parents of the working tree.

        :param parents_list: A list of (revision_id, tree) tuples. 
            If tree is None, then that element is treated as an unreachable
            parent tree - i.e. a ghost.
        """
        dirstate = self.current_dirstate()
        if len(parents_list) > 0:
            if not allow_leftmost_as_ghost and parents_list[0][1] is None:
                raise errors.GhostRevisionUnusableHere(leftmost_id)
        real_trees = []
        ghosts = []
        # convert absent trees to the null tree, which we convert back to 
        # missing on access.
        for rev_id, tree in parents_list:
            if tree is not None:
                real_trees.append((rev_id, tree))
            else:
                real_trees.append((rev_id,
                    self.branch.repository.revision_tree(None)))
                ghosts.append(rev_id)
        dirstate.set_parent_trees(real_trees, ghosts=ghosts)
        self._dirty = True

    def _set_root_id(self, file_id):
        """See WorkingTree.set_root_id."""
        self.current_dirstate().set_path_id('', file_id)
        self._dirty = True

    def unlock(self):
        """Unlock in format 4 trees needs to write the entire dirstate."""
        if self._control_files._lock_count == 1:
            if self._hashcache.needs_write:
                self._hashcache.write()
            # eventually we should do signature checking during read locks for
            # dirstate updates.
            if self._control_files._lock_mode == 'w':
                if self._dirty:
                    self.flush()
            self._dirstate = None
            self._inventory = None
        # reverse order of locking.
        try:
            return self._control_files.unlock()
        finally:
            self.branch.unlock()

    @needs_tree_write_lock
    def unversion(self, file_ids):
        """Remove the file ids in file_ids from the current versioned set.

        When a file_id is unversioned, all of its children are automatically
        unversioned.

        :param file_ids: The file ids to stop versioning.
        :raises: NoSuchId if any fileid is not currently versioned.
        """
        if not file_ids:
            return
        state = self.current_dirstate()
        state._read_dirblocks_if_needed()
        ids_to_unversion = set()
        for fileid in file_ids:
            ids_to_unversion.add(fileid.encode('utf8'))
        paths_to_unversion = set()
        # sketch:
        # check if the root is to be unversioned, if so, assert for now.
        # make a copy of the _dirblocks data 
        # during the copy,
        #  skip paths in paths_to_unversion
        #  skip ids in ids_to_unversion, and add their paths to
        #  paths_to_unversion if they are a directory
        # if there are any un-unversioned ids at the end, raise
        if state._root_row[0][3] in ids_to_unversion:
            # I haven't written the code to unversion / yet - it should be 
            # supported.
            raise errors.BzrError('Unversioning the / is not currently supported')
        new_blocks = []
        for block in state._dirblocks:
            # first check: is the path one to remove - it or its children
            delete_block = False
            for path in paths_to_unversion:
                if (block[0].startswith(path) and
                    (len(block[0]) == len(path) or
                     block[0][len(path)] == '/')):
                    # this path should be deleted
                    delete_block = True
                    break
            # TODO: trim paths_to_unversion as we pass by paths
            if delete_block:
                # this block is to be deleted. skip it.
                continue
            # copy undeleted rows from within the the block
            new_blocks.append((block[0], []))
            new_row = new_blocks[-1][1]
            for row, row_parents in block[1]:
                if row[3] not in ids_to_unversion:
                    new_row.append((row, row_parents))
                else:
                    # skip the row, and if its a dir mark its path to be removed
                    if row[2] == 'directory':
                        paths_to_unversion.add((row[0] + '/' + row[1]).strip('/'))
                    assert not row_parents, "not ready to preserve parents."
                    ids_to_unversion.remove(row[3])
        if ids_to_unversion:
            raise errors.NoSuchId(self, iter(ids_to_unversion).next())
        state._dirblocks = new_blocks
        state._dirblock_state = dirstate.DirState.IN_MEMORY_MODIFIED
        # have to change the legacy inventory too.
        if self._inventory is not None:
            for file_id in file_ids:
                if self._inventory.has_id(file_id):
                    self._inventory.remove_recursive_id(file_id)

    @needs_tree_write_lock
    def _write_inventory(self, inv):
        """Write inventory as the current inventory."""
        assert not self._dirty, "attempting to write an inventory when the dirstate is dirty will cause data loss"
        self.current_dirstate().set_state_from_inventory(inv)
        self._dirty = True
        self.flush()


class WorkingTreeFormat4(WorkingTreeFormat3):
    """The first consolidated dirstate working tree format.

    This format:
        - exists within a metadir controlling .bzr
        - includes an explicit version marker for the workingtree control
          files, separate from the BzrDir format
        - modifies the hash cache format
        - is new in bzr TODO FIXME SETBEFOREMERGE
        - uses a LockDir to guard access to it.
    """

    def get_format_string(self):
        """See WorkingTreeFormat.get_format_string()."""
        return "Bazaar Working Tree format 4\n"

    def get_format_description(self):
        """See WorkingTreeFormat.get_format_description()."""
        return "Working tree format 4"

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
        local_path = transport.local_abspath('dirstate')
        dirstate.DirState.initialize(local_path)
        wt = WorkingTree4(a_bzrdir.root_transport.local_abspath('.'),
                         branch,
                         _format=self,
                         _bzrdir=a_bzrdir,
                         _control_files=control_files)
        wt._new_tree()
        wt.lock_write()
        try:
            #wt.current_dirstate().set_path_id('', NEWROOT)
            wt.set_last_revision(revision_id)
            wt.flush()
            transform.build_tree(wt.basis_tree(), wt)
        finally:
            control_files.unlock()
            wt.unlock()
        return wt


    def _open(self, a_bzrdir, control_files):
        """Open the tree itself.
        
        :param a_bzrdir: the dir for the tree.
        :param control_files: the control files for the tree.
        """
        return WorkingTree4(a_bzrdir.root_transport.local_abspath('.'),
                           branch=a_bzrdir.open_branch(),
                           _format=self,
                           _bzrdir=a_bzrdir,
                           _control_files=control_files)


class DirStateRevisionTree(Tree):
    """A revision tree pulling the inventory from a dirstate."""

    def __init__(self, dirstate, revision_id, repository):
        self._dirstate = dirstate
        self._revision_id = revision_id
        self._repository = repository
        self._inventory = None
        self._locked = False

    def _comparison_data(self, entry, path):
        """See Tree._comparison_data."""
        if entry is None:
            return None, False, None
        # trust the entry as RevisionTree does, but this may not be
        # sensible: the entry might not have come from us?
        return entry.kind, entry.executable, None

    def _file_size(self, entry, stat_value):
        return entry.text_size

    def get_file_sha1(self, file_id, path=None, stat_value=None):
        # TODO: if path is present, fast-path on that, as inventory
        # might not be present
        ie = self.inventory[file_id]
        if ie.kind == "file":
            return ie.text_sha1
        return None

    def get_file_size(self, file_id):
        return self.inventory[file_id].text_size

    def _get_inventory(self):
        if self._inventory is not None:
            return self._inventory
        self._generate_inventory()
        return self._inventory

    inventory = property(_get_inventory,
                         doc="Inventory of this Tree")

    def _generate_inventory(self):
        """Create and set self.inventory from the dirstate object.
        
        This is relatively expensive: we have to walk the entire dirstate.
        Ideally we would not, and instead would """
        assert self._locked, 'cannot generate inventory of an unlocked '\
            'dirstate revision tree'
        assert self._revision_id in self._dirstate.get_parent_ids(), \
            'parent %s has disappeared from %s' % (
            self._revision_id, self._dirstate.get_parent_ids())
        parent_index = self._dirstate.get_parent_ids().index(self._revision_id)
        rows = self._dirstate._iter_rows()
        root_row = rows.next()
        inv = Inventory(root_id=root_row[0][3].decode('utf8'),
            revision_id=self._revision_id)
        for line in rows:
            revid, kind, dirname, name, size, executable, sha1 = line[1][parent_index]
            if not revid:
                # not in this revision tree.
                continue
            parent_id = inv[inv.path2id(dirname.decode('utf8'))].file_id
            file_id = line[0][3].decode('utf8')
            entry = make_entry(kind, name.decode('utf8'), parent_id, file_id)
            entry.revision = revid.decode('utf8')
            if kind == 'file':
                entry.executable = executable
                entry.text_size = size
                entry.text_sha1 = sha1
            inv.add(entry)
        self._inventory = inv

    def get_parent_ids(self):
        """The parents of a tree in the dirstate are not cached."""
        return self._repository.get_revision(self._revision_id).parent_ids

    def lock_read(self):
        """Lock the tree for a set of operations."""
        self._locked = True

    def unlock(self):
        """Unlock, freeing any cache memory used during the lock."""
        # outside of a lock, the inventory is suspect: release it.
        self._inventory = None
        self._locked = False
