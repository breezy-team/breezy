# Copyright (C) 2006, 2007, 2009-2012 Canonical Ltd
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

from breezy.tests import TestCaseWithTransport
from breezy.workingtree import WorkingTree


class TestRemerge(TestCaseWithTransport):
    def make_file(self, name, contents):
        with open(name, "w") as f:
            f.write(contents)

    def create_conflicts(self):
        """Create a conflicted tree."""
        os.mkdir("base")
        self.make_file("base/hello", "hi world")
        self.make_file("base/answer", "42")
        self.run_bzr("init", working_dir="base")
        self.run_bzr("add", working_dir="base")
        self.run_bzr("commit -m base", working_dir="base")
        self.run_bzr("branch base other")
        self.run_bzr("branch base this")
        self.make_file("other/hello", "Hello.")
        self.make_file("other/answer", "Is anyone there?")
        self.run_bzr("commit -m other", working_dir="other")
        self.make_file("this/hello", "Hello, world")
        self.run_bzr("mv answer question", working_dir="this")
        self.make_file(
            "this/question", "What do you get when you multiply sixtimes nine?"
        )
        self.run_bzr("commit -m this", working_dir="this")

    def test_remerge(self):
        """Remerge command works as expected."""
        self.create_conflicts()
        self.run_bzr("merge ../other --show-base", retcode=1, working_dir="this")
        with open("this/hello") as f:
            conflict_text = f.read()
        self.assertTrue("|||||||" in conflict_text)
        self.assertTrue("hi world" in conflict_text)

        self.run_bzr_error(
            ["conflicts encountered"], "remerge", retcode=1, working_dir="this"
        )
        with open("this/hello") as f:
            conflict_text = f.read()
        self.assertFalse("|||||||" in conflict_text)
        self.assertFalse("hi world" in conflict_text)

        os.unlink("this/hello.OTHER")
        os.unlink("this/question.OTHER")

        self.run_bzr_error(
            ["jello is not versioned"],
            "remerge jello --merge-type weave",
            working_dir="this",
        )
        self.run_bzr_error(
            ["conflicts encountered"],
            "remerge hello --merge-type weave",
            retcode=1,
            working_dir="this",
        )

        self.assertPathExists("this/hello.OTHER")
        self.assertPathDoesNotExist("this/question.OTHER")

        self.run_bzr("file-id hello", working_dir="this")[0]
        self.run_bzr_error(
            ["hello.THIS is not versioned"], "file-id hello.THIS", working_dir="this"
        )

        self.run_bzr_error(
            ["conflicts encountered"],
            "remerge --merge-type weave",
            retcode=1,
            working_dir="this",
        )

        self.assertPathExists("this/hello.OTHER")
        self.assertTrue("this/hello.BASE")
        with open("this/hello") as f:
            conflict_text = f.read()
        self.assertFalse("|||||||" in conflict_text)
        self.assertFalse("hi world" in conflict_text)

        self.run_bzr_error(
            ["Showing base is not supported.*Weave"],
            "remerge . --merge-type weave --show-base",
            working_dir="this",
        )
        self.run_bzr_error(
            ["Can't reprocess and show base"],
            "remerge . --show-base --reprocess",
            working_dir="this",
        )
        self.run_bzr_error(
            ["conflicts encountered"],
            "remerge . --merge-type weave --reprocess",
            retcode=1,
            working_dir="this",
        )
        self.run_bzr_error(
            ["conflicts encountered"],
            "remerge hello --show-base",
            retcode=1,
            working_dir="this",
        )
        self.run_bzr_error(
            ["conflicts encountered"],
            "remerge hello --reprocess",
            retcode=1,
            working_dir="this",
        )

        self.run_bzr("resolve --all", working_dir="this")
        self.run_bzr("commit -m done", working_dir="this")

        self.run_bzr_error(
            [
                "remerge only works after normal merges",
                "Not cherrypicking or multi-merges",
            ],
            "remerge",
            working_dir="this",
        )

    def test_conflicts(self):
        self.create_conflicts()
        self.run_bzr("merge ../other", retcode=1, working_dir="this")
        wt = WorkingTree.open("this")
        self.assertEqual(2, len(wt.conflicts()))
        self.run_bzr("remerge", retcode=1, working_dir="this")
        wt = WorkingTree.open("this")
        self.assertEqual(2, len(wt.conflicts()))
        self.run_bzr("remerge hello", retcode=1, working_dir="this")
        wt = WorkingTree.open("this")
        self.assertEqual(2, len(wt.conflicts()))
