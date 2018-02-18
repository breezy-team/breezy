# Copyright (C) 2006, 2007, 2009, 2010 Canonical Ltd
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

"""Tests of the WorkingTree.unversion API."""

from breezy import (
    errors,
    )
from breezy.tests.per_workingtree import TestCaseWithWorkingTree


class TestUnversion(TestCaseWithWorkingTree):

    def test_unversion_requires_write_lock(self):
        """WT.unversion([]) in a read lock raises ReadOnlyError."""
        tree = self.make_branch_and_tree('.')
        tree.lock_read()
        self.assertRaises(errors.ReadOnlyError, tree.unversion, [])
        tree.unlock()

    def test_unversion_missing_file(self):
        """WT.unversion(['missing']) raises NoSuchId."""
        tree = self.make_branch_and_tree('.')
        self.assertRaises(errors.NoSuchFile, tree.unversion, ['missing'])

    def test_unversion_parent_and_child_renamed_bug_187207(self):
        # When unversioning dirstate trees show a bug in dealing with
        # unversioning children of reparented children of unversioned
        # paths when relocation entries are present and the relocation
        # points later into the dirstate.
        tree = self.make_branch_and_tree('.')
        self.build_tree(['del/', 'del/sub/', 'del/sub/b'])
        tree.add(['del', 'del/sub', 'del/sub/b'])
        b_id = tree.path2id('del/sub/b')
        tree.commit('setup')
        tree.rename_one('del/sub', 'sub')
        self.assertEqual('sub/b', tree.id2path(b_id))
        tree.unversion(['del', 'sub/b'])
        self.assertRaises(errors.NoSuchId, tree.id2path, b_id)

    def test_unversion_several_files(self):
        """After unversioning several files, they should not be versioned."""
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b', 'c'])
        tree.add(['a', 'b', 'c'])
        a_id = tree.path2id('a')
        b_id = tree.path2id('b')
        c_id = tree.path2id('c')
        # within a lock unversion should take effect
        tree.lock_write()
        self.assertTrue(tree.is_versioned('a'))
        tree.unversion(['a', 'b'])
        self.assertFalse(tree.is_versioned('a'))
        self.assertFalse(tree.has_id(a_id))
        self.assertFalse(tree.has_id(b_id))
        self.assertTrue(tree.has_id(c_id))
        self.assertTrue(tree.has_filename('a'))
        self.assertTrue(tree.has_filename('b'))
        self.assertTrue(tree.has_filename('c'))
        tree.unlock()
        # the changes should have persisted to disk - reopen the workingtree
        # to be sure.
        tree = tree.controldir.open_workingtree()
        self.addCleanup(tree.lock_read().unlock)
        self.assertFalse(tree.has_id(a_id))
        self.assertFalse(tree.has_id(b_id))
        self.assertTrue(tree.has_id(c_id))
        self.assertTrue(tree.has_filename('a'))
        self.assertTrue(tree.has_filename('b'))
        self.assertTrue(tree.has_filename('c'))

    def test_unversion_subtree(self):
        """Unversioning the root of a subtree unversions the entire subtree."""
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a/', 'a/b', 'c'])
        tree.add(['a', 'a/b', 'c'])
        a_id = tree.path2id('a')
        b_id = tree.path2id('a/b')
        c_id = tree.path2id('c')
        # within a lock unversion should take effect
        tree.lock_write()
        tree.unversion(['a'])
        self.assertFalse(tree.has_id(a_id))
        self.assertFalse(tree.has_id(b_id))
        self.assertTrue(tree.has_id(c_id))
        self.assertTrue(tree.has_filename('a'))
        self.assertTrue(tree.has_filename('a/b'))
        self.assertTrue(tree.has_filename('c'))
        tree.unlock()

    def test_unversion_subtree_and_children(self):
        """Passing a child id will raise NoSuchId.

        This is because the parent directory will have already been removed.
        """
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a/', 'a/b', 'a/c', 'd'])
        tree.add(['a', 'a/b', 'a/c', 'd'])
        a_id = tree.path2id('a')
        b_id = tree.path2id('a/b')
        c_id = tree.path2id('a/c')
        d_id = tree.path2id('d')
        with tree.lock_write():
            tree.unversion(['a/b', 'a'])
            self.assertFalse(tree.has_id(a_id))
            self.assertFalse(tree.has_id(b_id))
            self.assertFalse(tree.has_id(c_id))
            self.assertTrue(tree.has_id(d_id))
            # The files are still on disk
            self.assertTrue(tree.has_filename('a'))
            self.assertTrue(tree.has_filename('a/b'))
            self.assertTrue(tree.has_filename('a/c'))
            self.assertTrue(tree.has_filename('d'))

    def test_unversion_renamed(self):
        tree = self.make_branch_and_tree('a')
        self.build_tree(['a/dir/', 'a/dir/f1', 'a/dir/f2', 'a/dir/f3',
                         'a/dir2/'])
        tree.add(['dir', 'dir/f1', 'dir/f2', 'dir/f3', 'dir2'])
        dir_id = tree.path2id('dir')
        dir2_id = tree.path2id('dir2')
        f1_id = tree.path2id('dir/f1')
        f2_id = tree.path2id('dir/f2')
        f3_id = tree.path2id('dir/f3')
        rev_id1 = tree.commit('init')
        # Start off by renaming entries, and then unversion a bunch of entries
        # https://bugs.launchpad.net/bzr/+bug/114615
        tree.rename_one('dir/f1', 'dir/a')
        tree.rename_one('dir/f2', 'dir/z')
        tree.move(['dir/f3'], 'dir2')

        tree.lock_read()
        try:
            root_id = tree.get_root_id()
            paths = [(path, ie.file_id)
                     for path, ie in tree.iter_entries_by_dir()]
        finally:
            tree.unlock()
        self.assertEqual([('', root_id),
                          ('dir', dir_id),
                          ('dir2', dir2_id),
                          ('dir/a', f1_id),
                          ('dir/z', f2_id),
                          ('dir2/f3', f3_id),
                         ], paths)

        tree.unversion({'dir'})
        paths = [(path, ie.file_id)
                 for path, ie in tree.iter_entries_by_dir()]

        self.assertEqual([('', root_id),
                          ('dir2', dir2_id),
                          ('dir2/f3', f3_id),
                         ], paths)

    def test_unversion_after_conflicted_merge(self):
        # Test for bug #114615
        tree_a = self.make_branch_and_tree('A')
        self.build_tree(['A/a/', 'A/a/m', 'A/a/n'])
        tree_a.add(['a', 'a/m', 'a/n'])
        a_id = tree_a.path2id('a')
        m_id = tree_a.path2id('a/m')
        n_id = tree_a.path2id('a/n')
        tree_a.commit('init')

        tree_a.lock_read()
        try:
            root_id = tree_a.get_root_id()
        finally:
            tree_a.unlock()

        tree_b = tree_a.controldir.sprout('B').open_workingtree()
        self.build_tree(['B/xyz/'])
        tree_b.add(['xyz'])
        xyz_id = tree_b.path2id('xyz')
        tree_b.rename_one('a/m', 'xyz/m')
        tree_b.unversion(['a'])
        tree_b.commit('delete in B')

        paths = [(path, ie.file_id)
                 for path, ie in tree_b.iter_entries_by_dir()]
        self.assertEqual([('', root_id),
                          ('xyz', xyz_id),
                          ('xyz/m', m_id),
                         ], paths)

        self.build_tree_contents([('A/a/n', b'new contents for n\n')])
        tree_a.commit('change n in A')

        # Merging from A should introduce conflicts because 'n' was modified
        # and removed, so 'a' needs to be restored. We also have a conflict
        # because 'a' is still an existing directory
        num_conflicts = tree_b.merge_from_branch(tree_a.branch)
        self.assertEqual(4, num_conflicts)
        paths = [(path, ie.file_id)
                 for path, ie in tree_b.iter_entries_by_dir()]
        self.assertEqual([('', root_id),
                          ('a', a_id),
                          ('xyz', xyz_id),
                          ('a/n.OTHER', n_id),
                          ('xyz/m', m_id),
                         ], paths)
        tree_b.unversion(['a'])
        paths = [(path, ie.file_id)
                 for path, ie in tree_b.iter_entries_by_dir()]
        self.assertEqual([('', root_id),
                          ('xyz', xyz_id),
                          ('xyz/m', m_id),
                         ], paths)
