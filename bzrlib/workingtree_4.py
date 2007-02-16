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

from cStringIO import StringIO
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
from bzrlib.inventory import InventoryEntry, Inventory, ROOT_ID, entry_factory
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
from bzrlib.workingtree import WorkingTree, WorkingTree3, WorkingTreeFormat3


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
            # deliberately add the file with no cached stat or sha1
            # - on the first access it will be gathered, and we can
            # always change this once tests are all passing.
            state.add(f, file_id, kind, None, '')
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

    def filter_unversioned_files(self, paths):
        """Filter out paths that are not versioned.

        :return: set of paths.
        """
        # TODO: make a generic multi-bisect routine roughly that should list
        # the paths, then process one half at a time recursively, and feed the
        # results of each bisect in further still
        paths = sorted(paths)
        result = set()
        state = self.current_dirstate()
        # TODO we want a paths_to_dirblocks helper I think
        for path in paths:
            dirname, basename = os.path.split(path.encode('utf8'))
            _, _, _, path_is_versioned = state._get_block_row_index(
                dirname, basename)
            if path_is_versioned:
                result.add(path)
        return result

    def flush(self):
        """Write all cached data to disk."""
        if self._control_files._lock_mode != 'w':
            raise errors.NotWriteLocked(self)
        self.current_dirstate().save()
        self._inventory = None
        self._dirty = False

    def _generate_inventory(self):
        """Create and set self.inventory from the dirstate object.
        
        This is relatively expensive: we have to walk the entire dirstate.
        Ideally we would not, and can deprecate this function.
        """
        #: uncomment to trap on inventory requests.
        # import pdb;pdb.set_trace()
        state = self.current_dirstate()
        state._read_dirblocks_if_needed()
        rows = state._iter_rows()
        current_row = state._root_row
        current_id = current_row[0][3].decode('utf8')
        inv = Inventory(root_id=current_id)
        # we could do this straight out of the dirstate; it might be fast
        # and should be profiled - RBC 20070216
        parent_ids = {'' : inv.root.file_id}
        for block in state._dirblocks:
            # block of unversioned files, skip.
            if block[0] == '/':
                continue
            dirname = block[0]
            parent_id = parent_ids[block[0]]
            for line in block[1]:
                _, name, kind, fileid_utf8, size, stat, link_or_sha1 = line[0]
                file_id = fileid_utf8.decode('utf8')
                entry = entry_factory[kind](file_id, name.decode('utf8'), parent_id)
                if kind == 'file':
                    #entry.executable = executable
                    #entry.text_size = size
                    #entry.text_sha1 = sha1
                    pass
                elif kind == 'directory':
                    parent_ids[(dirname + '/' + name).strip('/')] = file_id
                inv.add(entry)
        self._inventory = inv

    def get_file_sha1(self, file_id, path=None, stat_value=None):
        #if not path:
        #    path = self.inventory.id2path(file_id)
        #    # now lookup row by path
        row, parents = self._get_row(file_id=file_id, path=path)
        assert row is not None, 'what error should this raise'
        # TODO:
        # if row stat is valid, use cached sha1, else, get a new sha1.
        if path is None:
            path = (row[0] + '/' + row[1]).strip('/').decode('utf8')
        return self._hashcache.get_sha1(path, stat_value)

    def _get_inventory(self):
        """Get the inventory for the tree. This is only valid within a lock."""
        if self._inventory is not None:
            return self._inventory
        self._generate_inventory()
        return self._inventory

    inventory = property(_get_inventory,
                         doc="Inventory of this Tree")

    @needs_read_lock
    def get_parent_ids(self):
        """See Tree.get_parent_ids.
        
        This implementation requests the ids list from the dirstate file.
        """
        return self.current_dirstate().get_parent_ids()

    @needs_read_lock
    def get_root_id(self):
        """Return the id of this trees root"""
        return self.current_dirstate()._iter_rows().next()[0][3].decode('utf8')

    def _get_row(self, file_id=None, path=None):
        """Get the dirstate row for file_id or path.

        If either file_id or path is supplied, it is used as the key to lookup.
        If both are supplied, the fastest lookup is used, and an error is
        raised if they do not both point at the same row.
        
        :param file_id: An optional unicode file_id to be looked up.
        :param path: An optional unicode path to be looked up.
        :return: The dirstate row tuple for path/file_id, or (None, None)
        """
        if file_id is None and path is None:
            raise errors.BzrError('must supply file_id or path')
        state = self.current_dirstate()
        state._read_dirblocks_if_needed()
        if file_id is not None:
            fileid_utf8 = file_id.encode('utf8')
        if path is not None:
            # path lookups are faster
            row = state._get_row(path)
            if file_id:
                if row[0][3] != fileid_utf8:
                    raise BzrError('integrity error ? : mismatching file_id and path')
            return row
        else:
            for row in state._iter_rows():
                if row[0][3] == fileid_utf8:
                    return row
            return None, None

    def has_id(self, file_id):
        state = self.current_dirstate()
        fileid_utf8 = file_id.encode('utf8')
        row, parents = self._get_row(file_id)
        if row is None:
            return False
        return osutils.lexists(pathjoin(
                    self.basedir, row[0].decode('utf8'), row[1].decode('utf8')))

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

    @needs_tree_write_lock
    def move(self, from_paths, to_dir=None, after=False, **kwargs):
        """See WorkingTree.move()."""
        if not from_paths:
            return ()

        state = self.current_dirstate()

        # check for deprecated use of signature
        if to_dir is None:
            to_dir = kwargs.get('to_name', None)
            if to_dir is None:
                raise TypeError('You must supply a target directory')
            else:
                symbol_versioning.warn('The parameter to_name was deprecated'
                                       ' in version 0.13. Use to_dir instead',
                                       DeprecationWarning)

        assert not isinstance(from_paths, basestring)
        to_dir_utf8 = to_dir.encode('utf8')
        to_row_dirname, to_basename = os.path.split(to_dir_utf8)
        # check destination directory
        # get the details for it
        to_row_block_index, to_row_row_index, dir_present, row_present = \
            state._get_block_row_index(to_row_dirname, to_basename)
        if not row_present:
            raise errors.BzrMoveFailedError('', to_dir,
                errors.NotInWorkingDirectory(to_dir))
        to_row = state._dirblocks[to_row_block_index][1][to_row_row_index][0]
        # get a handle on the block itself.
        to_block_index = state._ensure_block(
            to_row_block_index, to_row_row_index, to_dir_utf8)
        to_block = state._dirblocks[to_block_index]
        to_abs = self.abspath(to_dir)
        if not isdir(to_abs):
            raise errors.BzrMoveFailedError('',to_dir,
                errors.NotADirectory(to_abs))

        if to_row[2] != 'directory':
            raise errors.BzrMoveFailedError('',to_dir,
                errors.NotADirectory(to_abs))

        if self._inventory is not None:
            update_inventory = True
            inv = self.inventory
            to_dir_ie = inv[to_dir_id]
            to_dir_id = to_row[3].decode('utf8')
        else:
            update_inventory = False

        # create rename entries and tuples
        for from_rel in from_paths:
            # from_rel is 'pathinroot/foo/bar'
            from_dirname, from_tail = os.path.split(from_rel)
            from_dirname = from_dirname.encode('utf8')
            from_row = self._get_row(path=from_rel)
            if from_row == (None, None):
                raise errors.BzrMoveFailedError(from_rel,to_dir,
                    errors.NotVersionedError(path=str(from_rel)))

            from_id = from_row[0][3].decode('utf8')
            to_rel = pathjoin(to_dir, from_tail)
            item_to_row = self._get_row(path=to_rel)
            if item_to_row != (None, None):
                raise errors.BzrMoveFailedError(from_rel, to_rel,
                    "Target is already versioned.")

            if from_rel == to_rel:
                raise errors.BzrMoveFailedError(from_rel, to_rel,
                    "Source and target are identical.")

            from_missing = not self.has_filename(from_rel)
            to_missing = not self.has_filename(to_rel)
            if after:
                move_file = False
            else:
                move_file = True
            if to_missing:
                if not move_file:
                    raise errors.BzrMoveFailedError(from_rel, to_rel,
                        errors.NoSuchFile(path=to_rel,
                        extra="New file has not been created yet"))
                elif from_missing:
                    # neither path exists
                    raise errors.BzrRenameFailedError(from_rel, to_rel,
                        errors.PathsDoNotExist(paths=(from_rel, to_rel)))
            else:
                if from_missing: # implicitly just update our path mapping
                    move_file = False
                else:
                    raise errors.RenameFailedFilesExist(from_rel, to_rel,
                        extra="(Use --after to update the Bazaar id)")

            rollbacks = []
            def rollback_rename():
                """A single rename has failed, roll it back."""
                error = None
                for rollback in reversed(rollbacks):
                    try:
                        rollback()
                    except e:
                        error = e
                if error:
                    raise error

            # perform the disk move first - its the most likely failure point.
            from_rel_abs = self.abspath(from_rel)
            to_rel_abs = self.abspath(to_rel)
            try:
                osutils.rename(from_rel_abs, to_rel_abs)
            except OSError, e:
                raise errors.BzrMoveFailedError(from_rel, to_rel, e[1])
            rollbacks.append(lambda: osutils.rename(to_rel_abs, from_rel_abs))
            try:
                # perform the rename in the inventory next if needed: its easy
                # to rollback
                if update_inventory:
                    # rename the entry
                    from_entry = inv[from_id]
                    current_parent = from_entry.parent_id
                    inv.rename(from_id, to_dir_id, from_tail)
                    rollbacks.append(
                        lambda: inv.rename(from_id, current_parent, from_tail))
                # finally do the rename in the dirstate, which is a little
                # tricky to rollback, but least likely to need it.
                basename = from_tail.encode('utf8')
                old_block_index, old_row_index, dir_present, file_present = \
                    state._get_block_row_index(from_dirname, basename)
                old_block = state._dirblocks[old_block_index][1]
                # remove the old row
                old_row = old_block.pop(old_row_index)
                rollbacks.append(lambda:old_block.insert(old_row_index, old_row))
                # create new row in current block
                new_row = ((to_block[0],) + old_row[0][1:], old_row[1])
                insert_position = bisect_left(to_block[1], new_row)
                to_block[1].insert(insert_position, new_row)
                rollbacks.append(lambda:to_block[1].pop(insert_position))
                if new_row[0][2] == 'directory':
                    import pdb;pdb.set_trace()
                    # if a directory, rename all the contents of child blocks
                    # adding rollbacks as each is inserted to remove them and
                    # restore the original
                    # TODO: large scale slice assignment.
                    # setup new list
                    # save old list region
                    # move up or down the old region
                    # add rollback to move the region back
                    # assign new list to new region
                    # done
            except:
                rollback_rename()
                raise
            state._dirblock_state = dirstate.DirState.IN_MEMORY_MODIFIED
            self._dirty = True

        return #rename_tuples

    def _new_tree(self):
        """Initialize the state in this tree to be a new tree."""
        self._dirty = True

    @needs_read_lock
    def path2id(self, path):
        """Return the id for path in this tree."""
        state = self.current_dirstate()
        row = self._get_row(path=path)
        if row == (None, None):
            return None
        return row[0][3].decode('utf8')

    def read_working_inventory(self):
        """Read the working inventory.
        
        This is a meaningless operation for dirstate, but we obey it anyhow.
        """
        return self.inventory

    @needs_read_lock
    def revision_tree(self, revision_id):
        """See Tree.revision_tree.

        WorkingTree4 supplies revision_trees for any basis tree.
        """
        dirstate = self.current_dirstate()
        parent_ids = dirstate.get_parent_ids()
        if revision_id not in parent_ids:
            raise errors.NoSuchRevisionInTree(self, revision_id)
        if revision_id in dirstate.get_ghosts():
            raise errors.NoSuchRevisionInTree(self, revision_id)
        return DirStateRevisionTree(dirstate, revision_id,
            self.branch.repository)

    @needs_tree_write_lock
    def set_last_revision(self, new_revision):
        """Change the last revision in the working tree."""
        parents = self.get_parent_ids()
        if new_revision in (NULL_REVISION, None):
            assert len(parents) < 2, (
                "setting the last parent to none with a pending merge is "
                "unsupported.")
            self.set_parent_ids([])
        else:
            self.set_parent_ids([new_revision] + parents[1:],
                allow_leftmost_as_ghost=True)

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
                raise errors.GhostRevisionUnusableHere(parents_list[0][0])
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
        state = self.current_dirstate()
        state.set_path_id('', file_id)
        self._dirty = state._dirblock_state == dirstate.DirState.IN_MEMORY_MODIFIED

    def unlock(self):
        """Unlock in format 4 trees needs to write the entire dirstate."""
        if self._control_files._lock_count == 1:
            self._write_hashcache_if_dirty()
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
        deleted_rows = []
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
                    if row_parents:
                        deleted_rows.append((row[3], row_parents))
                    ids_to_unversion.remove(row[3])
        if ids_to_unversion:
            raise errors.NoSuchId(self, iter(ids_to_unversion).next())
        state._dirblocks = new_blocks
        for fileid_utf8, parents in deleted_rows:
            state.add_deleted(fileid_utf8, parents)
        state._dirblock_state = dirstate.DirState.IN_MEMORY_MODIFIED
        self._dirty = True
        # have to change the legacy inventory too.
        if self._inventory is not None:
            for file_id in file_ids:
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
            basis = wt.basis_tree()
            basis.lock_read()
            transform.build_tree(basis, wt)
            basis.unlock()
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
        self._locked = 0

    def annotate_iter(self, file_id):
        """See Tree.annotate_iter"""
        w = self._repository.weave_store.get_weave(file_id,
                           self._repository.get_transaction())
        return w.annotate_iter(self.inventory[file_id].revision)

    def _comparison_data(self, entry, path):
        """See Tree._comparison_data."""
        if entry is None:
            return None, False, None
        # trust the entry as RevisionTree does, but this may not be
        # sensible: the entry might not have come from us?
        return entry.kind, entry.executable, None

    def _file_size(self, entry, stat_value):
        return entry.text_size

    def filter_unversioned_files(self, paths):
        """Filter out paths that are not versioned.

        :return: set of paths.
        """
        pred = self.has_filename
        return set((p for p in paths if not pred(p)))

    def _generate_inventory(self):
        """Create and set self.inventory from the dirstate object.
        
        This is relatively expensive: we have to walk the entire dirstate.
        Ideally we would not, and instead would """
        assert self._locked, 'cannot generate inventory of an unlocked '\
            'dirstate revision tree'
        assert self._revision_id in self._dirstate.get_parent_ids(), \
            'parent %s has disappeared from %s' % (
            self._revision_id, self._dirstate.get_parent_ids())
        # separate call for profiling - makes it clear where the costs are.
        self._dirstate._read_dirblocks_if_needed()
        parent_index = self._dirstate.get_parent_ids().index(self._revision_id)
        # because the parent tree may look dramatically different to the current
        # tree, we grab and sort the tree content  all at once, then
        # deserialise into an inventory.
        rows = self._dirstate._iter_rows()
        parent_rows = []
        for row in rows:
            parent_rows.append((row[1][parent_index], row[0][3].decode('utf8')))
        parent_rows = iter(sorted(parent_rows, key=lambda x:x[0][2:3]))
        root_row = parent_rows.next()
        inv = Inventory(root_id=root_row[1], revision_id=self._revision_id)
        inv.root.revision = root_row[1][parent_index][0].decode('utf8')
        # we could do this straight out of the dirstate; it might be fast
        # and should be profiled - RBC 20070216
        parent_ids = {'' : inv.root.file_id}
        for line in parent_rows:
            revid, kind, dirname, name, size, executable, sha1 = line[0]
            if not revid:
                # not in this revision tree.
                continue
            parent_id = parent_ids[dirname]
            file_id = line[1]
            entry = entry_factory[kind](file_id, name.decode('utf8'), parent_id)
            entry.revision = revid.decode('utf8')
            if kind == 'file':
                entry.executable = executable
                entry.text_size = size
                entry.text_sha1 = sha1
            elif kind == 'directory':
                parent_ids[(dirname + '/' + name).strip('/')] = file_id
            inv.add(entry)
        self._inventory = inv

    def get_file_sha1(self, file_id, path=None, stat_value=None):
        # TODO: if path is present, fast-path on that, as inventory
        # might not be present
        ie = self.inventory[file_id]
        if ie.kind == "file":
            return ie.text_sha1
        return None

    def get_file(self, file_id):
        return StringIO(self.get_file_text(file_id))

    def get_file_lines(self, file_id):
        ie = self.inventory[file_id]
        return self._repository.weave_store.get_weave(file_id,
                self._repository.get_transaction()).get_lines(ie.revision)

    def get_file_size(self, file_id):
        return self.inventory[file_id].text_size

    def get_file_text(self, file_id):
        return ''.join(self.get_file_lines(file_id))

    def get_revision_id(self):
        """Return the revision id for this tree."""
        return self._revision_id

    def _get_inventory(self):
        if self._inventory is not None:
            return self._inventory
        self._generate_inventory()
        return self._inventory

    inventory = property(_get_inventory,
                         doc="Inventory of this Tree")

    def get_parent_ids(self):
        """The parents of a tree in the dirstate are not cached."""
        return self._repository.get_revision(self._revision_id).parent_ids

    def has_filename(self, filename):
        return bool(self.inventory.path2id(filename))

    def kind(self, file_id):
        return self.inventory[file_id].kind

    def is_executable(self, file_id, path=None):
        ie = self.inventory[file_id]
        if ie.kind != "file":
            return None 
        return ie.executable

    def list_files(self, include_root=False):
        # We use a standard implementation, because DirStateRevisionTree is
        # dealing with one of the parents of the current state
        inv = self._get_inventory()
        entries = inv.iter_entries()
        if self.inventory.root is not None and not include_root:
            entries.next()
        for path, entry in entries:
            yield path, 'V', entry.kind, entry.file_id, entry
        
    def lock_read(self):
        """Lock the tree for a set of operations."""
        if not self._locked:
            self._repository.lock_read()
        self._locked += 1

    def path2id(self, path):
        """Return the id for path in this tree."""
        # TODO: if there is no inventory, do an optimistic lookup in the
        # dirstate by the path; commonly this will work.
        return self.inventory.path2id(path)

    def unlock(self):
        """Unlock, freeing any cache memory used during the lock."""
        # outside of a lock, the inventory is suspect: release it.
        self._locked -=1
        if not self._locked:
            self._inventory = None
            self._locked = False
            self._repository.unlock()

    def walkdirs(self, prefix=""):
        # TODO: jam 20070215 This is the cheap way by cheating and using the
        #       RevisionTree implementation.
        #       This should be cleaned up to use the much faster Dirstate code
        #       This is a little tricky, though, because the dirstate is
        #       indexed by current path, not by parent path.
        #       So for now, we just build up the parent inventory, and extract
        #       it the same way RevisionTree does.
        _directory = 'directory'
        inv = self._get_inventory()
        top_id = inv.path2id(prefix)
        if top_id is None:
            pending = []
        else:
            pending = [(prefix, top_id)]
        while pending:
            dirblock = []
            relpath, file_id = pending.pop()
            # 0 - relpath, 1- file-id
            if relpath:
                relroot = relpath + '/'
            else:
                relroot = ""
            # FIXME: stash the node in pending
            entry = inv[file_id]
            for name, child in entry.sorted_children():
                toppath = relroot + name
                dirblock.append((toppath, name, child.kind, None,
                    child.file_id, child.kind
                    ))
            yield (relpath, entry.file_id), dirblock
            # push the user specified dirs from dirblock
            for dir in reversed(dirblock):
                if dir[2] == _directory:
                    pending.append((dir[0], dir[4]))
