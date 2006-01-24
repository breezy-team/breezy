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

# TODO: build_working_dir can be built on something simpler than merge()

import os
import errno

import bzrlib
from bzrlib._changeset import generate_changeset, ExceptionConflictHandler
from bzrlib._changeset import Inventory, Diff3Merge, ReplaceContents
from bzrlib._merge_core import WeaveMerge
from bzrlib._merge_core import merge_flex, ApplyMerge3, BackupBeforeChange
from bzrlib.branch import Branch
from bzrlib.delta import compare_trees
from bzrlib.errors import (BzrCommandError,
                           NotBranchError,
                           UnrelatedBranches,
                           NoCommonAncestor,
                           NoCommits,
                           WorkingTreeNotRevision,
                           NotVersionedError,
                           BzrError)
from bzrlib.fetch import greedy_fetch, fetch
import bzrlib.osutils
from bzrlib.osutils import rename, pathjoin
from bzrlib.revision import common_ancestor, MultipleRevisionSources
from bzrlib.revision import is_ancestor, NULL_REVISION
from bzrlib.trace import mutter, warning, note

# TODO: Report back as changes are merged in

# comments from abentley on irc: merge happens in two stages, each
# of which generates a changeset object

# stage 1: generate OLD->OTHER,
# stage 2: use MINE and OLD->OTHER to generate MINE -> RESULT

class _MergeConflictHandler(ExceptionConflictHandler):
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
        from bzrlib._changeset import get_contents
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

def _get_tree(treespec, local_branch=None):
    location, revno = treespec
    branch = Branch.open_containing(location)[0]
    if revno is None:
        revision = None
    elif revno == -1:
        revision = branch.last_revision()
    else:
        revision = branch.get_rev_id(revno)
        if revision is None:
            revision = NULL_REVISION
    return branch, _get_revid_tree(branch, revision, local_branch)


def _get_revid_tree(branch, revision, local_branch):
    if revision is None:
        base_tree = branch.working_tree()
    else:
        if local_branch is not None:
            greedy_fetch(local_branch, branch, revision)
            base_tree = local_branch.revision_tree(revision)
        else:
            base_tree = branch.revision_tree(revision)
    return base_tree


def build_working_dir(to_dir):
    """Build a working directory in an empty directory.

    to_dir is a directory containing branch metadata but no working files,
    typically constructed by cloning an existing branch. 

    This is split out as a special idiomatic case of merge.  It could
    eventually be done by just building the tree directly calling into 
    lower-level code (e.g. constructing a changeset).
    """
    # RBC 20051019 is this not just 'export' ?
    # AB Well, export doesn't take care of inventory...
    this_branch = Branch.open_containing(to_dir)[0]
    transform_tree(this_branch.working_tree(), this_branch.basis_tree())


def transform_tree(from_tree, to_tree, interesting_ids=None):
    merge_inner(from_tree.branch, to_tree, from_tree, ignore_zero=True,
                interesting_ids=interesting_ids)


def merge_inner(this_branch, other_tree, base_tree, ignore_zero=False,
                backup_files=False, 
                merge_type=ApplyMerge3, 
                interesting_ids=None, 
                show_base=False, 
                reprocess=False, 
                other_rev_id=None,
                interesting_files=None):
    """Primary interface for merging. 

        typical use is probably 
        'merge_inner(branch, branch.get_revision_tree(other_revision),
                     branch.get_revision_tree(base_revision))'
        """
    merger = Merger(this_branch, other_tree, base_tree)
    merger.backup_files = backup_files
    merger.merge_type = merge_type
    merger.interesting_ids = interesting_ids
    if interesting_files:
        assert not interesting_ids, ('Only supply interesting_ids'
                                     ' or interesting_files')
        merger._set_interesting_files(interesting_files)
    merger.show_base = show_base 
    merger.reprocess = reprocess
    merger.conflict_handler = _MergeConflictHandler(merger.this_tree, 
                                                    base_tree, other_tree,
                                                    ignore_zero=ignore_zero)
    merger.other_rev_id = other_rev_id
    merger.other_basis = other_rev_id
    return merger.do_merge()


class Merger(object):
    def __init__(self, this_branch, other_tree=None, base_tree=None):
        object.__init__(self)
        self.this_branch = this_branch
        self.this_basis = this_branch.last_revision()
        self.this_rev_id = None
        self.this_tree = this_branch.working_tree()
        self.this_revision_tree = None
        self.this_basis_tree = None
        self.other_tree = other_tree
        self.base_tree = base_tree
        self.ignore_zero = False
        self.backup_files = False
        self.interesting_ids = None
        self.show_base = False
        self.reprocess = False
        self.conflict_handler = _MergeConflictHandler(self.this_tree, 
                                                      base_tree, other_tree)

    def revision_tree(self, revision_id):
        return self.this_branch.revision_tree(revision_id)

    def ensure_revision_trees(self):
        if self.this_revision_tree is None:
            self.this_basis_tree = self.this_branch.revision_tree(
                self.this_basis)
            if self.this_basis == self.this_rev_id:
                self.this_revision_tree = self.this_basis_tree

        if self.other_rev_id is None:
            other_basis_tree = self.revision_tree(self.other_basis)
            changes = compare_trees(self.other_tree, other_basis_tree)
            if changes.has_changed():
                raise WorkingTreeNotRevision(self.this_tree)
            other_rev_id = other_basis
            self.other_tree = other_basis_tree

    def file_revisions(self, file_id):
        self.ensure_revision_trees()
        def get_id(tree, file_id):
            revision_id = tree.inventory[file_id].revision
            assert revision_id is not None
            return revision_id
        if self.this_rev_id is None:
            if self.this_basis_tree.get_file_sha1(file_id) != \
                self.this_tree.get_file_sha1(file_id):
                raise WorkingTreeNotRevision(self.this_tree)

        trees = (self.this_basis_tree, self.other_tree)
        return [get_id(tree, file_id) for tree in trees]

    def merge_factory(self, file_id, base, other):
        if self.merge_type.history_based:
            if self.show_base is True:
                raise BzrError("Cannot show base for hisory-based merges")
            if self.reprocess is True:
                raise BzrError("Cannot reprocess history-based merges")
                
            t_revid, o_revid = self.file_revisions(file_id)
            weave = self.this_basis_tree.get_weave(file_id)
            contents_change = self.merge_type(weave, t_revid, o_revid)
        else:
            if self.show_base is True or self.reprocess is True:
                contents_change = self.merge_type(file_id, base, other, 
                                                  show_base=self.show_base, 
                                                  reprocess=self.reprocess)
            else:
                contents_change = self.merge_type(file_id, base, other)
        if self.backup_files:
            contents_change = BackupBeforeChange(contents_change)
        return contents_change

    def check_basis(self, check_clean):
        if self.this_basis is None:
            raise BzrCommandError("This branch has no commits")
        if check_clean:
            self.compare_basis()
            if self.this_basis != self.this_rev_id:
                raise BzrCommandError("Working tree has uncommitted changes.")

    def compare_basis(self):
        changes = compare_trees(self.this_branch.working_tree(), 
                                self.this_branch.basis_tree(), False)
        if not changes.has_changed():
            self.this_rev_id = self.this_basis

    def set_interesting_files(self, file_list):
        try:
            self._set_interesting_files(file_list)
        except NotVersionedError, e:
            raise BzrCommandError("%s is not a source file in any"
                                      " tree." % e.path)

    def _set_interesting_files(self, file_list):
        """Set the list of interesting ids from a list of files."""
        if file_list is None:
            self.interesting_ids = None
            return

        interesting_ids = set()
        for fname in file_list:
            path = self.this_tree.relpath(fname)
            found_id = False
            for tree in (self.this_tree, self.base_tree, self.other_tree):
                file_id = tree.inventory.path2id(path)
                if file_id is not None:
                    interesting_ids.add(file_id)
                    found_id = True
            if not found_id:
                raise NotVersionedError(path=fname)
        self.interesting_ids = interesting_ids

    def set_pending(self):
        if not self.base_is_ancestor:
            return
        if self.other_rev_id is None:
            return
        if self.other_rev_id in self.this_branch.get_ancestry(self.this_basis):
            return
        self.this_branch.working_tree().add_pending_merge(self.other_rev_id)

    def set_other(self, other_revision):
        other_branch, self.other_tree = _get_tree(other_revision, 
                                                  self.this_branch)
        if other_revision[1] == -1:
            self.other_rev_id = other_branch.last_revision()
            if self.other_rev_id is None:
                raise NoCommits(other_branch)
            self.other_basis = self.other_rev_id
        elif other_revision[1] is not None:
            self.other_rev_id = other_branch.get_rev_id(other_revision[1])
            self.other_basis = self.other_rev_id
        else:
            self.other_rev_id = None
            self.other_basis = other_branch.last_revision()
            if self.other_basis is None:
                raise NoCommits(other_branch)
        fetch(from_branch=other_branch, to_branch=self.this_branch, 
              last_revision=self.other_basis)

    def set_base(self, base_revision):
        mutter("doing merge() with no base_revision specified")
        if base_revision == [None, None]:
            try:
                self.base_rev_id = common_ancestor(self.this_basis, 
                                                   self.other_basis, 
                                                   self.this_branch)
            except NoCommonAncestor:
                raise UnrelatedBranches()
            self.base_tree = _get_revid_tree(self.this_branch, self.base_rev_id,
                                            None)
            self.base_is_ancestor = True
        else:
            base_branch, self.base_tree = _get_tree(base_revision)
            if base_revision[1] == -1:
                self.base_rev_id = base_branch.last_revision()
            elif base_revision[1] is None:
                self.base_rev_id = None
            else:
                self.base_rev_id = base_branch.get_rev_id(base_revision[1])
            fetch(from_branch=base_branch, to_branch=self.this_branch)
            self.base_is_ancestor = is_ancestor(self.this_basis, 
                                                self.base_rev_id,
                                                self.this_branch)

    def do_merge(self):
        def get_inventory(tree):
            return tree.inventory
        
        inv_changes = merge_flex(self.this_tree, self.base_tree, 
                                 self.other_tree,
                                 generate_changeset, get_inventory,
                                 self.conflict_handler,
                                 merge_factory=self.merge_factory, 
                                 interesting_ids=self.interesting_ids)

        adjust_ids = []
        for id, path in inv_changes.iteritems():
            if path is not None:
                if path == u'.':
                    path = u''
                else:
                    assert path.startswith('.' + '/') or path.startswith('.' + '\\'), "path is %s" % path
                path = path[2:]
            adjust_ids.append((path, id))
        if len(adjust_ids) > 0:
            self.this_branch.working_tree().set_inventory(self.regen_inventory(adjust_ids))
        conflicts = self.conflict_handler.conflicts
        self.conflict_handler.finalize()
        return conflicts

    def regen_inventory(self, new_entries):
        old_entries = self.this_branch.working_tree().read_working_inventory()
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
            return pathjoin(id2path(entry.parent_id), entry.name)
            
        for file_id in old_entries:
            entry = old_entries[file_id]
            path = id2path(file_id)
            new_inventory[file_id] = (path, file_id, entry.parent_id, 
                                      entry.kind)
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
            abspath = pathjoin(self.this_tree.basedir, path)
            kind = bzrlib.osutils.file_kind(abspath)
            new_inventory[file_id] = (path, file_id, parent, kind)
            by_path[path] = file_id 

        # Get a list in insertion order
        new_inventory_list = new_inventory.values()
        mutter ("""Inventory regeneration:
    old length: %i insertions: %i deletions: %i new_length: %i"""\
            % (len(old_entries), insertions, deletions, 
               len(new_inventory_list)))
        assert len(new_inventory_list) == len(old_entries) + insertions\
            - deletions
        new_inventory_list.sort()
        return new_inventory_list


merge_types = {     "merge3": (ApplyMerge3, "Native diff3-style merge"), 
                     "diff3": (Diff3Merge,  "Merge using external diff3"),
                     'weave': (WeaveMerge, "Weave-based merge")
              }
