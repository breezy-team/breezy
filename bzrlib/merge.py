# Copyright (C) 2005, 2006 Canonical Ltd
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


import os
import errno
import warnings

from bzrlib import (
    errors,
    osutils,
    patiencediff,
    registry,
    revision as _mod_revision,
    )
from bzrlib.branch import Branch
from bzrlib.conflicts import ConflictList, Conflict
from bzrlib.errors import (BzrCommandError,
                           BzrError,
                           NoCommonAncestor,
                           NoCommits,
                           NoSuchRevision,
                           NoSuchFile,
                           NotBranchError,
                           NotVersionedError,
                           UnrelatedBranches,
                           UnsupportedOperation,
                           WorkingTreeNotRevision,
                           BinaryFile,
                           )
from bzrlib.merge3 import Merge3
from bzrlib.osutils import rename, pathjoin
from progress import DummyProgress, ProgressPhase
from bzrlib.revision import (is_ancestor, NULL_REVISION, ensure_null)
from bzrlib.textfile import check_text_lines
from bzrlib.trace import mutter, warning, note
from bzrlib.transform import (TreeTransform, resolve_conflicts, cook_conflicts,
                              conflict_pass, FinalPaths, create_by_entry,
                              unique_add, ROOT_PARENT)
from bzrlib.versionedfile import PlanWeaveMerge
from bzrlib import ui

# TODO: Report back as changes are merged in


def transform_tree(from_tree, to_tree, interesting_ids=None):
    merge_inner(from_tree.branch, to_tree, from_tree, ignore_zero=True,
                interesting_ids=interesting_ids, this_tree=from_tree)


class Merger(object):
    def __init__(self, this_branch, other_tree=None, base_tree=None,
                 this_tree=None, pb=DummyProgress(), change_reporter=None,
                 recurse='down'):
        object.__init__(self)
        assert this_tree is not None, "this_tree is required"
        self.this_branch = this_branch
        self.this_basis = _mod_revision.ensure_null(
            this_branch.last_revision())
        self.this_rev_id = None
        self.this_tree = this_tree
        self.this_revision_tree = None
        self.this_basis_tree = None
        self.other_tree = other_tree
        self.other_branch = None
        self.base_tree = base_tree
        self.ignore_zero = False
        self.backup_files = False
        self.interesting_ids = None
        self.interesting_files = None
        self.show_base = False
        self.reprocess = False
        self._pb = pb
        self.pp = None
        self.recurse = recurse
        self.change_reporter = change_reporter
        self._cached_trees = {}

    def revision_tree(self, revision_id, branch=None):
        if revision_id not in self._cached_trees:
            if branch is None:
                branch = self.this_branch
            try:
                tree = self.this_tree.revision_tree(revision_id)
            except errors.NoSuchRevisionInTree:
                tree = branch.repository.revision_tree(revision_id)
            self._cached_trees[revision_id] = tree
        return self._cached_trees[revision_id]

    def _get_tree(self, treespec, possible_transports=None):
        from bzrlib import workingtree
        location, revno = treespec
        if revno is None:
            tree = workingtree.WorkingTree.open_containing(location)[0]
            return tree.branch, tree
        branch = Branch.open_containing(location, possible_transports)[0]
        if revno == -1:
            revision_id = branch.last_revision()
        else:
            revision_id = branch.get_rev_id(revno)
        revision_id = ensure_null(revision_id)
        return branch, self.revision_tree(revision_id, branch)

    def ensure_revision_trees(self):
        if self.this_revision_tree is None:
            self.this_basis_tree = self.revision_tree(self.this_basis)
            if self.this_basis == self.this_rev_id:
                self.this_revision_tree = self.this_basis_tree

        if self.other_rev_id is None:
            other_basis_tree = self.revision_tree(self.other_basis)
            changes = other_basis_tree.changes_from(self.other_tree)
            if changes.has_changed():
                raise WorkingTreeNotRevision(self.this_tree)
            other_rev_id = self.other_basis
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

    def check_basis(self, check_clean, require_commits=True):
        if self.this_basis is None and require_commits is True:
            raise BzrCommandError("This branch has no commits."
                                  " (perhaps you would prefer 'bzr pull')")
        if check_clean:
            self.compare_basis()
            if self.this_basis != self.this_rev_id:
                raise BzrCommandError("Working tree has uncommitted changes.")

    def compare_basis(self):
        try:
            basis_tree = self.revision_tree(self.this_tree.last_revision())
        except errors.RevisionNotPresent:
            basis_tree = self.this_tree.basis_tree()
        changes = self.this_tree.changes_from(basis_tree)
        if not changes.has_changed():
            self.this_rev_id = self.this_basis

    def set_interesting_files(self, file_list):
        self.interesting_files = file_list

    def set_pending(self):
        if not self.base_is_ancestor or not self.base_is_other_ancestor:
            return
        self._add_parent()

    def _add_parent(self):
        new_parents = self.this_tree.get_parent_ids() + [self.other_rev_id]
        new_parent_trees = []
        for revision_id in new_parents:
            try:
                tree = self.revision_tree(revision_id)
            except errors.RevisionNotPresent:
                tree = None
            else:
                tree.lock_read()
            new_parent_trees.append((revision_id, tree))
        try:
            self.this_tree.set_parent_trees(new_parent_trees,
                                            allow_leftmost_as_ghost=True)
        finally:
            for _revision_id, tree in new_parent_trees:
                if tree is not None:
                    tree.unlock()

    def set_other(self, other_revision, possible_transports=None):
        """Set the revision and tree to merge from.

        This sets the other_tree, other_rev_id, other_basis attributes.

        :param other_revision: The [path, revision] list to merge from.
        """
        self.other_branch, self.other_tree = self._get_tree(other_revision,
                                                            possible_transports)
        if other_revision[1] == -1:
            self.other_rev_id = _mod_revision.ensure_null(
                self.other_branch.last_revision())
            if _mod_revision.is_null(self.other_rev_id):
                raise NoCommits(self.other_branch)
            self.other_basis = self.other_rev_id
        elif other_revision[1] is not None:
            self.other_rev_id = self.other_branch.get_rev_id(other_revision[1])
            self.other_basis = self.other_rev_id
        else:
            self.other_rev_id = None
            self.other_basis = self.other_branch.last_revision()
            if self.other_basis is None:
                raise NoCommits(self.other_branch)
        if self.other_rev_id is not None:
            self._cached_trees[self.other_rev_id] = self.other_tree
        self._maybe_fetch(self.other_branch,self.this_branch, self.other_basis)

    def set_other_revision(self, revision_id, other_branch):
        """Set 'other' based on a branch and revision id

        :param revision_id: The revision to use for a tree
        :param other_branch: The branch containing this tree
        """
        self.other_rev_id = revision_id
        self.other_branch = other_branch
        self._maybe_fetch(other_branch, self.this_branch, self.other_rev_id)
        self.other_tree = self.revision_tree(revision_id)
        self.other_basis = revision_id

    def set_base_revision(self, revision_id, branch):
        """Set 'base' based on a branch and revision id

        :param revision_id: The revision to use for a tree
        :param branch: The branch containing this tree
        """
        self.base_rev_id = revision_id
        self.base_branch = branch
        self._maybe_fetch(branch, self.this_branch, revision_id)
        self.base_tree = self.revision_tree(revision_id)
        self.base_is_ancestor = is_ancestor(self.this_basis,
                                            self.base_rev_id,
                                            self.this_branch)
        self.base_is_other_ancestor = is_ancestor(self.other_basis,
                                                  self.base_rev_id,
                                                  self.this_branch)

    def _maybe_fetch(self, source, target, revision_id):
        if (source.repository.bzrdir.root_transport.base !=
            target.repository.bzrdir.root_transport.base):
            target.fetch(source, revision_id)

    def find_base(self):
        this_repo = self.this_branch.repository
        graph = this_repo.get_graph()
        revisions = [ensure_null(self.this_basis),
                     ensure_null(self.other_basis)]
        if NULL_REVISION in revisions:
            self.base_rev_id = NULL_REVISION
        else:
            self.base_rev_id = graph.find_unique_lca(*revisions)
            if self.base_rev_id == NULL_REVISION:
                raise UnrelatedBranches()
        self.base_tree = self.revision_tree(self.base_rev_id)
        self.base_is_ancestor = True
        self.base_is_other_ancestor = True

    def set_base(self, base_revision):
        """Set the base revision to use for the merge.

        :param base_revision: A 2-list containing a path and revision number.
        """
        mutter("doing merge() with no base_revision specified")
        if base_revision == [None, None]:
            self.find_base()
        else:
            base_branch, self.base_tree = self._get_tree(base_revision)
            if base_revision[1] == -1:
                self.base_rev_id = base_branch.last_revision()
            elif base_revision[1] is None:
                self.base_rev_id = _mod_revision.NULL_REVISION
            else:
                self.base_rev_id = _mod_revision.ensure_null(
                    base_branch.get_rev_id(base_revision[1]))
            self._maybe_fetch(base_branch, self.this_branch, self.base_rev_id)
            self.base_is_ancestor = is_ancestor(self.this_basis, 
                                                self.base_rev_id,
                                                self.this_branch)
            self.base_is_other_ancestor = is_ancestor(self.other_basis,
                                                      self.base_rev_id,
                                                      self.this_branch)

    def do_merge(self):
        kwargs = {'working_tree':self.this_tree, 'this_tree': self.this_tree,
                  'other_tree': self.other_tree,
                  'interesting_ids': self.interesting_ids,
                  'interesting_files': self.interesting_files,
                  'pp': self.pp}
        if self.merge_type.requires_base:
            kwargs['base_tree'] = self.base_tree
        if self.merge_type.supports_reprocess:
            kwargs['reprocess'] = self.reprocess
        elif self.reprocess:
            raise BzrError("Conflict reduction is not supported for merge"
                                  " type %s." % self.merge_type)
        if self.merge_type.supports_show_base:
            kwargs['show_base'] = self.show_base
        elif self.show_base:
            raise BzrError("Showing base is not supported for this"
                                  " merge type. %s" % self.merge_type)
        self.this_tree.lock_tree_write()
        if self.base_tree is not None:
            self.base_tree.lock_read()
        if self.other_tree is not None:
            self.other_tree.lock_read()
        try:
            merge = self.merge_type(pb=self._pb,
                                    change_reporter=self.change_reporter,
                                    **kwargs)
            if self.recurse == 'down':
                for path, file_id in self.this_tree.iter_references():
                    sub_tree = self.this_tree.get_nested_tree(file_id, path)
                    other_revision = self.other_tree.get_reference_revision(
                        file_id, path)
                    if  other_revision == sub_tree.last_revision():
                        continue
                    sub_merge = Merger(sub_tree.branch, this_tree=sub_tree)
                    sub_merge.merge_type = self.merge_type
                    relpath = self.this_tree.relpath(path)
                    other_branch = self.other_branch.reference_parent(file_id, relpath)
                    sub_merge.set_other_revision(other_revision, other_branch)
                    base_revision = self.base_tree.get_reference_revision(file_id)
                    sub_merge.base_tree = \
                        sub_tree.branch.repository.revision_tree(base_revision)
                    sub_merge.do_merge()

        finally:
            if self.other_tree is not None:
                self.other_tree.unlock()
            if self.base_tree is not None:
                self.base_tree.unlock()
            self.this_tree.unlock()
        if len(merge.cooked_conflicts) == 0:
            if not self.ignore_zero:
                note("All changes applied successfully.")
        else:
            note("%d conflicts encountered." % len(merge.cooked_conflicts))

        return len(merge.cooked_conflicts)


class Merge3Merger(object):
    """Three-way merger that uses the merge3 text merger"""
    requires_base = True
    supports_reprocess = True
    supports_show_base = True
    history_based = False
    winner_idx = {"this": 2, "other": 1, "conflict": 1}

    def __init__(self, working_tree, this_tree, base_tree, other_tree, 
                 interesting_ids=None, reprocess=False, show_base=False,
                 pb=DummyProgress(), pp=None, change_reporter=None,
                 interesting_files=None):
        """Initialize the merger object and perform the merge.

        :param working_tree: The working tree to apply the merge to
        :param this_tree: The local tree in the merge operation
        :param base_tree: The common tree in the merge operation
        :param other_tree: The other other tree to merge changes from
        :param interesting_ids: The file_ids of files that should be
            participate in the merge.  May not be combined with
            interesting_files.
        :param: reprocess If True, perform conflict-reduction processing.
        :param show_base: If True, show the base revision in text conflicts.
            (incompatible with reprocess)
        :param pb: A Progress bar
        :param pp: A ProgressPhase object
        :param change_reporter: An object that should report changes made
        :param interesting_files: The tree-relative paths of files that should
            participate in the merge.  If these paths refer to directories,
            the contents of those directories will also be included.  May not
            be combined with interesting_ids.  If neither interesting_files nor
            interesting_ids is specified, all files may participate in the
            merge.
        """
        object.__init__(self)
        if interesting_files is not None:
            assert interesting_ids is None
        self.interesting_ids = interesting_ids
        self.interesting_files = interesting_files
        self.this_tree = working_tree
        self.this_tree.lock_tree_write()
        self.base_tree = base_tree
        self.base_tree.lock_read()
        self.other_tree = other_tree
        self.other_tree.lock_read()
        self._raw_conflicts = []
        self.cooked_conflicts = []
        self.reprocess = reprocess
        self.show_base = show_base
        self.pb = pb
        self.pp = pp
        self.change_reporter = change_reporter
        if self.pp is None:
            self.pp = ProgressPhase("Merge phase", 3, self.pb)

        self.tt = TreeTransform(working_tree, self.pb)
        try:
            self.pp.next_phase()
            entries = self._entries3()
            child_pb = ui.ui_factory.nested_progress_bar()
            try:
                for num, (file_id, changed, parents3, names3,
                          executable3) in enumerate(entries):
                    child_pb.update('Preparing file merge', num, len(entries))
                    self._merge_names(file_id, parents3, names3)
                    if changed:
                        file_status = self.merge_contents(file_id)
                    else:
                        file_status = 'unmodified'
                    self._merge_executable(file_id,
                        executable3, file_status)
            finally:
                child_pb.finished()
            self.fix_root()
            self.pp.next_phase()
            child_pb = ui.ui_factory.nested_progress_bar()
            try:
                fs_conflicts = resolve_conflicts(self.tt, child_pb,
                    lambda t, c: conflict_pass(t, c, self.other_tree))
            finally:
                child_pb.finished()
            if change_reporter is not None:
                from bzrlib import delta
                delta.report_changes(self.tt._iter_changes(), change_reporter)
            self.cook_conflicts(fs_conflicts)
            for conflict in self.cooked_conflicts:
                warning(conflict)
            self.pp.next_phase()
            results = self.tt.apply(no_conflicts=True)
            self.write_modified(results)
            try:
                working_tree.add_conflicts(self.cooked_conflicts)
            except UnsupportedOperation:
                pass
        finally:
            self.tt.finalize()
            self.other_tree.unlock()
            self.base_tree.unlock()
            self.this_tree.unlock()
            self.pb.clear()

    def _entries3(self):
        """Gather data about files modified between three trees.

        Return a list of tuples of file_id, changed, parents3, names3,
        executable3.  changed is a boolean indicating whether the file contents
        or kind were changed.  parents3 is a tuple of parent ids for base,
        other and this.  names3 is a tuple of names for base, other and this.
        executable3 is a tuple of execute-bit values for base, other and this.
        """
        result = []
        iterator = self.other_tree._iter_changes(self.base_tree,
                include_unchanged=True, specific_files=self.interesting_files,
                extra_trees=[self.this_tree])
        for (file_id, paths, changed, versioned, parents, names, kind,
             executable) in iterator:
            if (self.interesting_ids is not None and
                file_id not in self.interesting_ids):
                continue
            if file_id in self.this_tree.inventory:
                entry = self.this_tree.inventory[file_id]
                this_name = entry.name
                this_parent = entry.parent_id
                this_executable = entry.executable
            else:
                this_name = None
                this_parent = None
                this_executable = None
            parents3 = parents + (this_parent,)
            names3 = names + (this_name,)
            executable3 = executable + (this_executable,)
            result.append((file_id, changed, parents3, names3, executable3))
        return result

    def fix_root(self):
        try:
            self.tt.final_kind(self.tt.root)
        except NoSuchFile:
            self.tt.cancel_deletion(self.tt.root)
        if self.tt.final_file_id(self.tt.root) is None:
            self.tt.version_file(self.tt.tree_file_id(self.tt.root), 
                                 self.tt.root)
        if self.other_tree.inventory.root is None:
            return
        other_root_file_id = self.other_tree.inventory.root.file_id
        other_root = self.tt.trans_id_file_id(other_root_file_id)
        if other_root == self.tt.root:
            return
        try:
            self.tt.final_kind(other_root)
        except NoSuchFile:
            return
        self.reparent_children(self.other_tree.inventory.root, self.tt.root)
        self.tt.cancel_creation(other_root)
        self.tt.cancel_versioning(other_root)

    def reparent_children(self, ie, target):
        for thing, child in ie.children.iteritems():
            trans_id = self.tt.trans_id_file_id(child.file_id)
            self.tt.adjust_path(self.tt.final_name(trans_id), target, trans_id)

    def write_modified(self, results):
        modified_hashes = {}
        for path in results.modified_paths:
            file_id = self.this_tree.path2id(self.this_tree.relpath(path))
            if file_id is None:
                continue
            hash = self.this_tree.get_file_sha1(file_id)
            if hash is None:
                continue
            modified_hashes[file_id] = hash
        self.this_tree.set_merge_modified(modified_hashes)

    @staticmethod
    def parent(entry, file_id):
        """Determine the parent for a file_id (used as a key method)"""
        if entry is None:
            return None
        return entry.parent_id

    @staticmethod
    def name(entry, file_id):
        """Determine the name for a file_id (used as a key method)"""
        if entry is None:
            return None
        return entry.name
    
    @staticmethod
    def contents_sha1(tree, file_id):
        """Determine the sha1 of the file contents (used as a key method)."""
        if file_id not in tree:
            return None
        return tree.get_file_sha1(file_id)

    @staticmethod
    def executable(tree, file_id):
        """Determine the executability of a file-id (used as a key method)."""
        if file_id not in tree:
            return None
        if tree.kind(file_id) != "file":
            return False
        return tree.is_executable(file_id)

    @staticmethod
    def kind(tree, file_id):
        """Determine the kind of a file-id (used as a key method)."""
        if file_id not in tree:
            return None
        return tree.kind(file_id)

    @staticmethod
    def _three_way(base, other, this):
        #if base == other, either they all agree, or only THIS has changed.
        if base == other:
            return 'this'
        elif this not in (base, other):
            return 'conflict'
        # "Ambiguous clean merge" -- both sides have made the same change.
        elif this == other:
            return "this"
        # this == base: only other has changed.
        else:
            return "other"

    @staticmethod
    def scalar_three_way(this_tree, base_tree, other_tree, file_id, key):
        """Do a three-way test on a scalar.
        Return "this", "other" or "conflict", depending whether a value wins.
        """
        key_base = key(base_tree, file_id)
        key_other = key(other_tree, file_id)
        #if base == other, either they all agree, or only THIS has changed.
        if key_base == key_other:
            return "this"
        key_this = key(this_tree, file_id)
        if key_this not in (key_base, key_other):
            return "conflict"
        # "Ambiguous clean merge"
        elif key_this == key_other:
            return "this"
        else:
            assert key_this == key_base
            return "other"

    def merge_names(self, file_id):
        def get_entry(tree):
            if file_id in tree.inventory:
                return tree.inventory[file_id]
            else:
                return None
        this_entry = get_entry(self.this_tree)
        other_entry = get_entry(self.other_tree)
        base_entry = get_entry(self.base_tree)
        entries = (base_entry, other_entry, this_entry)
        names = []
        parents = []
        for entry in entries:
            if entry is None:
                names.append(None)
                parents.append(None)
            else:
                names.append(entry.name)
                parents.append(entry.parent_id)
        return self._merge_names(file_id, parents, names)

    def _merge_names(self, file_id, parents, names):
        """Perform a merge on file_id names and parents"""
        base_name, other_name, this_name = names
        base_parent, other_parent, this_parent = parents

        name_winner = self._three_way(*names)

        parent_id_winner = self._three_way(*parents)
        if this_name is None:
            if name_winner == "this":
                name_winner = "other"
            if parent_id_winner == "this":
                parent_id_winner = "other"
        if name_winner == "this" and parent_id_winner == "this":
            return
        if name_winner == "conflict":
            trans_id = self.tt.trans_id_file_id(file_id)
            self._raw_conflicts.append(('name conflict', trans_id, 
                                        this_name, other_name))
        if parent_id_winner == "conflict":
            trans_id = self.tt.trans_id_file_id(file_id)
            self._raw_conflicts.append(('parent conflict', trans_id, 
                                        this_parent, other_parent))
        if other_name is None:
            # it doesn't matter whether the result was 'other' or 
            # 'conflict'-- if there's no 'other', we leave it alone.
            return
        # if we get here, name_winner and parent_winner are set to safe values.
        trans_id = self.tt.trans_id_file_id(file_id)
        parent_id = parents[self.winner_idx[parent_id_winner]]
        if parent_id is not None:
            parent_trans_id = self.tt.trans_id_file_id(parent_id)
            self.tt.adjust_path(names[self.winner_idx[name_winner]],
                                parent_trans_id, trans_id)

    def merge_contents(self, file_id):
        """Performa a merge on file_id contents."""
        def contents_pair(tree):
            if file_id not in tree:
                return (None, None)
            kind = tree.kind(file_id)
            if kind == "file":
                contents = tree.get_file_sha1(file_id)
            elif kind == "symlink":
                contents = tree.get_symlink_target(file_id)
            else:
                contents = None
            return kind, contents

        def contents_conflict():
            trans_id = self.tt.trans_id_file_id(file_id)
            name = self.tt.final_name(trans_id)
            parent_id = self.tt.final_parent(trans_id)
            if file_id in self.this_tree.inventory:
                self.tt.unversion_file(trans_id)
                if file_id in self.this_tree:
                    self.tt.delete_contents(trans_id)
            file_group = self._dump_conflicts(name, parent_id, file_id, 
                                              set_version=True)
            self._raw_conflicts.append(('contents conflict', file_group))

        # See SPOT run.  run, SPOT, run.
        # So we're not QUITE repeating ourselves; we do tricky things with
        # file kind...
        base_pair = contents_pair(self.base_tree)
        other_pair = contents_pair(self.other_tree)
        if base_pair == other_pair:
            # OTHER introduced no changes
            return "unmodified"
        this_pair = contents_pair(self.this_tree)
        if this_pair == other_pair:
            # THIS and OTHER introduced the same changes
            return "unmodified"
        else:
            trans_id = self.tt.trans_id_file_id(file_id)
            if this_pair == base_pair:
                # only OTHER introduced changes
                if file_id in self.this_tree:
                    # Remove any existing contents
                    self.tt.delete_contents(trans_id)
                if file_id in self.other_tree:
                    # OTHER changed the file
                    create_by_entry(self.tt, 
                                    self.other_tree.inventory[file_id], 
                                    self.other_tree, trans_id)
                    if file_id not in self.this_tree.inventory:
                        self.tt.version_file(file_id, trans_id)
                    return "modified"
                elif file_id in self.this_tree.inventory:
                    # OTHER deleted the file
                    self.tt.unversion_file(trans_id)
                    return "deleted"
            #BOTH THIS and OTHER introduced changes; scalar conflict
            elif this_pair[0] == "file" and other_pair[0] == "file":
                # THIS and OTHER are both files, so text merge.  Either
                # BASE is a file, or both converted to files, so at least we
                # have agreement that output should be a file.
                try:
                    self.text_merge(file_id, trans_id)
                except BinaryFile:
                    return contents_conflict()
                if file_id not in self.this_tree.inventory:
                    self.tt.version_file(file_id, trans_id)
                try:
                    self.tt.tree_kind(trans_id)
                    self.tt.delete_contents(trans_id)
                except NoSuchFile:
                    pass
                return "modified"
            else:
                # Scalar conflict, can't text merge.  Dump conflicts
                return contents_conflict()

    def get_lines(self, tree, file_id):
        """Return the lines in a file, or an empty list."""
        if file_id in tree:
            return tree.get_file(file_id).readlines()
        else:
            return []

    def text_merge(self, file_id, trans_id):
        """Perform a three-way text merge on a file_id"""
        # it's possible that we got here with base as a different type.
        # if so, we just want two-way text conflicts.
        if file_id in self.base_tree and \
            self.base_tree.kind(file_id) == "file":
            base_lines = self.get_lines(self.base_tree, file_id)
        else:
            base_lines = []
        other_lines = self.get_lines(self.other_tree, file_id)
        this_lines = self.get_lines(self.this_tree, file_id)
        m3 = Merge3(base_lines, this_lines, other_lines)
        start_marker = "!START OF MERGE CONFLICT!" + "I HOPE THIS IS UNIQUE"
        if self.show_base is True:
            base_marker = '|' * 7
        else:
            base_marker = None

        def iter_merge3(retval):
            retval["text_conflicts"] = False
            for line in m3.merge_lines(name_a = "TREE", 
                                       name_b = "MERGE-SOURCE", 
                                       name_base = "BASE-REVISION",
                                       start_marker=start_marker, 
                                       base_marker=base_marker,
                                       reprocess=self.reprocess):
                if line.startswith(start_marker):
                    retval["text_conflicts"] = True
                    yield line.replace(start_marker, '<' * 7)
                else:
                    yield line
        retval = {}
        merge3_iterator = iter_merge3(retval)
        self.tt.create_file(merge3_iterator, trans_id)
        if retval["text_conflicts"] is True:
            self._raw_conflicts.append(('text conflict', trans_id))
            name = self.tt.final_name(trans_id)
            parent_id = self.tt.final_parent(trans_id)
            file_group = self._dump_conflicts(name, parent_id, file_id, 
                                              this_lines, base_lines,
                                              other_lines)
            file_group.append(trans_id)

    def _dump_conflicts(self, name, parent_id, file_id, this_lines=None, 
                        base_lines=None, other_lines=None, set_version=False,
                        no_base=False):
        """Emit conflict files.
        If this_lines, base_lines, or other_lines are omitted, they will be
        determined automatically.  If set_version is true, the .OTHER, .THIS
        or .BASE (in that order) will be created as versioned files.
        """
        data = [('OTHER', self.other_tree, other_lines), 
                ('THIS', self.this_tree, this_lines)]
        if not no_base:
            data.append(('BASE', self.base_tree, base_lines))
        versioned = False
        file_group = []
        for suffix, tree, lines in data:
            if file_id in tree:
                trans_id = self._conflict_file(name, parent_id, tree, file_id,
                                               suffix, lines)
                file_group.append(trans_id)
                if set_version and not versioned:
                    self.tt.version_file(file_id, trans_id)
                    versioned = True
        return file_group
           
    def _conflict_file(self, name, parent_id, tree, file_id, suffix, 
                       lines=None):
        """Emit a single conflict file."""
        name = name + '.' + suffix
        trans_id = self.tt.create_path(name, parent_id)
        entry = tree.inventory[file_id]
        create_by_entry(self.tt, entry, tree, trans_id, lines)
        return trans_id

    def merge_executable(self, file_id, file_status):
        """Perform a merge on the execute bit."""
        executable = [self.executable(t, file_id) for t in (self.base_tree,
                      self.other_tree, self.this_tree)]
        self._merge_executable(file_id, executable, file_status)

    def _merge_executable(self, file_id, executable, file_status):
        """Perform a merge on the execute bit."""
        base_executable, other_executable, this_executable = executable
        if file_status == "deleted":
            return
        trans_id = self.tt.trans_id_file_id(file_id)
        try:
            if self.tt.final_kind(trans_id) != "file":
                return
        except NoSuchFile:
            return
        winner = self._three_way(*executable)
        if winner == "conflict":
        # There must be a None in here, if we have a conflict, but we
        # need executability since file status was not deleted.
            if self.executable(self.other_tree, file_id) is None:
                winner = "this"
            else:
                winner = "other"
        if winner == "this":
            if file_status == "modified":
                executability = this_executable
                if executability is not None:
                    trans_id = self.tt.trans_id_file_id(file_id)
                    self.tt.set_executability(executability, trans_id)
        else:
            assert winner == "other"
            if file_id in self.other_tree:
                executability = other_executable
            elif file_id in self.this_tree:
                executability = this_executable
            elif file_id in self.base_tree:
                executability = base_executable
            if executability is not None:
                trans_id = self.tt.trans_id_file_id(file_id)
                self.tt.set_executability(executability, trans_id)

    def cook_conflicts(self, fs_conflicts):
        """Convert all conflicts into a form that doesn't depend on trans_id"""
        from conflicts import Conflict
        name_conflicts = {}
        self.cooked_conflicts.extend(cook_conflicts(fs_conflicts, self.tt))
        fp = FinalPaths(self.tt)
        for conflict in self._raw_conflicts:
            conflict_type = conflict[0]
            if conflict_type in ('name conflict', 'parent conflict'):
                trans_id = conflict[1]
                conflict_args = conflict[2:]
                if trans_id not in name_conflicts:
                    name_conflicts[trans_id] = {}
                unique_add(name_conflicts[trans_id], conflict_type, 
                           conflict_args)
            if conflict_type == 'contents conflict':
                for trans_id in conflict[1]:
                    file_id = self.tt.final_file_id(trans_id)
                    if file_id is not None:
                        break
                path = fp.get_path(trans_id)
                for suffix in ('.BASE', '.THIS', '.OTHER'):
                    if path.endswith(suffix):
                        path = path[:-len(suffix)]
                        break
                c = Conflict.factory(conflict_type, path=path, file_id=file_id)
                self.cooked_conflicts.append(c)
            if conflict_type == 'text conflict':
                trans_id = conflict[1]
                path = fp.get_path(trans_id)
                file_id = self.tt.final_file_id(trans_id)
                c = Conflict.factory(conflict_type, path=path, file_id=file_id)
                self.cooked_conflicts.append(c)

        for trans_id, conflicts in name_conflicts.iteritems():
            try:
                this_parent, other_parent = conflicts['parent conflict']
                assert this_parent != other_parent
            except KeyError:
                this_parent = other_parent = \
                    self.tt.final_file_id(self.tt.final_parent(trans_id))
            try:
                this_name, other_name = conflicts['name conflict']
                assert this_name != other_name
            except KeyError:
                this_name = other_name = self.tt.final_name(trans_id)
            other_path = fp.get_path(trans_id)
            if this_parent is not None and this_name is not None:
                this_parent_path = \
                    fp.get_path(self.tt.trans_id_file_id(this_parent))
                this_path = pathjoin(this_parent_path, this_name)
            else:
                this_path = "<deleted>"
            file_id = self.tt.final_file_id(trans_id)
            c = Conflict.factory('path conflict', path=this_path,
                                 conflict_path=other_path, file_id=file_id)
            self.cooked_conflicts.append(c)
        self.cooked_conflicts.sort(key=Conflict.sort_key)


class WeaveMerger(Merge3Merger):
    """Three-way tree merger, text weave merger."""
    supports_reprocess = True
    supports_show_base = False

    def __init__(self, working_tree, this_tree, base_tree, other_tree, 
                 interesting_ids=None, pb=DummyProgress(), pp=None,
                 reprocess=False, change_reporter=None,
                 interesting_files=None):
        super(WeaveMerger, self).__init__(working_tree, this_tree, 
                                          base_tree, other_tree, 
                                          interesting_ids=interesting_ids, 
                                          pb=pb, pp=pp, reprocess=reprocess,
                                          change_reporter=change_reporter)

    def _merged_lines(self, file_id):
        """Generate the merged lines.
        There is no distinction between lines that are meant to contain <<<<<<<
        and conflicts.
        """
        plan = self.this_tree.plan_file_merge(file_id, self.other_tree)
        textmerge = PlanWeaveMerge(plan, '<<<<<<< TREE\n',
            '>>>>>>> MERGE-SOURCE\n')
        return textmerge.merge_lines(self.reprocess)

    def text_merge(self, file_id, trans_id):
        """Perform a (weave) text merge for a given file and file-id.
        If conflicts are encountered, .THIS and .OTHER files will be emitted,
        and a conflict will be noted.
        """
        lines, conflicts = self._merged_lines(file_id)
        lines = list(lines)
        # Note we're checking whether the OUTPUT is binary in this case, 
        # because we don't want to get into weave merge guts.
        check_text_lines(lines)
        self.tt.create_file(lines, trans_id)
        if conflicts:
            self._raw_conflicts.append(('text conflict', trans_id))
            name = self.tt.final_name(trans_id)
            parent_id = self.tt.final_parent(trans_id)
            file_group = self._dump_conflicts(name, parent_id, file_id, 
                                              no_base=True)
            file_group.append(trans_id)


class Diff3Merger(Merge3Merger):
    """Three-way merger using external diff3 for text merging"""

    def dump_file(self, temp_dir, name, tree, file_id):
        out_path = pathjoin(temp_dir, name)
        out_file = open(out_path, "wb")
        try:
            in_file = tree.get_file(file_id)
            for line in in_file:
                out_file.write(line)
        finally:
            out_file.close()
        return out_path

    def text_merge(self, file_id, trans_id):
        """Perform a diff3 merge using a specified file-id and trans-id.
        If conflicts are encountered, .BASE, .THIS. and .OTHER conflict files
        will be dumped, and a will be conflict noted.
        """
        import bzrlib.patch
        temp_dir = osutils.mkdtemp(prefix="bzr-")
        try:
            new_file = pathjoin(temp_dir, "new")
            this = self.dump_file(temp_dir, "this", self.this_tree, file_id)
            base = self.dump_file(temp_dir, "base", self.base_tree, file_id)
            other = self.dump_file(temp_dir, "other", self.other_tree, file_id)
            status = bzrlib.patch.diff3(new_file, this, base, other)
            if status not in (0, 1):
                raise BzrError("Unhandled diff3 exit code")
            f = open(new_file, 'rb')
            try:
                self.tt.create_file(f, trans_id)
            finally:
                f.close()
            if status == 1:
                name = self.tt.final_name(trans_id)
                parent_id = self.tt.final_parent(trans_id)
                self._dump_conflicts(name, parent_id, file_id)
                self._raw_conflicts.append(('text conflict', trans_id))
        finally:
            osutils.rmtree(temp_dir)


def merge_inner(this_branch, other_tree, base_tree, ignore_zero=False,
                backup_files=False,
                merge_type=Merge3Merger,
                interesting_ids=None,
                show_base=False,
                reprocess=False,
                other_rev_id=None,
                interesting_files=None,
                this_tree=None,
                pb=DummyProgress(),
                change_reporter=None):
    """Primary interface for merging. 

        typical use is probably 
        'merge_inner(branch, branch.get_revision_tree(other_revision),
                     branch.get_revision_tree(base_revision))'
        """
    if this_tree is None:
        raise BzrError("bzrlib.merge.merge_inner requires a this_tree "
            "parameter as of bzrlib version 0.8.")
    merger = Merger(this_branch, other_tree, base_tree, this_tree=this_tree,
                    pb=pb, change_reporter=change_reporter)
    merger.backup_files = backup_files
    merger.merge_type = merge_type
    merger.interesting_ids = interesting_ids
    merger.ignore_zero = ignore_zero
    if interesting_files:
        assert not interesting_ids, ('Only supply interesting_ids'
                                     ' or interesting_files')
        merger.interesting_files = interesting_files
    merger.show_base = show_base
    merger.reprocess = reprocess
    merger.other_rev_id = other_rev_id
    merger.other_basis = other_rev_id
    return merger.do_merge()

def get_merge_type_registry():
    """Merge type registry is in bzrlib.option to avoid circular imports.

    This method provides a sanctioned way to retrieve it.
    """
    from bzrlib import option
    return option._merge_type_registry


def _plan_annotate_merge(annotated_a, annotated_b, ancestors_a, ancestors_b):
    def status_a(revision, text):
        if revision in ancestors_b:
            return 'killed-b', text
        else:
            return 'new-a', text

    def status_b(revision, text):
        if revision in ancestors_a:
            return 'killed-a', text
        else:
            return 'new-b', text

    plain_a = [t for (a, t) in annotated_a]
    plain_b = [t for (a, t) in annotated_b]
    matcher = patiencediff.PatienceSequenceMatcher(None, plain_a, plain_b)
    blocks = matcher.get_matching_blocks()
    a_cur = 0
    b_cur = 0
    for ai, bi, l in blocks:
        # process all mismatched sections
        # (last mismatched section is handled because blocks always
        # includes a 0-length last block)
        for revision, text in annotated_a[a_cur:ai]:
            yield status_a(revision, text)
        for revision, text in annotated_b[b_cur:bi]:
            yield status_b(revision, text)

        # and now the matched section
        a_cur = ai + l
        b_cur = bi + l
        for text_a, text_b in zip(plain_a[ai:a_cur], plain_b[bi:b_cur]):
            assert text_a == text_b
            yield "unchanged", text_a
