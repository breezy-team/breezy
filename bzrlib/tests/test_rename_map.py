from bzrlib.rename_map import RenameMap
from bzrlib.tests import TestCaseWithTransport

class TestRenameMap(TestCaseWithTransport):

    a_lines = 'a\nb\nc\n'.splitlines(True)
    b_lines = 'b\nc\nd\n'.splitlines(True)


    def test_add_edge_hashes(self):
        rn = RenameMap()
        rn.add_edge_hashes(self.a_lines, 'a')
        self.assertEqual(set(['a']), rn.edge_hashes[hash(('a\n', 'b\n'))])
        self.assertEqual(set(['a']), rn.edge_hashes[hash(('b\n', 'c\n'))])
        self.assertIs(None, rn.edge_hashes.get(hash(('c\n', 'd\n'))))

    def test_add_file_edge_hashes(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree_contents([('tree/a', ''.join(self.a_lines))])
        tree.add('a', 'a')
        rn = RenameMap()
        rn.add_file_edge_hashes(tree, ['a'])
        self.assertEqual(set(['a']), rn.edge_hashes[hash(('a\n', 'b\n'))])
        self.assertEqual(set(['a']), rn.edge_hashes[hash(('b\n', 'c\n'))])
        self.assertIs(None, rn.edge_hashes.get(hash(('c\n', 'd\n'))))

    def test_hitcounts(self):
        rn = RenameMap()
        rn.add_edge_hashes(self.a_lines, 'a')
        rn.add_edge_hashes(self.b_lines, 'b')
        self.assertEqual({'a': 3, 'b': 1}, rn.hitcounts(self.a_lines))
        self.assertEqual({'a': 1}, rn.hitcounts(self.a_lines[:-1]))
        self.assertEqual({'b': 3, 'a': 1}, rn.hitcounts(self.b_lines))

    def test_file_match(self):
        rn = RenameMap()
        rn.add_edge_hashes(self.a_lines, 'aid')
        rn.add_edge_hashes(self.b_lines, 'bid')
        tree = self.make_branch_and_tree('tree')
        self.build_tree_contents([('tree/a', ''.join(self.a_lines))])
        self.build_tree_contents([('tree/b', ''.join(self.b_lines))])
        self.assertEqual({'a': 'aid', 'b': 'bid'},
                         rn.file_match(tree, ['a', 'b']))

    def test_file_match_no_dups(self):
        rn = RenameMap()
        rn.add_edge_hashes(self.a_lines, 'aid')
        tree = self.make_branch_and_tree('tree')
        self.build_tree_contents([('tree/a', ''.join(self.a_lines))])
        self.build_tree_contents([('tree/b', ''.join(self.b_lines))])
        self.build_tree_contents([('tree/c', ''.join(self.b_lines))])
        self.assertEqual({'a': 'aid'},
                         rn.file_match(tree, ['a', 'b', 'c']))
