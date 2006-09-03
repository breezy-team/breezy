# Copyright (C) 2006 by Canonical Ltd
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
