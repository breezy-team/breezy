# (C) 2005 Canonical Ltd

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


# TODO: Maybe also keep the full path of the entry, and the children?
# But those depend on its position within a particular inventory, and
# it would be nice not to need to hold the backpointer here.

# TODO: Perhaps split InventoryEntry into subclasses for files,
# directories, etc etc.


# This should really be an id randomly assigned when the tree is
# created, but it's not for now.
ROOT_ID = "TREE_ROOT"


import sys, os.path, types, re

import bzrlib
from bzrlib.errors import BzrError, BzrCheckError

from bzrlib.osutils import uuid, quotefn, splitpath, joinpath, appendpath
from bzrlib.trace import mutter
from bzrlib.errors import NotVersionedError
        

class InventoryEntry(object):
    """Description of a versioned file.

    An InventoryEntry has the following fields, which are also
    present in the XML inventory-entry element:

    file_id

    name
        (within the parent directory)

    kind
        'directory' or 'file'

    parent_id
        file_id of the parent directory, or ROOT_ID

    name_version
        the revision_id in which the name or parent of this file was
        last changed

    text_sha1
        sha-1 of the text of the file
        
    text_size
        size in bytes of the text of the file
        
    text_version
        the revision_id in which the text of this file was introduced

    (reading a version 4 tree created a text_id field.)

    >>> i = Inventory()
    >>> i.path2id('')
    'TREE_ROOT'
    >>> i.add(InventoryEntry('123', 'src', 'directory', ROOT_ID))
    InventoryEntry('123', 'src', kind='directory', parent_id='TREE_ROOT')
    >>> i.add(InventoryEntry('2323', 'hello.c', 'file', parent_id='123'))
    InventoryEntry('2323', 'hello.c', kind='file', parent_id='123')
    >>> for j in i.iter_entries():
    ...   print j
    ... 
    ('src', InventoryEntry('123', 'src', kind='directory', parent_id='TREE_ROOT'))
    ('src/hello.c', InventoryEntry('2323', 'hello.c', kind='file', parent_id='123'))
    >>> i.add(InventoryEntry('2323', 'bye.c', 'file', '123'))
    Traceback (most recent call last):
    ...
    BzrError: inventory already contains entry with id {2323}
    >>> i.add(InventoryEntry('2324', 'bye.c', 'file', '123'))
    InventoryEntry('2324', 'bye.c', kind='file', parent_id='123')
    >>> i.add(InventoryEntry('2325', 'wibble', 'directory', '123'))
    InventoryEntry('2325', 'wibble', kind='directory', parent_id='123')
    >>> i.path2id('src/wibble')
    '2325'
    >>> '2325' in i
    True
    >>> i.add(InventoryEntry('2326', 'wibble.c', 'file', '2325'))
    InventoryEntry('2326', 'wibble.c', kind='file', parent_id='2325')
    >>> i['2326']
    InventoryEntry('2326', 'wibble.c', kind='file', parent_id='2325')
    >>> for j in i.iter_entries():
    ...     print j[0]
    ...     assert i.path2id(j[0])
    ... 
    src
    src/bye.c
    src/hello.c
    src/wibble
    src/wibble/wibble.c
    >>> i.id2path('2326')
    'src/wibble/wibble.c'
    """
    
    __slots__ = ['text_sha1', 'text_size', 'file_id', 'name', 'kind',
                 'text_id', 'parent_id', 'children',
                 'text_version', 'name_version', ]


    def __init__(self, file_id, name, kind, parent_id, text_id=None):
        """Create an InventoryEntry
        
        The filename must be a single component, relative to the
        parent directory; it cannot be a whole path or relative name.

        >>> e = InventoryEntry('123', 'hello.c', 'file', ROOT_ID)
        >>> e.name
        'hello.c'
        >>> e.file_id
        '123'
        >>> e = InventoryEntry('123', 'src/hello.c', 'file', ROOT_ID)
        Traceback (most recent call last):
        BzrCheckError: InventoryEntry name 'src/hello.c' is invalid
        """
        assert isinstance(name, basestring), name
        if '/' in name or '\\' in name:
            raise BzrCheckError('InventoryEntry name %r is invalid' % name)
        
        self.text_version = None
        self.name_version = None
        self.text_sha1 = None
        self.text_size = None
        self.file_id = file_id
        self.name = name
        self.kind = kind
        self.text_id = text_id
        self.parent_id = parent_id
        if kind == 'directory':
            self.children = {}
        elif kind == 'file':
            pass
        else:
            raise BzrError("unhandled entry kind %r" % kind)



    def sorted_children(self):
        l = self.children.items()
        l.sort()
        return l


    def copy(self):
        other = InventoryEntry(self.file_id, self.name, self.kind,
                               self.parent_id)
        other.text_id = self.text_id
        other.text_sha1 = self.text_sha1
        other.text_size = self.text_size
        other.text_version = self.text_version
        other.name_version = self.name_version
        # note that children are *not* copied; they're pulled across when
        # others are added
        return other


    def __repr__(self):
        return ("%s(%r, %r, kind=%r, parent_id=%r)"
                % (self.__class__.__name__,
                   self.file_id,
                   self.name,
                   self.kind,
                   self.parent_id))

    
    def __eq__(self, other):
        if not isinstance(other, InventoryEntry):
            return NotImplemented

        return (self.file_id == other.file_id) \
               and (self.name == other.name) \
               and (self.text_sha1 == other.text_sha1) \
               and (self.text_size == other.text_size) \
               and (self.text_id == other.text_id) \
               and (self.parent_id == other.parent_id) \
               and (self.kind == other.kind) \
               and (self.text_version == other.text_version) \
               and (self.name_version == other.name_version)


    def __ne__(self, other):
        return not (self == other)

    def __hash__(self):
        raise ValueError('not hashable')



class RootEntry(InventoryEntry):
    def __init__(self, file_id):
        self.file_id = file_id
        self.children = {}
        self.kind = 'root_directory'
        self.parent_id = None
        self.name = ''

    def __eq__(self, other):
        if not isinstance(other, RootEntry):
            return NotImplemented
        
        return (self.file_id == other.file_id) \
               and (self.children == other.children)



class Inventory(object):
    """Inventory of versioned files in a tree.

    This describes which file_id is present at each point in the tree,
    and possibly the SHA-1 or other information about the file.
    Entries can be looked up either by path or by file_id.

    The inventory represents a typical unix file tree, with
    directories containing files and subdirectories.  We never store
    the full path to a file, because renaming a directory implicitly
    moves all of its contents.  This class internally maintains a
    lookup tree that allows the children under a directory to be
    returned quickly.

    InventoryEntry objects must not be modified after they are
    inserted, other than through the Inventory API.

    >>> inv = Inventory()
    >>> inv.add(InventoryEntry('123-123', 'hello.c', 'file', ROOT_ID))
    InventoryEntry('123-123', 'hello.c', kind='file', parent_id='TREE_ROOT')
    >>> inv['123-123'].name
    'hello.c'

    May be treated as an iterator or set to look up file ids:
    
    >>> bool(inv.path2id('hello.c'))
    True
    >>> '123-123' in inv
    True

    May also look up by name:

    >>> [x[0] for x in inv.iter_entries()]
    ['hello.c']
    >>> inv = Inventory('TREE_ROOT-12345678-12345678')
    >>> inv.add(InventoryEntry('123-123', 'hello.c', 'file', ROOT_ID))
    InventoryEntry('123-123', 'hello.c', kind='file', parent_id='TREE_ROOT-12345678-12345678')
    """
    def __init__(self, root_id=ROOT_ID):
        """Create or read an inventory.

        If a working directory is specified, the inventory is read
        from there.  If the file is specified, read from that. If not,
        the inventory is created empty.

        The inventory is created with a default root directory, with
        an id of None.
        """
        # We are letting Branch(init=True) create a unique inventory
        # root id. Rather than generating a random one here.
        #if root_id is None:
        #    root_id = bzrlib.branch.gen_file_id('TREE_ROOT')
        self.root = RootEntry(root_id)
        self._byid = {self.root.file_id: self.root}


    def copy(self):
        other = Inventory(self.root.file_id)
        # copy recursively so we know directories will be added before
        # their children.  There are more efficient ways than this...
        for path, entry in self.iter_entries():
            if entry == self.root:
                continue
            other.add(entry.copy())
        return other


    def __iter__(self):
        return iter(self._byid)


    def __len__(self):
        """Returns number of entries."""
        return len(self._byid)


    def iter_entries(self, from_dir=None):
        """Return (path, entry) pairs, in order by name."""
        if from_dir == None:
            assert self.root
            from_dir = self.root
        elif isinstance(from_dir, basestring):
            from_dir = self._byid[from_dir]
            
        kids = from_dir.children.items()
        kids.sort()
        for name, ie in kids:
            yield name, ie
            if ie.kind == 'directory':
                for cn, cie in self.iter_entries(from_dir=ie.file_id):
                    yield os.path.join(name, cn), cie


    def entries(self):
        """Return list of (path, ie) for all entries except the root.

        This may be faster than iter_entries.
        """
        accum = []
        def descend(dir_ie, dir_path):
            kids = dir_ie.children.items()
            kids.sort()
            for name, ie in kids:
                child_path = os.path.join(dir_path, name)
                accum.append((child_path, ie))
                if ie.kind == 'directory':
                    descend(ie, child_path)

        descend(self.root, '')
        return accum


    def directories(self):
        """Return (path, entry) pairs for all directories, including the root.
        """
        accum = []
        def descend(parent_ie, parent_path):
            accum.append((parent_path, parent_ie))
            
            kids = [(ie.name, ie) for ie in parent_ie.children.itervalues() if ie.kind == 'directory']
            kids.sort()

            for name, child_ie in kids:
                child_path = os.path.join(parent_path, name)
                descend(child_ie, child_path)
        descend(self.root, '')
        return accum
        


    def __contains__(self, file_id):
        """True if this entry contains a file with given id.

        >>> inv = Inventory()
        >>> inv.add(InventoryEntry('123', 'foo.c', 'file', ROOT_ID))
        InventoryEntry('123', 'foo.c', kind='file', parent_id='TREE_ROOT')
        >>> '123' in inv
        True
        >>> '456' in inv
        False
        """
        return file_id in self._byid


    def __getitem__(self, file_id):
        """Return the entry for given file_id.

        >>> inv = Inventory()
        >>> inv.add(InventoryEntry('123123', 'hello.c', 'file', ROOT_ID))
        InventoryEntry('123123', 'hello.c', kind='file', parent_id='TREE_ROOT')
        >>> inv['123123'].name
        'hello.c'
        """
        try:
            return self._byid[file_id]
        except KeyError:
            if file_id == None:
                raise BzrError("can't look up file_id None")
            else:
                raise BzrError("file_id {%s} not in inventory" % file_id)


    def get_file_kind(self, file_id):
        return self._byid[file_id].kind

    def get_child(self, parent_id, filename):
        return self[parent_id].children.get(filename)


    def add(self, entry):
        """Add entry to inventory.

        To add  a file to a branch ready to be committed, use Branch.add,
        which calls this.

        Returns the new entry object.
        """
        if entry.file_id in self._byid:
            raise BzrError("inventory already contains entry with id {%s}" % entry.file_id)

        if entry.parent_id == ROOT_ID or entry.parent_id is None:
            entry.parent_id = self.root.file_id

        try:
            parent = self._byid[entry.parent_id]
        except KeyError:
            raise BzrError("parent_id {%s} not in inventory" % entry.parent_id)

        if parent.children.has_key(entry.name):
            raise BzrError("%s is already versioned" %
                    appendpath(self.id2path(parent.file_id), entry.name))

        self._byid[entry.file_id] = entry
        parent.children[entry.name] = entry
        return entry


    def add_path(self, relpath, kind, file_id=None):
        """Add entry from a path.

        The immediate parent must already be versioned.

        Returns the new entry object."""
        from bzrlib.branch import gen_file_id
        
        parts = bzrlib.osutils.splitpath(relpath)
        if len(parts) == 0:
            raise BzrError("cannot re-add root of inventory")

        if file_id == None:
            file_id = gen_file_id(relpath)

        parent_path = parts[:-1]
        parent_id = self.path2id(parent_path)
        if parent_id == None:
            raise NotVersionedError(parent_path)

        ie = InventoryEntry(file_id, parts[-1],
                            kind=kind, parent_id=parent_id)
        return self.add(ie)


    def __delitem__(self, file_id):
        """Remove entry by id.

        >>> inv = Inventory()
        >>> inv.add(InventoryEntry('123', 'foo.c', 'file', ROOT_ID))
        InventoryEntry('123', 'foo.c', kind='file', parent_id='TREE_ROOT')
        >>> '123' in inv
        True
        >>> del inv['123']
        >>> '123' in inv
        False
        """
        ie = self[file_id]

        assert self[ie.parent_id].children[ie.name] == ie
        
        # TODO: Test deleting all children; maybe hoist to a separate
        # deltree method?
        if ie.kind == 'directory':
            for cie in ie.children.values():
                del self[cie.file_id]
            del ie.children

        del self._byid[file_id]
        del self[ie.parent_id].children[ie.name]


    def __eq__(self, other):
        """Compare two sets by comparing their contents.

        >>> i1 = Inventory()
        >>> i2 = Inventory()
        >>> i1 == i2
        True
        >>> i1.add(InventoryEntry('123', 'foo', 'file', ROOT_ID))
        InventoryEntry('123', 'foo', kind='file', parent_id='TREE_ROOT')
        >>> i1 == i2
        False
        >>> i2.add(InventoryEntry('123', 'foo', 'file', ROOT_ID))
        InventoryEntry('123', 'foo', kind='file', parent_id='TREE_ROOT')
        >>> i1 == i2
        True
        """
        if not isinstance(other, Inventory):
            return NotImplemented

        if len(self._byid) != len(other._byid):
            # shortcut: obviously not the same
            return False

        return self._byid == other._byid


    def __ne__(self, other):
        return not self.__eq__(other)


    def __hash__(self):
        raise ValueError('not hashable')


    def get_idpath(self, file_id):
        """Return a list of file_ids for the path to an entry.

        The list contains one element for each directory followed by
        the id of the file itself.  So the length of the returned list
        is equal to the depth of the file in the tree, counting the
        root directory as depth 1.
        """
        p = []
        while file_id != None:
            try:
                ie = self._byid[file_id]
            except KeyError:
                raise BzrError("file_id {%s} not found in inventory" % file_id)
            p.insert(0, ie.file_id)
            file_id = ie.parent_id
        return p


    def id2path(self, file_id):
        """Return as a list the path to file_id."""

        # get all names, skipping root
        p = [self._byid[fid].name for fid in self.get_idpath(file_id)[1:]]
        return os.sep.join(p)
            


    def path2id(self, name):
        """Walk down through directories to return entry of last component.

        names may be either a list of path components, or a single
        string, in which case it is automatically split.

        This returns the entry of the last component in the path,
        which may be either a file or a directory.

        Returns None iff the path is not found.
        """
        if isinstance(name, types.StringTypes):
            name = splitpath(name)

        mutter("lookup path %r" % name)

        parent = self.root
        for f in name:
            try:
                cie = parent.children[f]
                assert cie.name == f
                assert cie.parent_id == parent.file_id
                parent = cie
            except KeyError:
                # or raise an error?
                return None

        return parent.file_id


    def has_filename(self, names):
        return bool(self.path2id(names))


    def has_id(self, file_id):
        return self._byid.has_key(file_id)


    def rename(self, file_id, new_parent_id, new_name):
        """Move a file within the inventory.

        This can change either the name, or the parent, or both.

        This does not move the working file."""
        if not is_valid_name(new_name):
            raise BzrError("not an acceptable filename: %r" % new_name)

        new_parent = self._byid[new_parent_id]
        if new_name in new_parent.children:
            raise BzrError("%r already exists in %r" % (new_name, self.id2path(new_parent_id)))

        new_parent_idpath = self.get_idpath(new_parent_id)
        if file_id in new_parent_idpath:
            raise BzrError("cannot move directory %r into a subdirectory of itself, %r"
                    % (self.id2path(file_id), self.id2path(new_parent_id)))

        file_ie = self._byid[file_id]
        old_parent = self._byid[file_ie.parent_id]

        # TODO: Don't leave things messed up if this fails

        del old_parent.children[file_ie.name]
        new_parent.children[new_name] = file_ie
        
        file_ie.name = new_name
        file_ie.parent_id = new_parent_id




_NAME_RE = None

def is_valid_name(name):
    global _NAME_RE
    if _NAME_RE == None:
        _NAME_RE = re.compile(r'^[^/\\]+$')
        
    return bool(_NAME_RE.match(name))
