from bzrlib.tests import TestCaseInTempDir
from bzrlib.branch import Branch
from bzrlib.transform import TreeTransform

class TestTreeTransform(TestCaseInTempDir):
    def test_build(self):
        branch = Branch.initialize('.')
        wt = branch.working_tree()
        transform = TreeTransform(wt)
        try:
            root = transform.get_id_tree(wt.get_root_id())
            trans_id = transform.create_path('name', root)
            transform.create_file('contents', trans_id)
            transform.version_file('my_pretties', trans_id)
            transform.apply()
            self.assertEqual('contents', file('name').read())
            self.assertEqual(wt.path2id('name'), 'my_pretties')
        finally:
            transform.finalize()
        # is it safe to finalize repeatedly?
        transform.finalize()

    def test_convenience(self):
        branch = Branch.initialize('.')
        wt = branch.working_tree()
        transform = TreeTransform(wt)
        try:
            root = transform.get_id_tree(wt.get_root_id())
            trans_id = transform.new_file('name', root, 'contents', 
                                          'my_pretties')
            transform.apply()
            self.assertEqual('contents', file('name').read())
            self.assertEqual(wt.path2id('name'), 'my_pretties')
        finally:
            transform.finalize()
