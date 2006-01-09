from bzrlib.tests import TestCaseInTempDir
from bzrlib.branch import Branch
from bzrlib.transform import TreeTransform
from bzrlib.errors import DuplicateKey, MalformedTransform, NoSuchFile
from bzrlib.osutils import file_kind
import os

class TestTreeTransform(TestCaseInTempDir):
    def test_build(self):
        branch = Branch.initialize('.')
        wt = branch.working_tree()
        transform = TreeTransform(wt)
        try:
            root = transform.get_id_tree(wt.get_root_id())
            self.assertIs(transform.get_tree_parent(root), None)
            imaginary_id = transform.get_tree_path_id('imaginary')
            self.assertEqual(transform.get_tree_parent(imaginary_id), root)
            self.assertEqual(transform.final_kind(root), 'directory')
            self.assertEqual(transform.final_file_id(root), wt.get_root_id())
            trans_id = transform.create_path('name', root)
            self.assertIs(transform.final_file_id(trans_id), None)
            self.assertRaises(NoSuchFile, transform.final_kind, trans_id)
            transform.create_file('contents', trans_id)
            transform.set_executability(True, trans_id)
            transform.version_file('my_pretties', trans_id)
            self.assertRaises(DuplicateKey, transform.version_file,
                              'my_pretties', trans_id)
            self.assertEqual(transform.final_file_id(trans_id), 'my_pretties')
            self.assertEqual(transform.final_parent(trans_id), root)
            self.assertIs(transform.final_parent(root), None)
            oz_id = transform.create_path('oz', root)
            transform.create_directory(oz_id)
            transform.version_file('ozzie', oz_id)
            wiz_id = transform.create_path('wizard', oz_id)
            transform.create_symlink('behind_curtain', wiz_id)
            transform.version_file('wiz-id', wiz_id)
            trans_id2 = transform.create_path('name2', root)
            transform.create_file('contents', trans_id2)
            transform.set_executability(False, trans_id2)
            transform.version_file('my_pretties2', trans_id2)
            transform.apply()
            self.assertEqual('contents', file('name').read())
            self.assertEqual(wt.path2id('name'), 'my_pretties')
            self.assertIs(wt.is_executable('my_pretties'), True)
            self.assertIs(wt.is_executable('my_pretties2'), False)
            self.assertEqual('directory', file_kind('oz'))
            self.assertEqual(file_kind('oz/wizard'), 'symlink')
            self.assertEqual(os.readlink('oz/wizard'), 'behind_curtain')
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
            oz = transform.new_directory('oz', root, 'oz-id')
            dorothy = transform.new_directory('dorothy', oz, 'dorothy-id')
            toto = transform.new_file('toto', dorothy, 'toto-contents', 
                                      'toto-id')
            wizard = transform.new_symlink('wizard', oz, 'wizard-target', 
                                           'wizard-id')
            transform.apply()
            self.assertEqual(len(transform.find_conflicts()), 0)
            self.assertEqual('contents', file('name').read())
            self.assertEqual(wt.path2id('name'), 'my_pretties')
            self.assertEqual(wt.path2id('oz'), 'oz-id')
            self.assertEqual(wt.path2id('oz/dorothy'), 'dorothy-id')
            self.assertEqual(wt.path2id('oz/dorothy/toto'), 'toto-id')
            self.assertEqual(wt.path2id('oz/wizard'), 'wizard-id')
            self.assertEqual('toto-contents', file('oz/dorothy/toto').read())
            self.assertEqual(os.readlink('oz/wizard'), 'wizard-target')
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
            transform.adjust_path('name', trans_id, trans_id2)
            self.assertEqual(transform.find_conflicts(), 
                             [('non-directory parent', trans_id)])
            tinman_id = transform.get_tree_path_id('tinman')
            transform.adjust_path('name', tinman_id, trans_id2)
            self.assertEqual(transform.find_conflicts(), 
                             [('unversioned parent', tinman_id), 
                              ('missing parent', tinman_id)])
            lion_id = transform.create_path('lion', root)
            self.assertEqual(transform.find_conflicts(), 
                             [('unversioned parent', tinman_id), 
                              ('missing parent', tinman_id)])
            transform.adjust_path('name', lion_id, trans_id2)
            self.assertEqual(transform.find_conflicts(), 
                             [('unversioned parent', lion_id),
                              ('missing parent', lion_id)])
            transform.version_file("Courage", lion_id)
            self.assertEqual(transform.find_conflicts(), 
                             [('missing parent', lion_id), 
                              ('versioning no contents', lion_id)])
            transform.adjust_path('name2', root, trans_id2)
            self.assertEqual(transform.find_conflicts(), 
                             [('versioning no contents', lion_id)])
            transform.create_file('Contents, okay?', lion_id)
            transform.adjust_path('name2', trans_id2, trans_id2)
            self.assertEqual(transform.find_conflicts(), 
                             [('parent loop', trans_id2), 
                              ('non-directory parent', trans_id2)])
            transform.adjust_path('name2', root, trans_id2)
            oz_id = transform.new_directory('oz', root)
            transform.set_executability(True, oz_id)
            self.assertEqual(transform.find_conflicts(), 
                             [('unversioned executability', oz_id)])
            transform.version_file('oz-id', oz_id)
            self.assertEqual(transform.find_conflicts(), 
                             [('non-file executability', oz_id)])
            transform.set_executability(None, oz_id)
            tip_id = transform.new_symlink('tip', oz_id, 'ozma', 'tip-id')
            transform.set_executability(True, tip_id)
            self.assertEqual(transform.find_conflicts(), 
                             [('non-file executability', tip_id)])
            transform.set_executability(None, tip_id)
            transform.apply()
            self.assertEqual('contents', file('name').read())
            self.assertEqual(wt.path2id('name'), 'my_pretties')
        finally:
            transform.finalize()
