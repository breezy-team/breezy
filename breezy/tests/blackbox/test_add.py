# Copyright (C) 2006, 2007, 2009-2012, 2016 Canonical Ltd
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

"""Tests of the 'brz add' command."""

import os

from breezy import osutils, tests
from breezy.tests import features, script
from breezy.tests.scenarios import load_tests_apply_scenarios

load_tests = load_tests_apply_scenarios


class TestAdd(tests.TestCaseWithTransport):
    scenarios = [
        ("pre-views", {"branch_tree_format": "pack-0.92"}),
        ("view-aware", {"branch_tree_format": "2a"}),
    ]

    def make_branch_and_tree(self, dir):
        return super().make_branch_and_tree(dir, format=self.branch_tree_format)

    def test_add_reports(self):
        """Add command prints the names of added files."""
        self.make_branch_and_tree(".")
        self.build_tree(["top.txt", "dir/", "dir/sub.txt", "CVS"])
        self.build_tree_contents([(".bzrignore", b"CVS\n")])
        out = self.run_bzr("add")[0]
        # the ordering is not defined at the moment
        results = sorted(out.rstrip("\n").split("\n"))
        self.assertEqual(
            ["adding .bzrignore", "adding dir", "adding dir/sub.txt", "adding top.txt"],
            results,
        )
        out = self.run_bzr("add -v")[0]
        results = sorted(out.rstrip("\n").split("\n"))
        self.assertEqual(['ignored CVS matching "CVS"'], results)

    def test_add_quiet_is(self):
        """Add -q does not print the names of added files."""
        self.make_branch_and_tree(".")
        self.build_tree(["top.txt", "dir/", "dir/sub.txt"])
        out = self.run_bzr("add -q")[0]
        # the ordering is not defined at the moment
        results = sorted(out.rstrip("\n").split("\n"))
        self.assertEqual([""], results)

    def test_add_in_unversioned(self):
        """Try to add a file in an unversioned directory.

        "brz add" should add the parent(s) as necessary.
        """
        self.make_branch_and_tree(".")
        self.build_tree(["inertiatic/", "inertiatic/esp"])
        self.assertEqual(self.run_bzr("unknowns")[0], "inertiatic\n")
        self.run_bzr("add inertiatic/esp")
        self.assertEqual(self.run_bzr("unknowns")[0], "")

        # Multiple unversioned parents
        self.build_tree(["veil/", "veil/cerpin/", "veil/cerpin/taxt"])
        self.assertEqual(self.run_bzr("unknowns")[0], "veil\n")
        self.run_bzr("add veil/cerpin/taxt")
        self.assertEqual(self.run_bzr("unknowns")[0], "")

        # Check whacky paths work
        self.build_tree(["cicatriz/", "cicatriz/esp"])
        self.assertEqual(self.run_bzr("unknowns")[0], "cicatriz\n")
        self.run_bzr("add inertiatic/../cicatriz/esp")
        self.assertEqual(self.run_bzr("unknowns")[0], "")

    def test_add_no_recurse(self):
        self.make_branch_and_tree(".")
        self.build_tree(["inertiatic/", "inertiatic/esp"])
        self.assertEqual(self.run_bzr("unknowns")[0], "inertiatic\n")
        self.run_bzr("add -N inertiatic")
        self.assertEqual(self.run_bzr("unknowns")[0], "inertiatic/esp\n")

    def test_add_in_versioned(self):
        """Try to add a file in a versioned directory.

        "brz add" should do this happily.
        """
        self.make_branch_and_tree(".")
        self.build_tree(["inertiatic/", "inertiatic/esp"])
        self.assertEqual(self.run_bzr("unknowns")[0], "inertiatic\n")
        self.run_bzr("add --no-recurse inertiatic")
        self.assertEqual(self.run_bzr("unknowns")[0], "inertiatic/esp\n")
        self.run_bzr("add inertiatic/esp")
        self.assertEqual(self.run_bzr("unknowns")[0], "")

    def test_subdir_add(self):
        """Add in subdirectory should add only things from there down."""
        eq = self.assertEqual

        t = self.make_branch_and_tree(".")
        self.build_tree(["src/", "README"])

        eq(sorted(t.unknowns()), ["README", "src"])

        self.run_bzr("add src")

        self.build_tree(["src/foo.c"])

        # add with no arguments in a subdirectory gets only files below that
        # subdirectory
        self.run_bzr("add", working_dir="src")
        self.assertEqual("README\n", self.run_bzr("unknowns", working_dir="src")[0])
        # reopen to see the new changes
        t = t.controldir.open_workingtree("src")
        versioned = [path for path, entry in t.iter_entries_by_dir()]
        self.assertEqual(versioned, ["", "src", "src/foo.c"])

        # add from the parent directory should pick up all file names
        self.run_bzr("add")
        self.assertEqual(self.run_bzr("unknowns")[0], "")
        self.run_bzr("check")

    def test_add_missing(self):
        """Brz add foo where foo is missing should error."""
        self.make_branch_and_tree(".")
        self.run_bzr("add missing-file", retcode=3)

    def test_add_from(self):
        base_tree = self.make_branch_and_tree("base")
        self.build_tree(["base/a", "base/b/", "base/b/c"])
        base_tree.add(["a", "b", "b/c"])
        base_tree.commit("foo")

        new_tree = self.make_branch_and_tree("new")
        self.build_tree(["new/a", "new/b/", "new/b/c", "d"])

        out, err = self.run_bzr("add --file-ids-from ../base", working_dir="new")
        self.assertEqual("", err)
        self.assertEqualDiff(
            "adding a w/ file id from a\n"
            "adding b w/ file id from b\n"
            "adding b/c w/ file id from b/c\n",
            out,
        )
        new_tree = new_tree.controldir.open_workingtree()
        self.assertEqual(base_tree.path2id("a"), new_tree.path2id("a"))
        self.assertEqual(base_tree.path2id("b"), new_tree.path2id("b"))
        self.assertEqual(base_tree.path2id("b/c"), new_tree.path2id("b/c"))

    def test_add_from_subdir(self):
        base_tree = self.make_branch_and_tree("base")
        self.build_tree(["base/a", "base/b/", "base/b/c", "base/b/d"])
        base_tree.add(["a", "b", "b/c", "b/d"])
        base_tree.commit("foo")

        new_tree = self.make_branch_and_tree("new")
        self.build_tree(["new/c", "new/d"])

        out, err = self.run_bzr("add --file-ids-from ../base/b", working_dir="new")
        self.assertEqual("", err)
        self.assertEqualDiff(
            "adding c w/ file id from b/c\nadding d w/ file id from b/d\n", out
        )

        new_tree = new_tree.controldir.open_workingtree("new")
        self.assertEqual(base_tree.path2id("b/c"), new_tree.path2id("c"))
        self.assertEqual(base_tree.path2id("b/d"), new_tree.path2id("d"))

    def test_add_dry_run(self):
        """Test a dry run add, make sure nothing is added."""
        wt = self.make_branch_and_tree(".")
        self.build_tree(["inertiatic/", "inertiatic/esp"])
        self.assertEqual(list(wt.unknowns()), ["inertiatic"])
        self.run_bzr("add --dry-run")
        self.assertEqual(list(wt.unknowns()), ["inertiatic"])

    def test_add_control_dir(self):
        """The control dir and its content should be refused."""
        self.make_branch_and_tree(".")
        err = self.run_bzr("add .bzr", retcode=3)[1]
        self.assertContainsRe(err, r"ERROR:.*\.bzr.*control file")
        err = self.run_bzr("add .bzr/README", retcode=3)[1]
        self.assertContainsRe(err, r"ERROR:.*\.bzr.*control file")
        self.build_tree([".bzr/crescent"])
        err = self.run_bzr("add .bzr/crescent", retcode=3)[1]
        self.assertContainsRe(err, r"ERROR:.*\.bzr.*control file")

    def test_add_via_symlink(self):
        self.requireFeature(features.SymlinkFeature(self.test_dir))
        self.make_branch_and_tree("source")
        self.build_tree(["source/top.txt"])
        os.symlink("source", "link")
        out = self.run_bzr(["add", "link/top.txt"])[0]
        self.assertEqual(out, "adding top.txt\n")

    def test_add_symlink_to_abspath(self):
        self.requireFeature(features.SymlinkFeature(self.test_dir))
        self.make_branch_and_tree("tree")
        os.symlink(osutils.abspath("target"), "tree/link")
        out = self.run_bzr(["add", "tree/link"])[0]
        self.assertEqual(out, "adding link\n")

    def test_add_not_child(self):
        # https://bugs.launchpad.net/bzr/+bug/98735
        sr = script.ScriptRunner()
        self.make_branch_and_tree("tree1")
        self.make_branch_and_tree("tree2")
        self.build_tree(["tree1/a", "tree2/b"])
        sr.run_script(
            self,
            """
        $ brz add tree1/a tree2/b
        2>brz: ERROR: Path "...tree2/b" is not a child of path "...tree1"
        """,
        )

    def test_add_multiple_files_in_unicode_cwd(self):
        """Adding multiple files in a non-ascii cwd, see lp:686611."""
        self.requireFeature(features.UnicodeFilenameFeature)
        self.make_branch_and_tree("\xa7")
        self.build_tree(["\xa7/a", "\xa7/b"])
        out, err = self.run_bzr(["add", "a", "b"], working_dir="\xa7")
        self.assertEqual(out, "adding a\nadding b\n")
        self.assertEqual(err, "")

    def test_add_skip_large_files(self):
        """Test skipping files larger than add.maximum_file_size."""
        tree = self.make_branch_and_tree(".")
        self.build_tree(["small.txt", "big.txt", "big2.txt"])
        self.build_tree_contents([("small.txt", b"0\n")])
        self.build_tree_contents([("big.txt", b"01234567890123456789\n")])
        self.build_tree_contents([("big2.txt", b"01234567890123456789\n")])
        tree.branch.get_config_stack().set("add.maximum_file_size", 5)
        out = self.run_bzr("add")[0]
        results = sorted(out.rstrip("\n").split("\n"))
        self.assertEqual(["adding small.txt"], results)
        # named items never skipped, even if over max
        out, err = self.run_bzr(["add", "big2.txt"])
        results = sorted(out.rstrip("\n").split("\n"))
        self.assertEqual(["adding big2.txt"], results)
        self.assertEqual("", err)
        tree.branch.get_config_stack().set("add.maximum_file_size", 30)
        out = self.run_bzr("add")[0]
        results = sorted(out.rstrip("\n").split("\n"))
        self.assertEqual(["adding big.txt"], results)

    def test_add_backslash(self):
        # pad.lv/165151
        if os.path.sep == "\\":
            # TODO(jelmer): Test that backslashes are appropriately
            # ignored?
            raise tests.TestNotApplicable(
                "unable to add filenames with backslashes where "
                " it is the path separator"
            )
        self.make_branch_and_tree(".")
        self.build_tree(["\\"])
        self.assertEqual("adding \\\n", self.run_bzr("add \\\\")[0])
        self.assertEqual("\\\n", self.run_bzr("ls --versioned")[0])
