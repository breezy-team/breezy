#! /usr/bin/env python
# -*- coding: UTF-8 -*-

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

from inventory import Inventory
from trace import mutter, note
from osutils import pumpfile, compare_files, filesize, quotefn, sha_file, \
     joinpath, splitpath, appendpath, isdir, isfile, file_kind
from errors import bailout
import branch
from stat import S_ISREG, S_ISDIR, ST_MODE, ST_SIZE

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

    def id_set(self):
        """Return set of all ids in this tree."""
        return self.inventory.id_set()

    def id2path(self, file_id):
        return self.inventory.id2path(file_id)

    def _get_inventory(self):
        return self._inventory

    inventory = property(_get_inventory,
                         doc="Inventory of this Tree")

    def _check_retrieved(self, ie, f):
        # TODO: Test this check by damaging the store?
        if ie.text_size is not None:
            fs = filesize(f)
            if fs != ie.text_size:
                bailout("mismatched size for file %r in %r" % (ie.file_id, self._store),
                        ["inventory expects %d bytes" % ie.text_size,
                         "file is actually %d bytes" % fs,
                         "store is probably damaged/corrupt"])

        f_hash = sha_file(f)
        f.seek(0)
        if ie.text_sha1 != f_hash:
            bailout("wrong SHA-1 for file %r in %r" % (ie.file_id, self._store),
                    ["inventory expects %s" % ie.text_sha1,
                     "file is actually %s" % f_hash,
                     "store is probably damaged/corrupt"])


    def export(self, dest):
        """Export this tree to a new directory.

        `dest` should not exist, and will be created holding the
        contents of this tree.

        :todo: To handle subdirectories we need to create the
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
                bailout("don't know how to export {%s} of kind %r", fid, kind)
            mutter("  export {%s} kind %s to %s" % (ie.file_id, kind, fullpath))



class WorkingTree(Tree):
    """Working copy tree.

    The inventory is held in the `Branch` working-inventory, and the
    files are in a directory on disk.

    It is possible for a `WorkingTree` to have a filename which is
    not listed in the Inventory and vice versa.
    """
    def __init__(self, basedir, inv):
        self._inventory = inv
        self.basedir = basedir
        self.path2id = inv.path2id

    def __repr__(self):
        return "<%s of %s>" % (self.__class__.__name__,
                               self.basedir)

    def abspath(self, filename):
        return os.path.join(self.basedir, filename)

    def has_filename(self, filename):
        return os.path.exists(self.abspath(filename))

    def get_file(self, file_id):
        return self.get_file_byname(self.id2path(file_id))

    def get_file_byname(self, filename):
        return file(self.abspath(filename), 'rb')

    def _get_store_filename(self, file_id):
        return self.abspath(self.id2path(file_id))

    def has_id(self, file_id):
        # files that have been deleted are excluded
        if not self.inventory.has_id(file_id):
            return False
        return os.access(self.abspath(self.inventory.id2path(file_id)), os.F_OK)

    def get_file_size(self, file_id):
        return os.stat(self._get_store_filename(file_id))[ST_SIZE]

    def get_file_sha1(self, file_id):
        f = self.get_file(file_id)
        return sha_file(f)


    def file_class(self, filename):
        if self.path2id(filename):
            return 'V'
        elif self.is_ignored(filename):
            return 'I'
        else:
            return '?'


    def file_kind(self, filename):
        if isfile(self.abspath(filename)):
            return 'file'
        elif isdir(self.abspath(filename)):
            return 'directory'
        else:
            return 'unknown'


    def list_files(self):
        """Recursively list all files as (path, class, kind, id).

        Lists, but does not descend into unversioned directories.

        This does not include files that have been deleted in this
        tree.

        Skips the control directory.
        """
        inv = self.inventory

        def descend(from_dir, from_dir_id, dp):
            ls = os.listdir(dp)
            ls.sort()
            for f in ls:
                if bzrlib.BZRDIR == f:
                    continue

                # path within tree
                fp = appendpath(from_dir, f)

                # absolute path
                fap = appendpath(dp, f)
                
                f_ie = inv.get_child(from_dir_id, f)
                if f_ie:
                    c = 'V'
                elif self.is_ignored(fp):
                    c = 'I'
                else:
                    c = '?'

                fk = file_kind(fap)

                if f_ie:
                    if f_ie.kind != fk:
                        bailout("file %r entered as kind %r id %r, now of kind %r"
                                % (fap, f_ie.kind, f_ie.file_id, fk))

                yield fp, c, fk, (f_ie and f_ie.file_id)

                if fk != 'directory':
                    continue

                if c != 'V':
                    # don't descend unversioned directories
                    continue
                
                for ff in descend(fp, f_ie.file_id, fap):
                    yield ff

        for f in descend('', None, self.basedir):
            yield f
            


    def unknowns(self, path='', dir_id=None):
        """Yield names of unknown files in this WorkingTree.

        If there are any unknown directories then only the directory is
        returned, not all its children.  But if there are unknown files
        under a versioned subdirectory, they are returned.

        Currently returned depth-first, sorted by name within directories.
        """
        for fpath, fclass, fkind, fid in self.list_files():
            if fclass == '?':
                yield fpath
                

    def ignored_files(self):
        for fpath, fclass, fkind, fid in self.list_files():
            if fclass == 'I':
                yield fpath


    def get_ignore_list(self):
        """Return list of ignore patterns."""
        if self.has_filename(bzrlib.IGNORE_FILENAME):
            f = self.get_file_byname(bzrlib.IGNORE_FILENAME)
            return [line.rstrip("\n\r") for line in f.readlines()]
        else:
            return bzrlib.DEFAULT_IGNORE


    def is_ignored(self, filename):
        """Check whether the filename matches an ignore pattern.

        Patterns containing '/' need to match the whole path; others
        match against only the last component."""
        ## TODO: Take them from a file, not hardcoded
        ## TODO: Use extended zsh-style globs maybe?
        ## TODO: Use '**' to match directories?
        for pat in self.get_ignore_list():
            if '/' in pat:
                if fnmatch.fnmatchcase(filename, pat):
                    return True
            else:
                if fnmatch.fnmatchcase(splitpath(filename)[-1], pat):
                    return True
        return False
        

        
        

class RevisionTree(Tree):
    """Tree viewing a previous revision.

    File text can be retrieved from the text store.

    :todo: Some kind of `__repr__` method, but a good one
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
        fs = filesize(f)
        if ie.text_size is None:
            note("warning: no text size recorded on %r" % ie)
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

    

