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
import tempfile
import shutil
import errno
from fetch import greedy_fetch

import bzrlib.osutils
import bzrlib.revision
from bzrlib.merge_core import merge_flex, ApplyMerge3, BackupBeforeChange
from bzrlib.changeset import generate_changeset, ExceptionConflictHandler
from bzrlib.changeset import Inventory, Diff3Merge
from bzrlib.branch import Branch
from bzrlib.errors import BzrCommandError, UnrelatedBranches, NoCommonAncestor
from bzrlib.errors import NoCommits
from bzrlib.delta import compare_trees
from bzrlib.trace import mutter, warning
from bzrlib.fetch import greedy_fetch
from bzrlib.revision import is_ancestor
from bzrlib.osutils import rename


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
    def __init__(self, ignore_zero=False):
        ExceptionConflictHandler.__init__(self)
        self.conflicts = 0
        self.ignore_zero = ignore_zero

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

    def add_suffix(self, name, suffix, last_new_name=None):
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
            return new_name
        except OSError, e:
            if e.errno != errno.EEXIST and e.errno != errno.ENOTEMPTY:
                raise
            return self.add_suffix(name, suffix, last_new_name=new_name)

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
        self.add_suffix(this_path, ".THIS")
        self.dump(base_lines, this_path+".BASE")
        self.dump(other_lines, this_path+".OTHER")
        rename(new_file, this_path)
        self.conflict("Diff3 conflict encountered in %s" % this_path)

    def new_contents_conflict(self, filename, other_contents):
        """Conflicting contents for newly added file."""
        self.copy(other_contents, filename + ".OTHER")
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

    def finalize(self):
        if not self.ignore_zero:
            print "%d conflicts encountered.\n" % self.conflicts
            
def get_tree(treespec, temp_root, label, local_branch=None):
    location, revno = treespec
    branch = Branch.open_containing(location)
    if revno is None:
        revision = None
    elif revno == -1:
        revision = branch.last_patch()
    else:
        revision = branch.get_rev_id(revno)
    return branch, get_revid_tree(branch, revision, temp_root, label,
                                  local_branch)

def get_revid_tree(branch, revision, temp_root, label, local_branch):
    if revision is None:
        base_tree = branch.working_tree()
    else:
        if local_branch is not None:
            greedy_fetch(local_branch, branch, revision)
            base_tree = local_branch.revision_tree(revision)
        else:
            base_tree = branch.revision_tree(revision)
    temp_path = os.path.join(temp_root, label)
    os.mkdir(temp_path)
    return MergeTree(base_tree, temp_path)


def file_exists(tree, file_id):
    return tree.has_filename(tree.id2path(file_id))
    

class MergeTree(object):
    def __init__(self, tree, tempdir):
        object.__init__(self)
        if hasattr(tree, "basedir"):
            self.root = tree.basedir
        else:
            self.root = None
        self.tree = tree
        self.tempdir = tempdir
        os.mkdir(os.path.join(self.tempdir, "texts"))
        os.mkdir(os.path.join(self.tempdir, "symlinks"))
        self.cached = {}

    def __iter__(self):
        return self.tree.__iter__()

    def __contains__(self, file_id):
        return file_id in self.tree

    def get_file(self, file_id):
        return self.tree.get_file(file_id)

    def get_file_sha1(self, id):
        return self.tree.get_file_sha1(id)

    def id2path(self, file_id):
        return self.tree.id2path(file_id)

    def has_id(self, file_id):
        return self.tree.has_id(file_id)

    def has_or_had_id(self, file_id):
        if file_id == self.tree.inventory.root.file_id:
            return True
        return self.tree.inventory.has_id(file_id)

    def has_or_had_id(self, file_id):
        if file_id == self.tree.inventory.root.file_id:
            return True
        return self.tree.inventory.has_id(file_id)

    def readonly_path(self, id):
        if id not in self.tree:
            return None
        if self.root is not None:
            return self.tree.abspath(self.tree.id2path(id))
        else:
            kind = self.tree.inventory[id].kind
            if kind in ("directory", "root_directory"):
                return self.tempdir
            if not self.cached.has_key(id):
                if kind == "file":
                    path = os.path.join(self.tempdir, "texts", id)
                    outfile = file(path, "wb")
                    outfile.write(self.tree.get_file(id).read())
                    assert(os.path.exists(path))
                else:
                    assert kind == "symlink"
                    path = os.path.join(self.tempdir, "symlinks", id)
                    target = self.tree.get_symlink_target(id)
                    os.symlink(target, path)
                self.cached[id] = path
            return self.cached[id]



def merge(other_revision, base_revision,
          check_clean=True, ignore_zero=False,
          this_dir=None, backup_files=False, merge_type=ApplyMerge3,
          file_list=None):
    """Merge changes into a tree.

    base_revision
        tuple(path, revision) Base for three-way merge.
    other_revision
        tuple(path, revision) Other revision for three-way merge.
    this_dir
        Directory to merge changes into; '.' by default.
    check_clean
        If true, this_dir must have no uncommitted changes before the
        merge begins.
    all available ancestors of other_revision and base_revision are
    automatically pulled into the branch.
    """
    from bzrlib.revision import common_ancestor, MultipleRevisionSources
    from bzrlib.errors import NoSuchRevision
    tempdir = tempfile.mkdtemp(prefix="bzr-")
    try:
        if this_dir is None:
            this_dir = '.'
        this_branch = Branch.open_containing(this_dir)
        this_rev_id = this_branch.last_patch()
        if this_rev_id is None:
            raise BzrCommandError("This branch has no commits")
        if check_clean:
            changes = compare_trees(this_branch.working_tree(), 
                                    this_branch.basis_tree(), False)
            if changes.has_changed():
                raise BzrCommandError("Working tree has uncommitted changes.")
        other_branch, other_tree = get_tree(other_revision, tempdir, "other",
                                            this_branch)
        if other_revision[1] == -1:
            other_rev_id = other_branch.last_patch()
            if other_rev_id is None:
                raise NoCommits(other_branch)
            other_basis = other_rev_id
        elif other_revision[1] is not None:
            other_rev_id = other_branch.get_rev_id(other_revision[1])
            other_basis = other_rev_id
        else:
            other_rev_id = None
            other_basis = other_branch.last_patch()
            if other_basis is None:
                raise NoCommits(other_branch)
        if base_revision == [None, None]:
            try:
                base_rev_id = common_ancestor(this_rev_id, other_basis, 
                                              this_branch)
            except NoCommonAncestor:
                raise UnrelatedBranches()
            base_tree = get_revid_tree(this_branch, base_rev_id, tempdir, 
                                       "base", None)
            base_is_ancestor = True
        else:
            base_branch, base_tree = get_tree(base_revision, tempdir, "base")
            if base_revision[1] == -1:
                base_rev_id = base_branch.last_patch()
            elif base_revision[1] is None:
                base_rev_id = None
            else:
                base_rev_id = base_branch.get_rev_id(base_revision[1])
            multi_source = MultipleRevisionSources(this_branch, base_branch)
            base_is_ancestor = is_ancestor(this_rev_id, base_rev_id,
                                           multi_source)
        if file_list is None:
            interesting_ids = None
        else:
            interesting_ids = set()
            this_tree = this_branch.working_tree()
            for fname in file_list:
                path = this_branch.relpath(fname)
                found_id = False
                for tree in (this_tree, base_tree.tree, other_tree.tree):
                    file_id = tree.inventory.path2id(path)
                    if file_id is not None:
                        interesting_ids.add(file_id)
                        found_id = True
                if not found_id:
                    raise BzrCommandError("%s is not a source file in any"
                                          " tree." % fname)
        merge_inner(this_branch, other_tree, base_tree, tempdir, 
                    ignore_zero=ignore_zero, backup_files=backup_files, 
                    merge_type=merge_type, interesting_ids=interesting_ids)
        if base_is_ancestor and other_rev_id is not None\
            and other_rev_id not in this_branch.revision_history():
            this_branch.add_pending_merge(other_rev_id)
    finally:
        shutil.rmtree(tempdir)


def set_interesting(inventory_a, inventory_b, interesting_ids):
    """Mark files whose ids are in interesting_ids as interesting
    """
    for inventory in (inventory_a, inventory_b):
        for path, source_file in inventory.iteritems():
             source_file.interesting = source_file.id in interesting_ids


def generate_cset_optimized(tree_a, tree_b, interesting_ids=None):
    """Generate a changeset.  If interesting_ids is supplied, only changes
    to those files will be shown.  Metadata changes are stripped.
    """ 
    cset =  generate_changeset(tree_a, tree_b, interesting_ids)
    for entry in cset.entries.itervalues():
        entry.metadata_change = None
    return cset


def merge_inner(this_branch, other_tree, base_tree, tempdir, 
                ignore_zero=False, merge_type=ApplyMerge3, backup_files=False,
                interesting_ids=None):

    def merge_factory(file_id, base, other):
        contents_change = merge_type(file_id, base, other)
        if backup_files:
            contents_change = BackupBeforeChange(contents_change)
        return contents_change

    this_tree = get_tree((this_branch.base, None), tempdir, "this")[1]

    def get_inventory(tree):
        return tree.tree.inventory

    inv_changes = merge_flex(this_tree, base_tree, other_tree,
                             generate_cset_optimized, get_inventory,
                             MergeConflictHandler(ignore_zero=ignore_zero),
                             merge_factory=merge_factory, 
                             interesting_ids=interesting_ids)

    adjust_ids = []
    for id, path in inv_changes.iteritems():
        if path is not None:
            if path == '.':
                path = ''
            else:
                assert path.startswith('.' + os.sep), "path is %s" % path
            path = path[2:]
        adjust_ids.append((path, id))
    if len(adjust_ids) > 0:
        this_branch.set_inventory(regen_inventory(this_branch, this_tree.root,
                                                  adjust_ids))


def regen_inventory(this_branch, root, new_entries):
    old_entries = this_branch.read_working_inventory()
    new_inventory = {}
    by_path = {}
    new_entries_map = {} 
    for path, file_id in new_entries:
        if path is None:
            continue
        new_entries_map[file_id] = path

    def id2path(file_id):
        path = new_entries_map.get(file_id)
        if path is not None:
            return path
        entry = old_entries[file_id]
        if entry.parent_id is None:
            return entry.name
        return os.path.join(id2path(entry.parent_id), entry.name)
        
    for file_id in old_entries:
        entry = old_entries[file_id]
        path = id2path(file_id)
        new_inventory[file_id] = (path, file_id, entry.parent_id, entry.kind)
        by_path[path] = file_id
    
    deletions = 0
    insertions = 0
    new_path_list = []
    for path, file_id in new_entries:
        if path is None:
            del new_inventory[file_id]
            deletions += 1
        else:
            new_path_list.append((path, file_id))
            if file_id not in old_entries:
                insertions += 1
    # Ensure no file is added before its parent
    new_path_list.sort()
    for path, file_id in new_path_list:
        if path == '':
            parent = None
        else:
            parent = by_path[os.path.dirname(path)]
        kind = bzrlib.osutils.file_kind(os.path.join(root, path))
        new_inventory[file_id] = (path, file_id, parent, kind)
        by_path[path] = file_id 

    # Get a list in insertion order
    new_inventory_list = new_inventory.values()
    mutter ("""Inventory regeneration:
old length: %i insertions: %i deletions: %i new_length: %i"""\
        % (len(old_entries), insertions, deletions, len(new_inventory_list)))
    assert len(new_inventory_list) == len(old_entries) + insertions - deletions
    new_inventory_list.sort()
    return new_inventory_list

merge_types = {     "merge3": (ApplyMerge3, "Native diff3-style merge"), 
                     "diff3": (Diff3Merge,  "Merge using external diff3")
              }

