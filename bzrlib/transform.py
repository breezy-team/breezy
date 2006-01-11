import os
from bzrlib.errors import (DuplicateKey, MalformedTransform, NoSuchFile,
                           ReusingTransform)
from bzrlib.osutils import file_kind, supports_executable
from bzrlib.inventory import InventoryEntry
from bzrlib import BZRDIR
import errno

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
        self._tree_path_ids = {}
        self._tree_id_paths = {}
        self._new_root = self.get_id_tree(tree.get_root_id())
        self.__done = False

    def finalize(self):
        if self._tree is None:
            return
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
        self._new_name[trans_id] = name
        self._new_parent[trans_id] = parent

    def get_id_tree(self, inventory_id):
        """Determine the transaction id of a working tree file.
        
        This reflects only files that already exist, not ones that will be
        added by transactions.
        """
        return self.get_tree_path_id(self._tree.id2path(inventory_id))

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

    def create_file(self, contents, trans_id):
        """Schedule creation of a new file.

        See also new_file.
        
        Contents is an iterator of strings, all of which will be written
        to the target destination.
        """
        unique_add(self._new_contents, trans_id, ('file', contents))

    def create_directory(self, trans_id):
        """Schedule creation of a new directory.
        
        See also new_directory.
        """
        unique_add(self._new_contents, trans_id, ('directory',))

    def create_symlink(self, target, trans_id):
        """Schedule creation of a new symbolic link.

        target is a bytestring.
        See also new_symlink.
        """
        unique_add(self._new_contents, trans_id, ('symlink', target))

    def delete_contents(self, trans_id):
        """Schedule the contents of a path entry for deletion"""
        self._removed_contents.add(trans_id)

    def set_executability(self, executability, trans_id):
        """Schedule setting of the 'execute' bit"""
        if executability is None:
            del self._new_executability[trans_id]
        else:
            unique_add(self._new_executability, trans_id, executability)

    def version_file(self, file_id, trans_id):
        """Schedule a file to become versioned."""
        unique_add(self._new_id, trans_id, file_id)

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
            return self._new_contents[trans_id][0]
        elif trans_id in self._removed_contents:
            raise NoSuchFile(None)
        else:
            return self.tree_kind(trans_id)

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
            try:
                path = self._tree_id_paths[trans_id]
            except KeyError:
                # the file is a new, unversioned file, or invalid trans_id
                return None
            # the file is old; the old id is still valid
            return self._tree.path2id(path)

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
        try:
            return self._new_name[trans_id]
        except KeyError:
            return os.path.basename(self._tree_id_paths[trans_id])

    def _by_parent(self):
        by_parent = {}
        items = list(self._new_parent.iteritems())
        items.extend((t, self.final_parent(t)) for t in self._tree_id_paths)
        for trans_id, parent_id in items:
            if parent_id not in by_parent:
                by_parent[parent_id] = set()
            by_parent[parent_id].add(trans_id)
        return by_parent

    def find_conflicts(self):
        """Find any violations of inventory of filesystem invariants"""
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
        conflicts.extend(self._parent_type_conflicts(by_parent))
        conflicts.extend(self._improper_versioning())
        conflicts.extend(self._executability_conflicts())
        return conflicts

    def _add_tree_children(self):
        parents = self._by_parent().keys()
        parents.extend([t for t in self._removed_contents if 
                        self.tree_kind(t) == 'directory'])
        for parent_id in parents:
            try:
                path = self._tree_id_paths[parent_id]
            except KeyError:
                continue
            try:
                children = os.listdir(self._tree.abspath(path))
            except OSError, e:
                if e.errno != errno.ENOENT:
                    raise
                continue
                
            for child in children:
                childpath = joinpath(path, child)
                if childpath == BZRDIR:
                    continue
                self.get_tree_path_id(childpath)

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

    def _parent_type_conflicts(self, by_parent):
        """parents must have directory 'contents'."""
        conflicts = []
        for parent_id in by_parent.iterkeys():
            if parent_id is ROOT_PARENT:
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
            
    def apply(self):
        """\
        Apply all changes to the inventory and filesystem.
        
        If filesystem or inventory conflicts are present, MalformedTransform
        will be thrown.
        """
        if len(self.find_conflicts()) != 0:
            raise MalformedTransform()
        inv = self._tree.inventory
        for trans_id in self._removed_contents:
            if trans_id in self._removed_contents:
                path = self._tree_id_paths[trans_id]
                try:
                    os.unlink(path)
                except OSError, e:
                    if e.errno != errno.EISDIR:
                        raise
                    os.rmdir(path)

        for path, trans_id in self.new_paths():
            try:
                kind = self._new_contents[trans_id][0]
            except KeyError:
                kind = contents = None
            if kind == 'file':
                contents = self._new_contents[trans_id][1]
                f = file(self._tree.abspath(path), 'wb')
                for segment in contents:
                    f.write(segment)
                f.close()
            elif kind == 'directory':
                os.mkdir(self._tree.abspath(path))
            elif kind == 'symlink':
                target = self._new_contents[trans_id][1]
                os.symlink(target, path)

            if trans_id in self._new_id:
                if kind is None:
                    kind = file_kind(self._tree.abspath(path))
                inv.add_path(path, kind, self._new_id[trans_id])
            # requires files and inventory entries to be in place
            if trans_id in self._new_executability:
                self._set_executability(path, inv, trans_id)

        self._tree._write_inventory(inv)
        self.__done = True

    def _set_executability(self, path, inv, trans_id):
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
    file_ids = list(tree)
    file_ids.sort(key=tree.id2path)
    return file_ids

def build_tree(branch, tree):
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
            name = entry.name
            kind = entry.kind
            if kind == 'file':
                contents = tree.get_file_lines(file_id)
                executable = tree.is_executable(file_id)
                file_trans_id[file_id] = tt.new_file(name, parent_id, contents,
                                                     file_id, executable)
            elif kind == 'directory':
                file_trans_id[file_id] = tt.new_directory(name, parent_id, 
                                                          file_id)
            elif kind == 'symlink':
                target = entry.get_symlink_target(file_id)
                file_trans_id[file_id] = tt.new_symlink(name, parent_id,
                                                        target, file_id)
        tt.apply()
    finally:
        tt.finalize()
