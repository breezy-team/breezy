import os
def unique_add(map, key, value):
    if key in map:
        raise Exception("Key %s already present in map")
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
        self._new_file = {}
        self._new_id = {}
        self.root = "root"

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

    def get_id_tree(self, inventory_id):
        """Determine the transaction id of a working tree file.
        
        This reflects only files that already exist, not ones that will be
        added by transactions.
        """
        if inventory_id not in self._tree:
            raise Exception('ID not in tree')
        return 'tree-%s' % inventory_id

    def create_file(self, contents, trans_id):
        """Create a new, possibly versioned, file.
        
        Contents is an iterator of strings, all of which will be written
        to the target destination
        """
        unique_add(self._new_file, trans_id, contents)

    def version_file(self, file_id, trans_id):
        unique_add(self._new_id, trans_id, file_id)

    def new_paths(self):
        new_ids = set()
        fp = FinalPaths(self.root, self._new_name, self._new_parent)
        for id_set in (self._new_name, self._new_parent, self._new_file,
                       self._new_id):
            new_ids.update(id_set)
        new_paths = [(fp.get_path(t), t) for t in new_ids]
        new_paths.sort()
        return new_paths
            
    def apply(self):
        inv = self._tree.inventory
        for path, trans_id in self.new_paths():
            kind = None
            if trans_id in self._new_file:
                f = file(self._tree.abspath(path), 'wb')
                for segment in self._new_file[trans_id]:
                    f.write(segment)
                f.close()
                kind = "file"

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
