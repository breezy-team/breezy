# Copyright (C) 2010-2018 Jelmer Vernooij <jelmer@jelmer.uk>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Tests for bzr-git's object store."""

from __future__ import absolute_import

from dulwich.objects import (
    Blob,
    Tree,
    )

from ...branchbuilder import (
    BranchBuilder,
    )
from ...bzr.inventory import (
    InventoryDirectory,
    InventoryFile,
    )
from ...errors import (
    NoSuchRevision,
    )
from ...graph import (
    DictParentsProvider,
    Graph,
    )
from ...tests import (
    TestCase,
    TestCaseWithTransport,
    )

from ..cache import (
    DictGitShaMap,
    )
from ..object_store import (
    BazaarObjectStore,
    LRUTreeCache,
    directory_to_tree,
    _check_expected_sha,
    _find_missing_bzr_revids,
    _tree_to_objects,
    )


class ExpectedShaTests(TestCase):

    def setUp(self):
        super(ExpectedShaTests, self).setUp()
        self.obj = Blob()
        self.obj.data = b"foo"

    def test_none(self):
        _check_expected_sha(None, self.obj)

    def test_hex(self):
        _check_expected_sha(
            self.obj.sha().hexdigest().encode('ascii'), self.obj)
        self.assertRaises(AssertionError, _check_expected_sha,
                          b"0" * 40, self.obj)

    def test_binary(self):
        _check_expected_sha(self.obj.sha().digest(), self.obj)
        self.assertRaises(AssertionError, _check_expected_sha,
                          b"x" * 20, self.obj)


class FindMissingBzrRevidsTests(TestCase):

    def _find_missing(self, ancestry, want, have):
        return _find_missing_bzr_revids(
            Graph(DictParentsProvider(ancestry)),
            set(want), set(have))

    def test_simple(self):
        self.assertEqual(set(), self._find_missing({}, [], []))

    def test_up_to_date(self):
        self.assertEqual(set(),
                         self._find_missing({"a": ["b"]}, ["a"], ["a"]))

    def test_one_missing(self):
        self.assertEqual(set(["a"]),
                         self._find_missing({"a": ["b"]}, ["a"], ["b"]))

    def test_two_missing(self):
        self.assertEqual(set(["a", "b"]),
                         self._find_missing({"a": ["b"], "b": ["c"]}, ["a"], ["c"]))

    def test_two_missing_history(self):
        self.assertEqual(set(["a", "b"]),
                         self._find_missing({"a": ["b"], "b": ["c"], "c": ["d"]},
                                            ["a"], ["c"]))


class LRUTreeCacheTests(TestCaseWithTransport):

    def setUp(self):
        super(LRUTreeCacheTests, self).setUp()
        self.branch = self.make_branch(".")
        self.branch.lock_write()
        self.addCleanup(self.branch.unlock)
        self.cache = LRUTreeCache(self.branch.repository)

    def test_get_not_present(self):
        self.assertRaises(NoSuchRevision, self.cache.revision_tree,
                          "unknown")

    def test_revision_trees(self):
        self.assertRaises(NoSuchRevision, self.cache.revision_trees,
                          ["unknown", "la"])

    def test_iter_revision_trees(self):
        self.assertRaises(NoSuchRevision, self.cache.iter_revision_trees,
                          ["unknown", "la"])

    def test_get(self):
        bb = BranchBuilder(branch=self.branch)
        bb.start_series()
        revid = bb.build_snapshot(None,
                                  [('add', ('', None, 'directory', None)),
                                   ('add', ('foo', b'foo-id',
                                            'file', b'a\nb\nc\nd\ne\n')),
                                   ])
        bb.finish_series()
        tree = self.cache.revision_tree(revid)
        self.assertEqual(revid, tree.get_revision_id())


class BazaarObjectStoreTests(TestCaseWithTransport):

    def setUp(self):
        super(BazaarObjectStoreTests, self).setUp()
        self.branch = self.make_branch(".")
        self.branch.lock_write()
        self.addCleanup(self.branch.unlock)
        self.store = BazaarObjectStore(self.branch.repository)

    def test_get_blob(self):
        b = Blob()
        b.data = b'a\nb\nc\nd\ne\n'
        self.store.lock_read()
        self.addCleanup(self.store.unlock)
        self.assertRaises(KeyError, self.store.__getitem__, b.id)
        bb = BranchBuilder(branch=self.branch)
        bb.start_series()
        bb.build_snapshot(None,
                          [('add', ('', None, 'directory', None)),
                           ('add', ('foo', b'foo-id', 'file', b'a\nb\nc\nd\ne\n')),
                           ])
        bb.finish_series()
        # read locks cache
        self.assertRaises(KeyError, self.store.__getitem__, b.id)
        self.store.unlock()
        self.store.lock_read()
        self.assertEqual(b, self.store[b.id])

    def test_get_raw(self):
        b = Blob()
        b.data = b'a\nb\nc\nd\ne\n'
        self.store.lock_read()
        self.addCleanup(self.store.unlock)
        self.assertRaises(KeyError, self.store.get_raw, b.id)
        bb = BranchBuilder(branch=self.branch)
        bb.start_series()
        bb.build_snapshot(None,
                          [('add', ('', None, 'directory', None)),
                           ('add', ('foo', b'foo-id', 'file', b'a\nb\nc\nd\ne\n')),
                           ])
        bb.finish_series()
        # read locks cache
        self.assertRaises(KeyError, self.store.get_raw, b.id)
        self.store.unlock()
        self.store.lock_read()
        self.assertEqual(b.as_raw_string(), self.store.get_raw(b.id)[1])

    def test_contains(self):
        b = Blob()
        b.data = b'a\nb\nc\nd\ne\n'
        self.store.lock_read()
        self.addCleanup(self.store.unlock)
        self.assertFalse(b.id in self.store)
        bb = BranchBuilder(branch=self.branch)
        bb.start_series()
        bb.build_snapshot(None,
                          [('add', ('', None, 'directory', None)),
                           ('add', ('foo', b'foo-id', 'file', b'a\nb\nc\nd\ne\n')),
                           ])
        bb.finish_series()
        # read locks cache
        self.assertFalse(b.id in self.store)
        self.store.unlock()
        self.store.lock_read()
        self.assertTrue(b.id in self.store)


class TreeToObjectsTests(TestCaseWithTransport):

    def setUp(self):
        super(TreeToObjectsTests, self).setUp()
        self.idmap = DictGitShaMap()

    def test_no_changes(self):
        tree = self.make_branch_and_tree('.')
        self.addCleanup(tree.lock_read().unlock)
        entries = list(_tree_to_objects(tree, [tree], self.idmap, {}))
        self.assertEqual([], entries)

    def test_with_gitdir(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['.git', 'foo'])
        tree.add(['.git', 'foo'])
        revid = tree.commit('commit')
        revtree = tree.branch.repository.revision_tree(revid)
        self.addCleanup(revtree.lock_read().unlock)
        entries = list(_tree_to_objects(revtree, [], self.idmap, {}))
        self.assertEqual(['foo', ''], [p[0] for p in entries])


class DirectoryToTreeTests(TestCase):

    def test_empty(self):
        t = directory_to_tree('', [], None, {}, None, allow_empty=False)
        self.assertEqual(None, t)

    def test_empty_dir(self):
        child_ie = InventoryDirectory(b'bar', 'bar', b'bar')
        t = directory_to_tree('', [child_ie], lambda p, x: None, {}, None,
                              allow_empty=False)
        self.assertEqual(None, t)

    def test_empty_dir_dummy_files(self):
        child_ie = InventoryDirectory(b'bar', 'bar', b'bar')
        t = directory_to_tree('', [child_ie], lambda p, x: None, {}, ".mydummy",
                              allow_empty=False)
        self.assertTrue(".mydummy" in t)

    def test_empty_root(self):
        child_ie = InventoryDirectory(b'bar', 'bar', b'bar')
        t = directory_to_tree('', [child_ie], lambda p, x: None, {}, None,
                              allow_empty=True)
        self.assertEqual(Tree(), t)

    def test_with_file(self):
        child_ie = InventoryFile(b'bar', 'bar', b'bar')
        b = Blob.from_string(b"bla")
        t1 = directory_to_tree('', [child_ie], lambda p, x: b.id, {}, None,
                               allow_empty=False)
        t2 = Tree()
        t2.add(b"bar", 0o100644, b.id)
        self.assertEqual(t1, t2)

    def test_with_gitdir(self):
        child_ie = InventoryFile(b'bar', 'bar', b'bar')
        git_file_ie = InventoryFile(b'gitid', '.git', b'bar')
        b = Blob.from_string(b"bla")
        t1 = directory_to_tree('', [child_ie, git_file_ie],
                               lambda p, x: b.id, {}, None,
                               allow_empty=False)
        t2 = Tree()
        t2.add(b"bar", 0o100644, b.id)
        self.assertEqual(t1, t2)
