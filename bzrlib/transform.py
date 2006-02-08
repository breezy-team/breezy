# Copyright (C) 2006 Canonical Ltd

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

import os
import errno
from tempfile import mkdtemp
from shutil import rmtree
from stat import S_ISREG

from bzrlib import BZRDIR
from bzrlib.errors import (DuplicateKey, MalformedTransform, NoSuchFile,
                           ReusingTransform, NotVersionedError, CantMoveRoot,
                           WorkingTreeNotRevision)
from bzrlib.inventory import InventoryEntry
from bzrlib.osutils import file_kind, supports_executable, pathjoin
from bzrlib.merge3 import Merge3
from bzrlib.trace import mutter

ROOT_PARENT = "root-parent"

def unique_add(map, key, value):
    if key in map:
        raise DuplicateKey(key=key)
    map[key] = value

class TreeTransform(object):
    """Represent a tree transformation."""
    def __init__(self, tree):
        """Note: a write lock is taken on the tree.
        
        Use TreeTransform.finalize() to release the lock
        """
        object.__init__(self)
        self._tree = tree
        self._tree.lock_write()
        self._id_number = 0
        self._new_name = {}
        self._new_parent = {}
        self._new_contents = {}
        self._removed_contents = set()
        self._new_executability = {}
        self._new_id = {}
        self._r_new_id = {}
        self._removed_id = set()
        self._tree_path_ids = {}
        self._tree_id_paths = {}
        self._new_root = self.get_id_tree(tree.get_root_id())
        self.__done = False
        # XXX use the WorkingTree LockableFiles, when available
        control_files = self._tree.branch.control_files
        self._limbodir = control_files.controlfilename('limbo')
        os.mkdir(self._limbodir)

    def finalize(self):
        """Release the working tree lock, if held."""
        if self._tree is None:
            return
        for trans_id, kind in self._new_contents.iteritems():
            path = self._limbo_name(trans_id)
            if kind == "directory":
                os.rmdir(path)
            else:
                os.unlink(path)
        os.rmdir(self._limbodir)
        self._tree.unlock()
        self._tree = None

    def _assign_id(self):
        """Produce a new tranform id"""
        new_id = "new-%s" % self._id_number
        self._id_number +=1
        return new_id

    def create_path(self, name, parent):
        """Assign a transaction id to a new path"""
        trans_id = self._assign_id()
        unique_add(self._new_name, trans_id, name)
        unique_add(self._new_parent, trans_id, parent)
        return trans_id

    def adjust_path(self, name, parent, trans_id):
        """Change the path that is assigned to a transaction id."""
        if trans_id == self._new_root:
            raise CantMoveRoot
        self._new_name[trans_id] = name
        self._new_parent[trans_id] = parent

    def adjust_root_path(self, name, parent):
        """Emulate moving the root by moving all children, instead.
        
        We do this by undoing the association of root's transaction id with the
        current tree.  This allows us to create a new directory with that
        transaction id.  We unversion the root directory and version the 
        physically new directory, and hope someone versions the tree root
        later.
        """
        old_root = self._new_root
        old_root_file_id = self.final_file_id(old_root)
        # force moving all children of root
        for child_id in self.iter_tree_children(old_root):
            if child_id != parent:
                self.adjust_path(self.final_name(child_id), 
                                 self.final_parent(child_id), child_id)
            file_id = self.final_file_id(child_id)
            if file_id is not None:
                self.unversion_file(child_id)
            self.version_file(file_id, child_id)
        
        # the physical root needs a new transaction id
        self._tree_path_ids.pop("")
        self._tree_id_paths.pop(old_root)
        self._new_root = self.get_id_tree(self._tree.get_root_id())
        if parent == old_root:
            parent = self._new_root
        self.adjust_path(name, parent, old_root)
        self.create_directory(old_root)
        self.version_file(old_root_file_id, old_root)
        self.unversion_file(self._new_root)

    def get_id_tree(self, inventory_id):
        """Determine the transaction id of a working tree file.
        
        This reflects only files that already exist, not ones that will be
        added by transactions.
        """
        return self.get_tree_path_id(self._tree.id2path(inventory_id))

    def get_trans_id(self, file_id):
        """\
        Determine or set the transaction id associated with a file ID.
        A new id is only created for file_ids that were never present.  If
        a transaction has been unversioned, it is deliberately still returned.
        (this will likely lead to an unversioned parent conflict.)
        """
        if file_id in self._r_new_id and self._r_new_id[file_id] is not None:
            return self._r_new_id[file_id]
        elif file_id in self._tree.inventory:
            return self.get_id_tree(file_id)
        else:
            trans_id = self._assign_id()
            self.version_file(file_id, trans_id)
            return trans_id

    def canonical_path(self, path):
        """Get the canonical tree-relative path"""
        # don't follow final symlinks
        dirname, basename = os.path.split(self._tree.abspath(path))
        dirname = os.path.realpath(dirname)
        return self._tree.relpath(os.path.join(dirname, basename))

    def get_tree_path_id(self, path):
        """Determine (and maybe set) the transaction ID for a tree path."""
        path = self.canonical_path(path)
        if path not in self._tree_path_ids:
            self._tree_path_ids[path] = self._assign_id()
            self._tree_id_paths[self._tree_path_ids[path]] = path
        return self._tree_path_ids[path]

    def get_tree_parent(self, trans_id):
        """Determine id of the parent in the tree."""
        path = self._tree_id_paths[trans_id]
        if path == "":
            return ROOT_PARENT
        return self.get_tree_path_id(os.path.dirname(path))

    def create_file(self, contents, trans_id, mode_id=None):
        """Schedule creation of a new file.

        See also new_file.
        
        Contents is an iterator of strings, all of which will be written
        to the target destination.

        New file takes the permissions of any existing file with that id,
        unless mode_id is specified.
        """
        f = file(self._limbo_name(trans_id), 'wb')
        unique_add(self._new_contents, trans_id, 'file')
        for segment in contents:
            f.write(segment)
        f.close()
        self._set_mode(trans_id, mode_id, S_ISREG)

    def _set_mode(self, trans_id, mode_id, typefunc):
        if mode_id is None:
            mode_id = trans_id
        try:
            old_path = self._tree_id_paths[mode_id]
        except KeyError:
            return
        try:
            mode = os.stat(old_path).st_mode
        except OSError, e:
            if e.errno == errno.ENOENT:
                return
            else:
                raise
        if typefunc(mode):
            os.chmod(self._limbo_name(trans_id), mode)

    def create_directory(self, trans_id):
        """Schedule creation of a new directory.
        
        See also new_directory.
        """
        os.mkdir(self._limbo_name(trans_id))
        unique_add(self._new_contents, trans_id, 'directory')

    def create_symlink(self, target, trans_id):
        """Schedule creation of a new symbolic link.

        target is a bytestring.
        See also new_symlink.
        """
        os.symlink(target, self._limbo_name(trans_id))
        unique_add(self._new_contents, trans_id, 'symlink')

    def delete_contents(self, trans_id):
        """Schedule the contents of a path entry for deletion"""
        self._removed_contents.add(trans_id)

    def cancel_deletion(self, trans_id):
        """Cancel a scheduled deletion"""
        self._removed_contents.remove(trans_id)

    def unversion_file(self, trans_id):
        """Schedule a path entry to become unversioned"""
        self._removed_id.add(trans_id)

    def delete_versioned(self, trans_id):
        """Delete and unversion a versioned file"""
        self.delete_contents(trans_id)
        self.unversion_file(trans_id)

    def set_executability(self, executability, trans_id):
        """Schedule setting of the 'execute' bit"""
        if executability is None:
            del self._new_executability[trans_id]
        else:
            unique_add(self._new_executability, trans_id, executability)

    def version_file(self, file_id, trans_id):
        """Schedule a file to become versioned."""
        unique_add(self._new_id, trans_id, file_id)
        unique_add(self._r_new_id, file_id, trans_id)

    def cancel_versioning(self, trans_id):
        """Undo a previous versioning of a file"""
        file_id = self._new_id[trans_id]
        del self._new_id[trans_id]
        del self._r_new_id[file_id]

    def new_paths(self):
        """Determine the paths of all new and changed files"""
        new_ids = set()
        fp = FinalPaths(self._new_root, self)
        for id_set in (self._new_name, self._new_parent, self._new_contents,
                       self._new_id, self._new_executability):
            new_ids.update(id_set)
        new_paths = [(fp.get_path(t), t) for t in new_ids]
        new_paths.sort()
        return new_paths

    def tree_kind(self, trans_id):
        """Determine the file kind in the working tree.

        Raises NoSuchFile if the file does not exist
        """
        path = self._tree_id_paths.get(trans_id)
        if path is None:
            raise NoSuchFile(None)
        try:
            return file_kind(self._tree.abspath(path))
        except OSError, e:
            if e.errno != errno.ENOENT:
                raise
            else:
                raise NoSuchFile(path)

    def final_kind(self, trans_id):
        """\
        Determine the final file kind, after any changes applied.
        
        Raises NoSuchFile if the file does not exist/has no contents.
        (It is conceivable that a path would be created without the
        corresponding contents insertion command)
        """
        if trans_id in self._new_contents:
            return self._new_contents[trans_id]
        elif trans_id in self._removed_contents:
            raise NoSuchFile(None)
        else:
            return self.tree_kind(trans_id)

    def get_tree_file_id(self, trans_id):
        """Determine the file id associated with the trans_id in the tree"""
        try:
            path = self._tree_id_paths[trans_id]
        except KeyError:
            # the file is a new, unversioned file, or invalid trans_id
            return None
        # the file is old; the old id is still valid
        if self._new_root == trans_id:
            return self._tree.inventory.root.file_id
        return self._tree.path2id(path)

    def final_file_id(self, trans_id):
        """\
        Determine the file id after any changes are applied, or None.
        
        None indicates that the file will not be versioned after changes are
        applied.
        """
        try:
            # there is a new id for this file
            return self._new_id[trans_id]
        except KeyError:
            if trans_id in self._removed_id:
                return None
        return self.get_tree_file_id(trans_id)

    def final_parent(self, trans_id):
        """\
        Determine the parent file_id, after any changes are applied.

        ROOT_PARENT is returned for the tree root.
        """
        try:
            return self._new_parent[trans_id]
        except KeyError:
            return self.get_tree_parent(trans_id)

    def final_name(self, trans_id):
        """Determine the final filename, after all changes are applied."""
        try:
            return self._new_name[trans_id]
        except KeyError:
            return os.path.basename(self._tree_id_paths[trans_id])

    def _by_parent(self):
        """Return a map of parent: children for known parents.
        
        Only new paths and parents of tree files with assigned ids are used.
        """
        by_parent = {}
        items = list(self._new_parent.iteritems())
        items.extend((t, self.final_parent(t)) for t in 
                      self._tree_id_paths.keys())
        for trans_id, parent_id in items:
            if parent_id not in by_parent:
                by_parent[parent_id] = set()
            by_parent[parent_id].add(trans_id)
        return by_parent

    def path_changed(self, trans_id):
        return trans_id in self._new_name or trans_id in self._new_parent

    def find_conflicts(self):
        """Find any violations of inventory or filesystem invariants"""
        if self.__done is True:
            raise ReusingTransform()
        conflicts = []
        # ensure all children of all existent parents are known
        # all children of non-existent parents are known, by definition.
        self._add_tree_children()
        by_parent = self._by_parent()
        conflicts.extend(self._unversioned_parents(by_parent))
        conflicts.extend(self._parent_loops())
        conflicts.extend(self._duplicate_entries(by_parent))
        conflicts.extend(self._duplicate_ids())
        conflicts.extend(self._parent_type_conflicts(by_parent))
        conflicts.extend(self._improper_versioning())
        conflicts.extend(self._executability_conflicts())
        return conflicts

    def _add_tree_children(self):
        """\
        Add all the children of all active parents to the known paths.

        Active parents are those which gain children, and those which are
        removed.  This is a necessary first step in detecting conflicts.
        """
        parents = self._by_parent().keys()
        parents.extend([t for t in self._removed_contents if 
                        self.tree_kind(t) == 'directory'])
        for trans_id in self._removed_id:
            file_id = self.get_tree_file_id(trans_id)
            if self._tree.inventory[file_id].kind in ('directory', 
                                                      'root_directory'):
                parents.append(trans_id)

        for parent_id in parents:
            # ensure that all children are registered with the transaction
            list(self.iter_tree_children(parent_id))

    def iter_tree_children(self, parent_id):
        """Iterate through the entry's tree children, if any"""
        try:
            path = self._tree_id_paths[parent_id]
        except KeyError:
            return
        try:
            children = os.listdir(self._tree.abspath(path))
        except OSError, e:
            if e.errno != errno.ENOENT and e.errno != errno.ESRCH:
                raise
            return
            
        for child in children:
            childpath = joinpath(path, child)
            if childpath == BZRDIR:
                continue
            yield self.get_tree_path_id(childpath)

    def _parent_loops(self):
        """No entry should be its own ancestor"""
        conflicts = []
        for trans_id in self._new_parent:
            seen = set()
            parent_id = trans_id
            while parent_id is not ROOT_PARENT:
                seen.add(parent_id)
                parent_id = self.final_parent(parent_id)
                if parent_id == trans_id:
                    conflicts.append(('parent loop', trans_id))
                if parent_id in seen:
                    break
        return conflicts

    def _unversioned_parents(self, by_parent):
        """If parent directories are versioned, children must be versioned."""
        conflicts = []
        for parent_id, children in by_parent.iteritems():
            if parent_id is ROOT_PARENT:
                continue
            if self.final_file_id(parent_id) is not None:
                continue
            for child_id in children:
                if self.final_file_id(child_id) is not None:
                    conflicts.append(('unversioned parent', parent_id))
                    break;
        return conflicts

    def _improper_versioning(self):
        """\
        Cannot version a file with no contents, or a bad type.
        
        However, existing entries with no contents are okay.
        """
        conflicts = []
        for trans_id in self._new_id.iterkeys():
            try:
                kind = self.final_kind(trans_id)
            except NoSuchFile:
                conflicts.append(('versioning no contents', trans_id))
                continue
            if not InventoryEntry.versionable_kind(kind):
                conflicts.append(('versioning bad kind', trans_id, kind))
        return conflicts

    def _executability_conflicts(self):
        """Check for bad executability changes.
        
        Only versioned files may have their executability set, because
        1. only versioned entries can have executability under windows
        2. only files can be executable.  (The execute bit on a directory
           does not indicate searchability)
        """
        conflicts = []
        for trans_id in self._new_executability:
            if self.final_file_id(trans_id) is None:
                conflicts.append(('unversioned executability', trans_id))
            else:
                try:
                    non_file = self.final_kind(trans_id) != "file"
                except NoSuchFile:
                    non_file = True
                if non_file is True:
                    conflicts.append(('non-file executability', trans_id))
        return conflicts

    def _duplicate_entries(self, by_parent):
        """No directory may have two entries with the same name."""
        conflicts = []
        for children in by_parent.itervalues():
            name_ids = [(self.final_name(t), t) for t in children]
            name_ids.sort()
            last_name = None
            last_trans_id = None
            for name, trans_id in name_ids:
                if name == last_name:
                    conflicts.append(('duplicate', last_trans_id, trans_id,
                    name))
                last_name = name
                last_trans_id = trans_id
        return conflicts

    def _duplicate_ids(self):
        """Each inventory id may only be used once"""
        conflicts = []
        removed_tree_ids = set((self.get_tree_file_id(trans_id) for trans_id in
                                self._removed_id))
        active_tree_ids = set((f for f in self._tree.inventory if
                               f not in removed_tree_ids))
        for trans_id, file_id in self._new_id.iteritems():
            if file_id in active_tree_ids:
                old_trans_id = self.get_id_tree(file_id)
                conflicts.append(('duplicate id', old_trans_id, trans_id))
        return conflicts

    def _parent_type_conflicts(self, by_parent):
        """parents must have directory 'contents'."""
        conflicts = []
        for parent_id, children in by_parent.iteritems():
            if parent_id is ROOT_PARENT:
                continue
            if not self._any_contents(children):
                continue
            for child in children:
                try:
                    self.final_kind(child)
                except NoSuchFile:
                    continue
            try:
                kind = self.final_kind(parent_id)
            except NoSuchFile:
                kind = None
            if kind is None:
                conflicts.append(('missing parent', parent_id))
            elif kind != "directory":
                conflicts.append(('non-directory parent', parent_id))
        return conflicts

    def _any_contents(self, trans_ids):
        """Return true if any of the trans_ids, will have contents."""
        for trans_id in trans_ids:
            try:
                kind = self.final_kind(trans_id)
            except NoSuchFile:
                continue
            return True
        return False
            
    def apply(self):
        """\
        Apply all changes to the inventory and filesystem.
        
        If filesystem or inventory conflicts are present, MalformedTransform
        will be thrown.
        """
        conflicts = self.find_conflicts()
        if len(conflicts) != 0:
            raise MalformedTransform(conflicts=conflicts)
        limbo_inv = {}
        inv = self._tree.inventory
        self._apply_removals(inv, limbo_inv)
        self._apply_insertions(inv, limbo_inv)
        self._tree._write_inventory(inv)
        self.__done = True
        self.finalize()

    def _limbo_name(self, trans_id):
        """Generate the limbo name of a file"""
        return os.path.join(self._limbodir, trans_id)

    def _apply_removals(self, inv, limbo_inv):
        """Perform tree operations that remove directory/inventory names.
        
        That is, delete files that are to be deleted, and put any files that
        need renaming into limbo.  This must be done in strict child-to-parent
        order.
        """
        tree_paths = list(self._tree_path_ids.iteritems())
        tree_paths.sort(reverse=True)
        for path, trans_id in tree_paths:
            full_path = self._tree.abspath(path)
            if trans_id in self._removed_contents:
                try:
                    os.unlink(full_path)
                except OSError, e:
                # We may be renaming a dangling inventory id
                    if e.errno != errno.EISDIR and e.errno != errno.EACCES:
                        raise
                    os.rmdir(full_path)
            elif trans_id in self._new_name or trans_id in self._new_parent:
                try:
                    os.rename(full_path, self._limbo_name(trans_id))
                except OSError, e:
                    if e.errno != errno.ENOENT:
                        raise
            if trans_id in self._removed_id:
                if trans_id == self._new_root:
                    file_id = self._tree.inventory.root.file_id
                else:
                    file_id = self.get_tree_file_id(trans_id)
                del inv[file_id]
            elif trans_id in self._new_name or trans_id in self._new_parent:
                file_id = self.get_tree_file_id(trans_id)
                if file_id is not None:
                    limbo_inv[trans_id] = inv[file_id]
                    del inv[file_id]

    def _apply_insertions(self, inv, limbo_inv):
        """Perform tree operations that insert directory/inventory names.
        
        That is, create any files that need to be created, and restore from
        limbo any files that needed renaming.  This must be done in strict
        parent-to-child order.
        """
        for path, trans_id in self.new_paths():
            try:
                kind = self._new_contents[trans_id]
            except KeyError:
                kind = contents = None
            if trans_id in self._new_contents or self.path_changed(trans_id):
                full_path = self._tree.abspath(path)
                try:
                    os.rename(self._limbo_name(trans_id), full_path)
                except OSError, e:
                    # We may be renaming a dangling inventory id
                    if e.errno != errno.ENOENT:
                        raise
                if trans_id in self._new_contents:
                    del self._new_contents[trans_id]

            if trans_id in self._new_id:
                if kind is None:
                    kind = file_kind(self._tree.abspath(path))
                try:
                    inv.add_path(path, kind, self._new_id[trans_id])
                except:
                    raise repr((path, kind, self._new_id[trans_id]))
            elif trans_id in self._new_name or trans_id in self._new_parent:
                entry = limbo_inv.get(trans_id)
                if entry is not None:
                    entry.name = self.final_name(trans_id)
                    parent_trans_id = self.final_parent(trans_id)
                    entry.parent_id = self.final_file_id(parent_trans_id)
                    inv.add(entry)

            # requires files and inventory entries to be in place
            if trans_id in self._new_executability:
                self._set_executability(path, inv, trans_id)

    def _set_executability(self, path, inv, trans_id):
        """Set the executability of versioned files """
        file_id = inv.path2id(path)
        new_executability = self._new_executability[trans_id]
        inv[file_id].executable = new_executability
        if supports_executable():
            abspath = self._tree.abspath(path)
            current_mode = os.stat(abspath).st_mode
            if new_executability:
                umask = os.umask(0)
                os.umask(umask)
                to_mode = current_mode | (0100 & ~umask)
                # Enable x-bit for others only if they can read it.
                if current_mode & 0004:
                    to_mode |= 0001 & ~umask
                if current_mode & 0040:
                    to_mode |= 0010 & ~umask
            else:
                to_mode = current_mode & ~0111
            os.chmod(abspath, to_mode)

    def _new_entry(self, name, parent_id, file_id):
        """Helper function to create a new filesystem entry."""
        trans_id = self.create_path(name, parent_id)
        if file_id is not None:
            self.version_file(file_id, trans_id)
        return trans_id

    def new_file(self, name, parent_id, contents, file_id=None, 
                 executable=None):
        """\
        Convenience method to create files.
        
        name is the name of the file to create.
        parent_id is the transaction id of the parent directory of the file.
        contents is an iterator of bytestrings, which will be used to produce
        the file.
        file_id is the inventory ID of the file, if it is to be versioned.
        """
        trans_id = self._new_entry(name, parent_id, file_id)
        self.create_file(contents, trans_id)
        if executable is not None:
            self.set_executability(executable, trans_id)
        return trans_id

    def new_directory(self, name, parent_id, file_id=None):
        """\
        Convenience method to create directories.

        name is the name of the directory to create.
        parent_id is the transaction id of the parent directory of the
        directory.
        file_id is the inventory ID of the directory, if it is to be versioned.
        """
        trans_id = self._new_entry(name, parent_id, file_id)
        self.create_directory(trans_id)
        return trans_id 

    def new_symlink(self, name, parent_id, target, file_id=None):
        """\
        Convenience method to create symbolic link.
        
        name is the name of the symlink to create.
        parent_id is the transaction id of the parent directory of the symlink.
        target is a bytestring of the target of the symlink.
        file_id is the inventory ID of the file, if it is to be versioned.
        """
        trans_id = self._new_entry(name, parent_id, file_id)
        self.create_symlink(target, trans_id)
        return trans_id

def joinpath(parent, child):
    """Join tree-relative paths, handling the tree root specially"""
    if parent is None or parent == "":
        return child
    else:
        return os.path.join(parent, child)

class FinalPaths(object):
    """\
    Make path calculation cheap by memoizing paths.

    The underlying tree must not be manipulated between calls, or else
    the results will likely be incorrect.
    """
    def __init__(self, root, transform):
        object.__init__(self)
        self.root = root
        self._known_paths = {}
        self.transform = transform

    def _determine_path(self, trans_id):
        if trans_id == self.root:
            return ""
        name = self.transform.final_name(trans_id)
        parent_id = self.transform.final_parent(trans_id)
        if parent_id == self.root:
            return name
        else:
            return os.path.join(self.get_path(parent_id), name)

    def get_path(self, trans_id):
        if trans_id not in self._known_paths:
            self._known_paths[trans_id] = self._determine_path(trans_id)
        return self._known_paths[trans_id]

def topology_sorted_ids(tree):
    """Determine the topological order of the ids in a tree"""
    file_ids = list(tree)
    file_ids.sort(key=tree.id2path)
    return file_ids

def build_tree(branch, tree):
    """Create working tree for a branch, using a Transaction."""
    file_trans_id = {}
    wt = branch.working_tree()
    tt = TreeTransform(wt)
    try:
        file_trans_id[wt.get_root_id()] = tt.get_id_tree(wt.get_root_id())
        file_ids = topology_sorted_ids(tree)
        for file_id in file_ids:
            entry = tree.inventory[file_id]
            if entry.parent_id is None:
                continue
            if entry.parent_id not in file_trans_id:
                raise repr(entry.parent_id)
            parent_id = file_trans_id[entry.parent_id]
            file_trans_id[file_id] = new_by_entry(tt, entry, parent_id, tree)
        tt.apply()
    finally:
        tt.finalize()

def new_by_entry(tt, entry, parent_id, tree):
    name = entry.name
    kind = entry.kind
    if kind == 'file':
        contents = tree.get_file(entry.file_id).readlines()
        executable = tree.is_executable(entry.file_id)
        return tt.new_file(name, parent_id, contents, entry.file_id, 
                           executable)
    elif kind == 'directory':
        return tt.new_directory(name, parent_id, entry.file_id)
    elif kind == 'symlink':
        target = entry.get_symlink_target(file_id)
        return tt.new_symlink(name, parent_id, target, file_id)

def create_by_entry(tt, entry, tree, trans_id, lines=None, mode_id=None):
    if entry.kind == "file":
        if lines == None:
            lines = tree.get_file(entry.file_id).readlines()
        tt.create_file(lines, trans_id, mode_id=mode_id)
    elif entry.kind == "symlink":
        tt.create_symlink(tree.get_symlink_target(entry.file_id), trans_id)
    elif entry.kind == "directory":
        tt.create_directory(trans_id)

def create_entry_executability(tt, entry, trans_id):
    if entry.kind == "file":
        tt.set_executability(entry.executable, trans_id)

def find_interesting(working_tree, target_tree, filenames):
    if not filenames:
        interesting_ids = None
    else:
        interesting_ids = set()
        for tree_path in filenames:
            for tree in (working_tree, target_tree):
                not_found = True
                file_id = tree.inventory.path2id(tree_path)
                if file_id is not None:
                    interesting_ids.add(file_id)
                    not_found = False
                if not_found:
                    raise NotVersionedError(path=tree_path)
    return interesting_ids


def change_entry(tt, file_id, working_tree, target_tree, 
                 get_trans_id, backups, trans_id):
    e_trans_id = get_trans_id(file_id)
    entry = target_tree.inventory[file_id]
    has_contents, contents_mod, meta_mod, = _entry_changes(file_id, entry, 
                                                           working_tree)
    if contents_mod:
        mode_id = e_trans_id
        if has_contents:
            if not backups:
                tt.delete_contents(e_trans_id)
            else:
                parent_trans_id = get_trans_id(entry.parent_id)
                tt.adjust_path(entry.name+"~", parent_trans_id, e_trans_id)
                tt.unversion_file(e_trans_id)
                e_trans_id = tt.create_path(entry.name, parent_trans_id)
                tt.version_file(file_id, e_trans_id)
                trans_id[file_id] = e_trans_id
        create_by_entry(tt, entry, target_tree, e_trans_id, mode_id=mode_id)
        create_entry_executability(tt, entry, e_trans_id)

    elif meta_mod:
        tt.set_executability(entry.executable, e_trans_id)
    if tt.final_name(e_trans_id) != entry.name:
        adjust_path  = True
    else:
        parent_id = tt.final_parent(e_trans_id)
        parent_file_id = tt.final_file_id(parent_id)
        if parent_file_id != entry.parent_id:
            adjust_path = True
        else:
            adjust_path = False
    if adjust_path:
        parent_trans_id = get_trans_id(entry.parent_id)
        tt.adjust_path(entry.name, parent_trans_id, e_trans_id)


def _entry_changes(file_id, entry, working_tree):
    """\
    Determine in which ways the inventory entry has changed.

    Returns booleans: has_contents, content_mod, meta_mod
    has_contents means there are currently contents, but they differ
    contents_mod means contents need to be modified
    meta_mod means the metadata needs to be modified
    """
    cur_entry = working_tree.inventory[file_id]
    try:
        working_kind = working_tree.kind(file_id)
        has_contents = True
    except OSError, e:
        if e.errno != errno.ENOENT:
            raise
        has_contents = False
        contents_mod = True
        meta_mod = False
    if has_contents is True:
        real_e_kind = entry.kind
        if real_e_kind == 'root_directory':
            real_e_kind = 'directory'
        if real_e_kind != working_kind:
            contents_mod, meta_mod = True, False
        else:
            cur_entry._read_tree_state(working_tree.id2path(file_id), 
                                       working_tree)
            contents_mod, meta_mod = entry.detect_changes(cur_entry)
    return has_contents, contents_mod, meta_mod


def revert(working_tree, target_tree, filenames, backups=False):
    interesting_ids = find_interesting(working_tree, target_tree, filenames)
    def interesting(file_id):
        return interesting_ids is None or file_id in interesting_ids

    tt = TreeTransform(working_tree)
    try:
        trans_id = {}
        def get_trans_id(file_id):
            try:
                return trans_id[file_id]
            except KeyError:
                return tt.get_id_tree(file_id)

        for file_id in topology_sorted_ids(target_tree):
            if not interesting(file_id):
                continue
            if file_id not in working_tree.inventory:
                entry = target_tree.inventory[file_id]
                parent_id = get_trans_id(entry.parent_id)
                e_trans_id = new_by_entry(tt, entry, parent_id, target_tree)
                trans_id[file_id] = e_trans_id
            else:
                change_entry(tt, file_id, working_tree, target_tree, 
                             get_trans_id, backups, trans_id)
        for file_id in working_tree:
            if not interesting(file_id):
                continue
            if file_id not in target_tree:
                tt.unversion_file(tt.get_id_tree(file_id))
        resolve_conflicts(tt)
        tt.apply()
    finally:
        tt.finalize()


def resolve_conflicts(tt):
    """Make many conflict-resolution attempts, but die if they fail"""
    for n in range(10):
        conflicts = tt.find_conflicts()
        if len(conflicts) == 0:
            return
        conflict_pass(tt, conflicts)
    raise MalformedTransform(conflicts=conflicts)


def conflict_pass(tt, conflicts):
    for c_type, conflict in ((c[0], c) for c in conflicts):
        if c_type == 'duplicate id':
            tt.unversion_file(conflict[1])
        elif c_type == 'duplicate':
            # files that were renamed take precedence
            new_name = tt.final_name(conflict[1])+'.moved'
            final_parent = tt.final_parent(conflict[1])
            if tt.path_changed(conflict[1]):
                tt.adjust_path(new_name, final_parent, conflict[2])
            else:
                tt.adjust_path(new_name, final_parent, conflict[1])
        elif c_type == 'parent loop':
            # break the loop by undoing one of the ops that caused the loop
            cur = conflict[1]
            while not tt.path_changed(cur):
                cur = tt.final_parent(cur)
            tt.adjust_path(tt.final_name(cur), tt.get_tree_parent(cur), cur)
        elif c_type == 'missing parent':
            trans_id = conflict[1]
            try:
                tt.cancel_deletion(trans_id)
            except KeyError:
                tt.create_directory(trans_id)
        elif c_type == 'unversioned parent':
            tt.version_file(tt.get_tree_file_id(conflict[1]), conflict[1])


class Merge3Merger(object):
    requires_base = True
    supports_reprocess = True
    supports_show_base = True
    history_based = False
    def __init__(self, working_tree, this_tree, base_tree, other_tree, 
                 reprocess=False, show_base=False):
        object.__init__(self)
        self.this_tree = working_tree
        self.base_tree = base_tree
        self.other_tree = other_tree
        self.conflicts = []
        self.reprocess = reprocess
        self.show_base = show_base

        all_ids = set(base_tree)
        all_ids.update(other_tree)
        self.tt = TreeTransform(working_tree)
        try:
            for file_id in all_ids:
                self.merge_names(file_id)
                file_status = self.merge_contents(file_id)
                self.merge_executable(file_id, file_status)
                
            resolve_conflicts(self.tt)
            self.tt.apply()
        finally:
            try:
                self.tt.finalize()
            except:
                pass
       
    @staticmethod
    def parent(entry, file_id):
        if entry is None:
            return None
        return entry.parent_id

    @staticmethod
    def name(entry, file_id):
        if entry is None:
            return None
        return entry.name
    
    @staticmethod
    def contents_sha1(tree, file_id):
        if file_id not in tree:
            return None
        return tree.get_file_sha1(file_id)

    @staticmethod
    def executable(tree, file_id):
        if file_id not in tree:
            return None
        if tree.kind(file_id) != "file":
            return False
        return tree.is_executable(file_id)

    @staticmethod
    def kind(tree, file_id):
        if file_id not in tree:
            return None
        return tree.kind(file_id)

    @staticmethod
    def scalar_three_way(this_tree, base_tree, other_tree, file_id, key):
        """Do a three-way test on a scalar.
        Return "this", "other" or "conflict", depending whether a value wins.
        """
        key_base = key(base_tree, file_id)
        key_other = key(other_tree, file_id)
        #if base == other, either they all agree, or only THIS has changed.
        if key_base == key_other:
            return "this"
        key_this = key(this_tree, file_id)
        if key_this not in (key_base, key_other):
            return "conflict"
        # "Ambiguous clean merge"
        elif key_this == key_other:
            return "this"
        else:
            assert key_this == key_base
            return "other"

    def merge_names(self, file_id):
        def get_entry(tree):
            if file_id in tree.inventory:
                return tree.inventory[file_id]
            else:
                return None
        this_entry = get_entry(self.this_tree)
        other_entry = get_entry(self.other_tree)
        base_entry = get_entry(self.base_tree)
        name_winner = self.scalar_three_way(this_entry, base_entry, 
                                            other_entry, file_id, self.name)
        parent_id_winner = self.scalar_three_way(this_entry, base_entry, 
                                                 other_entry, file_id, 
                                                 self.parent)
        if this_entry is None:
            if name_winner == "this":
                name_winner = "other"
            if parent_id_winner == "this":
                parent_id_winner = "other"
        if name_winner == "this" and parent_id_winner == "this":
            return
        if other_entry is None:
            # it doesn't matter whether the result was 'other' or 
            # 'conflict'-- if there's no 'other', we leave it alone.
            return
        # if we get here, name_winner and parent_winner are set to safe values.
        winner_entry = {"this": this_entry, "other": other_entry, 
                        "conflict": other_entry}
        trans_id = self.tt.get_trans_id(file_id)
        parent_id = winner_entry[parent_id_winner].parent_id
        parent_trans_id = self.tt.get_trans_id(parent_id)
        self.tt.adjust_path(winner_entry[name_winner].name, parent_trans_id,
                            trans_id)


    def merge_contents(self, file_id):
        def contents_pair(tree):
            if file_id not in tree:
                return (None, None)
            kind = tree.kind(file_id)
            if kind == "file":
                contents = tree.get_file_sha1(file_id)
            elif kind == "symlink":
                contents = tree.get_symlink_target(file_id)
            else:
                contents = None
            return kind, contents
        # See SPOT run.  run, SPOT, run.
        # So we're not QUITE repeating ourselves; we do tricky things with
        # file kind...
        base_pair = contents_pair(self.base_tree)
        other_pair = contents_pair(self.other_tree)
        if base_pair == other_pair:
            return "unmodified"
        this_pair = contents_pair(self.this_tree)
        if this_pair == other_pair:
            return "unmodified"
        else:
            trans_id = self.tt.get_trans_id(file_id)
            if this_pair == base_pair:
                if file_id in self.this_tree:
                    self.tt.delete_contents(trans_id)
                if file_id in self.other_tree.inventory:
                    create_by_entry(self.tt, 
                                    self.other_tree.inventory[file_id], 
                                    self.other_tree, trans_id)
                    return "modified"
                if file_id in self.this_tree:
                    self.tt.unversion_file(trans_id)
                    return "deleted"
            elif this_pair[0] == "file" and other_pair[0] == "file":
                # If this and other are both files, either base is a file, or
                # both converted to files, so at least we have agreement that
                # output should be a file.
                self.text_merge(file_id, trans_id)
                return "modified"
            else:
                trans_id = self.tt.get_trans_id(file_id)
                name = self.tt.final_name(trans_id)
                parent_id = self.tt.final_parent(trans_id)
                if file_id in self.this_tree.inventory:
                    self.tt.unversion_file(trans_id)
                    self.tt.delete_contents(trans_id)
                else:
                    self.tt.cancel_versioning(trans_id)
                self.conflicts.append(('contents conflict', (file_id)))
                file_group = self._dump_conflicts(name, parent_id, file_id, 
                                                  set_version=True)

    def get_lines(self, tree, file_id):
        if file_id in tree:
            return tree.get_file(file_id).readlines()
        else:
            return []

    def text_merge(self, file_id, trans_id):
        """Perform a three-way text merge on a file_id"""
        # it's possible that we got here with base as a different type.
        # if so, we just want two-way text conflicts.
        if file_id in self.base_tree and \
            self.base_tree.kind(file_id) == "file":
            base_lines = self.get_lines(self.base_tree, file_id)
        else:
            base_lines = []
        other_lines = self.get_lines(self.other_tree, file_id)
        this_lines = self.get_lines(self.this_tree, file_id)
        m3 = Merge3(base_lines, this_lines, other_lines)
        start_marker = "!START OF MERGE CONFLICT!" + "I HOPE THIS IS UNIQUE"
        if self.show_base is True:
            base_marker = '|' * 7
        else:
            base_marker = None

        def iter_merge3(retval):
            retval["text_conflicts"] = False
            for line in m3.merge_lines(name_a = "TREE", 
                                       name_b = "MERGE-SOURCE", 
                                       name_base = "BASE-REVISION",
                                       start_marker=start_marker, 
                                       base_marker=base_marker,
                                       reprocess=self.reprocess):
                if line.startswith(start_marker):
                    retval["text_conflicts"] = True
                    yield line.replace(start_marker, '<' * 7)
                else:
                    yield line
        retval = {}
        merge3_iterator = iter_merge3(retval)
        self.tt.create_file(merge3_iterator, trans_id)
        if retval["text_conflicts"] is True:
            self.conflicts.append(('text conflict', (file_id)))
            name = self.tt.final_name(trans_id)
            parent_id = self.tt.final_parent(trans_id)
            file_group = self._dump_conflicts(name, parent_id, file_id, 
                                              this_lines, base_lines,
                                              other_lines)
            file_group.append(trans_id)

    def _dump_conflicts(self, name, parent_id, file_id, this_lines=None, 
                        base_lines=None, other_lines=None, set_version=False,
                        no_base=False):
        data = [('OTHER', self.other_tree, other_lines), 
                ('THIS', self.this_tree, this_lines)]
        if not no_base:
            data.append(('BASE', self.base_tree, base_lines))
        versioned = False
        file_group = []
        for suffix, tree, lines in data:
            if file_id in tree:
                trans_id = self._conflict_file(name, parent_id, tree, file_id,
                                               suffix, lines)
                file_group.append(trans_id)
                if set_version and not versioned:
                    self.tt.version_file(file_id, trans_id)
                    versioned = True
        return file_group
           
    def _conflict_file(self, name, parent_id, tree, file_id, suffix, 
                       lines=None):
        name = name + '.' + suffix
        trans_id = self.tt.create_path(name, parent_id)
        entry = tree.inventory[file_id]
        create_by_entry(self.tt, entry, tree, trans_id, lines)
        return trans_id

    def merge_executable(self, file_id, file_status):
        if file_status == "deleted":
            return
        trans_id = self.tt.get_trans_id(file_id)
        try:
            if self.tt.final_kind(trans_id) != "file":
                return
        except NoSuchFile:
            return
        winner = self.scalar_three_way(self.this_tree, self.base_tree, 
                                       self.other_tree, file_id, 
                                       self.executable)
        if winner == "conflict":
        # There must be a None in here, if we have a conflict, but we
        # need executability since file status was not deleted.
            if self.other_tree.is_executable(file_id) is None:
                winner == "this"
            else:
                winner == "other"
        if winner == "this":
            if file_status == "modified":
                executability = self.this_tree.is_executable(file_id)
                if executability is not None:
                    trans_id = self.tt.get_trans_id(file_id)
                    self.tt.set_executability(executability, trans_id)
        else:
            assert winner == "other"
            if file_id in self.other_tree:
                executability = self.other_tree.is_executable(file_id)
            elif file_id in self.this_tree:
                executability = self.this_tree.is_executable(file_id)
            elif file_id in self.base_tree:
                executability = self.base_tree.is_executable(file_id)
            if executability is not None:
                trans_id = self.tt.get_trans_id(file_id)
                self.tt.set_executability(executability, trans_id)

class WeaveMerger(Merge3Merger):
    supports_reprocess = False
    supports_show_base = False
    def _merged_lines(self, file_id):
        """Generate the merged lines.
        There is no distinction between lines that are meant to contain <<<<<<<
        and conflicts.
        """
        if getattr(self.this_tree, 'get_weave', False) is False:
            # If we have a WorkingTree, try using the basis
            wt_sha1 = self.this_tree.get_file_sha1(file_id)
            this_tree = self.this_tree.branch.basis_tree()
            if this_tree.get_file_sha1(file_id) != wt_sha1:
                raise WorkingTreeNotRevision(self.this_tree)
        else:
            this_tree = self.this_tree
        weave = this_tree.get_weave(file_id)
        this_revision_id = this_tree.inventory[file_id].revision
        other_revision_id = self.other_tree.inventory[file_id].revision
        this_i = weave.lookup(this_revision_id)
        other_i = weave.lookup(other_revision_id)
        plan =  weave.plan_merge(this_i, other_i)
        return weave.weave_merge(plan)

    def text_merge(self, file_id, trans_id):
        lines = self._merged_lines(file_id)
        conflicts = '<<<<<<<\n' in lines
        self.tt.create_file(lines, trans_id)
        if conflicts:
            self.conflicts.append(('text conflict', (file_id)))
            name = self.tt.final_name(trans_id)
            parent_id = self.tt.final_parent(trans_id)
            file_group = self._dump_conflicts(name, parent_id, file_id, 
                                              no_base=True)
            file_group.append(trans_id)


class Diff3Merger(Merge3Merger):
    """Use good ol' diff3 to do text merges"""
    def dump_file(self, temp_dir, name, tree, file_id):
        out_path = pathjoin(temp_dir, name)
        out_file = file(out_path, "wb")
        in_file = tree.get_file(file_id)
        for line in in_file:
            out_file.write(line)
        return out_path

    def text_merge(self, file_id, trans_id):
        import bzrlib.patch
        temp_dir = mkdtemp(prefix="bzr-")
        try:
            new_file = os.path.join(temp_dir, "new")
            this = self.dump_file(temp_dir, "this", self.this_tree, file_id)
            base = self.dump_file(temp_dir, "base", self.base_tree, file_id)
            other = self.dump_file(temp_dir, "other", self.other_tree, file_id)
            status = bzrlib.patch.diff3(new_file, this, base, other)
            if status not in (0, 1):
                raise BzrError("Unhandled diff3 exit code")
            self.tt.create_file(file(new_file, "rb"), trans_id)
            if status == 1:
                name = self.tt.final_name(trans_id)
                parent_id = self.tt.final_parent(trans_id)
                self._dump_conflicts(name, parent_id, file_id)
            self.conflicts.append(('text conflict', (file_id)))
        finally:
            rmtree(temp_dir)
