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


import os
import errno

import bzrlib.osutils
from bzrlib._changeset import ExceptionConflictHandler
from bzrlib._changeset import ReplaceContents
from bzrlib.errors import NotBranchError
from bzrlib.trace import warning, note
from bzrlib.osutils import rename, pathjoin

# TODO: Report back as changes are merged in

# comments from abentley on irc: merge happens in two stages, each
# of which generates a changeset object

# stage 1: generate OLD->OTHER,
# stage 2: use MINE and OLD->OTHER to generate MINE -> RESULT

class MergeConflictHandler(ExceptionConflictHandler):
    """Handle conflicts encountered while merging.

    This subclasses ExceptionConflictHandler, so that any types of
    conflict that are not explicitly handled cause an exception and
    terminate the merge.
    """
    def __init__(self, this_tree, base_tree, other_tree, ignore_zero=False):
        ExceptionConflictHandler.__init__(self)
        self.conflicts = 0
        self.ignore_zero = ignore_zero
        self.this_tree = this_tree
        self.base_tree = base_tree
        self.other_tree = other_tree

    def copy(self, source, dest):
        """Copy the text and mode of a file
        :param source: The path of the file to copy
        :param dest: The distination file to create
        """
        s_file = file(source, "rb")
        d_file = file(dest, "wb")
        for line in s_file:
            d_file.write(line)
        os.chmod(dest, 0777 & os.stat(source).st_mode)

    def dump(self, lines, dest):
        """Copy the text and mode of a file
        :param source: The path of the file to copy
        :param dest: The distination file to create
        """
        d_file = file(dest, "wb")
        for line in lines:
            d_file.write(line)

    def add_suffix(self, name, suffix, last_new_name=None, fix_inventory=True):
        """Rename a file to append a suffix.  If the new name exists, the
        suffix is added repeatedly until a non-existant name is found

        :param name: The path of the file
        :param suffix: The suffix to append
        :param last_new_name: (used for recursive calls) the last name tried
        """
        if last_new_name is None:
            last_new_name = name
        new_name = last_new_name+suffix
        try:
            rename(name, new_name)
            if fix_inventory is True:
                try:
                    relpath = self.this_tree.relpath(name)
                except NotBranchError:
                    relpath = None
                if relpath is not None:
                    file_id = self.this_tree.path2id(relpath)
                    if file_id is not None:
                        new_path = self.this_tree.relpath(new_name)
                        rename(new_name, name)
                        self.this_tree.rename_one(relpath, new_path)
                        assert self.this_tree.id2path(file_id) == new_path
        except OSError, e:
            if e.errno != errno.EEXIST and e.errno != errno.ENOTEMPTY:
                raise
            return self.add_suffix(name, suffix, last_new_name=new_name, 
                                   fix_inventory=fix_inventory)
        return new_name

    def conflict(self, text):
        warning(text)
        self.conflicts += 1
        

    def merge_conflict(self, new_file, this_path, base_lines, other_lines):
        """
        Handle diff3 conflicts by producing a .THIS, .BASE and .OTHER.  The
        main file will be a version with diff3 conflicts.
        :param new_file: Path to the output file with diff3 markers
        :param this_path: Path to the file text for the THIS tree
        :param base_path: Path to the file text for the BASE tree
        :param other_path: Path to the file text for the OTHER tree
        """
        self.add_suffix(this_path, ".THIS", fix_inventory=False)
        self.dump(base_lines, this_path+".BASE")
        self.dump(other_lines, this_path+".OTHER")
        rename(new_file, this_path)
        self.conflict("Diff3 conflict encountered in %s" % this_path)

    def weave_merge_conflict(self, filename, weave, other_i, out_file):
        """
        Handle weave conflicts by producing a .THIS, and .OTHER.  The
        main file will be a version with diff3-style conflicts.
        """
        self.add_suffix(filename, ".THIS", fix_inventory=False)
        out_file.commit()
        self.dump(weave.get_iter(other_i), filename+".OTHER")
        self.conflict("Text conflict encountered in %s" % filename)

    def new_contents_conflict(self, filename, other_contents):
        """Conflicting contents for newly added file."""
        other_contents(filename + ".OTHER", self, False)
        self.conflict("Conflict in newly added file %s" % filename)
    

    def target_exists(self, entry, target, old_path):
        """Handle the case when the target file or dir exists"""
        moved_path = self.add_suffix(target, ".moved")
        self.conflict("Moved existing %s to %s" % (target, moved_path))

    def rmdir_non_empty(self, filename):
        """Handle the case where the dir to be removed still has contents"""
        self.conflict("Directory %s not removed because it is not empty"\
            % filename)
        return "skip"

    def rem_contents_conflict(self, filename, this_contents, base_contents):
        base_contents(filename+".BASE", self)
        this_contents(filename+".THIS", self)
        self.conflict("Other branch deleted locally modified file %s" %
                      filename)
        return ReplaceContents(this_contents, None)

    def abs_this_path(self, file_id):
        """Return the absolute path for a file_id in the this tree."""
        return self.this_tree.id2abspath(file_id)

    def add_missing_parents(self, file_id, tree):
        """If some of the parents for file_id are missing, add them."""
        entry = tree.inventory[file_id]
        if entry.parent_id not in self.this_tree:
            return self.create_all_missing(entry.parent_id, tree)
        else:
            return self.abs_this_path(entry.parent_id)

    def create_all_missing(self, file_id, tree):
        """Add contents for a file_id and all its parents to a tree."""
        entry = tree.inventory[file_id]
        if entry.parent_id is not None and entry.parent_id not in self.this_tree:
            abspath = self.create_all_missing(entry.parent_id, tree)
        else:
            abspath = self.abs_this_path(entry.parent_id)
        entry_path = pathjoin(abspath, entry.name)
        if not os.path.isdir(entry_path):
            self.create(file_id, entry_path, tree)
        return entry_path

    def create(self, file_id, path, tree):
        """Uses tree data to create a filesystem object for the file_id"""
        from _changeset import get_contents
        get_contents(tree, file_id)(path, self)

    def missing_for_merge(self, file_id, other_path):
        """The file_id doesn't exist in THIS, but does in OTHER and BASE"""
        self.conflict("Other branch modified locally deleted file %s" %
                      other_path)
        parent_dir = self.add_missing_parents(file_id, self.other_tree)
        stem = pathjoin(parent_dir, os.path.basename(other_path))
        self.create(file_id, stem+".OTHER", self.other_tree)
        self.create(file_id, stem+".BASE", self.base_tree)

    def threeway_contents_conflict(filename, this_contents, base_contents,
                                   other_contents):
        self.conflict("Three-way conflict merging %s" % filename)

    def finalize(self):
        if self.conflicts == 0:
            if not self.ignore_zero:
                note("All changes applied successfully.")
        else:
            note("%d conflicts encountered." % self.conflicts)
