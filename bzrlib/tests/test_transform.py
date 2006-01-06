from bzrlib.tests import TestCaseInTempDir
from bzrlib.branch import Branch
from bzrlib.transform import TreeTransform
from bzrlib.errors import DuplicateKey, MalformedTransform, NoSuchFile

class TestTreeTransform(TestCaseInTempDir):
    def test_build(self):
        branch = Branch.initialize('.')
        wt = branch.working_tree()
        transform = TreeTransform(wt)
        try:
            root = transform.get_id_tree(wt.get_root_id())
            self.assertEqual(transform.final_kind(root), 'directory')
            trans_id = transform.create_path('name', root)
            self.assertRaises(NoSuchFile, transform.final_kind, trans_id)
            transform.create_file('contents', trans_id)
            self.assertEqual(transform.final_kind(trans_id), 'file')
            self.assertRaises(DuplicateKey, transform.create_file, 'contents', 
                              trans_id)
            transform.version_file('my_pretties', trans_id)
            self.assertRaises(DuplicateKey, transform.version_file,
                              'my_pretties', trans_id)
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
            self.assertEqual(len(transform.find_conflicts()), 0)
            self.assertEqual('contents', file('name').read())
            self.assertEqual(wt.path2id('name'), 'my_pretties')
        finally:
            transform.finalize()

    def test_conflicts(self):
        branch = Branch.initialize('.')
        wt = branch.working_tree()
        transform = TreeTransform(wt)
        try:
            root = transform.get_id_tree(wt.get_root_id())
            trans_id = transform.new_file('name', root, 'contents', 
                                          'my_pretties')
            self.assertEqual(len(transform.find_conflicts()), 0)
            trans_id2 = transform.new_file('name', root, 'Crontents', 'toto')
            self.assertEqual(transform.find_conflicts(), 
                             [('duplicate', trans_id, trans_id2)])
            self.assertRaises(MalformedTransform, transform.apply)
            transform.adjust_path('name2', root, trans_id2)
            transform.apply()
            self.assertEqual('contents', file('name').read())
            self.assertEqual(wt.path2id('name'), 'my_pretties')
        finally:
            transform.finalize()
