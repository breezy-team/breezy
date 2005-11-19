# Copyright (C) 2004 Aaron Bentley <aaron.bentley@utoronto.ca>
#
#    This program is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program; if not, write to the Free Software
#    Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Represent and apply a changeset.

Conflicts in applying a changeset are represented as exceptions.

This only handles the in-memory objects representing changesets, which are
primarily used by the merge code. 
"""

import os.path
import errno
import stat
from tempfile import mkdtemp
from shutil import rmtree
from itertools import izip

from bzrlib.trace import mutter, warning
from bzrlib.osutils import rename, sha_file
import bzrlib

__docformat__ = "restructuredtext"

NULL_ID = "!NULL"

class OldFailedTreeOp(Exception):
    def __init__(self):
        Exception.__init__(self, "bzr-tree-change contains files from a"
                           " previous failed merge operation.")
def invert_dict(dict):
    newdict = {}
    for (key,value) in dict.iteritems():
        newdict[value] = key
    return newdict

       
class ChangeExecFlag(object):
    """This is two-way change, suitable for file modification, creation,
    deletion"""
    def __init__(self, old_exec_flag, new_exec_flag):
        self.old_exec_flag = old_exec_flag
        self.new_exec_flag = new_exec_flag

    def apply(self, filename, conflict_handler, reverse=False):
        if not reverse:
            from_exec_flag = self.old_exec_flag
            to_exec_flag = self.new_exec_flag
        else:
            from_exec_flag = self.new_exec_flag
            to_exec_flag = self.old_exec_flag
        try:
            current_exec_flag = bool(os.stat(filename).st_mode & 0111)
        except OSError, e:
            if e.errno == errno.ENOENT:
                if conflict_handler.missing_for_exec_flag(filename) == "skip":
                    return
                else:
                    current_exec_flag = from_exec_flag

        if from_exec_flag is not None and current_exec_flag != from_exec_flag:
            if conflict_handler.wrong_old_exec_flag(filename,
                        from_exec_flag, current_exec_flag) != "continue":
                return

        if to_exec_flag is not None:
            current_mode = os.stat(filename).st_mode
            if to_exec_flag:
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
            try:
                os.chmod(filename, to_mode)
            except IOError, e:
                if e.errno == errno.ENOENT:
                    conflict_handler.missing_for_exec_flag(filename)

    def __eq__(self, other):
        return (isinstance(other, ChangeExecFlag) and
                self.old_exec_flag == other.old_exec_flag and
                self.new_exec_flag == other.new_exec_flag)

    def __ne__(self, other):
        return not (self == other)


def dir_create(filename, conflict_handler, reverse):
    """Creates the directory, or deletes it if reverse is true.  Intended to be
    used with ReplaceContents.

    :param filename: The name of the directory to create
    :type filename: str
    :param reverse: If true, delete the directory, instead
    :type reverse: bool
    """
    if not reverse:
        try:
            os.mkdir(filename)
        except OSError, e:
            if e.errno != errno.EEXIST:
                raise
            if conflict_handler.dir_exists(filename) == "continue":
                os.mkdir(filename)
        except IOError, e:
            if e.errno == errno.ENOENT:
                if conflict_handler.missing_parent(filename)=="continue":
                    file(filename, "wb").write(self.contents)
    else:
        try:
            os.rmdir(filename)
        except OSError, e:
            if e.errno != errno.ENOTEMPTY:
                raise
            if conflict_handler.rmdir_non_empty(filename) == "skip":
                return
            os.rmdir(filename)


class SymlinkCreate(object):
    """Creates or deletes a symlink (for use with ReplaceContents)"""
    def __init__(self, contents):
        """Constructor.

        :param contents: The filename of the target the symlink should point to
        :type contents: str
        """
        self.target = contents

    def __repr__(self):
        return "SymlinkCreate(%s)" % self.target

    def __call__(self, filename, conflict_handler, reverse):
        """Creates or destroys the symlink.

        :param filename: The name of the symlink to create
        :type filename: str
        """
        if reverse:
            assert(os.readlink(filename) == self.target)
            os.unlink(filename)
        else:
            try:
                os.symlink(self.target, filename)
            except OSError, e:
                if e.errno != errno.EEXIST:
                    raise
                if conflict_handler.link_name_exists(filename) == "continue":
                    os.symlink(self.target, filename)

    def __eq__(self, other):
        if not isinstance(other, SymlinkCreate):
            return False
        elif self.target != other.target:
            return False
        else:
            return True

    def __ne__(self, other):
        return not (self == other)

class FileCreate(object):
    """Create or delete a file (for use with ReplaceContents)"""
    def __init__(self, contents):
        """Constructor

        :param contents: The contents of the file to write
        :type contents: str
        """
        self.contents = contents

    def __repr__(self):
        return "FileCreate(%i b)" % len(self.contents)

    def __eq__(self, other):
        if not isinstance(other, FileCreate):
            return False
        elif self.contents != other.contents:
            return False
        else:
            return True

    def __ne__(self, other):
        return not (self == other)

    def __call__(self, filename, conflict_handler, reverse):
        """Create or delete a file

        :param filename: The name of the file to create
        :type filename: str
        :param reverse: Delete the file instead of creating it
        :type reverse: bool
        """
        if not reverse:
            try:
                file(filename, "wb").write(self.contents)
            except IOError, e:
                if e.errno == errno.ENOENT:
                    if conflict_handler.missing_parent(filename)=="continue":
                        file(filename, "wb").write(self.contents)
                else:
                    raise

        else:
            try:
                if (file(filename, "rb").read() != self.contents):
                    direction = conflict_handler.wrong_old_contents(filename,
                                                                    self.contents)
                    if  direction != "continue":
                        return
                os.unlink(filename)
            except IOError, e:
                if e.errno != errno.ENOENT:
                    raise
                if conflict_handler.missing_for_rm(filename, undo) == "skip":
                    return

                    

class TreeFileCreate(object):
    """Create or delete a file (for use with ReplaceContents)"""
    def __init__(self, tree, file_id):
        """Constructor

        :param contents: The contents of the file to write
        :type contents: str
        """
        self.tree = tree
        self.file_id = file_id

    def __repr__(self):
        return "TreeFileCreate(%s)" % self.file_id

    def __eq__(self, other):
        if not isinstance(other, TreeFileCreate):
            return False
        return self.tree.get_file_sha1(self.file_id) == \
            other.tree.get_file_sha1(other.file_id)

    def __ne__(self, other):
        return not (self == other)

    def write_file(self, filename):
        outfile = file(filename, "wb")
        for line in self.tree.get_file(self.file_id):
            outfile.write(line)

    def same_text(self, filename):
        in_file = file(filename, "rb")
        return sha_file(in_file) == self.tree.get_file_sha1(self.file_id)

    def __call__(self, filename, conflict_handler, reverse):
        """Create or delete a file

        :param filename: The name of the file to create
        :type filename: str
        :param reverse: Delete the file instead of creating it
        :type reverse: bool
        """
        if not reverse:
            try:
                self.write_file(filename)
            except IOError, e:
                if e.errno == errno.ENOENT:
                    if conflict_handler.missing_parent(filename)=="continue":
                        self.write_file(filename)
                else:
                    raise

        else:
            try:
                if not self.same_text(filename):
                    direction = conflict_handler.wrong_old_contents(filename,
                        self.tree.get_file(self.file_id).read())
                    if  direction != "continue":
                        return
                os.unlink(filename)
            except IOError, e:
                if e.errno != errno.ENOENT:
                    raise
                if conflict_handler.missing_for_rm(filename, undo) == "skip":
                    return

                    

def reversed(sequence):
    max = len(sequence) - 1
    for i in range(len(sequence)):
        yield sequence[max - i]

class ReplaceContents(object):
    """A contents-replacement framework.  It allows a file/directory/symlink to
    be created, deleted, or replaced with another file/directory/symlink.
    Arguments must be callable with (filename, reverse).
    """
    def __init__(self, old_contents, new_contents):
        """Constructor.

        :param old_contents: The change to reverse apply (e.g. a deletion), \
        when going forwards.
        :type old_contents: `dir_create`, `SymlinkCreate`, `FileCreate`, \
        NoneType, etc.
        :param new_contents: The second change to apply (e.g. a creation), \
        when going forwards.
        :type new_contents: `dir_create`, `SymlinkCreate`, `FileCreate`, \
        NoneType, etc.
        """
        self.old_contents=old_contents
        self.new_contents=new_contents

    def __repr__(self):
        return "ReplaceContents(%r -> %r)" % (self.old_contents,
                                              self.new_contents)

    def __eq__(self, other):
        if not isinstance(other, ReplaceContents):
            return False
        elif self.old_contents != other.old_contents:
            return False
        elif self.new_contents != other.new_contents:
            return False
        else:
            return True
    def __ne__(self, other):
        return not (self == other)

    def apply(self, filename, conflict_handler, reverse=False):
        """Applies the FileReplacement to the specified filename

        :param filename: The name of the file to apply changes to
        :type filename: str
        :param reverse: If true, apply the change in reverse
        :type reverse: bool
        """
        if not reverse:
            undo = self.old_contents
            perform = self.new_contents
        else:
            undo = self.new_contents
            perform = self.old_contents
        mode = None
        if undo is not None:
            try:
                mode = os.lstat(filename).st_mode
                if stat.S_ISLNK(mode):
                    mode = None
            except OSError, e:
                if e.errno != errno.ENOENT:
                    raise
                if conflict_handler.missing_for_rm(filename, undo) == "skip":
                    return
            undo(filename, conflict_handler, reverse=True)
        if perform is not None:
            perform(filename, conflict_handler, reverse=False)
            if mode is not None:
                os.chmod(filename, mode)

    def is_creation(self):
        return self.new_contents is not None and self.old_contents is None

    def is_deletion(self):
        return self.old_contents is not None and self.new_contents is None

class ApplySequence(object):
    def __init__(self, changes=None):
        self.changes = []
        if changes is not None:
            self.changes.extend(changes)

    def __eq__(self, other):
        if not isinstance(other, ApplySequence):
            return False
        elif len(other.changes) != len(self.changes):
            return False
        else:
            for i in range(len(self.changes)):
                if self.changes[i] != other.changes[i]:
                    return False
            return True

    def __ne__(self, other):
        return not (self == other)

    
    def apply(self, filename, conflict_handler, reverse=False):
        if not reverse:
            iter = self.changes
        else:
            iter = reversed(self.changes)
        for change in iter:
            change.apply(filename, conflict_handler, reverse)


class Diff3Merge(object):
    history_based = False
    def __init__(self, file_id, base, other):
        self.file_id = file_id
        self.base = base
        self.other = other

    def is_creation(self):
        return False

    def is_deletion(self):
        return False

    def __eq__(self, other):
        if not isinstance(other, Diff3Merge):
            return False
        return (self.base == other.base and 
                self.other == other.other and self.file_id == other.file_id)

    def __ne__(self, other):
        return not (self == other)

    def dump_file(self, temp_dir, name, tree):
        out_path = os.path.join(temp_dir, name)
        out_file = file(out_path, "wb")
        in_file = tree.get_file(self.file_id)
        for line in in_file:
            out_file.write(line)
        return out_path

    def apply(self, filename, conflict_handler, reverse=False):
        import bzrlib.patch
        temp_dir = mkdtemp(prefix="bzr-")
        try:
            new_file = filename+".new"
            base_file = self.dump_file(temp_dir, "base", self.base)
            other_file = self.dump_file(temp_dir, "other", self.other)
            if not reverse:
                base = base_file
                other = other_file
            else:
                base = other_file
                other = base_file
            status = bzrlib.patch.diff3(new_file, filename, base, other)
            if status == 0:
                os.chmod(new_file, os.stat(filename).st_mode)
                rename(new_file, filename)
                return
            else:
                assert(status == 1)
                def get_lines(filename):
                    my_file = file(filename, "rb")
                    lines = my_file.readlines()
                    my_file.close()
                    return lines
                base_lines = get_lines(base)
                other_lines = get_lines(other)
                conflict_handler.merge_conflict(new_file, filename, base_lines, 
                                                other_lines)
        finally:
            rmtree(temp_dir)


def CreateDir():
    """Convenience function to create a directory.

    :return: A ReplaceContents that will create a directory
    :rtype: `ReplaceContents`
    """
    return ReplaceContents(None, dir_create)

def DeleteDir():
    """Convenience function to delete a directory.

    :return: A ReplaceContents that will delete a directory
    :rtype: `ReplaceContents`
    """
    return ReplaceContents(dir_create, None)

def CreateFile(contents):
    """Convenience fucntion to create a file.
    
    :param contents: The contents of the file to create 
    :type contents: str
    :return: A ReplaceContents that will create a file 
    :rtype: `ReplaceContents`
    """
    return ReplaceContents(None, FileCreate(contents))

def DeleteFile(contents):
    """Convenience fucntion to delete a file.
    
    :param contents: The contents of the file to delete
    :type contents: str
    :return: A ReplaceContents that will delete a file 
    :rtype: `ReplaceContents`
    """
    return ReplaceContents(FileCreate(contents), None)

def ReplaceFileContents(old_tree, new_tree, file_id):
    """Convenience fucntion to replace the contents of a file.
    
    :param old_contents: The contents of the file to replace 
    :type old_contents: str
    :param new_contents: The contents to replace the file with
    :type new_contents: str
    :return: A ReplaceContents that will replace the contents of a file a file 
    :rtype: `ReplaceContents`
    """
    return ReplaceContents(TreeFileCreate(old_tree, file_id), 
                           TreeFileCreate(new_tree, file_id))

def CreateSymlink(target):
    """Convenience fucntion to create a symlink.
    
    :param target: The path the link should point to
    :type target: str
    :return: A ReplaceContents that will delete a file 
    :rtype: `ReplaceContents`
    """
    return ReplaceContents(None, SymlinkCreate(target))

def DeleteSymlink(target):
    """Convenience fucntion to delete a symlink.
    
    :param target: The path the link should point to
    :type target: str
    :return: A ReplaceContents that will delete a file 
    :rtype: `ReplaceContents`
    """
    return ReplaceContents(SymlinkCreate(target), None)

def ChangeTarget(old_target, new_target):
    """Convenience fucntion to change the target of a symlink.
    
    :param old_target: The current link target
    :type old_target: str
    :param new_target: The new link target to use
    :type new_target: str
    :return: A ReplaceContents that will delete a file 
    :rtype: `ReplaceContents`
    """
    return ReplaceContents(SymlinkCreate(old_target), SymlinkCreate(new_target))


class InvalidEntry(Exception):
    """Raise when a ChangesetEntry is invalid in some way"""
    def __init__(self, entry, problem):
        """Constructor.

        :param entry: The invalid ChangesetEntry
        :type entry: `ChangesetEntry`
        :param problem: The problem with the entry
        :type problem: str
        """
        msg = "Changeset entry for %s (%s) is invalid.\n%s" % (entry.id, 
                                                               entry.path, 
                                                               problem)
        Exception.__init__(self, msg)
        self.entry = entry


class SourceRootHasName(InvalidEntry):
    """This changeset entry has a name other than "", but its parent is !NULL"""
    def __init__(self, entry, name):
        """Constructor.

        :param entry: The invalid ChangesetEntry
        :type entry: `ChangesetEntry`
        :param name: The name of the entry
        :type name: str
        """
        msg = 'Child of !NULL is named "%s", not "./.".' % name
        InvalidEntry.__init__(self, entry, msg)

class NullIDAssigned(InvalidEntry):
    """The id !NULL was assigned to a real entry"""
    def __init__(self, entry):
        """Constructor.

        :param entry: The invalid ChangesetEntry
        :type entry: `ChangesetEntry`
        """
        msg = '"!NULL" id assigned to a file "%s".' % entry.path
        InvalidEntry.__init__(self, entry, msg)

class ParentIDIsSelf(InvalidEntry):
    """An entry is marked as its own parent"""
    def __init__(self, entry):
        """Constructor.

        :param entry: The invalid ChangesetEntry
        :type entry: `ChangesetEntry`
        """
        msg = 'file %s has "%s" id for both self id and parent id.' % \
            (entry.path, entry.id)
        InvalidEntry.__init__(self, entry, msg)

class ChangesetEntry(object):
    """An entry the changeset"""
    def __init__(self, id, parent, path):
        """Constructor. Sets parent and name assuming it was not
        renamed/created/deleted.
        :param id: The id associated with the entry
        :param parent: The id of the parent of this entry (or !NULL if no
        parent)
        :param path: The file path relative to the tree root of this entry
        """
        self.id = id
        self.path = path 
        self.new_path = path
        self.parent = parent
        self.new_parent = parent
        self.contents_change = None
        self.metadata_change = None
        if parent == NULL_ID and path !='./.':
            raise SourceRootHasName(self, path)
        if self.id == NULL_ID:
            raise NullIDAssigned(self)
        if self.id  == self.parent:
            raise ParentIDIsSelf(self)

    def __str__(self):
        return "ChangesetEntry(%s)" % self.id

    def __get_dir(self):
        if self.path is None:
            return None
        return os.path.dirname(self.path)

    def __set_dir(self, dir):
        self.path = os.path.join(dir, os.path.basename(self.path))

    dir = property(__get_dir, __set_dir)
    
    def __get_name(self):
        if self.path is None:
            return None
        return os.path.basename(self.path)

    def __set_name(self, name):
        self.path = os.path.join(os.path.dirname(self.path), name)

    name = property(__get_name, __set_name)

    def __get_new_dir(self):
        if self.new_path is None:
            return None
        return os.path.dirname(self.new_path)

    def __set_new_dir(self, dir):
        self.new_path = os.path.join(dir, os.path.basename(self.new_path))

    new_dir = property(__get_new_dir, __set_new_dir)

    def __get_new_name(self):
        if self.new_path is None:
            return None
        return os.path.basename(self.new_path)

    def __set_new_name(self, name):
        self.new_path = os.path.join(os.path.dirname(self.new_path), name)

    new_name = property(__get_new_name, __set_new_name)

    def needs_rename(self):
        """Determines whether the entry requires renaming.

        :rtype: bool
        """

        return (self.parent != self.new_parent or self.name != self.new_name)

    def is_deletion(self, reverse):
        """Return true if applying the entry would delete a file/directory.

        :param reverse: if true, the changeset is being applied in reverse
        :rtype: bool
        """
        return self.is_creation(not reverse)

    def is_creation(self, reverse):
        """Return true if applying the entry would create a file/directory.

        :param reverse: if true, the changeset is being applied in reverse
        :rtype: bool
        """
        if self.contents_change is None:
            return False
        if reverse:
            return self.contents_change.is_deletion()
        else:
            return self.contents_change.is_creation()

    def is_creation_or_deletion(self):
        """Return true if applying the entry would create or delete a 
        file/directory.

        :rtype: bool
        """
        return self.is_creation(False) or self.is_deletion(False)

    def get_cset_path(self, mod=False):
        """Determine the path of the entry according to the changeset.

        :param changeset: The changeset to derive the path from
        :type changeset: `Changeset`
        :param mod: If true, generate the MOD path.  Otherwise, generate the \
        ORIG path.
        :return: the path of the entry, or None if it did not exist in the \
        requested tree.
        :rtype: str or NoneType
        """
        if mod:
            if self.new_parent == NULL_ID:
                return "./."
            elif self.new_parent is None:
                return None
            return self.new_path
        else:
            if self.parent == NULL_ID:
                return "./."
            elif self.parent is None:
                return None
            return self.path

    def summarize_name(self, reverse=False):
        """Produce a one-line summary of the filename.  Indicates renames as
        old => new, indicates creation as None => new, indicates deletion as
        old => None.

        :param changeset: The changeset to get paths from
        :type changeset: `Changeset`
        :param reverse: If true, reverse the names in the output
        :type reverse: bool
        :rtype: str
        """
        orig_path = self.get_cset_path(False)
        mod_path = self.get_cset_path(True)
        if orig_path is not None:
            orig_path = orig_path[2:]
        if mod_path is not None:
            mod_path = mod_path[2:]
        if orig_path == mod_path:
            return orig_path
        else:
            if not reverse:
                return "%s => %s" % (orig_path, mod_path)
            else:
                return "%s => %s" % (mod_path, orig_path)


    def get_new_path(self, id_map, changeset, reverse=False):
        """Determine the full pathname to rename to

        :param id_map: The map of ids to filenames for the tree
        :type id_map: Dictionary
        :param changeset: The changeset to get data from
        :type changeset: `Changeset`
        :param reverse: If true, we're applying the changeset in reverse
        :type reverse: bool
        :rtype: str
        """
        mutter("Finding new path for %s", self.summarize_name())
        if reverse:
            parent = self.parent
            to_dir = self.dir
            from_dir = self.new_dir
            to_name = self.name
            from_name = self.new_name
        else:
            parent = self.new_parent
            to_dir = self.new_dir
            from_dir = self.dir
            to_name = self.new_name
            from_name = self.name

        if to_name is None:
            return None

        if parent == NULL_ID or parent is None:
            if to_name != '.':
                raise SourceRootHasName(self, to_name)
            else:
                return '.'
        if from_dir == to_dir:
            dir = os.path.dirname(id_map[self.id])
        else:
            mutter("path, new_path: %r %r", self.path, self.new_path)
            parent_entry = changeset.entries[parent]
            dir = parent_entry.get_new_path(id_map, changeset, reverse)
        if from_name == to_name:
            name = os.path.basename(id_map[self.id])
        else:
            name = to_name
            assert(from_name is None or from_name == os.path.basename(id_map[self.id]))
        return os.path.join(dir, name)

    def is_boring(self):
        """Determines whether the entry does nothing
        
        :return: True if the entry does no renames or content changes
        :rtype: bool
        """
        if self.contents_change is not None:
            return False
        elif self.metadata_change is not None:
            return False
        elif self.parent != self.new_parent:
            return False
        elif self.name != self.new_name:
            return False
        else:
            return True

    def apply(self, filename, conflict_handler, reverse=False):
        """Applies the file content and/or metadata changes.

        :param filename: the filename of the entry
        :type filename: str
        :param reverse: If true, apply the changes in reverse
        :type reverse: bool
        """
        if self.is_deletion(reverse) and self.metadata_change is not None:
            self.metadata_change.apply(filename, conflict_handler, reverse)
        if self.contents_change is not None:
            self.contents_change.apply(filename, conflict_handler, reverse)
        if not self.is_deletion(reverse) and self.metadata_change is not None:
            self.metadata_change.apply(filename, conflict_handler, reverse)

class IDPresent(Exception):
    def __init__(self, id):
        msg = "Cannot add entry because that id has already been used:\n%s" %\
            id
        Exception.__init__(self, msg)
        self.id = id

class Changeset(object):
    """A set of changes to apply"""
    def __init__(self, base_id=None, target_id=None):
        self.base_id = base_id
        self.target_id = target_id
        self.entries = {}

    def add_entry(self, entry):
        """Add an entry to the list of entries"""
        if self.entries.has_key(entry.id):
            raise IDPresent(entry.id)
        self.entries[entry.id] = entry

def my_sort(sequence, key, reverse=False):
    """A sort function that supports supplying a key for comparison
    
    :param sequence: The sequence to sort
    :param key: A callable object that returns the values to be compared
    :param reverse: If true, sort in reverse order
    :type reverse: bool
    """
    def cmp_by_key(entry_a, entry_b):
        if reverse:
            tmp=entry_a
            entry_a = entry_b
            entry_b = tmp
        return cmp(key(entry_a), key(entry_b))
    sequence.sort(cmp_by_key)

def get_rename_entries(changeset, inventory, reverse):
    """Return a list of entries that will be renamed.  Entries are sorted from
    longest to shortest source path and from shortest to longest target path.

    :param changeset: The changeset to look in
    :type changeset: `Changeset`
    :param inventory: The source of current tree paths for the given ids
    :type inventory: Dictionary
    :param reverse: If true, the changeset is being applied in reverse
    :type reverse: bool
    :return: source entries and target entries as a tuple
    :rtype: (List, List)
    """
    source_entries = [x for x in changeset.entries.itervalues() 
                      if x.needs_rename() or x.is_creation_or_deletion()]
    # these are done from longest path to shortest, to avoid deleting a
    # parent before its children are deleted/renamed 
    def longest_to_shortest(entry):
        path = inventory.get(entry.id)
        if path is None:
            return 0
        else:
            return len(path)
    my_sort(source_entries, longest_to_shortest, reverse=True)

    target_entries = source_entries[:]
    # These are done from shortest to longest path, to avoid creating a
    # child before its parent has been created/renamed
    def shortest_to_longest(entry):
        path = entry.get_new_path(inventory, changeset, reverse)
        if path is None:
            return 0
        else:
            return len(path)
    my_sort(target_entries, shortest_to_longest)
    return (source_entries, target_entries)

def rename_to_temp_delete(source_entries, inventory, dir, temp_dir, 
                          conflict_handler, reverse):
    """Delete and rename entries as appropriate.  Entries are renamed to temp
    names.  A map of id -> temp name (or None, for deletions) is returned.

    :param source_entries: The entries to rename and delete
    :type source_entries: List of `ChangesetEntry`
    :param inventory: The map of id -> filename in the current tree
    :type inventory: Dictionary
    :param dir: The directory to apply changes to
    :type dir: str
    :param reverse: Apply changes in reverse
    :type reverse: bool
    :return: a mapping of id to temporary name
    :rtype: Dictionary
    """
    temp_name = {}
    for i in range(len(source_entries)):
        entry = source_entries[i]
        if entry.is_deletion(reverse):
            path = os.path.join(dir, inventory[entry.id])
            entry.apply(path, conflict_handler, reverse)
            temp_name[entry.id] = None

        elif entry.needs_rename():
            to_name = os.path.join(temp_dir, str(i))
            src_path = inventory.get(entry.id)
            if src_path is not None:
                src_path = os.path.join(dir, src_path)
                try:
                    rename(src_path, to_name)
                    temp_name[entry.id] = to_name
                except OSError, e:
                    if e.errno != errno.ENOENT:
                        raise
                    if conflict_handler.missing_for_rename(src_path, to_name) \
                        == "skip":
                        continue

    return temp_name


def rename_to_new_create(changed_inventory, target_entries, inventory, 
                         changeset, dir, conflict_handler, reverse):
    """Rename entries with temp names to their final names, create new files.

    :param changed_inventory: A mapping of id to temporary name
    :type changed_inventory: Dictionary
    :param target_entries: The entries to apply changes to
    :type target_entries: List of `ChangesetEntry`
    :param changeset: The changeset to apply
    :type changeset: `Changeset`
    :param dir: The directory to apply changes to
    :type dir: str
    :param reverse: If true, apply changes in reverse
    :type reverse: bool
    """
    for entry in target_entries:
        new_tree_path = entry.get_new_path(inventory, changeset, reverse)
        if new_tree_path is None:
            continue
        new_path = os.path.join(dir, new_tree_path)
        old_path = changed_inventory.get(entry.id)
        if bzrlib.osutils.lexists(new_path):
            if conflict_handler.target_exists(entry, new_path, old_path) == \
                "skip":
                continue
        if entry.is_creation(reverse):
            entry.apply(new_path, conflict_handler, reverse)
            changed_inventory[entry.id] = new_tree_path
        elif entry.needs_rename():
            if old_path is None:
                continue
            try:
                rename(old_path, new_path)
                changed_inventory[entry.id] = new_tree_path
            except OSError, e:
                raise Exception ("%s is missing" % new_path)

class TargetExists(Exception):
    def __init__(self, entry, target):
        msg = "The path %s already exists" % target
        Exception.__init__(self, msg)
        self.entry = entry
        self.target = target

class RenameConflict(Exception):
    def __init__(self, id, this_name, base_name, other_name):
        msg = """Trees all have different names for a file
 this: %s
 base: %s
other: %s
   id: %s""" % (this_name, base_name, other_name, id)
        Exception.__init__(self, msg)
        self.this_name = this_name
        self.base_name = base_name
        self_other_name = other_name

class MoveConflict(Exception):
    def __init__(self, id, this_parent, base_parent, other_parent):
        msg = """The file is in different directories in every tree
 this: %s
 base: %s
other: %s
   id: %s""" % (this_parent, base_parent, other_parent, id)
        Exception.__init__(self, msg)
        self.this_parent = this_parent
        self.base_parent = base_parent
        self_other_parent = other_parent

class MergeConflict(Exception):
    def __init__(self, this_path):
        Exception.__init__(self, "Conflict applying changes to %s" % this_path)
        self.this_path = this_path

class WrongOldContents(Exception):
    def __init__(self, filename):
        msg = "Contents mismatch deleting %s" % filename
        self.filename = filename
        Exception.__init__(self, msg)

class WrongOldExecFlag(Exception):
    def __init__(self, filename, old_exec_flag, new_exec_flag):
        msg = "Executable flag missmatch on %s:\n" \
        "Expected %s, got %s." % (filename, old_exec_flag, new_exec_flag)
        self.filename = filename
        Exception.__init__(self, msg)

class RemoveContentsConflict(Exception):
    def __init__(self, filename):
        msg = "Conflict deleting %s, which has different contents in BASE"\
            " and THIS" % filename
        self.filename = filename
        Exception.__init__(self, msg)

class DeletingNonEmptyDirectory(Exception):
    def __init__(self, filename):
        msg = "Trying to remove dir %s while it still had files" % filename
        self.filename = filename
        Exception.__init__(self, msg)


class PatchTargetMissing(Exception):
    def __init__(self, filename):
        msg = "Attempt to patch %s, which does not exist" % filename
        Exception.__init__(self, msg)
        self.filename = filename

class MissingForSetExec(Exception):
    def __init__(self, filename):
        msg = "Attempt to change permissions on  %s, which does not exist" %\
            filename
        Exception.__init__(self, msg)
        self.filename = filename

class MissingForRm(Exception):
    def __init__(self, filename):
        msg = "Attempt to remove missing path %s" % filename
        Exception.__init__(self, msg)
        self.filename = filename


class MissingForRename(Exception):
    def __init__(self, filename, to_path):
        msg = "Attempt to move missing path %s to %s" % (filename, to_path)
        Exception.__init__(self, msg)
        self.filename = filename

class NewContentsConflict(Exception):
    def __init__(self, filename):
        msg = "Conflicting contents for new file %s" % (filename)
        Exception.__init__(self, msg)

class WeaveMergeConflict(Exception):
    def __init__(self, filename):
        msg = "Conflicting contents for file %s" % (filename)
        Exception.__init__(self, msg)

class ThreewayContentsConflict(Exception):
    def __init__(self, filename):
        msg = "Conflicting contents for file %s" % (filename)
        Exception.__init__(self, msg)


class MissingForMerge(Exception):
    def __init__(self, filename):
        msg = "The file %s was modified, but does not exist in this tree"\
            % (filename)
        Exception.__init__(self, msg)


class ExceptionConflictHandler(object):
    """Default handler for merge exceptions.

    This throws an error on any kind of conflict.  Conflict handlers can
    descend from this class if they have a better way to handle some or
    all types of conflict.
    """
    def missing_parent(self, pathname):
        parent = os.path.dirname(pathname)
        raise Exception("Parent directory missing for %s" % pathname)

    def dir_exists(self, pathname):
        raise Exception("Directory already exists for %s" % pathname)

    def failed_hunks(self, pathname):
        raise Exception("Failed to apply some hunks for %s" % pathname)

    def target_exists(self, entry, target, old_path):
        raise TargetExists(entry, target)

    def rename_conflict(self, id, this_name, base_name, other_name):
        raise RenameConflict(id, this_name, base_name, other_name)

    def move_conflict(self, id, this_dir, base_dir, other_dir):
        raise MoveConflict(id, this_dir, base_dir, other_dir)

    def merge_conflict(self, new_file, this_path, base_lines, other_lines):
        os.unlink(new_file)
        raise MergeConflict(this_path)

    def wrong_old_contents(self, filename, expected_contents):
        raise WrongOldContents(filename)

    def rem_contents_conflict(self, filename, this_contents, base_contents):
        raise RemoveContentsConflict(filename)

    def wrong_old_exec_flag(self, filename, old_exec_flag, new_exec_flag):
        raise WrongOldExecFlag(filename, old_exec_flag, new_exec_flag)

    def rmdir_non_empty(self, filename):
        raise DeletingNonEmptyDirectory(filename)

    def link_name_exists(self, filename):
        raise TargetExists(filename)

    def patch_target_missing(self, filename, contents):
        raise PatchTargetMissing(filename)

    def missing_for_exec_flag(self, filename):
        raise MissingForExecFlag(filename)

    def missing_for_rm(self, filename, change):
        raise MissingForRm(filename)

    def missing_for_rename(self, filename, to_path):
        raise MissingForRename(filename, to_path)

    def missing_for_merge(self, file_id, other_path):
        raise MissingForMerge(other_path)

    def new_contents_conflict(self, filename, other_contents):
        raise NewContentsConflict(filename)

    def weave_merge_conflict(self, filename, weave, other_i, out_file):
        raise WeaveMergeConflict(filename)
 
    def threeway_contents_conflict(self, filename, this_contents,
                                   base_contents, other_contents):
        raise ThreewayContentsConflict(filename)

    def finalize(self):
        pass

def apply_changeset(changeset, inventory, dir, conflict_handler=None, 
                    reverse=False):
    """Apply a changeset to a directory.

    :param changeset: The changes to perform
    :type changeset: `Changeset`
    :param inventory: The mapping of id to filename for the directory
    :type inventory: Dictionary
    :param dir: The path of the directory to apply the changes to
    :type dir: str
    :param reverse: If true, apply the changes in reverse
    :type reverse: bool
    :return: The mapping of the changed entries
    :rtype: Dictionary
    """
    if conflict_handler is None:
        conflict_handler = ExceptionConflictHandler()
    temp_dir = os.path.join(dir, "bzr-tree-change")
    try:
        os.mkdir(temp_dir)
    except OSError, e:
        if e.errno == errno.EEXIST:
            try:
                os.rmdir(temp_dir)
            except OSError, e:
                if e.errno == errno.ENOTEMPTY:
                    raise OldFailedTreeOp()
            os.mkdir(temp_dir)
        else:
            raise
    
    #apply changes that don't affect filenames
    for entry in changeset.entries.itervalues():
        if not entry.is_creation_or_deletion() and not entry.is_boring():
            if entry.id not in inventory:
                warning("entry {%s} no longer present, can't be updated",
                        entry.id)
                continue
            path = os.path.join(dir, inventory[entry.id])
            entry.apply(path, conflict_handler, reverse)

    # Apply renames in stages, to minimize conflicts:
    # Only files whose name or parent change are interesting, because their
    # target name may exist in the source tree.  If a directory's name changes,
    # that doesn't make its children interesting.
    (source_entries, target_entries) = get_rename_entries(changeset, inventory,
                                                          reverse)

    changed_inventory = rename_to_temp_delete(source_entries, inventory, dir,
                                              temp_dir, conflict_handler,
                                              reverse)

    rename_to_new_create(changed_inventory, target_entries, inventory,
                         changeset, dir, conflict_handler, reverse)
    os.rmdir(temp_dir)
    return changed_inventory


def apply_changeset_tree(cset, tree, reverse=False):
    r_inventory = {}
    for entry in tree.source_inventory().itervalues():
        inventory[entry.id] = entry.path
    new_inventory = apply_changeset(cset, r_inventory, tree.basedir,
                                    reverse=reverse)
    new_entries, remove_entries = \
        get_inventory_change(inventory, new_inventory, cset, reverse)
    tree.update_source_inventory(new_entries, remove_entries)


def get_inventory_change(inventory, new_inventory, cset, reverse=False):
    new_entries = {}
    remove_entries = []
    for entry in cset.entries.itervalues():
        if entry.needs_rename():
            new_path = entry.get_new_path(inventory, cset)
            if new_path is None:
                remove_entries.append(entry.id)
            else:
                new_entries[new_path] = entry.id
    return new_entries, remove_entries


def print_changeset(cset):
    """Print all non-boring changeset entries
    
    :param cset: The changeset to print
    :type cset: `Changeset`
    """
    for entry in cset.entries.itervalues():
        if entry.is_boring():
            continue
        print entry.id
        print entry.summarize_name(cset)

class CompositionFailure(Exception):
    def __init__(self, old_entry, new_entry, problem):
        msg = "Unable to conpose entries.\n %s" % problem
        Exception.__init__(self, msg)

class IDMismatch(CompositionFailure):
    def __init__(self, old_entry, new_entry):
        problem = "Attempt to compose entries with different ids: %s and %s" %\
            (old_entry.id, new_entry.id)
        CompositionFailure.__init__(self, old_entry, new_entry, problem)

def compose_changesets(old_cset, new_cset):
    """Combine two changesets into one.  This works well for exact patching.
    Otherwise, not so well.

    :param old_cset: The first changeset that would be applied
    :type old_cset: `Changeset`
    :param new_cset: The second changeset that would be applied
    :type new_cset: `Changeset`
    :return: A changeset that combines the changes in both changesets
    :rtype: `Changeset`
    """
    composed = Changeset()
    for old_entry in old_cset.entries.itervalues():
        new_entry = new_cset.entries.get(old_entry.id)
        if new_entry is None:
            composed.add_entry(old_entry)
        else:
            composed_entry = compose_entries(old_entry, new_entry)
            if composed_entry.parent is not None or\
                composed_entry.new_parent is not None:
                composed.add_entry(composed_entry)
    for new_entry in new_cset.entries.itervalues():
        if not old_cset.entries.has_key(new_entry.id):
            composed.add_entry(new_entry)
    return composed

def compose_entries(old_entry, new_entry):
    """Combine two entries into one.

    :param old_entry: The first entry that would be applied
    :type old_entry: ChangesetEntry
    :param old_entry: The second entry that would be applied
    :type old_entry: ChangesetEntry
    :return: A changeset entry combining both entries
    :rtype: `ChangesetEntry`
    """
    if old_entry.id != new_entry.id:
        raise IDMismatch(old_entry, new_entry)
    output = ChangesetEntry(old_entry.id, old_entry.parent, old_entry.path)

    if (old_entry.parent != old_entry.new_parent or 
        new_entry.parent != new_entry.new_parent):
        output.new_parent = new_entry.new_parent

    if (old_entry.path != old_entry.new_path or 
        new_entry.path != new_entry.new_path):
        output.new_path = new_entry.new_path

    output.contents_change = compose_contents(old_entry, new_entry)
    output.metadata_change = compose_metadata(old_entry, new_entry)
    return output

def compose_contents(old_entry, new_entry):
    """Combine the contents of two changeset entries.  Entries are combined
    intelligently where possible, but the fallback behavior returns an 
    ApplySequence.

    :param old_entry: The first entry that would be applied
    :type old_entry: `ChangesetEntry`
    :param new_entry: The second entry that would be applied
    :type new_entry: `ChangesetEntry`
    :return: A combined contents change
    :rtype: anything supporting the apply(reverse=False) method
    """
    old_contents = old_entry.contents_change
    new_contents = new_entry.contents_change
    if old_entry.contents_change is None:
        return new_entry.contents_change
    elif new_entry.contents_change is None:
        return old_entry.contents_change
    elif isinstance(old_contents, ReplaceContents) and \
        isinstance(new_contents, ReplaceContents):
        if old_contents.old_contents == new_contents.new_contents:
            return None
        else:
            return ReplaceContents(old_contents.old_contents,
                                   new_contents.new_contents)
    elif isinstance(old_contents, ApplySequence):
        output = ApplySequence(old_contents.changes)
        if isinstance(new_contents, ApplySequence):
            output.changes.extend(new_contents.changes)
        else:
            output.changes.append(new_contents)
        return output
    elif isinstance(new_contents, ApplySequence):
        output = ApplySequence((old_contents.changes,))
        output.extend(new_contents.changes)
        return output
    else:
        return ApplySequence((old_contents, new_contents))

def compose_metadata(old_entry, new_entry):
    old_meta = old_entry.metadata_change
    new_meta = new_entry.metadata_change
    if old_meta is None:
        return new_meta
    elif new_meta is None:
        return old_meta
    elif (isinstance(old_meta, ChangeExecFlag) and
          isinstance(new_meta, ChangeExecFlag)):
        return ChangeExecFlag(old_meta.old_exec_flag, new_meta.new_exec_flag)
    else:
        return ApplySequence(old_meta, new_meta)


def changeset_is_null(changeset):
    for entry in changeset.entries.itervalues():
        if not entry.is_boring():
            return False
    return True

class UnsupportedFiletype(Exception):
    def __init__(self, kind, full_path):
        msg = "The file \"%s\" is a %s, which is not a supported filetype." \
            % (full_path, kind)
        Exception.__init__(self, msg)
        self.full_path = full_path
        self.kind = kind

def generate_changeset(tree_a, tree_b, interesting_ids=None):
    return ChangesetGenerator(tree_a, tree_b, interesting_ids)()


class ChangesetGenerator(object):
    def __init__(self, tree_a, tree_b, interesting_ids=None):
        object.__init__(self)
        self.tree_a = tree_a
        self.tree_b = tree_b
        self._interesting_ids = interesting_ids

    def iter_both_tree_ids(self):
        for file_id in self.tree_a:
            yield file_id
        for file_id in self.tree_b:
            if file_id not in self.tree_a:
                yield file_id

    def __call__(self):
        base_id = hasattr(self.tree_a, 'get_revision_id') and self.tree_a.get_revision_id()
        target_id = hasattr(self.tree_b, 'get_revision_id') and self.tree_b.get_revision_id()
        cset = Changeset(base_id, target_id)
        for file_id in self.iter_both_tree_ids():
            cs_entry = self.make_entry(file_id)
            if cs_entry is not None and not cs_entry.is_boring():
                cset.add_entry(cs_entry)

        for entry in list(cset.entries.itervalues()):
            if entry.parent != entry.new_parent:
                if not cset.entries.has_key(entry.parent) and\
                    entry.parent != NULL_ID and entry.parent is not None:
                    parent_entry = self.make_boring_entry(entry.parent)
                    cset.add_entry(parent_entry)
                if not cset.entries.has_key(entry.new_parent) and\
                    entry.new_parent != NULL_ID and \
                    entry.new_parent is not None:
                    parent_entry = self.make_boring_entry(entry.new_parent)
                    cset.add_entry(parent_entry)
        return cset

    def iter_inventory(self, tree):
        for file_id in tree:
            yield self.get_entry(file_id, tree)

    def get_entry(self, file_id, tree):
        if not tree.has_or_had_id(file_id):
            return None
        return tree.inventory[file_id]

    def get_entry_parent(self, entry):
        if entry is None:
            return None
        return entry.parent_id

    def get_path(self, file_id, tree):
        if not tree.has_or_had_id(file_id):
            return None
        path = tree.id2path(file_id)
        if path == '':
            return './.'
        else:
            return path

    def make_basic_entry(self, file_id, only_interesting):
        entry_a = self.get_entry(file_id, self.tree_a)
        entry_b = self.get_entry(file_id, self.tree_b)
        if only_interesting and not self.is_interesting(entry_a, entry_b):
            return None
        parent = self.get_entry_parent(entry_a)
        path = self.get_path(file_id, self.tree_a)
        cs_entry = ChangesetEntry(file_id, parent, path)
        new_parent = self.get_entry_parent(entry_b)

        new_path = self.get_path(file_id, self.tree_b)

        cs_entry.new_path = new_path
        cs_entry.new_parent = new_parent
        return cs_entry

    def is_interesting(self, entry_a, entry_b):
        if self._interesting_ids is None:
            return True
        if entry_a is not None:
            file_id = entry_a.file_id
        elif entry_b is not None:
            file_id = entry_b.file_id
        else:
            return False
        return file_id in self._interesting_ids

    def make_boring_entry(self, id):
        cs_entry = self.make_basic_entry(id, only_interesting=False)
        if cs_entry.is_creation_or_deletion():
            return self.make_entry(id, only_interesting=False)
        else:
            return cs_entry
        

    def make_entry(self, id, only_interesting=True):
        cs_entry = self.make_basic_entry(id, only_interesting)

        if cs_entry is None:
            return None

        cs_entry.metadata_change = self.make_exec_flag_change(id)

        if id in self.tree_a and id in self.tree_b:
            a_sha1 = self.tree_a.get_file_sha1(id)
            b_sha1 = self.tree_b.get_file_sha1(id)
            if None not in (a_sha1, b_sha1) and a_sha1 == b_sha1:
                return cs_entry

        cs_entry.contents_change = self.make_contents_change(id)
        return cs_entry

    def make_exec_flag_change(self, file_id):
        exec_flag_a = exec_flag_b = None
        if file_id in self.tree_a and self.tree_a.kind(file_id) == "file":
            exec_flag_a = self.tree_a.is_executable(file_id)

        if file_id in self.tree_b and self.tree_b.kind(file_id) == "file":
            exec_flag_b = self.tree_b.is_executable(file_id)

        if exec_flag_a == exec_flag_b:
            return None
        return ChangeExecFlag(exec_flag_a, exec_flag_b)

    def make_contents_change(self, file_id):
        a_contents = get_contents(self.tree_a, file_id)
        b_contents = get_contents(self.tree_b, file_id)
        if a_contents == b_contents:
            return None
        return ReplaceContents(a_contents, b_contents)


def get_contents(tree, file_id):
    """Return the appropriate contents to create a copy of file_id from tree"""
    if file_id not in tree:
        return None
    kind = tree.kind(file_id)
    if kind == "file":
        return TreeFileCreate(tree, file_id)
    elif kind in ("directory", "root_directory"):
        return dir_create
    elif kind == "symlink":
        return SymlinkCreate(tree.get_symlink_target(file_id))
    else:
        raise UnsupportedFiletype(kind, tree.id2path(file_id))


def full_path(entry, tree):
    return os.path.join(tree.basedir, entry.path)

def new_delete_entry(entry, tree, inventory, delete):
    if entry.path == "":
        parent = NULL_ID
    else:
        parent = inventory[dirname(entry.path)].id
    cs_entry = ChangesetEntry(parent, entry.path)
    if delete:
        cs_entry.new_path = None
        cs_entry.new_parent = None
    else:
        cs_entry.path = None
        cs_entry.parent = None
    full_path = full_path(entry, tree)
    status = os.lstat(full_path)
    if stat.S_ISDIR(file_stat.st_mode):
        action = dir_create
    


        
# XXX: Can't we unify this with the regular inventory object
class Inventory(object):
    def __init__(self, inventory):
        self.inventory = inventory
        self.rinventory = None

    def get_rinventory(self):
        if self.rinventory is None:
            self.rinventory  = invert_dict(self.inventory)
        return self.rinventory

    def get_path(self, id):
        return self.inventory.get(id)

    def get_name(self, id):
        path = self.get_path(id)
        if path is None:
            return None
        else:
            return os.path.basename(path)

    def get_dir(self, id):
        path = self.get_path(id)
        if path == "":
            return None
        if path is None:
            return None
        return os.path.dirname(path)

    def get_parent(self, id):
        if self.get_path(id) is None:
            return None
        directory = self.get_dir(id)
        if directory == '.':
            directory = './.'
        if directory is None:
            return NULL_ID
        return self.get_rinventory().get(directory)
