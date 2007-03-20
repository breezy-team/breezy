from bzrlib import (
    bzrdir,
    info,
    tests,
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
