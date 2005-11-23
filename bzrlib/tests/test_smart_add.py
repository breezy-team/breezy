import os
import unittest

from bzrlib.tests import TestCaseInTempDir, TestCase
from bzrlib.branch import Branch
from bzrlib.errors import NotBranchError
from bzrlib.inventory import InventoryFile

class TestSmartAdd(TestCaseInTempDir):

    def test_add_dot_from_root(self):
        """Test adding . from the root of the tree.""" 
        from bzrlib.add import smart_add
        paths = ("original/", "original/file1", "original/file2")
        self.build_tree(paths)
        branch = Branch.initialize(".")
        smart_add((".",), recurse=True)
        for path in paths:
            self.assertNotEqual(branch.working_tree().path2id(path), None)

    def test_add_dot_from_subdir(self):
        """Test adding . from a subdir of the tree.""" 
        from bzrlib.add import smart_add
        paths = ("original/", "original/file1", "original/file2")
        self.build_tree(paths)
        branch = Branch.initialize(".")
        os.chdir("original")
        smart_add((".",), recurse=True)
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
        from bzrlib.add import smart_add, add_reporter_null
        
        paths = ("original/", "original/file1", "original/file2")
        child_paths = ("path",)
        full_child_paths = ("original/child", "original/child/path")
        build_paths = ("original/", "original/file1", "original/file2", 
                       "original/child/", "original/child/path")
        
        self.build_tree(build_paths)
        branch = Branch.initialize(".")
        child_branch = Branch.initialize("original/child")
        smart_add((".",), True, add_reporter_null)
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
        branch = Branch.initialize(".")
        smart_add(paths)
        for path in paths:
            self.assertNotEqual(branch.working_tree().path2id(path), None)
            
class TestSmartAddBranch(TestCaseInTempDir):
    """Test smart adds with a specified branch."""

    def test_add_dot_from_root(self):
        """Test adding . from the root of the tree.""" 
        from bzrlib.add import smart_add_branch
        paths = ("original/", "original/file1", "original/file2")
        self.build_tree(paths)
        branch = Branch.initialize(".")
        smart_add_branch(branch, (".",))
        for path in paths:
            self.assertNotEqual(branch.working_tree().path2id(path), None)

    def test_add_dot_from_subdir(self):
        """Test adding . from a subdir of the tree.""" 
        from bzrlib.add import smart_add_branch
        paths = ("original/", "original/file1", "original/file2")
        self.build_tree(paths)
        branch = Branch.initialize(".")
        os.chdir("original")
        smart_add_branch(branch, (".",))
        for path in paths:
            self.assertNotEqual(branch.working_tree().path2id(path), None)

    def test_add_tree_from_above_tree(self):
        """Test adding a tree from above the tree.""" 
        from bzrlib.add import smart_add_branch
        paths = ("original/", "original/file1", "original/file2")
        branch_paths = ("branch/", "branch/original/", "branch/original/file1",
                        "branch/original/file2")
        self.build_tree(branch_paths)
        branch = Branch.initialize("branch")
        smart_add_branch(branch, ("branch",))
        for path in paths:
            self.assertNotEqual(branch.working_tree().path2id(path), None)

    def test_add_above_tree_preserves_tree(self):
        """Test nested trees are not affect by an add above them."""
        from bzrlib.add import smart_add_branch
        paths = ("original/", "original/file1", "original/file2")
        child_paths = ("path")
        full_child_paths = ("original/child", "original/child/path")
        build_paths = ("original/", "original/file1", "original/file2", 
                       "original/child/", "original/child/path")
        self.build_tree(build_paths)
        branch = Branch.initialize(".")
        child_branch = Branch.initialize("original/child")
        smart_add_branch(branch, (".",))
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
        from bzrlib.add import smart_add_branch
        paths = ("file1", "file2")
        self.build_tree(paths)
        branch = Branch.initialize(".")
        smart_add_branch(branch, paths)
        for path in paths:
            self.assertNotEqual(branch.working_tree().path2id(path), None)

class TestAddCallbacks(TestCaseInTempDir):

    def setUp(self):
        super(TestAddCallbacks, self).setUp()
        self.entry = InventoryFile("id", "name", None)

    def test_null_callback(self):
        from bzrlib.add import add_reporter_null
        add_reporter_null('path', 'file', self.entry)

    def test_print_callback(self):
        from bzrlib.add import add_reporter_print
        from StringIO import StringIO
        stdout = StringIO()
        self.apply_redirected(None, stdout, None, add_reporter_print,
                              'path', 'file', self.entry)
        self.assertEqual(stdout.getvalue(), "added path\n")
