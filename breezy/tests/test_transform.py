# Copyright (C) 2006-2012, 2016 Canonical Ltd
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

import os

import fastbencode as bencode

from .. import osutils, tests, trace, transform
from .. import revision as _mod_revision
from ..bzr import generate_ids
from ..controldir import ControlDir
from ..errors import (
    StrictCommitFailed,
)
from ..merge import Merge3Merger
from ..mutabletree import MutableTree
from ..osutils import file_kind, pathjoin
from ..transform import (
    ROOT_PARENT,
    MalformedTransform,
    TransformRenameFailed,
    _FileMover,
    resolve_conflicts,
)
from ..transport import FileExists
from . import TestCaseInTempDir, features
from .features import HardlinkFeature, SymlinkFeature


class TransformGroup:
    def __init__(self, dirname, root_id):
        self.name = dirname
        os.mkdir(dirname)
        self.wt = ControlDir.create_standalone_workingtree(dirname)
        if self.wt.supports_file_ids:
            self.wt.set_root_id(root_id)
        self.b = self.wt.branch
        self.tt = self.wt.transform()
        self.root = self.tt.trans_id_tree_path("")


def conflict_text(tree, merge):
    template = b"%s TREE\n%s%s\n%s%s MERGE-SOURCE\n"
    return template % (b"<" * 7, tree, b"=" * 7, merge, b">" * 7)


class TestTransformMerge(TestCaseInTempDir):
    def test_text_merge(self):
        root_id = generate_ids.gen_root_id()
        base = TransformGroup("base", root_id)
        base.tt.new_file("a", base.root, [b"a\nb\nc\nd\be\n"], b"a")
        base.tt.new_file("b", base.root, [b"b1"], b"b")
        base.tt.new_file("c", base.root, [b"c"], b"c")
        base.tt.new_file("d", base.root, [b"d"], b"d")
        base.tt.new_file("e", base.root, [b"e"], b"e")
        base.tt.new_file("f", base.root, [b"f"], b"f")
        base.tt.new_directory("g", base.root, b"g")
        base.tt.new_directory("h", base.root, b"h")
        base.tt.apply()
        other = TransformGroup("other", root_id)
        other.tt.new_file("a", other.root, [b"y\nb\nc\nd\be\n"], b"a")
        other.tt.new_file("b", other.root, [b"b2"], b"b")
        other.tt.new_file("c", other.root, [b"c2"], b"c")
        other.tt.new_file("d", other.root, [b"d"], b"d")
        other.tt.new_file("e", other.root, [b"e2"], b"e")
        other.tt.new_file("f", other.root, [b"f"], b"f")
        other.tt.new_file("g", other.root, [b"g"], b"g")
        other.tt.new_file("h", other.root, [b"h\ni\nj\nk\n"], b"h")
        other.tt.new_file("i", other.root, [b"h\ni\nj\nk\n"], b"i")
        other.tt.apply()
        this = TransformGroup("this", root_id)
        this.tt.new_file("a", this.root, [b"a\nb\nc\nd\bz\n"], b"a")
        this.tt.new_file("b", this.root, [b"b"], b"b")
        this.tt.new_file("c", this.root, [b"c"], b"c")
        this.tt.new_file("d", this.root, [b"d2"], b"d")
        this.tt.new_file("e", this.root, [b"e2"], b"e")
        this.tt.new_file("f", this.root, [b"f"], b"f")
        this.tt.new_file("g", this.root, [b"g"], b"g")
        this.tt.new_file("h", this.root, [b"1\n2\n3\n4\n"], b"h")
        this.tt.new_file("i", this.root, [b"1\n2\n3\n4\n"], b"i")
        this.tt.apply()
        Merge3Merger(this.wt, this.wt, base.wt, other.wt)

        # textual merge
        with this.wt.get_file("a") as f:
            self.assertEqual(f.read(), b"y\nb\nc\nd\bz\n")
        # three-way text conflict
        with this.wt.get_file("b") as f:
            self.assertEqual(f.read(), conflict_text(b"b", b"b2"))
        # OTHER wins
        self.assertEqual(this.wt.get_file("c").read(), b"c2")
        # THIS wins
        self.assertEqual(this.wt.get_file("d").read(), b"d2")
        # Ambigious clean merge
        self.assertEqual(this.wt.get_file("e").read(), b"e2")
        # No change
        self.assertEqual(this.wt.get_file("f").read(), b"f")
        # Correct correct results when THIS == OTHER
        self.assertEqual(this.wt.get_file("g").read(), b"g")
        # Text conflict when THIS & OTHER are text and BASE is dir
        self.assertEqual(
            this.wt.get_file("h").read(),
            conflict_text(b"1\n2\n3\n4\n", b"h\ni\nj\nk\n"),
        )
        self.assertEqual(this.wt.get_file("h.THIS").read(), b"1\n2\n3\n4\n")
        self.assertEqual(this.wt.get_file("h.OTHER").read(), b"h\ni\nj\nk\n")
        self.assertEqual(file_kind(this.wt.abspath("h.BASE")), "directory")
        self.assertEqual(
            this.wt.get_file("i").read(),
            conflict_text(b"1\n2\n3\n4\n", b"h\ni\nj\nk\n"),
        )
        self.assertEqual(this.wt.get_file("i.THIS").read(), b"1\n2\n3\n4\n")
        self.assertEqual(this.wt.get_file("i.OTHER").read(), b"h\ni\nj\nk\n")
        self.assertEqual(os.path.exists(this.wt.abspath("i.BASE")), False)
        modified = ["a", "b", "c", "h", "i"]
        merge_modified = this.wt.merge_modified()
        self.assertSubset(merge_modified, modified)
        self.assertEqual(len(merge_modified), len(modified))
        with open(this.wt.abspath("a"), "wb") as f:
            f.write(b"booga")
        modified.pop(0)
        merge_modified = this.wt.merge_modified()
        self.assertSubset(merge_modified, modified)
        self.assertEqual(len(merge_modified), len(modified))
        this.wt.remove("b")
        this.wt.revert()

    def test_file_merge(self):
        self.requireFeature(SymlinkFeature(self.test_dir))
        root_id = generate_ids.gen_root_id()
        base = TransformGroup("BASE", root_id)
        this = TransformGroup("THIS", root_id)
        other = TransformGroup("OTHER", root_id)
        for tg in this, base, other:
            tg.tt.new_directory("a", tg.root, b"a")
            tg.tt.new_symlink("b", tg.root, "b", b"b")
            tg.tt.new_file("c", tg.root, [b"c"], b"c")
            tg.tt.new_symlink("d", tg.root, tg.name, b"d")
        targets = (
            (base, "base-e", "base-f", None, None),
            (this, "other-e", "this-f", "other-g", "this-h"),
            (other, "other-e", None, "other-g", "other-h"),
        )
        for tg, e_target, f_target, g_target, h_target in targets:
            for link, target in (
                ("e", e_target),
                ("f", f_target),
                ("g", g_target),
                ("h", h_target),
            ):
                if target is not None:
                    tg.tt.new_symlink(link, tg.root, target, link.encode("ascii"))

        for tg in this, base, other:
            tg.tt.apply()
        Merge3Merger(this.wt, this.wt, base.wt, other.wt)
        self.assertIs(os.path.isdir(this.wt.abspath("a")), True)
        self.assertIs(os.path.islink(this.wt.abspath("b")), True)
        self.assertIs(os.path.isfile(this.wt.abspath("c")), True)
        for suffix in ("THIS", "BASE", "OTHER"):
            self.assertEqual(os.readlink(this.wt.abspath("d." + suffix)), suffix)
        self.assertIs(os.path.lexists(this.wt.abspath("d")), False)
        self.assertEqual(this.wt.id2path(b"d"), "d.OTHER")
        self.assertEqual(this.wt.id2path(b"f"), "f.THIS")
        self.assertEqual(os.readlink(this.wt.abspath("e")), "other-e")
        self.assertIs(os.path.lexists(this.wt.abspath("e.THIS")), False)
        self.assertIs(os.path.lexists(this.wt.abspath("e.OTHER")), False)
        self.assertIs(os.path.lexists(this.wt.abspath("e.BASE")), False)
        self.assertIs(os.path.lexists(this.wt.abspath("g")), True)
        self.assertIs(os.path.lexists(this.wt.abspath("g.BASE")), False)
        self.assertIs(os.path.lexists(this.wt.abspath("h")), False)
        self.assertIs(os.path.lexists(this.wt.abspath("h.BASE")), False)
        self.assertIs(os.path.lexists(this.wt.abspath("h.THIS")), True)
        self.assertIs(os.path.lexists(this.wt.abspath("h.OTHER")), True)

    def test_filename_merge(self):
        root_id = generate_ids.gen_root_id()
        base = TransformGroup("BASE", root_id)
        this = TransformGroup("THIS", root_id)
        other = TransformGroup("OTHER", root_id)
        base_a, this_a, other_a = (
            t.tt.new_directory("a", t.root, b"a") for t in [base, this, other]
        )
        base_b, this_b, other_b = (
            t.tt.new_directory("b", t.root, b"b") for t in [base, this, other]
        )
        base.tt.new_directory("c", base_a, b"c")
        this.tt.new_directory("c1", this_a, b"c")
        other.tt.new_directory("c", other_b, b"c")

        base.tt.new_directory("d", base_a, b"d")
        this.tt.new_directory("d1", this_b, b"d")
        other.tt.new_directory("d", other_a, b"d")

        base.tt.new_directory("e", base_a, b"e")
        this.tt.new_directory("e", this_a, b"e")
        other.tt.new_directory("e1", other_b, b"e")

        base.tt.new_directory("f", base_a, b"f")
        this.tt.new_directory("f1", this_b, b"f")
        other.tt.new_directory("f1", other_b, b"f")

        for tg in [this, base, other]:
            tg.tt.apply()
        Merge3Merger(this.wt, this.wt, base.wt, other.wt)
        self.assertEqual(this.wt.id2path(b"c"), pathjoin("b/c1"))
        self.assertEqual(this.wt.id2path(b"d"), pathjoin("b/d1"))
        self.assertEqual(this.wt.id2path(b"e"), pathjoin("b/e1"))
        self.assertEqual(this.wt.id2path(b"f"), pathjoin("b/f1"))

    def test_filename_merge_conflicts(self):
        root_id = generate_ids.gen_root_id()
        base = TransformGroup("BASE", root_id)
        this = TransformGroup("THIS", root_id)
        other = TransformGroup("OTHER", root_id)
        base_a, this_a, other_a = (
            t.tt.new_directory("a", t.root, b"a") for t in [base, this, other]
        )
        base_b, this_b, other_b = (
            t.tt.new_directory("b", t.root, b"b") for t in [base, this, other]
        )

        base.tt.new_file("g", base_a, [b"g"], b"g")
        other.tt.new_file("g1", other_b, [b"g1"], b"g")

        base.tt.new_file("h", base_a, [b"h"], b"h")
        this.tt.new_file("h1", this_b, [b"h1"], b"h")

        base.tt.new_file("i", base.root, [b"i"], b"i")
        other.tt.new_directory("i1", this_b, b"i")

        for tg in [this, base, other]:
            tg.tt.apply()
        Merge3Merger(this.wt, this.wt, base.wt, other.wt)

        self.assertEqual(this.wt.id2path(b"g"), pathjoin("b/g1.OTHER"))
        self.assertIs(os.path.lexists(this.wt.abspath("b/g1.BASE")), True)
        self.assertIs(os.path.lexists(this.wt.abspath("b/g1.THIS")), False)
        self.assertEqual(this.wt.id2path(b"h"), pathjoin("b/h1.THIS"))
        self.assertIs(os.path.lexists(this.wt.abspath("b/h1.BASE")), True)
        self.assertIs(os.path.lexists(this.wt.abspath("b/h1.OTHER")), False)
        self.assertEqual(this.wt.id2path(b"i"), pathjoin("b/i1.OTHER"))


class TestCommitTransform(tests.TestCaseWithTransport):
    def get_branch(self):
        tree = self.make_branch_and_tree("tree")
        tree.lock_write()
        self.addCleanup(tree.unlock)
        tree.commit("empty commit")
        return tree.branch

    def get_branch_and_transform(self):
        branch = self.get_branch()
        tt = branch.basis_tree().preview_transform()
        self.addCleanup(tt.finalize)
        return branch, tt

    def test_commit_wrong_basis(self):
        branch = self.get_branch()
        basis = branch.repository.revision_tree(_mod_revision.NULL_REVISION)
        tt = basis.preview_transform()
        self.addCleanup(tt.finalize)
        e = self.assertRaises(ValueError, tt.commit, branch, "")
        self.assertEqual("TreeTransform not based on branch basis: null:", str(e))

    def test_empy_commit(self):
        branch, tt = self.get_branch_and_transform()
        rev = tt.commit(branch, "my message")
        self.assertEqual(2, branch.revno())
        repo = branch.repository
        self.assertEqual("my message", repo.get_revision(rev).message)

    def test_merge_parents(self):
        branch, tt = self.get_branch_and_transform()
        tt.commit(branch, "my message", [b"rev1b", b"rev1c"])
        self.assertEqual([b"rev1b", b"rev1c"], branch.basis_tree().get_parent_ids()[1:])

    def test_first_commit(self):
        branch = self.make_branch("branch")
        branch.lock_write()
        self.addCleanup(branch.unlock)
        tt = branch.basis_tree().preview_transform()
        self.addCleanup(tt.finalize)
        tt.new_directory("", ROOT_PARENT, b"TREE_ROOT")
        tt.commit(branch, "my message")
        self.assertEqual([], branch.basis_tree().get_parent_ids())
        self.assertNotEqual(_mod_revision.NULL_REVISION, branch.last_revision())

    def test_first_commit_with_merge_parents(self):
        branch = self.make_branch("branch")
        branch.lock_write()
        self.addCleanup(branch.unlock)
        tt = branch.basis_tree().preview_transform()
        self.addCleanup(tt.finalize)
        e = self.assertRaises(
            ValueError, tt.commit, branch, "my message", [b"rev1b-id"]
        )
        self.assertEqual("Cannot supply merge parents for first commit.", str(e))
        self.assertEqual(_mod_revision.NULL_REVISION, branch.last_revision())

    def test_add_files(self):
        branch, tt = self.get_branch_and_transform()
        tt.new_file("file", tt.root, [b"contents"], b"file-id")
        trans_id = tt.new_directory("dir", tt.root, b"dir-id")
        if SymlinkFeature(self.test_dir).available():
            tt.new_symlink("symlink", trans_id, "target", b"symlink-id")
        tt.commit(branch, "message")
        tree = branch.basis_tree()
        self.assertEqual("file", tree.id2path(b"file-id"))
        self.assertEqual(b"contents", tree.get_file_text("file"))
        self.assertEqual("dir", tree.id2path(b"dir-id"))
        if SymlinkFeature(self.test_dir).available():
            self.assertEqual("dir/symlink", tree.id2path(b"symlink-id"))
            self.assertEqual("target", tree.get_symlink_target("dir/symlink"))

    def test_add_unversioned(self):
        branch, tt = self.get_branch_and_transform()
        tt.new_file("file", tt.root, [b"contents"])
        self.assertRaises(StrictCommitFailed, tt.commit, branch, "message", strict=True)

    def test_modify_strict(self):
        branch, tt = self.get_branch_and_transform()
        tt.new_file("file", tt.root, [b"contents"], b"file-id")
        tt.commit(branch, "message", strict=True)
        tt = branch.basis_tree().preview_transform()
        self.addCleanup(tt.finalize)
        trans_id = tt.trans_id_file_id(b"file-id")
        tt.delete_contents(trans_id)
        tt.create_file([b"contents"], trans_id)
        tt.commit(branch, "message", strict=True)

    def test_commit_malformed(self):
        """Committing a malformed transform should raise an exception.

        In this case, we are adding a file without adding its parent.
        """
        branch, tt = self.get_branch_and_transform()
        parent_id = tt.trans_id_file_id(b"parent-id")
        tt.new_file("file", parent_id, [b"contents"], b"file-id")
        self.assertRaises(MalformedTransform, tt.commit, branch, "message")

    def test_commit_rich_revision_data(self):
        branch, tt = self.get_branch_and_transform()
        rev_id = tt.commit(
            branch,
            "message",
            timestamp=1,
            timezone=43201,
            committer="me <me@example.com>",
            revprops={"foo": "bar"},
            revision_id=b"revid-1",
            authors=[
                "Author1 <author1@example.com>",
                "Author2 <author2@example.com>",
            ],
        )
        self.assertEqual(b"revid-1", rev_id)
        revision = branch.repository.get_revision(rev_id)
        self.assertEqual(1, revision.timestamp)
        self.assertEqual(43201, revision.timezone)
        self.assertEqual("me <me@example.com>", revision.committer)
        self.assertEqual(
            ["Author1 <author1@example.com>", "Author2 <author2@example.com>"],
            revision.get_apparent_authors(),
        )
        del revision.properties["authors"]
        self.assertEqual({"foo": "bar", "branch-nick": "tree"}, revision.properties)

    def test_no_explicit_revprops(self):
        branch, tt = self.get_branch_and_transform()
        rev_id = tt.commit(
            branch,
            "message",
            authors=[
                "Author1 <author1@example.com>",
                "Author2 <author2@example.com>",
            ],
        )
        revision = branch.repository.get_revision(rev_id)
        self.assertEqual(
            ["Author1 <author1@example.com>", "Author2 <author2@example.com>"],
            revision.get_apparent_authors(),
        )
        self.assertEqual("tree", revision.properties["branch-nick"])


class TestFileMover(tests.TestCaseWithTransport):
    def test_file_mover(self):
        self.build_tree(["a/", "a/b", "c/", "c/d"])
        mover = _FileMover()
        mover.rename("a", "q")
        self.assertPathExists("q")
        self.assertPathDoesNotExist("a")
        self.assertPathExists("q/b")
        self.assertPathExists("c")
        self.assertPathExists("c/d")

    def test_pre_delete_rollback(self):
        self.build_tree(["a/"])
        mover = _FileMover()
        mover.pre_delete("a", "q")
        self.assertPathExists("q")
        self.assertPathDoesNotExist("a")
        mover.rollback()
        self.assertPathDoesNotExist("q")
        self.assertPathExists("a")

    def test_apply_deletions(self):
        self.build_tree(["a/", "b/"])
        mover = _FileMover()
        mover.pre_delete("a", "q")
        mover.pre_delete("b", "r")
        self.assertPathExists("q")
        self.assertPathExists("r")
        self.assertPathDoesNotExist("a")
        self.assertPathDoesNotExist("b")
        mover.apply_deletions()
        self.assertPathDoesNotExist("q")
        self.assertPathDoesNotExist("r")
        self.assertPathDoesNotExist("a")
        self.assertPathDoesNotExist("b")

    def test_file_mover_rollback(self):
        self.build_tree(["a/", "a/b", "c/", "c/d/", "c/e/"])
        mover = _FileMover()
        mover.rename("c/d", "c/f")
        mover.rename("c/e", "c/d")
        try:
            mover.rename("a", "c")
        except FileExists:
            mover.rollback()
        self.assertPathExists("a")
        self.assertPathExists("c/d")


class Bogus(Exception):
    pass


class TestTransformRollback(tests.TestCaseWithTransport):
    class ExceptionFileMover(_FileMover):
        def __init__(self, bad_source=None, bad_target=None):
            _FileMover.__init__(self)
            self.bad_source = bad_source
            self.bad_target = bad_target

        def rename(self, source, target):
            if self.bad_source is not None and source.endswith(self.bad_source):
                raise Bogus
            elif self.bad_target is not None and target.endswith(self.bad_target):
                raise Bogus
            else:
                _FileMover.rename(self, source, target)

    def test_rollback_rename(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree(["a/", "a/b"])
        tt = tree.transform()
        self.addCleanup(tt.finalize)
        a_id = tt.trans_id_tree_path("a")
        tt.adjust_path("c", tt.root, a_id)
        tt.adjust_path("d", a_id, tt.trans_id_tree_path("a/b"))
        self.assertRaises(
            Bogus, tt.apply, _mover=self.ExceptionFileMover(bad_source="a")
        )
        self.assertPathExists("a")
        self.assertPathExists("a/b")
        tt.apply()
        self.assertPathExists("c")
        self.assertPathExists("c/d")

    def test_rollback_rename_into_place(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree(["a/", "a/b"])
        tt = tree.transform()
        self.addCleanup(tt.finalize)
        a_id = tt.trans_id_tree_path("a")
        tt.adjust_path("c", tt.root, a_id)
        tt.adjust_path("d", a_id, tt.trans_id_tree_path("a/b"))
        self.assertRaises(
            Bogus, tt.apply, _mover=self.ExceptionFileMover(bad_target="c/d")
        )
        self.assertPathExists("a")
        self.assertPathExists("a/b")
        tt.apply()
        self.assertPathExists("c")
        self.assertPathExists("c/d")

    def test_rollback_deletion(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree(["a/", "a/b"])
        tt = tree.transform()
        self.addCleanup(tt.finalize)
        a_id = tt.trans_id_tree_path("a")
        tt.delete_contents(a_id)
        tt.adjust_path("d", tt.root, tt.trans_id_tree_path("a/b"))
        self.assertRaises(
            Bogus, tt.apply, _mover=self.ExceptionFileMover(bad_target="d")
        )
        self.assertPathExists("a")
        self.assertPathExists("a/b")


class TestFinalizeRobustness(tests.TestCaseWithTransport):
    """Ensure treetransform creation errors can be safely cleaned up after."""

    def _override_globals_in_method(self, instance, method_name, globals):
        """Replace method on instance with one with updated globals."""
        import types

        func = getattr(instance, method_name).__func__
        new_globals = dict(func.__globals__)
        new_globals.update(globals)
        new_func = types.FunctionType(
            func.__code__, new_globals, func.__name__, func.__defaults__
        )
        setattr(instance, method_name, types.MethodType(new_func, instance))
        self.addCleanup(delattr, instance, method_name)

    @staticmethod
    def _fake_open_raises_before(name, mode):
        """Like open() but raises before doing anything."""
        raise RuntimeError

    @staticmethod
    def _fake_open_raises_after(name, mode):
        """Like open() but raises after creating file without returning."""
        open(name, mode).close()
        raise RuntimeError

    def create_transform_and_root_trans_id(self):
        """Setup a transform creating a file in limbo."""
        tree = self.make_branch_and_tree(".")
        tt = tree.transform()
        return tt, tt.create_path("a", tt.root)

    def create_transform_and_subdir_trans_id(self):
        """Setup a transform creating a directory containing a file in limbo."""
        tree = self.make_branch_and_tree(".")
        tt = tree.transform()
        d_trans_id = tt.create_path("d", tt.root)
        tt.create_directory(d_trans_id)
        f_trans_id = tt.create_path("a", d_trans_id)
        tt.adjust_path("a", d_trans_id, f_trans_id)
        return tt, f_trans_id

    def test_root_create_file_open_raises_before_creation(self):
        tt, trans_id = self.create_transform_and_root_trans_id()
        self._override_globals_in_method(
            tt, "create_file", {"open": self._fake_open_raises_before}
        )
        self.assertRaises(RuntimeError, tt.create_file, [b"contents"], trans_id)
        path = tt._limbo_name(trans_id)
        self.assertPathDoesNotExist(path)
        tt.finalize()
        self.assertPathDoesNotExist(tt._limbodir)

    def test_root_create_file_open_raises_after_creation(self):
        tt, trans_id = self.create_transform_and_root_trans_id()
        self._override_globals_in_method(
            tt, "create_file", {"open": self._fake_open_raises_after}
        )
        self.assertRaises(RuntimeError, tt.create_file, [b"contents"], trans_id)
        path = tt._limbo_name(trans_id)
        self.assertPathExists(path)
        tt.finalize()
        self.assertPathDoesNotExist(path)
        self.assertPathDoesNotExist(tt._limbodir)

    def test_subdir_create_file_open_raises_before_creation(self):
        tt, trans_id = self.create_transform_and_subdir_trans_id()
        self._override_globals_in_method(
            tt, "create_file", {"open": self._fake_open_raises_before}
        )
        self.assertRaises(RuntimeError, tt.create_file, [b"contents"], trans_id)
        path = tt._limbo_name(trans_id)
        self.assertPathDoesNotExist(path)
        tt.finalize()
        self.assertPathDoesNotExist(tt._limbodir)

    def test_subdir_create_file_open_raises_after_creation(self):
        tt, trans_id = self.create_transform_and_subdir_trans_id()
        self._override_globals_in_method(
            tt, "create_file", {"open": self._fake_open_raises_after}
        )
        self.assertRaises(RuntimeError, tt.create_file, [b"contents"], trans_id)
        path = tt._limbo_name(trans_id)
        self.assertPathExists(path)
        tt.finalize()
        self.assertPathDoesNotExist(path)
        self.assertPathDoesNotExist(tt._limbodir)

    def test_rename_in_limbo_rename_raises_after_rename(self):
        tt, trans_id = self.create_transform_and_root_trans_id()
        parent1 = tt.new_directory("parent1", tt.root)
        child1 = tt.new_file("child1", parent1, [b"contents"])
        parent2 = tt.new_directory("parent2", tt.root)

        class FakeOSModule:
            def rename(self, old, new):
                os.rename(old, new)
                raise RuntimeError

        self._override_globals_in_method(tt, "_rename_in_limbo", {"os": FakeOSModule()})
        self.assertRaises(RuntimeError, tt.adjust_path, "child1", parent2, child1)
        path = osutils.pathjoin(tt._limbo_name(parent2), "child1")
        self.assertPathExists(path)
        tt.finalize()
        self.assertPathDoesNotExist(path)
        self.assertPathDoesNotExist(tt._limbodir)

    def test_rename_in_limbo_rename_raises_before_rename(self):
        tt, trans_id = self.create_transform_and_root_trans_id()
        parent1 = tt.new_directory("parent1", tt.root)
        child1 = tt.new_file("child1", parent1, [b"contents"])
        parent2 = tt.new_directory("parent2", tt.root)

        class FakeOSModule:
            def rename(self, old, new):
                raise RuntimeError

        self._override_globals_in_method(tt, "_rename_in_limbo", {"os": FakeOSModule()})
        self.assertRaises(RuntimeError, tt.adjust_path, "child1", parent2, child1)
        path = osutils.pathjoin(tt._limbo_name(parent1), "child1")
        self.assertPathExists(path)
        tt.finalize()
        self.assertPathDoesNotExist(path)
        self.assertPathDoesNotExist(tt._limbodir)


class TestTransformMissingParent(tests.TestCaseWithTransport):
    def make_tt_with_versioned_dir(self):
        wt = self.make_branch_and_tree(".")
        self.build_tree(
            [
                "dir/",
            ]
        )
        wt.add(["dir"], ids=[b"dir-id"])
        wt.commit("Create dir")
        tt = wt.transform()
        self.addCleanup(tt.finalize)
        return wt, tt

    def test_resolve_create_parent_for_versioned_file(self):
        wt, tt = self.make_tt_with_versioned_dir()
        dir_tid = tt.trans_id_tree_path("dir")
        tt.new_file("file", dir_tid, [b"Contents"], file_id=b"file-id")
        tt.delete_contents(dir_tid)
        tt.unversion_file(dir_tid)
        conflicts = resolve_conflicts(tt)
        # one conflict for the missing directory, one for the unversioned
        # parent
        self.assertLength(2, conflicts)

    def test_non_versioned_file_create_conflict(self):
        wt, tt = self.make_tt_with_versioned_dir()
        dir_tid = tt.trans_id_tree_path("dir")
        tt.new_file("file", dir_tid, [b"Contents"])
        tt.delete_contents(dir_tid)
        tt.unversion_file(dir_tid)
        conflicts = resolve_conflicts(tt)
        # no conflicts or rather: orphaning 'file' resolve the 'dir' conflict
        self.assertLength(1, conflicts)
        self.assertEqual(("deleting parent", "Not deleting", "new-1"), conflicts.pop())


class FakeSerializer:
    """Serializer implementation that simply returns the input.

    The input is returned in the order used by pack.ContainerPushParser.
    """

    @staticmethod
    def bytes_record(bytes, names):
        return names, bytes


class TestSerializeTransform(tests.TestCaseWithTransport):
    _test_needs_features = [features.UnicodeFilenameFeature]

    def get_preview(self, tree=None):
        if tree is None:
            tree = self.make_branch_and_tree("tree")
        tt = tree.preview_transform()
        self.addCleanup(tt.finalize)
        return tt

    def assertSerializesTo(self, expected, tt):
        records = list(tt.serialize(FakeSerializer()))
        self.assertEqual(expected, records)

    @staticmethod
    def default_attribs():
        return {
            b"_id_number": 1,
            b"_new_name": {},
            b"_new_parent": {},
            b"_new_executability": {},
            b"_new_id": {},
            b"_tree_path_ids": {b"": b"new-0"},
            b"_removed_id": [],
            b"_removed_contents": [],
            b"_non_present_ids": {},
        }

    def make_records(self, attribs, contents):
        records = [((((b"attribs"),),), bencode.bencode(attribs))]
        records.extend([(((n, k),), c) for n, k, c in contents])
        return records

    def creation_records(self):
        attribs = self.default_attribs()
        attribs[b"_id_number"] = 3
        attribs[b"_new_name"] = {b"new-1": "foo\u1234".encode(), b"new-2": b"qux"}
        attribs[b"_new_id"] = {b"new-1": b"baz", b"new-2": b"quxx"}
        attribs[b"_new_parent"] = {b"new-1": b"new-0", b"new-2": b"new-0"}
        attribs[b"_new_executability"] = {b"new-1": 1}
        contents = [
            (b"new-1", b"file", b"i 1\nbar\n"),
            (b"new-2", b"directory", b""),
        ]
        return self.make_records(attribs, contents)

    def test_serialize_creation(self):
        tt = self.get_preview()
        tt.new_file("foo\u1234", tt.root, [b"bar"], b"baz", True)
        tt.new_directory("qux", tt.root, b"quxx")
        self.assertSerializesTo(self.creation_records(), tt)

    def test_deserialize_creation(self):
        tt = self.get_preview()
        tt.deserialize(iter(self.creation_records()))
        self.assertEqual(3, tt._id_number)
        self.assertEqual({"new-1": "foo\u1234", "new-2": "qux"}, tt._new_name)
        self.assertEqual({"new-1": b"baz", "new-2": b"quxx"}, tt._new_id)
        self.assertEqual({"new-1": tt.root, "new-2": tt.root}, tt._new_parent)
        self.assertEqual({b"baz": "new-1", b"quxx": "new-2"}, tt._r_new_id)
        self.assertEqual({"new-1": True}, tt._new_executability)
        self.assertEqual({"new-1": "file", "new-2": "directory"}, tt._new_contents)
        with open(tt._limbo_name("new-1"), "rb") as foo_limbo:
            foo_content = foo_limbo.read()
        self.assertEqual(b"bar", foo_content)

    def symlink_creation_records(self):
        attribs = self.default_attribs()
        attribs[b"_id_number"] = 2
        attribs[b"_new_name"] = {b"new-1": "foo\u1234".encode()}
        attribs[b"_new_parent"] = {b"new-1": b"new-0"}
        contents = [(b"new-1", b"symlink", "bar\u1234".encode())]
        return self.make_records(attribs, contents)

    def test_serialize_symlink_creation(self):
        self.requireFeature(features.SymlinkFeature(self.test_dir))
        tt = self.get_preview()
        tt.new_symlink("foo\u1234", tt.root, "bar\u1234")
        self.assertSerializesTo(self.symlink_creation_records(), tt)

    def test_deserialize_symlink_creation(self):
        self.requireFeature(features.SymlinkFeature(self.test_dir))
        tt = self.get_preview()
        tt.deserialize(iter(self.symlink_creation_records()))
        abspath = tt._limbo_name("new-1")
        foo_content = osutils.readlink(abspath)
        self.assertEqual("bar\u1234", foo_content)

    def make_destruction_preview(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree(["foo\u1234", "bar"])
        tree.add(["foo\u1234", "bar"], ids=[b"foo-id", b"bar-id"])
        return self.get_preview(tree)

    def destruction_records(self):
        attribs = self.default_attribs()
        attribs[b"_id_number"] = 3
        attribs[b"_removed_id"] = [b"new-1"]
        attribs[b"_removed_contents"] = [b"new-2"]
        attribs[b"_tree_path_ids"] = {
            b"": b"new-0",
            "foo\u1234".encode(): b"new-1",
            b"bar": b"new-2",
        }
        return self.make_records(attribs, [])

    def test_serialize_destruction(self):
        tt = self.make_destruction_preview()
        foo_trans_id = tt.trans_id_tree_path("foo\u1234")
        tt.unversion_file(foo_trans_id)
        bar_trans_id = tt.trans_id_tree_path("bar")
        tt.delete_contents(bar_trans_id)
        self.assertSerializesTo(self.destruction_records(), tt)

    def test_deserialize_destruction(self):
        tt = self.make_destruction_preview()
        tt.deserialize(iter(self.destruction_records()))
        self.assertEqual(
            {"foo\u1234": "new-1", "bar": "new-2", "": tt.root}, tt._tree_path_ids
        )
        self.assertEqual(
            {"new-1": "foo\u1234", "new-2": "bar", tt.root: ""}, tt._tree_id_paths
        )
        self.assertEqual({"new-1"}, tt._removed_id)
        self.assertEqual({"new-2"}, tt._removed_contents)

    def missing_records(self):
        attribs = self.default_attribs()
        attribs[b"_id_number"] = 2
        attribs[b"_non_present_ids"] = {
            b"boo": b"new-1",
        }
        return self.make_records(attribs, [])

    def test_serialize_missing(self):
        tt = self.get_preview()
        tt.trans_id_file_id(b"boo")
        self.assertSerializesTo(self.missing_records(), tt)

    def test_deserialize_missing(self):
        tt = self.get_preview()
        tt.deserialize(iter(self.missing_records()))
        self.assertEqual({b"boo": "new-1"}, tt._non_present_ids)

    def make_modification_preview(self):
        LINES_ONE = b"aa\nbb\ncc\ndd\n"
        LINES_TWO = b"z\nbb\nx\ndd\n"
        tree = self.make_branch_and_tree("tree")
        self.build_tree_contents([("tree/file", LINES_ONE)])
        tree.add("file", ids=b"file-id")
        return self.get_preview(tree), [LINES_TWO]

    def modification_records(self):
        attribs = self.default_attribs()
        attribs[b"_id_number"] = 2
        attribs[b"_tree_path_ids"] = {
            b"file": b"new-1",
            b"": b"new-0",
        }
        attribs[b"_removed_contents"] = [b"new-1"]
        contents = [(b"new-1", b"file", b"i 1\nz\n\nc 0 1 1 1\ni 1\nx\n\nc 0 3 3 1\n")]
        return self.make_records(attribs, contents)

    def test_serialize_modification(self):
        tt, LINES = self.make_modification_preview()
        trans_id = tt.trans_id_file_id(b"file-id")
        tt.delete_contents(trans_id)
        tt.create_file(LINES, trans_id)
        self.assertSerializesTo(self.modification_records(), tt)

    def test_deserialize_modification(self):
        tt, LINES = self.make_modification_preview()
        tt.deserialize(iter(self.modification_records()))
        self.assertFileEqual(b"".join(LINES), tt._limbo_name("new-1"))

    def make_kind_change_preview(self):
        LINES = b"a\nb\nc\nd\n"
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/foo/"])
        tree.add("foo", ids=b"foo-id")
        return self.get_preview(tree), [LINES]

    def kind_change_records(self):
        attribs = self.default_attribs()
        attribs[b"_id_number"] = 2
        attribs[b"_tree_path_ids"] = {
            b"foo": b"new-1",
            b"": b"new-0",
        }
        attribs[b"_removed_contents"] = [b"new-1"]
        contents = [(b"new-1", b"file", b"i 4\na\nb\nc\nd\n\n")]
        return self.make_records(attribs, contents)

    def test_serialize_kind_change(self):
        tt, LINES = self.make_kind_change_preview()
        trans_id = tt.trans_id_file_id(b"foo-id")
        tt.delete_contents(trans_id)
        tt.create_file(LINES, trans_id)
        self.assertSerializesTo(self.kind_change_records(), tt)

    def test_deserialize_kind_change(self):
        tt, LINES = self.make_kind_change_preview()
        tt.deserialize(iter(self.kind_change_records()))
        self.assertFileEqual(b"".join(LINES), tt._limbo_name("new-1"))

    def make_add_contents_preview(self):
        LINES = b"a\nb\nc\nd\n"
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/foo"])
        tree.add("foo")
        os.unlink("tree/foo")
        return self.get_preview(tree), LINES

    def add_contents_records(self):
        attribs = self.default_attribs()
        attribs[b"_id_number"] = 2
        attribs[b"_tree_path_ids"] = {
            b"foo": b"new-1",
            b"": b"new-0",
        }
        contents = [(b"new-1", b"file", b"i 4\na\nb\nc\nd\n\n")]
        return self.make_records(attribs, contents)

    def test_serialize_add_contents(self):
        tt, LINES = self.make_add_contents_preview()
        trans_id = tt.trans_id_tree_path("foo")
        tt.create_file([LINES], trans_id)
        self.assertSerializesTo(self.add_contents_records(), tt)

    def test_deserialize_add_contents(self):
        tt, LINES = self.make_add_contents_preview()
        tt.deserialize(iter(self.add_contents_records()))
        self.assertFileEqual(LINES, tt._limbo_name("new-1"))

    def test_get_parents_lines(self):
        LINES_ONE = b"aa\nbb\ncc\ndd\n"
        tree = self.make_branch_and_tree("tree")
        self.build_tree_contents([("tree/file", LINES_ONE)])
        tree.add("file", ids=b"file-id")
        tt = self.get_preview(tree)
        trans_id = tt.trans_id_tree_path("file")
        self.assertEqual(
            ([b"aa\n", b"bb\n", b"cc\n", b"dd\n"],), tt._get_parents_lines(trans_id)
        )

    def test_get_parents_texts(self):
        LINES_ONE = b"aa\nbb\ncc\ndd\n"
        tree = self.make_branch_and_tree("tree")
        self.build_tree_contents([("tree/file", LINES_ONE)])
        tree.add("file", ids=b"file-id")
        tt = self.get_preview(tree)
        trans_id = tt.trans_id_tree_path("file")
        self.assertEqual((LINES_ONE,), tt._get_parents_texts(trans_id))


class TestOrphan(tests.TestCaseWithTransport):
    def test_no_orphan_for_transform_preview(self):
        tree = self.make_branch_and_tree("tree")
        tt = tree.preview_transform()
        self.addCleanup(tt.finalize)
        self.assertRaises(NotImplementedError, tt.new_orphan, "foo", "bar")

    def _set_orphan_policy(self, wt, policy):
        wt.branch.get_config_stack().set("transform.orphan_policy", policy)

    def _prepare_orphan(self, wt):
        self.build_tree(["dir/", "dir/file", "dir/foo"])
        wt.add(["dir", "dir/file"], ids=[b"dir-id", b"file-id"])
        wt.commit("add dir and file ignoring foo")
        tt = wt.transform()
        self.addCleanup(tt.finalize)
        # dir and bar are deleted
        dir_tid = tt.trans_id_tree_path("dir")
        file_tid = tt.trans_id_tree_path("dir/file")
        orphan_tid = tt.trans_id_tree_path("dir/foo")
        tt.delete_contents(file_tid)
        tt.unversion_file(file_tid)
        tt.delete_contents(dir_tid)
        tt.unversion_file(dir_tid)
        # There should be a conflict because dir still contain foo
        raw_conflicts = tt.find_raw_conflicts()
        self.assertLength(1, raw_conflicts)
        self.assertEqual(("missing parent", "new-1"), raw_conflicts[0])
        return tt, orphan_tid

    def test_new_orphan_created(self):
        wt = self.make_branch_and_tree(".")
        self._set_orphan_policy(wt, "move")
        tt, orphan_tid = self._prepare_orphan(wt)
        warnings = []

        def warning(*args):
            warnings.append(args[0] % args[1:])

        self.overrideAttr(trace, "warning", warning)
        remaining_conflicts = resolve_conflicts(tt)
        self.assertEqual(["dir/foo has been orphaned in brz-orphans"], warnings)
        # Yeah for resolved conflicts !
        self.assertLength(0, remaining_conflicts)
        # We have a new orphan
        self.assertEqual("foo.~1~", tt.final_name(orphan_tid))
        self.assertEqual("brz-orphans", tt.final_name(tt.final_parent(orphan_tid)))

    def test_never_orphan(self):
        wt = self.make_branch_and_tree(".")
        self._set_orphan_policy(wt, "conflict")
        tt, orphan_tid = self._prepare_orphan(wt)
        remaining_conflicts = resolve_conflicts(tt)
        self.assertLength(1, remaining_conflicts)
        self.assertEqual(
            ("deleting parent", "Not deleting", "new-1"), remaining_conflicts.pop()
        )

    def test_orphan_error(self):
        def bogus_orphan(tt, orphan_id, parent_id):
            raise transform.OrphaningError(
                tt.final_name(orphan_id), tt.final_name(parent_id)
            )

        transform.orphaning_registry.register(
            "bogus", bogus_orphan, "Raise an error when orphaning"
        )
        wt = self.make_branch_and_tree(".")
        self._set_orphan_policy(wt, "bogus")
        tt, orphan_tid = self._prepare_orphan(wt)
        remaining_conflicts = resolve_conflicts(tt)
        self.assertLength(1, remaining_conflicts)
        self.assertEqual(
            ("deleting parent", "Not deleting", "new-1"), remaining_conflicts.pop()
        )

    def test_unknown_orphan_policy(self):
        wt = self.make_branch_and_tree(".")
        # Set a fictional policy nobody ever implemented
        self._set_orphan_policy(wt, "donttouchmypreciouuus")
        tt, orphan_tid = self._prepare_orphan(wt)
        warnings = []

        def warning(*args):
            warnings.append(args[0] % args[1:])

        self.overrideAttr(trace, "warning", warning)
        remaining_conflicts = resolve_conflicts(tt)
        # We fallback to the default policy which create a conflict
        self.assertLength(1, remaining_conflicts)
        self.assertEqual(
            ("deleting parent", "Not deleting", "new-1"), remaining_conflicts.pop()
        )
        self.assertLength(1, warnings)
        self.assertStartsWith(warnings[0], 'Value "donttouchmypreciouuus" ')


class TestTransformHooks(tests.TestCaseWithTransport):
    def setUp(self):
        super().setUp()
        self.wt = self.make_branch_and_tree(".")
        os.chdir("..")

    def transform(self):
        transform = self.wt.transform()
        self.addCleanup(transform.finalize)
        return transform, transform.root

    def test_pre_commit_hooks(self):
        calls = []

        def record_pre_transform(tree, tt):
            calls.append((tree, tt))

        MutableTree.hooks.install_named_hook(
            "pre_transform", record_pre_transform, "Pre transform"
        )
        transform, root = self.transform()
        old_root_id = transform.tree_file_id(root)
        transform.apply()
        self.assertEqual(old_root_id, self.wt.path2id(""))
        self.assertEqual([(self.wt, transform)], calls)

    def test_post_commit_hooks(self):
        calls = []

        def record_post_transform(tree, tt):
            calls.append((tree, tt))

        MutableTree.hooks.install_named_hook(
            "post_transform", record_post_transform, "Post transform"
        )
        transform, root = self.transform()
        old_root_id = transform.tree_file_id(root)
        transform.apply()
        self.assertEqual(old_root_id, self.wt.path2id(""))
        self.assertEqual([(self.wt, transform)], calls)


class TestLinkTree(tests.TestCaseWithTransport):
    def setUp(self):
        tests.TestCaseWithTransport.setUp(self)
        self.requireFeature(HardlinkFeature(self.test_dir))
        self.parent_tree = self.make_branch_and_tree("parent")
        self.parent_tree.lock_write()
        self.addCleanup(self.parent_tree.unlock)
        self.build_tree_contents([("parent/foo", b"bar")])
        self.parent_tree.add("foo")
        self.parent_tree.commit("added foo")
        child_controldir = self.parent_tree.controldir.sprout("child")
        self.child_tree = child_controldir.open_workingtree()

    def hardlinked(self):
        parent_stat = os.lstat(self.parent_tree.abspath("foo"))
        child_stat = os.lstat(self.child_tree.abspath("foo"))
        return parent_stat.st_ino == child_stat.st_ino

    def test_link_fails_if_modified(self):
        """If the file to be linked has modified text, don't link."""
        self.build_tree_contents([("child/foo", b"baz")])
        transform.link_tree(self.child_tree, self.parent_tree)
        self.assertFalse(self.hardlinked())

    def test_link_fails_if_execute_bit_changed(self):
        """If the file to be linked has modified execute bit, don't link."""
        tt = self.child_tree.transform()
        try:
            trans_id = tt.trans_id_tree_path("foo")
            tt.set_executability(True, trans_id)
            tt.apply()
        finally:
            tt.finalize()
        transform.link_tree(self.child_tree, self.parent_tree)
        self.assertFalse(self.hardlinked())

    def test_link_succeeds_if_unmodified(self):
        """If the file to be linked is unmodified, link."""
        transform.link_tree(self.child_tree, self.parent_tree)
        self.assertTrue(self.hardlinked())


class ErrorTests(tests.TestCase):
    def test_transform_rename_failed(self):
        e = TransformRenameFailed("from", "to", "readonly file", 2)
        self.assertEqual("Failed to rename from to to: readonly file", str(e))
