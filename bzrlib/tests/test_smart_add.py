import os
import unittest

from bzrlib.add import smart_add, smart_add_tree
from bzrlib.tests import TestCaseWithTransport, TestCase
from bzrlib.errors import NoSuchFile
from bzrlib.inventory import InventoryFile, Inventory
from bzrlib.workingtree import WorkingTree

class TestSmartAdd(TestCaseWithTransport):

    def test_add_dot_from_root(self):
        """Test adding . from the root of the tree.""" 
        from bzrlib.add import smart_add
        paths = ("original/", "original/file1", "original/file2")
        self.build_tree(paths)
        wt = self.make_branch_and_tree('.')
        branch = wt.branch
        smart_add_tree(wt, (u".",))
        for path in paths:
            self.assertNotEqual(wt.path2id(path), None)

    def test_add_dot_from_subdir(self):
        """Test adding . from a subdir of the tree.""" 
        from bzrlib.add import smart_add
        paths = ("original/", "original/file1", "original/file2")
        self.build_tree(paths)
        wt = self.make_branch_and_tree('.')
        branch = wt.branch
        os.chdir("original")
        smart_add_tree(wt, (u".",))
        for path in paths:
            self.assertNotEqual(wt.path2id(path), None)

    def test_add_tree_from_above_tree(self):
        """Test adding a tree from above the tree.""" 
        from bzrlib.add import smart_add
        paths = ("original/", "original/file1", "original/file2")
        branch_paths = ("branch/", "branch/original/", "branch/original/file1",
                        "branch/original/file2")
        self.build_tree(branch_paths)
        wt = self.make_branch_and_tree('branch')
        branch = wt.branch
        smart_add_tree(wt, ("branch",))
        for path in paths:
            self.assertNotEqual(wt.path2id(path), None)

    def test_add_above_tree_preserves_tree(self):
        """Test nested trees are not affect by an add above them."""
        from bzrlib.add import smart_add
        paths = ("original/", "original/file1", "original/file2")
        child_paths = ("path",)
        full_child_paths = ("original/child", "original/child/path")
        build_paths = ("original/", "original/file1", "original/file2", 
                       "original/child/", "original/child/path")
        
        self.build_tree(build_paths)
        wt = self.make_branch_and_tree('.')
        branch = wt.branch
        child_tree = self.make_branch_and_tree('original/child')
        smart_add_tree(wt, (".",))
        for path in paths:
            self.assertNotEqual((path, wt.path2id(path)),
                                (path, None))
        for path in full_child_paths:
            self.assertEqual((path, wt.path2id(path)),
                             (path, None))
        for path in child_paths:
            self.assertEqual(child_tree.path2id(path), None)

    def test_add_paths(self):
        """Test smart-adding a list of paths."""
        from bzrlib.add import smart_add
        paths = ("file1", "file2")
        self.build_tree(paths)
        wt = self.make_branch_and_tree('.')
        smart_add_tree(wt, paths)
        for path in paths:
            self.assertNotEqual(wt.path2id(path), None)
    
    def test_add_ignored_nested_paths(self):
        """Test smart-adding a list of paths which includes ignored ones."""
        wt = self.make_branch_and_tree('.')
        tree_shape = ("adir/", "adir/CVS/", "adir/CVS/afile", "adir/CVS/afile2")
        add_paths = ("adir/CVS", "adir/CVS/afile", "adir")
        expected_paths = ("adir", "adir/CVS", "adir/CVS/afile", "adir/CVS/afile2")
        self.build_tree(tree_shape)
        smart_add_tree(wt, add_paths)
        for path in expected_paths:
            self.assertNotEqual(wt.path2id(path), None, "No id added for %s" % path)

    def test_save_false(self):
        """Test smart-adding a path with save set to false."""
        wt = self.make_branch_and_tree('.')
        self.build_tree(['file'])
        smart_add_tree(wt, ['file'], save=False)
        self.assertNotEqual(wt.path2id('file'), None, "No id added for 'file'")
        wt.read_working_inventory()
        self.assertEqual(wt.path2id('file'), None)

    def test_add_dry_run(self):
        """Test a dry run add, make sure nothing is added."""
        from bzrlib.commands import run_bzr
        eq = self.assertEqual
        wt = self.make_branch_and_tree('.')
        branch = wt.branch
        self.build_tree(['inertiatic/', 'inertiatic/esp'])
        eq(list(wt.unknowns()), ['inertiatic'])
        self.capture('add --dry-run .')
        eq(list(wt.unknowns()), ['inertiatic'])

    def test_add_non_existant(self):
        """Test smart-adding a file that does not exist."""
        from bzrlib.add import smart_add
        wt = self.make_branch_and_tree('.')
        branch = wt.branch
        self.assertRaises(NoSuchFile, smart_add_tree, wt, 'non-existant-file')

    def test_returns_and_ignores(self):
        """Correctly returns added/ignored files"""
        from bzrlib.commands import run_bzr
        wt = self.make_branch_and_tree('.')
        branch = wt.branch
        # no files should be ignored by default, so we need to create
        # an ignore rule - we create one for the pyc files, which means
        # CVS should not be ignored.
        self.build_tree(['inertiatic/', 'inertiatic/esp', 'inertiatic/CVS', 
                        'inertiatic/foo.pyc'])
        self.build_tree_contents([('.bzrignore', '*.py[oc]\n')])
        added, ignored = smart_add_tree(wt, u'.')
        self.assertSubset(('inertiatic', 'inertiatic/esp', 'inertiatic/CVS'),
                          added)
        self.assertSubset(('*.py[oc]',), ignored)
        self.assertSubset(('inertiatic/foo.pyc',), ignored['*.py[oc]'])


class TestSmartAddTree(TestCaseWithTransport):
    """Test smart adds with a specified branch."""

    def test_add_dot_from_root(self):
        """Test adding . from the root of the tree.""" 
        paths = ("original/", "original/file1", "original/file2")
        self.build_tree(paths)
        wt = self.make_branch_and_tree('.')
        branch = wt.branch
        smart_add_tree(wt, (u".",))
        for path in paths:
            self.assertNotEqual(wt.path2id(path), None)

    def test_add_dot_from_subdir(self):
        """Test adding . from a subdir of the tree.""" 
        from bzrlib.add import smart_add_tree
        paths = ("original/", "original/file1", "original/file2")
        self.build_tree(paths)
        wt = self.make_branch_and_tree('.')
        branch = wt.branch
        os.chdir("original")
        smart_add_tree(wt, (u".",))
        for path in paths:
            self.assertNotEqual(wt.path2id(path), None)

    def test_add_tree_from_above_tree(self):
        """Test adding a tree from above the tree.""" 
        from bzrlib.add import smart_add_tree
        paths = ("original/", "original/file1", "original/file2")
        branch_paths = ("branch/", "branch/original/", "branch/original/file1",
                        "branch/original/file2")
        self.build_tree(branch_paths)
        tree = self.make_branch_and_tree('branch')
        branch = tree.branch
        smart_add_tree(tree, ("branch",))
        for path in paths:
            self.assertNotEqual(tree.path2id(path), None)

    def test_add_above_tree_preserves_tree(self):
        """Test nested trees are not affect by an add above them."""
        from bzrlib.add import smart_add_tree
        paths = ("original/", "original/file1", "original/file2")
        child_paths = ("path")
        full_child_paths = ("original/child", "original/child/path")
        build_paths = ("original/", "original/file1", "original/file2", 
                       "original/child/", "original/child/path")
        self.build_tree(build_paths)
        tree = self.make_branch_and_tree('.')
        branch = tree.branch
        child_tree = self.make_branch_and_tree("original/child")
        smart_add_tree(tree, (u".",))
        for path in paths:
            self.assertNotEqual((path, tree.path2id(path)),
                                (path, None))
        for path in full_child_paths:
            self.assertEqual((path, tree.path2id(path)),
                             (path, None))
        for path in child_paths:
            self.assertEqual(child_tree.path2id(path), None)

    def test_add_paths(self):
        """Test smart-adding a list of paths."""
        from bzrlib.add import smart_add_tree
        paths = ("file1", "file2")
        self.build_tree(paths)
        wt = self.make_branch_and_tree('.')
        branch = wt.branch
        smart_add_tree(wt, paths)
        for path in paths:
            self.assertNotEqual(wt.path2id(path), None)


class TestAddActions(TestCase):

    def test_quiet(self):
        self.run_action("")

    def test__print(self):
        self.run_action("added path\n")

    def run_action(self, output):
        from bzrlib.add import AddAction, FastPath
        from cStringIO import StringIO
        inv = Inventory()
        stdout = StringIO()
        action = AddAction(to_file=stdout, should_print=bool(output))

        self.apply_redirected(None, stdout, None, action, inv, None, FastPath('path'), 'file')
        self.assertEqual(stdout.getvalue(), output)
