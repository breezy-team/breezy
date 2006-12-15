from bzrlib.tests.tree_implementations import TestCaseWithTree

class TestAnnotate(TestCaseWithTree):
    
    def test_annotate(self):
        work_tree = self.make_branch_and_tree('wt')
        tree = self.get_tree_no_parents_abc_content(work_tree)
        tree_revision = getattr(tree, 'get_revision_id', lambda: 'current:')()
        for revision, line in tree.annotate_iter('a-id'):
            self.assertEqual('contents of a\n', line)
            self.assertEqual(tree_revision, revision)
