from bzrlib.tests import TestCaseInTempDir
from bzrlib.branch import Branch
from bzrlib.transform import TreeTransform, ROOT_PARENT, FinalPaths
from bzrlib.errors import (DuplicateKey, MalformedTransform, NoSuchFile,
                           ReusingTransform)
from bzrlib.osutils import file_kind
import os

class TestTreeTransform(TestCaseInTempDir):
    def test_build(self):
        branch = Branch.initialize('.')
        wt = branch.working_tree()
        transform = TreeTransform(wt)
        try:
            root = transform.get_id_tree(wt.get_root_id())
            self.assertIs(transform.get_tree_parent(root), ROOT_PARENT)
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
            self.assertIs(transform.final_parent(root), ROOT_PARENT)
            self.assertIs(transform.get_tree_parent(root), ROOT_PARENT)
            oz_id = transform.create_path('oz', root)
            transform.create_directory(oz_id)
            transform.version_file('ozzie', oz_id)
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
                                          'my_pretties', True)
            oz = transform.new_directory('oz', root, 'oz-id')
            dorothy = transform.new_directory('dorothy', oz, 'dorothy-id')
            toto = transform.new_file('toto', dorothy, 'toto-contents', 
                                      'toto-id', False)

            self.assertEqual(len(transform.find_conflicts()), 0)
            transform.apply()
            self.assertRaises(ReusingTransform, transform.find_conflicts)
            self.assertEqual('contents', file('name').read())
            self.assertEqual(wt.path2id('name'), 'my_pretties')
            self.assertIs(wt.is_executable('my_pretties'), True)
            self.assertEqual(wt.path2id('oz'), 'oz-id')
            self.assertEqual(wt.path2id('oz/dorothy'), 'dorothy-id')
            self.assertEqual(wt.path2id('oz/dorothy/toto'), 'toto-id')

            self.assertEqual('toto-contents', file('oz/dorothy/toto').read())
            self.assertIs(wt.is_executable('toto-id'), False)
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
                             [('duplicate', trans_id, trans_id2, 'name')])
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
        finally:
            transform.finalize()
            self.assertEqual(wt.path2id('name'), 'my_pretties')
            self.assertEqual('contents', file(wt.abspath('name')).read())
        transform2 = TreeTransform(wt)
        try:
            oz_id = transform2.get_id_tree('oz-id')
            newtip = transform2.new_file('tip', oz_id, 'other', 'tip-id')
            result = transform2.find_conflicts()
            fp = FinalPaths(transform2._new_root, transform2)
            self.assert_('oz/tip' in transform2._tree_path_ids)
            self.assertEqual(fp.get_path(newtip), 'oz/tip')
            self.assertEqual(len(result), 1)
            self.assertEqual((result[0][0], result[0][1]), 
                             ('duplicate', newtip))
        finally:
            transform2.finalize()
        transform3 = TreeTransform(wt)
        try:
            oz_id = transform3.get_id_tree('oz-id')
            transform3.delete_contents(oz_id)
            self.assertEqual(transform3.find_conflicts(), 
                             [('missing parent', oz_id)])
            root_id = transform3.get_id_tree('TREE_ROOT')
            tip_id = transform3.get_id_tree('tip-id')
            transform3.adjust_path('tip', root_id, tip_id)
            transform3.apply()
        finally:
            transform3.finalize()

    def test_name_invariants(self):
        branch = Branch.initialize('.')
        wt = branch.working_tree()
        create_tree = TreeTransform(wt)
        try:
            # prepare tree
            root = create_tree.get_id_tree('TREE_ROOT')
            create_tree.new_file('name1', root, 'hello1', 'name1')
            create_tree.new_file('name2', root, 'hello2', 'name2')
            ddir = create_tree.new_directory('dying_directory', root, 'ddir')
            create_tree.new_file('dying_file', ddir, 'goodbye1', 'dfile')
            create_tree.new_file('moving_file', ddir, 'later1', 'mfile')
            create_tree.new_file('moving_file2', root, 'later2', 'mfile2')
            create_tree.apply()
        finally:
            create_tree.finalize()
        mangle_tree = TreeTransform(wt)
        try:
            root = mangle_tree.get_id_tree('TREE_ROOT')
            #swap names
            name1 = mangle_tree.get_id_tree('name1')
            name2 = mangle_tree.get_id_tree('name2')
            mangle_tree.adjust_path('name2', root, name1)
            mangle_tree.adjust_path('name1', root, name2)

            #tests for deleting parent directories 
            ddir = mangle_tree.get_id_tree('ddir')
            mangle_tree.delete_contents(ddir)
            dfile = mangle_tree.get_id_tree('dfile')
            mangle_tree.delete_versioned(dfile)
            mangle_tree.unversion_file(dfile)
            mfile = mangle_tree.get_id_tree('mfile')
            mangle_tree.adjust_path('mfile', root, mfile)

            #tests for adding parent directories
            newdir = mangle_tree.new_directory('new_directory', root, 'newdir')
            mfile2 = mangle_tree.get_id_tree('mfile2')
            mangle_tree.adjust_path('mfile2', newdir, mfile2)
            mangle_tree.new_file('newfile', newdir, 'hello3', 'dfile')
            self.assertEqual(mangle_tree.final_file_id(mfile2), 'mfile2')
            self.assertEqual(mangle_tree.final_parent(mfile2), newdir)
            self.assertEqual(mangle_tree.final_file_id(mfile2), 'mfile2')
            mangle_tree.apply()
        finally:
            mangle_tree.finalize()
        self.assertEqual(file(wt.abspath('name1')).read(), 'hello2')
        self.assertEqual(file(wt.abspath('name2')).read(), 'hello1')
        mfile2_path = wt.abspath(os.path.join('new_directory','mfile2'))
        self.assertEqual(mangle_tree.final_parent(mfile2), newdir)
        self.assertEqual(file(mfile2_path).read(), 'later2')
        self.assertEqual(wt.id2path('mfile2'), 'new_directory/mfile2')
        self.assertEqual(wt.path2id('new_directory/mfile2'), 'mfile2')
        newfile_path = wt.abspath(os.path.join('new_directory','newfile'))
        self.assertEqual(file(newfile_path).read(), 'hello3')
        self.assertEqual(wt.path2id('dying_directory'), 'ddir')
        self.assertIs(wt.path2id('dying_directory/dying_file'), None)
        mfile2_path = wt.abspath(os.path.join('new_directory','mfile2'))

    def test_symlinks(self):
        if not getattr(os, 'symlink', False):
            return
        branch = Branch.initialize('.')
        wt = branch.working_tree()
        transform = TreeTransform(wt)
        try:
            root = transform.get_id_tree(wt.get_root_id())
            oz_id = transform.new_directory('oz', root)
            wizard = transform.new_symlink('wizard', oz, 'wizard-target', 
                                           'wizard-id')
            wiz_id = transform.create_path('wizard2', oz_id)
            transform.create_symlink('behind_curtain', wiz_id)
            transform.version_file('wiz-id2', wiz_id)            
            self.assertEqual(wt.path2id('oz/wizard'), 'wizard-id')
            transform.apply()
            self.assertEqual(file_kind('oz/wizard'), 'symlink')
            self.assertEqual(os.readlink('oz/wizard'), 'behind_curtain')
            self.assertEqual(os.readlink('oz/wizard2'), 'wizard-target')
        finally:
            transform.finalize()
