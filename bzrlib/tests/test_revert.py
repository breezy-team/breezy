# Copyright (C) 2006 Canonical Ltd
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


from bzrlib import merge, tests


class TestRevert(tests.TestCaseWithTransport):
    """Ensure that revert behaves as expected"""

    def test_revert_merged_dir(self):
        """Reverting a merge that adds a directory deletes the directory"""
        source_tree = self.make_branch_and_tree('source')
        source_tree.commit('empty tree')
        target_tree = source_tree.bzrdir.sprout('target').open_workingtree()
        self.build_tree(['source/dir/', 'source/dir/contents'])
        source_tree.add(['dir', 'dir/contents'], ['dir-id', 'contents-id'])
        source_tree.commit('added dir')
        merge.merge_inner(target_tree.branch, source_tree.basis_tree(), 
                          target_tree.basis_tree(), this_tree=target_tree)
        self.failUnlessExists('target/dir')
        self.failUnlessExists('target/dir/contents')
        target_tree.revert([])
        self.failIfExists('target/dir/contents')
        self.failIfExists('target/dir')

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
        merge_target = tree.bzrdir.sprout('merge_target').open_workingtree()
        self.build_tree(['tree/new_file'])

        # newly-added files should not be deleted
        tree.add('new_file')
        basis_tree = tree.basis_tree()
        tree.revert([])
        self.failUnlessExists('tree/new_file')

        # unchanged files should be deleted
        tree.add('new_file')
        tree.commit('add new_file')
        tree.revert([], old_tree=basis_tree)
        self.failIfExists('tree/new_file')
        
        # files should be deleted if their changes came from merges
        merge_target.merge_from_branch(tree.branch)
        self.failUnlessExists('merge_target/new_file')
        merge_target.revert([])
        self.failIfExists('merge_target/new_file')

        # files should not be deleted if changed after a merge
        merge_target.merge_from_branch(tree.branch)
        self.failUnlessExists('merge_target/new_file')
        self.build_tree_contents([('merge_target/new_file', 'new_contents')])
        merge_target.revert([])
        self.failUnlessExists('merge_target/new_file')
