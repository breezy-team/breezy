# Copyright (C) 2006-2009, 2011 Canonical Ltd
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

"""Tests for MultiWalker."""

from breezy import multiwalker, revision
from breezy.tests import TestCaseWithTransport


class TestMultiWalker(TestCaseWithTransport):
    def assertStepOne(self, has_more, path, file_id, iterator):
        retval = multiwalker.MultiWalker._step_one(iterator)
        if not has_more:
            self.assertIs(None, path)
            self.assertIs(None, file_id)
            self.assertEqual((False, None, None), retval)
        else:
            self.assertEqual(
                (has_more, path, file_id), (retval[0], retval[1], retval[2].file_id)
            )

    def test__step_one_empty(self):
        tree = self.make_branch_and_tree("empty")
        repo = tree.branch.repository
        empty_tree = repo.revision_tree(revision.NULL_REVISION)

        iterator = empty_tree.iter_entries_by_dir()
        self.assertStepOne(False, None, None, iterator)
        self.assertStepOne(False, None, None, iterator)

    def test__step_one(self):
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/a", "tree/b/", "tree/b/c"])
        tree.add(["a", "b", "b/c"], ids=[b"a-id", b"b-id", b"c-id"])

        iterator = tree.iter_entries_by_dir()
        tree.lock_read()
        self.addCleanup(tree.unlock)

        root_id = tree.path2id("")
        self.assertStepOne(True, "", root_id, iterator)
        self.assertStepOne(True, "a", b"a-id", iterator)
        self.assertStepOne(True, "b", b"b-id", iterator)
        self.assertStepOne(True, "b/c", b"c-id", iterator)
        self.assertStepOne(False, None, None, iterator)
        self.assertStepOne(False, None, None, iterator)

    def assertWalkerNext(
        self, exp_path, exp_file_id, master_has_node, exp_other_paths, iterator
    ):
        """Check what happens when we step the iterator.

        :param path: The path for this entry
        :param file_id: The file_id for this entry
        :param master_has_node: Does the master tree have this entry?
        :param exp_other_paths: A list of other_path values.
        :param iterator: The iterator to step
        """
        path, file_id, master_ie, other_values = next(iterator)
        self.assertEqual(
            (exp_path, exp_file_id), (path, file_id), "Master entry did not match"
        )
        if master_has_node:
            self.assertIsNot(None, master_ie, "master should have an entry")
        else:
            self.assertIs(None, master_ie, "master should not have an entry")
        self.assertEqual(
            len(exp_other_paths), len(other_values), "Wrong number of other entries"
        )
        other_paths = []
        other_file_ids = []
        for path, ie in other_values:
            other_paths.append(path)
            if ie is None:
                other_file_ids.append(None)
            else:
                other_file_ids.append(ie.file_id)

        exp_file_ids = []
        for path in exp_other_paths:
            if path is None:
                exp_file_ids.append(None)
            else:
                exp_file_ids.append(file_id)
        self.assertEqual(exp_other_paths, other_paths, "Other paths incorrect")
        self.assertEqual(exp_file_ids, other_file_ids, "Other file_ids incorrect")

    def lock_and_get_basis_and_root_id(self, tree):
        tree.lock_read()
        self.addCleanup(tree.unlock)
        basis_tree = tree.basis_tree()
        basis_tree.lock_read()
        self.addCleanup(basis_tree.unlock)
        root_id = tree.path2id("")
        return basis_tree, root_id

    def test_simple_stepping(self):
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/a", "tree/b/", "tree/b/c"])
        tree.add(["a", "b", "b/c"], ids=[b"a-id", b"b-id", b"c-id"])

        tree.commit("first", rev_id=b"first-rev-id")

        basis_tree, root_id = self.lock_and_get_basis_and_root_id(tree)

        walker = multiwalker.MultiWalker(tree, [basis_tree])
        iterator = walker.iter_all()
        self.assertWalkerNext("", root_id, True, [""], iterator)
        self.assertWalkerNext("a", b"a-id", True, ["a"], iterator)
        self.assertWalkerNext("b", b"b-id", True, ["b"], iterator)
        self.assertWalkerNext("b/c", b"c-id", True, ["b/c"], iterator)
        self.assertRaises(StopIteration, next, iterator)

    def test_master_has_extra(self):
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/a", "tree/b/", "tree/c", "tree/d"])
        tree.add(["a", "b", "d"], ids=[b"a-id", b"b-id", b"d-id"])

        tree.commit("first", rev_id=b"first-rev-id")

        tree.add(["c"], ids=[b"c-id"])
        basis_tree, root_id = self.lock_and_get_basis_and_root_id(tree)

        walker = multiwalker.MultiWalker(tree, [basis_tree])
        iterator = walker.iter_all()
        self.assertWalkerNext("", root_id, True, [""], iterator)
        self.assertWalkerNext("a", b"a-id", True, ["a"], iterator)
        self.assertWalkerNext("b", b"b-id", True, ["b"], iterator)
        self.assertWalkerNext("c", b"c-id", True, [None], iterator)
        self.assertWalkerNext("d", b"d-id", True, ["d"], iterator)
        self.assertRaises(StopIteration, next, iterator)

    def test_master_renamed_to_earlier(self):
        """The record is still present, it just shows up early."""
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/a", "tree/c", "tree/d"])
        tree.add(["a", "c", "d"], ids=[b"a-id", b"c-id", b"d-id"])
        tree.commit("first", rev_id=b"first-rev-id")
        tree.rename_one("d", "b")

        basis_tree, root_id = self.lock_and_get_basis_and_root_id(tree)

        walker = multiwalker.MultiWalker(tree, [basis_tree])
        iterator = walker.iter_all()
        self.assertWalkerNext("", root_id, True, [""], iterator)
        self.assertWalkerNext("a", b"a-id", True, ["a"], iterator)
        self.assertWalkerNext("b", b"d-id", True, ["d"], iterator)
        self.assertWalkerNext("c", b"c-id", True, ["c"], iterator)
        self.assertRaises(StopIteration, next, iterator)

    def test_master_renamed_to_later(self):
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/a", "tree/b", "tree/d"])
        tree.add(["a", "b", "d"], ids=[b"a-id", b"b-id", b"d-id"])
        tree.commit("first", rev_id=b"first-rev-id")
        tree.rename_one("b", "e")

        basis_tree, root_id = self.lock_and_get_basis_and_root_id(tree)

        walker = multiwalker.MultiWalker(tree, [basis_tree])
        iterator = walker.iter_all()
        self.assertWalkerNext("", root_id, True, [""], iterator)
        self.assertWalkerNext("a", b"a-id", True, ["a"], iterator)
        self.assertWalkerNext("d", b"d-id", True, ["d"], iterator)
        self.assertWalkerNext("e", b"b-id", True, ["b"], iterator)
        self.assertRaises(StopIteration, next, iterator)

    def test_other_extra_in_middle(self):
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/a", "tree/b", "tree/d"])
        tree.add(["a", "b", "d"], ids=[b"a-id", b"b-id", b"d-id"])
        tree.commit("first", rev_id=b"first-rev-id")
        tree.remove(["b"])

        basis_tree, root_id = self.lock_and_get_basis_and_root_id(tree)
        walker = multiwalker.MultiWalker(tree, [basis_tree])
        iterator = walker.iter_all()
        self.assertWalkerNext("", root_id, True, [""], iterator)
        self.assertWalkerNext("a", b"a-id", True, ["a"], iterator)
        self.assertWalkerNext("d", b"d-id", True, ["d"], iterator)
        self.assertWalkerNext("b", b"b-id", False, ["b"], iterator)
        self.assertRaises(StopIteration, next, iterator)

    def test_other_extra_at_end(self):
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/a", "tree/b", "tree/d"])
        tree.add(["a", "b", "d"], ids=[b"a-id", b"b-id", b"d-id"])
        tree.commit("first", rev_id=b"first-rev-id")
        tree.remove(["d"])

        basis_tree, root_id = self.lock_and_get_basis_and_root_id(tree)
        walker = multiwalker.MultiWalker(tree, [basis_tree])
        iterator = walker.iter_all()
        self.assertWalkerNext("", root_id, True, [""], iterator)
        self.assertWalkerNext("a", b"a-id", True, ["a"], iterator)
        self.assertWalkerNext("b", b"b-id", True, ["b"], iterator)
        self.assertWalkerNext("d", b"d-id", False, ["d"], iterator)
        self.assertRaises(StopIteration, next, iterator)

    def test_others_extra_at_end(self):
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/a", "tree/b", "tree/c", "tree/d", "tree/e"])
        tree.add(
            ["a", "b", "c", "d", "e"], ids=[b"a-id", b"b-id", b"c-id", b"d-id", b"e-id"]
        )
        tree.commit("first", rev_id=b"first-rev-id")
        tree.remove(["e"])
        tree.commit("second", rev_id=b"second-rev-id")
        tree.remove(["d"])
        tree.commit("third", rev_id=b"third-rev-id")
        tree.remove(["c"])

        basis_tree, root_id = self.lock_and_get_basis_and_root_id(tree)
        first_tree = tree.branch.repository.revision_tree(b"first-rev-id")
        second_tree = tree.branch.repository.revision_tree(b"second-rev-id")
        walker = multiwalker.MultiWalker(tree, [basis_tree, first_tree, second_tree])
        iterator = walker.iter_all()
        self.assertWalkerNext("", root_id, True, ["", "", ""], iterator)
        self.assertWalkerNext("a", b"a-id", True, ["a", "a", "a"], iterator)
        self.assertWalkerNext("b", b"b-id", True, ["b", "b", "b"], iterator)
        self.assertWalkerNext("c", b"c-id", False, ["c", "c", "c"], iterator)
        self.assertWalkerNext("d", b"d-id", False, [None, "d", "d"], iterator)
        self.assertWalkerNext("e", b"e-id", False, [None, "e", None], iterator)
        self.assertRaises(StopIteration, next, iterator)

    def test_different_file_id_in_others(self):
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/a", "tree/b", "tree/c/"])
        tree.add(["a", "b", "c"], ids=[b"a-id", b"b-id", b"c-id"])
        tree.commit("first", rev_id=b"first-rev-id")

        tree.rename_one("b", "c/d")
        self.build_tree(["tree/b"])
        tree.add(["b"], ids=[b"b2-id"])
        tree.commit("second", rev_id=b"second-rev-id")

        tree.rename_one("a", "c/e")
        self.build_tree(["tree/a"])
        tree.add(["a"], ids=[b"a2-id"])

        basis_tree, root_id = self.lock_and_get_basis_and_root_id(tree)
        first_tree = tree.branch.repository.revision_tree(b"first-rev-id")
        walker = multiwalker.MultiWalker(tree, [basis_tree, first_tree])

        iterator = walker.iter_all()
        self.assertWalkerNext("", root_id, True, ["", ""], iterator)
        self.assertWalkerNext("a", b"a2-id", True, [None, None], iterator)
        self.assertWalkerNext("b", b"b2-id", True, ["b", None], iterator)
        self.assertWalkerNext("c", b"c-id", True, ["c", "c"], iterator)
        self.assertWalkerNext("c/d", b"b-id", True, ["c/d", "b"], iterator)
        self.assertWalkerNext("c/e", b"a-id", True, ["a", "a"], iterator)
        self.assertRaises(StopIteration, next, iterator)

    def assertLtByDirblock(self, lt_val, path1, path2):
        self.assertEqual(
            lt_val, multiwalker.MultiWalker._lt_path_by_dirblock(path1, path2)
        )

    def test__lt_path_by_dirblock(self):
        # We only support Unicode strings at this point
        self.assertRaises(
            TypeError, multiwalker.MultiWalker._lt_path_by_dirblock, b"", b"b"
        )
        self.assertLtByDirblock(False, "", "")
        self.assertLtByDirblock(False, "a", "a")
        self.assertLtByDirblock(False, "a/b", "a/b")
        self.assertLtByDirblock(False, "a/b/c", "a/b/c")
        self.assertLtByDirblock(False, "a-a", "a")
        self.assertLtByDirblock(True, "a-a", "a/a")
        self.assertLtByDirblock(True, "a=a", "a/a")
        self.assertLtByDirblock(False, "a-a/a", "a/a")
        self.assertLtByDirblock(False, "a=a/a", "a/a")
        self.assertLtByDirblock(False, "a-a/a", "a/a/a")
        self.assertLtByDirblock(False, "a=a/a", "a/a/a")
        self.assertLtByDirblock(False, "a-a/a/a", "a/a/a")
        self.assertLtByDirblock(False, "a=a/a/a", "a/a/a")

    def assertPathToKey(self, expected, path):
        self.assertEqual(expected, multiwalker.MultiWalker._path_to_key(path))

    def test__path_to_key(self):
        self.assertPathToKey(([""], ""), "")
        self.assertPathToKey(([""], "a"), "a")
        self.assertPathToKey((["a"], "b"), "a/b")
        self.assertPathToKey((["a", "b"], "c"), "a/b/c")
