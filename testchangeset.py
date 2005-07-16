
import bzrlib
import unittest
from StringIO import StringIO

from bzrlib.selftest import InTempDir

from bzrlib.diff import internal_diff
from read_changeset import ChangesetTree

class MockTree(object):
    def __init__(self):
        from bzrlib.inventory import RootEntry, ROOT_ID
        object.__init__(self)
        self.paths = {ROOT_ID: ""}
        self.ids = {"": ROOT_ID}
        self.contents = {}
        self.root = RootEntry(ROOT_ID)

    inventory = property(lambda x:x)

    def __iter__(self):
        return self.paths.iterkeys()

    def __getitem__(self, file_id):
        if file_id == self.root.file_id:
            return self.root
        else:
            return self.make_entry(file_id, self.paths[file_id])

    def parent_id(self, file_id):
        from os.path import dirname
        parent_dir = dirname(self.paths[file_id])
        if parent_dir == "":
            return None
        return self.ids[parent_dir]

    def iter_entries(self):
        for path, file_id in self.ids.iteritems():
            yield path, self[file_id]

    def get_file_kind(self, file_id):
        if file_id in self.contents:
            kind = 'file'
        else:
            kind = 'directory'
        return kind

    def make_entry(self, file_id, path):
        from os.path import basename
        from bzrlib.inventory import InventoryEntry
        name = basename(path)
        kind = self.get_file_kind(file_id)
        parent_id = self.parent_id(file_id)
        text_sha_1, text_size = self.contents_stats(file_id)
        ie = InventoryEntry(file_id, name, kind, parent_id)
        ie.text_sha_1 = text_sha_1
        ie.text_size = text_size
        return ie

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

    def contents_stats(self, file_id):
        from bzrlib.osutils import sha_file
        if file_id not in self.contents:
            return None, None
        text_sha1 = sha_file(self.get_file(file_id))
        return text_sha1, len(self.contents[file_id])


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
        ctree.note_id("e", "grandparent/alt_parent/fool", kind="directory")
        self.assertEqual(self.sorted_ids(ctree), ['a', 'b', 'd', 'e'])

class CSetTester(InTempDir):

    def get_valid_cset(self, base_rev_id, rev_id, auto_commit=False):
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

        open(',,cset', 'wb').write(cset_txt.getvalue())
        cset_txt.seek(0)
        # This should also validate the generate changeset
        cset = read_changeset(cset_txt, self.b1)
        info, tree = cset
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

        self.valid_apply_changeset(base_rev_id, cset, auto_commit=auto_commit)

        return cset

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

    def valid_apply_changeset(self, base_rev_id, cset, auto_commit=False):
        """Get the base revision, apply the changes, and make
        sure everything matches the builtin branch.
        """
        from apply_changeset import _apply_cset

        to_branch = self.get_checkout(base_rev_id)
        auto_committed = _apply_cset(to_branch, cset, auto_commit=auto_commit)

        info = cset[0]
        for rev in info.real_revisions:
            self.assert_(rev.revision_id in to_branch.revision_store,
                'Missing revision {%s} after applying changeset' 
                % rev.revision_id)

        self.assert_(info.target in to_branch.inventory_store)
        for file_id, ie in to_branch.get_inventory(info.target).iter_entries():
            if hasattr(ie, 'text_id') and ie.text_id is not None:
                self.assert_(ie.text_id in to_branch.text_store)


        # Don't call get_valid_cset(auto_commit=True) unless you
        # expect the auto-commit to succeed.
        self.assertEqual(auto_commit, auto_committed)

        if auto_committed:
            # We might also check that all revisions are in the
            # history for some changeset applications which
            # merge multiple revisions.
            self.assertEqual(to_branch.last_patch(), info.target)
        else:
            self.assert_(info.target in to_branch.pending_merges())


        rev = info.real_revisions[-1]
        base_tree = self.b1.revision_tree(rev.revision_id)
        to_tree = to_branch.revision_tree(rev.revision_id)
        
        # TODO: make sure the target tree is identical to base tree
        #       we might also check the working tree.

        base_files = list(base_tree.list_files())
        to_files = list(to_tree.list_files())
        self.assertEqual(len(base_files), len(to_files))
        self.assertEqual(base_files, to_files)

        for path, status, kind, fileid in base_files:
            # Check that the meta information is the same
            self.assertEqual(base_tree.get_file_size(fileid),
                    to_tree.get_file_size(fileid))
            self.assertEqual(base_tree.get_file_sha1(fileid),
                    to_tree.get_file_sha1(fileid))
            # Check that the contents are the same
            # This is pretty expensive
            # self.assertEqual(base_tree.get_file(fileid).read(),
            #         to_tree.get_file(fileid).read())

    def runTest(self):
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
        self.build_tree([
                'b1/with space.txt'
                , 'b1/dir/'
                , 'b1/dir/filein subdir.c'
                , 'b1/dir/WithCaps.txt'
                , 'b1/sub/'
                , 'b1/sub/sub/'
                , 'b1/sub/sub/nonempty.txt'
                # Tabs are not valid in filenames on windows
                #'b1/with\ttab.txt'
                ])
        open('b1/sub/sub/emptyfile.txt', 'wb').close()
        self.b1.add([
                'with space.txt'
                , 'dir'
                , 'dir/filein subdir.c'
                , 'dir/WithCaps.txt'
                , 'sub'
                , 'sub/sub'
                , 'sub/sub/nonempty.txt'
                , 'sub/sub/emptyfile.txt'
                ])
        self.b1.commit('add whitespace', rev_id='a@cset-0-2')

        cset = self.get_valid_cset('a@cset-0-1', 'a@cset-0-2')
        cset = self.get_valid_cset('a@cset-0-1', 'a@cset-0-2', auto_commit=True)
        # Check a rollup changeset
        cset = self.get_valid_cset(None, 'a@cset-0-2')
        cset = self.get_valid_cset(None, 'a@cset-0-2', auto_commit=True)

        # Now delete entries
        self.b1.remove(['sub/sub/nonempty.txt'
                , 'sub/sub/emptyfile.txt'
                , 'sub/sub'])
        self.b1.commit('removed', rev_id='a@cset-0-3')
        
        cset = self.get_valid_cset('a@cset-0-2', 'a@cset-0-3')
        cset = self.get_valid_cset('a@cset-0-2', 'a@cset-0-3', auto_commit=True)
        # Check a rollup changeset
        cset = self.get_valid_cset(None, 'a@cset-0-3')
        cset = self.get_valid_cset(None, 'a@cset-0-3', auto_commit=True)


        # Now move the directory
        self.b1.rename_one('dir', 'sub/dir')
        self.b1.commit('rename dir', rev_id='a@cset-0-4')

        cset = self.get_valid_cset('a@cset-0-3', 'a@cset-0-4')
        # Check a rollup changeset
        cset = self.get_valid_cset(None, 'a@cset-0-4')
        cset = self.get_valid_cset(None, 'a@cset-0-4', auto_commit=True)
        cset = self.get_valid_cset('a@cset-0-1', 'a@cset-0-4', auto_commit=True)
        cset = self.get_valid_cset('a@cset-0-2', 'a@cset-0-4', auto_commit=True)
        cset = self.get_valid_cset('a@cset-0-3', 'a@cset-0-4', auto_commit=True)

TEST_CLASSES = [
    CTreeTester,
    CSetTester
]

