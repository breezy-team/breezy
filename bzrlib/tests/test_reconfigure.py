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
    branch as _mod_branch,
    errors,
    reconfigure,
    repository,
    tests,
    workingtree,
    )


class TestReconfigure(tests.TestCaseWithTransport):

    def test_tree_to_branch(self):
        tree = self.make_branch_and_tree('tree')
        reconfiguration = reconfigure.Reconfigure.to_branch(tree.bzrdir)
        reconfiguration.apply()
        self.assertRaises(errors.NoWorkingTree, workingtree.WorkingTree.open,
                          'tree')

    def test_modified_tree_to_branch(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/file'])
        tree.add('file')
        reconfiguration = reconfigure.Reconfigure.to_branch(tree.bzrdir)
        self.assertRaises(errors.UncommittedChanges, reconfiguration.apply)
        reconfiguration.apply(force=True)
        self.assertRaises(errors.NoWorkingTree, workingtree.WorkingTree.open,
                          'tree')

    def test_branch_to_branch(self):
        branch = self.make_branch('branch')
        self.assertRaises(errors.AlreadyBranch,
                          reconfigure.Reconfigure.to_branch, branch.bzrdir)

    def test_repo_to_branch(self):
        repo = self.make_repository('repo')
        reconfiguration = reconfigure.Reconfigure.to_branch(repo.bzrdir)
        reconfiguration.apply()

    def test_checkout_to_branch(self):
        branch = self.make_branch('branch')
        checkout = branch.create_checkout('checkout')
        reconfiguration = reconfigure.Reconfigure.to_branch(checkout.bzrdir)
        reconfiguration.apply()
        self.assertIs(None, checkout.branch.get_bound_location())

    def test_lightweight_checkout_to_branch(self):
        branch = self.make_branch('branch')
        checkout = branch.create_checkout('checkout', lightweight=True)
        checkout.commit('first commit', rev_id='rev1')
        reconfiguration = reconfigure.Reconfigure.to_branch(checkout.bzrdir)
        reconfiguration.apply()
        checkout_branch = checkout.bzrdir.open_branch()
        self.assertEqual(checkout_branch.bzrdir.root_transport.base,
                         checkout.bzrdir.root_transport.base)
        self.assertEqual('rev1', checkout_branch.last_revision())
        repo = checkout.bzrdir.open_repository()
        repo.get_revision('rev1')

    def test_lightweight_checkout_to_checkout(self):
        branch = self.make_branch('branch')
        checkout = branch.create_checkout('checkout', lightweight=True)
        reconfiguration = reconfigure.Reconfigure.to_checkout(checkout.bzrdir)
        reconfiguration.apply()
        checkout_branch = checkout.bzrdir.open_branch()
        self.assertIsNot(checkout_branch.get_bound_location(), None)

    def test_lightweight_conversion_uses_shared_repo(self):
        parent = self.make_branch('parent')
        shared_repo = self.make_repository('repo', shared=True)
        checkout = parent.create_checkout('repo/checkout', lightweight=True)
        reconfigure.Reconfigure.to_tree(checkout.bzrdir).apply()
        checkout_repo = checkout.bzrdir.open_branch().repository
        self.assertEqual(shared_repo.bzrdir.root_transport.base,
                         checkout_repo.bzrdir.root_transport.base)

    def test_branch_to_tree(self):
        branch = self.make_branch('branch')
        reconfiguration=reconfigure.Reconfigure.to_tree(branch.bzrdir)
        reconfiguration.apply()
        branch.bzrdir.open_workingtree()

    def test_tree_to_tree(self):
        tree = self.make_branch_and_tree('tree')
        self.assertRaises(errors.AlreadyTree, reconfigure.Reconfigure.to_tree,
                          tree.bzrdir)

    def test_select_bind_location(self):
        branch = self.make_branch('branch')
        reconfiguration = reconfigure.Reconfigure(branch.bzrdir)
        self.assertRaises(errors.NoBindLocation,
                          reconfiguration._select_bind_location)
        branch.set_parent('http://parent')
        self.assertEqual('http://parent',
                         reconfiguration._select_bind_location())
        branch.set_push_location('sftp://push')
        self.assertEqual('sftp://push',
                         reconfiguration._select_bind_location())
        branch.set_bound_location('bzr://foo/old-bound')
        branch.set_bound_location(None)
        self.assertEqual('bzr://foo/old-bound',
                         reconfiguration._select_bind_location())
        branch.set_bound_location('bzr://foo/cur-bound')
        self.assertEqual('bzr://foo/cur-bound',
                         reconfiguration._select_bind_location())
        reconfiguration.new_bound_location = 'ftp://user-specified'
        self.assertEqual('ftp://user-specified',
                         reconfiguration._select_bind_location())

    def test_select_reference_bind_location(self):
        branch = self.make_branch('branch')
        checkout = branch.create_checkout('checkout', lightweight=True)
        reconfiguration = reconfigure.Reconfigure(checkout.bzrdir)
        self.assertEqual(branch.base,
                         reconfiguration._select_bind_location())

    def test_tree_to_checkout(self):
        # A tree with no related branches and no supplied bind location cannot
        # become a checkout
        parent = self.make_branch('parent')

        tree = self.make_branch_and_tree('tree')
        reconfiguration = reconfigure.Reconfigure.to_checkout(tree.bzrdir)
        self.assertRaises(errors.NoBindLocation, reconfiguration.apply)
        # setting a parent allows it to become a checkout
        tree.branch.set_parent(parent.base)
        reconfiguration.apply()
        # supplying a location allows it to become a checkout
        tree2 = self.make_branch_and_tree('tree2')
        reconfiguration = reconfigure.Reconfigure.to_checkout(tree2.bzrdir,
                                                              parent.base)
        reconfiguration.apply()

    def test_tree_to_lightweight_checkout(self):
        # A tree with no related branches and no supplied bind location cannot
        # become a checkout
        parent = self.make_branch('parent')

        tree = self.make_branch_and_tree('tree')
        reconfiguration = reconfigure.Reconfigure.to_lightweight_checkout(
            tree.bzrdir)
        self.assertRaises(errors.NoBindLocation, reconfiguration.apply)
        # setting a parent allows it to become a checkout
        tree.branch.set_parent(parent.base)
        reconfiguration.apply()
        # supplying a location allows it to become a checkout
        tree2 = self.make_branch_and_tree('tree2')
        reconfiguration = reconfigure.Reconfigure.to_lightweight_checkout(
            tree2.bzrdir, parent.base)
        reconfiguration.apply()

    def test_checkout_to_checkout(self):
        parent = self.make_branch('parent')
        checkout = parent.create_checkout('checkout')
        self.assertRaises(errors.AlreadyCheckout,
                          reconfigure.Reconfigure.to_checkout, checkout.bzrdir)

    def test_checkout_to_lightweight(self):
        parent = self.make_branch('parent')
        checkout = parent.create_checkout('checkout')
        checkout.commit('test', rev_id='new-commit', local=True)
        reconfiguration = reconfigure.Reconfigure.to_lightweight_checkout(
            checkout.bzrdir)
        reconfiguration.apply()
        wt = checkout.bzrdir.open_workingtree()
        self.assertTrue(parent.repository.has_same_location(
            wt.branch.repository))
        parent.repository.get_revision('new-commit')
        self.assertRaises(errors.NoRepositoryPresent,
                          checkout.bzrdir.open_repository)

    def test_branch_to_lightweight_checkout(self):
        parent = self.make_branch('parent')
        child = parent.bzrdir.sprout('child').open_workingtree()
        child.commit('test', rev_id='new-commit')
        child.bzrdir.destroy_workingtree()
        reconfiguration = reconfigure.Reconfigure.to_lightweight_checkout(
            child.bzrdir)
        reconfiguration.apply()
        wt = child.bzrdir.open_workingtree()
        self.assertTrue(parent.repository.has_same_location(
            wt.branch.repository))
        parent.repository.get_revision('new-commit')
        self.assertRaises(errors.NoRepositoryPresent,
                          child.bzrdir.open_repository)

    def test_lightweight_checkout_to_lightweight_checkout(self):
        parent = self.make_branch('parent')
        checkout = parent.create_checkout('checkout', lightweight=True)
        self.assertRaises(errors.AlreadyLightweightCheckout,
                          reconfigure.Reconfigure.to_lightweight_checkout,
                          checkout.bzrdir)

    def test_repo_to_tree(self):
        repo = self.make_repository('repo')
        reconfiguration = reconfigure.Reconfigure.to_tree(repo.bzrdir)
        reconfiguration.apply()
        workingtree.WorkingTree.open('repo')

    def test_shared_repo_to_lightweight_checkout(self):
        repo = self.make_repository('repo', shared=True)
        reconfiguration = reconfigure.Reconfigure.to_lightweight_checkout(
            repo.bzrdir)
        self.assertRaises(errors.NoBindLocation, reconfiguration.apply)
        branch = self.make_branch('branch')
        reconfiguration = reconfigure.Reconfigure.to_lightweight_checkout(
            repo.bzrdir, 'branch')
        reconfiguration.apply()
        workingtree.WorkingTree.open('repo')
        repository.Repository.open('repo')

    def test_unshared_repo_to_lightweight_checkout(self):
        repo = self.make_repository('repo', shared=False)
        branch = self.make_branch('branch')
        reconfiguration = reconfigure.Reconfigure.to_lightweight_checkout(
            repo.bzrdir, 'branch')
        reconfiguration.apply()
        workingtree.WorkingTree.open('repo')
        self.assertRaises(errors.NoRepositoryPresent,
                          repository.Repository.open, 'repo')
