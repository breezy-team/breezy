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
#
# Author: Aaron Bentley <aaron.bentley@utoronto.ca>

"""Black-box tests for brz merge."""

import doctest
import os

from testtools import matchers

from breezy import (
    branch,
    controldir,
    merge_directive,
    osutils,
    tests,
    urlutils,
    workingtree,
)
from breezy.bzr import conflicts
from breezy.tests import scenarios, script

load_tests = scenarios.load_tests_apply_scenarios


class TestMerge(tests.TestCaseWithTransport):
    def example_branch(self, path="."):
        tree = self.make_branch_and_tree(path)
        self.build_tree_contents(
            [
                (osutils.pathjoin(path, "hello"), b"foo"),
                (osutils.pathjoin(path, "goodbye"), b"baz"),
            ]
        )
        tree.add("hello")
        tree.commit(message="setup")
        tree.add("goodbye")
        tree.commit(message="setup")
        return tree

    def create_conflicting_branches(self):
        """Create two branches which have overlapping modifications.

        :return: (tree, other_branch) Where merging other_branch causes a file
            conflict.
        """
        builder = self.make_branch_builder("branch")
        builder.build_snapshot(
            None,
            [
                ("add", ("", b"root-id", "directory", None)),
                ("add", ("fname", b"f-id", "file", b"a\nb\nc\n")),
            ],
            revision_id=b"rev1",
        )
        builder.build_snapshot(
            [b"rev1"], [("modify", ("fname", b"a\nB\nD\n"))], revision_id=b"rev2other"
        )
        other = builder.get_branch().controldir.sprout("other").open_branch()
        builder.build_snapshot(
            [b"rev1"], [("modify", ("fname", b"a\nB\nC\n"))], revision_id=b"rev2this"
        )
        tree = builder.get_branch().create_checkout("tree", lightweight=True)
        return tree, other

    def test_merge_reprocess(self):
        d = controldir.ControlDir.create_standalone_workingtree(".")
        d.commit("h")
        self.run_bzr("merge . --reprocess --merge-type weave")

    def test_merge(self):
        a_tree = self.example_branch("a")
        ancestor = a_tree.branch.revno()
        b_tree = a_tree.controldir.sprout("b").open_workingtree()
        self.build_tree_contents([("b/goodbye", b"quux")])
        b_tree.commit(message="more u's are always good")

        self.build_tree_contents([("a/hello", b"quuux")])
        # We can't merge when there are in-tree changes
        self.run_bzr("merge ../b", retcode=3, working_dir="a")
        a = workingtree.WorkingTree.open("a")
        a_tip = a.commit("Like an epidemic of u's")

        def run_merge_then_revert(args, retcode=None, working_dir="a"):
            self.run_bzr(
                ["merge", "../b", "-r", "last:1..last:1"] + args,
                retcode=retcode,
                working_dir=working_dir,
            )
            if retcode != 3:
                a_tree.revert(backups=False)

        run_merge_then_revert(["--merge-type", "bloof"], retcode=3)
        run_merge_then_revert(["--merge-type", "merge3"])
        run_merge_then_revert(["--merge-type", "weave"])
        run_merge_then_revert(["--merge-type", "lca"])
        self.run_bzr_error(
            ["Show-base is not supported for this merge type"],
            "merge ../b -r last:1..last:1 --merge-type weave --show-base",
            working_dir="a",
        )
        a_tree.revert(backups=False)
        self.run_bzr("merge ../b -r last:1..last:1 --reprocess", working_dir="a")
        a_tree.revert(backups=False)
        self.run_bzr("merge ../b -r last:1", working_dir="a")
        self.check_file_contents("a/goodbye", b"quux")
        # Merging a branch pulls its revision into the tree
        b = branch.Branch.open("b")
        b_tip = b.last_revision()
        self.assertTrue(a.branch.repository.has_revision(b_tip))
        self.assertEqual([a_tip, b_tip], a.get_parent_ids())
        a_tree.revert(backups=False)
        out, err = self.run_bzr("merge -r revno:1:./hello", retcode=3, working_dir="a")
        self.assertTrue("Not a branch" in err)
        self.run_bzr(
            "merge -r revno:%d:./..revno:%d:../b" % (ancestor, b.revno()),
            working_dir="a",
        )
        self.assertEqual(
            a.get_parent_ids(), [a.branch.last_revision(), b.last_revision()]
        )
        self.check_file_contents("a/goodbye", b"quux")
        a_tree.revert(backups=False)
        self.run_bzr("merge -r revno:%d:../b" % b.revno(), working_dir="a")
        self.assertEqual(
            a.get_parent_ids(), [a.branch.last_revision(), b.last_revision()]
        )
        a_tip = a.commit("merged")
        self.run_bzr("merge ../b -r last:1", working_dir="a")
        self.assertEqual([a_tip], a.get_parent_ids())

    def test_merge_defaults_to_reprocess(self):
        tree, other = self.create_conflicting_branches()
        # The default merge algorithm should enable 'reprocess' because
        # 'show-base' is not set
        self.run_bzr("merge ../other", working_dir="tree", retcode=1)
        self.assertEqualDiff(
            b"a\nB\n<<<<<<< TREE\nC\n=======\nD\n>>>>>>> MERGE-SOURCE\n",
            tree.get_file_text("fname"),
        )

    def test_merge_explicit_reprocess_show_base(self):
        tree, other = self.create_conflicting_branches()
        # Explicitly setting --reprocess, and --show-base is an error
        self.run_bzr_error(
            ["Cannot do conflict reduction and show base"],
            "merge ../other --reprocess --show-base",
            working_dir="tree",
        )

    def test_merge_override_reprocess(self):
        tree, other = self.create_conflicting_branches()
        # Explicitly disable reprocess
        self.run_bzr("merge ../other --no-reprocess", working_dir="tree", retcode=1)
        self.assertEqualDiff(
            b"a\n<<<<<<< TREE\nB\nC\n=======\nB\nD\n>>>>>>> MERGE-SOURCE\n",
            tree.get_file_text("fname"),
        )

    def test_merge_override_show_base(self):
        tree, other = self.create_conflicting_branches()
        # Setting '--show-base' will auto-disable '--reprocess'
        self.run_bzr("merge ../other --show-base", working_dir="tree", retcode=1)
        self.assertEqualDiff(
            b"a\n"
            b"<<<<<<< TREE\n"
            b"B\n"
            b"C\n"
            b"||||||| BASE-REVISION\n"
            b"b\n"
            b"c\n"
            b"=======\n"
            b"B\n"
            b"D\n"
            b">>>>>>> MERGE-SOURCE\n",
            tree.get_file_text("fname"),
        )

    def test_merge_with_missing_file(self):
        """Merge handles missing file conflicts."""
        self.build_tree_contents(
            [
                ("a/",),
                ("a/sub/",),
                ("a/sub/a.txt", b"hello\n"),
                ("a/b.txt", b"hello\n"),
                ("a/sub/c.txt", b"hello\n"),
            ]
        )
        a_tree = self.make_branch_and_tree("a")
        a_tree.add(["sub", "b.txt", "sub/c.txt", "sub/a.txt"])
        a_tree.commit(message="added a")
        b_tree = a_tree.controldir.sprout("b").open_workingtree()
        self.build_tree_contents(
            [
                ("a/sub/a.txt", b"hello\nthere\n"),
                ("a/b.txt", b"hello\nthere\n"),
                ("a/sub/c.txt", b"hello\nthere\n"),
            ]
        )
        a_tree.commit(message="Added there")
        os.remove("a/sub/a.txt")
        os.remove("a/sub/c.txt")
        os.rmdir("a/sub")
        os.remove("a/b.txt")
        a_tree.commit(message="Removed a.txt")
        self.build_tree_contents(
            [
                ("b/sub/a.txt", b"hello\nsomething\n"),
                ("b/b.txt", b"hello\nsomething\n"),
                ("b/sub/c.txt", b"hello\nsomething\n"),
            ]
        )
        b_tree.commit(message="Modified a.txt")

        self.run_bzr("merge ../a/", retcode=1, working_dir="b")
        self.assertPathExists("b/sub/a.txt.THIS")
        self.assertPathExists("b/sub/a.txt.BASE")

        self.run_bzr("merge ../b/", retcode=1, working_dir="a")
        self.assertPathExists("a/sub/a.txt.OTHER")
        self.assertPathExists("a/sub/a.txt.BASE")

    def test_conflict_leaves_base_this_other_files(self):
        tree, other = self.create_conflicting_branches()
        self.run_bzr("merge ../other", working_dir="tree", retcode=1)
        self.assertFileEqual(b"a\nb\nc\n", "tree/fname.BASE")
        self.assertFileEqual(b"a\nB\nD\n", "tree/fname.OTHER")
        self.assertFileEqual(b"a\nB\nC\n", "tree/fname.THIS")

    def test_weave_conflict_leaves_base_this_other_files(self):
        tree, other = self.create_conflicting_branches()
        self.run_bzr("merge ../other --weave", working_dir="tree", retcode=1)
        self.assertFileEqual(b"a\nb\nc\n", "tree/fname.BASE")
        self.assertFileEqual(b"a\nB\nD\n", "tree/fname.OTHER")
        self.assertFileEqual(b"a\nB\nC\n", "tree/fname.THIS")

    def test_merge_remember(self):
        """Merge changes from one branch to another, test submit location."""
        tree_a = self.make_branch_and_tree("branch_a")
        branch_a = tree_a.branch
        self.build_tree(["branch_a/a"])
        tree_a.add("a")
        tree_a.commit("commit a")
        branch_b = branch_a.controldir.sprout("branch_b").open_branch()
        tree_b = branch_b.controldir.open_workingtree()
        branch_c = branch_a.controldir.sprout("branch_c").open_branch()
        tree_c = branch_c.controldir.open_workingtree()
        self.build_tree(["branch_a/b"])
        tree_a.add("b")
        tree_a.commit("commit b")
        self.build_tree(["branch_c/c"])
        tree_c.add("c")
        tree_c.commit("commit c")
        # reset parent
        parent = branch_b.get_parent()
        branch_b.set_parent(None)
        self.assertEqual(None, branch_b.get_parent())
        # test merge for failure without parent set
        out = self.run_bzr("merge", retcode=3, working_dir="branch_b")
        self.assertEqual(out, ("", "brz: ERROR: No location specified or remembered\n"))

        # test uncommitted changes
        self.build_tree(["branch_b/d"])
        tree_b.add("d")
        self.run_bzr_error(
            ['Working tree ".*" has uncommitted changes'],
            "merge",
            working_dir="branch_b",
        )

        # merge should now pass and implicitly remember merge location
        tree_b.commit("commit d")
        out, err = self.run_bzr("merge ../branch_a", working_dir="branch_b")

        base = urlutils.local_path_from_url(branch_a.base)
        self.assertEndsWith(err, "+N  b\nAll changes applied successfully.\n")
        # re-open branch as external run_brz modified it
        branch_b = branch_b.controldir.open_branch()
        self.assertEqual(
            osutils.abspath(branch_b.get_submit_branch()), osutils.abspath(parent)
        )
        # test implicit --remember when committing new file
        self.build_tree(["branch_b/e"])
        tree_b.add("e")
        tree_b.commit("commit e")
        out, err = self.run_bzr("merge", working_dir="branch_b")
        self.assertStartsWith(
            err, "Merging from remembered submit location {}\n".format(base)
        )
        # re-open tree as external run_brz modified it
        tree_b = branch_b.controldir.open_workingtree()
        tree_b.commit("merge branch_a")
        # test explicit --remember
        out, err = self.run_bzr("merge ../branch_c --remember", working_dir="branch_b")
        self.assertEqual(out, "")
        self.assertEqual(err, "+N  c\nAll changes applied successfully.\n")
        # re-open branch as external run_brz modified it
        branch_b = branch_b.controldir.open_branch()
        self.assertEqual(
            osutils.abspath(branch_b.get_submit_branch()),
            osutils.abspath(branch_c.controldir.root_transport.base),
        )
        # re-open tree as external run_brz modified it
        tree_b = branch_b.controldir.open_workingtree()
        tree_b.commit("merge branch_c")

    def test_merge_bundle(self):
        from breezy.bzr.testament import Testament

        tree_a = self.make_branch_and_tree("branch_a")
        self.build_tree_contents([("branch_a/a", b"hello")])
        tree_a.add("a")
        tree_a.commit("message")

        tree_b = tree_a.controldir.sprout("branch_b").open_workingtree()
        self.build_tree_contents([("branch_a/a", b"hey there")])
        tree_a.commit("message")

        self.build_tree_contents([("branch_b/a", b"goodbye")])
        tree_b.commit("message")
        self.run_bzr("bundle ../branch_a -o ../bundle", working_dir="branch_b")
        self.run_bzr("merge ../bundle", retcode=1, working_dir="branch_a")
        testament_a = Testament.from_revision(
            tree_a.branch.repository, tree_b.get_parent_ids()[0]
        )
        testament_b = Testament.from_revision(
            tree_b.branch.repository, tree_b.get_parent_ids()[0]
        )
        self.assertEqualDiff(testament_a.as_text(), testament_b.as_text())
        tree_a.set_conflicts([])
        tree_a.commit("message")
        # it is legal to attempt to merge an already-merged bundle
        err = self.run_bzr("merge ../bundle", working_dir="branch_a")[1]
        # but it does nothing
        self.assertFalse(tree_a.changes_from(tree_a.basis_tree()).has_changed())
        self.assertEqual("Nothing to do.\n", err)

    def test_merge_uncommitted(self):
        """Check that merge --uncommitted behaves properly."""
        tree_a = self.make_branch_and_tree("a")
        self.build_tree(["a/file_1", "a/file_2"])
        tree_a.add(["file_1", "file_2"])
        tree_a.commit("commit 1")
        tree_b = tree_a.controldir.sprout("b").open_workingtree()
        self.assertPathExists("b/file_1")
        tree_a.rename_one("file_1", "file_i")
        tree_a.commit("commit 2")
        tree_a.rename_one("file_2", "file_ii")
        self.run_bzr("merge a --uncommitted -d b")
        self.assertPathExists("b/file_1")
        self.assertPathExists("b/file_ii")
        tree_b.revert()
        self.run_bzr_error(
            ("Cannot use --uncommitted and --revision",),
            "merge /a --uncommitted -r1 -d b",
        )

    def test_merge_uncommitted_file(self):
        """It should be possible to merge changes from a single file."""
        tree_a = self.make_branch_and_tree("tree_a")
        tree_a.commit("initial commit")
        tree_a.controldir.sprout("tree_b")
        self.build_tree(["tree_a/file1", "tree_a/file2"])
        tree_a.add(["file1", "file2"])
        self.run_bzr(
            ["merge", "--uncommitted", "../tree_a/file1"], working_dir="tree_b"
        )
        self.assertPathExists("tree_b/file1")
        self.assertPathDoesNotExist("tree_b/file2")

    def test_merge_nonexistent_file(self):
        """It should not be possible to merge changes from a file which
        does not exist.
        """
        tree_a = self.make_branch_and_tree("tree_a")
        self.build_tree_contents([("tree_a/file", b"bar\n")])
        tree_a.add(["file"])
        tree_a.commit("commit 1")
        self.run_bzr_error(
            ("Path\\(s\\) do not exist: non/existing",),
            ["merge", "non/existing"],
            working_dir="tree_a",
        )

    def pullable_branch(self):
        tree_a = self.make_branch_and_tree("a")
        self.build_tree_contents([("a/file", b"bar\n")])
        tree_a.add(["file"])
        self.id1 = tree_a.commit("commit 1")

        tree_b = self.make_branch_and_tree("b")
        tree_b.pull(tree_a.branch)
        self.build_tree_contents([("b/file", b"foo\n")])
        self.id2 = tree_b.commit("commit 2")

    def test_merge_pull(self):
        self.pullable_branch()
        (out, err) = self.run_bzr("merge --pull ../b", working_dir="a")
        self.assertContainsRe(out, "Now on revision 2\\.")
        tree_a = workingtree.WorkingTree.open("a")
        self.assertEqual([self.id2], tree_a.get_parent_ids())

    def test_merge_pull_preview(self):
        self.pullable_branch()
        (out, err) = self.run_bzr("merge --pull --preview -d a b")
        self.assertThat(
            out,
            matchers.DocTestMatches(
                """=== modified file 'file'
--- file\t...
+++ file\t...
@@ -1,1 +1,1 @@
-bar
+foo

""",
                doctest.ELLIPSIS | doctest.REPORT_UDIFF,
            ),
        )
        tree_a = workingtree.WorkingTree.open("a")
        self.assertEqual([self.id1], tree_a.get_parent_ids())

    def test_merge_kind_change(self):
        tree_a = self.make_branch_and_tree("tree_a")
        self.build_tree_contents([("tree_a/file", b"content_1")])
        tree_a.add("file", ids=b"file-id")
        tree_a.commit("added file")
        tree_b = tree_a.controldir.sprout("tree_b").open_workingtree()
        os.unlink("tree_a/file")
        self.build_tree(["tree_a/file/"])
        tree_a.commit("changed file to directory")
        self.run_bzr("merge ../tree_a", working_dir="tree_b")
        self.assertEqual("directory", osutils.file_kind("tree_b/file"))
        tree_b.revert()
        self.assertEqual("file", osutils.file_kind("tree_b/file"))
        self.build_tree_contents([("tree_b/file", b"content_2")])
        tree_b.commit("content change")
        self.run_bzr("merge ../tree_a", retcode=1, working_dir="tree_b")
        self.assertEqual(
            tree_b.conflicts(), [conflicts.ContentsConflict("file", file_id="file-id")]
        )

    def test_directive_cherrypick(self):
        source = self.make_branch_and_tree("source")
        source.commit("nothing")
        # see https://bugs.launchpad.net/bzr/+bug/409688 - trying to
        # cherrypick from one branch into another unrelated branch with a
        # different root id will give shape conflicts.  as a workaround we
        # make sure they share the same root id.
        target = source.controldir.sprout("target").open_workingtree()
        self.build_tree(["source/a"])
        source.add("a")
        source.commit("Added a", rev_id=b"rev1")
        self.build_tree(["source/b"])
        source.add("b")
        source.commit("Added b", rev_id=b"rev2")
        target.commit("empty commit")
        self.write_directive("directive", source.branch, "target", b"rev2", b"rev1")
        out, err = self.run_bzr("merge -d target directive")
        self.assertPathDoesNotExist("target/a")
        self.assertPathExists("target/b")
        self.assertContainsRe(err, "Performing cherrypick")

    def write_directive(
        self,
        filename,
        source,
        target,
        revision_id,
        base_revision_id=None,
        mangle_patch=False,
    ):
        md = merge_directive.MergeDirective2.from_objects(
            source.repository,
            revision_id,
            0,
            0,
            target,
            base_revision_id=base_revision_id,
        )
        if mangle_patch:
            md.patch = b"asdf\n"
        self.build_tree_contents([(filename, b"".join(md.to_lines()))])

    def test_directive_verify_warning(self):
        source = self.make_branch_and_tree("source")
        self.build_tree(["source/a"])
        source.add("a")
        source.commit("Added a", rev_id=b"rev1")
        target = self.make_branch_and_tree("target")
        target.commit("empty commit")
        self.write_directive("directive", source.branch, "target", b"rev1")
        err = self.run_bzr("merge -d target directive")[1]
        self.assertNotContainsRe(err, "Preview patch does not match changes")
        target.revert()
        self.write_directive(
            "directive", source.branch, "target", b"rev1", mangle_patch=True
        )
        err = self.run_bzr("merge -d target directive")[1]
        self.assertContainsRe(err, "Preview patch does not match changes")

    def test_merge_arbitrary(self):
        target = self.make_branch_and_tree("target")
        target.commit("empty")
        # We need a revision that has no integer revno
        branch_a = target.controldir.sprout("branch_a").open_workingtree()
        self.build_tree(["branch_a/file1"])
        branch_a.add("file1")
        branch_a.commit("added file1", rev_id=b"rev2a")
        branch_b = target.controldir.sprout("branch_b").open_workingtree()
        self.build_tree(["branch_b/file2"])
        branch_b.add("file2")
        branch_b.commit("added file2", rev_id=b"rev2b")
        branch_b.merge_from_branch(branch_a.branch)
        self.assertPathExists("branch_b/file1")
        branch_b.commit("merged branch_a", rev_id=b"rev3b")

        # It works if the revid has an interger revno
        self.run_bzr("merge -d target -r revid:rev2a branch_a")
        self.assertPathExists("target/file1")
        self.assertPathDoesNotExist("target/file2")
        target.revert()

        # It should work if the revid has no integer revno
        self.run_bzr("merge -d target -r revid:rev2a branch_b")
        self.assertPathExists("target/file1")
        self.assertPathDoesNotExist("target/file2")

    def assertDirectoryContent(self, directory, entries, message=""):
        """Assert whether entries (file or directories) exist in a directory.

        It also checks that there are no extra entries.
        """
        ondisk = os.listdir(directory)
        if set(ondisk) == set(entries):
            return
        if message:
            message += "\n"
        raise AssertionError(
            '{}"{}" directory content is different:\na = {}\nb = {}\n'.format(message, directory, sorted(entries), sorted(ondisk))
        )

    def test_cherrypicking_merge(self):
        # make source branch
        source = self.make_branch_and_tree("source")
        for f in ("a", "b", "c", "d"):
            self.build_tree(["source/" + f])
            source.add(f)
            source.commit("added " + f, rev_id=b"rev_" + f.encode("ascii"))
        # target branch
        target = source.controldir.sprout("target", b"rev_a").open_workingtree()
        self.assertDirectoryContent("target", [".bzr", "a"])
        # pick 1 revision
        self.run_bzr("merge -d target -r revid:rev_b..revid:rev_c source")
        self.assertDirectoryContent("target", [".bzr", "a", "c"])
        target.revert()
        # pick 2 revisions
        self.run_bzr("merge -d target -r revid:rev_b..revid:rev_d source")
        self.assertDirectoryContent("target", [".bzr", "a", "c", "d"])
        target.revert()
        # pick 1 revision with option --changes
        self.run_bzr("merge -d target -c revid:rev_d source")
        self.assertDirectoryContent("target", [".bzr", "a", "d"])

    def test_merge_criss_cross(self):
        tree_a = self.make_branch_and_tree("a")
        tree_a.commit("", rev_id=b"rev1")
        tree_b = tree_a.controldir.sprout("b").open_workingtree()
        tree_a.commit("", rev_id=b"rev2a")
        tree_b.commit("", rev_id=b"rev2b")
        tree_a.merge_from_branch(tree_b.branch)
        tree_b.merge_from_branch(tree_a.branch)
        tree_a.commit("", rev_id=b"rev3a")
        tree_b.commit("", rev_id=b"rev3b")
        tree_a.branch.repository.get_graph(tree_b.branch.repository)
        out, err = self.run_bzr(["merge", "-d", "a", "b"])
        self.assertContainsRe(err, "Warning: criss-cross merge encountered.")

    def test_merge_from_submit(self):
        tree_a = self.make_branch_and_tree("a")
        tree_a.commit("test")
        tree_b = tree_a.controldir.sprout("b").open_workingtree()
        tree_c = tree_a.controldir.sprout("c").open_workingtree()
        out, err = self.run_bzr(["merge", "-d", "c"])
        self.assertContainsRe(err, "Merging from remembered parent location .*a\\/")
        with tree_c.branch.lock_write():
            tree_c.branch.set_submit_branch(tree_b.controldir.root_transport.base)
        out, err = self.run_bzr(["merge", "-d", "c"])
        self.assertContainsRe(err, "Merging from remembered submit location .*b\\/")

    def test_remember_sets_submit(self):
        tree_a = self.make_branch_and_tree("a")
        tree_a.commit("rev1")
        tree_b = tree_a.controldir.sprout("b").open_workingtree()
        self.assertIs(tree_b.branch.get_submit_branch(), None)

        # Remember should not happen if using default from parent
        out, err = self.run_bzr(["merge", "-d", "b"])
        refreshed = workingtree.WorkingTree.open("b")
        self.assertIs(refreshed.branch.get_submit_branch(), None)

        # Remember should happen if user supplies location
        out, err = self.run_bzr(["merge", "-d", "b", "a"])
        refreshed = workingtree.WorkingTree.open("b")
        self.assertEqual(
            refreshed.branch.get_submit_branch(), tree_a.controldir.root_transport.base
        )

    def test_no_remember_dont_set_submit(self):
        tree_a = self.make_branch_and_tree("a")
        self.build_tree_contents([("a/file", b"a\n")])
        tree_a.add("file")
        tree_a.commit("rev1")
        tree_b = tree_a.controldir.sprout("b").open_workingtree()
        self.assertIs(tree_b.branch.get_submit_branch(), None)

        # Remember should not happen if using default from parent
        out, err = self.run_bzr(["merge", "-d", "b", "--no-remember"])
        self.assertEqual(None, tree_b.branch.get_submit_branch())

        # Remember should not happen if user supplies location but ask for not
        # remembering it
        out, err = self.run_bzr(["merge", "-d", "b", "--no-remember", "a"])
        self.assertEqual(None, tree_b.branch.get_submit_branch())

    def test_weave_cherrypick(self):
        this_tree = self.make_branch_and_tree("this")
        self.build_tree_contents([("this/file", b"a\n")])
        this_tree.add("file")
        this_tree.commit("rev1")
        other_tree = this_tree.controldir.sprout("other").open_workingtree()
        self.build_tree_contents([("other/file", b"a\nb\n")])
        other_tree.commit("rev2b")
        self.build_tree_contents([("other/file", b"c\na\nb\n")])
        other_tree.commit("rev3b")
        self.run_bzr("merge --weave -d this other -r -2..-1")
        self.assertFileEqual(b"c\na\n", "this/file")

    def test_lca_merge_criss_cross(self):
        tree_a = self.make_branch_and_tree("a")
        self.build_tree_contents([("a/file", b"base-contents\n")])
        tree_a.add("file")
        tree_a.commit("", rev_id=b"rev1")
        tree_b = tree_a.controldir.sprout("b").open_workingtree()
        self.build_tree_contents([("a/file", b"base-contents\nthis-contents\n")])
        tree_a.commit("", rev_id=b"rev2a")
        self.build_tree_contents([("b/file", b"base-contents\nother-contents\n")])
        tree_b.commit("", rev_id=b"rev2b")
        tree_a.merge_from_branch(tree_b.branch)
        self.build_tree_contents([("a/file", b"base-contents\nthis-contents\n")])
        tree_a.set_conflicts([])
        tree_b.merge_from_branch(tree_a.branch)
        self.build_tree_contents([("b/file", b"base-contents\nother-contents\n")])
        tree_b.set_conflicts([])
        tree_a.commit("", rev_id=b"rev3a")
        tree_b.commit("", rev_id=b"rev3b")
        out, err = self.run_bzr(["merge", "-d", "a", "b", "--lca"], retcode=1)
        self.assertFileEqual(
            b"base-contents\n<<<<<<< TREE\nthis-contents\n"
            b"=======\nother-contents\n>>>>>>> MERGE-SOURCE\n",
            "a/file",
        )

    def test_merge_preview(self):
        this_tree = self.make_branch_and_tree("this")
        this_tree.commit("rev1")
        other_tree = this_tree.controldir.sprout("other").open_workingtree()
        self.build_tree_contents([("other/file", b"new line")])
        other_tree.add("file")
        other_tree.commit("rev2a")
        this_tree.commit("rev2b")
        out, err = self.run_bzr(["merge", "-d", "this", "other", "--preview"])
        self.assertContainsRe(out, "\\+new line")
        self.assertNotContainsRe(err, "\\+N  file\n")
        this_tree.lock_read()
        self.addCleanup(this_tree.unlock)
        self.assertEqual([], list(this_tree.iter_changes(this_tree.basis_tree())))

    def test_merge_missing_second_revision_spec(self):
        """Merge uses branch basis when the second revision is unspecified."""
        this = self.make_branch_and_tree("this")
        this.commit("rev1")
        other = self.make_branch_and_tree("other")
        self.build_tree(["other/other_file"])
        other.add("other_file")
        other.commit("rev1b")
        self.run_bzr("merge -d this other -r0..")
        self.assertPathExists("this/other_file")

    def test_merge_interactive_unlocks_branch(self):
        this = self.make_branch_and_tree("this")
        this.commit("empty commit")
        other = this.controldir.sprout("other").open_workingtree()
        other.commit("empty commit 2")
        self.run_bzr("merge -i -d this other")
        this.lock_write()
        this.unlock()

    def test_merge_fetches_tags(self):
        """Tags are updated by merge, and revisions named in those tags are
        fetched.
        """
        # Make a source, sprout a target off it
        builder = self.make_branch_builder("source")
        builder.build_commit(message="Rev 1", rev_id=b"rev-1")
        source = builder.get_branch()
        target_bzrdir = source.controldir.sprout("target")
        # Add a non-ancestry tag to source
        builder.build_commit(message="Rev 2a", rev_id=b"rev-2a")
        source.tags.set_tag("tag-a", b"rev-2a")
        source.set_last_revision_info(1, b"rev-1")
        source.get_config_stack().set("branch.fetch_tags", True)
        builder.build_commit(message="Rev 2b", rev_id=b"rev-2b")
        # Merge from source
        self.run_bzr("merge -d target source")
        target = target_bzrdir.open_branch()
        # The tag is present, and so is its revision.
        self.assertEqual(b"rev-2a", target.tags.lookup_tag("tag-a"))
        target.repository.get_revision(b"rev-2a")


class TestMergeRevisionRange(tests.TestCaseWithTransport):
    scenarios = (("whole-tree", {"context": "."}), ("file-only", {"context": "a"}))

    def setUp(self):
        super().setUp()
        self.tree = self.make_branch_and_tree(".")
        self.tree.commit("initial commit")
        for f in ("a", "b"):
            self.build_tree([f])
            self.tree.add(f)
            self.tree.commit("added " + f)

    def test_merge_reversed_revision_range(self):
        self.run_bzr("merge -r 2..1 " + self.context)
        self.assertPathDoesNotExist("a")
        self.assertPathExists("b")


class TestMergeScript(script.TestCaseWithTransportAndScript):
    def test_merge_empty_branch(self):
        source = self.make_branch_and_tree("source")
        self.build_tree(["source/a"])
        source.add("a")
        source.commit("Added a", rev_id=b"rev1")
        self.make_branch_and_tree("target")
        self.run_script("""\
$ brz merge -d target source
2>brz: ERROR: Merging into empty branches not currently supported, https://bugs.launchpad.net/bzr/+bug/308562
""")


class TestMergeForce(tests.TestCaseWithTransport):
    def setUp(self):
        super().setUp()
        self.tree_a = self.make_branch_and_tree("a")
        self.build_tree(["a/foo"])
        self.tree_a.add(["foo"])
        self.tree_a.commit("add file")
        self.tree_b = self.tree_a.controldir.sprout("b").open_workingtree()
        self.build_tree_contents([("a/foo", b"change 1")])
        self.tree_a.commit("change file")
        self.tree_b.merge_from_branch(self.tree_a.branch)

    def test_merge_force(self):
        self.tree_a.commit("empty change to allow merge to run")
        # Second merge on top of the uncommitted one
        self.run_bzr(["merge", "../a", "--force"], working_dir="b")

    def test_merge_with_uncommitted_changes(self):
        self.run_bzr_error(
            ["Working tree .* has uncommitted changes"],
            ["merge", "../a"],
            working_dir="b",
        )

    def test_merge_with_pending_merges(self):
        # Revert the changes keeping the pending merge
        self.run_bzr(["revert", "b"])
        self.run_bzr_error(
            ["Working tree .* has uncommitted changes"],
            ["merge", "../a"],
            working_dir="b",
        )
