
import bzrlib
import unittest
from StringIO import StringIO

from bzrlib.diff import internal_diff
from read_changeset import ChangesetTree

class MockTree(object):
    def __init__(self):
        object.__init__(self)
        self.paths = {}
        self.ids = {}
        self.contents = {}

    def __iter__(self):
        return self.paths.iterkeys()

    def add_dir(self, file_id, path):
        self.paths[file_id] = path
        self.ids[path] = file_id
    
    def add_file(self, file_id, path, contents):
        self.add_dir(file_id, path)
        self.contents[file_id] = contents

    def path2id(self, path):
        return self.ids.get(path)

    def id2path(self, file_id):
        return self.paths.get(file_id)

    def has_id(self, file_id):
        return self.id2path(file_id) is not None

    def get_file(self, file_id):
        result = StringIO()
        result.write(self.contents[file_id])
        result.seek(0,0)
        return result

class CTreeTester(unittest.TestCase):
    """A simple unittest tester for the ChangesetTree class."""

    def make_tree_1(self):
        mtree = MockTree()
        mtree.add_dir("a", "grandparent")
        mtree.add_dir("b", "grandparent/parent")
        mtree.add_file("c", "grandparent/parent/file", "Hello\n")
        mtree.add_dir("d", "grandparent/alt_parent")
        return ChangesetTree(mtree), mtree
        
    def test_renames(self):
        """Ensure that file renames have the proper effect on children"""
        ctree = self.make_tree_1()[0]
        self.assertEqual(ctree.old_path("grandparent"), "grandparent")
        self.assertEqual(ctree.old_path("grandparent/parent"), "grandparent/parent")
        self.assertEqual(ctree.old_path("grandparent/parent/file"),
            "grandparent/parent/file")

        self.assertEqual(ctree.id2path("a"), "grandparent")
        self.assertEqual(ctree.id2path("b"), "grandparent/parent")
        self.assertEqual(ctree.id2path("c"), "grandparent/parent/file")

        self.assertEqual(ctree.path2id("grandparent"), "a")
        self.assertEqual(ctree.path2id("grandparent/parent"), "b")
        self.assertEqual(ctree.path2id("grandparent/parent/file"), "c")

        assert ctree.path2id("grandparent2") is None
        assert ctree.path2id("grandparent2/parent") is None
        assert ctree.path2id("grandparent2/parent/file") is None

        ctree.note_rename("grandparent", "grandparent2")
        assert ctree.old_path("grandparent") is None
        assert ctree.old_path("grandparent/parent") is None
        assert ctree.old_path("grandparent/parent/file") is None

        self.assertEqual(ctree.id2path("a"), "grandparent2")
        self.assertEqual(ctree.id2path("b"), "grandparent2/parent")
        self.assertEqual(ctree.id2path("c"), "grandparent2/parent/file")

        self.assertEqual(ctree.path2id("grandparent2"), "a")
        self.assertEqual(ctree.path2id("grandparent2/parent"), "b")
        self.assertEqual(ctree.path2id("grandparent2/parent/file"), "c")

        assert ctree.path2id("grandparent") is None
        assert ctree.path2id("grandparent/parent") is None
        assert ctree.path2id("grandparent/parent/file") is None

        ctree.note_rename("grandparent/parent", "grandparent2/parent2")
        self.assertEqual(ctree.id2path("a"), "grandparent2")
        self.assertEqual(ctree.id2path("b"), "grandparent2/parent2")
        self.assertEqual(ctree.id2path("c"), "grandparent2/parent2/file")

        self.assertEqual(ctree.path2id("grandparent2"), "a")
        self.assertEqual(ctree.path2id("grandparent2/parent2"), "b")
        self.assertEqual(ctree.path2id("grandparent2/parent2/file"), "c")

        assert ctree.path2id("grandparent2/parent") is None
        assert ctree.path2id("grandparent2/parent/file") is None

        ctree.note_rename("grandparent/parent/file", 
                          "grandparent2/parent2/file2")
        self.assertEqual(ctree.id2path("a"), "grandparent2")
        self.assertEqual(ctree.id2path("b"), "grandparent2/parent2")
        self.assertEqual(ctree.id2path("c"), "grandparent2/parent2/file2")

        self.assertEqual(ctree.path2id("grandparent2"), "a")
        self.assertEqual(ctree.path2id("grandparent2/parent2"), "b")
        self.assertEqual(ctree.path2id("grandparent2/parent2/file2"), "c")

        assert ctree.path2id("grandparent2/parent2/file") is None

    def test_moves(self):
        """Ensure that file moves have the proper effect on children"""
        ctree = self.make_tree_1()[0]
        ctree.note_rename("grandparent/parent/file", 
                          "grandparent/alt_parent/file")
        self.assertEqual(ctree.id2path("c"), "grandparent/alt_parent/file")
        self.assertEqual(ctree.path2id("grandparent/alt_parent/file"), "c")
        assert ctree.path2id("grandparent/parent/file") is None

    def unified_diff(self, old, new):
        out = StringIO()
        internal_diff("old", old, "new", new, out)
        out.seek(0,0)
        return out.read()

    def make_tree_2(self):
        ctree = self.make_tree_1()[0]
        ctree.note_rename("grandparent/parent/file", 
                          "grandparent/alt_parent/file")
        assert ctree.id2path("e") is None
        assert ctree.path2id("grandparent/parent/file") is None
        ctree.note_id("e", "grandparent/parent/file")
        return ctree

    def test_adds(self):
        """File/inventory adds"""
        ctree = self.make_tree_2()
        add_patch = self.unified_diff([], ["Extra cheese\n"])
        ctree.note_patch("grandparent/parent/file", add_patch)
        self.adds_test(ctree)

    def adds_test(self, ctree):
        self.assertEqual(ctree.id2path("e"), "grandparent/parent/file")
        self.assertEqual(ctree.path2id("grandparent/parent/file"), "e")
        self.assertEqual(ctree.get_file("e").read(), "Extra cheese\n")

    def test_adds2(self):
        """File/inventory adds, with patch-compatibile renames"""
        ctree = self.make_tree_2()
        ctree.contents_by_id = False
        add_patch = self.unified_diff(["Hello\n"], ["Extra cheese\n"])
        ctree.note_patch("grandparent/parent/file", add_patch)
        self.adds_test(ctree)

    def make_tree_3(self):
        ctree, mtree = self.make_tree_1()
        mtree.add_file("e", "grandparent/parent/topping", "Anchovies\n")
        ctree.note_rename("grandparent/parent/file", 
                          "grandparent/alt_parent/file")
        ctree.note_rename("grandparent/parent/topping", 
                          "grandparent/alt_parent/stopping")
        return ctree

    def get_file_test(self, ctree):
        self.assertEqual(ctree.get_file("e").read(), "Lemon\n")
        self.assertEqual(ctree.get_file("c").read(), "Hello\n")

    def test_get_file(self):
        """Get file contents"""
        ctree = self.make_tree_3()
        mod_patch = self.unified_diff(["Anchovies\n"], ["Lemon\n"])
        ctree.note_patch("grandparent/alt_parent/stopping", mod_patch)
        self.get_file_test(ctree)

    def test_get_file2(self):
        """Get file contents, with patch-compatibile renames"""
        ctree = self.make_tree_3()
        ctree.contents_by_id = False
        mod_patch = self.unified_diff([], ["Lemon\n"])
        ctree.note_patch("grandparent/alt_parent/stopping", mod_patch)
        mod_patch = self.unified_diff([], ["Hello\n"])
        ctree.note_patch("grandparent/alt_parent/file", mod_patch)
        self.get_file_test(ctree)

    def test_delete(self):
        "Deletion by changeset"
        ctree = self.make_tree_1()[0]
        self.assertEqual(ctree.get_file("c").read(), "Hello\n")
        ctree.note_deletion("grandparent/parent/file")
        assert ctree.id2path("c") is None
        assert ctree.path2id("grandparent/parent/file") is None

    def sorted_ids(self, tree):
        ids = list(tree)
        ids.sort()
        return ids

    def test_iteration(self):
        """Ensure that iteration through ids works properly"""
        ctree = self.make_tree_1()[0]
        self.assertEqual(self.sorted_ids(ctree), ['a', 'b', 'c', 'd'])
        ctree.note_deletion("grandparent/parent/file")
        ctree.note_id("e", "grandparent/alt_parent/fool")
        self.assertEqual(self.sorted_ids(ctree), ['a', 'b', 'd', 'e'])

def test():
    patchesTestSuite = unittest.makeSuite(CTreeTester,'test_')
    runner = unittest.TextTestRunner()
    runner.run(patchesTestSuite)


