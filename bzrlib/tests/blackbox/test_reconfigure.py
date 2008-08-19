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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

from bzrlib import (
    bzrdir,
    errors,
    tests,
    workingtree,
    )


class TestReconfigure(tests.TestCaseWithTransport):

    def test_no_type(self):
        branch = self.make_branch('branch')
        self.run_bzr_error(['No target configuration specified'],
                           'reconfigure branch')

    def test_branch_to_tree(self):
        branch = self.make_branch('branch')
        self.run_bzr('reconfigure --tree branch')
        tree = workingtree.WorkingTree.open('branch')

    def test_tree_to_branch(self):
        tree = self.make_branch_and_tree('tree')
        self.run_bzr('reconfigure --branch tree')
        self.assertRaises(errors.NoWorkingTree,
                          workingtree.WorkingTree.open, 'tree')

    def test_branch_to_specified_checkout(self):
        branch = self.make_branch('branch')
        parent = self.make_branch('parent')
        self.run_bzr('reconfigure branch --checkout --bind-to parent')

    def test_force(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/file'])
        tree.add('file')
        self.run_bzr_error(['Working tree ".*" has uncommitted changes'],
                            'reconfigure --branch tree')
        self.run_bzr('reconfigure --force --branch tree')

    def test_lightweight_checkout_to_checkout(self):
        branch = self.make_branch('branch')
        checkout = branch.create_checkout('checkout', lightweight=True)
        self.run_bzr('reconfigure --checkout checkout')

    def test_no_args(self):
        branch = self.make_branch('branch')
        self.run_bzr_error(['No target configuration specified'],
                           'reconfigure', working_dir='branch')

    def test_checkout_to_lightweight_checkout(self):
        branch = self.make_branch('branch')
        checkout = branch.create_checkout('checkout')
        self.run_bzr('reconfigure --lightweight-checkout checkout')

    def test_standalone_to_use_shared(self):
        self.build_tree(['repo/'])
        tree = self.make_branch_and_tree('repo/tree')
        repo = self.make_repository('repo', shared=True)
        self.run_bzr('reconfigure --use-shared', working_dir='repo/tree')
        tree = workingtree.WorkingTree.open('repo/tree')
        self.assertNotEqual(tree.bzrdir.root_transport.base,
            tree.branch.repository.bzrdir.root_transport.base)

    def test_use_shared_to_standalone(self):
        repo = self.make_repository('repo', shared=True)
        branch = bzrdir.BzrDir.create_branch_convenience('repo/tree')
        self.assertNotEqual(branch.bzrdir.root_transport.base,
            branch.repository.bzrdir.root_transport.base)
        self.run_bzr('reconfigure --standalone', working_dir='repo/tree')
        tree = workingtree.WorkingTree.open('repo/tree')
        self.assertEqual(tree.bzrdir.root_transport.base,
            tree.branch.repository.bzrdir.root_transport.base)
