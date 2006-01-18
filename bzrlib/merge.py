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

import bzrlib
from bzrlib._changeset import generate_changeset
from bzrlib._changeset import Inventory, Diff3Merge
from bzrlib._merge import MergeConflictHandler
from bzrlib._merge_core import WeaveMerge
from bzrlib._merge_core import merge_flex, ApplyMerge3, BackupBeforeChange
from bzrlib.branch import Branch
from bzrlib.delta import compare_trees
from bzrlib.errors import (BzrCommandError,
                           UnrelatedBranches,
                           NoCommonAncestor,
                           NoCommits,
                           WorkingTreeNotRevision,
                           NotVersionedError,
                           BzrError)
from bzrlib.fetch import greedy_fetch, fetch
from bzrlib.osutils import pathjoin
from bzrlib.revision import common_ancestor, MultipleRevisionSources
from bzrlib.revision import is_ancestor, NULL_REVISION
from bzrlib.trace import mutter, note


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


def merge(other_revision, base_revision,
          check_clean=True, ignore_zero=False,
          this_dir=None, backup_files=False, merge_type=ApplyMerge3,
          file_list=None, show_base=False, reprocess=False):
    """Merge changes into a tree.

    base_revision
        list(path, revno) Base for three-way merge.  
        If [None, None] then a base will be automatically determined.
    other_revision
        list(path, revno) Other revision for three-way merge.
    this_dir
        Directory to merge changes into; '.' by default.
    check_clean
        If true, this_dir must have no uncommitted changes before the
        merge begins.
    ignore_zero - If true, suppress the "zero conflicts" message when 
        there are no conflicts; should be set when doing something we expect
        to complete perfectly.
    file_list - If supplied, merge only changes to selected files.

    All available ancestors of other_revision and base_revision are
    automatically pulled into the branch.

    The revno may be -1 to indicate the last revision on the branch, which is
    the typical case.

    This function is intended for use from the command line; programmatic
    clients might prefer to call merge_inner(), which has less magic behavior.
    """
    if this_dir is None:
        this_dir = u'.'
    this_branch = Branch.open_containing(this_dir)[0]
    if show_base and not merge_type is ApplyMerge3:
        raise BzrCommandError("Show-base is not supported for this merge"
                              " type. %s" % merge_type)
    if reprocess and not merge_type is ApplyMerge3:
        raise BzrCommandError("Reprocess is not supported for this merge"
                              " type. %s" % merge_type)
    if reprocess and show_base:
        raise BzrCommandError("Cannot reprocess and show base.")
    merger = Merger(this_branch)
    merger.check_basis(check_clean)
    merger.set_other(other_revision)
    merger.set_base(base_revision)
    if merger.base_rev_id == merger.other_rev_id:
        note('Nothing to do.')
        return 0
    merger.backup_files = backup_files
    merger.merge_type = merge_type 
    merger.set_interesting_files(file_list)
    merger.show_base = show_base 
    merger.reprocess = reprocess
    merger.conflict_handler = MergeConflictHandler(merger.this_tree, 
                                                   merger.base_tree, 
                                                   merger.other_tree,
                                                   ignore_zero=ignore_zero)
    conflicts = merger.do_merge()
    merger.set_pending()
    return conflicts


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
    merger.conflict_handler = MergeConflictHandler(merger.this_tree, base_tree, 
                                                   other_tree,
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
        self.conflict_handler = MergeConflictHandler(self.this_tree, base_tree, 
                                                     other_tree)

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
