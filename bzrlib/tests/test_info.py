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
    bzrdir,
    info,
    tests,
    workingtree,
    repository as _mod_repository,
    )


class TestInfo(tests.TestCaseWithTransport):

    def test_describe_standalone_layout(self):
        tree = self.make_branch_and_tree('tree')
        self.assertEqual('Empty control directory', info.describe_layout())
        self.assertEqual('Unshared repository with trees',
            info.describe_layout(tree.branch.repository))
        tree.branch.repository.set_make_working_trees(False)
        self.assertEqual('Unshared repository',
            info.describe_layout(tree.branch.repository))
        self.assertEqual('Standalone branch',
            info.describe_layout(tree.branch.repository, tree.branch))
        self.assertEqual('Standalone branchless tree',
            info.describe_layout(tree.branch.repository, None, tree))
        self.assertEqual('Standalone tree',
            info.describe_layout(tree.branch.repository, tree.branch, tree))
        tree.branch.bind(tree.branch)
        self.assertEqual('Bound branch',
            info.describe_layout(tree.branch.repository, tree.branch))
        self.assertEqual('Checkout',
            info.describe_layout(tree.branch.repository, tree.branch, tree))
        checkout = tree.branch.create_checkout('checkout', lightweight=True)
        self.assertEqual('Lightweight checkout',
            info.describe_layout(checkout.branch.repository, checkout.branch,
                                 checkout))

    def test_describe_repository_layout(self):
        repository = self.make_repository('.', shared=True)
        tree = bzrdir.BzrDir.create_branch_convenience('tree',
            force_new_tree=True).bzrdir.open_workingtree()
        self.assertEqual('Shared repository with trees',
            info.describe_layout(tree.branch.repository))
        repository.set_make_working_trees(False)
        self.assertEqual('Shared repository',
            info.describe_layout(tree.branch.repository))
        self.assertEqual('Repository branch',
            info.describe_layout(tree.branch.repository, tree.branch))
        self.assertEqual('Repository branchless tree',
            info.describe_layout(tree.branch.repository, None, tree))
        self.assertEqual('Repository tree',
            info.describe_layout(tree.branch.repository, tree.branch, tree))
        tree.branch.bind(tree.branch)
        self.assertEqual('Repository checkout',
            info.describe_layout(tree.branch.repository, tree.branch, tree))
        checkout = tree.branch.create_checkout('checkout', lightweight=True)
        self.assertEqual('Lightweight checkout',
            info.describe_layout(checkout.branch.repository, checkout.branch,
                                 checkout))

    def assertTreeDescription(self, format):
        """Assert a tree's format description matches expectations"""
        self.make_branch_and_tree('%s_tree' % format, format=format)
        tree = workingtree.WorkingTree.open('%s_tree' % format)
        self.assertEqual(format, info.describe_format(tree.bzrdir,
            tree.branch.repository, tree.branch, tree))

    def assertCheckoutDescription(self, format, expected=None):
        """Assert a checkout's format description matches expectations"""
        if expected is None:
            expected = format
        branch = self.make_branch('%s_cobranch' % format, format=format)
        # this ought to be easier...
        branch.create_checkout('%s_co' % format,
            lightweight=True).bzrdir.destroy_workingtree()
        control = bzrdir.BzrDir.open('%s_co' % format)
        old_format = control._format.workingtree_format
        try:
            control._format.workingtree_format = \
                bzrdir.format_registry.make_bzrdir(format).workingtree_format
            control.create_workingtree()
            tree = workingtree.WorkingTree.open('%s_co' % format)
            self.assertEqual(expected, info.describe_format(tree.bzrdir,
                tree.branch.repository, tree.branch, tree))
        finally:
            control._format.workingtree_format = old_format

    def assertBranchDescription(self, format, expected=None):
        """Assert branch's format description matches expectations"""
        if expected is None:
            expected = format
        self.make_branch('%s_branch' % format, format=format)
        branch = _mod_branch.Branch.open('%s_branch' % format)
        self.assertEqual(expected, info.describe_format(branch.bzrdir,
            branch.repository, branch, None))

    def assertRepoDescription(self, format, expected=None):
        """Assert repository's format description matches expectations"""
        if expected is None:
            expected = format
        self.make_repository('%s_repo' % format, format=format)
        repo = _mod_repository.Repository.open('%s_repo' % format)
        self.assertEqual(expected, info.describe_format(repo.bzrdir,
            repo, None, None))

    def test_describe_tree_format(self):
        for key in bzrdir.format_registry.keys():
            if key == 'default':
                continue
            self.assertTreeDescription(key)

    def test_describe_checkout_format(self):
        for key in bzrdir.format_registry.keys():
            if key in ('default', 'weave'):
                continue
            expected = None
            if key in ('dirstate', 'dirstate-tags', 'dirstate-with-subtree'):
                expected = 'dirstate or dirstate-tags'
            if key in ('knit', 'metaweave'):
                expected = 'knit or metaweave'
            self.assertCheckoutDescription(key, expected)

    def test_describe_branch_format(self):
        for key in bzrdir.format_registry.keys():
            if key == 'default':
                continue
            expected = None
            if key in ('dirstate', 'knit'):
                expected = 'dirstate or knit'
            self.assertBranchDescription(key, expected)

    def test_describe_repo_format(self):
        for key in bzrdir.format_registry.keys():
            if key == 'default':
                continue
            expected = None
            if key in ('dirstate', 'knit', 'dirstate-tags'):
                expected = 'dirstate or dirstate-tags or knit'
            self.assertRepoDescription(key, expected)

        format = bzrdir.format_registry.make_bzrdir('metaweave')
        format.set_branch_format(_mod_branch.BzrBranchFormat6())
        tree = self.make_branch_and_tree('unknown', format=format)
        self.assertEqual('unnamed', info.describe_format(tree.bzrdir,
            tree.branch.repository, tree.branch, tree))

    def test_gather_location_standalone(self):
        tree = self.make_branch_and_tree('tree')
        self.assertEqual([('branch root', tree.bzrdir.root_transport.base)],
            info.gather_location_info(tree.branch.repository, tree.branch,
                                      tree))
        self.assertEqual([('branch root', tree.bzrdir.root_transport.base)],
            info.gather_location_info(tree.branch.repository, tree.branch))
        return tree

    def test_gather_location_repo(self):
        srepo = self.make_repository('shared', shared=True)
        self.assertEqual([('shared repository',
                          srepo.bzrdir.root_transport.base)],
                          info.gather_location_info(srepo))
        urepo = self.make_repository('unshared')
        self.assertEqual([('repository',
                          urepo.bzrdir.root_transport.base)],
                          info.gather_location_info(urepo))

    def test_gather_location_repo_branch(self):
        srepo = self.make_repository('shared', shared=True)
        self.assertEqual([('shared repository',
                          srepo.bzrdir.root_transport.base)],
                          info.gather_location_info(srepo))
        tree = self.make_branch_and_tree('shared/tree')
        self.assertEqual([('shared repository',
                          srepo.bzrdir.root_transport.base),
                          ('repository branch', 'tree')],
                          info.gather_location_info(srepo,
                              tree.branch, tree))

    def test_gather_location_light_checkout(self):
        tree = self.make_branch_and_tree('tree')
        lcheckout = tree.branch.create_checkout('lcheckout', lightweight=True)
        self.assertEqual(
            [('light checkout root', lcheckout.bzrdir.root_transport.base),
             ('checkout of branch', tree.bzrdir.root_transport.base)],
            self.gather_tree_location_info(lcheckout))

    def test_gather_location_heavy_checkout(self):
        tree = self.make_branch_and_tree('tree')
        checkout = tree.branch.create_checkout('checkout')
        self.assertEqual(
            [('checkout root', checkout.bzrdir.root_transport.base),
             ('checkout of branch', tree.bzrdir.root_transport.base)],
            self.gather_tree_location_info(checkout))
        light_checkout = checkout.branch.create_checkout('light_checkout',
                                                         lightweight=True)
        self.assertEqual(
            [('light checkout root',
              light_checkout.bzrdir.root_transport.base),
             ('checkout root', checkout.bzrdir.root_transport.base),
             ('checkout of branch', tree.bzrdir.root_transport.base)],
             self.gather_tree_location_info(light_checkout)
             )

    def test_gather_location_shared_repo_checkout(self):
        tree = self.make_branch_and_tree('tree')
        srepo = self.make_repository('shared', shared=True)
        shared_checkout = tree.branch.create_checkout('shared/checkout')
        self.assertEqual(
            [('repository checkout root',
              shared_checkout.bzrdir.root_transport.base),
             ('checkout of branch', tree.bzrdir.root_transport.base),
             ('shared repository', srepo.bzrdir.root_transport.base)],
             self.gather_tree_location_info(shared_checkout))

    def gather_tree_location_info(self, tree):
        return info.gather_location_info(tree.branch.repository, tree.branch,
                                         tree)

    def test_gather_location_bound(self):
        branch = self.make_branch('branch')
        bound_branch = self.make_branch('bound_branch')
        bound_branch.bind(branch)
        self.assertEqual(
            [('branch root', bound_branch.bzrdir.root_transport.base),
             ('bound to branch', branch.bzrdir.root_transport.base)],
            info.gather_location_info(bound_branch.repository, bound_branch)
        )
