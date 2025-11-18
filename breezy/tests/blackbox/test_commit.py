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


"""Tests for the commit CLI of bzr."""

import doctest
import os
import re
import sys

from testtools.matchers import DocTestMatches

from ... import ignores, msgeditor, osutils
from ...controldir import ControlDir
from .. import TestCaseWithTransport, features, test_foreign
from ..test_bedding import override_whoami


class TestCommit(TestCaseWithTransport):
    def test_05_empty_commit(self):
        """Commit of tree with no versioned files should fail."""
        # If forced, it should succeed, but this is not tested here.
        self.make_branch_and_tree(".")
        self.build_tree(["hello.txt"])
        out, err = self.run_bzr("commit -m empty", retcode=3)
        self.assertEqual("", out)
        # Two ugly bits here.
        # 1) We really don't want 'aborting commit write group' anymore.
        # 2) brz: ERROR: is a really long line, so we wrap it with '\'
        self.assertThat(
            err,
            DocTestMatches(
                """\
Committing to: ...
brz: ERROR: No changes to commit.\
 Please 'brz add' the files you want to commit,\
 or use --unchanged to force an empty commit.
""",
                flags=doctest.ELLIPSIS | doctest.REPORT_UDIFF,
            ),
        )

    def test_commit_success(self):
        """Successful commit should not leave behind a bzr-commit-* file."""
        self.make_branch_and_tree(".")
        self.run_bzr("commit --unchanged -m message")
        self.assertEqual("", self.run_bzr("unknowns")[0])

        # same for unicode messages
        self.run_bzr(["commit", "--unchanged", "-m", "foo\xb5"])
        self.assertEqual("", self.run_bzr("unknowns")[0])

    def test_commit_lossy_native(self):
        """A --lossy option to commit is supported."""
        self.make_branch_and_tree(".")
        self.run_bzr("commit --lossy --unchanged -m message")
        self.assertEqual("", self.run_bzr("unknowns")[0])

    def test_commit_lossy_foreign(self):
        test_foreign.register_dummy_foreign_for_test(self)
        self.make_branch_and_tree(".", format=test_foreign.DummyForeignVcsDirFormat())
        self.run_bzr("commit --lossy --unchanged -m message")
        output = self.run_bzr("revision-info")[0]
        self.assertTrue(output.startswith("1 dummy-"))

    def test_commit_with_path(self):
        """Commit tree with path of root specified."""
        a_tree = self.make_branch_and_tree("a")
        self.build_tree(["a/a_file"])
        a_tree.add("a_file")
        self.run_bzr(["commit", "-m", "first commit", "a"])

        b_tree = a_tree.controldir.sprout("b").open_workingtree()
        self.build_tree_contents([("b/a_file", b"changes in b")])
        self.run_bzr(["commit", "-m", "first commit in b", "b"])

        self.build_tree_contents([("a/a_file", b"new contents")])
        self.run_bzr(["commit", "-m", "change in a", "a"])

        b_tree.merge_from_branch(a_tree.branch)
        self.assertEqual(len(b_tree.conflicts()), 1)
        self.run_bzr("resolved b/a_file")
        self.run_bzr(["commit", "-m", "merge into b", "b"])

    def test_10_verbose_commit(self):
        """Add one file and examine verbose commit output."""
        tree = self.make_branch_and_tree(".")
        self.build_tree(["hello.txt"])
        tree.add("hello.txt")
        out, err = self.run_bzr("commit -m added")
        self.assertEqual("", out)
        self.assertContainsRe(
            err,
            "^Committing to: .*\nadded hello.txt\nCommitted revision 1.\n$",
        )

    def prepare_simple_history(self):
        """Prepare and return a working tree with one commit of one file."""
        # Commit with modified file should say so
        wt = ControlDir.create_standalone_workingtree(".")
        self.build_tree(["hello.txt", "extra.txt"])
        wt.add(["hello.txt"])
        wt.commit(message="added")
        return wt

    def test_verbose_commit_modified(self):
        # Verbose commit of modified file should say so
        self.prepare_simple_history()
        self.build_tree_contents([("hello.txt", b"new contents")])
        out, err = self.run_bzr("commit -m modified")
        self.assertEqual("", out)
        self.assertContainsRe(
            err,
            "^Committing to: .*\nmodified hello\\.txt\nCommitted revision 2\\.\n$",
        )

    def test_unicode_commit_message_is_filename(self):
        """Unicode commit message same as a filename (Bug #563646)."""
        self.requireFeature(features.UnicodeFilenameFeature)
        file_name = "\N{EURO SIGN}"
        self.run_bzr(["init"])
        with open(file_name, "w") as f:
            f.write("hello world")
        self.run_bzr(["add"])
        out, err = self.run_bzr(["commit", "-m", file_name])
        reflags = re.MULTILINE | re.DOTALL | re.UNICODE
        osutils.get_terminal_encoding()
        self.assertContainsRe(err, "The commit message is a file name:", flags=reflags)

        # Run same test with a filename that causes encode
        # error for the terminal encoding. We do this
        # by forcing terminal encoding of ascii for
        # osutils.get_terminal_encoding which is used
        # by ui.text.show_warning
        default_get_terminal_enc = osutils.get_terminal_encoding
        try:
            osutils.get_terminal_encoding = lambda trace=None: "ascii"
            file_name = "foo\u1234"
            with open(file_name, "w") as f:
                f.write("hello world")
            self.run_bzr(["add"])
            _out, err = self.run_bzr(["commit", "-m", file_name])
            reflags = re.MULTILINE | re.DOTALL | re.UNICODE
            osutils.get_terminal_encoding()
            self.assertContainsRe(
                err, "The commit message is a file name:", flags=reflags
            )
        finally:
            osutils.get_terminal_encoding = default_get_terminal_enc

    def test_non_ascii_file_unversioned_utf8(self):
        self.requireFeature(features.UnicodeFilenameFeature)
        tree = self.make_branch_and_tree(".")
        self.build_tree(["f"])
        tree.add(["f"])
        _out, err = self.run_bzr_raw(
            ["commit", "-m", "Wrong filename", "\xa7"], encoding="utf-8", retcode=3
        )
        self.assertContainsRe(err, b'(?m)not versioned: "\xc2\xa7"$')

    def test_non_ascii_file_unversioned_iso_8859_5(self):
        self.requireFeature(features.UnicodeFilenameFeature)
        tree = self.make_branch_and_tree(".")
        self.build_tree(["f"])
        tree.add(["f"])
        _out, err = self.run_bzr_raw(
            ["commit", "-m", "Wrong filename", "\xa7"], encoding="iso-8859-5", retcode=3
        )
        self.assertNotContainsString(err, b"\xc2\xa7")
        self.assertContainsRe(err, b'(?m)not versioned: "\xfd"$')

    def test_warn_about_forgotten_commit_message(self):
        """Test that the lack of -m parameter is caught."""
        wt = self.make_branch_and_tree(".")
        self.build_tree(["one", "two"])
        wt.add(["two"])
        _out, err = self.run_bzr("commit -m one two")
        self.assertContainsRe(err, "The commit message is a file name")

    def test_verbose_commit_renamed(self):
        # Verbose commit of renamed file should say so
        wt = self.prepare_simple_history()
        wt.rename_one("hello.txt", "gutentag.txt")
        out, err = self.run_bzr("commit -m renamed")
        self.assertEqual("", out)
        self.assertContainsRe(
            err,
            "^Committing to: .*\n"
            "renamed hello\\.txt => gutentag\\.txt\n"
            "Committed revision 2\\.$\n",
        )

    def test_verbose_commit_moved(self):
        # Verbose commit of file moved to new directory should say so
        wt = self.prepare_simple_history()
        os.mkdir("subdir")
        wt.add(["subdir"])
        wt.rename_one("hello.txt", "subdir/hello.txt")
        out, err = self.run_bzr("commit -m renamed")
        self.assertEqual("", out)
        self.assertEqual(
            {
                "Committing to: {}/".format(osutils.getcwd()),
                "added subdir",
                "renamed hello.txt => subdir/hello.txt",
                "Committed revision 2.",
                "",
            },
            set(err.split("\n")),
        )

    def test_verbose_commit_with_unknown(self):
        """Unknown files should not be listed by default in verbose output."""
        # Is that really the best policy?
        wt = ControlDir.create_standalone_workingtree(".")
        self.build_tree(["hello.txt", "extra.txt"])
        wt.add(["hello.txt"])
        out, err = self.run_bzr("commit -m added")
        self.assertEqual("", out)
        self.assertContainsRe(
            err,
            "^Committing to: .*\nadded hello\\.txt\nCommitted revision 1\\.\n$",
        )

    def test_verbose_commit_with_unchanged(self):
        """Unchanged files should not be listed by default in verbose output."""
        tree = self.make_branch_and_tree(".")
        self.build_tree(["hello.txt", "unchanged.txt"])
        tree.add("unchanged.txt")
        self.run_bzr("commit -m unchanged unchanged.txt")
        tree.add("hello.txt")
        out, err = self.run_bzr("commit -m added")
        self.assertEqual("", out)
        self.assertContainsRe(
            err,
            "^Committing to: .*\nadded hello\\.txt\nCommitted revision 2\\.$\n",
        )

    def test_verbose_commit_includes_master_location(self):
        """Location of master is displayed when committing to bound branch."""
        a_tree = self.make_branch_and_tree("a")
        self.build_tree(["a/b"])
        a_tree.add("b")
        a_tree.commit(message="Initial message")

        a_tree.branch.create_checkout("b")
        expected = "{}/".format(osutils.abspath("a"))
        _out, err = self.run_bzr("commit -m blah --unchanged", working_dir="b")
        self.assertEqual(
            err, "Committing to: {}\nCommitted revision 2.\n".format(expected)
        )

    def test_commit_sanitizes_CR_in_message(self):
        # See bug #433779, basically Emacs likes to pass '\r\n' style line
        # endings to 'brz commit -m ""' which breaks because we don't allow
        # '\r' in commit messages. (Mostly because of issues where XML style
        # formats arbitrarily strip it out of the data while parsing.)
        # To make life easier for users, we just always translate '\r\n' =>
        # '\n'. And '\r' => '\n'.
        a_tree = self.make_branch_and_tree("a")
        self.build_tree(["a/b"])
        a_tree.add("b")
        self.run_bzr(
            ["commit", "-m", "a string\r\n\r\nwith mixed\r\rendings\n"], working_dir="a"
        )
        rev_id = a_tree.branch.last_revision()
        rev = a_tree.branch.repository.get_revision(rev_id)
        self.assertEqualDiff("a string\n\nwith mixed\n\nendings\n", rev.message)

    def test_commit_merge_reports_all_modified_files(self):
        # the commit command should show all the files that are shown by
        # brz diff or brz status when committing, even when they were not
        # changed by the user but rather through doing a merge.
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
        with other_tree.lock_write():
            # perform the needed actions on the files and dirs.
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
        this_tree.merge_from_branch(other_tree.branch)
        out, err = self.run_bzr("commit -m added", working_dir="this")
        self.assertEqual("", out)
        self.assertEqual(
            {
                "Committing to: {}/".format(osutils.pathjoin(osutils.getcwd(), "this")),
                "modified filetomodify",
                "added newdir",
                "added newfile",
                "renamed dirtorename => renameddir",
                "renamed filetorename => renamedfile",
                "renamed dirtoreparent => renameddir/reparenteddir",
                "renamed filetoreparent => renameddir/reparentedfile",
                "deleted dirtoremove",
                "deleted filetoremove",
                "Committed revision 2.",
                "",
            },
            set(err.split("\n")),
        )

    def test_empty_commit_message(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree_contents([("foo.c", b"int main() {}")])
        tree.add("foo.c")
        self.run_bzr('commit -m ""')

    def test_other_branch_commit(self):
        # this branch is to ensure consistent behaviour, whether we're run
        # inside a branch, or not.
        self.make_branch_and_tree(".")
        inner_tree = self.make_branch_and_tree("branch")
        self.build_tree_contents(
            [("branch/foo.c", b"int main() {}"), ("branch/bar.c", b"int main() {}")]
        )
        inner_tree.add(["foo.c", "bar.c"])
        # can't commit files in different trees; sane error
        self.run_bzr("commit -m newstuff branch/foo.c .", retcode=3)
        # can commit to branch - records foo.c only
        self.run_bzr("commit -m newstuff branch/foo.c")
        # can commit to branch - records bar.c
        self.run_bzr("commit -m newstuff branch")
        # No changes left
        self.run_bzr_error(["No changes to commit"], "commit -m newstuff branch")

    def test_out_of_date_tree_commit(self):
        # check we get an error code and a clear message committing with an out
        # of date checkout
        tree = self.make_branch_and_tree("branch")
        # make a checkout
        tree.branch.create_checkout("checkout", lightweight=True)
        # commit to the original branch to make the checkout out of date
        tree.commit("message branch", allow_pointless=True)
        # now commit to the checkout should emit
        # ERROR: Out of date with the branch, 'brz update' is suggested
        output = self.run_bzr(
            "commit --unchanged -m checkout_message checkout", retcode=3
        )
        self.assertEqual(
            output,
            (
                "",
                "brz: ERROR: Working tree is out of date, please run 'brz update'.\n",
            ),
        )

    def test_local_commit_unbound(self):
        # a --local commit on an unbound branch is an error
        self.make_branch_and_tree(".")
        out, err = self.run_bzr("commit --local", retcode=3)
        self.assertEqualDiff("", out)
        self.assertEqualDiff(
            "brz: ERROR: Cannot perform local-only commits on unbound branches.\n",
            err,
        )

    def test_commit_a_text_merge_in_a_checkout(self):
        # checkouts perform multiple actions in a transaction across bond
        # branches and their master, and have been observed to fail in the
        # past. This is a user story reported to fail in bug #43959 where
        # a merge done in a checkout (using the update command) failed to
        # commit correctly.
        trunk = self.make_branch_and_tree("trunk")

        u1 = trunk.branch.create_checkout("u1")
        self.build_tree_contents([("u1/hosts", b"initial contents\n")])
        u1.add("hosts")
        self.run_bzr("commit -m add-hosts u1")

        trunk.branch.create_checkout("u2")
        self.build_tree_contents([("u2/hosts", b"altered in u2\n")])
        self.run_bzr("commit -m checkin-from-u2 u2")

        # make an offline commits
        self.build_tree_contents([("u1/hosts", b"first offline change in u1\n")])
        self.run_bzr("commit -m checkin-offline --local u1")

        # now try to pull in online work from u2, and then commit our offline
        # work as a merge
        # retcode 1 as we expect a text conflict
        self.run_bzr("update u1", retcode=1)
        self.assertFileEqual(
            b"""\
<<<<<<< TREE
first offline change in u1
=======
altered in u2
>>>>>>> MERGE-SOURCE
""",
            "u1/hosts",
        )

        self.run_bzr("resolved u1/hosts")
        # add a text change here to represent resolving the merge conflicts in
        # favour of a new version of the file not identical to either the u1
        # version or the u2 version.
        self.build_tree_contents([("u1/hosts", b"merge resolution\n")])
        self.run_bzr("commit -m checkin-merge-of-the-offline-work-from-u1 u1")

    def test_commit_exclude_excludes_modified_files(self):
        """Commit -x foo should ignore changes to foo."""
        tree = self.make_branch_and_tree(".")
        self.build_tree(["a", "b", "c"])
        tree.smart_add(["."])
        out, err = self.run_bzr(["commit", "-m", "test", "-x", "b"])
        self.assertFalse("added b" in out)
        self.assertFalse("added b" in err)
        # If b was excluded it will still be 'added' in status.
        out, err = self.run_bzr(["added"])
        self.assertEqual("b\n", out)
        self.assertEqual("", err)

    def test_commit_exclude_twice_uses_both_rules(self):
        """Commit -x foo -x bar should ignore changes to foo and bar."""
        tree = self.make_branch_and_tree(".")
        self.build_tree(["a", "b", "c"])
        tree.smart_add(["."])
        out, err = self.run_bzr(["commit", "-m", "test", "-x", "b", "-x", "c"])
        self.assertFalse("added b" in out)
        self.assertFalse("added c" in out)
        self.assertFalse("added b" in err)
        self.assertFalse("added c" in err)
        # If b was excluded it will still be 'added' in status.
        out, err = self.run_bzr(["added"])
        self.assertTrue("b\n" in out)
        self.assertTrue("c\n" in out)
        self.assertEqual("", err)

    def test_commit_respects_spec_for_removals(self):
        """Commit with a file spec should only commit removals that match."""
        t = self.make_branch_and_tree(".")
        self.build_tree(["file-a", "dir-a/", "dir-a/file-b"])
        t.add(["file-a", "dir-a", "dir-a/file-b"])
        t.commit("Create")
        t.remove(["file-a", "dir-a/file-b"])
        result = self.run_bzr("commit . -m removed-file-b", working_dir="dir-a")[1]
        self.assertNotContainsRe(result, "file-a")
        result = self.run_bzr("status", working_dir="dir-a")[0]
        self.assertContainsRe(result, "removed:\n  file-a")

    def test_strict_commit(self):
        """Commit with --strict works if everything is known."""
        ignores._set_user_ignores([])
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/a"])
        tree.add("a")
        # A simple change should just work
        self.run_bzr("commit --strict -m adding-a", working_dir="tree")

    def test_strict_commit_no_changes(self):
        """Commit --strict gives "no changes" if there is nothing to commit."""
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/a"])
        tree.add("a")
        tree.commit("adding a")

        # With no changes, it should just be 'no changes'
        # Make sure that commit is failing because there is nothing to do
        self.run_bzr_error(
            ["No changes to commit"],
            "commit --strict -m no-changes",
            working_dir="tree",
        )

        # But --strict doesn't care if you supply --unchanged
        self.run_bzr("commit --strict --unchanged -m no-changes", working_dir="tree")

    def test_strict_commit_unknown(self):
        """Commit --strict fails if a file is unknown."""
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/a"])
        tree.add("a")
        tree.commit("adding a")

        # Add one file so there is a change, but forget the other
        self.build_tree(["tree/b", "tree/c"])
        tree.add("b")
        self.run_bzr_error(
            ["Commit refused because there are unknown files"],
            "commit --strict -m add-b",
            working_dir="tree",
        )

        # --no-strict overrides --strict
        self.run_bzr("commit --strict -m add-b --no-strict", working_dir="tree")

    def test_fixes_bug_output(self):
        """Commit --fixes=lp:23452 succeeds without output."""
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/hello.txt"])
        tree.add("hello.txt")
        output, err = self.run_bzr("commit -m hello --fixes=lp:23452 tree/hello.txt")
        self.assertEqual("", output)
        self.assertContainsRe(
            err, "Committing to: .*\nadded hello\\.txt\nCommitted revision 1\\.\n"
        )

    def test_fixes_bug_unicode(self):
        """Commit --fixes=lp:unicode succeeds without output."""
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/hello.txt"])
        tree.add("hello.txt")
        output, err = self.run_bzr_raw(
            ["commit", "-m", "hello", "--fixes=generic:\u20ac", "tree/hello.txt"],
            encoding="utf-8",
            retcode=3,
        )
        self.assertEqual(b"", output)
        self.assertContainsRe(
            err,
            b"brz: ERROR: Unrecognized bug generic:\xe2\x82\xac\\. Commit refused.\n",
        )

    def test_no_bugs_no_properties(self):
        """If no bugs are fixed, the bugs property is not set.

        see https://beta.launchpad.net/bzr/+bug/109613
        """
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/hello.txt"])
        tree.add("hello.txt")
        self.run_bzr("commit -m hello tree/hello.txt")
        # Get the revision properties, ignoring the branch-nick property, which
        # we don't care about for this test.
        last_rev = tree.branch.repository.get_revision(tree.last_revision())
        properties = dict(last_rev.properties)
        del properties["branch-nick"]
        self.assertFalse("bugs" in properties)

    def test_bugs_sets_property(self):
        """Commit --bugs=lp:234 sets the lp:234 revprop to 'related'."""
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/hello.txt"])
        tree.add("hello.txt")
        self.run_bzr("commit -m hello --bugs=lp:234 tree/hello.txt")

        # Get the revision properties, ignoring the branch-nick property, which
        # we don't care about for this test.
        last_rev = tree.branch.repository.get_revision(tree.last_revision())
        properties = dict(last_rev.properties)
        del properties["branch-nick"]

        self.assertEqual({"bugs": "https://launchpad.net/bugs/234 related"}, properties)

    def test_fixes_bug_sets_property(self):
        """Commit --fixes=lp:234 sets the lp:234 revprop to 'fixed'."""
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/hello.txt"])
        tree.add("hello.txt")
        self.run_bzr("commit -m hello --fixes=lp:234 tree/hello.txt")

        # Get the revision properties, ignoring the branch-nick property, which
        # we don't care about for this test.
        last_rev = tree.branch.repository.get_revision(tree.last_revision())
        properties = dict(last_rev.properties)
        del properties["branch-nick"]

        self.assertEqual({"bugs": "https://launchpad.net/bugs/234 fixed"}, properties)

    def test_fixes_multiple_bugs_sets_properties(self):
        """--fixes can be used more than once to show that bugs are fixed."""
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/hello.txt"])
        tree.add("hello.txt")
        self.run_bzr("commit -m hello --fixes=lp:123 --fixes=lp:235 tree/hello.txt")

        # Get the revision properties, ignoring the branch-nick property, which
        # we don't care about for this test.
        last_rev = tree.branch.repository.get_revision(tree.last_revision())
        properties = dict(last_rev.properties)
        del properties["branch-nick"]

        self.assertEqual(
            {
                "bugs": "https://launchpad.net/bugs/123 fixed\n"
                "https://launchpad.net/bugs/235 fixed"
            },
            properties,
        )

    def test_fixes_bug_with_alternate_trackers(self):
        """--fixes can be used on a properly configured branch to mark bug
        fixes on multiple trackers.
        """
        tree = self.make_branch_and_tree("tree")
        tree.branch.get_config().set_user_option(
            "trac_twisted_url", "http://twistedmatrix.com/trac"
        )
        self.build_tree(["tree/hello.txt"])
        tree.add("hello.txt")
        self.run_bzr("commit -m hello --fixes=lp:123 --fixes=twisted:235 tree/")

        # Get the revision properties, ignoring the branch-nick property, which
        # we don't care about for this test.
        last_rev = tree.branch.repository.get_revision(tree.last_revision())
        properties = dict(last_rev.properties)
        del properties["branch-nick"]

        self.assertEqual(
            {
                "bugs": "https://launchpad.net/bugs/123 fixed\n"
                "http://twistedmatrix.com/trac/ticket/235 fixed"
            },
            properties,
        )

    def test_fixes_unknown_bug_prefix(self):
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/hello.txt"])
        tree.add("hello.txt")
        self.run_bzr_error(
            ["Unrecognized bug {}. Commit refused.".format("xxx:123")],
            "commit -m add-b --fixes=xxx:123",
            working_dir="tree",
        )

    def test_fixes_bug_with_default_tracker(self):
        """Commit --fixes=234 uses the default bug tracker."""
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/hello.txt"])
        tree.add("hello.txt")
        self.run_bzr_error(
            [
                "brz: ERROR: No tracker specified for bug 123. Use the form "
                "'tracker:id' or specify a default bug tracker using the "
                "`bugtracker` option.\n"
                'See "brz help bugs" for more information on this feature. '
                "Commit refused."
            ],
            "commit -m add-b --fixes=123",
            working_dir="tree",
        )
        tree.branch.get_config_stack().set("bugtracker", "lp")
        self.run_bzr("commit -m hello --fixes=234 tree/hello.txt")
        last_rev = tree.branch.repository.get_revision(tree.last_revision())
        self.assertEqual(
            "https://launchpad.net/bugs/234 fixed", last_rev.properties["bugs"]
        )

    def test_fixes_invalid_bug_number(self):
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/hello.txt"])
        tree.add("hello.txt")
        self.run_bzr_error(
            [
                "Did not understand bug identifier orange: Must be an integer. "
                'See "brz help bugs" for more information on this feature.\n'
                "Commit refused."
            ],
            "commit -m add-b --fixes=lp:orange",
            working_dir="tree",
        )

    def test_fixes_invalid_argument(self):
        """Raise an appropriate error when the fixes argument isn't tag:id."""
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/hello.txt"])
        tree.add("hello.txt")
        self.run_bzr_error(
            [
                r"Invalid bug orange:apples:bananas. Must be in the form of "
                r"'tracker:id'\. See \"brz help bugs\" for more information on "
                r"this feature.\nCommit refused\."
            ],
            "commit -m add-b --fixes=orange:apples:bananas",
            working_dir="tree",
        )

    def test_no_author(self):
        """If the author is not specified, the author property is not set."""
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/hello.txt"])
        tree.add("hello.txt")
        self.run_bzr("commit -m hello tree/hello.txt")
        last_rev = tree.branch.repository.get_revision(tree.last_revision())
        properties = last_rev.properties
        self.assertFalse("author" in properties)

    def test_author_sets_property(self):
        """Commit --author='John Doe <jdoe@example.com>' sets the author
        revprop.
        """
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/hello.txt"])
        tree.add("hello.txt")
        self.run_bzr(
            [
                "commit",
                "-m",
                "hello",
                "--author",
                "John D\xf6 <jdoe@example.com>",
                "tree/hello.txt",
            ]
        )
        last_rev = tree.branch.repository.get_revision(tree.last_revision())
        properties = last_rev.properties
        self.assertEqual("John D\xf6 <jdoe@example.com>", properties["authors"])

    def test_author_no_email(self):
        """Author's name without an email address is allowed, too."""
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/hello.txt"])
        tree.add("hello.txt")
        _out, _err = self.run_bzr("commit -m hello --author='John Doe' tree/hello.txt")
        last_rev = tree.branch.repository.get_revision(tree.last_revision())
        properties = last_rev.properties
        self.assertEqual("John Doe", properties["authors"])

    def test_multiple_authors(self):
        """Multiple authors can be specyfied, and all are stored."""
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/hello.txt"])
        tree.add("hello.txt")
        _out, _err = self.run_bzr(
            "commit -m hello --author='John Doe' --author='Jane Rey' tree/hello.txt"
        )
        last_rev = tree.branch.repository.get_revision(tree.last_revision())
        properties = last_rev.properties
        self.assertEqual("John Doe\nJane Rey", properties["authors"])

    def test_commit_time(self):
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/hello.txt"])
        tree.add("hello.txt")
        _out, _err = self.run_bzr(
            "commit -m hello --commit-time='2009-10-10 08:00:00 +0100' tree/hello.txt"
        )
        last_rev = tree.branch.repository.get_revision(tree.last_revision())
        self.assertEqual(
            "Sat 2009-10-10 08:00:00 +0100",
            osutils.format_date(last_rev.timestamp, last_rev.timezone),
        )

    def test_commit_time_bad_time(self):
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/hello.txt"])
        tree.add("hello.txt")
        _out, err = self.run_bzr(
            "commit -m hello --commit-time='NOT A TIME' tree/hello.txt", retcode=3
        )
        self.assertStartsWith(err, "brz: ERROR: Could not parse --commit-time:")

    def test_commit_time_missing_tz(self):
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/hello.txt"])
        tree.add("hello.txt")
        _out, err = self.run_bzr(
            "commit -m hello --commit-time='2009-10-10 08:00:00' tree/hello.txt",
            retcode=3,
        )
        self.assertStartsWith(err, "brz: ERROR: Could not parse --commit-time:")
        # Test that it is actually checking and does not simply crash with
        # some other exception
        self.assertContainsString(err, "missing a timezone offset")

    def test_partial_commit_with_renames_in_tree(self):
        # this test illustrates bug #140419
        t = self.make_branch_and_tree(".")
        self.build_tree(["dir/", "dir/a", "test"])
        t.add(["dir/", "dir/a", "test"])
        t.commit("initial commit")
        # important part: file dir/a should change parent
        # and should appear before old parent
        # then during partial commit we have error
        # parent_id {dir-XXX} not in inventory
        t.rename_one("dir/a", "a")
        self.build_tree_contents([("test", b"changes in test")])
        # partial commit
        out, err = self.run_bzr('commit test -m "partial commit"')
        self.assertEqual("", out)
        self.assertContainsRe(err, r"modified test\nCommitted revision 2.")

    def test_commit_readonly_checkout(self):
        # https://bugs.launchpad.net/bzr/+bug/129701
        # "UnlockableTransport error trying to commit in checkout of readonly
        # branch"
        self.make_branch("master")
        master = ControlDir.open_from_transport(
            self.get_readonly_transport("master")
        ).open_branch()
        master.create_checkout("checkout")
        _out, err = self.run_bzr(
            ["commit", "--unchanged", "-mfoo", "checkout"], retcode=3
        )
        self.assertContainsRe(err, r"^brz: ERROR: Cannot lock.*readonly transport")

    def setup_editor(self):
        # Test that commit template hooks work
        if sys.platform == "win32":
            with open("fed.bat", "w") as f:
                f.write("@rem dummy fed")
            self.overrideEnv("BRZ_EDITOR", "fed.bat")
        else:
            with open("fed.sh", "wb") as f:
                f.write(b"#!/bin/sh\n")
            os.chmod("fed.sh", 0o755)
            self.overrideEnv("BRZ_EDITOR", "./fed.sh")

    def setup_commit_with_template(self):
        self.setup_editor()
        msgeditor.hooks.install_named_hook(
            "commit_message_template",
            lambda commit_obj, msg: "save me some typing\n",
            None,
        )
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/hello.txt"])
        tree.add("hello.txt")
        return tree

    def test_edit_empty_message(self):
        tree = self.make_branch_and_tree("tree")
        self.setup_editor()
        self.build_tree(["tree/hello.txt"])
        tree.add("hello.txt")
        _out, err = self.run_bzr("commit tree/hello.txt", retcode=3, stdin="y\n")
        self.assertContainsRe(err, "brz: ERROR: Empty commit message specified")

    def test_commit_hook_template_accepted(self):
        tree = self.setup_commit_with_template()
        _out, _err = self.run_bzr("commit tree/hello.txt", stdin="y\n")
        last_rev = tree.branch.repository.get_revision(tree.last_revision())
        self.assertEqual("save me some typing\n", last_rev.message)

    def test_commit_hook_template_rejected(self):
        tree = self.setup_commit_with_template()
        expected = tree.last_revision()
        _out, _err = self.run_bzr_error(
            [
                "Empty commit message specified."
                " Please specify a commit message with either"
                " --message or --file or leave a blank message"
                ' with --message "".'
            ],
            "commit tree/hello.txt",
            stdin="n\n",
        )
        self.assertEqual(expected, tree.last_revision())

    def test_set_commit_message(self):
        msgeditor.hooks.install_named_hook(
            "set_commit_message", lambda commit_obj, msg: "save me some typing\n", None
        )
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/hello.txt"])
        tree.add("hello.txt")
        _out, _err = self.run_bzr("commit tree/hello.txt")
        last_rev = tree.branch.repository.get_revision(tree.last_revision())
        self.assertEqual("save me some typing\n", last_rev.message)

    def test_commit_without_username(self):
        """Ensure commit error if username is not set."""
        self.run_bzr(["init", "foo"])
        with open("foo/foo.txt", "w") as f:
            f.write("hello")
        self.run_bzr(["add"], working_dir="foo")
        override_whoami(self)
        self.run_bzr_error(
            ["Unable to determine your name"],
            ["commit", "-m", "initial"],
            working_dir="foo",
        )

    def test_commit_recursive_checkout(self):
        """Ensure that a commit to a recursive checkout fails cleanly."""
        self.run_bzr(["init", "test_branch"])
        self.run_bzr(["checkout", "test_branch", "test_checkout"])
        # bind to self
        self.run_bzr(["bind", "."], working_dir="test_checkout")
        with open("test_checkout/foo.txt", "w") as f:
            f.write("hello")
        self.run_bzr(["add"], working_dir="test_checkout")
        _out, _err = self.run_bzr_error(
            ["Branch.*test_checkout.*appears to be bound to itself"],
            ["commit", "-m", "addedfoo"],
            working_dir="test_checkout",
        )

    def test_mv_dirs_non_ascii(self):
        """Move directory with non-ascii name and containing files.

        Regression test for bug 185211.
        """
        tree = self.make_branch_and_tree(".")
        self.build_tree(["abc\xa7/", "abc\xa7/foo"])

        tree.add(["abc\xa7/", "abc\xa7/foo"])
        tree.commit("checkin")

        tree.rename_one("abc\xa7", "abc")

        self.run_bzr('ci -m "non-ascii mv"')
