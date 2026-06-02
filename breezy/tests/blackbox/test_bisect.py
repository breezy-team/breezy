# Copyright (C) 2007-2010 Canonical Ltd
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


"""Tests of the 'brz bisect' command."""

import os
import shutil
import stat
import sys

from ...controldir import ControlDir
from .. import TestCaseWithTransport, TestSkipped, expectedFailure


class BisectTestCase(TestCaseWithTransport):
    """Test harness specific to the bisect plugin."""

    def assertRevno(self, rev):
        """Make sure we're at the right revision."""
        rev_contents = {
            1: "one",
            1.1: "one dot one",
            1.2: "one dot two",
            1.3: "one dot three",
            2: "two",
            3: "three",
            4: "four",
            5: "five",
        }

        with open("test_file") as test_file:
            content = test_file.read().strip()
        if content != rev_contents[rev]:
            rev_ids = {rev_contents[k]: k for k in rev_contents.keys()}
            found_rev = rev_ids[content]
            raise AssertionError(f"expected rev {rev:0.1f}, found rev {found_rev:0.1f}")

    def setUp(self):
        """Set up tests."""
        # These tests assume a branch with five revisions, and
        # a branch from version 1 containing three revisions
        # merged at version 2.

        TestCaseWithTransport.setUp(self)

        self.tree = self.make_branch_and_tree(".")

        with open("test_file", "w") as test_file:
            test_file.write("one")
        self.tree.add(self.tree.relpath(os.path.join(os.getcwd(), "test_file")))
        with open("test_file_append", "a") as test_file_append:
            test_file_append.write("one\n")
        self.tree.add(self.tree.relpath(os.path.join(os.getcwd(), "test_file_append")))
        self.tree.commit(message="add test files")

        ControlDir.open(".").sprout("../temp-clone")
        clone_controldir = ControlDir.open("../temp-clone")
        clone_tree = clone_controldir.open_workingtree()
        for content in ["one dot one", "one dot two", "one dot three"]:
            with open("../temp-clone/test_file", "w") as test_file:
                test_file.write(content)
            with open("../temp-clone/test_file_append", "a") as test_file_append:
                test_file_append.write(content + "\n")
            clone_tree.commit(message="make branch test change")
            saved_subtree_revid = clone_tree.branch.last_revision()

        self.tree.merge_from_branch(clone_tree.branch)
        with open("test_file", "w") as test_file:
            test_file.write("two")
        with open("test_file_append", "a") as test_file_append:
            test_file_append.write("two\n")
        self.tree.commit(message="merge external branch")
        shutil.rmtree("../temp-clone")

        self.subtree_rev = saved_subtree_revid

        file_contents = ["three", "four", "five"]
        for content in file_contents:
            with open("test_file", "w") as test_file:
                test_file.write(content)
            with open("test_file_append", "a") as test_file_append:
                test_file_append.write(content + "\n")
            self.tree.commit(message="make test change")

    def testWorkflow(self):
        """Run through a basic usage scenario."""
        # Start up the bisection.  When the two ends are set, we should
        # end up in the middle.

        self.run_bzr(["bisect", "start"])
        self.run_bzr(["bisect", "yes"])
        self.run_bzr(["bisect", "no", "-r", "1"])
        self.assertRevno(3)

        # Mark feature as present in the middle.  Should move us
        # halfway back between the current middle and the start.

        self.run_bzr(["bisect", "yes"])
        self.assertRevno(2)

        # Mark feature as not present.  Since this is only one
        # rev back from the lowest marked revision with the feature,
        # the process should end, with the current rev set to the
        # rev following.

        self.run_bzr(["bisect", "no"])
        self.assertRevno(3)

        # Run again.  Since we're done, this should do nothing.

        self.run_bzr(["bisect", "no"])
        self.assertRevno(3)

    def testWorkflowSubtree(self):
        """Run through a usage scenario where the offending change
        is in a subtree.
        """
        # Similar to testWorkflow, but make sure the plugin traverses
        # subtrees when the "final" revision is a merge point.

        # This part is similar to testWorkflow.

        self.run_bzr(["bisect", "start"])
        self.run_bzr(["bisect", "yes"])
        self.run_bzr(["bisect", "no", "-r", "1"])
        self.run_bzr(["bisect", "yes"])

        # Check to make sure we're where we expect to be.

        self.assertRevno(2)

        # Now, mark the merge point revno, meaning the feature
        # appeared at a merge point.

        self.run_bzr(["bisect", "yes"])
        self.assertRevno(1.2)

        # Continue bisecting along the subtree to the real conclusion.

        self.run_bzr(["bisect", "yes"])
        self.assertRevno(1.1)
        self.run_bzr(["bisect", "yes"])
        self.assertRevno(1.1)

        # Run again.  Since we're done, this should do nothing.

        self.run_bzr(["bisect", "yes"])
        self.assertRevno(1.1)

    def testMove(self):
        """Test manually moving to a different revision during the bisection."""
        # Set up a bisection in progress.

        self.run_bzr(["bisect", "start"])
        self.run_bzr(["bisect", "yes"])
        self.run_bzr(["bisect", "no", "-r", "1"])

        # Move.

        self.run_bzr(["bisect", "move", "-r", "2"])
        self.assertRevno(2)

    def testReset(self):
        """Test resetting the tree."""
        # Set up a bisection in progress.

        self.run_bzr(["bisect", "start"])
        self.run_bzr(["bisect", "yes"])
        self.run_bzr(["bisect", "no", "-r", "1"])
        self.run_bzr(["bisect", "yes"])

        # Now reset.

        self.run_bzr(["bisect", "reset"])
        self.assertRevno(5)

        # Check that reset doesn't do anything unless there's a
        # bisection in progress.

        with open("test_file", "w") as test_file:
            test_file.write("keep me")

        _out, err = self.run_bzr(["bisect", "reset"], retcode=3)
        self.assertIn("No bisection in progress.", err)

        with open("test_file") as test_file:
            content = test_file.read().strip()
        self.assertEqual(content, "keep me")

    def testLog(self):
        """Test saving the current bisection state, and re-loading it."""
        # Set up a bisection in progress.

        self.run_bzr(["bisect", "start"])
        self.run_bzr(["bisect", "yes"])
        self.run_bzr(["bisect", "no", "-r", "1"])
        self.run_bzr(["bisect", "yes"])

        # Now save the log.

        self.run_bzr(["bisect", "log", "-o", "bisect_log"])

        # Reset.

        self.run_bzr(["bisect", "reset"])

        # Read it back in.

        self.run_bzr(["bisect", "replay", "bisect_log"])
        self.assertRevno(2)

        # Mark another state, and see if the bisect moves in the
        # right way.

        self.run_bzr(["bisect", "no"])
        self.assertRevno(3)

    def testRunScript(self):
        """Make a test script and run it."""
        with open("test_script", "w") as test_script:
            test_script.write("#!/bin/sh\ngrep -q '^four' test_file_append\n")
        os.chmod("test_script", stat.S_IRWXU)
        self.run_bzr(["bisect", "start"])
        self.run_bzr(["bisect", "yes"])
        self.run_bzr(["bisect", "no", "-r", "1"])
        self.run_bzr(["bisect", "run", "./test_script"])
        self.assertRevno(4)

    # bisect does not drill down into merge commits:
    # https://bugs.launchpad.net/bzr-bisect/+bug/539937
    @expectedFailure
    def testRunScriptMergePoint(self):
        """Make a test script and run it."""
        if sys.platform == "win32":
            raise TestSkipped("Unable to run shell script on windows")
        with open("test_script", "w") as test_script:
            test_script.write("#!/bin/sh\ngrep -q '^two' test_file_append\n")
        os.chmod("test_script", stat.S_IRWXU)
        self.run_bzr(["bisect", "start"])
        self.run_bzr(["bisect", "yes"])
        self.run_bzr(["bisect", "no", "-r", "1"])
        self.run_bzr(["bisect", "run", "./test_script"])
        self.assertRevno(2)

    # bisect does not drill down into merge commits:
    # https://bugs.launchpad.net/bzr-bisect/+bug/539937
    @expectedFailure
    def testRunScriptSubtree(self):
        """Make a test script and run it."""
        if sys.platform == "win32":
            raise TestSkipped("Unable to run shell script on windows")
        with open("test_script", "w") as test_script:
            test_script.write("#!/bin/sh\ngrep -q '^one dot two' test_file_append\n")
        os.chmod("test_script", stat.S_IRWXU)
        self.run_bzr(["bisect", "start"])
        self.run_bzr(["bisect", "yes"])
        self.run_bzr(["bisect", "no", "-r", "1"])
        self.run_bzr(["bisect", "run", "./test_script"])
        self.assertRevno(1.2)
