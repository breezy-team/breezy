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

import os

from dromedary.errors import NoSuchFile

from breezy import _cmd_rs
from breezy.branch import Branch, PullResult
from breezy.errors import NoRepositoryPresent
from breezy.repository import Repository
from breezy.tests import TestCase, TestCaseWithTransport, features
from breezy.workingtree import WorkingTree


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

    def test_working_tree_basedir(self):
        tree = self.make_branch_and_tree("tree")
        wrapped = _cmd_rs.WorkingTree(tree)
        self.assertEqual(tree.basedir, wrapped.basedir)

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


class TestRustRepositoryBinding(TestCaseWithTransport):
    """The Repository binding wrapping a Python repository."""

    def make_committed_repo(self):
        tree = self.make_branch_and_tree("tree")
        self.build_tree_contents([("tree/f", b"x\n")])
        tree.add(["f"])
        revid = tree.commit("one")
        return tree.branch.repository, revid

    def test_has_revision(self):
        repo, revid = self.make_committed_repo()
        wrapped = _cmd_rs.Repository(repo)
        self.assertTrue(wrapped.has_revision(revid))
        self.assertFalse(wrapped.has_revision(b"missing-revid"))

    def test_all_revision_ids(self):
        repo, revid = self.make_committed_repo()
        wrapped = _cmd_rs.Repository(repo)
        self.assertEqual([revid], wrapped.all_revision_ids())

    def test_get_revision(self):
        repo, revid = self.make_committed_repo()
        wrapped = _cmd_rs.Repository(repo)
        self.assertEqual(revid, wrapped.get_revision(revid).revision_id)

    def test_supports_rich_root(self):
        repo, _revid = self.make_committed_repo()
        wrapped = _cmd_rs.Repository(repo)
        self.assertEqual(repo.supports_rich_root(), wrapped.supports_rich_root())

    def test_get_rev_id_for_revno(self):
        repo, revid = self.make_committed_repo()
        wrapped = _cmd_rs.Repository(repo)
        # Returns a (found, revision_id) tuple; the tip is revno 1.
        with repo.lock_read():
            self.assertEqual((True, revid), wrapped.get_rev_id_for_revno(1, (1, revid)))


class TestRustControlDir(TestCaseWithTransport):
    """The control directory layer, reached through _cmd_rs.ControlDir."""

    def test_python_backed_objects_come_back_unwrapped(self):
        from breezy.git.dir import LocalGitDir
        from breezy.git.workingtree import GitWorkingTree

        tree = self.make_branch_and_tree("gittree", format="git")
        opened = _cmd_rs.ControlDir.open(tree.basedir)
        self.assertIsInstance(opened, LocalGitDir)
        self.assertIsInstance(_cmd_rs.WorkingTree.open(tree.basedir), GitWorkingTree)
        # A wrapped Python control directory hands out its own objects too.
        wrapped = _cmd_rs.ControlDir(tree.controldir)
        self.assertIs(tree.controldir, wrapped.open_workingtree().controldir)
        self.assertIsInstance(wrapped.open_workingtree(), GitWorkingTree)

    def test_wrapped_python_repository_finds_branches(self):
        tree = self.make_branch_and_tree("tree")
        repository = _cmd_rs.Repository(tree.branch.repository)
        self.assertEqual(
            [tree.branch.base], [b.base for b in repository.find_branches()]
        )

    def test_create_uses_python_default_format(self):
        from breezy.bzr.bzrdir import BzrDir

        created = _cmd_rs.ControlDir.create("new")
        self.assertIsInstance(created, BzrDir)
        self.assertRaises(NoRepositoryPresent, created.open_repository)
        created.create_repository()
        self.assertTrue(_cmd_rs.ControlDir(created).has_repository())
        branch = _cmd_rs.ControlDir.create_branch_convenience("other")
        self.assertTrue(branch.controldir.has_workingtree())
        tree = _cmd_rs.ControlDir.create_standalone_workingtree("third")
        self.assertTrue(tree.controldir.has_branch())

    def test_open_containing_tree_or_branch(self):
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/sub/"])
        opened_tree, branch, relpath = (
            _cmd_rs.ControlDir.open_containing_tree_or_branch("tree/sub")
        )
        self.assertIsInstance(opened_tree, WorkingTree)
        self.assertIsInstance(branch, Branch)
        self.assertEqual("sub", relpath)
        self.assertEqual(tree.basedir, opened_tree.basedir)
        _tree, _branch, repository, relpath = (
            _cmd_rs.ControlDir.open_containing_tree_branch_or_repository("tree/sub")
        )
        self.assertIsInstance(repository, Repository)
        self.assertEqual("sub", relpath)

    def test_find_branches(self):
        self.make_branch_and_tree("a")
        self.build_tree(["b/"])
        self.make_branch_and_tree("b/nested")
        self.make_branch_and_tree("c", format="git")
        transport = self.get_transport()
        found = _cmd_rs.ControlDir.find_branches(transport)
        self.assertEqual(
            sorted(transport.base + name for name in ["a/", "b/nested/", "c/"]),
            sorted(b.base for b in found),
        )
        dirs = _cmd_rs.ControlDir.find_controldirs(transport)
        self.assertEqual(3, len(dirs))

    def test_class_method_openers(self):
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/sub/", "tree/sub/file"])
        branch, relpath = _cmd_rs.Branch.open_containing("tree/sub")
        self.assertIsInstance(branch, Branch)
        self.assertEqual("sub", relpath)
        self.assertEqual(tree.branch.base, _cmd_rs.Branch.open("tree").base)
        self.assertEqual(
            tree.branch.base,
            _cmd_rs.Branch.open_from_transport(self.get_transport("tree")).base,
        )
        self.assertIsInstance(_cmd_rs.Repository.open("tree"), Repository)
        opened, relpaths = _cmd_rs.WorkingTree.open_containing_paths(["tree/sub/file"])
        self.assertEqual(tree.basedir, opened.basedir)
        self.assertEqual(["sub/file"], relpaths)
        opened, relpath = _cmd_rs.WorkingTree.open_containing("tree/sub")
        self.assertEqual("sub", relpath)
        self.assertTrue(_cmd_rs.Tree.versionable_kind("file"))
        self.assertFalse(_cmd_rs.Tree.versionable_kind("bogus"))
        self.assertEqual(tree.branch.base, opened.branch.base)
        self.assertEqual(tree.controldir.user_url, opened.controldir.user_url)
        self.assertEqual(tree.branch.repository.base, opened.branch.repository.base)
        self.assertEqual(
            tree.controldir.control_url, _cmd_rs.ControlDir.open("tree").control_url
        )
        self.assertEqual(
            tree.controldir.root_transport.base,
            _cmd_rs.ControlDir.open("tree").root_transport.base,
        )

    def test_default_format_mirrors_python(self):
        from breezy.controldir import ControlDirFormat

        self.assertIs(
            ControlDirFormat.get_default_format(), _cmd_rs.get_default_format()
        )


class Boom(Exception):
    """Raised by every attribute of ``RaisingObject``."""


class RaisingObject:
    """A stand-in for a breezy object whose every attribute raises Boom."""

    def __getattr__(self, name):
        raise Boom(name)


class TestPythonErrorsPropagate(TestCase):
    """Errors from the wrapped Python object reach the caller unchanged."""

    def test_branch(self):
        branch = _cmd_rs.Branch(RaisingObject())
        for name in (
            "last_revision",
            "is_locked",
            "peek_lock_mode",
            "supports_tags",
            "get_tag_dict",
        ):
            self.assertRaises(Boom, getattr(branch, name))
        self.assertRaises(Boom, getattr, branch, "name")

    def test_repository(self):
        repository = _cmd_rs.Repository(RaisingObject())
        for name in (
            "is_locked",
            "is_write_locked",
            "supports_rich_root",
            "is_in_write_group",
        ):
            self.assertRaises(Boom, getattr(repository, name))
        self.assertRaises(Boom, repository.has_same_location, RaisingObject())


class TestPythonResultTypes(TestCaseWithTransport):
    """Results the Python trees give are converted, not rejected."""

    def make_tree(self):
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/dir/", "tree/file"])
        tree.add(["dir", "file"])
        return tree

    def test_path_content_summary_sha1(self):
        tree = self.make_tree()
        rtree = tree.branch.repository.revision_tree(tree.commit("one"))
        with rtree.lock_read():
            expected = rtree.path_content_summary("file")
            self.assertIsInstance(expected[3], bytes)
            self.assertEqual(expected, _cmd_rs.Tree(rtree).path_content_summary("file"))

    def test_path_content_summary_symlink(self):
        self.requireFeature(features.SymlinkFeature(self.test_dir))
        tree = self.make_tree()
        os.symlink("file", "tree/link")
        tree.add(["link"])
        with tree.lock_read():
            self.assertEqual(
                tree.path_content_summary("link"),
                _cmd_rs.WorkingTree(tree).path_content_summary("link"),
            )

    def test_get_file_size_of_directory(self):
        tree = self.make_tree()
        rtree = tree.branch.repository.revision_tree(tree.commit("one"))
        with rtree.lock_read():
            self.assertIs(None, rtree.get_file_size("dir"))
            self.assertIs(None, _cmd_rs.Tree(rtree).get_file_size("dir"))

    def test_pull_returns_pull_result(self):
        tree = self.make_tree()
        tree.commit("one")
        other = tree.controldir.sprout("other").open_workingtree()
        tip = tree.commit("two")
        with other.lock_write():
            result = _cmd_rs.WorkingTree(other).pull(tree.branch)
        self.assertIsInstance(result, PullResult)
        self.assertEqual(tip, other.last_revision())
