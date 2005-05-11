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

"""Tree classes, representing directory at point in time.
"""

from sets import Set
import os.path, os, fnmatch

from osutils import pumpfile, filesize, quotefn, sha_file, \
     joinpath, splitpath, appendpath, isdir, isfile, file_kind, fingerprint_file
import errno
from stat import S_ISREG, S_ISDIR, ST_MODE, ST_SIZE

from inventory import Inventory
from trace import mutter, note
from errors import bailout
import branch

import bzrlib

class Tree:
    """Abstract file tree.

    There are several subclasses:
    
    * `WorkingTree` exists as files on disk editable by the user.

    * `RevisionTree` is a tree as recorded at some point in the past.

    * `EmptyTree`

    Trees contain an `Inventory` object, and also know how to retrieve
    file texts mentioned in the inventory, either from a working
    directory or from a store.

    It is possible for trees to contain files that are not described
    in their inventory or vice versa; for this use `filenames()`.

    Trees can be compared, etc, regardless of whether they are working
    trees or versioned trees.
    """
    
    def has_filename(self, filename):
        """True if the tree has given filename."""
        raise NotImplementedError()

    def has_id(self, file_id):
        return self.inventory.has_id(file_id)

    __contains__ = has_id

    def id_set(self):
        """Return set of all ids in this tree."""
        return self.inventory.id_set()

    def __iter__(self):
        return iter(self.inventory)

    def id2path(self, file_id):
        return self.inventory.id2path(file_id)

    def _get_inventory(self):
        return self._inventory

    inventory = property(_get_inventory,
                         doc="Inventory of this Tree")

    def _check_retrieved(self, ie, f):
        fp = fingerprint_file(f)
        f.seek(0)
        
        if ie.text_size != None:
            if ie.text_size != fp['size']:
                bailout("mismatched size for file %r in %r" % (ie.file_id, self._store),
                        ["inventory expects %d bytes" % ie.text_size,
                         "file is actually %d bytes" % fp['size'],
                         "store is probably damaged/corrupt"])

        if ie.text_sha1 != fp['sha1']:
            bailout("wrong SHA-1 for file %r in %r" % (ie.file_id, self._store),
                    ["inventory expects %s" % ie.text_sha1,
                     "file is actually %s" % fp['sha1'],
                     "store is probably damaged/corrupt"])


    def print_file(self, fileid):
        """Print file with id `fileid` to stdout."""
        import sys
        pumpfile(self.get_file(fileid), sys.stdout)
        
        
    def export(self, dest):        
        """Export this tree to a new directory.

        `dest` should not exist, and will be created holding the
        contents of this tree.

        TODO: To handle subdirectories we need to create the
               directories first.

        :note: If the export fails, the destination directory will be
               left in a half-assed state.
        """
        os.mkdir(dest)
        mutter('export version %r' % self)
        inv = self.inventory
        for dp, ie in inv.iter_entries():
            kind = ie.kind
            fullpath = appendpath(dest, dp)
            if kind == 'directory':
                os.mkdir(fullpath)
            elif kind == 'file':
                pumpfile(self.get_file(ie.file_id), file(fullpath, 'wb'))
            else:
                bailout("don't know how to export {%s} of kind %r" % (ie.file_id, kind))
            mutter("  export {%s} kind %s to %s" % (ie.file_id, kind, fullpath))



class RevisionTree(Tree):
    """Tree viewing a previous revision.

    File text can be retrieved from the text store.

    TODO: Some kind of `__repr__` method, but a good one
           probably means knowing the branch and revision number,
           or at least passing a description to the constructor.
    """
    
    def __init__(self, store, inv):
        self._store = store
        self._inventory = inv

    def get_file(self, file_id):
        ie = self._inventory[file_id]
        f = self._store[ie.text_id]
        mutter("  get fileid{%s} from %r" % (file_id, self))
        self._check_retrieved(ie, f)
        return f

    def get_file_size(self, file_id):
        return self._inventory[file_id].text_size

    def get_file_sha1(self, file_id):
        ie = self._inventory[file_id]
        return ie.text_sha1

    def has_filename(self, filename):
        return bool(self.inventory.path2id(filename))

    def list_files(self):
        # The only files returned by this are those from the version
        for path, entry in self.inventory.iter_entries():
            yield path, 'V', entry.kind, entry.file_id


class EmptyTree(Tree):
    def __init__(self):
        self._inventory = Inventory()

    def has_filename(self, filename):
        return False

    def list_files(self):
        if False:  # just to make it a generator
            yield None
    


######################################################################
# diff

# TODO: Merge these two functions into a single one that can operate
# on either a whole tree or a set of files.

# TODO: Return the diff in order by filename, not by category or in
# random order.  Can probably be done by lock-stepping through the
# filenames from both trees.


def file_status(filename, old_tree, new_tree):
    """Return single-letter status, old and new names for a file.

    The complexity here is in deciding how to represent renames;
    many complex cases are possible.
    """
    old_inv = old_tree.inventory
    new_inv = new_tree.inventory
    new_id = new_inv.path2id(filename)
    old_id = old_inv.path2id(filename)

    if not new_id and not old_id:
        # easy: doesn't exist in either; not versioned at all
        if new_tree.is_ignored(filename):
            return 'I', None, None
        else:
            return '?', None, None
    elif new_id:
        # There is now a file of this name, great.
        pass
    else:
        # There is no longer a file of this name, but we can describe
        # what happened to the file that used to have
        # this name.  There are two possibilities: either it was
        # deleted entirely, or renamed.
        assert old_id
        if new_inv.has_id(old_id):
            return 'X', old_inv.id2path(old_id), new_inv.id2path(old_id)
        else:
            return 'D', old_inv.id2path(old_id), None

    # if the file_id is new in this revision, it is added
    if new_id and not old_inv.has_id(new_id):
        return 'A'

    # if there used to be a file of this name, but that ID has now
    # disappeared, it is deleted
    if old_id and not new_inv.has_id(old_id):
        return 'D'

    return 'wtf?'

    

def find_renames(old_inv, new_inv):
    for file_id in old_inv:
        if file_id not in new_inv:
            continue
        old_name = old_inv.id2path(file_id)
        new_name = new_inv.id2path(file_id)
        if old_name != new_name:
            yield (old_name, new_name)
            
