# Copyright (C) 2005, 2006, 2007 Canonical Ltd
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
from StringIO import StringIO

from bzrlib import (
    conflicts,
    errors,
    knit,
    merge as _mod_merge,
    option,
    progress,
    transform,
    versionedfile,
    )
from bzrlib.branch import Branch
from bzrlib.conflicts import ConflictList, TextConflict
from bzrlib.errors import UnrelatedBranches, NoCommits, BzrCommandError
from bzrlib.merge import transform_tree, merge_inner, _PlanMerge
from bzrlib.osutils import pathjoin, file_kind
from bzrlib.tests import TestCaseWithTransport, TestCaseWithMemoryTransport
from bzrlib.trace import (enable_test_log, disable_test_log)
from bzrlib.workingtree import WorkingTree


class TestMerge(TestCaseWithTransport):
    """Test appending more than one revision"""

    def test_pending(self):
        wt = self.make_branch_and_tree('.')
        rev_a = wt.commit("lala!")
        self.assertEqual([rev_a], wt.get_parent_ids())
        self.assertRaises(errors.PointlessMerge, wt.merge_from_branch,
                          wt.branch)
        self.assertEqual([rev_a], wt.get_parent_ids())
        return wt

    def test_undo(self):
        wt = self.make_branch_and_tree('.')
        wt.commit("lala!")
        wt.commit("haha!")
        wt.commit("blabla!")
        wt.merge_from_branch(wt.branch, wt.branch.get_rev_id(2),
                             wt.branch.get_rev_id(1))

    def test_nocommits(self):
        wt = self.test_pending()
        wt2 = self.make_branch_and_tree('branch2')
        self.assertRaises(NoCommits, wt.merge_from_branch, wt2.branch)
        return wt, wt2

    def test_unrelated(self):
        wt, wt2 = self.test_nocommits()
        wt2.commit("blah")
        self.assertRaises(UnrelatedBranches, wt.merge_from_branch, wt2.branch)
        return wt2

    def test_merge_one_file(self):
        """Do a partial merge of a tree which should not affect tree parents."""
        wt1 = self.make_branch_and_tree('branch1')
        tip = wt1.commit('empty commit')
        wt2 = self.make_branch_and_tree('branch2')
        wt2.pull(wt1.branch)
        file('branch1/foo', 'wb').write('foo')
        file('branch1/bar', 'wb').write('bar')
        wt1.add('foo')
        wt1.add('bar')
        wt1.commit('add foobar')
        os.chdir('branch2')
        self.run_bzr('merge ../branch1/baz', retcode=3)
        self.run_bzr('merge ../branch1/foo')
        self.failUnlessExists('foo')
        self.failIfExists('bar')
        wt2 = WorkingTree.open('.') # opens branch2
        self.assertEqual([tip], wt2.get_parent_ids())
        
    def test_pending_with_null(self):
        """When base is forced to revno 0, parent_ids are set"""
        wt2 = self.test_unrelated()
        wt1 = WorkingTree.open('.')
        br1 = wt1.branch
        br1.fetch(wt2.branch)
        # merge all of branch 2 into branch 1 even though they 
        # are not related.
        wt1.merge_from_branch(wt2.branch, wt2.last_revision(), 'null:')
        self.assertEqual([br1.last_revision(), wt2.branch.last_revision()],
            wt1.get_parent_ids())
        return (wt1, wt2.branch)

    def test_two_roots(self):
        """Merge base is sane when two unrelated branches are merged"""
        wt1, br2 = self.test_pending_with_null()
        wt1.commit("blah")
        wt1.lock_read()
        try:
            last = wt1.branch.last_revision()
            last2 = br2.last_revision()
            graph = wt1.branch.repository.get_graph()
            self.assertEqual(last2, graph.find_unique_lca(last, last2))
        finally:
            wt1.unlock()

    def test_create_rename(self):
        """Rename an inventory entry while creating the file"""
        tree =self.make_branch_and_tree('.')
        file('name1', 'wb').write('Hello')
        tree.add('name1')
        tree.commit(message="hello")
        tree.rename_one('name1', 'name2')
        os.unlink('name2')
        transform_tree(tree, tree.branch.basis_tree())

    def test_layered_rename(self):
        """Rename both child and parent at same time"""
        tree =self.make_branch_and_tree('.')
        os.mkdir('dirname1')
        tree.add('dirname1')
        filename = pathjoin('dirname1', 'name1')
        file(filename, 'wb').write('Hello')
        tree.add(filename)
        tree.commit(message="hello")
        filename2 = pathjoin('dirname1', 'name2')
        tree.rename_one(filename, filename2)
        tree.rename_one('dirname1', 'dirname2')
        transform_tree(tree, tree.branch.basis_tree())

    def test_ignore_zero_merge_inner(self):
        # Test that merge_inner's ignore zero parameter is effective
        tree_a =self.make_branch_and_tree('a')
        tree_a.commit(message="hello")
        dir_b = tree_a.bzrdir.sprout('b')
        tree_b = dir_b.open_workingtree()
        tree_b.lock_write()
        self.addCleanup(tree_b.unlock)
        tree_a.commit(message="hello again")
        log = StringIO()
        merge_inner(tree_b.branch, tree_a, tree_b.basis_tree(), 
                    this_tree=tree_b, ignore_zero=True)
        log = self._get_log(keep_log_file=True)
        self.failUnless('All changes applied successfully.\n' not in log)
        tree_b.revert()
        merge_inner(tree_b.branch, tree_a, tree_b.basis_tree(), 
                    this_tree=tree_b, ignore_zero=False)
        log = self._get_log(keep_log_file=True)
        self.failUnless('All changes applied successfully.\n' in log)

    def test_merge_inner_conflicts(self):
        tree_a = self.make_branch_and_tree('a')
        tree_a.set_conflicts(ConflictList([TextConflict('patha')]))
        merge_inner(tree_a.branch, tree_a, tree_a, this_tree=tree_a)
        self.assertEqual(1, len(tree_a.conflicts()))

    def test_rmdir_conflict(self):
        tree_a = self.make_branch_and_tree('a')
        self.build_tree(['a/b/'])
        tree_a.add('b', 'b-id')
        tree_a.commit('added b')
        # basis_tree() is only guaranteed to be valid as long as it is actually
        # the basis tree. This mutates the tree after grabbing basis, so go to
        # the repository.
        base_tree = tree_a.branch.repository.revision_tree(tree_a.last_revision())
        tree_z = tree_a.bzrdir.sprout('z').open_workingtree()
        self.build_tree(['a/b/c'])
        tree_a.add('b/c')
        tree_a.commit('added c')
        os.rmdir('z/b')
        tree_z.commit('removed b')
        merge_inner(tree_z.branch, tree_a, base_tree, this_tree=tree_z)
        self.assertEqual([
            conflicts.MissingParent('Created directory', 'b', 'b-id'),
            conflicts.UnversionedParent('Versioned directory', 'b', 'b-id')],
            tree_z.conflicts())
        merge_inner(tree_a.branch, tree_z.basis_tree(), base_tree,
                    this_tree=tree_a)
        self.assertEqual([
            conflicts.DeletingParent('Not deleting', 'b', 'b-id'),
            conflicts.UnversionedParent('Versioned directory', 'b', 'b-id')],
            tree_a.conflicts())

    def test_nested_merge(self):
        tree = self.make_branch_and_tree('tree',
            format='dirstate-with-subtree')
        sub_tree = self.make_branch_and_tree('tree/sub-tree',
            format='dirstate-with-subtree')
        sub_tree.set_root_id('sub-tree-root')
        self.build_tree_contents([('tree/sub-tree/file', 'text1')])
        sub_tree.add('file')
        sub_tree.commit('foo')
        tree.add_reference(sub_tree)
        tree.commit('set text to 1')
        tree2 = tree.bzrdir.sprout('tree2').open_workingtree()
        # modify the file in the subtree
        self.build_tree_contents([('tree2/sub-tree/file', 'text2')])
        # and merge the changes from the diverged subtree into the containing
        # tree
        tree2.commit('changed file text')
        tree.merge_from_branch(tree2.branch)
        self.assertFileEqual('text2', 'tree/sub-tree/file')

    def test_merge_with_missing(self):
        tree_a = self.make_branch_and_tree('tree_a')
        self.build_tree_contents([('tree_a/file', 'content_1')])
        tree_a.add('file')
        tree_a.commit('commit base')
        # basis_tree() is only guaranteed to be valid as long as it is actually
        # the basis tree. This mutates the tree after grabbing basis, so go to
        # the repository.
        base_tree = tree_a.branch.repository.revision_tree(tree_a.last_revision())
        tree_b = tree_a.bzrdir.sprout('tree_b').open_workingtree()
        self.build_tree_contents([('tree_a/file', 'content_2')])
        tree_a.commit('commit other')
        other_tree = tree_a.basis_tree()
        os.unlink('tree_b/file')
        merge_inner(tree_b.branch, other_tree, base_tree, this_tree=tree_b)

    def test_merge_kind_change(self):
        tree_a = self.make_branch_and_tree('tree_a')
        self.build_tree_contents([('tree_a/file', 'content_1')])
        tree_a.add('file', 'file-id')
        tree_a.commit('added file')
        tree_b = tree_a.bzrdir.sprout('tree_b').open_workingtree()
        os.unlink('tree_a/file')
        self.build_tree(['tree_a/file/'])
        tree_a.commit('changed file to directory')
        tree_b.merge_from_branch(tree_a.branch)
        self.assertEqual('directory', file_kind('tree_b/file'))
        tree_b.revert()
        self.assertEqual('file', file_kind('tree_b/file'))
        self.build_tree_contents([('tree_b/file', 'content_2')])
        tree_b.commit('content change')
        tree_b.merge_from_branch(tree_a.branch)
        self.assertEqual(tree_b.conflicts(),
                         [conflicts.ContentsConflict('file',
                          file_id='file-id')])
    
    def test_merge_type_registry(self):
        merge_type_option = option.Option.OPTIONS['merge-type']
        self.assertFalse('merge4' in [x[0] for x in 
                        merge_type_option.iter_switches()])
        registry = _mod_merge.get_merge_type_registry()
        registry.register_lazy('merge4', 'bzrlib.merge', 'Merge4Merger',
                               'time-travelling merge')
        self.assertTrue('merge4' in [x[0] for x in 
                        merge_type_option.iter_switches()])
        registry.remove('merge4')
        self.assertFalse('merge4' in [x[0] for x in 
                        merge_type_option.iter_switches()])

    def test_merge_other_moves_we_deleted(self):
        tree_a = self.make_branch_and_tree('A')
        tree_a.lock_write()
        self.addCleanup(tree_a.unlock)
        self.build_tree(['A/a'])
        tree_a.add('a')
        tree_a.commit('1', rev_id='rev-1')
        tree_a.flush()
        tree_a.rename_one('a', 'b')
        tree_a.commit('2')
        bzrdir_b = tree_a.bzrdir.sprout('B', revision_id='rev-1')
        tree_b = bzrdir_b.open_workingtree()
        tree_b.lock_write()
        self.addCleanup(tree_b.unlock)
        os.unlink('B/a')
        tree_b.commit('3')
        try:
            tree_b.merge_from_branch(tree_a.branch)
        except AttributeError:
            self.fail('tried to join a path when name was None')

    def test_merge_uncommitted_otherbasis_ancestor_of_thisbasis(self):
        tree_a = self.make_branch_and_tree('a')
        self.build_tree(['a/file_1', 'a/file_2'])
        tree_a.add(['file_1'])
        tree_a.commit('commit 1')
        tree_a.add(['file_2'])
        tree_a.commit('commit 2')
        tree_b = tree_a.bzrdir.sprout('b').open_workingtree()
        tree_b.rename_one('file_1', 'renamed')
        merger = _mod_merge.Merger.from_uncommitted(tree_a, tree_b,
                                                    progress.DummyProgress())
        merger.merge_type = _mod_merge.Merge3Merger
        merger.do_merge()
        self.assertEqual(tree_a.get_parent_ids(), [tree_b.last_revision()])

    def test_merge_uncommitted_otherbasis_ancestor_of_thisbasis_weave(self):
        tree_a = self.make_branch_and_tree('a')
        self.build_tree(['a/file_1', 'a/file_2'])
        tree_a.add(['file_1'])
        tree_a.commit('commit 1')
        tree_a.add(['file_2'])
        tree_a.commit('commit 2')
        tree_b = tree_a.bzrdir.sprout('b').open_workingtree()
        tree_b.rename_one('file_1', 'renamed')
        merger = _mod_merge.Merger.from_uncommitted(tree_a, tree_b,
                                                    progress.DummyProgress())
        merger.merge_type = _mod_merge.WeaveMerger
        merger.do_merge()
        self.assertEqual(tree_a.get_parent_ids(), [tree_b.last_revision()])

    def prepare_cherrypick(self):
        """Prepare a pair of trees for cherrypicking tests.

        Both trees have a file, 'file'.
        rev1 sets content to 'a'.
        rev2b adds 'b'.
        rev3b adds 'c'.
        A full merge of rev2b and rev3b into this_tree would add both 'b' and
        'c'.  A successful cherrypick of rev2b-rev3b into this_tree will add
        'c', but not 'b'.
        """
        this_tree = self.make_branch_and_tree('this')
        self.build_tree_contents([('this/file', "a\n")])
        this_tree.add('file')
        this_tree.commit('rev1')
        other_tree = this_tree.bzrdir.sprout('other').open_workingtree()
        self.build_tree_contents([('other/file', "a\nb\n")])
        other_tree.commit('rev2b', rev_id='rev2b')
        self.build_tree_contents([('other/file', "c\na\nb\n")])
        other_tree.commit('rev3b', rev_id='rev3b')
        this_tree.lock_write()
        self.addCleanup(this_tree.unlock)
        return this_tree, other_tree

    def test_weave_cherrypick(self):
        this_tree, other_tree = self.prepare_cherrypick()
        merger = _mod_merge.Merger.from_revision_ids(progress.DummyProgress(),
            this_tree, 'rev3b', 'rev2b', other_tree.branch)
        merger.merge_type = _mod_merge.WeaveMerger
        merger.do_merge()
        self.assertFileEqual('c\na\n', 'this/file')

    def test_weave_cannot_reverse_cherrypick(self):
        this_tree, other_tree = self.prepare_cherrypick()
        merger = _mod_merge.Merger.from_revision_ids(progress.DummyProgress(),
            this_tree, 'rev2b', 'rev3b', other_tree.branch)
        merger.merge_type = _mod_merge.WeaveMerger
        self.assertRaises(errors.CannotReverseCherrypick, merger.do_merge)

    def test_merge3_can_reverse_cherrypick(self):
        this_tree, other_tree = self.prepare_cherrypick()
        merger = _mod_merge.Merger.from_revision_ids(progress.DummyProgress(),
            this_tree, 'rev2b', 'rev3b', other_tree.branch)
        merger.merge_type = _mod_merge.Merge3Merger
        merger.do_merge()

    def test_merge3_will_detect_cherrypick(self):
        this_tree = self.make_branch_and_tree('this')
        self.build_tree_contents([('this/file', "a\n")])
        this_tree.add('file')
        this_tree.commit('rev1')
        other_tree = this_tree.bzrdir.sprout('other').open_workingtree()
        self.build_tree_contents([('other/file', "a\nb\n")])
        other_tree.commit('rev2b', rev_id='rev2b')
        self.build_tree_contents([('other/file', "a\nb\nc\n")])
        other_tree.commit('rev3b', rev_id='rev3b')
        this_tree.lock_write()
        self.addCleanup(this_tree.unlock)

        merger = _mod_merge.Merger.from_revision_ids(progress.DummyProgress(),
            this_tree, 'rev3b', 'rev2b', other_tree.branch)
        merger.merge_type = _mod_merge.Merge3Merger
        merger.do_merge()
        self.assertFileEqual('a\n'
                             '<<<<<<< TREE\n'
                             '=======\n'
                             'c\n'
                             '>>>>>>> MERGE-SOURCE\n',
                             'this/file')

    def test_make_merger(self):
        this_tree = self.make_branch_and_tree('this')
        this_tree.commit('rev1', rev_id='rev1')
        other_tree = this_tree.bzrdir.sprout('other').open_workingtree()
        this_tree.commit('rev2', rev_id='rev2a')
        other_tree.commit('rev2', rev_id='rev2b')
        this_tree.lock_write()
        self.addCleanup(this_tree.unlock)
        merger = _mod_merge.Merger.from_revision_ids(progress.DummyProgress,
            this_tree, 'rev2b', other_branch=other_tree.branch)
        merger.merge_type = _mod_merge.Merge3Merger
        tree_merger = merger.make_merger()
        self.assertIs(_mod_merge.Merge3Merger, tree_merger.__class__)
        self.assertEqual('rev2b', tree_merger.other_tree.get_revision_id())
        self.assertEqual('rev1', tree_merger.base_tree.get_revision_id())

    def test_make_preview_transform(self):
        this_tree = self.make_branch_and_tree('this')
        self.build_tree_contents([('this/file', '1\n')])
        this_tree.add('file', 'file-id')
        this_tree.commit('rev1', rev_id='rev1')
        other_tree = this_tree.bzrdir.sprout('other').open_workingtree()
        self.build_tree_contents([('this/file', '1\n2a\n')])
        this_tree.commit('rev2', rev_id='rev2a')
        self.build_tree_contents([('other/file', '2b\n1\n')])
        other_tree.commit('rev2', rev_id='rev2b')
        this_tree.lock_write()
        self.addCleanup(this_tree.unlock)
        merger = _mod_merge.Merger.from_revision_ids(progress.DummyProgress(),
            this_tree, 'rev2b', other_branch=other_tree.branch)
        merger.merge_type = _mod_merge.Merge3Merger
        tree_merger = merger.make_merger()
        tt = tree_merger.make_preview_transform()
        self.addCleanup(tt.finalize)
        preview_tree = tt.get_preview_tree()
        tree_file = this_tree.get_file('file-id')
        try:
            self.assertEqual('1\n2a\n', tree_file.read())
        finally:
            tree_file.close()
        preview_file = preview_tree.get_file('file-id')
        try:
            self.assertEqual('2b\n1\n2a\n', preview_file.read())
        finally:
            preview_file.close()

    def test_do_merge(self):
        this_tree = self.make_branch_and_tree('this')
        self.build_tree_contents([('this/file', '1\n')])
        this_tree.add('file', 'file-id')
        this_tree.commit('rev1', rev_id='rev1')
        other_tree = this_tree.bzrdir.sprout('other').open_workingtree()
        self.build_tree_contents([('this/file', '1\n2a\n')])
        this_tree.commit('rev2', rev_id='rev2a')
        self.build_tree_contents([('other/file', '2b\n1\n')])
        other_tree.commit('rev2', rev_id='rev2b')
        this_tree.lock_write()
        self.addCleanup(this_tree.unlock)
        merger = _mod_merge.Merger.from_revision_ids(progress.DummyProgress(),
            this_tree, 'rev2b', other_branch=other_tree.branch)
        merger.merge_type = _mod_merge.Merge3Merger
        tree_merger = merger.make_merger()
        tt = tree_merger.do_merge()
        tree_file = this_tree.get_file('file-id')
        try:
            self.assertEqual('2b\n1\n2a\n', tree_file.read())
        finally:
            tree_file.close()

    def test_merge_add_into_deleted_root(self):
        # Yes, people actually do this.  And report bugs if it breaks.
        source = self.make_branch_and_tree('source', format='rich-root-pack')
        self.build_tree(['source/foo/'])
        source.add('foo', 'foo-id')
        source.commit('Add foo')
        target = source.bzrdir.sprout('target').open_workingtree()
        subtree = target.extract('foo-id')
        subtree.commit('Delete root')
        self.build_tree(['source/bar'])
        source.add('bar', 'bar-id')
        source.commit('Add bar')
        subtree.merge_from_branch(source.branch)


class TestPlanMerge(TestCaseWithMemoryTransport):

    def setUp(self):
        TestCaseWithMemoryTransport.setUp(self)
        mapper = versionedfile.PrefixMapper()
        factory = knit.make_file_factory(True, mapper)
        self.vf = factory(self.get_transport())
        self.plan_merge_vf = versionedfile._PlanMergeVersionedFile('root')
        self.plan_merge_vf.fallback_versionedfiles.append(self.vf)

    def add_version(self, key, parents, text):
        self.vf.add_lines(key, parents, [c+'\n' for c in text])

    def add_rev(self, prefix, revision_id, parents, text):
        self.add_version((prefix, revision_id), [(prefix, p) for p in parents],
                         text)

    def add_uncommitted_version(self, key, parents, text):
        self.plan_merge_vf.add_lines(key, parents,
                                     [c+'\n' for c in text])

    def setup_plan_merge(self):
        self.add_rev('root', 'A', [], 'abc')
        self.add_rev('root', 'B', ['A'], 'acehg')
        self.add_rev('root', 'C', ['A'], 'fabg')
        return _PlanMerge('B', 'C', self.plan_merge_vf, ('root',))

    def setup_plan_merge_uncommitted(self):
        self.add_version(('root', 'A'), [], 'abc')
        self.add_uncommitted_version(('root', 'B:'), [('root', 'A')], 'acehg')
        self.add_uncommitted_version(('root', 'C:'), [('root', 'A')], 'fabg')
        return _PlanMerge('B:', 'C:', self.plan_merge_vf, ('root',))

    def test_unique_lines(self):
        plan = self.setup_plan_merge()
        self.assertEqual(plan._unique_lines(
            plan._get_matching_blocks('B', 'C')),
            ([1, 2, 3], [0, 2]))

    def test_plan_merge(self):
        self.setup_plan_merge()
        plan = self.plan_merge_vf.plan_merge('B', 'C')
        self.assertEqual([
                          ('new-b', 'f\n'),
                          ('unchanged', 'a\n'),
                          ('killed-a', 'b\n'),
                          ('killed-b', 'c\n'),
                          ('new-a', 'e\n'),
                          ('new-a', 'h\n'),
                          ('new-a', 'g\n'),
                          ('new-b', 'g\n')],
                         list(plan))

    def test_plan_merge_cherrypick(self):
        self.add_rev('root', 'A', [], 'abc')
        self.add_rev('root', 'B', ['A'], 'abcde')
        self.add_rev('root', 'C', ['A'], 'abcefg')
        self.add_rev('root', 'D', ['A', 'B', 'C'], 'abcdegh')
        my_plan = _PlanMerge('B', 'D', self.plan_merge_vf, ('root',))
        # We shortcut when one text supersedes the other in the per-file graph.
        # We don't actually need to compare the texts at this point.
        self.assertEqual([
                          ('new-b', 'a\n'),
                          ('new-b', 'b\n'),
                          ('new-b', 'c\n'),
                          ('new-b', 'd\n'),
                          ('new-b', 'e\n'),
                          ('new-b', 'g\n'),
                          ('new-b', 'h\n')],
                          list(my_plan.plan_merge()))

    def test_plan_merge_no_common_ancestor(self):
        self.add_rev('root', 'A', [], 'abc')
        self.add_rev('root', 'B', [], 'xyz')
        my_plan = _PlanMerge('A', 'B', self.plan_merge_vf, ('root',))
        self.assertEqual([
                          ('new-a', 'a\n'),
                          ('new-a', 'b\n'),
                          ('new-a', 'c\n'),
                          ('new-b', 'x\n'),
                          ('new-b', 'y\n'),
                          ('new-b', 'z\n')],
                          list(my_plan.plan_merge()))

    def test_plan_merge_tail_ancestors(self):
        # The graph looks like this:
        #       A       # Common to all ancestors
        #      / \
        #     B   C     # Ancestors of E, only common to one side
        #     |\ /|
        #     D E F     # D, F are unique to G, H respectively
        #     |/ \|     # E is the LCA for G & H, and the unique LCA for
        #     G   H     # I, J
        #     |\ /|
        #     | X |
        #     |/ \|
        #     I   J     # criss-cross merge of G, H
        #
        # In this situation, a simple pruning of ancestors of E will leave D &
        # F "dangling", which looks like they introduce lines different from
        # the ones in E, but in actuality C&B introduced the lines, and they
        # are already present in E

        # Introduce the base text
        self.add_rev('root', 'A', [], 'abc')
        # Introduces a new line B
        self.add_rev('root', 'B', ['A'], 'aBbc')
        # Introduces a new line C
        self.add_rev('root', 'C', ['A'], 'abCc')
        # Introduce new line D
        self.add_rev('root', 'D', ['B'], 'DaBbc')
        # Merges B and C by just incorporating both
        self.add_rev('root', 'E', ['B', 'C'], 'aBbCc')
        # Introduce new line F
        self.add_rev('root', 'F', ['C'], 'abCcF')
        # Merge D & E by just combining the texts
        self.add_rev('root', 'G', ['D', 'E'], 'DaBbCc')
        # Merge F & E by just combining the texts
        self.add_rev('root', 'H', ['F', 'E'], 'aBbCcF')
        # Merge G & H by just combining texts
        self.add_rev('root', 'I', ['G', 'H'], 'DaBbCcF')
        # Merge G & H but supersede an old line in B
        self.add_rev('root', 'J', ['H', 'G'], 'DaJbCcF')
        plan = self.plan_merge_vf.plan_merge('I', 'J')
        self.assertEqual([
                          ('unchanged', 'D\n'),
                          ('unchanged', 'a\n'),
                          ('killed-b', 'B\n'),
                          ('new-b', 'J\n'),
                          ('unchanged', 'b\n'),
                          ('unchanged', 'C\n'),
                          ('unchanged', 'c\n'),
                          ('unchanged', 'F\n')],
                         list(plan))

    def test_plan_merge_tail_triple_ancestors(self):
        # The graph looks like this:
        #       A       # Common to all ancestors
        #      / \
        #     B   C     # Ancestors of E, only common to one side
        #     |\ /|
        #     D E F     # D, F are unique to G, H respectively
        #     |/|\|     # E is the LCA for G & H, and the unique LCA for
        #     G Q H     # I, J
        #     |\ /|     # Q is just an extra node which is merged into both
        #     | X |     # I and J
        #     |/ \|
        #     I   J     # criss-cross merge of G, H
        #
        # This is the same as the test_plan_merge_tail_ancestors, except we add
        # a third LCA that doesn't add new lines, but will trigger our more
        # involved ancestry logic

        self.add_rev('root', 'A', [], 'abc')
        self.add_rev('root', 'B', ['A'], 'aBbc')
        self.add_rev('root', 'C', ['A'], 'abCc')
        self.add_rev('root', 'D', ['B'], 'DaBbc')
        self.add_rev('root', 'E', ['B', 'C'], 'aBbCc')
        self.add_rev('root', 'F', ['C'], 'abCcF')
        self.add_rev('root', 'G', ['D', 'E'], 'DaBbCc')
        self.add_rev('root', 'H', ['F', 'E'], 'aBbCcF')
        self.add_rev('root', 'Q', ['E'], 'aBbCc')
        self.add_rev('root', 'I', ['G', 'Q', 'H'], 'DaBbCcF')
        # Merge G & H but supersede an old line in B
        self.add_rev('root', 'J', ['H', 'Q', 'G'], 'DaJbCcF')
        plan = self.plan_merge_vf.plan_merge('I', 'J')
        self.assertEqual([
                          ('unchanged', 'D\n'),
                          ('unchanged', 'a\n'),
                          ('killed-b', 'B\n'),
                          ('new-b', 'J\n'),
                          ('unchanged', 'b\n'),
                          ('unchanged', 'C\n'),
                          ('unchanged', 'c\n'),
                          ('unchanged', 'F\n')],
                         list(plan))

    def test_plan_merge_2_tail_triple_ancestors(self):
        # The graph looks like this:
        #     A   B     # 2 tails going back to NULL
        #     |\ /|
        #     D E F     # D, is unique to G, F to H
        #     |/|\|     # E is the LCA for G & H, and the unique LCA for
        #     G Q H     # I, J
        #     |\ /|     # Q is just an extra node which is merged into both
        #     | X |     # I and J
        #     |/ \|
        #     I   J     # criss-cross merge of G, H (and Q)
        #

        # This is meant to test after hitting a 3-way LCA, and multiple tail
        # ancestors (only have NULL_REVISION in common)

        self.add_rev('root', 'A', [], 'abc')
        self.add_rev('root', 'B', [], 'def')
        self.add_rev('root', 'D', ['A'], 'Dabc')
        self.add_rev('root', 'E', ['A', 'B'], 'abcdef')
        self.add_rev('root', 'F', ['B'], 'defF')
        self.add_rev('root', 'G', ['D', 'E'], 'Dabcdef')
        self.add_rev('root', 'H', ['F', 'E'], 'abcdefF')
        self.add_rev('root', 'Q', ['E'], 'abcdef')
        self.add_rev('root', 'I', ['G', 'Q', 'H'], 'DabcdefF')
        # Merge G & H but supersede an old line in B
        self.add_rev('root', 'J', ['H', 'Q', 'G'], 'DabcdJfF')
        plan = self.plan_merge_vf.plan_merge('I', 'J')
        self.assertEqual([
                          ('unchanged', 'D\n'),
                          ('unchanged', 'a\n'),
                          ('unchanged', 'b\n'),
                          ('unchanged', 'c\n'),
                          ('unchanged', 'd\n'),
                          ('killed-b', 'e\n'),
                          ('new-b', 'J\n'),
                          ('unchanged', 'f\n'),
                          ('unchanged', 'F\n')],
                         list(plan))

    def test_plan_merge_uncommitted_files(self):
        self.setup_plan_merge_uncommitted()
        plan = self.plan_merge_vf.plan_merge('B:', 'C:')
        self.assertEqual([
                          ('new-b', 'f\n'),
                          ('unchanged', 'a\n'),
                          ('killed-a', 'b\n'),
                          ('killed-b', 'c\n'),
                          ('new-a', 'e\n'),
                          ('new-a', 'h\n'),
                          ('new-a', 'g\n'),
                          ('new-b', 'g\n')],
                         list(plan))

    def test_plan_merge_insert_order(self):
        """Weave merges are sensitive to the order of insertion.
        
        Specifically for overlapping regions, it effects which region gets put
        'first'. And when a user resolves an overlapping merge, if they use the
        same ordering, then the lines match the parents, if they don't only
        *some* of the lines match.
        """
        self.add_rev('root', 'A', [], 'abcdef')
        self.add_rev('root', 'B', ['A'], 'abwxcdef')
        self.add_rev('root', 'C', ['A'], 'abyzcdef')
        # Merge, and resolve the conflict by adding *both* sets of lines
        # If we get the ordering wrong, these will look like new lines in D,
        # rather than carried over from B, C
        self.add_rev('root', 'D', ['B', 'C'],
                         'abwxyzcdef')
        # Supersede the lines in B and delete the lines in C, which will
        # conflict if they are treated as being in D
        self.add_rev('root', 'E', ['C', 'B'],
                         'abnocdef')
        # Same thing for the lines in C
        self.add_rev('root', 'F', ['C'], 'abpqcdef')
        plan = self.plan_merge_vf.plan_merge('D', 'E')
        self.assertEqual([
                          ('unchanged', 'a\n'),
                          ('unchanged', 'b\n'),
                          ('killed-b', 'w\n'),
                          ('killed-b', 'x\n'),
                          ('killed-b', 'y\n'),
                          ('killed-b', 'z\n'),
                          ('new-b', 'n\n'),
                          ('new-b', 'o\n'),
                          ('unchanged', 'c\n'),
                          ('unchanged', 'd\n'),
                          ('unchanged', 'e\n'),
                          ('unchanged', 'f\n')],
                         list(plan))
        plan = self.plan_merge_vf.plan_merge('E', 'D')
        # Going in the opposite direction shows the effect of the opposite plan
        self.assertEqual([
                          ('unchanged', 'a\n'),
                          ('unchanged', 'b\n'),
                          ('new-b', 'w\n'),
                          ('new-b', 'x\n'),
                          ('killed-a', 'y\n'),
                          ('killed-a', 'z\n'),
                          ('killed-both', 'w\n'),
                          ('killed-both', 'x\n'),
                          ('new-a', 'n\n'),
                          ('new-a', 'o\n'),
                          ('unchanged', 'c\n'),
                          ('unchanged', 'd\n'),
                          ('unchanged', 'e\n'),
                          ('unchanged', 'f\n')],
                         list(plan))

    def test_plan_merge_criss_cross(self):
        # This is specificly trying to trigger problems when using limited
        # ancestry and weaves. The ancestry graph looks like:
        #       XX      unused ancestor, should not show up in the weave
        #       |
        #       A       Unique LCA
        #       |\
        #       B \     Introduces a line 'foo'
        #      / \ \
        #     C   D E   C & D both have 'foo', E has different changes
        #     |\ /| |
        #     | X | |
        #     |/ \|/
        #     F   G      All of C, D, E are merged into F and G, so they are
        #                all common ancestors.
        #
        # The specific issue with weaves:
        #   B introduced a text ('foo') that is present in both C and D.
        #   If we do not include B (because it isn't an ancestor of E), then
        #   the A=>C and A=>D look like both sides independently introduce the
        #   text ('foo'). If F does not modify the text, it would still appear
        #   to have deleted on of the versions from C or D. If G then modifies
        #   'foo', it should appear as superseding the value in F (since it
        #   came from B), rather than conflict because of the resolution during
        #   C & D.
        self.add_rev('root', 'XX', [], 'qrs')
        self.add_rev('root', 'A', ['XX'], 'abcdef')
        self.add_rev('root', 'B', ['A'], 'axcdef')
        self.add_rev('root', 'C', ['B'], 'axcdefg')
        self.add_rev('root', 'D', ['B'], 'haxcdef')
        self.add_rev('root', 'E', ['A'], 'abcdyf')
        # Simple combining of all texts
        self.add_rev('root', 'F', ['C', 'D', 'E'], 'haxcdyfg')
        # combine and supersede 'x'
        self.add_rev('root', 'G', ['C', 'D', 'E'], 'hazcdyfg')
        plan = self.plan_merge_vf.plan_merge('F', 'G')
        self.assertEqual([
                          ('unchanged', 'h\n'),
                          ('unchanged', 'a\n'),
                          ('killed-base', 'b\n'),
                          ('killed-b', 'x\n'),
                          ('new-b', 'z\n'),
                          ('unchanged', 'c\n'),
                          ('unchanged', 'd\n'),
                          ('killed-base', 'e\n'),
                          ('unchanged', 'y\n'),
                          ('unchanged', 'f\n'),
                          ('unchanged', 'g\n')],
                         list(plan))

    def assertRemoveExternalReferences(self, filtered_parent_map,
                                       child_map, tails, parent_map):
        """Assert results for _PlanMerge._remove_external_references."""
        (act_filtered_parent_map, act_child_map,
         act_tails) = _PlanMerge._remove_external_references(parent_map)

        # The parent map *should* preserve ordering, but the ordering of
        # children is not strictly defined
        # child_map = dict((k, sorted(children))
        #                  for k, children in child_map.iteritems())
        # act_child_map = dict(k, sorted(children)
        #                      for k, children in act_child_map.iteritems())
        self.assertEqual(filtered_parent_map, act_filtered_parent_map)
        self.assertEqual(child_map, act_child_map)
        self.assertEqual(sorted(tails), sorted(act_tails))

    def test__remove_external_references(self):
        # First, nothing to remove
        self.assertRemoveExternalReferences({3: [2], 2: [1], 1: []},
            {1: [2], 2: [3], 3: []}, [1], {3: [2], 2: [1], 1: []})
        # The reverse direction
        self.assertRemoveExternalReferences({1: [2], 2: [3], 3: []},
            {3: [2], 2: [1], 1: []}, [3], {1: [2], 2: [3], 3: []})
        # Extra references
        self.assertRemoveExternalReferences({3: [2], 2: [1], 1: []},
            {1: [2], 2: [3], 3: []}, [1], {3: [2, 4], 2: [1, 5], 1: [6]})
        # Multiple tails
        self.assertRemoveExternalReferences(
            {4: [2, 3], 3: [], 2: [1], 1: []},
            {1: [2], 2: [4], 3: [4], 4: []},
            [1, 3],
            {4: [2, 3], 3: [5], 2: [1], 1: [6]})
        # Multiple children
        self.assertRemoveExternalReferences(
            {1: [3], 2: [3, 4], 3: [], 4: []},
            {1: [], 2: [], 3: [1, 2], 4: [2]},
            [3, 4],
            {1: [3], 2: [3, 4], 3: [5], 4: []})

    def assertPruneTails(self, pruned_map, tails, parent_map):
        child_map = {}
        for key, parent_keys in parent_map.iteritems():
            child_map.setdefault(key, [])
            for pkey in parent_keys:
                child_map.setdefault(pkey, []).append(key)
        _PlanMerge._prune_tails(parent_map, child_map, tails)
        self.assertEqual(pruned_map, parent_map)

    def test__prune_tails(self):
        # Nothing requested to prune
        self.assertPruneTails({1: [], 2: [], 3: []}, [],
                              {1: [], 2: [], 3: []})
        # Prune a single entry
        self.assertPruneTails({1: [], 3: []}, [2],
                              {1: [], 2: [], 3: []})
        # Prune a chain
        self.assertPruneTails({1: []}, [3],
                              {1: [], 2: [3], 3: []})
        # Prune a chain with a diamond
        self.assertPruneTails({1: []}, [5],
                              {1: [], 2: [3, 4], 3: [5], 4: [5], 5: []})
        # Prune a partial chain
        self.assertPruneTails({1: [6], 6:[]}, [5],
                              {1: [2, 6], 2: [3, 4], 3: [5], 4: [5], 5: [],
                               6: []})
        # Prune a chain with multiple tips, that pulls out intermediates
        self.assertPruneTails({1:[3], 3:[]}, [4, 5],
                              {1: [2, 3], 2: [4, 5], 3: [], 4:[], 5:[]})
        self.assertPruneTails({1:[3], 3:[]}, [5, 4],
                              {1: [2, 3], 2: [4, 5], 3: [], 4:[], 5:[]})

    def test_subtract_plans(self):
        old_plan = [
        ('unchanged', 'a\n'),
        ('new-a', 'b\n'),
        ('killed-a', 'c\n'),
        ('new-b', 'd\n'),
        ('new-b', 'e\n'),
        ('killed-b', 'f\n'),
        ('killed-b', 'g\n'),
        ]
        new_plan = [
        ('unchanged', 'a\n'),
        ('new-a', 'b\n'),
        ('killed-a', 'c\n'),
        ('new-b', 'd\n'),
        ('new-b', 'h\n'),
        ('killed-b', 'f\n'),
        ('killed-b', 'i\n'),
        ]
        subtracted_plan = [
        ('unchanged', 'a\n'),
        ('new-a', 'b\n'),
        ('killed-a', 'c\n'),
        ('new-b', 'h\n'),
        ('unchanged', 'f\n'),
        ('killed-b', 'i\n'),
        ]
        self.assertEqual(subtracted_plan,
            list(_PlanMerge._subtract_plans(old_plan, new_plan)))

    def setup_merge_with_base(self):
        self.add_rev('root', 'COMMON', [], 'abc')
        self.add_rev('root', 'THIS', ['COMMON'], 'abcd')
        self.add_rev('root', 'BASE', ['COMMON'], 'eabc')
        self.add_rev('root', 'OTHER', ['BASE'], 'eafb')

    def test_plan_merge_with_base(self):
        self.setup_merge_with_base()
        plan = self.plan_merge_vf.plan_merge('THIS', 'OTHER', 'BASE')
        self.assertEqual([('unchanged', 'a\n'),
                          ('new-b', 'f\n'),
                          ('unchanged', 'b\n'),
                          ('killed-b', 'c\n'),
                          ('new-a', 'd\n')
                         ], list(plan))

    def test_plan_lca_merge(self):
        self.setup_plan_merge()
        plan = self.plan_merge_vf.plan_lca_merge('B', 'C')
        self.assertEqual([
                          ('new-b', 'f\n'),
                          ('unchanged', 'a\n'),
                          ('killed-b', 'c\n'),
                          ('new-a', 'e\n'),
                          ('new-a', 'h\n'),
                          ('killed-a', 'b\n'),
                          ('unchanged', 'g\n')],
                         list(plan))

    def test_plan_lca_merge_uncommitted_files(self):
        self.setup_plan_merge_uncommitted()
        plan = self.plan_merge_vf.plan_lca_merge('B:', 'C:')
        self.assertEqual([
                          ('new-b', 'f\n'),
                          ('unchanged', 'a\n'),
                          ('killed-b', 'c\n'),
                          ('new-a', 'e\n'),
                          ('new-a', 'h\n'),
                          ('killed-a', 'b\n'),
                          ('unchanged', 'g\n')],
                         list(plan))

    def test_plan_lca_merge_with_base(self):
        self.setup_merge_with_base()
        plan = self.plan_merge_vf.plan_lca_merge('THIS', 'OTHER', 'BASE')
        self.assertEqual([('unchanged', 'a\n'),
                          ('new-b', 'f\n'),
                          ('unchanged', 'b\n'),
                          ('killed-b', 'c\n'),
                          ('new-a', 'd\n')
                         ], list(plan))

    def test_plan_lca_merge_with_criss_cross(self):
        self.add_version(('root', 'ROOT'), [], 'abc')
        # each side makes a change
        self.add_version(('root', 'REV1'), [('root', 'ROOT')], 'abcd')
        self.add_version(('root', 'REV2'), [('root', 'ROOT')], 'abce')
        # both sides merge, discarding others' changes
        self.add_version(('root', 'LCA1'),
            [('root', 'REV1'), ('root', 'REV2')], 'abcd')
        self.add_version(('root', 'LCA2'),
            [('root', 'REV1'), ('root', 'REV2')], 'fabce')
        plan = self.plan_merge_vf.plan_lca_merge('LCA1', 'LCA2')
        self.assertEqual([('new-b', 'f\n'),
                          ('unchanged', 'a\n'),
                          ('unchanged', 'b\n'),
                          ('unchanged', 'c\n'),
                          ('conflicted-a', 'd\n'),
                          ('conflicted-b', 'e\n'),
                         ], list(plan))

    def test_plan_lca_merge_with_null(self):
        self.add_version(('root', 'A'), [], 'ab')
        self.add_version(('root', 'B'), [], 'bc')
        plan = self.plan_merge_vf.plan_lca_merge('A', 'B')
        self.assertEqual([('new-a', 'a\n'),
                          ('unchanged', 'b\n'),
                          ('new-b', 'c\n'),
                         ], list(plan))

    def test_plan_merge_with_delete_and_change(self):
        self.add_rev('root', 'C', [], 'a')
        self.add_rev('root', 'A', ['C'], 'b')
        self.add_rev('root', 'B', ['C'], '')
        plan = self.plan_merge_vf.plan_merge('A', 'B')
        self.assertEqual([('killed-both', 'a\n'),
                          ('new-a', 'b\n'),
                         ], list(plan))

    def test_plan_merge_with_move_and_change(self):
        self.add_rev('root', 'C', [], 'abcd')
        self.add_rev('root', 'A', ['C'], 'acbd')
        self.add_rev('root', 'B', ['C'], 'aBcd')
        plan = self.plan_merge_vf.plan_merge('A', 'B')
        self.assertEqual([('unchanged', 'a\n'),
                          ('new-a', 'c\n'),
                          ('killed-b', 'b\n'),
                          ('new-b', 'B\n'),
                          ('killed-a', 'c\n'),
                          ('unchanged', 'd\n'),
                         ], list(plan))


class TestMergeImplementation(object):

    def do_merge(self, target_tree, source_tree, **kwargs):
        merger = _mod_merge.Merger.from_revision_ids(progress.DummyProgress(),
            target_tree, source_tree.last_revision(),
            other_branch=source_tree.branch)
        merger.merge_type=self.merge_type
        for name, value in kwargs.items():
            setattr(merger, name, value)
        merger.do_merge()

    def test_merge_specific_file(self):
        this_tree = self.make_branch_and_tree('this')
        this_tree.lock_write()
        self.addCleanup(this_tree.unlock)
        self.build_tree_contents([
            ('this/file1', 'a\nb\n'),
            ('this/file2', 'a\nb\n')
        ])
        this_tree.add(['file1', 'file2'])
        this_tree.commit('Added files')
        other_tree = this_tree.bzrdir.sprout('other').open_workingtree()
        self.build_tree_contents([
            ('other/file1', 'a\nb\nc\n'),
            ('other/file2', 'a\nb\nc\n')
        ])
        other_tree.commit('modified both')
        self.build_tree_contents([
            ('this/file1', 'd\na\nb\n'),
            ('this/file2', 'd\na\nb\n')
        ])
        this_tree.commit('modified both')
        self.do_merge(this_tree, other_tree, interesting_files=['file1'])
        self.assertFileEqual('d\na\nb\nc\n', 'this/file1')
        self.assertFileEqual('d\na\nb\n', 'this/file2')

    def test_merge_move_and_change(self):
        this_tree = self.make_branch_and_tree('this')
        this_tree.lock_write()
        self.addCleanup(this_tree.unlock)
        self.build_tree_contents([
            ('this/file1', 'line 1\nline 2\nline 3\nline 4\n'),
        ])
        this_tree.add('file1',)
        this_tree.commit('Added file')
        other_tree = this_tree.bzrdir.sprout('other').open_workingtree()
        self.build_tree_contents([
            ('other/file1', 'line 1\nline 2 to 2.1\nline 3\nline 4\n'),
        ])
        other_tree.commit('Changed 2 to 2.1')
        self.build_tree_contents([
            ('this/file1', 'line 1\nline 3\nline 2\nline 4\n'),
        ])
        this_tree.commit('Swapped 2 & 3')
        self.do_merge(this_tree, other_tree)
        self.assertFileEqual('line 1\n'
            '<<<<<<< TREE\n'
            'line 3\n'
            'line 2\n'
            '=======\n'
            'line 2 to 2.1\n'
            'line 3\n'
            '>>>>>>> MERGE-SOURCE\n'
            'line 4\n', 'this/file1')


class TestMerge3Merge(TestCaseWithTransport, TestMergeImplementation):

    merge_type = _mod_merge.Merge3Merger


class TestWeaveMerge(TestCaseWithTransport, TestMergeImplementation):

    merge_type = _mod_merge.WeaveMerger


class TestLCAMerge(TestCaseWithTransport, TestMergeImplementation):

    merge_type = _mod_merge.LCAMerger

    def test_merge_move_and_change(self):
        self.expectFailure("lca merge doesn't conflict for move and change",
            super(TestLCAMerge, self).test_merge_move_and_change)
