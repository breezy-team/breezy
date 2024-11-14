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

"Test suite for the bzr bisect plugin."

import os
import shutil
from io import StringIO

from .. import bisect
from ..controldir import ControlDir
from . import TestCaseWithTransport, TestSkipped


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

        with open("test_file") as f:
            content = f.read().strip()
        if content != rev_contents[rev]:
            rev_ids = {rev_contents[k]: k for k in rev_contents}
            found_rev = rev_ids[content]
            raise AssertionError(
                "expected rev {:0.1f}, found rev {:0.1f}".format(rev, found_rev)
            )

    def setUp(self):
        """Set up tests."""

        # These tests assume a branch with five revisions, and
        # a branch from version 1 containing three revisions
        # merged at version 2.

        TestCaseWithTransport.setUp(self)

        self.tree = self.make_branch_and_tree(".")

        test_file = open("test_file", "w")
        test_file.write("one")
        test_file.close()
        self.tree.add(self.tree.relpath(os.path.join(os.getcwd(), "test_file")))
        test_file_append = open("test_file_append", "a")
        test_file_append.write("one\n")
        test_file_append.close()
        self.tree.add(self.tree.relpath(os.path.join(os.getcwd(), "test_file_append")))
        self.tree.commit(message="add test files")

        ControlDir.open(".").sprout("../temp-clone")
        clone_bzrdir = ControlDir.open("../temp-clone")
        clone_tree = clone_bzrdir.open_workingtree()
        for content in ["one dot one", "one dot two", "one dot three"]:
            test_file = open("../temp-clone/test_file", "w")
            test_file.write(content)
            test_file.close()
            test_file_append = open("../temp-clone/test_file_append", "a")
            test_file_append.write(content + "\n")
            test_file_append.close()
            clone_tree.commit(message="make branch test change")
            saved_subtree_revid = clone_tree.branch.last_revision()

        self.tree.merge_from_branch(clone_tree.branch)
        test_file = open("test_file", "w")
        test_file.write("two")
        test_file.close()
        test_file_append = open("test_file_append", "a")
        test_file_append.write("two\n")
        test_file_append.close()
        self.tree.commit(message="merge external branch")
        shutil.rmtree("../temp-clone")

        self.subtree_rev = saved_subtree_revid

        file_contents = ["three", "four", "five"]
        for content in file_contents:
            test_file = open("test_file", "w")
            test_file.write(content)
            test_file.close()
            test_file_append = open("test_file_append", "a")
            test_file_append.write(content + "\n")
            test_file_append.close()
            self.tree.commit(message="make test change")


class BisectHarnessTests(BisectTestCase):
    """Tests for the harness itself."""

    def testLastRev(self):
        """Test that the last revision is correct."""
        repo = self.tree.branch.repository
        top_revtree = repo.revision_tree(self.tree.last_revision())
        top_revtree.lock_read()
        top_file = top_revtree.get_file("test_file")
        test_content = top_file.read().strip()
        top_file.close()
        top_revtree.unlock()
        self.assertEqual(test_content, b"five")

    def testSubtreeRev(self):
        """Test that the last revision in a subtree is correct."""
        repo = self.tree.branch.repository
        sub_revtree = repo.revision_tree(self.subtree_rev)
        sub_revtree.lock_read()
        with sub_revtree.get_file("test_file") as sub_file:
            test_content = sub_file.read().strip()
        sub_revtree.unlock()
        self.assertEqual(test_content, b"one dot three")


class BisectCurrentUnitTests(BisectTestCase):
    """Test the BisectCurrent class."""

    def testShowLog(self):
        """Test that the log can be shown."""
        # Not a very good test; just makes sure the code doesn't fail,
        # not that the output makes any sense.
        sio = StringIO()
        bisect.BisectCurrent(self.tree.controldir).show_rev_log(outf=sio)

    def testShowLogSubtree(self):
        """Test that a subtree's log can be shown."""
        current = bisect.BisectCurrent(self.tree.controldir)
        current.switch(self.subtree_rev)
        sio = StringIO()
        current.show_rev_log(outf=sio)

    def testSwitchVersions(self):
        """Test switching versions."""
        current = bisect.BisectCurrent(self.tree.controldir)
        self.assertRevno(5)
        current.switch(4)
        self.assertRevno(4)

    def testReset(self):
        """Test resetting the working tree to a non-bisected state."""
        current = bisect.BisectCurrent(self.tree.controldir)
        current.switch(4)
        current.reset()
        self.assertRevno(5)
        self.assertFalse(os.path.exists(os.path.join(".bzr", bisect.BISECT_REV_PATH)))

    def testIsMergePoint(self):
        """Test merge point detection."""
        current = bisect.BisectCurrent(self.tree.controldir)
        self.assertRevno(5)
        self.assertFalse(current.is_merge_point())
        current.switch(2)
        self.assertTrue(current.is_merge_point())


class BisectLogUnitTests(BisectTestCase):
    """Test the BisectLog class."""

    def testCreateBlank(self):
        """Test creation of new log."""
        bisect_log = bisect.BisectLog(self.tree.controldir)
        bisect_log.save()
        self.assertTrue(os.path.exists(os.path.join(".bzr", bisect.BISECT_INFO_PATH)))

    def testLoad(self):
        """Test loading a log."""
        preloaded_log = open(os.path.join(".bzr", bisect.BISECT_INFO_PATH), "w")
        preloaded_log.write("rev1 yes\nrev2 no\nrev3 yes\n")
        preloaded_log.close()

        bisect_log = bisect.BisectLog(self.tree.controldir)
        self.assertEqual(len(bisect_log._items), 3)
        self.assertEqual(bisect_log._items[0], (b"rev1", "yes"))
        self.assertEqual(bisect_log._items[1], (b"rev2", "no"))
        self.assertEqual(bisect_log._items[2], (b"rev3", "yes"))

    def testSave(self):
        """Test saving the log."""
        bisect_log = bisect.BisectLog(self.tree.controldir)
        bisect_log._items = [(b"rev1", "yes"), (b"rev2", "no"), (b"rev3", "yes")]
        bisect_log.save()

        with open(os.path.join(".bzr", bisect.BISECT_INFO_PATH), "rb") as logfile:
            self.assertEqual(logfile.read(), b"rev1 yes\nrev2 no\nrev3 yes\n")
