import os

from bzrlib import bzrdir, repository, tests, workingtree


class TestJoin(tests.TestCaseWithTransport):

    def make_trees(self):
        format = bzrdir.get_knit2_format()
        base_tree = self.make_branch_and_tree('tree', format=format)
        base_tree.commit('empty commit')
        self.build_tree(['tree/subtree/', 'tree/subtree/file1'])
        sub_tree = self.make_branch_and_tree('tree/subtree')
        sub_tree.add('file1', 'file1-id')
        sub_tree.commit('added file1')
        return base_tree, sub_tree

    def check_success(self, path):
        base_tree = workingtree.WorkingTree.open(path)
        self.assertEqual('file1-id', base_tree.path2id('subtree/file1'))

    def test_join(self):
        base_tree, sub_tree = self.make_trees()
        self.run_bzr('join', 'tree/subtree')
        self.check_success('tree')

    def test_join_dot(self):
        base_tree, sub_tree = self.make_trees()
        self.run_bzr('join', '.', working_dir='tree/subtree')
        self.check_success('tree')

    def test_join_error(self):
        base_tree, sub_tree = self.make_trees()
        os.mkdir('tree/subtree2')
        os.rename('tree/subtree', 'tree/subtree2/subtree')
        self.run_bzr_error(('Cannot join .*subtree.  Parent directory is not'
                            ' versioned',), 'join', 'tree/subtree2/subtree')
        self.run_bzr_error(('Not a branch:.*subtree2',), 'join', 
                            'tree/subtree2')
