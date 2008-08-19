# Copyright (C) 2005, 2006, 2008 Canonical Ltd
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


import errno
from itertools import chain
import os
import warnings

from bzrlib import (
    debug,
    errors,
    graph as _mod_graph,
    osutils,
    patiencediff,
    registry,
    revision as _mod_revision,
    tsort,
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
from bzrlib.graph import Graph
from bzrlib.merge3 import Merge3
from bzrlib.osutils import rename, pathjoin
from progress import DummyProgress, ProgressPhase
from bzrlib.revision import (NULL_REVISION, ensure_null)
from bzrlib.textfile import check_text_lines
from bzrlib.trace import mutter, warning, note, is_quiet
from bzrlib.transform import (TransformPreview, TreeTransform,
                              resolve_conflicts, cook_conflicts,
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
                 recurse='down', revision_graph=None):
        object.__init__(self)
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
        self._revision_graph = revision_graph
        self._base_is_ancestor = None
        self._base_is_other_ancestor = None

    @property
    def revision_graph(self):
        if self._revision_graph is None:
            self._revision_graph = self.this_branch.repository.get_graph()
        return self._revision_graph

    def _set_base_is_ancestor(self, value):
        self._base_is_ancestor = value

    def _get_base_is_ancestor(self):
        if self._base_is_ancestor is None:
            self._base_is_ancestor = self.revision_graph.is_ancestor(
                self.base_rev_id, self.this_basis)
        return self._base_is_ancestor

    base_is_ancestor = property(_get_base_is_ancestor, _set_base_is_ancestor)

    def _set_base_is_other_ancestor(self, value):
        self._base_is_other_ancestor = value

    def _get_base_is_other_ancestor(self):
        if self._base_is_other_ancestor is None:
            if self.other_basis is None:
                return True
            self._base_is_other_ancestor = self.revision_graph.is_ancestor(
                self.base_rev_id, self.other_basis)
        return self._base_is_other_ancestor

    base_is_other_ancestor = property(_get_base_is_other_ancestor,
                                      _set_base_is_other_ancestor)

    @staticmethod
    def from_uncommitted(tree, other_tree, pb):
        """Return a Merger for uncommitted changes in other_tree.

        :param tree: The tree to merge into
        :param other_tree: The tree to get uncommitted changes from
        :param pb: A progress indicator
        """
        merger = Merger(tree.branch, other_tree, other_tree.basis_tree(), tree,
                        pb)
        merger.base_rev_id = merger.base_tree.get_revision_id()
        merger.other_rev_id = None
        merger.other_basis = merger.base_rev_id
        return merger

    @classmethod
    def from_mergeable(klass, tree, mergeable, pb):
        """Return a Merger for a bundle or merge directive.

        :param tree: The tree to merge changes into
        :param mergeable: A merge directive or bundle
        :param pb: A progress indicator
        """
        mergeable.install_revisions(tree.branch.repository)
        base_revision_id, other_revision_id, verified =\
            mergeable.get_merge_request(tree.branch.repository)
        revision_graph = tree.branch.repository.get_graph()
        if base_revision_id is not None:
            if (base_revision_id != _mod_revision.NULL_REVISION and
                revision_graph.is_ancestor(
                base_revision_id, tree.branch.last_revision())):
                base_revision_id = None
            else:
                warning('Performing cherrypick')
        merger = klass.from_revision_ids(pb, tree, other_revision_id,
                                         base_revision_id, revision_graph=
                                         revision_graph)
        return merger, verified

    @staticmethod
    def from_revision_ids(pb, tree, other, base=None, other_branch=None,
                          base_branch=None, revision_graph=None):
        """Return a Merger for revision-ids.

        :param tree: The tree to merge changes into
        :param other: The revision-id to use as OTHER
        :param base: The revision-id to use as BASE.  If not specified, will
            be auto-selected.
        :param other_branch: A branch containing the other revision-id.  If
            not supplied, tree.branch is used.
        :param base_branch: A branch containing the base revision-id.  If
            not supplied, other_branch or tree.branch will be used.
        :param revision_graph: If you have a revision_graph precomputed, pass
            it in, otherwise it will be created for you.
        :param pb: A progress indicator
        """
        merger = Merger(tree.branch, this_tree=tree, pb=pb,
                        revision_graph=revision_graph)
        if other_branch is None:
            other_branch = tree.branch
        merger.set_other_revision(other, other_branch)
        if base is None:
            merger.find_base()
        else:
            if base_branch is None:
                base_branch = other_branch
            merger.set_base_revision(base, base_branch)
        return merger

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
                raise errors.UncommittedChanges(self.this_tree)

    def compare_basis(self):
        try:
            basis_tree = self.revision_tree(self.this_tree.last_revision())
        except errors.NoSuchRevision:
            basis_tree = self.this_tree.basis_tree()
        changes = self.this_tree.changes_from(basis_tree)
        if not changes.has_changed():
            self.this_rev_id = self.this_basis

    def set_interesting_files(self, file_list):
        self.interesting_files = file_list

    def set_pending(self):
        if not self.base_is_ancestor or not self.base_is_other_ancestor or self.other_rev_id is None:
            return
        self._add_parent()

    def _add_parent(self):
        new_parents = self.this_tree.get_parent_ids() + [self.other_rev_id]
        new_parent_trees = []
        for revision_id in new_parents:
            try:
                tree = self.revision_tree(revision_id)
            except errors.NoSuchRevision:
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

    def _maybe_fetch(self, source, target, revision_id):
        if not source.repository.has_same_location(target.repository):
            target.fetch(source, revision_id)

    def find_base(self):
        revisions = [ensure_null(self.this_basis),
                     ensure_null(self.other_basis)]
        if NULL_REVISION in revisions:
            self.base_rev_id = NULL_REVISION
        else:
            self.base_rev_id, steps = self.revision_graph.find_unique_lca(
                revisions[0], revisions[1], count_steps=True)
            if self.base_rev_id == NULL_REVISION:
                raise UnrelatedBranches()
            if steps > 1:
                warning('Warning: criss-cross merge encountered.  See bzr'
                        ' help criss-cross.')
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

    def make_merger(self):
        kwargs = {'working_tree':self.this_tree, 'this_tree': self.this_tree,
                  'other_tree': self.other_tree,
                  'interesting_ids': self.interesting_ids,
                  'interesting_files': self.interesting_files,
                  'pp': self.pp,
                  'do_merge': False}
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
        if (not getattr(self.merge_type, 'supports_reverse_cherrypick', True)
            and not self.base_is_other_ancestor):
            raise errors.CannotReverseCherrypick()
        if self.merge_type.supports_cherrypick:
            kwargs['cherrypick'] = (not self.base_is_ancestor or
                                    not self.base_is_other_ancestor)
        return self.merge_type(pb=self._pb,
                               change_reporter=self.change_reporter,
                               **kwargs)

    def do_merge(self):
        self.this_tree.lock_tree_write()
        if self.base_tree is not None:
            self.base_tree.lock_read()
        if self.other_tree is not None:
            self.other_tree.lock_read()
        try:
            merge = self.make_merger()
            merge.do_merge()
            if self.recurse == 'down':
                for relpath, file_id in self.this_tree.iter_references():
                    sub_tree = self.this_tree.get_nested_tree(file_id, relpath)
                    other_revision = self.other_tree.get_reference_revision(
                        file_id, relpath)
                    if  other_revision == sub_tree.last_revision():
                        continue
                    sub_merge = Merger(sub_tree.branch, this_tree=sub_tree)
                    sub_merge.merge_type = self.merge_type
                    other_branch = self.other_branch.reference_parent(file_id, relpath)
                    sub_merge.set_other_revision(other_revision, other_branch)
                    base_revision = self.base_tree.get_reference_revision(file_id)
                    sub_merge.base_tree = \
                        sub_tree.branch.repository.revision_tree(base_revision)
                    sub_merge.base_rev_id = base_revision
                    sub_merge.do_merge()

        finally:
            if self.other_tree is not None:
                self.other_tree.unlock()
            if self.base_tree is not None:
                self.base_tree.unlock()
            self.this_tree.unlock()
        if len(merge.cooked_conflicts) == 0:
            if not self.ignore_zero and not is_quiet():
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
    supports_cherrypick = True
    supports_reverse_cherrypick = True
    winner_idx = {"this": 2, "other": 1, "conflict": 1}

    def __init__(self, working_tree, this_tree, base_tree, other_tree, 
                 interesting_ids=None, reprocess=False, show_base=False,
                 pb=DummyProgress(), pp=None, change_reporter=None,
                 interesting_files=None, do_merge=True,
                 cherrypick=False):
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
        if interesting_files is not None and interesting_ids is not None:
            raise ValueError(
                'specify either interesting_ids or interesting_files')
        self.interesting_ids = interesting_ids
        self.interesting_files = interesting_files
        self.this_tree = working_tree
        self.base_tree = base_tree
        self.other_tree = other_tree
        self._raw_conflicts = []
        self.cooked_conflicts = []
        self.reprocess = reprocess
        self.show_base = show_base
        self.pb = pb
        self.pp = pp
        self.change_reporter = change_reporter
        self.cherrypick = cherrypick
        if self.pp is None:
            self.pp = ProgressPhase("Merge phase", 3, self.pb)
        if do_merge:
            self.do_merge()

    def do_merge(self):
        self.this_tree.lock_tree_write()
        self.base_tree.lock_read()
        self.other_tree.lock_read()
        self.tt = TreeTransform(self.this_tree, self.pb)
        try:
            self.pp.next_phase()
            self._compute_transform()
            self.pp.next_phase()
            results = self.tt.apply(no_conflicts=True)
            self.write_modified(results)
            try:
                self.this_tree.add_conflicts(self.cooked_conflicts)
            except UnsupportedOperation:
                pass
        finally:
            self.tt.finalize()
            self.other_tree.unlock()
            self.base_tree.unlock()
            self.this_tree.unlock()
            self.pb.clear()

    def make_preview_transform(self):
        self.base_tree.lock_read()
        self.other_tree.lock_read()
        self.tt = TransformPreview(self.this_tree)
        try:
            self.pp.next_phase()
            self._compute_transform()
            self.pp.next_phase()
        finally:
            self.other_tree.unlock()
            self.base_tree.unlock()
            self.pb.clear()
        return self.tt

    def _compute_transform(self):
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
        if self.change_reporter is not None:
            from bzrlib import delta
            delta.report_changes(
                self.tt.iter_changes(), self.change_reporter)
        self.cook_conflicts(fs_conflicts)
        for conflict in self.cooked_conflicts:
            warning(conflict)

    def _entries3(self):
        """Gather data about files modified between three trees.

        Return a list of tuples of file_id, changed, parents3, names3,
        executable3.  changed is a boolean indicating whether the file contents
        or kind were changed.  parents3 is a tuple of parent ids for base,
        other and this.  names3 is a tuple of names for base, other and this.
        executable3 is a tuple of execute-bit values for base, other and this.
        """
        result = []
        iterator = self.other_tree.iter_changes(self.base_tree,
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
        other_root_file_id = self.other_tree.get_root_id()
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
        # "Ambiguous clean merge"
        if key_this == key_other:
            return "this"
        elif key_this == key_base:
            return "other"
        else:
            return "conflict"

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
        m3 = Merge3(base_lines, this_lines, other_lines,
                    is_cherrypick=self.cherrypick)
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
        winner = self._three_way(*executable)
        if winner == "conflict":
        # There must be a None in here, if we have a conflict, but we
        # need executability since file status was not deleted.
            if self.executable(self.other_tree, file_id) is None:
                winner = "this"
            else:
                winner = "other"
        if winner == 'this' and file_status != "modified":
            return
        trans_id = self.tt.trans_id_file_id(file_id)
        try:
            if self.tt.final_kind(trans_id) != "file":
                return
        except NoSuchFile:
            return
        if winner == "this":
            executability = this_executable
        else:
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
                if this_parent == other_parent:
                    raise AssertionError()
            except KeyError:
                this_parent = other_parent = \
                    self.tt.final_file_id(self.tt.final_parent(trans_id))
            try:
                this_name, other_name = conflicts['name conflict']
                if this_name == other_name:
                    raise AssertionError()
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
    supports_reverse_cherrypick = False
    history_based = True

    def _merged_lines(self, file_id):
        """Generate the merged lines.
        There is no distinction between lines that are meant to contain <<<<<<<
        and conflicts.
        """
        if self.cherrypick:
            base = self.base_tree
        else:
            base = None
        plan = self.this_tree.plan_file_merge(file_id, self.other_tree,
                                              base=base)
        if 'merge' in debug.debug_flags:
            plan = list(plan)
            trans_id = self.tt.trans_id_file_id(file_id)
            name = self.tt.final_name(trans_id) + '.plan'
            contents = ('%10s|%s' % l for l in plan)
            self.tt.new_file(name, self.tt.final_parent(trans_id), contents)
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


class LCAMerger(WeaveMerger):

    def _merged_lines(self, file_id):
        """Generate the merged lines.
        There is no distinction between lines that are meant to contain <<<<<<<
        and conflicts.
        """
        if self.cherrypick:
            base = self.base_tree
        else:
            base = None
        plan = self.this_tree.plan_file_lca_merge(file_id, self.other_tree,
                                                  base=base)
        if 'merge' in debug.debug_flags:
            plan = list(plan)
            trans_id = self.tt.trans_id_file_id(file_id)
            name = self.tt.final_name(trans_id) + '.plan'
            contents = ('%10s|%s' % l for l in plan)
            self.tt.new_file(name, self.tt.final_parent(trans_id), contents)
        textmerge = PlanWeaveMerge(plan, '<<<<<<< TREE\n',
            '>>>>>>> MERGE-SOURCE\n')
        return textmerge.merge_lines(self.reprocess)


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
        if interesting_ids:
            raise ValueError('Only supply interesting_ids'
                             ' or interesting_files')
        merger.interesting_files = interesting_files
    merger.show_base = show_base
    merger.reprocess = reprocess
    merger.other_rev_id = other_rev_id
    merger.other_basis = other_rev_id
    get_revision_id = getattr(base_tree, 'get_revision_id', None)
    if get_revision_id is None:
        get_revision_id = base_tree.last_revision
    merger.set_base_revision(get_revision_id(), this_branch)
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
        for text_a in plain_a[ai:a_cur]:
            yield "unchanged", text_a


class _PlanMergeBase(object):

    def __init__(self, a_rev, b_rev, vf, key_prefix):
        """Contructor.

        :param a_rev: Revision-id of one revision to merge
        :param b_rev: Revision-id of the other revision to merge
        :param vf: A VersionedFiles containing both revisions
        :param key_prefix: A prefix for accessing keys in vf, typically
            (file_id,).
        """
        self.a_rev = a_rev
        self.b_rev = b_rev
        self.vf = vf
        self._last_lines = None
        self._last_lines_revision_id = None
        self._cached_matching_blocks = {}
        self._key_prefix = key_prefix
        self._precache_tip_lines()

    def _precache_tip_lines(self):
        lines = self.get_lines([self.a_rev, self.b_rev])
        self.lines_a = lines[self.a_rev]
        self.lines_b = lines[self.b_rev]

    def get_lines(self, revisions):
        """Get lines for revisions from the backing VersionedFiles.
        
        :raises RevisionNotPresent: on absent texts.
        """
        keys = [(self._key_prefix + (rev,)) for rev in revisions]
        result = {}
        for record in self.vf.get_record_stream(keys, 'unordered', True):
            if record.storage_kind == 'absent':
                raise errors.RevisionNotPresent(record.key, self.vf)
            result[record.key[-1]] = osutils.split_lines(
                record.get_bytes_as('fulltext'))
        return result

    def plan_merge(self):
        """Generate a 'plan' for merging the two revisions.

        This involves comparing their texts and determining the cause of
        differences.  If text A has a line and text B does not, then either the
        line was added to text A, or it was deleted from B.  Once the causes
        are combined, they are written out in the format described in
        VersionedFile.plan_merge
        """
        blocks = self._get_matching_blocks(self.a_rev, self.b_rev)
        unique_a, unique_b = self._unique_lines(blocks)
        new_a, killed_b = self._determine_status(self.a_rev, unique_a)
        new_b, killed_a = self._determine_status(self.b_rev, unique_b)
        return self._iter_plan(blocks, new_a, killed_b, new_b, killed_a)

    def _iter_plan(self, blocks, new_a, killed_b, new_b, killed_a):
        last_i = 0
        last_j = 0
        for i, j, n in blocks:
            for a_index in range(last_i, i):
                if a_index in new_a:
                    if a_index in killed_b:
                        yield 'conflicted-a', self.lines_a[a_index]
                    else:
                        yield 'new-a', self.lines_a[a_index]
                else:
                    yield 'killed-b', self.lines_a[a_index]
            for b_index in range(last_j, j):
                if b_index in new_b:
                    if b_index in killed_a:
                        yield 'conflicted-b', self.lines_b[b_index]
                    else:
                        yield 'new-b', self.lines_b[b_index]
                else:
                    yield 'killed-a', self.lines_b[b_index]
            # handle common lines
            for a_index in range(i, i+n):
                yield 'unchanged', self.lines_a[a_index]
            last_i = i+n
            last_j = j+n

    def _get_matching_blocks(self, left_revision, right_revision):
        """Return a description of which sections of two revisions match.

        See SequenceMatcher.get_matching_blocks
        """
        cached = self._cached_matching_blocks.get((left_revision,
                                                   right_revision))
        if cached is not None:
            return cached
        if self._last_lines_revision_id == left_revision:
            left_lines = self._last_lines
            right_lines = self.get_lines([right_revision])[right_revision]
        else:
            lines = self.get_lines([left_revision, right_revision])
            left_lines = lines[left_revision]
            right_lines = lines[right_revision]
        self._last_lines = right_lines
        self._last_lines_revision_id = right_revision
        matcher = patiencediff.PatienceSequenceMatcher(None, left_lines,
                                                       right_lines)
        return matcher.get_matching_blocks()

    def _unique_lines(self, matching_blocks):
        """Analyse matching_blocks to determine which lines are unique

        :return: a tuple of (unique_left, unique_right), where the values are
            sets of line numbers of unique lines.
        """
        last_i = 0
        last_j = 0
        unique_left = []
        unique_right = []
        for i, j, n in matching_blocks:
            unique_left.extend(range(last_i, i))
            unique_right.extend(range(last_j, j))
            last_i = i + n
            last_j = j + n
        return unique_left, unique_right

    @staticmethod
    def _subtract_plans(old_plan, new_plan):
        """Remove changes from new_plan that came from old_plan.

        It is assumed that the difference between the old_plan and new_plan
        is their choice of 'b' text.

        All lines from new_plan that differ from old_plan are emitted
        verbatim.  All lines from new_plan that match old_plan but are
        not about the 'b' revision are emitted verbatim.

        Lines that match and are about the 'b' revision are the lines we
        don't want, so we convert 'killed-b' -> 'unchanged', and 'new-b'
        is skipped entirely.
        """
        matcher = patiencediff.PatienceSequenceMatcher(None, old_plan,
                                                       new_plan)
        last_j = 0
        for i, j, n in matcher.get_matching_blocks():
            for jj in range(last_j, j):
                yield new_plan[jj]
            for jj in range(j, j+n):
                plan_line = new_plan[jj]
                if plan_line[0] == 'new-b':
                    pass
                elif plan_line[0] == 'killed-b':
                    yield 'unchanged', plan_line[1]
                else:
                    yield plan_line
            last_j = j + n


class _PlanMerge(_PlanMergeBase):
    """Plan an annotate merge using on-the-fly annotation"""

    def __init__(self, a_rev, b_rev, vf, key_prefix):
        super(_PlanMerge, self).__init__(a_rev, b_rev, vf, key_prefix)
        self.a_key = self._key_prefix + (self.a_rev,)
        self.b_key = self._key_prefix + (self.b_rev,)
        self.graph = Graph(self.vf)
        heads = self.graph.heads((self.a_key, self.b_key))
        if len(heads) == 1:
            # one side dominates, so we can just return its values, yay for
            # per-file graphs
            # Ideally we would know that before we get this far
            self._head_key = heads.pop()
            if self._head_key == self.a_key:
                other = b_rev
            else:
                other = a_rev
            mutter('found dominating revision for %s\n%s > %s', self.vf,
                   self._head_key[-1], other)
            self._weave = None
        else:
            self._head_key = None
            self._build_weave()

    def _precache_tip_lines(self):
        # Turn this into a no-op, because we will do this later
        pass

    def _find_recursive_lcas(self):
        """Find all the ancestors back to a unique lca"""
        cur_ancestors = (self.a_key, self.b_key)
        # graph.find_lca(uncommon, keys) now returns plain NULL_REVISION,
        # rather than a key tuple. We will just map that directly to no common
        # ancestors.
        parent_map = {}
        while True:
            next_lcas = self.graph.find_lca(*cur_ancestors)
            # Map a plain NULL_REVISION to a simple no-ancestors
            if next_lcas == set([NULL_REVISION]):
                next_lcas = ()
            # Order the lca's based on when they were merged into the tip
            # While the actual merge portion of weave merge uses a set() of
            # active revisions, the order of insertion *does* effect the
            # implicit ordering of the texts.
            for rev_key in cur_ancestors:
                ordered_parents = tuple(self.graph.find_merge_order(rev_key,
                                                                    next_lcas))
                parent_map[rev_key] = ordered_parents
            if len(next_lcas) == 0:
                break
            elif len(next_lcas) == 1:
                parent_map[list(next_lcas)[0]] = ()
                break
            elif len(next_lcas) > 2:
                # More than 2 lca's, fall back to grabbing all nodes between
                # this and the unique lca.
                mutter('More than 2 LCAs, falling back to all nodes for:'
                       ' %s, %s\n=> %s', self.a_key, self.b_key, cur_ancestors)
                cur_lcas = next_lcas
                while len(cur_lcas) > 1:
                    cur_lcas = self.graph.find_lca(*cur_lcas)
                if len(cur_lcas) == 0:
                    # No common base to find, use the full ancestry
                    unique_lca = None
                else:
                    unique_lca = list(cur_lcas)[0]
                    if unique_lca == NULL_REVISION:
                        # find_lca will return a plain 'NULL_REVISION' rather
                        # than a key tuple when there is no common ancestor, we
                        # prefer to just use None, because it doesn't confuse
                        # _get_interesting_texts()
                        unique_lca = None
                parent_map.update(self._find_unique_parents(next_lcas,
                                                            unique_lca))
                break
            cur_ancestors = next_lcas
        return parent_map

    def _find_unique_parents(self, tip_keys, base_key):
        """Find ancestors of tip that aren't ancestors of base.
        
        :param tip_keys: Nodes that are interesting
        :param base_key: Cull all ancestors of this node
        :return: The parent map for all revisions between tip_keys and
            base_key. base_key will be included. References to nodes outside of
            the ancestor set will also be removed.
        """
        # TODO: this would be simpler if find_unique_ancestors took a list
        #       instead of a single tip, internally it supports it, but it
        #       isn't a "backwards compatible" api change.
        if base_key is None:
            parent_map = dict(self.graph.iter_ancestry(tip_keys))
            # We remove NULL_REVISION because it isn't a proper tuple key, and
            # thus confuses things like _get_interesting_texts, and our logic
            # to add the texts into the memory weave.
            if NULL_REVISION in parent_map:
                parent_map.pop(NULL_REVISION)
        else:
            interesting = set()
            for tip in tip_keys:
                interesting.update(
                    self.graph.find_unique_ancestors(tip, [base_key]))
            parent_map = self.graph.get_parent_map(interesting)
            parent_map[base_key] = ()
        culled_parent_map, child_map, tails = self._remove_external_references(
            parent_map)
        # Remove all the tails but base_key
        if base_key is not None:
            tails.remove(base_key)
            self._prune_tails(culled_parent_map, child_map, tails)
        # Now remove all the uninteresting 'linear' regions
        simple_map = _mod_graph.collapse_linear_regions(culled_parent_map)
        return simple_map

    @staticmethod
    def _remove_external_references(parent_map):
        """Remove references that go outside of the parent map.

        :param parent_map: Something returned from Graph.get_parent_map(keys)
        :return: (filtered_parent_map, child_map, tails)
            filtered_parent_map is parent_map without external references
            child_map is the {parent_key: [child_keys]} mapping
            tails is a list of nodes that do not have any parents in the map
        """
        # TODO: The basic effect of this function seems more generic than
        #       _PlanMerge. But the specific details of building a child_map,
        #       and computing tails seems very specific to _PlanMerge.
        #       Still, should this be in Graph land?
        filtered_parent_map = {}
        child_map = {}
        tails = []
        for key, parent_keys in parent_map.iteritems():
            culled_parent_keys = [p for p in parent_keys if p in parent_map]
            if not culled_parent_keys:
                tails.append(key)
            for parent_key in culled_parent_keys:
                child_map.setdefault(parent_key, []).append(key)
            # TODO: Do we want to do this, it adds overhead for every node,
            #       just to say that the node has no children
            child_map.setdefault(key, [])
            filtered_parent_map[key] = culled_parent_keys
        return filtered_parent_map, child_map, tails

    @staticmethod
    def _prune_tails(parent_map, child_map, tails_to_remove):
        """Remove tails from the parent map.
        
        This will remove the supplied revisions until no more children have 0
        parents.

        :param parent_map: A dict of {child: [parents]}, this dictionary will
            be modified in place.
        :param tails_to_remove: A list of tips that should be removed,
            this list will be consumed
        :param child_map: The reverse dict of parent_map ({parent: [children]})
            this dict will be modified
        :return: None, parent_map will be modified in place.
        """
        while tails_to_remove:
            next = tails_to_remove.pop()
            parent_map.pop(next)
            children = child_map.pop(next)
            for child in children:
                child_parents = parent_map[child]
                child_parents.remove(next)
                if len(child_parents) == 0:
                    tails_to_remove.append(child)

    def _get_interesting_texts(self, parent_map):
        """Return a dict of texts we are interested in.

        Note that the input is in key tuples, but the output is in plain
        revision ids.

        :param parent_map: The output from _find_recursive_lcas
        :return: A dict of {'revision_id':lines} as returned by
            _PlanMergeBase.get_lines()
        """
        all_revision_keys = set(parent_map)
        all_revision_keys.add(self.a_key)
        all_revision_keys.add(self.b_key)

        # Everything else is in 'keys' but get_lines is in 'revision_ids'
        all_texts = self.get_lines([k[-1] for k in all_revision_keys])
        return all_texts

    def _build_weave(self):
        from bzrlib import weave
        self._weave = weave.Weave(weave_name='in_memory_weave',
                                  allow_reserved=True)
        parent_map = self._find_recursive_lcas()

        all_texts = self._get_interesting_texts(parent_map)

        # Note: Unfortunately, the order given by topo_sort will effect the
        # ordering resolution in the output. Specifically, if you add A then B,
        # then in the output text A lines will show up before B lines. And, of
        # course, topo_sort doesn't guarantee any real ordering.
        # So we use merge_sort, and add a fake node on the tip.
        # This ensures that left-hand parents will always be inserted into the
        # weave before right-hand parents.
        tip_key = self._key_prefix + (_mod_revision.CURRENT_REVISION,)
        parent_map[tip_key] = (self.a_key, self.b_key)

        for seq_num, key, depth, eom in reversed(tsort.merge_sort(parent_map,
                                                                  tip_key)):
            if key == tip_key:
                continue
        # for key in tsort.topo_sort(parent_map):
            parent_keys = parent_map[key]
            revision_id = key[-1]
            parent_ids = [k[-1] for k in parent_keys]
            self._weave.add_lines(revision_id, parent_ids,
                                  all_texts[revision_id])

    def plan_merge(self):
        """Generate a 'plan' for merging the two revisions.

        This involves comparing their texts and determining the cause of
        differences.  If text A has a line and text B does not, then either the
        line was added to text A, or it was deleted from B.  Once the causes
        are combined, they are written out in the format described in
        VersionedFile.plan_merge
        """
        if self._head_key is not None: # There was a single head
            if self._head_key == self.a_key:
                plan = 'new-a'
            else:
                if self._head_key != self.b_key:
                    raise AssertionError('There was an invalid head: %s != %s'
                                         % (self.b_key, self._head_key))
                plan = 'new-b'
            head_rev = self._head_key[-1]
            lines = self.get_lines([head_rev])[head_rev]
            return ((plan, line) for line in lines)
        return self._weave.plan_merge(self.a_rev, self.b_rev)


class _PlanLCAMerge(_PlanMergeBase):
    """
    This merge algorithm differs from _PlanMerge in that:
    1. comparisons are done against LCAs only
    2. cases where a contested line is new versus one LCA but old versus
       another are marked as conflicts, by emitting the line as conflicted-a
       or conflicted-b.

    This is faster, and hopefully produces more useful output.
    """

    def __init__(self, a_rev, b_rev, vf, key_prefix, graph):
        _PlanMergeBase.__init__(self, a_rev, b_rev, vf, key_prefix)
        lcas = graph.find_lca(key_prefix + (a_rev,), key_prefix + (b_rev,))
        self.lcas = set()
        for lca in lcas:
            if lca == NULL_REVISION:
                self.lcas.add(lca)
            else:
                self.lcas.add(lca[-1])
        for lca in self.lcas:
            if _mod_revision.is_null(lca):
                lca_lines = []
            else:
                lca_lines = self.get_lines([lca])[lca]
            matcher = patiencediff.PatienceSequenceMatcher(None, self.lines_a,
                                                           lca_lines)
            blocks = list(matcher.get_matching_blocks())
            self._cached_matching_blocks[(a_rev, lca)] = blocks
            matcher = patiencediff.PatienceSequenceMatcher(None, self.lines_b,
                                                           lca_lines)
            blocks = list(matcher.get_matching_blocks())
            self._cached_matching_blocks[(b_rev, lca)] = blocks

    def _determine_status(self, revision_id, unique_line_numbers):
        """Determines the status unique lines versus all lcas.

        Basically, determines why the line is unique to this revision.

        A line may be determined new, killed, or both.

        If a line is determined new, that means it was not present in at least
        one LCA, and is not present in the other merge revision.

        If a line is determined killed, that means the line was present in
        at least one LCA.

        If a line is killed and new, this indicates that the two merge
        revisions contain differing conflict resolutions.
        :param revision_id: The id of the revision in which the lines are
            unique
        :param unique_line_numbers: The line numbers of unique lines.
        :return a tuple of (new_this, killed_other):
        """
        new = set()
        killed = set()
        unique_line_numbers = set(unique_line_numbers)
        for lca in self.lcas:
            blocks = self._get_matching_blocks(revision_id, lca)
            unique_vs_lca, _ignored = self._unique_lines(blocks)
            new.update(unique_line_numbers.intersection(unique_vs_lca))
            killed.update(unique_line_numbers.difference(unique_vs_lca))
        return new, killed
