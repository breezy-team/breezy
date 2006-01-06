import os
from bzrlib.errors import DuplicateKey, MalformedTransform, NoSuchFile
from bzrlib.osutils import file_kind
import errno
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
        self._new_id = {}
        self._tree_path_ids = {}
        self._tree_id_paths = {}
        self._new_root = self.get_id_tree(tree.get_root_id())

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

    def create_file(self, contents, trans_id):
        """Create a new, possibly versioned, file.
        
        Contents is an iterator of strings, all of which will be written
        to the target destination
        """
        unique_add(self._new_contents, trans_id, ('file', contents))

    def version_file(self, file_id, trans_id):
        unique_add(self._new_id, trans_id, file_id)

    def new_paths(self):
        new_ids = set()
        fp = FinalPaths(self._new_root, self._new_name, self._new_parent)
        for id_set in (self._new_name, self._new_parent, self._new_contents,
                       self._new_id):
            new_ids.update(id_set)
        new_paths = [(fp.get_path(t), t) for t in new_ids]
        new_paths.sort()
        return new_paths

    def final_kind(self, trans_id):
        """Determine the final file kind, after any changes applied.
        
        Raises NoSuchFile if the file does not exist/has no contents.
        (It is conceivable that a path would be created without the
        corresponding contents insertion command)
        """
        if trans_id in self._new_contents:
            return self._new_contents[trans_id][0]
        else:
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

    def find_conflicts(self):
        """Find any violations of inventory of filesystem invariants"""
        by_parent = {}
        conflicts = []
        for trans_id, parent_id in self._new_parent.iteritems():
            if parent_id not in by_parent:
                by_parent[parent_id] = set()
            by_parent[parent_id].add(trans_id)

        conflicts.extend(self._duplicate_entries(by_parent))
        conflicts.extend(self._parent_type_conflicts(by_parent))
        return conflicts

    def _duplicate_entries(self, by_parent):
        """No directory may have two entries with the same name."""
        conflicts = []
        for children in by_parent.itervalues():
            name_ids = [(self._new_name[t], t) for t in children]
            name_ids.sort()
            last_name = None
            last_trans_id = None
            for name, trans_id in name_ids:
                if name == last_name:
                    conflicts.append(('duplicate', last_trans_id, trans_id))
                last_name = name
                last_trans_id = trans_id
        return conflicts

    def _parent_type_conflicts(self, by_parent):
        """parents must have directory 'contents'."""
        conflicts = []
        for parent_id in by_parent.iterkeys():
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
        if len(self.find_conflicts()) != 0:
            raise MalformedTransform()
        inv = self._tree.inventory
        for path, trans_id in self.new_paths():
            try:
                kind, contents = self._new_contents[trans_id]
            except KeyError:
                kind = contents = None
            if kind == 'file':
                f = file(self._tree.abspath(path), 'wb')
                for segment in contents:
                    f.write(segment)
                f.close()

            if trans_id in self._new_id:
                if kind is None:
                    kind = file_kind()
                inv.add_path(path, kind, self._new_id[trans_id])
        self._tree._write_inventory(inv)

    def new_file(self, name, parent_id, contents, file_id=None):
        """Convenience method to create files""" 
        trans_id = self.create_path(name, parent_id)
        self.create_file(contents, trans_id)
        if file_id is not None:
            self.version_file(file_id, trans_id)
        return trans_id


class FinalPaths(object):
    def __init__(self, root, names, parents):
        object.__init__(self)
        self.root = root
        self._new_name = names
        self._new_parent = parents
        self._known_paths = {}

    def _determine_path(self, trans_id):
        if trans_id == self.root:
            return ""
        name = self._new_name[trans_id]
        parent_id = self._new_parent[trans_id]
        if parent_id == self.root:
            return name
        else:
            return os.path.join(self.get_path(parent_id), name)

    def get_path(self, trans_id):
        if trans_id not in self._known_paths:
            self._known_paths[trans_id] = self._determine_path(trans_id)
        return self._known_paths[trans_id]
