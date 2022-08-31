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

import os

from breezy import merge, tests, transform, workingtree


class TestRevert(tests.TestCaseWithTransport):
    """Ensure that revert behaves as expected"""

    def test_revert_merged_dir(self):
        """Reverting a merge that adds a directory deletes the directory"""
        source_tree = self.make_branch_and_tree('source')
        source_tree.commit('empty tree')
        target_tree = source_tree.controldir.sprout(
            'target').open_workingtree()
        self.build_tree(['source/dir/', 'source/dir/contents'])
        source_tree.add(['dir', 'dir/contents'], ids=[b'dir-id', b'contents-id'])
        source_tree.commit('added dir')
        target_tree.lock_write()
        self.addCleanup(target_tree.unlock)
        merge.merge_inner(target_tree.branch, source_tree.basis_tree(),
                          target_tree.basis_tree(), this_tree=target_tree)
        self.assertPathExists('target/dir')
        self.assertPathExists('target/dir/contents')
        target_tree.revert()
        self.assertPathDoesNotExist('target/dir/contents')
        self.assertPathDoesNotExist('target/dir')

    def test_revert_new(self):
        """Only locally-changed new files should be preserved when reverting

        When a file isn't present in revert's target tree:
        If a file hasn't been committed, revert should unversion it, but not
        delete it.
        If a file has local changes, revert should unversion it, but not
        delete it.
        If a file has no changes from the last commit, revert should delete it.
        If a file has changes due to a merge, revert should delete it.
        """
        tree = self.make_branch_and_tree('tree')
        tree.commit('empty tree')
        merge_target = tree.controldir.sprout(
            'merge_target').open_workingtree()
        self.build_tree(['tree/new_file'])

        # newly-added files should not be deleted
        tree.add('new_file')
        basis_tree = tree.branch.repository.revision_tree(tree.last_revision())
        tree.revert()
        self.assertPathExists('tree/new_file')

        # unchanged files should be deleted
        tree.add('new_file')
        tree.commit('add new_file')
        tree.revert(old_tree=basis_tree)
        self.assertPathDoesNotExist('tree/new_file')

        # files should be deleted if their changes came from merges
        merge_target.merge_from_branch(tree.branch)
        self.assertPathExists('merge_target/new_file')
        merge_target.revert()
        self.assertPathDoesNotExist('merge_target/new_file')

        # files should not be deleted if changed after a merge
        merge_target.merge_from_branch(tree.branch)
        self.assertPathExists('merge_target/new_file')
        self.build_tree_contents([('merge_target/new_file', b'new_contents')])
        merge_target.revert()
        self.assertPathExists('merge_target/new_file')

    def tree_with_executable(self):
        tree = self.make_branch_and_tree('tree')
        tt = tree.transform()
        tt.new_file('newfile', tt.root, [b'helooo!'], b'newfile-id', True)
        tt.apply()
        with tree.lock_write():
            self.assertTrue(tree.is_executable('newfile'))
            tree.commit('added newfile')
        return tree

    def test_preserve_execute(self):
        tree = self.tree_with_executable()
        tt = tree.transform()
        newfile = tt.trans_id_tree_path('newfile')
        tt.delete_contents(newfile)
        tt.create_file([b'Woooorld!'], newfile)
        tt.apply()
        tree = workingtree.WorkingTree.open('tree')
        tree.lock_write()
        self.addCleanup(tree.unlock)
        self.assertTrue(tree.is_executable('newfile'))
        transform.revert(tree, tree.basis_tree(), None, backups=True)
        with tree.get_file('newfile', 'rb') as f:
            self.assertEqual(b'helooo!', f.read())
        self.assertTrue(tree.is_executable('newfile'))

    def test_revert_executable(self):
        tree = self.tree_with_executable()
        tt = tree.transform()
        newfile = tt.trans_id_tree_path('newfile')
        tt.set_executability(False, newfile)
        tt.apply()
        tree.lock_write()
        self.addCleanup(tree.unlock)
        transform.revert(tree, tree.basis_tree(), None)
        self.assertTrue(tree.is_executable('newfile'))

    def test_revert_deletes_files_from_revert(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['file'])
        tree.add('file')
        rev1 = tree.commit('added file')
        with tree.lock_read():
            file_sha = tree.get_file_sha1('file')
        os.unlink('file')
        tree.commit('removed file')
        self.assertPathDoesNotExist('file')
        tree.revert(old_tree=tree.branch.repository.revision_tree(rev1))
        self.assertEqual({'file': file_sha}, tree.merge_modified())
        self.assertPathExists('file')
        tree.revert()
        self.assertPathDoesNotExist('file')
        self.assertEqual({}, tree.merge_modified())

    def test_revert_file_in_deleted_dir(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['dir/', 'dir/file1', 'dir/file2'])
        tree.add(['dir', 'dir/file1', 'dir/file2'],
                 ids=[b'dir-id', b'file1-id', b'file2-id'])
        tree.commit("Added files")
        os.unlink('dir/file1')
        os.unlink('dir/file2')
        os.rmdir('dir')
        tree.remove(['dir/', 'dir/file1', 'dir/file2'])
        tree.revert(['dir/file1'])
        self.assertPathExists('dir/file1')
        self.assertPathDoesNotExist('dir/file2')
        self.assertEqual(b'dir-id', tree.path2id('dir'))

    def test_revert_root_id_change(self):
        tree = self.make_branch_and_tree('.')
        tree.set_root_id(b'initial-root-id')
        self.build_tree(['file1'])
        tree.add(['file1'])
        tree.commit('first')
        tree.set_root_id(b'temp-root-id')
        self.assertEqual(b'temp-root-id', tree.path2id(''))
        tree.revert()
        self.assertEqual(b'initial-root-id', tree.path2id(''))
