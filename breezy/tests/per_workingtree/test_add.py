# Copyright (C) 2007 Canonical Ltd
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

"""Tests for interface conformance of 'WorkingTree.add'"""

from breezy import (
    errors,
    tests,
    )
from breezy.bzr import (
    inventory,
    )
from breezy.tests.matchers import HasLayout
from breezy.tests.per_workingtree import TestCaseWithWorkingTree


class TestAdd(TestCaseWithWorkingTree):

    def assertTreeLayout(self, expected, tree):
        """Check that the tree has the correct layout."""
        self.assertThat(tree, HasLayout(expected))

    def test_add_one(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['one'])
        tree.add('one')
        root_id = tree.get_root_id()

        self.assertTreeLayout(
            [('', root_id), ('one', tree.path2id('one'))], tree)

    def test_add_existing_id(self):
        """Adding an entry with a pre-existing id raises DuplicateFileId"""
        tree = self.make_branch_and_tree('.')
        if not tree.supports_setting_file_ids():
            self.skipTest("tree does not support setting file ids")
        self.build_tree(['a', 'b'])
        tree.add(['a'])
        self.assertRaises(errors.DuplicateFileId,
                          tree.add, ['b'], [tree.path2id('a')])
        root_id = tree.get_root_id()
        # And the entry should not have been added.
        self.assertTreeLayout([('', root_id), ('a', tree.path2id('a'))], tree)

    def test_add_old_id(self):
        """We can add an old id, as long as it doesn't exist now."""
        tree = self.make_branch_and_tree('.')
        if not tree.supports_setting_file_ids():
            self.skipTest("tree does not support setting file ids")
        self.build_tree(['a', 'b'])
        tree.add(['a'])
        file_id = tree.path2id('a')
        tree.commit('first')
        root_id = tree.get_root_id()
        # And the entry should not have been added.
        tree.unversion(['a'])
        tree.add(['b'], [file_id])
        self.assertTreeLayout([('', root_id), ('b', file_id)], tree)
        self.assertTreeLayout([('', root_id), ('a', file_id)],
                              tree.basis_tree())

    def test_add_one_list(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['one'])
        tree.add(['one'])
        root_id = tree.get_root_id()

        self.assertTreeLayout(
            [('', root_id), ('one', tree.path2id('one'))], tree)

    def test_add_one_new_id(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['one'])
        tree.add(['one'])
        root_id = tree.get_root_id()
        one_id = tree.path2id('one')

        self.assertTreeLayout([('', root_id), ('one', one_id)], tree)

    def test_add_unicode(self):
        tree = self.make_branch_and_tree('.')
        try:
            self.build_tree([u'f\xf6'])
        except UnicodeError:
            raise tests.TestSkipped('Filesystem does not support filename.')
        tree.add([u'f\xf6'])
        root_id = tree.get_root_id()
        foo_id = tree.path2id(u'f\xf6')

        self.assertTreeLayout([('', root_id), (u'f\xf6', foo_id)], tree)

    def test_add_subdir_with_ids(self):
        tree = self.make_branch_and_tree('.')
        if not tree.supports_setting_file_ids():
            self.skipTest("tree does not support setting file ids")
        self.build_tree(['dir/', 'dir/subdir/', 'dir/subdir/foo'])
        tree.add(['dir'], ['dir-id'])
        tree.add(['dir/subdir'], ['subdir-id'])
        tree.add(['dir/subdir/foo'], ['foo-id'])
        root_id = tree.get_root_id()

        self.assertTreeLayout([('', root_id), ('dir/', 'dir-id'),
                               ('dir/subdir/', 'subdir-id'),
                               ('dir/subdir/foo', 'foo-id')], tree)

    def test_add_subdir(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['dir/', 'dir/subdir/', 'dir/subdir/foo'])
        tree.add(['dir'])
        tree.add(['dir/subdir'])
        tree.add(['dir/subdir/foo'])
        root_id = tree.get_root_id()

        self.assertTreeLayout([
            ('', root_id),
            ('dir/', tree.path2id('dir')),
            ('dir/subdir/', tree.path2id('dir/subdir')),
            ('dir/subdir/foo', tree.path2id('dir/subdir/foo'))],
            tree)

    def test_add_multiple(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b', 'dir/', 'dir/subdir/', 'dir/subdir/foo'])
        tree.add(['a', 'b', 'dir', 'dir/subdir', 'dir/subdir/foo'])
        root_id = tree.get_root_id()

        self.assertTreeLayout([
            (p, tree.path2id(p))
            for p in ['', 'a', 'b', 'dir/', 'dir/subdir/', 'dir/subdir/foo']],
            tree)

    def test_add_multiple_with_file_ids(self):
        tree = self.make_branch_and_tree('.')
        if not tree.supports_setting_file_ids():
            self.skipTest("tree does not support setting file ids")
        self.build_tree(['a', 'b', 'dir/', 'dir/subdir/', 'dir/subdir/foo'])
        tree.add(['a', 'b', 'dir', 'dir/subdir', 'dir/subdir/foo'],
                 ['a-id', 'b-id', 'dir-id', 'subdir-id', 'foo-id'])
        root_id = tree.get_root_id()

        self.assertTreeLayout([('', root_id), ('a', 'a-id'), ('b', 'b-id'),
                               ('dir/', 'dir-id'), ('dir/subdir/', 'subdir-id'),
                               ('dir/subdir/foo', 'foo-id')], tree)

    def test_add_invalid(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['dir/', 'dir/subdir/', 'dir/subdir/foo'])
        root_id = tree.get_root_id()

        self.assertRaises(errors.NotVersionedError,
                          tree.add, ['dir/subdir'])
        self.assertTreeLayout([('', root_id)], tree)

    def test_add_after_remove(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['dir/', 'dir/subdir/', 'dir/subdir/foo'])
        root_id = tree.get_root_id()
        tree.add(['dir'])
        tree.commit('dir')
        tree.unversion(['dir'])
        self.assertRaises(errors.NotVersionedError,
                          tree.add, ['dir/subdir'])

    def test_add_root(self):
        # adding the root should be a no-op, or at least not
        # do anything whacky.
        tree = self.make_branch_and_tree('.')
        tree.lock_write()
        tree.add('')
        self.assertEqual([tree.path2id('')], list(tree.all_file_ids()))
        # the root should have been changed to be a new unique root.
        self.assertNotEqual(inventory.ROOT_ID, tree.path2id(''))
        tree.unlock()

    def test_add_previously_added(self):
        # adding a path that was previously added should work
        tree = self.make_branch_and_tree('.')
        self.build_tree(['foo'])
        tree.add(['foo'])
        tree.unversion(['foo'])
        tree.add(['foo'])
        self.assertTrue(tree.has_filename('foo'))

    def test_add_previously_added_with_file_id(self):
        # adding a path that was previously added should work
        tree = self.make_branch_and_tree('.')
        if not tree.supports_setting_file_ids():
            self.skipTest("tree does not support setting file ids")
        self.build_tree(['foo'])
        tree.add(['foo'], ['foo-id'])
        tree.unversion(['foo'])
        tree.add(['foo'], ['foo-id'])
        self.assertEqual('foo-id', tree.path2id('foo'))

    def test_add_present_in_basis(self):
        # adding a path that was present in the basis should work.
        tree = self.make_branch_and_tree('.')
        self.build_tree(['foo'])
        tree.add(['foo'])
        tree.commit('add foo')
        tree.unversion(['foo'])
        tree.add(['foo'])
        self.assertTrue(tree.has_filename('foo'))

    def test_add_present_in_basis_with_file_ids(self):
        # adding a path that was present in the basis should work.
        tree = self.make_branch_and_tree('.')
        if not tree.supports_setting_file_ids():
            self.skipTest("tree does not support setting file ids")
        self.build_tree(['foo'])
        tree.add(['foo'], ['foo-id'])
        tree.commit('add foo')
        tree.unversion(['foo'])
        tree.add(['foo'], ['foo-id'])
        self.assertEqual('foo-id', tree.path2id('foo'))
