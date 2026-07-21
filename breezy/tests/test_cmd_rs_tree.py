# Copyright (C) 2026 Breezy Developers
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

"""Tests for the Rust tree bindings in ``breezy._cmd_rs``.

The ``Tree``/``MutableTree``/``WorkingTree``/``RevisionTree`` classes each wrap
a Rust tree trait object. Given a Python tree they wrap it as a ``PyTree``
behind the trait object, so calls made here travel Python -> Rust -> Python.
The class hierarchy mirrors the trait hierarchy.
"""

from dromedary.errors import NoSuchFile

from breezy import _cmd_rs
from breezy.tests import TestCaseWithTransport


class TestRustTreeBinding(TestCaseWithTransport):
    def make_tree(self):
        """A MemoryTree with a single versioned file, locked for writing."""
        branch = self.make_branch("branch")
        tree = branch.create_memorytree()
        tree.lock_write()
        self.addCleanup(tree.unlock)
        tree.add([""])
        tree.put_file_bytes_non_atomic("hello.txt", b"world\n")
        tree.add(["hello.txt"])
        return tree

    def test_class_hierarchy(self):
        self.assertTrue(issubclass(_cmd_rs.MutableTree, _cmd_rs.Tree))
        self.assertTrue(issubclass(_cmd_rs.WorkingTree, _cmd_rs.MutableTree))
        self.assertTrue(issubclass(_cmd_rs.WorkingTree, _cmd_rs.Tree))
        self.assertTrue(issubclass(_cmd_rs.RevisionTree, _cmd_rs.Tree))

    def test_isinstance(self):
        tree = self.make_tree()
        wt = _cmd_rs.WorkingTree(tree)
        self.assertIsInstance(wt, _cmd_rs.WorkingTree)
        self.assertIsInstance(wt, _cmd_rs.MutableTree)
        self.assertIsInstance(wt, _cmd_rs.Tree)

    def test_tree_query_methods(self):
        tree = self.make_tree()
        wrapped = _cmd_rs.Tree(tree)
        self.assertEqual(
            tree.supports_rename_tracking(), wrapped.supports_rename_tracking()
        )
        self.assertTrue(wrapped.is_versioned("hello.txt"))
        self.assertFalse(wrapped.is_versioned("nope.txt"))
        self.assertEqual("file", wrapped.kind("hello.txt"))
        self.assertTrue(wrapped.has_filename("hello.txt"))
        self.assertEqual(b"world\n", wrapped.get_file_text("hello.txt"))
        self.assertEqual(
            sorted(tree.all_versioned_paths()),
            sorted(wrapped.all_versioned_paths()),
        )

    def test_inherited_tree_methods_on_working_tree(self):
        tree = self.make_tree()
        wt = _cmd_rs.WorkingTree(tree)
        # Tree-level methods are inherited by the WorkingTree wrapper.
        self.assertTrue(wt.is_versioned("hello.txt"))
        self.assertEqual(b"world\n", wt.get_file_text("hello.txt"))

    def test_mutable_methods_require_mutable_tree(self):
        tree = self.make_tree()
        # A plain Tree wrapper does not expose the mutating API.
        self.assertFalse(hasattr(_cmd_rs.Tree(tree), "put_file_bytes_non_atomic"))
        mt = _cmd_rs.MutableTree(tree)
        mt.put_file_bytes_non_atomic("hello.txt", b"changed\n")
        self.assertEqual(b"changed\n", tree.get_file_text("hello.txt"))

    def test_working_tree_last_revision(self):
        tree = self.make_tree()
        wt = _cmd_rs.WorkingTree(tree)
        self.assertEqual(tree.last_revision(), wt.last_revision())

    def test_mutable_tree_last_revision(self):
        tree = self.make_tree()
        # MutableTree.last_revision returns the leftmost parent id, or None.
        mt = _cmd_rs.MutableTree(tree)
        self.assertEqual(tree.last_revision(), mt.last_revision())

    def test_iter_changes(self):
        tree = self.make_tree()
        wt = _cmd_rs.WorkingTree(tree)
        basis = tree.basis_tree()
        # hello.txt shows up as an added path relative to the empty basis.
        paths = {c.path[1] for c in wt.iter_changes(basis)}
        self.assertIn("hello.txt", paths)

    def test_error_mapping(self):
        tree = self.make_tree()
        wrapped = _cmd_rs.Tree(tree)
        self.assertRaises(NoSuchFile, wrapped.get_file_text, "does-not-exist.txt")

    def test_get_parent_ids(self):
        tree = self.make_tree()
        self.assertEqual(tree.get_parent_ids(), _cmd_rs.Tree(tree).get_parent_ids())

    def test_revision_tree(self):
        tree = self.make_tree()
        revid = tree.commit("one")
        rtree = tree.branch.repository.revision_tree(revid)
        wrapped = _cmd_rs.RevisionTree(rtree)
        self.assertIsInstance(wrapped, _cmd_rs.Tree)
        self.assertEqual(revid, wrapped.get_revision_id())
        # RevisionTree extends Tree, not MutableTree, so has no commit method.
        self.assertFalse(hasattr(wrapped, "commit"))

    def test_lock_read_unlock(self):
        branch = self.make_branch("branch")
        tree = branch.create_memorytree()
        wrapped = _cmd_rs.Tree(tree)
        # A lock/unlock round trip through the wrapper does not error and
        # leaves the tree readable.
        wrapped.lock_read()
        wrapped.unlock()
        with tree.lock_read():
            self.assertEqual([], tree.get_parent_ids())


class TestRustBranchBinding(TestCaseWithTransport):
    """The Branch binding wrapping a Python branch (Python -> Rust -> Python)."""

    def make_committed_branch(self):
        tree = self.make_branch_and_tree("tree")
        self.build_tree_contents([("tree/f", b"x\n")])
        tree.add(["f"])
        revid = tree.commit("one")
        return tree.branch, revid

    def test_query_methods(self):
        branch, revid = self.make_committed_branch()
        wrapped = _cmd_rs.Branch(branch)
        self.assertEqual(revid, wrapped.last_revision())
        self.assertEqual(branch.revno(), wrapped.revno())
        self.assertEqual(branch.last_revision_info(), wrapped.last_revision_info())
        self.assertEqual(branch.supports_tags(), wrapped.supports_tags())

    def test_get_rev_id(self):
        branch, revid = self.make_committed_branch()
        wrapped = _cmd_rs.Branch(branch)
        self.assertEqual(revid, wrapped.get_rev_id(1))

    def test_heads_to_fetch(self):
        # heads_to_fetch returns sets in Python; the tip is a must-fetch head.
        branch, revid = self.make_committed_branch()
        wrapped = _cmd_rs.Branch(branch)
        must, _if_present = wrapped.heads_to_fetch()
        self.assertIn(revid, must)

    def test_get_tag_dict(self):
        branch, revid = self.make_committed_branch()
        branch.tags.set_tag("v1", revid)
        wrapped = _cmd_rs.Branch(branch)
        self.assertEqual({"v1": revid}, wrapped.get_tag_dict())

    def test_set_and_get_parent(self):
        branch, _revid = self.make_committed_branch()
        wrapped = _cmd_rs.Branch(branch)
        wrapped.set_parent("../other")
        self.assertIn("other", wrapped.get_parent())

    def test_not_stacked_raises(self):
        from breezy.errors import NotStacked

        branch, _revid = self.make_committed_branch()
        wrapped = _cmd_rs.Branch(branch)
        self.assertRaises(NotStacked, wrapped.get_stacked_on_url)
