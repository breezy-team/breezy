# Copyright (C) 2005-2012, 2016 Canonical Ltd
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
from io import BytesIO

import breezy

from .. import config, controldir, errors, osutils, trace
from .. import transport as _mod_transport
from ..branch import Branch
from ..bzr.bzrdir import BzrDirMetaFormat1
from ..commit import (
    CannotCommitSelectedFileMerge,
    Commit,
    NullCommitReporter,
    PointlessCommit,
    filter_excluded,
)
from ..errors import BzrError, LockContention
from ..tree import TreeChange
from . import TestCase, TestCaseWithTransport, test_foreign
from .features import SymlinkFeature
from .matchers import MatchesAncestry

# TODO: Test commit with some added, and added-but-missing files


class MustSignConfig(config.MemoryStack):
    def __init__(self):
        super().__init__(
            b"""
create_signatures=always
"""
        )


class CapturingReporter(NullCommitReporter):
    """This reporter captures the calls made to it for evaluation later."""

    def __init__(self):
        # a list of the calls this received
        self.calls = []

    def snapshot_change(self, change, path):
        self.calls.append(("change", change, path))

    def deleted(self, file_id):
        self.calls.append(("deleted", file_id))

    def missing(self, path):
        self.calls.append(("missing", path))

    def renamed(self, change, old_path, new_path):
        self.calls.append(("renamed", change, old_path, new_path))

    def is_verbose(self):
        return True


class TestCommit(TestCaseWithTransport):
    def test_simple_commit(self):
        """Commit and check two versions of a single file."""
        wt = self.make_branch_and_tree(".")
        b = wt.branch
        with open("hello", "w") as f:
            f.write("hello world")
        wt.add("hello")
        rev1 = wt.commit(message="add hello")

        with open("hello", "w") as f:
            f.write("version 2")
        rev2 = wt.commit(message="commit 2")

        eq = self.assertEqual
        eq(b.revno(), 2)
        rev = b.repository.get_revision(rev1)
        eq(rev.message, "add hello")

        tree1 = b.repository.revision_tree(rev1)
        tree1.lock_read()
        text = tree1.get_file_text("hello")
        tree1.unlock()
        self.assertEqual(b"hello world", text)

        tree2 = b.repository.revision_tree(rev2)
        tree2.lock_read()
        text = tree2.get_file_text("hello")
        tree2.unlock()
        self.assertEqual(b"version 2", text)

    def test_commit_lossy_native(self):
        """Attempt a lossy commit to a native branch."""
        wt = self.make_branch_and_tree(".")
        with open("hello", "w") as f:
            f.write("hello world")
        wt.add("hello")
        revid = wt.commit(message="add hello", rev_id=b"revid", lossy=True)
        self.assertEqual(b"revid", revid)

    def test_commit_lossy_foreign(self):
        """Attempt a lossy commit to a foreign branch."""
        test_foreign.register_dummy_foreign_for_test(self)
        wt = self.make_branch_and_tree(
            ".", format=test_foreign.DummyForeignVcsDirFormat()
        )
        with open("hello", "w") as f:
            f.write("hello world")
        wt.add("hello")
        revid = wt.commit(
            message="add hello", lossy=True, timestamp=1302659388, timezone=0
        )
        self.assertEqual(b"dummy-v1:1302659388-0-UNKNOWN", revid)

    def test_commit_bound_lossy_foreign(self):
        """Attempt a lossy commit to a bzr branch bound to a foreign branch."""
        test_foreign.register_dummy_foreign_for_test(self)
        foreign_branch = self.make_branch(
            "foreign", format=test_foreign.DummyForeignVcsDirFormat()
        )
        wt = foreign_branch.create_checkout("local")
        with open("local/hello", "w") as f:
            f.write("hello world")
        wt.add("hello")
        revid = wt.commit(
            message="add hello", lossy=True, timestamp=1302659388, timezone=0
        )
        self.assertEqual(b"dummy-v1:1302659388-0-0", revid)
        self.assertEqual(b"dummy-v1:1302659388-0-0", foreign_branch.last_revision())
        self.assertEqual(b"dummy-v1:1302659388-0-0", wt.branch.last_revision())

    def test_missing_commit(self):
        """Test a commit with a missing file."""
        wt = self.make_branch_and_tree(".")
        b = wt.branch
        with open("hello", "w") as f:
            f.write("hello world")
        wt.add(["hello"], ids=[b"hello-id"])
        wt.commit(message="add hello")

        os.remove("hello")
        reporter = CapturingReporter()
        wt.commit("removed hello", rev_id=b"rev2", reporter=reporter)
        self.assertEqual([("missing", "hello"), ("deleted", "hello")], reporter.calls)

        tree = b.repository.revision_tree(b"rev2")
        self.assertFalse(tree.has_filename("hello"))

    def test_partial_commit_move(self):
        """Test a partial commit where a file was renamed but not committed.

        https://bugs.launchpad.net/bzr/+bug/83039

        If not handled properly, commit will try to snapshot
        dialog.py with olive/ as a parent, while
        olive/ has not been snapshotted yet.
        """
        wt = self.make_branch_and_tree(".")
        self.build_tree(["annotate/", "annotate/foo.py", "olive/", "olive/dialog.py"])
        wt.add(["annotate", "olive", "annotate/foo.py", "olive/dialog.py"])
        wt.commit(message="add files")
        wt.rename_one("olive/dialog.py", "aaa")
        self.build_tree_contents([("annotate/foo.py", b"modified\n")])
        wt.commit("renamed hello", specific_files=["annotate"])

    def test_pointless_commit(self):
        """Commit refuses unless there are changes or it's forced."""
        wt = self.make_branch_and_tree(".")
        b = wt.branch
        with open("hello", "w") as f:
            f.write("hello")
        wt.add(["hello"])
        wt.commit(message="add hello")
        self.assertEqual(b.revno(), 1)
        self.assertRaises(
            PointlessCommit, wt.commit, message="fails", allow_pointless=False
        )
        self.assertEqual(b.revno(), 1)

    def test_commit_empty(self):
        """Commiting an empty tree works."""
        wt = self.make_branch_and_tree(".")
        b = wt.branch
        wt.commit(message="empty tree", allow_pointless=True)
        self.assertRaises(
            PointlessCommit, wt.commit, message="empty tree", allow_pointless=False
        )
        wt.commit(message="empty tree", allow_pointless=True)
        self.assertEqual(b.revno(), 2)

    def test_selective_delete(self):
        """Selective commit in tree with deletions."""
        wt = self.make_branch_and_tree(".")
        b = wt.branch
        with open("hello", "w") as f:
            f.write("hello")
        with open("buongia", "w") as f:
            f.write("buongia")
        wt.add(["hello", "buongia"], ids=[b"hello-id", b"buongia-id"])
        wt.commit(message="add files", rev_id=b"test@rev-1")

        os.remove("hello")
        with open("buongia", "w") as f:
            f.write("new text")
        wt.commit(
            message="update text",
            specific_files=["buongia"],
            allow_pointless=False,
            rev_id=b"test@rev-2",
        )

        wt.commit(
            message="remove hello",
            specific_files=["hello"],
            allow_pointless=False,
            rev_id=b"test@rev-3",
        )

        eq = self.assertEqual
        eq(b.revno(), 3)

        tree2 = b.repository.revision_tree(b"test@rev-2")
        tree2.lock_read()
        self.addCleanup(tree2.unlock)
        self.assertTrue(tree2.has_filename("hello"))
        self.assertEqual(tree2.get_file_text("hello"), b"hello")
        self.assertEqual(tree2.get_file_text("buongia"), b"new text")

        tree3 = b.repository.revision_tree(b"test@rev-3")
        tree3.lock_read()
        self.addCleanup(tree3.unlock)
        self.assertFalse(tree3.has_filename("hello"))
        self.assertEqual(tree3.get_file_text("buongia"), b"new text")

    def test_commit_rename(self):
        """Test commit of a revision where a file is renamed."""
        tree = self.make_branch_and_tree(".")
        b = tree.branch
        self.build_tree(["hello"], line_endings="binary")
        tree.add(["hello"], ids=[b"hello-id"])
        tree.commit(message="one", rev_id=b"test@rev-1", allow_pointless=False)

        tree.rename_one("hello", "fruity")
        tree.commit(message="renamed", rev_id=b"test@rev-2", allow_pointless=False)

        eq = self.assertEqual
        tree1 = b.repository.revision_tree(b"test@rev-1")
        tree1.lock_read()
        self.addCleanup(tree1.unlock)
        eq(tree1.id2path(b"hello-id"), "hello")
        eq(tree1.get_file_text("hello"), b"contents of hello\n")
        self.assertFalse(tree1.has_filename("fruity"))
        self.check_tree_shape(tree1, ["hello"])
        eq(tree1.get_file_revision("hello"), b"test@rev-1")

        tree2 = b.repository.revision_tree(b"test@rev-2")
        tree2.lock_read()
        self.addCleanup(tree2.unlock)
        eq(tree2.id2path(b"hello-id"), "fruity")
        eq(tree2.get_file_text("fruity"), b"contents of hello\n")
        self.check_tree_shape(tree2, ["fruity"])
        eq(tree2.get_file_revision("fruity"), b"test@rev-2")

    def test_reused_rev_id(self):
        """Test that a revision id cannot be reused in a branch."""
        wt = self.make_branch_and_tree(".")
        wt.commit("initial", rev_id=b"test@rev-1", allow_pointless=True)
        self.assertRaises(
            Exception,
            wt.commit,
            message="reused id",
            rev_id=b"test@rev-1",
            allow_pointless=True,
        )

    def test_commit_move(self):
        """Test commit of revisions with moved files and directories."""
        eq = self.assertEqual
        wt = self.make_branch_and_tree(".")
        b = wt.branch
        r1 = b"test@rev-1"
        self.build_tree(["hello", "a/", "b/"])
        wt.add(["hello", "a", "b"], ids=[b"hello-id", b"a-id", b"b-id"])
        wt.commit("initial", rev_id=r1, allow_pointless=False)
        wt.move(["hello"], "a")
        r2 = b"test@rev-2"
        wt.commit("two", rev_id=r2, allow_pointless=False)
        wt.lock_read()
        try:
            self.check_tree_shape(wt, ["a/", "a/hello", "b/"])
        finally:
            wt.unlock()

        wt.move(["b"], "a")
        r3 = b"test@rev-3"
        wt.commit("three", rev_id=r3, allow_pointless=False)
        wt.lock_read()
        try:
            self.check_tree_shape(wt, ["a/", "a/hello", "a/b/"])
            self.check_tree_shape(
                b.repository.revision_tree(r3), ["a/", "a/hello", "a/b/"]
            )
        finally:
            wt.unlock()

        wt.move(["a/hello"], "a/b")
        r4 = b"test@rev-4"
        wt.commit("four", rev_id=r4, allow_pointless=False)
        wt.lock_read()
        try:
            self.check_tree_shape(wt, ["a/", "a/b/hello", "a/b/"])
        finally:
            wt.unlock()

        inv = b.repository.get_inventory(r4)
        eq(inv.get_entry(b"hello-id").revision, r4)
        eq(inv.get_entry(b"a-id").revision, r1)
        eq(inv.get_entry(b"b-id").revision, r3)

    def test_removed_commit(self):
        """Commit with a removed file."""
        wt = self.make_branch_and_tree(".")
        b = wt.branch
        with open("hello", "w") as f:
            f.write("hello world")
        wt.add(["hello"], ids=[b"hello-id"])
        wt.commit(message="add hello")
        wt.remove("hello")
        wt.commit("removed hello", rev_id=b"rev2")

        tree = b.repository.revision_tree(b"rev2")
        self.assertFalse(tree.has_filename("hello"))

    def test_committed_ancestry(self):
        """Test commit appends revisions to ancestry."""
        wt = self.make_branch_and_tree(".")
        b = wt.branch
        rev_ids = []
        for i in range(4):
            with open("hello", "w") as f:
                f.write((str(i) * 4) + "\n")
            if i == 0:
                wt.add(["hello"], ids=[b"hello-id"])
            rev_id = b"test@rev-%d" % (i + 1)
            rev_ids.append(rev_id)
            wt.commit(message="rev %d" % (i + 1), rev_id=rev_id)
        for i in range(4):
            self.assertThat(rev_ids[: i + 1], MatchesAncestry(b.repository, rev_ids[i]))

    def test_commit_new_subdir_child_selective(self):
        wt = self.make_branch_and_tree(".")
        b = wt.branch
        self.build_tree(["dir/", "dir/file1", "dir/file2"])
        wt.add(
            ["dir", "dir/file1", "dir/file2"], ids=[b"dirid", b"file1id", b"file2id"]
        )
        wt.commit("dir/file1", specific_files=["dir/file1"], rev_id=b"1")
        inv = b.repository.get_inventory(b"1")
        self.assertEqual(b"1", inv.get_entry(b"dirid").revision)
        self.assertEqual(b"1", inv.get_entry(b"file1id").revision)
        # FIXME: This should raise a KeyError I think, rbc20051006
        self.assertRaises(BzrError, inv.get_entry, b"file2id")

    def test_strict_commit(self):
        """Try and commit with unknown files and strict = True, should fail."""
        from ..errors import StrictCommitFailed

        wt = self.make_branch_and_tree(".")
        with open("hello", "w") as f:
            f.write("hello world")
        wt.add("hello")
        with open("goodbye", "w") as f:
            f.write("goodbye cruel world!")
        self.assertRaises(
            StrictCommitFailed,
            wt.commit,
            message="add hello but not goodbye",
            strict=True,
        )

    def test_strict_commit_without_unknowns(self):
        """Try and commit with no unknown files and strict = True,
        should work.
        """
        wt = self.make_branch_and_tree(".")
        with open("hello", "w") as f:
            f.write("hello world")
        wt.add("hello")
        wt.commit(message="add hello", strict=True)

    def test_nonstrict_commit(self):
        """Try and commit with unknown files and strict = False, should work."""
        wt = self.make_branch_and_tree(".")
        with open("hello", "w") as f:
            f.write("hello world")
        wt.add("hello")
        with open("goodbye", "w") as f:
            f.write("goodbye cruel world!")
        wt.commit(message="add hello but not goodbye", strict=False)

    def test_nonstrict_commit_without_unknowns(self):
        """Try and commit with no unknown files and strict = False,
        should work.
        """
        wt = self.make_branch_and_tree(".")
        with open("hello", "w") as f:
            f.write("hello world")
        wt.add("hello")
        wt.commit(message="add hello", strict=False)

    def test_signed_commit(self):
        import breezy.commit as commit
        import breezy.gpg

        oldstrategy = breezy.gpg.GPGStrategy
        wt = self.make_branch_and_tree(".")
        branch = wt.branch
        wt.commit("base", allow_pointless=True, rev_id=b"A")
        self.assertFalse(branch.repository.has_signature_for_revision_id(b"A"))
        try:
            from ..bzr.testament import Testament

            # monkey patch gpg signing mechanism
            breezy.gpg.GPGStrategy = breezy.gpg.LoopbackGPGStrategy
            conf = config.MemoryStack(
                b"""
create_signatures=always
"""
            )
            commit.Commit(config_stack=conf).commit(
                message="base", allow_pointless=True, rev_id=b"B", working_tree=wt
            )

            def sign(text):
                return breezy.gpg.LoopbackGPGStrategy(None).sign(
                    text, breezy.gpg.MODE_CLEAR
                )

            self.assertEqual(
                sign(Testament.from_revision(branch.repository, b"B").as_short_text()),
                branch.repository.get_signature_text(b"B"),
            )
        finally:
            breezy.gpg.GPGStrategy = oldstrategy

    def test_commit_failed_signature(self):
        import breezy.commit as commit
        import breezy.gpg

        oldstrategy = breezy.gpg.GPGStrategy
        wt = self.make_branch_and_tree(".")
        branch = wt.branch
        wt.commit("base", allow_pointless=True, rev_id=b"A")
        self.assertFalse(branch.repository.has_signature_for_revision_id(b"A"))
        try:
            # monkey patch gpg signing mechanism
            breezy.gpg.GPGStrategy = breezy.gpg.DisabledGPGStrategy
            conf = config.MemoryStack(
                b"""
create_signatures=always
"""
            )
            self.assertRaises(
                breezy.gpg.SigningFailed,
                commit.Commit(config_stack=conf).commit,
                message="base",
                allow_pointless=True,
                rev_id=b"B",
                working_tree=wt,
            )
            branch = Branch.open(self.get_url("."))
            self.assertEqual(branch.last_revision(), b"A")
            self.assertFalse(branch.repository.has_revision(b"B"))
        finally:
            breezy.gpg.GPGStrategy = oldstrategy

    def test_commit_failed_signature_optional(self):
        import breezy.commit as commit
        import breezy.gpg

        oldstrategy = breezy.gpg.GPGStrategy
        wt = self.make_branch_and_tree(".")
        branch = wt.branch
        base_revid = wt.commit("base", allow_pointless=True)
        self.assertFalse(branch.repository.has_signature_for_revision_id(base_revid))
        try:
            # monkey patch gpg signing mechanism
            breezy.gpg.GPGStrategy = breezy.gpg.DisabledGPGStrategy
            conf = config.MemoryStack(
                b"""
create_signatures=when-possible
"""
            )
            revid = commit.Commit(config_stack=conf).commit(
                message="base", allow_pointless=True, working_tree=wt
            )
            branch = Branch.open(self.get_url("."))
            self.assertEqual(branch.last_revision(), revid)
        finally:
            breezy.gpg.GPGStrategy = oldstrategy

    def test_commit_invokes_hooks(self):
        import breezy.commit as commit

        wt = self.make_branch_and_tree(".")
        calls = []

        def called(branch, rev_id):
            calls.append("called")

        breezy.ahook = called
        try:
            conf = config.MemoryStack(b"post_commit=breezy.ahook breezy.ahook")
            commit.Commit(config_stack=conf).commit(
                message="base", allow_pointless=True, rev_id=b"A", working_tree=wt
            )
            self.assertEqual(["called", "called"], calls)
        finally:
            del breezy.ahook

    def test_commit_object_doesnt_set_nick(self):
        # using the Commit object directly does not set the branch nick.
        wt = self.make_branch_and_tree(".")
        c = Commit()
        c.commit(working_tree=wt, message="empty tree", allow_pointless=True)
        self.assertEqual(wt.branch.revno(), 1)
        self.assertEqual(
            {}, wt.branch.repository.get_revision(wt.branch.last_revision()).properties
        )

    def test_safe_master_lock(self):
        os.mkdir("master")
        master = BzrDirMetaFormat1().initialize("master")
        master.create_repository()
        master_branch = master.create_branch()
        master.create_workingtree()
        bound = master.sprout("bound")
        wt = bound.open_workingtree()
        wt.branch.set_bound_location(os.path.realpath("master"))
        with master_branch.lock_write():
            self.assertRaises(LockContention, wt.commit, "silly")

    def test_commit_bound_merge(self):
        # see bug #43959; commit of a merge in a bound branch fails to push
        # the new commit into the master
        master_branch = self.make_branch("master")
        bound_tree = self.make_branch_and_tree("bound")
        bound_tree.branch.bind(master_branch)

        self.build_tree_contents([("bound/content_file", b"initial contents\n")])
        bound_tree.add(["content_file"])
        bound_tree.commit(message="woo!")

        other_bzrdir = master_branch.controldir.sprout("other")
        other_tree = other_bzrdir.open_workingtree()

        # do a commit to the other branch changing the content file so
        # that our commit after merging will have a merged revision in the
        # content file history.
        self.build_tree_contents([("other/content_file", b"change in other\n")])
        other_tree.commit("change in other")

        # do a merge into the bound branch from other, and then change the
        # content file locally to force a new revision (rather than using the
        # revision from other). This forces extra processing in commit.
        bound_tree.merge_from_branch(other_tree.branch)
        self.build_tree_contents([("bound/content_file", b"change in bound\n")])

        # before #34959 was fixed, this failed with 'revision not present in
        # weave' when trying to implicitly push from the bound branch to the master
        bound_tree.commit(message="commit of merge in bound tree")

    def test_commit_reporting_after_merge(self):
        # when doing a commit of a merge, the reporter needs to still
        # be called for each item that is added/removed/deleted.
        this_tree = self.make_branch_and_tree("this")
        # we need a bunch of files and dirs, to perform one action on each.
        self.build_tree(
            [
                "this/dirtorename/",
                "this/dirtoreparent/",
                "this/dirtoleave/",
                "this/dirtoremove/",
                "this/filetoreparent",
                "this/filetorename",
                "this/filetomodify",
                "this/filetoremove",
                "this/filetoleave",
            ]
        )
        this_tree.add(
            [
                "dirtorename",
                "dirtoreparent",
                "dirtoleave",
                "dirtoremove",
                "filetoreparent",
                "filetorename",
                "filetomodify",
                "filetoremove",
                "filetoleave",
            ]
        )
        this_tree.commit("create_files")
        other_dir = this_tree.controldir.sprout("other")
        other_tree = other_dir.open_workingtree()
        other_tree.lock_write()
        # perform the needed actions on the files and dirs.
        try:
            other_tree.rename_one("dirtorename", "renameddir")
            other_tree.rename_one("dirtoreparent", "renameddir/reparenteddir")
            other_tree.rename_one("filetorename", "renamedfile")
            other_tree.rename_one("filetoreparent", "renameddir/reparentedfile")
            other_tree.remove(["dirtoremove", "filetoremove"])
            self.build_tree_contents(
                [
                    ("other/newdir/",),
                    ("other/filetomodify", b"new content"),
                    ("other/newfile", b"new file content"),
                ]
            )
            other_tree.add("newfile")
            other_tree.add("newdir/")
            other_tree.commit("modify all sample files and dirs.")
        finally:
            other_tree.unlock()
        this_tree.merge_from_branch(other_tree.branch)
        reporter = CapturingReporter()
        this_tree.commit("do the commit", reporter=reporter)
        expected = {
            ("change", "modified", "filetomodify"),
            ("change", "added", "newdir"),
            ("change", "added", "newfile"),
            ("renamed", "renamed", "dirtorename", "renameddir"),
            ("renamed", "renamed", "filetorename", "renamedfile"),
            ("renamed", "renamed", "dirtoreparent", "renameddir/reparenteddir"),
            ("renamed", "renamed", "filetoreparent", "renameddir/reparentedfile"),
            ("deleted", "dirtoremove"),
            ("deleted", "filetoremove"),
        }
        result = set(reporter.calls)
        missing = expected - result
        new = result - expected
        self.assertEqual((set(), set()), (missing, new))

    def test_commit_removals_respects_filespec(self):
        """Commit respects the specified_files for removals."""
        tree = self.make_branch_and_tree(".")
        self.build_tree(["a", "b"])
        tree.add(["a", "b"])
        tree.commit("added a, b")
        tree.remove(["a", "b"])
        tree.commit("removed a", specific_files="a")
        basis = tree.basis_tree()
        with tree.lock_read():
            self.assertFalse(basis.is_versioned("a"))
            self.assertTrue(basis.is_versioned("b"))

    def test_commit_saves_1ms_timestamp(self):
        """Passing in a timestamp is saved with 1ms resolution."""
        tree = self.make_branch_and_tree(".")
        self.build_tree(["a"])
        tree.add("a")
        tree.commit("added a", timestamp=1153248633.4186721, timezone=0, rev_id=b"a1")

        rev = tree.branch.repository.get_revision(b"a1")
        self.assertEqual(1153248633.419, rev.timestamp)

    def test_commit_has_1ms_resolution(self):
        """Allowing commit to generate the timestamp also has 1ms resolution."""
        tree = self.make_branch_and_tree(".")
        self.build_tree(["a"])
        tree.add("a")
        tree.commit("added a", rev_id=b"a1")

        rev = tree.branch.repository.get_revision(b"a1")
        timestamp = rev.timestamp
        timestamp_1ms = round(timestamp, 3)
        self.assertEqual(timestamp_1ms, timestamp)

    def assertBasisTreeKind(self, kind, tree, path):
        basis = tree.basis_tree()
        basis.lock_read()
        try:
            self.assertEqual(kind, basis.kind(path))
        finally:
            basis.unlock()

    def test_unsupported_symlink_commit(self):
        self.requireFeature(SymlinkFeature(self.test_dir))
        tree = self.make_branch_and_tree(".")
        self.build_tree(["hello"])
        tree.add("hello")
        tree.commit("added hello", rev_id=b"hello_id")
        os.symlink("hello", "foo")
        tree.add("foo")
        tree.commit("added foo", rev_id=b"foo_id")
        log = BytesIO()
        trace.push_log_file(log, short=True)
        self.overrideAttr(os, "symlink", None)
        self.overrideAttr(osutils, "supports_symlinks", lambda x: False)
        # At this point as bzr thinks symlinks are not supported
        # we should get a warning about symlink foo and bzr should
        # not think its removed.
        os.unlink("foo")
        self.build_tree(["world"])
        tree.add("world")
        tree.commit("added world", rev_id=b"world_id")
        self.assertContainsRe(
            log.getvalue(),
            b'Ignoring "foo" as symlinks are not supported on this filesystem\\.',
        )

    def test_commit_kind_changes(self):
        self.requireFeature(SymlinkFeature(self.test_dir))
        tree = self.make_branch_and_tree(".")
        os.symlink("target", "name")
        tree.add("name", ids=b"a-file-id")
        tree.commit("Added a symlink")
        self.assertBasisTreeKind("symlink", tree, "name")

        os.unlink("name")
        self.build_tree(["name"])
        tree.commit("Changed symlink to file")
        self.assertBasisTreeKind("file", tree, "name")

        os.unlink("name")
        os.symlink("target", "name")
        tree.commit("file to symlink")
        self.assertBasisTreeKind("symlink", tree, "name")

        os.unlink("name")
        os.mkdir("name")
        tree.commit("symlink to directory")
        self.assertBasisTreeKind("directory", tree, "name")

        os.rmdir("name")
        os.symlink("target", "name")
        tree.commit("directory to symlink")
        self.assertBasisTreeKind("symlink", tree, "name")

        # prepare for directory <-> file tests
        os.unlink("name")
        os.mkdir("name")
        tree.commit("symlink to directory")
        self.assertBasisTreeKind("directory", tree, "name")

        os.rmdir("name")
        self.build_tree(["name"])
        tree.commit("Changed directory to file")
        self.assertBasisTreeKind("file", tree, "name")

        os.unlink("name")
        os.mkdir("name")
        tree.commit("file to directory")
        self.assertBasisTreeKind("directory", tree, "name")

    def test_commit_unversioned_specified(self):
        """Commit should raise if specified files isn't in basis or worktree."""
        tree = self.make_branch_and_tree(".")
        self.assertRaises(
            errors.PathsNotVersionedError,
            tree.commit,
            "message",
            specific_files=["bogus"],
        )

    class Callback:
        def __init__(self, message, testcase):
            self.called = False
            self.message = message
            self.testcase = testcase

        def __call__(self, commit_obj):
            self.called = True
            self.testcase.assertTrue(isinstance(commit_obj, Commit))
            return self.message

    def test_commit_callback(self):
        """Commit should invoke a callback to get the message."""
        tree = self.make_branch_and_tree(".")
        try:
            tree.commit()
        except Exception as e:
            self.assertIsInstance(e, BzrError)
            self.assertEqual(
                "The message or message_callback keyword"
                " parameter is required for commit().",
                str(e),
            )
        else:
            self.fail("exception not raised")
        cb = self.Callback("commit 1", self)
        tree.commit(message_callback=cb)
        self.assertTrue(cb.called)
        repository = tree.branch.repository
        message = repository.get_revision(tree.last_revision()).message
        self.assertEqual("commit 1", message)

    def test_no_callback_pointless(self):
        """Callback should not be invoked for pointless commit."""
        tree = self.make_branch_and_tree(".")
        cb = self.Callback("commit 2", self)
        self.assertRaises(
            PointlessCommit, tree.commit, message_callback=cb, allow_pointless=False
        )
        self.assertFalse(cb.called)

    def test_no_callback_netfailure(self):
        """Callback should not be invoked if connectivity fails."""
        tree = self.make_branch_and_tree(".")
        cb = self.Callback("commit 2", self)
        repository = tree.branch.repository
        # simulate network failure

        def raise_(self, arg, arg2, arg3=None, arg4=None):
            raise _mod_transport.NoSuchFile("foo")

        repository.add_inventory = raise_
        repository.add_inventory_by_delta = raise_
        self.assertRaises(_mod_transport.NoSuchFile, tree.commit, message_callback=cb)
        self.assertFalse(cb.called)

    def test_selected_file_merge_commit(self):
        """Ensure the correct error is raised."""
        tree = self.make_branch_and_tree("foo")
        # pending merge would turn into a left parent
        tree.commit("commit 1")
        tree.add_parent_tree_id(b"example")
        self.build_tree(["foo/bar", "foo/baz"])
        tree.add(["bar", "baz"])
        err = self.assertRaises(
            CannotCommitSelectedFileMerge,
            tree.commit,
            "commit 2",
            specific_files=["bar", "baz"],
        )
        self.assertEqual(["bar", "baz"], err.files)
        self.assertEqual(
            "Selected-file commit of merges is not supported yet: files bar, baz",
            str(err),
        )

    def test_commit_ordering(self):
        """Test of corner-case commit ordering error."""
        tree = self.make_branch_and_tree(".")
        self.build_tree(["a/", "a/z/", "a/c/", "a/z/x", "a/z/y"])
        tree.add(["a/", "a/z/", "a/c/", "a/z/x", "a/z/y"])
        tree.commit("setup")
        self.build_tree(["a/c/d/"])
        tree.add("a/c/d")
        tree.rename_one("a/z/x", "a/c/d/x")
        tree.commit("test", specific_files=["a/z/y"])

    def test_commit_no_author(self):
        """The default kwarg author in MutableTree.commit should not add
        the 'author' revision property.
        """
        tree = self.make_branch_and_tree("foo")
        rev_id = tree.commit("commit 1")
        rev = tree.branch.repository.get_revision(rev_id)
        self.assertNotIn("author", rev.properties)
        self.assertNotIn("authors", rev.properties)

    def test_commit_author(self):
        """Passing a non-empty authors kwarg to MutableTree.commit should add
        the 'author' revision property.
        """
        tree = self.make_branch_and_tree("foo")
        rev_id = tree.commit("commit 1", authors=["John Doe <jdoe@example.com>"])
        rev = tree.branch.repository.get_revision(rev_id)
        self.assertEqual("John Doe <jdoe@example.com>", rev.properties["authors"])
        self.assertNotIn("author", rev.properties)

    def test_commit_empty_authors_list(self):
        """Passing an empty list to authors shouldn't add the property."""
        tree = self.make_branch_and_tree("foo")
        rev_id = tree.commit("commit 1", authors=[])
        rev = tree.branch.repository.get_revision(rev_id)
        self.assertNotIn("author", rev.properties)
        self.assertNotIn("authors", rev.properties)

    def test_multiple_authors(self):
        tree = self.make_branch_and_tree("foo")
        rev_id = tree.commit(
            "commit 1",
            authors=["John Doe <jdoe@example.com>", "Jane Rey <jrey@example.com>"],
        )
        rev = tree.branch.repository.get_revision(rev_id)
        self.assertEqual(
            "John Doe <jdoe@example.com>\nJane Rey <jrey@example.com>",
            rev.properties["authors"],
        )
        self.assertNotIn("author", rev.properties)

    def test_author_with_newline_rejected(self):
        tree = self.make_branch_and_tree("foo")
        self.assertRaises(
            AssertionError,
            tree.commit,
            "commit 1",
            authors=["John\nDoe <jdoe@example.com>"],
        )

    def test_commit_with_checkout_and_branch_sharing_repo(self):
        self.make_repository("repo", shared=True)
        # make_branch_and_tree ignores shared repos
        branch = controldir.ControlDir.create_branch_convenience("repo/branch")
        tree2 = branch.create_checkout("repo/tree2")
        tree2.commit("message", rev_id=b"rev1")
        self.assertTrue(tree2.branch.repository.has_revision(b"rev1"))


class FilterExcludedTests(TestCase):
    def test_add_file_not_excluded(self):
        changes = [
            TreeChange(
                (None, "newpath"),
                0,
                (False, False),
                ("newpath", "newpath"),
                ("file", "file"),
                (True, True),
            )
        ]
        self.assertEqual(changes, list(filter_excluded(changes, ["otherpath"])))

    def test_add_file_excluded(self):
        changes = [
            TreeChange(
                (None, "newpath"),
                0,
                (False, False),
                ("newpath", "newpath"),
                ("file", "file"),
                (True, True),
            )
        ]
        self.assertEqual([], list(filter_excluded(changes, ["newpath"])))

    def test_delete_file_excluded(self):
        changes = [
            TreeChange(
                ("somepath", None),
                0,
                (False, None),
                ("newpath", None),
                ("file", None),
                (True, None),
            )
        ]
        self.assertEqual([], list(filter_excluded(changes, ["somepath"])))

    def test_move_from_or_to_excluded(self):
        changes = [
            TreeChange(
                ("oldpath", "newpath"),
                0,
                (False, False),
                ("oldpath", "newpath"),
                ("file", "file"),
                (True, True),
            )
        ]
        self.assertEqual([], list(filter_excluded(changes, ["oldpath"])))
        self.assertEqual([], list(filter_excluded(changes, ["newpath"])))
