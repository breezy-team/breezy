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

"""Tests of status command.

Most of these depend on the particular formatting used.
As such they really are blackbox tests even though some of the
tests are not using self.capture. If we add tests for the programmatic
interface later, they will be non blackbox tests.
"""

import sys
from io import BytesIO, StringIO
from os import chdir, mkdir, rmdir, unlink

from breezy.bzr import bzrdir, conflicts

from ... import errors, osutils, status
from ...osutils import pathjoin
from ...revisionspec import RevisionSpec
from ...status import show_tree_status
from .. import TestCaseWithTransport, TestSkipped


class BranchStatus(TestCaseWithTransport):
    def setUp(self):
        super().setUp()
        # As TestCase.setUp clears all hooks, we install this default
        # post_status hook handler for the test.
        status.hooks.install_named_hook(
            "post_status", status._show_shelve_summary, "brz status"
        )

    def assertStatus(
        self,
        expected_lines,
        working_tree,
        specific_files=None,
        revision=None,
        short=False,
        pending=True,
        verbose=False,
    ):
        """Run status in working_tree and look for output.

        :param expected_lines: The lines to look for.
        :param working_tree: The tree to run status in.
        """
        output_string = self.status_string(
            working_tree, specific_files, revision, short, pending, verbose
        )
        self.assertEqual(expected_lines, output_string.splitlines(True))

    def status_string(
        self,
        wt,
        specific_files=None,
        revision=None,
        short=False,
        pending=True,
        verbose=False,
    ):
        uio = self.make_utf8_encoded_stringio()
        show_tree_status(
            wt,
            specific_files=specific_files,
            to_file=uio,
            revision=revision,
            short=short,
            show_pending=pending,
            verbose=verbose,
        )
        return uio.getvalue().decode("utf-8")

    def test_branch_status(self):
        """Test basic branch status."""
        wt = self.make_branch_and_tree(".")

        # status with no commits or files - it must
        # work and show no output. We do this with no
        # commits to be sure that it's not going to fail
        # as a corner case.
        self.assertStatus([], wt)

        self.build_tree(["hello.c", "bye.c"])
        self.assertStatus(
            [
                "unknown:\n",
                "  bye.c\n",
                "  hello.c\n",
            ],
            wt,
        )
        self.assertStatus(
            [
                "?   bye.c\n",
                "?   hello.c\n",
            ],
            wt,
            short=True,
        )

        # add a commit to allow showing pending merges.
        wt.commit("create a parent to allow testing merge output")

        wt.add_parent_tree_id(b"pending@pending-0-0")
        self.assertStatus(
            [
                "unknown:\n",
                "  bye.c\n",
                "  hello.c\n",
                "pending merge tips: (use -v to see all merge revisions)\n",
                "  (ghost) pending@pending-0-0\n",
            ],
            wt,
        )
        self.assertStatus(
            [
                "unknown:\n",
                "  bye.c\n",
                "  hello.c\n",
                "pending merges:\n",
                "  (ghost) pending@pending-0-0\n",
            ],
            wt,
            verbose=True,
        )
        self.assertStatus(
            [
                "?   bye.c\n",
                "?   hello.c\n",
                "P   (ghost) pending@pending-0-0\n",
            ],
            wt,
            short=True,
        )
        self.assertStatus(
            [
                "unknown:\n",
                "  bye.c\n",
                "  hello.c\n",
            ],
            wt,
            pending=False,
        )
        self.assertStatus(
            [
                "?   bye.c\n",
                "?   hello.c\n",
            ],
            wt,
            short=True,
            pending=False,
        )

    def test_branch_status_revisions(self):
        """Tests branch status with revisions."""
        wt = self.make_branch_and_tree(".")

        self.build_tree(["hello.c", "bye.c"])
        wt.add("hello.c")
        wt.add("bye.c")
        wt.commit("Test message")

        revs = [RevisionSpec.from_string("0")]
        self.assertStatus(["added:\n", "  bye.c\n", "  hello.c\n"], wt, revision=revs)

        self.build_tree(["more.c"])
        wt.add("more.c")
        wt.commit("Another test message")

        revs.append(RevisionSpec.from_string("1"))
        self.assertStatus(
            [
                "added:\n",
                "  bye.c\n",
                "  hello.c\n",
            ],
            wt,
            revision=revs,
        )

    def test_pending(self):
        """Pending merges display works, including Unicode."""
        mkdir("./branch")
        wt = self.make_branch_and_tree("branch")
        b = wt.branch
        wt.commit("Empty commit 1")
        b_2_dir = b.controldir.sprout("./copy")
        b_2_dir.open_branch()
        wt2 = b_2_dir.open_workingtree()
        wt.commit("\N{TIBETAN DIGIT TWO} Empty commit 2")
        wt2.merge_from_branch(wt.branch)
        message = self.status_string(wt2, verbose=True)
        self.assertStartsWith(message, "pending merges:\n")
        self.assertEndsWith(message, "Empty commit 2\n")
        wt2.commit("merged")
        # must be long to make sure we see elipsis at the end
        wt.commit("Empty commit 3 " + "blah blah blah blah " * 100)
        wt2.merge_from_branch(wt.branch)
        message = self.status_string(wt2, verbose=True)
        self.assertStartsWith(message, "pending merges:\n")
        self.assertTrue("Empty commit 3" in message)
        self.assertEndsWith(message, "...\n")

    def test_tree_status_ignores(self):
        """Tests branch status with ignores."""
        wt = self.make_branch_and_tree(".")
        self.run_bzr("ignore *~")
        wt.commit("commit .bzrignore")
        self.build_tree(["foo.c", "foo.c~"])
        self.assertStatus(
            [
                "unknown:\n",
                "  foo.c\n",
            ],
            wt,
        )
        self.assertStatus(
            [
                "?   foo.c\n",
            ],
            wt,
            short=True,
        )

    def test_tree_status_specific_files(self):
        """Tests branch status with given specific files."""
        wt = self.make_branch_and_tree(".")

        self.build_tree(
            ["directory/", "directory/hello.c", "bye.c", "test.c", "dir2/", "missing.c"]
        )
        wt.add("directory")
        wt.add("test.c")
        wt.commit("testing")
        wt.add("missing.c")
        unlink("missing.c")

        self.assertStatus(
            [
                "missing:\n",
                "  missing.c\n",
                "unknown:\n",
                "  bye.c\n",
                "  dir2/\n",
                "  directory/hello.c\n",
            ],
            wt,
        )

        self.assertStatus(
            [
                "?   bye.c\n",
                "?   dir2/\n",
                "?   directory/hello.c\n",
                "+!  missing.c\n",
            ],
            wt,
            short=True,
        )

        tof = StringIO()
        self.assertRaises(
            errors.PathsDoNotExist,
            show_tree_status,
            wt,
            specific_files=["bye.c", "test.c", "absent.c"],
            to_file=tof,
        )

        tof = StringIO()
        show_tree_status(wt, specific_files=["directory"], to_file=tof)
        tof.seek(0)
        self.assertEqual(tof.readlines(), ["unknown:\n", "  directory/hello.c\n"])
        tof = StringIO()
        show_tree_status(wt, specific_files=["directory"], to_file=tof, short=True)
        tof.seek(0)
        self.assertEqual(tof.readlines(), ["?   directory/hello.c\n"])

        tof = StringIO()
        show_tree_status(wt, specific_files=["dir2"], to_file=tof)
        tof.seek(0)
        self.assertEqual(tof.readlines(), ["unknown:\n", "  dir2/\n"])
        tof = StringIO()
        show_tree_status(wt, specific_files=["dir2"], to_file=tof, short=True)
        tof.seek(0)
        self.assertEqual(tof.readlines(), ["?   dir2/\n"])

        tof = StringIO()
        revs = [RevisionSpec.from_string("0"), RevisionSpec.from_string("1")]
        show_tree_status(
            wt, specific_files=["test.c"], to_file=tof, short=True, revision=revs
        )
        tof.seek(0)
        self.assertEqual(tof.readlines(), ["+N  test.c\n"])

        tof = StringIO()
        show_tree_status(wt, specific_files=["missing.c"], to_file=tof)
        tof.seek(0)
        self.assertEqual(tof.readlines(), ["missing:\n", "  missing.c\n"])

        tof = StringIO()
        show_tree_status(wt, specific_files=["missing.c"], to_file=tof, short=True)
        tof.seek(0)
        self.assertEqual(tof.readlines(), ["+!  missing.c\n"])

    def test_specific_files_conflicts(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree(["dir2/"])
        tree.add("dir2")
        tree.commit("added dir2")
        tree.set_conflicts([conflicts.ContentsConflict("foo")])
        tof = BytesIO()
        show_tree_status(tree, specific_files=["dir2"], to_file=tof)
        self.assertEqualDiff(b"", tof.getvalue())
        tree.set_conflicts([conflicts.ContentsConflict("dir2")])
        tof = StringIO()
        show_tree_status(tree, specific_files=["dir2"], to_file=tof)
        self.assertEqualDiff(
            "conflicts:\n  Contents conflict in dir2\n", tof.getvalue()
        )

        tree.set_conflicts([conflicts.ContentsConflict("dir2/file1")])
        tof = StringIO()
        show_tree_status(tree, specific_files=["dir2"], to_file=tof)
        self.assertEqualDiff(
            "conflicts:\n  Contents conflict in dir2/file1\n", tof.getvalue()
        )

    def _prepare_nonexistent(self):
        wt = self.make_branch_and_tree(".")
        self.assertStatus([], wt)
        self.build_tree(
            [
                "FILE_A",
                "FILE_B",
                "FILE_C",
                "FILE_D",
                "FILE_E",
            ]
        )
        wt.add("FILE_A")
        wt.add("FILE_B")
        wt.add("FILE_C")
        wt.add("FILE_D")
        wt.add("FILE_E")
        wt.commit("Create five empty files.")
        with open("FILE_B", "w") as f:
            f.write("Modification to file FILE_B.")
        with open("FILE_C", "w") as f:
            f.write("Modification to file FILE_C.")
        unlink("FILE_E")  # FILE_E will be versioned but missing
        with open("FILE_Q", "w") as f:
            f.write("FILE_Q is added but not committed.")
        wt.add("FILE_Q")  # FILE_Q will be added but not committed
        open("UNVERSIONED_BUT_EXISTING", "w")
        return wt

    def test_status_nonexistent_file(self):
        # files that don't exist in either the basis tree or working tree
        # should give an error
        wt = self._prepare_nonexistent()
        self.assertStatus(
            [
                "removed:\n",
                "  FILE_E\n",
                "added:\n",
                "  FILE_Q\n",
                "modified:\n",
                "  FILE_B\n",
                "  FILE_C\n",
                "unknown:\n",
                "  UNVERSIONED_BUT_EXISTING\n",
            ],
            wt,
        )
        self.assertStatus(
            [
                " M  FILE_B\n",
                " M  FILE_C\n",
                " D  FILE_E\n",
                "+N  FILE_Q\n",
                "?   UNVERSIONED_BUT_EXISTING\n",
            ],
            wt,
            short=True,
        )

        # Okay, everything's looking good with the existent files.
        # Let's see what happens when we throw in non-existent files.

        # brz st [--short] NONEXISTENT '
        expected = [
            "nonexistent:\n",
            "  NONEXISTENT\n",
        ]
        out, err = self.run_bzr("status NONEXISTENT", retcode=3)
        self.assertEqual(expected, out.splitlines(True))
        self.assertContainsRe(err, r".*ERROR: Path\(s\) do not exist: " "NONEXISTENT.*")
        expected = [
            "X:   NONEXISTENT\n",
        ]
        out, err = self.run_bzr("status --short NONEXISTENT", retcode=3)
        self.assertContainsRe(err, r".*ERROR: Path\(s\) do not exist: " "NONEXISTENT.*")

    def test_status_nonexistent_file_with_others(self):
        # brz st [--short] NONEXISTENT ...others..
        self._prepare_nonexistent()
        expected = [
            "removed:\n",
            "  FILE_E\n",
            "modified:\n",
            "  FILE_B\n",
            "  FILE_C\n",
            "nonexistent:\n",
            "  NONEXISTENT\n",
        ]
        out, err = self.run_bzr(
            "status NONEXISTENT FILE_A FILE_B FILE_C FILE_D FILE_E", retcode=3
        )
        self.assertEqual(expected, out.splitlines(True))
        self.assertContainsRe(err, r".*ERROR: Path\(s\) do not exist: " "NONEXISTENT.*")
        expected = [
            " M  FILE_B\n",
            " M  FILE_C\n",
            " D  FILE_E\n",
            "X   NONEXISTENT\n",
        ]
        out, err = self.run_bzr(
            "status --short NONEXISTENT FILE_A FILE_B FILE_C FILE_D FILE_E",
            retcode=3,
        )
        self.assertEqual(expected, out.splitlines(True))
        self.assertContainsRe(err, r".*ERROR: Path\(s\) do not exist: " "NONEXISTENT.*")

    def test_status_multiple_nonexistent_files(self):
        # brz st [--short] NONEXISTENT ... ANOTHER_NONEXISTENT ...
        self._prepare_nonexistent()
        expected = [
            "removed:\n",
            "  FILE_E\n",
            "modified:\n",
            "  FILE_B\n",
            "  FILE_C\n",
            "nonexistent:\n",
            "  ANOTHER_NONEXISTENT\n",
            "  NONEXISTENT\n",
        ]
        out, err = self.run_bzr(
            "status NONEXISTENT FILE_A FILE_B ANOTHER_NONEXISTENT FILE_C FILE_D FILE_E",
            retcode=3,
        )
        self.assertEqual(expected, out.splitlines(True))
        self.assertContainsRe(
            err,
            r".*ERROR: Path\(s\) do not exist: " "ANOTHER_NONEXISTENT NONEXISTENT.*",
        )
        expected = [
            " M  FILE_B\n",
            " M  FILE_C\n",
            " D  FILE_E\n",
            "X   ANOTHER_NONEXISTENT\n",
            "X   NONEXISTENT\n",
        ]
        out, err = self.run_bzr(
            "status --short NONEXISTENT "
            "FILE_A FILE_B ANOTHER_NONEXISTENT "
            "FILE_C FILE_D FILE_E",
            retcode=3,
        )
        self.assertEqual(expected, out.splitlines(True))
        self.assertContainsRe(
            err,
            r".*ERROR: Path\(s\) do not exist: " "ANOTHER_NONEXISTENT NONEXISTENT.*",
        )

    def test_status_nonexistent_file_with_unversioned(self):
        # brz st [--short] NONEXISTENT A B UNVERSIONED_BUT_EXISTING C D E Q
        self._prepare_nonexistent()
        expected = [
            "removed:\n",
            "  FILE_E\n",
            "added:\n",
            "  FILE_Q\n",
            "modified:\n",
            "  FILE_B\n",
            "  FILE_C\n",
            "unknown:\n",
            "  UNVERSIONED_BUT_EXISTING\n",
            "nonexistent:\n",
            "  NONEXISTENT\n",
        ]
        out, err = self.run_bzr(
            "status NONEXISTENT "
            "FILE_A FILE_B UNVERSIONED_BUT_EXISTING "
            "FILE_C FILE_D FILE_E FILE_Q",
            retcode=3,
        )
        self.assertEqual(expected, out.splitlines(True))
        self.assertContainsRe(err, r".*ERROR: Path\(s\) do not exist: " "NONEXISTENT.*")
        expected = sorted(
            [
                "+N  FILE_Q\n",
                "?   UNVERSIONED_BUT_EXISTING\n",
                " D  FILE_E\n",
                " M  FILE_C\n",
                " M  FILE_B\n",
                "X   NONEXISTENT\n",
            ]
        )
        out, err = self.run_bzr(
            "status --short NONEXISTENT "
            "FILE_A FILE_B UNVERSIONED_BUT_EXISTING "
            "FILE_C FILE_D FILE_E FILE_Q",
            retcode=3,
        )
        actual = out.splitlines(True)
        actual.sort()
        self.assertEqual(expected, actual)
        self.assertContainsRe(err, r".*ERROR: Path\(s\) do not exist: " "NONEXISTENT.*")

    def test_status_out_of_date(self):
        """Simulate status of out-of-date tree after remote push."""
        tree = self.make_branch_and_tree(".")
        self.build_tree_contents([("a", b"foo\n")])
        with tree.lock_write():
            tree.add(["a"])
            tree.commit("add test file")
            # simulate what happens after a remote push
            tree.set_last_revision(b"0")
        _out, err = self.run_bzr("status")
        self.assertEqual("working tree is out of date, run 'brz update'\n", err)

    def test_status_on_ignored(self):
        """Tests branch status on an unversioned file which is considered ignored.

        See https://bugs.launchpad.net/bzr/+bug/40103
        """
        self.make_branch_and_tree(".")

        self.build_tree(["test1.c", "test1.c~", "test2.c~"])
        result = self.run_bzr("status")[0]
        self.assertContainsRe(result, "unknown:\n  test1.c\n")
        short_result = self.run_bzr("status --short")[0]
        self.assertContainsRe(short_result, "\\?   test1.c\n")

        result = self.run_bzr("status test1.c")[0]
        self.assertContainsRe(result, "unknown:\n  test1.c\n")
        short_result = self.run_bzr("status --short test1.c")[0]
        self.assertContainsRe(short_result, "\\?   test1.c\n")

        result = self.run_bzr("status test1.c~")[0]
        self.assertContainsRe(result, "ignored:\n  test1.c~\n")
        short_result = self.run_bzr("status --short test1.c~")[0]
        self.assertContainsRe(short_result, "I   test1.c~\n")

        result = self.run_bzr("status test1.c~ test2.c~")[0]
        self.assertContainsRe(result, "ignored:\n  test1.c~\n  test2.c~\n")
        short_result = self.run_bzr("status --short test1.c~ test2.c~")[0]
        self.assertContainsRe(short_result, "I   test1.c~\nI   test2.c~\n")

        result = self.run_bzr("status test1.c test1.c~ test2.c~")[0]
        self.assertContainsRe(
            result, "unknown:\n  test1.c\nignored:\n  test1.c~\n  test2.c~\n"
        )
        short_result = self.run_bzr("status --short test1.c test1.c~ test2.c~")[0]
        self.assertContainsRe(
            short_result, "\\?   test1.c\nI   test1.c~\nI   test2.c~\n"
        )

    def test_status_write_lock(self):
        """Test that status works without fetching history and
        having a write lock.

        See https://bugs.launchpad.net/bzr/+bug/149270
        """
        mkdir("branch1")
        wt = self.make_branch_and_tree("branch1")
        b = wt.branch
        wt.commit("Empty commit 1")
        wt2 = b.controldir.sprout("branch2").open_workingtree()
        wt2.commit("Empty commit 2")
        out, _err = self.run_bzr("status branch1 -rbranch:branch2")
        self.assertEqual("", out)

    def test_status_with_shelves(self):
        """Ensure that _show_shelve_summary handler works."""
        wt = self.make_branch_and_tree(".")
        self.build_tree(["hello.c"])
        wt.add("hello.c")
        self.run_bzr(["shelve", "--all", "-m", "foo"])
        self.build_tree(["bye.c"])
        wt.add("bye.c")
        self.assertStatus(
            [
                "added:\n",
                "  bye.c\n",
                '1 shelf exists. See "brz shelve --list" for details.\n',
            ],
            wt,
        )
        self.run_bzr(["shelve", "--all", "-m", "bar"])
        self.build_tree(["eggs.c", "spam.c"])
        wt.add("eggs.c")
        wt.add("spam.c")
        self.assertStatus(
            [
                "added:\n",
                "  eggs.c\n",
                "  spam.c\n",
                '2 shelves exist. See "brz shelve --list" for details.\n',
            ],
            wt,
        )
        self.assertStatus(
            [
                "added:\n",
                "  spam.c\n",
            ],
            wt,
            specific_files=["spam.c"],
        )


class CheckoutStatus(BranchStatus):
    def setUp(self):
        super().setUp()
        mkdir("codir")
        chdir("codir")

    def make_branch_and_tree(self, relpath):
        source = self.make_branch(pathjoin("..", relpath))
        checkout = bzrdir.BzrDirMetaFormat1().initialize(relpath)
        checkout.set_branch_reference(source)
        return checkout.create_workingtree()


class TestStatus(TestCaseWithTransport):
    def test_status_plain(self):
        tree = self.make_branch_and_tree(".")

        self.build_tree(["hello.txt"])
        result = self.run_bzr("status")[0]
        self.assertContainsRe(result, "unknown:\n  hello.txt\n")

        tree.add("hello.txt")
        result = self.run_bzr("status")[0]
        self.assertContainsRe(result, "added:\n  hello.txt\n")

        tree.commit(message="added")
        result = self.run_bzr("status -r 0..1")[0]
        self.assertContainsRe(result, "added:\n  hello.txt\n")

        result = self.run_bzr("status -c 1")[0]
        self.assertContainsRe(result, "added:\n  hello.txt\n")

        self.build_tree(["world.txt"])
        result = self.run_bzr("status -r 0")[0]
        self.assertContainsRe(result, "added:\n  hello.txt\nunknown:\n  world.txt\n")
        result2 = self.run_bzr("status -r 0..")[0]
        self.assertEqual(result2, result)

    def test_status_short(self):
        tree = self.make_branch_and_tree(".")

        self.build_tree(["hello.txt"])
        result = self.run_bzr("status --short")[0]
        self.assertContainsRe(result, "[?]   hello.txt\n")

        tree.add("hello.txt")
        result = self.run_bzr("status --short")[0]
        self.assertContainsRe(result, "[+]N  hello.txt\n")

        tree.commit(message="added")
        result = self.run_bzr("status --short -r 0..1")[0]
        self.assertContainsRe(result, "[+]N  hello.txt\n")

        self.build_tree(["world.txt"])
        result = self.run_bzr("status -S -r 0")[0]
        self.assertContainsRe(result, "[+]N  hello.txt\n[?]   world.txt\n")
        result2 = self.run_bzr("status -S -r 0..")[0]
        self.assertEqual(result2, result)

    def test_status_versioned(self):
        tree = self.make_branch_and_tree(".")

        self.build_tree(["hello.txt"])
        result = self.run_bzr("status --versioned")[0]
        self.assertNotContainsRe(result, "unknown:\n  hello.txt\n")

        tree.add("hello.txt")
        result = self.run_bzr("status --versioned")[0]
        self.assertContainsRe(result, "added:\n  hello.txt\n")

        tree.commit("added")
        result = self.run_bzr("status --versioned -r 0..1")[0]
        self.assertContainsRe(result, "added:\n  hello.txt\n")

        self.build_tree(["world.txt"])
        result = self.run_bzr("status --versioned -r 0")[0]
        self.assertContainsRe(result, "added:\n  hello.txt\n")
        self.assertNotContainsRe(result, "unknown:\n  world.txt\n")
        result2 = self.run_bzr("status --versioned -r 0..")[0]
        self.assertEqual(result2, result)

    def test_status_SV(self):
        tree = self.make_branch_and_tree(".")

        self.build_tree(["hello.txt"])
        result = self.run_bzr("status -SV")[0]
        self.assertNotContainsRe(result, "hello.txt")

        tree.add("hello.txt")
        result = self.run_bzr("status -SV")[0]
        self.assertContainsRe(result, "[+]N  hello.txt\n")

        tree.commit(message="added")
        result = self.run_bzr("status -SV -r 0..1")[0]
        self.assertContainsRe(result, "[+]N  hello.txt\n")

        self.build_tree(["world.txt"])
        result = self.run_bzr("status -SV -r 0")[0]
        self.assertContainsRe(result, "[+]N  hello.txt\n")

        result2 = self.run_bzr("status -SV -r 0..")[0]
        self.assertEqual(result2, result)

    def assertStatusContains(self, pattern, short=False):
        """Run status, and assert it contains the given pattern."""
        if short:
            result = self.run_bzr("status --short")[0]
        else:
            result = self.run_bzr("status")[0]
        self.assertContainsRe(result, pattern)

    def test_kind_change_plain(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree(["file"])
        tree.add("file")
        tree.commit("added file")
        unlink("file")
        self.build_tree(["file/"])
        self.assertStatusContains("kind changed:\n  file \\(file => directory\\)")
        tree.rename_one("file", "directory")
        self.assertStatusContains(
            "renamed:\n  file => directory/\nmodified:\n  directory/\n"
        )
        rmdir("directory")
        self.assertStatusContains("removed:\n  file\n")

    def test_kind_change_short(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree(["file"])
        tree.add("file")
        tree.commit("added file")
        unlink("file")
        self.build_tree(["file/"])
        self.assertStatusContains("K  file => file/", short=True)
        tree.rename_one("file", "directory")
        self.assertStatusContains("RK  file => directory/", short=True)
        rmdir("directory")
        self.assertStatusContains("RD  file => directory", short=True)

    def test_status_illegal_revision_specifiers(self):
        _out, err = self.run_bzr("status -r 1..23..123", retcode=3)
        self.assertContainsRe(err, "one or two revision specifiers")

    def test_status_no_pending(self):
        a_tree = self.make_branch_and_tree("a")
        self.build_tree(["a/a"])
        a_tree.add("a")
        a_tree.commit("a")
        b_tree = a_tree.controldir.sprout("b").open_workingtree()
        self.build_tree(["b/b"])
        b_tree.add("b")
        b_tree.commit("b")

        self.run_bzr("merge ../b", working_dir="a")
        out, _err = self.run_bzr("status --no-pending", working_dir="a")
        self.assertEqual(out, "added:\n  b\n")

    def test_pending_specific_files(self):
        """With a specific file list, pending merges are not shown."""
        tree = self.make_branch_and_tree("tree")
        self.build_tree_contents([("tree/a", b"content of a\n")])
        tree.add("a")
        tree.commit("one")
        alt = tree.controldir.sprout("alt").open_workingtree()
        self.build_tree_contents([("alt/a", b"content of a\nfrom alt\n")])
        alt.commit("alt")
        tree.merge_from_branch(alt.branch)
        output = self.make_utf8_encoded_stringio()
        show_tree_status(tree, to_file=output)
        self.assertContainsRe(output.getvalue(), b"pending merge")
        out, _err = self.run_bzr("status tree/a")
        self.assertNotContainsRe(out, "pending merge")


class TestStatusEncodings(TestCaseWithTransport):
    def make_uncommitted_tree(self):
        """Build a branch with uncommitted unicode named changes in the cwd."""
        working_tree = self.make_branch_and_tree(".")
        filename = "hell\u00d8"
        try:
            self.build_tree_contents([(filename, b"contents of hello")])
        except UnicodeEncodeError:
            raise TestSkipped(
                "can't build unicode working tree in filesystem encoding {}".format(
                    sys.getfilesystemencoding()
                )
            )
        working_tree.add(filename)
        return working_tree

    def test_stdout_ascii(self):
        self.overrideAttr(osutils, "_cached_user_encoding", "ascii")
        self.make_uncommitted_tree()
        stdout, _stderr = self.run_bzr("status")

        self.assertEqual(
            stdout,
            """\
added:
  hell?
""",
        )

    def test_stdout_latin1(self):
        self.overrideAttr(osutils, "_cached_user_encoding", "latin-1")
        self.make_uncommitted_tree()
        stdout, _stderr = self.run_bzr("status")

        expected = """\
added:
  hell\u00d8
"""
        self.assertEqual(stdout, expected)
