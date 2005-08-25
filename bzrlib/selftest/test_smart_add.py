import os
import unittest

from bzrlib.selftest import FunctionalTestCase, TestCase
from bzrlib.branch import Branch
from bzrlib.errors import NotBranchError, NotVersionedError

class TestSmartAdd(FunctionalTestCase):

    def test_add_dot_from_root(self):
        """Test adding . from the root of the tree.""" 
        from bzrlib.add import smart_add
        paths = ("original/", "original/file1", "original/file2")
        self.build_tree(paths)
        branch = Branch(".", init=True)
        smart_add((".",), False, True)
        for path in paths:
            self.assertNotEqual(branch.inventory.path2id(path), None)

    def test_add_dot_from_subdir(self):
        """Test adding . from a subdir of the tree.""" 
        from bzrlib.add import smart_add
        paths = ("original/", "original/file1", "original/file2")
        self.build_tree(paths)
        branch = Branch(".", init=True)
        os.chdir("original")
        smart_add((".",), False, True)
        for path in paths:
            self.assertNotEqual(branch.inventory.path2id(path), None)

    def test_add_tree_from_above_tree(self):
        """Test adding a tree from above the tree.""" 
        from bzrlib.add import smart_add
        paths = ("original/", "original/file1", "original/file2")
        branch_paths = ("branch/", "branch/original/", "branch/original/file1", "branch/original/file2")
        self.build_tree(branch_paths)
        branch = Branch("branch", init=True)
        smart_add(("branch",), False, True)
        for path in paths:
            self.assertNotEqual(branch.inventory.path2id(path), None)

    def test_add_above_tree_preserves_tree(self):
        """Test nested trees are not affect by an add above them."""
        from bzrlib.add import smart_add
        paths = ("original/", "original/file1", "original/file2")
        child_paths = ("path")
        full_child_paths = ("original/child", "original/child/path")
        build_paths = ("original/", "original/file1", "original/file2", 
                       "original/child/", "original/child/path")
        self.build_tree(build_paths)
        branch = Branch(".", init=True)
        child_branch = Branch("original/child", init=True)
        smart_add((".",), False, True)
        for path in paths:
            self.assertNotEqual((path, branch.inventory.path2id(path)),
                                (path, None))
        for path in full_child_paths:
            self.assertEqual((path, branch.inventory.path2id(path)),
                             (path, None))
        for path in child_paths:
            self.assertEqual(child_branch.inventory.path2id(path), None)
