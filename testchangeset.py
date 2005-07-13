
import bzrlib
import unittest
from StringIO import StringIO

from bzrlib.selftest import InTempDir

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

class CSetTester(InTempDir):

    def get_valid_cset(self, base_rev_id, rev_id):
        """Create a changeset from base_rev_id -> rev_id in built-in branch.
        Make sure that the text generated is valid, and that it
        can be applied against the base, and generate the same information.
        
        :return: The in-memory changeset
        """
        from cStringIO import StringIO
        from gen_changeset import show_changeset
        from read_changeset import read_changeset

        cset_txt = StringIO()
        show_changeset(self.b1, base_rev_id, self.b1, rev_id, to_file=cset_txt)
        cset_txt.seek(0)
        self.assertEqual(cset_txt.readline(), '# Bazaar-NG changeset v0.0.5\n')
        self.assertEqual(cset_txt.readline(), '# \n')

        rev = self.b1.get_revision(rev_id)
        self.assertEqual(cset_txt.readline(), '# committer: %s\n' % rev.committer)

        cset_txt.seek(0)
        # This should also validate the generate changeset
        cset = read_changeset(cset_txt, self.b1)
        info, tree, inv = cset
        for cset_rev in info.real_revisions:
            # These really should have already been checked in read_changeset
            # since it computes the sha1 hash for the revision, which
            # only will match if everything is okay, but lets be
            # explicit about it
            branch_rev = self.b1.get_revision(cset_rev.revision_id)
            for a in ('inventory_id', 'inventory_sha1', 'revision_id',
                    'timestamp', 'timezone', 'message', 'committer'):
                self.assertEqual(getattr(branch_rev, a), getattr(cset_rev, a))
            self.assertEqual(len(branch_rev.parents), len(cset_rev.parents))
            for b_par, c_par in zip(branch_rev.parents, cset_rev.parents):
                self.assertEqual(b_par.revision_id, c_par.revision_id)
                # Foolishly, pending-merges generates parents which
                # may not have revision entries
                if b_par.revision_sha1 is None:
                    if b_par.revision_id in self.b1.revision_store:
                        sha1 = self.b1.get_revision_sha1(b_par.revision_id)
                    else:
                        sha1 = None
                else:
                    sha1 = b_par.revision_sha1
                if sha1 is not None:
                    self.assertEqual(sha1, c_par.revision_sha1)

        self.valid_apply_changeset(base_rev_id, cset)

        return info, tree, inv

    def get_checkout(self, rev_id):
        """Get a new tree, with the specified revision in it.
        """
        from bzrlib.branch import find_branch
        import tempfile
        from bzrlib.merge import merge

        dirname = tempfile.mkdtemp(prefix='test-branch-', dir='.')
        to_branch = find_branch(dirname, init=True)
        # TODO: Once root ids are established, remove this if
        if hasattr(self.b1, 'get_root_id'):
            to_branch.set_root_id(self.b1.get_root_id())
        if rev_id is not None:
            # TODO Worry about making the root id of the branch
            # the same
            rh = self.b1.revision_history()
            self.assert_(rev_id in rh, 'Missing revision %s in base tree' % rev_id)
            revno = self.b1.revision_history().index(rev_id) + 1
            to_branch.update_revisions(self.b1, stop_revision=revno)
            merge((dirname, -1), (dirname, 0), this_dir=dirname,
                    check_clean=False, ignore_zero=True)
        return to_branch

    def valid_apply_changeset(self, base_rev_id, cset):
        """Get the base revision, apply the changes, and make
        sure everything matches the builtin branch.
        """
        from apply_changeset import _apply_cset

        to_branch = self.get_checkout(base_rev_id)
        _apply_cset(to_branch, cset)

        info = cset[0]
        for rev in info.real_revisions:
            self.assert_(rev.revision_id in to_branch.revision_store,
                'Missing revision {%s} after applying changeset' 
                % rev.revision_id)

        rev = info.real_revisions[-1]
        base_tree = self.b1.revision_tree(rev.revision_id)
        to_tree = to_branch.revision_tree(rev.revision_id)
        
        # TODO: make sure the target tree is identical to base tree

    def test_add(self):
        from bzrlib.branch import find_branch
        import common

        import os, sys
        pjoin = os.path.join

        os.mkdir('b1')
        self.b1 = find_branch('b1', init=True)

        open(pjoin('b1/one'), 'wb').write('one\n')
        self.b1.add('one')
        self.b1.commit('add one', rev_id='a@cset-0-1')

        cset = self.get_valid_cset(None, 'a@cset-0-1')

        # Make sure we can handle files with spaces, tabs, other
        # bogus characters
        files = ['with space.txt',
                'dir/',
                'dir/filein subdir.c',
                'dir/WithCaps.txt'
                ]
        if sys.platform not in ('win32', 'cygwin'):
            # Tabs are not valid in filenames on windows
            files.append('with\ttab.txt')
        self.build_tree(['b1/' + f for f in files])
        self.b1.add(files)
        self.b1.commit('add whitespace', rev_id='a@cset-0-2')

        cset = self.get_valid_cset('a@cset-0-1', 'a@cset-0-2')
        # Check a rollup changeset
        cset = self.get_valid_cset(None, 'a@cset-0-2')
        
TEST_CLASSES = [
    CTreeTester,
    CSetTester
]

