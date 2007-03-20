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
        tree = self.make_branch_and_tree('%s_tree' % format, format=format)
        tree = workingtree.WorkingTree.open('%s_tree' % format)
        self.assertEqual(format, info.describe_format(tree.bzrdir,
            tree.branch.repository, tree.branch, tree))

    def assertBranchDescription(self, format, expected=None):
        if expected is None:
            expected = format
        branch = self.make_branch('%s_branch' % format, format=format)
        branch = _mod_branch.Branch.open('%s_branch' % format)
        self.assertEqual(expected, info.describe_format(branch.bzrdir,
            branch.repository, branch, None))

    def assertRepoDescription(self, format, expected=None):
        if expected is None:
            expected = format
        repo = self.make_repository('%s_repo' % format, format=format)
        repo = _mod_repository.Repository.open('%s_repo' % format)
        self.assertEqual(expected, info.describe_format(repo.bzrdir,
            repo, None, None))

    def test_describe_format(self):
        for key in bzrdir.format_registry.keys():
            if key == 'default':
                continue
            self.assertTreeDescription(key)

        for key in bzrdir.format_registry.keys():
            if key == 'default':
                continue
            expected = None
            if key in ('dirstate', 'knit'):
                expected = 'dirstate / knit'
            self.assertBranchDescription(key, expected)

        for key in bzrdir.format_registry.keys():
            if key == 'default':
                continue
            expected = None
            if key in ('dirstate', 'knit', 'dirstate-tags'):
                expected = 'dirstate / dirstate-tags / knit'
            self.assertRepoDescription(key, expected)

        format = bzrdir.format_registry.make_bzrdir('metaweave')
        format.set_branch_format(_mod_branch.BzrBranchFormat6())
        tree = self.make_branch_and_tree('unknown', format=format)
        self.assertEqual('unnamed', info.describe_format(tree.bzrdir,
            tree.branch.repository, tree.branch, tree))
