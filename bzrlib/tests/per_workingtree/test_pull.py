# Copyright (C) 2006, 2007, 2009-2012, 2016 Canonical Ltd
# Authors:  Robert Collins <robert.collins@canonical.com>
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA


from bzrlib import tests
from bzrlib.revision import NULL_REVISION
from bzrlib.tests import per_workingtree


class TestPull(per_workingtree.TestCaseWithWorkingTree):

    def get_pullable_trees(self):
        self.build_tree(['from/', 'from/file', 'to/'])
        tree = self.make_branch_and_tree('from')
        tree.add('file')
        tree.commit('foo', rev_id='A')
        tree_b = self.make_branch_and_tree('to')
        return tree, tree_b

    def test_pull_null(self):
        tree_a, tree_b = self.get_pullable_trees()
        root_id = tree_a.get_root_id()
        tree_a.pull(tree_b.branch, stop_revision=NULL_REVISION, overwrite=True)
        self.assertEqual(root_id, tree_a.get_root_id())

    def test_pull(self):
        tree_a, tree_b = self.get_pullable_trees()
        tree_b.pull(tree_a.branch)
        self.assertTrue(tree_b.branch.repository.has_revision('A'))
        self.assertEqual(['A'], tree_b.get_parent_ids())

    def test_pull_overwrites(self):
        tree_a, tree_b = self.get_pullable_trees()
        tree_b.commit('foo', rev_id='B')
        self.assertEqual('B', tree_b.branch.last_revision())
        tree_b.pull(tree_a.branch, overwrite=True)
        self.assertTrue(tree_b.branch.repository.has_revision('A'))
        self.assertTrue(tree_b.branch.repository.has_revision('B'))
        self.assertEqual(['A'], tree_b.get_parent_ids())

    def test_pull_merges_tree_content(self):
        tree_a, tree_b = self.get_pullable_trees()
        tree_b.pull(tree_a.branch)
        self.assertFileEqual('contents of from/file\n', 'to/file')

    def test_pull_changes_root_id(self):
        tree = self.make_branch_and_tree('from')
        tree.set_root_id('first_root_id')
        self.build_tree(['from/file'])
        tree.add(['file'])
        tree.commit('first')
        to_tree = tree.bzrdir.sprout('to').open_workingtree()
        self.assertEqual('first_root_id', to_tree.get_root_id())
        tree.set_root_id('second_root_id')
        tree.commit('second')
        to_tree.pull(tree.branch)
        self.assertEqual('second_root_id', to_tree.get_root_id())


class TestPullWithOrphans(per_workingtree.TestCaseWithWorkingTree):

    def make_branch_deleting_dir(self, relpath=None):
        if relpath is None:
            relpath = 'trunk'
        builder = self.make_branch_builder(relpath)
        builder.start_series()

        # Create an empty trunk
        builder.build_snapshot('1', None, [
                ('add', ('', 'root-id', 'directory', ''))])
        builder.build_snapshot('2', ['1'], [
                ('add', ('dir', 'dir-id', 'directory', '')),
                ('add', ('file', 'file-id', 'file', 'trunk content\n')),])
        builder.build_snapshot('3', ['2'], [
                ('unversion', 'dir-id'),])
        builder.finish_series()
        return builder.get_branch()

    def test_pull_orphans(self):
        if not self.workingtree_format.missing_parent_conflicts:
            raise tests.TestSkipped(
                '%r does not support missing parent conflicts' %
                    self.workingtree_format)
        trunk = self.make_branch_deleting_dir('trunk')
        work = trunk.bzrdir.sprout('work', revision_id='2').open_workingtree()
        work.branch.get_config_stack().set(
            'bzr.transform.orphan_policy', 'move')
        # Add some unversioned files in dir
        self.build_tree(['work/dir/foo',
                         'work/dir/subdir/',
                         'work/dir/subdir/foo'])
        work.pull(trunk)
        self.assertLength(0, work.conflicts())
        # The directory removal should succeed
        self.assertPathDoesNotExist('work/dir')
