import os
import unittest

from bzrlib.tests import TestCaseInTempDir, TestCase
from bzrlib.branch import Branch
from bzrlib.errors import NotBranchError, NoSuchFile
from bzrlib.inventory import InventoryFile, Inventory
from bzrlib.workingtree import WorkingTree
from bzrlib.add import smart_add

class TestSmartAdd(TestCaseInTempDir):

    def test_add_dot_from_root(self):
        """Test adding . from the root of the tree.""" 
        from bzrlib.add import smart_add
        paths = ("original/", "original/file1", "original/file2")
        self.build_tree(paths)
        branch = Branch.initialize(u".")
        smart_add((u".",))
        for path in paths:
            self.assertNotEqual(branch.working_tree().path2id(path), None)

    def test_add_dot_from_subdir(self):
        """Test adding . from a subdir of the tree.""" 
        from bzrlib.add import smart_add
        paths = ("original/", "original/file1", "original/file2")
        self.build_tree(paths)
        branch = Branch.initialize(u".")
        os.chdir("original")
        smart_add((u".",))
        for path in paths:
            self.assertNotEqual(branch.working_tree().path2id(path), None)

    def test_add_tree_from_above_tree(self):
        """Test adding a tree from above the tree.""" 
        from bzrlib.add import smart_add
        paths = ("original/", "original/file1", "original/file2")
        branch_paths = ("branch/", "branch/original/", "branch/original/file1",
                        "branch/original/file2")
        self.build_tree(branch_paths)
        branch = Branch.initialize("branch")
        smart_add(("branch",))
        for path in paths:
            self.assertNotEqual(branch.working_tree().path2id(path), None)

    def test_add_above_tree_preserves_tree(self):
        """Test nested trees are not affect by an add above them."""
        from bzrlib.add import smart_add
        paths = ("original/", "original/file1", "original/file2")
        child_paths = ("path",)
        full_child_paths = ("original/child", "original/child/path")
        build_paths = ("original/", "original/file1", "original/file2", 
                       "original/child/", "original/child/path")
        
        self.build_tree(build_paths)
        branch = Branch.initialize(u".")
        child_branch = Branch.initialize("original/child")
        smart_add((u".",))
        for path in paths:
            self.assertNotEqual((path, branch.working_tree().path2id(path)),
                                (path, None))
        for path in full_child_paths:
            self.assertEqual((path, branch.working_tree().path2id(path)),
                             (path, None))
        for path in child_paths:
            self.assertEqual(child_branch.working_tree().path2id(path), None)

    def test_add_paths(self):
        """Test smart-adding a list of paths."""
        from bzrlib.add import smart_add
        paths = ("file1", "file2")
        self.build_tree(paths)
        branch = Branch.initialize(u".")
        smart_add(paths)
        for path in paths:
            self.assertNotEqual(branch.working_tree().path2id(path), None)

    def test_add_dry_run(self):
        """Test a dry run add, make sure nothing is added."""
        from bzrlib.commands import run_bzr
        eq = self.assertEqual
        b = Branch.initialize(u'.')
        t = b.working_tree()
        self.build_tree(['inertiatic/', 'inertiatic/esp'])
        eq(list(t.unknowns()), ['inertiatic'])
        self.capture('add --dry-run .')
        eq(list(t.unknowns()), ['inertiatic'])

    def test_add_non_existant(self):
        """Test smart-adding a file that does not exist."""
        from bzrlib.add import smart_add
        branch = Branch.initialize(u".")
        self.assertRaises(NoSuchFile, smart_add, 'non-existant-file')

    def test_returns(self):
        """Correctly returns added/ignored files"""
        from bzrlib.commands import run_bzr
        b = Branch.initialize(u'.')
        t = b.working_tree()
        self.build_tree(['inertiatic/', 'inertiatic/esp', 'inertiatic/CVS', 
                        'inertiatic/foo.pyc'])
        added, ignored = smart_add(u'.')
        self.AssertSubset(('inertiatic', 'inertiatic/esp'), added)
        self.AssertSubset(('CVS', '*.py[oc]'), ignored)
        self.AssertSubset(('inertiatic/CVS',), ignored['CVS'])
        self.AssertSubset(('inertiatic/foo.pyc',), ignored['*.py[oc]'])


class TestSmartAddBranch(TestCaseInTempDir):
    """Test smart adds with a specified branch."""

    def test_add_dot_from_root(self):
        """Test adding . from the root of the tree.""" 
        from bzrlib.add import smart_add_tree
        paths = ("original/", "original/file1", "original/file2")
        self.build_tree(paths)
        Branch.initialize(u".")
        tree = WorkingTree()
        smart_add_tree(tree, (u".",))
        for path in paths:
            self.assertNotEqual(tree.path2id(path), None)

    def test_add_dot_from_subdir(self):
        """Test adding . from a subdir of the tree.""" 
        from bzrlib.add import smart_add_tree
        paths = ("original/", "original/file1", "original/file2")
        self.build_tree(paths)
        Branch.initialize(u".")
        tree = WorkingTree()
        os.chdir("original")
        smart_add_tree(tree, (u".",))
        for path in paths:
            self.assertNotEqual(tree.path2id(path), None)

    def test_add_tree_from_above_tree(self):
        """Test adding a tree from above the tree.""" 
        from bzrlib.add import smart_add_tree
        paths = ("original/", "original/file1", "original/file2")
        branch_paths = ("branch/", "branch/original/", "branch/original/file1",
                        "branch/original/file2")
        self.build_tree(branch_paths)
        Branch.initialize("branch")
        tree = WorkingTree("branch")
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
        Branch.initialize(u".")
        tree = WorkingTree()
        child_branch = Branch.initialize("original/child")
        smart_add_tree(tree, (u".",))
        for path in paths:
            self.assertNotEqual((path, tree.path2id(path)),
                                (path, None))
        for path in full_child_paths:
            self.assertEqual((path, tree.path2id(path)),
                             (path, None))
        for path in child_paths:
            self.assertEqual(child_branch.working_tree().path2id(path), None)

    def test_add_paths(self):
        """Test smart-adding a list of paths."""
        from bzrlib.add import smart_add_tree
        paths = ("file1", "file2")
        self.build_tree(paths)
        Branch.initialize(u".")
        tree = WorkingTree()
        smart_add_tree(tree, paths)
        for path in paths:
            self.assertNotEqual(tree.path2id(path), None)


class TestAddActions(TestCaseInTempDir):

    def test_null(self):
        from bzrlib.add import add_action_null
        self.run_action(add_action_null, "", False)

    def test_add(self):
        self.entry = InventoryFile("id", "name", None)
        from bzrlib.add import add_action_add
        self.run_action(add_action_add, "", True)

    def test_add_and_print(self):
        from bzrlib.add import add_action_add_and_print
        self.run_action(add_action_add_and_print, "added path\n", True)

    def test_print(self):
        from bzrlib.add import add_action_print
        self.run_action(add_action_print, "added path\n", False)

    def run_action(self, action, output, should_add):
        from StringIO import StringIO
        inv = Inventory()
        stdout = StringIO()

        self.apply_redirected(None, stdout, None, action, inv, 'path', 'file')
        self.assertEqual(stdout.getvalue(), output)

        if should_add:
            self.assertNotEqual(inv.path2id('path'), None)
        else:
            self.assertEqual(inv.path2id('path'), None)
