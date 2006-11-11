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


"""Black-box tests for bzr remove-tree."""

import os

from bzrlib.tests.blackbox import ExternalBase


class TestRemoveTree(ExternalBase):

    def setUp(self):
        super(TestRemoveTree, self).setUp()
        self.tree = self.make_branch_and_tree('branch1')
        self.build_tree(['branch1/foo'])
        self.tree.add('foo')
        self.tree.commit('1')
        self.failUnlessExists('branch1/foo')

    # Success modes

    def test_remove_tree_original_branch(self):
        os.chdir('branch1')
        self.run_bzr('remove-tree')
        self.failIfExists('foo')
    
    def test_remove_tree_original_branch_explicit(self):
        self.run_bzr('remove-tree', 'branch1')
        self.failIfExists('branch1/foo')

    def test_remove_tree_sprouted_branch(self):
        self.tree.bzrdir.sprout('branch2')
        self.failUnlessExists('branch2/foo')
        os.chdir('branch2')
        self.run_bzr('remove-tree')
        self.failIfExists('foo')
    
    def test_remove_tree_sprouted_branch_explicit(self):
        self.tree.bzrdir.sprout('branch2')
        self.failUnlessExists('branch2/foo')
        self.run_bzr('remove-tree', 'branch2')
        self.failIfExists('branch2/foo')

    def test_remove_tree_checkout(self):
        self.tree.branch.create_checkout('branch2', lightweight=False)
        self.failUnlessExists('branch2/foo')
        os.chdir('branch2')
        self.run_bzr('remove-tree')
        self.failIfExists('foo')
        os.chdir('..')
        self.failUnlessExists('branch1/foo')
    
    def test_remove_tree_checkout_explicit(self):
        self.tree.branch.create_checkout('branch2', lightweight=False)
        self.failUnlessExists('branch2/foo')
        self.run_bzr('remove-tree', 'branch2')
        self.failIfExists('branch2/foo')
        self.failUnlessExists('branch1/foo')

    # Failure modes

    def test_remove_tree_lightweight_checkout(self):
        self.tree.branch.create_checkout('branch2', lightweight=True)
        self.failUnlessExists('branch2/foo')
        os.chdir('branch2')
        output = self.run_bzr_error(
            ["Cannot remove working tree from lightweight checkout"],
            'remove-tree', retcode=3)
        self.failUnlessExists('foo')
        os.chdir('..')
        self.failUnlessExists('branch1/foo')
    
    def test_remove_tree_lightweight_checkout_explicit(self):
        self.tree.branch.create_checkout('branch2', lightweight=True)
        self.failUnlessExists('branch2/foo')
        output = self.run_bzr(
            ["Cannot remove working tree from lightweight checkout"],
            'remove-tree', 'branch2', retcode=3)
        self.failUnlessExists('branch2/foo')
        self.failUnlessExists('branch1/foo')

    def test_remove_tree_empty_dir(self):
        os.mkdir('branch2')
        os.chdir('branch2')
        output = self.run_bzr(["Not a branch"],
                              'remove-tree', retcode=3)

    def test_remove_tree_repeatedly(self):
        self.run_bzr('remove-tree', 'branch1')
        self.failIfExists('branch1/foo')
        output = self.run_bzr_error(["No working tree to remove"],
                                    'remove-tree', 'branch1', retcode=3)

    def test_remove_tree_remote_path(self):
        # TODO: I can't think of a way to implement this...
        pass
