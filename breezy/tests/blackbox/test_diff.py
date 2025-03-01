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


"""Black-box tests for brz diff."""

import os
import re

from breezy import tests, workingtree
from breezy.diff import DiffTree
from breezy.diff import format_registry as diff_format_registry
from breezy.tests import features


def subst_dates(string):
    """Replace date strings with constant values."""
    return re.sub(
        r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} [-\+]\d{4}",
        "YYYY-MM-DD HH:MM:SS +ZZZZ",
        string,
    )


class DiffBase(tests.TestCaseWithTransport):
    """Base class with common setup method."""

    def make_example_branch(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree_contents([("hello", b"foo\n"), ("goodbye", b"baz\n")])
        tree.add(["hello"])
        tree.commit("setup")
        tree.add(["goodbye"])
        tree.commit("setup")
        return tree


class TestDiff(DiffBase):
    def test_diff(self):
        tree = self.make_example_branch()
        self.build_tree_contents([("hello", b"hello world!")])
        tree.commit(message="fixing hello")
        output = self.run_bzr("diff -r 2..3", retcode=1)[0]
        self.assertTrue("\n+hello world!" in output)
        output = self.run_bzr("diff -c 3", retcode=1)[0]
        self.assertTrue("\n+hello world!" in output)
        output = self.run_bzr("diff -r last:3..last:1", retcode=1)[0]
        self.assertTrue("\n+baz" in output)
        output = self.run_bzr("diff -c last:2", retcode=1)[0]
        self.assertTrue("\n+baz" in output)
        self.build_tree(["moo"])
        tree.add("moo")
        os.unlink("moo")
        self.run_bzr("diff")

    def test_diff_prefix(self):
        """Diff --prefix appends to filenames in output."""
        self.make_example_branch()
        self.build_tree_contents([("hello", b"hello world!\n")])
        out, err = self.run_bzr("diff --prefix old/:new/", retcode=1)
        self.assertEqual(err, "")
        self.assertEqualDiff(
            subst_dates(out),
            """\
=== modified file 'hello'
--- old/hello\tYYYY-MM-DD HH:MM:SS +ZZZZ
+++ new/hello\tYYYY-MM-DD HH:MM:SS +ZZZZ
@@ -1,1 +1,1 @@
-foo
+hello world!

""",
        )

    def test_diff_illegal_prefix_value(self):
        # There was an error in error reporting for this option
        out, err = self.run_bzr("diff --prefix old/", retcode=3)
        self.assertContainsRe(err, "--prefix expects two values separated by a colon")

    def test_diff_p1(self):
        """Diff -p1 produces lkml-style diffs."""
        self.make_example_branch()
        self.build_tree_contents([("hello", b"hello world!\n")])
        out, err = self.run_bzr("diff -p1", retcode=1)
        self.assertEqual(err, "")
        self.assertEqualDiff(
            subst_dates(out),
            """\
=== modified file 'hello'
--- old/hello\tYYYY-MM-DD HH:MM:SS +ZZZZ
+++ new/hello\tYYYY-MM-DD HH:MM:SS +ZZZZ
@@ -1,1 +1,1 @@
-foo
+hello world!

""",
        )

    def test_diff_p0(self):
        """Diff -p0 produces diffs with no prefix."""
        self.make_example_branch()
        self.build_tree_contents([("hello", b"hello world!\n")])
        out, err = self.run_bzr("diff -p0", retcode=1)
        self.assertEqual(err, "")
        self.assertEqualDiff(
            subst_dates(out),
            """\
=== modified file 'hello'
--- hello\tYYYY-MM-DD HH:MM:SS +ZZZZ
+++ hello\tYYYY-MM-DD HH:MM:SS +ZZZZ
@@ -1,1 +1,1 @@
-foo
+hello world!

""",
        )

    def test_diff_nonexistent(self):
        # Get an error from a file that does not exist at all
        # (Malone #3619)
        self.make_example_branch()
        out, err = self.run_bzr(
            "diff does-not-exist",
            retcode=3,
            error_regexes=("not versioned.*does-not-exist",),
        )

    def test_diff_illegal_revision_specifiers(self):
        out, err = self.run_bzr(
            "diff -r 1..23..123",
            retcode=3,
            error_regexes=("one or two revision specifiers",),
        )

    def test_diff_using_and_format(self):
        out, err = self.run_bzr(
            "diff --format=default --using=mydi",
            retcode=3,
            error_regexes=("are mutually exclusive",),
        )

    def test_diff_nonexistent_revision(self):
        out, err = self.run_bzr(
            "diff -r 123",
            retcode=3,
            error_regexes=("Requested revision: '123' does not exist in branch:",),
        )

    def test_diff_nonexistent_dotted_revision(self):
        out, err = self.run_bzr("diff -r 1.1", retcode=3)
        self.assertContainsRe(
            err, "Requested revision: '1.1' does not exist in branch:"
        )

    def test_diff_nonexistent_dotted_revision_change(self):
        out, err = self.run_bzr("diff -c 1.1", retcode=3)
        self.assertContainsRe(
            err, "Requested revision: '1.1' does not exist in branch:"
        )

    def test_diff_unversioned(self):
        # Get an error when diffing a non-versioned file.
        # (Malone #3619)
        self.make_example_branch()
        self.build_tree(["unversioned-file"])
        out, err = self.run_bzr("diff unversioned-file", retcode=3)
        self.assertContainsRe(err, "not versioned.*unversioned-file")

    # TODO: What should diff say for a file deleted in working tree?

    def example_branches(self):
        branch1_tree = self.make_branch_and_tree("branch1")
        self.build_tree(["branch1/file"], line_endings="binary")
        self.build_tree(["branch1/file2"], line_endings="binary")
        branch1_tree.add("file")
        branch1_tree.add("file2")
        branch1_tree.commit(message="add file and file2")
        branch2_tree = branch1_tree.controldir.sprout("branch2").open_workingtree()
        self.build_tree_contents([("branch2/file", b"new content\n")])
        branch2_tree.commit(message="update file")
        return branch1_tree, branch2_tree

    def check_b2_vs_b1(self, cmd):
        # Compare branch2 vs branch1 using cmd and check the result
        out, err = self.run_bzr(cmd, retcode=1)
        self.assertEqual("", err)
        self.assertEqual(
            "=== modified file 'file'\n"
            "--- old/file\tYYYY-MM-DD HH:MM:SS +ZZZZ\n"
            "+++ new/file\tYYYY-MM-DD HH:MM:SS +ZZZZ\n"
            "@@ -1,1 +1,1 @@\n"
            "-new content\n"
            "+contents of branch1/file\n"
            "\n",
            subst_dates(out),
        )

    def check_b1_vs_b2(self, cmd):
        # Compare branch1 vs branch2 using cmd and check the result
        out, err = self.run_bzr(cmd, retcode=1)
        self.assertEqual("", err)
        self.assertEqualDiff(
            "=== modified file 'file'\n"
            "--- old/file\tYYYY-MM-DD HH:MM:SS +ZZZZ\n"
            "+++ new/file\tYYYY-MM-DD HH:MM:SS +ZZZZ\n"
            "@@ -1,1 +1,1 @@\n"
            "-contents of branch1/file\n"
            "+new content\n"
            "\n",
            subst_dates(out),
        )

    def check_no_diffs(self, cmd):
        # Check that running cmd returns an empty diff
        out, err = self.run_bzr(cmd, retcode=0)
        self.assertEqual("", err)
        self.assertEqual("", out)

    def test_diff_branches(self):
        self.example_branches()
        # should open branch1 and diff against branch2,
        self.check_b2_vs_b1("diff -r branch:branch2 branch1")
        # Compare two working trees using various syntax forms
        self.check_b2_vs_b1("diff --old branch2 --new branch1")
        self.check_b2_vs_b1("diff --old branch2 branch1")
        self.check_b2_vs_b1("diff branch2 --new branch1")
        # Test with a selected file that was changed
        self.check_b2_vs_b1("diff --old branch2 --new branch1 file")
        self.check_b2_vs_b1("diff --old branch2 branch1/file")
        self.check_b2_vs_b1("diff branch2/file --new branch1")
        # Test with a selected file that was not changed
        self.check_no_diffs("diff --old branch2 --new branch1 file2")
        self.check_no_diffs("diff --old branch2 branch1/file2")
        self.check_no_diffs("diff branch2/file2 --new branch1")

    def test_diff_branches_no_working_trees(self):
        branch1_tree, branch2_tree = self.example_branches()
        # Compare a working tree to a branch without a WT
        dir1 = branch1_tree.controldir
        dir1.destroy_workingtree()
        self.assertFalse(dir1.has_workingtree())
        self.check_b2_vs_b1("diff --old branch2 --new branch1")
        self.check_b2_vs_b1("diff --old branch2 branch1")
        self.check_b2_vs_b1("diff branch2 --new branch1")
        # Compare a branch without a WT to one with a WT
        self.check_b1_vs_b2("diff --old branch1 --new branch2")
        self.check_b1_vs_b2("diff --old branch1 branch2")
        self.check_b1_vs_b2("diff branch1 --new branch2")
        # Compare a branch with a WT against another without a WT
        dir2 = branch2_tree.controldir
        dir2.destroy_workingtree()
        self.assertFalse(dir2.has_workingtree())
        self.check_b1_vs_b2("diff --old branch1 --new branch2")
        self.check_b1_vs_b2("diff --old branch1 branch2")
        self.check_b1_vs_b2("diff branch1 --new branch2")

    def test_diff_revno_branches(self):
        self.example_branches()
        branch2_tree = workingtree.WorkingTree.open_containing("branch2")[0]
        self.build_tree_contents([("branch2/file", b"even newer content")])
        branch2_tree.commit(message="update file once more")

        out, err = self.run_bzr(
            "diff -r revno:1:branch2..revno:1:branch1",
        )
        self.assertEqual("", err)
        self.assertEqual("", out)
        out, err = self.run_bzr("diff -r revno:2:branch2..revno:1:branch1", retcode=1)
        self.assertEqual("", err)
        self.assertEqualDiff(
            "=== modified file 'file'\n"
            "--- old/file\tYYYY-MM-DD HH:MM:SS +ZZZZ\n"
            "+++ new/file\tYYYY-MM-DD HH:MM:SS +ZZZZ\n"
            "@@ -1,1 +1,1 @@\n"
            "-new content\n"
            "+contents of branch1/file\n"
            "\n",
            subst_dates(out),
        )

    def test_diff_color_always(self):
        from ... import colordiff
        from ...terminal import colorstring

        self.overrideAttr(colordiff, "GLOBAL_COLORDIFFRC", None)
        self.example_branches()
        branch2_tree = workingtree.WorkingTree.open_containing("branch2")[0]
        self.build_tree_contents([("branch2/file", b"even newer content")])
        branch2_tree.commit(message="update file once more")

        out, err = self.run_bzr(
            "diff --color=always -r revno:2:branch2..revno:1:branch1", retcode=1
        )
        self.assertEqual("", err)
        self.assertEqualDiff(
            (
                colorstring(b"=== modified file 'file'\n", "darkyellow")
                + colorstring(b"--- old/file\tYYYY-MM-DD HH:MM:SS +ZZZZ\n", "darkred")
                + colorstring(b"+++ new/file\tYYYY-MM-DD HH:MM:SS +ZZZZ\n", "darkblue")
                + colorstring(b"@@ -1 +1 @@\n", "darkgreen")
                + colorstring(b"-new content\n", "darkred")
                + colorstring(b"+contents of branch1/file\n", "darkblue")
                + colorstring(b"\n", "darkwhite")
            ).decode(),
            subst_dates(out),
        )

    def example_branch2(self):
        branch1_tree = self.make_branch_and_tree("branch1")
        self.build_tree_contents([("branch1/file1", b"original line\n")])
        branch1_tree.add("file1")
        branch1_tree.commit(message="first commit")
        self.build_tree_contents([("branch1/file1", b"repo line\n")])
        branch1_tree.commit(message="second commit")
        return branch1_tree

    def test_diff_to_working_tree(self):
        self.example_branch2()
        self.build_tree_contents([("branch1/file1", b"new line")])
        output = self.run_bzr("diff -r 1.. branch1", retcode=1)
        self.assertContainsRe(output[0], "\n\\-original line\n\\+new line\n")

    def test_diff_to_working_tree_in_subdir(self):
        self.example_branch2()
        self.build_tree_contents([("branch1/file1", b"new line")])
        os.mkdir("branch1/dir1")
        output = self.run_bzr("diff -r 1..", retcode=1, working_dir="branch1/dir1")
        self.assertContainsRe(output[0], "\n\\-original line\n\\+new line\n")

    def test_diff_across_rename(self):
        """The working tree path should always be considered for diffing."""
        tree = self.make_example_branch()
        self.run_bzr("diff -r 0..1 hello", retcode=1)
        tree.rename_one("hello", "hello1")
        self.run_bzr("diff hello1", retcode=1)
        self.run_bzr("diff -r 0..1 hello1", retcode=1)

    def test_diff_to_branch_no_working_tree(self):
        branch1_tree = self.example_branch2()
        dir1 = branch1_tree.controldir
        dir1.destroy_workingtree()
        self.assertFalse(dir1.has_workingtree())
        output = self.run_bzr("diff -r 1.. branch1", retcode=1)
        self.assertContainsRe(output[0], "\n\\-original line\n\\+repo line\n")

    def test_custom_format(self):
        class BooDiffTree(DiffTree):
            def show_diff(self, specific_files, extra_trees=None):
                self.to_file.write("BOO!\n")
                return super().show_diff(specific_files, extra_trees)

        diff_format_registry.register("boo", BooDiffTree, "Scary diff format")
        self.addCleanup(diff_format_registry.remove, "boo")
        self.make_example_branch()
        self.build_tree_contents([("hello", b"hello world!\n")])
        output = self.run_bzr("diff --format=boo", retcode=1)
        self.assertTrue("BOO!" in output[0])
        output = self.run_bzr("diff -Fboo", retcode=1)
        self.assertTrue("BOO!" in output[0])

    def test_binary_diff_remove(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree_contents([("a", b"\x00" * 20)])
        tree.add(["a"])
        tree.commit("add binary file")
        os.unlink("a")
        output = self.run_bzr("diff", retcode=1)
        self.assertEqual(
            "=== removed file 'a'\nBinary files old/a and new/a differ\n", output[0]
        )

    def test_moved_away(self):
        # pad.lv/1880354
        tree = self.make_branch_and_tree(".")
        self.build_tree_contents([("a", "asdf\n")])
        tree.add(["a"])
        tree.commit("add a")
        tree.rename_one("a", "b")
        self.build_tree_contents([("a", "qwer\n")])
        tree.add("a")
        output, error = self.run_bzr("diff -p0", retcode=1)
        self.assertEqualDiff(
            """\
=== added file 'a'
--- a\tYYYY-MM-DD HH:MM:SS +ZZZZ
+++ a\tYYYY-MM-DD HH:MM:SS +ZZZZ
@@ -0,0 +1,1 @@
+qwer

=== renamed file 'a' => 'b'
""",
            subst_dates(output),
        )


class TestCheckoutDiff(TestDiff):
    def make_example_branch(self):
        tree = super().make_example_branch()
        tree = tree.branch.create_checkout("checkout")
        os.chdir("checkout")
        return tree

    def example_branch2(self):
        tree = super().example_branch2()
        os.mkdir("checkouts")
        tree = tree.branch.create_checkout("checkouts/branch1")
        os.chdir("checkouts")
        return tree

    def example_branches(self):
        branch1_tree, branch2_tree = super().example_branches()
        os.mkdir("checkouts")
        branch1_tree = branch1_tree.branch.create_checkout("checkouts/branch1")
        branch2_tree = branch2_tree.branch.create_checkout("checkouts/branch2")
        os.chdir("checkouts")
        return branch1_tree, branch2_tree


class TestDiffLabels(DiffBase):
    def test_diff_label_removed(self):
        tree = super().make_example_branch()
        tree.remove("hello", keep_files=False)
        diff = self.run_bzr("diff", retcode=1)
        self.assertTrue("=== removed file 'hello'" in diff[0])

    def test_diff_label_added(self):
        tree = super().make_example_branch()
        self.build_tree_contents([("barbar", b"barbar")])
        tree.add("barbar")
        diff = self.run_bzr("diff", retcode=1)
        self.assertTrue("=== added file 'barbar'" in diff[0])

    def test_diff_label_modified(self):
        super().make_example_branch()
        self.build_tree_contents([("hello", b"barbar")])
        diff = self.run_bzr("diff", retcode=1)
        self.assertTrue("=== modified file 'hello'" in diff[0])

    def test_diff_label_renamed(self):
        tree = super().make_example_branch()
        tree.rename_one("hello", "gruezi")
        diff = self.run_bzr("diff", retcode=1)
        self.assertTrue("=== renamed file 'hello' => 'gruezi'" in diff[0])


class TestExternalDiff(DiffBase):
    def test_external_diff(self):
        """Test that we can spawn an external diff process."""
        self.disable_missing_extensions_warning()
        # We have to use run_brz_subprocess, because we need to
        # test writing directly to stdout, (there was a bug in
        # subprocess.py that we had to workaround).
        # However, if 'diff' may not be available
        self.make_example_branch()
        out, err = self.run_brz_subprocess(
            "diff -Oprogress_bar=none -r 1 --diff-options -ub",
            universal_newlines=True,
            retcode=None,
        )
        if b"Diff is not installed on this machine" in err:
            raise tests.TestSkipped("No external 'diff' is available")
        self.assertEqual(b"", err)
        # We have to skip the stuff in the middle, because it depends
        # on time.time()
        self.assertStartsWith(
            out,
            b"=== added file 'goodbye'\n"
            b"--- old/goodbye\t1970-01-01 00:00:00 +0000\n"
            b"+++ new/goodbye\t",
        )
        self.assertEndsWith(out, b"\n@@ -0,0 +1 @@\n+baz\n\n")

    def test_external_diff_options_and_using(self):
        """Test that the options are passed correctly to an external diff process."""
        self.requireFeature(features.diff_feature)
        self.make_example_branch()
        self.build_tree_contents([("hello", b"Foo\n")])
        out, err = self.run_bzr(
            "diff --diff-options -i --diff-options -a --using diff", retcode=1
        )
        self.assertEqual("=== modified file 'hello'\n1c1\n< foo\n---\n> Foo\n", out)
        self.assertEqual("", err)


class TestDiffOutput(DiffBase):
    def test_diff_output(self):
        # check that output doesn't mangle line-endings
        self.make_example_branch()
        self.build_tree_contents([("hello", b"hello world!\n")])
        output = self.run_brz_subprocess("diff", retcode=1)[0]
        self.assertTrue(b"\n+hello world!\n" in output)
