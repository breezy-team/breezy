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

"""Tests for Tree and InterTree."""

from breezy import errors, revision
from breezy.tests import TestCase, TestCaseWithTransport

from ..tree import (
    FileTimestampUnavailable,
    InterTree,
    find_previous_paths,
    get_canonical_path,
)


class TestErrors(TestCase):
    def test_file_timestamp_unavailable(self):
        e = FileTimestampUnavailable("/path/foo")
        self.assertEqual("The filestamp for /path/foo is not available.", str(e))


class TestInterTree(TestCaseWithTransport):
    def test_revision_tree_revision_tree(self):
        # we should have an InterTree registered for RevisionTree to
        # RevisionTree.
        tree = self.make_branch_and_tree(".")
        rev_id = tree.commit("first post")
        rev_id2 = tree.commit("second post", allow_pointless=True)
        rev_tree = tree.branch.repository.revision_tree(rev_id)
        rev_tree2 = tree.branch.repository.revision_tree(rev_id2)
        optimiser = InterTree.get(rev_tree, rev_tree2)
        self.assertIsInstance(optimiser, InterTree)
        optimiser = InterTree.get(rev_tree2, rev_tree)
        self.assertIsInstance(optimiser, InterTree)

    def test_working_tree_revision_tree(self):
        # we should have an InterTree available for WorkingTree to
        # RevisionTree.
        tree = self.make_branch_and_tree(".")
        rev_id = tree.commit("first post")
        rev_tree = tree.branch.repository.revision_tree(rev_id)
        optimiser = InterTree.get(rev_tree, tree)
        self.assertIsInstance(optimiser, InterTree)
        optimiser = InterTree.get(tree, rev_tree)
        self.assertIsInstance(optimiser, InterTree)

    def test_working_tree_working_tree(self):
        # we should have an InterTree available for WorkingTree to
        # WorkingTree.
        tree = self.make_branch_and_tree("1")
        tree2 = self.make_branch_and_tree("2")
        optimiser = InterTree.get(tree, tree2)
        self.assertIsInstance(optimiser, InterTree)
        optimiser = InterTree.get(tree2, tree)
        self.assertIsInstance(optimiser, InterTree)


class RecordingOptimiser(InterTree):
    calls: list[tuple[str, ...]] = []

    def compare(
        self,
        want_unchanged=False,
        specific_files=None,
        extra_trees=None,
        require_versioned=False,
        include_root=False,
        want_unversioned=False,
    ):
        self.calls.append(
            (
                "compare",
                self.source,
                self.target,
                want_unchanged,
                specific_files,
                extra_trees,
                require_versioned,
                include_root,
                want_unversioned,
            )
        )

    def find_source_path(self, target_path, recurse="none"):
        self.calls.append(
            ("find_source_path", self.source, self.target, target_path, recurse)
        )

    @classmethod
    def is_compatible(klass, source, target):
        return True


class TestTree(TestCaseWithTransport):
    def test_compare_calls_InterTree_compare(self):
        """This test tests the way Tree.compare() uses InterTree."""
        old_optimisers = InterTree._optimisers
        try:
            InterTree._optimisers = []
            RecordingOptimiser.calls = []
            InterTree.register_optimiser(RecordingOptimiser)
            tree = self.make_branch_and_tree("1")
            null_tree = tree.basis_tree()
            tree2 = self.make_branch_and_tree("2")
            # do a series of calls:
            # trivial usage
            tree.changes_from(tree2)
            # pass in all optional arguments by position
            tree.changes_from(tree2, "unchanged", "specific", "extra", "require", True)
            # pass in all optional arguments by keyword
            tree.changes_from(
                tree2,
                specific_files="specific",
                want_unchanged="unchanged",
                extra_trees="extra",
                require_versioned="require",
                include_root=True,
                want_unversioned=True,
            )
        finally:
            InterTree._optimisers = old_optimisers
        self.assertEqual(
            [
                ("find_source_path", null_tree, tree, "", "none"),
                ("find_source_path", null_tree, tree2, "", "none"),
                ("compare", tree2, tree, False, None, None, False, False, False),
                (
                    "compare",
                    tree2,
                    tree,
                    "unchanged",
                    "specific",
                    "extra",
                    "require",
                    True,
                    False,
                ),
                (
                    "compare",
                    tree2,
                    tree,
                    "unchanged",
                    "specific",
                    "extra",
                    "require",
                    True,
                    True,
                ),
            ],
            RecordingOptimiser.calls,
        )

    def test_changes_from_with_root(self):
        """Ensure the include_root option does what's expected."""
        wt = self.make_branch_and_tree(".")
        delta = wt.changes_from(wt.basis_tree())
        self.assertEqual(len(delta.added), 0)
        delta = wt.changes_from(wt.basis_tree(), include_root=True)
        self.assertEqual(len(delta.added), 1)
        self.assertEqual(delta.added[0].path[1], "")

    def test_changes_from_with_require_versioned(self):
        """Ensure the require_versioned option does what's expected."""
        wt = self.make_branch_and_tree(".")
        self.build_tree(["known_file", "unknown_file"])
        wt.add("known_file")

        self.assertRaises(
            errors.PathsNotVersionedError,
            wt.changes_from,
            wt.basis_tree(),
            wt,
            specific_files=["known_file", "unknown_file"],
            require_versioned=True,
        )

        # we need to pass a known file with an unknown file to get this to
        # fail when expected.
        delta = wt.changes_from(
            wt.basis_tree(),
            specific_files=["known_file", "unknown_file"],
            require_versioned=False,
        )
        self.assertEqual(len(delta.added), 1)


class FindPreviousPathsTests(TestCaseWithTransport):
    def test_new(self):
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/b"])
        tree.add(["b"])
        revid1 = tree.commit("first")
        tree1 = tree.branch.repository.revision_tree(revid1)

        tree0 = tree.branch.repository.revision_tree(revision.NULL_REVISION)

        self.assertEqual({"b": None}, find_previous_paths(tree1, tree0, ["b"]))

    def test_find_previous_paths(self):
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/b"])
        tree.add(["b"])
        revid1 = tree.commit("first")
        tree1 = tree.branch.repository.revision_tree(revid1)

        tree.rename_one("b", "c")
        self.build_tree(["tree/b"])
        tree.add(["b"])
        revid2 = tree.commit("second")
        tree2 = tree.branch.repository.revision_tree(revid2)

        self.assertEqual(
            {"c": "b", "b": None}, find_previous_paths(tree2, tree1, ["b", "c"])
        )


class GetCanonicalPath(TestCaseWithTransport):
    def test_existing_case(self):
        # Test that we can find a file from a path with different case
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/b"])
        tree.add(["b"])
        self.assertEqual("b", get_canonical_path(tree, "b", lambda x: x.lower()))
        self.assertEqual("b", get_canonical_path(tree, "B", lambda x: x.lower()))

    def test_nonexistant_preserves_case(self):
        tree = self.make_branch_and_tree("tree")
        self.assertEqual("b", get_canonical_path(tree, "b", lambda x: x.lower()))
        self.assertEqual("B", get_canonical_path(tree, "B", lambda x: x.lower()))

    def test_in_directory_with_case(self):
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/a/", "tree/a/b"])
        tree.add(["a", "a/b"])
        self.assertEqual("a/b", get_canonical_path(tree, "a/b", lambda x: x.lower()))
        self.assertEqual("a/b", get_canonical_path(tree, "A/B", lambda x: x.lower()))
        self.assertEqual("a/b", get_canonical_path(tree, "A/b", lambda x: x.lower()))
        self.assertEqual("a/C", get_canonical_path(tree, "A/C", lambda x: x.lower()))

    def test_trailing_slash(self):
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/a/", "tree/a/b"])
        tree.add(["a", "a/b"])
        self.assertEqual("a", get_canonical_path(tree, "a", lambda x: x))
        self.assertEqual("a", get_canonical_path(tree, "a/", lambda x: x))
