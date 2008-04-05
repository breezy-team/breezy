# Copyright (C) 2008 Canonical Ltd
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"Test suite for the bzr bisect plugin."

import os
import shutil
import bzrlib
import bzrlib.bzrdir
import bzrlib.tests
import bzrlib.revisionspec
import bzrlib.plugins.bisect as bisect


class BisectTestCase(bzrlib.tests.TestCaseWithTransport):
    "Test harness specific to the bisect plugin."

    def assertRevno(self, rev):
        "Make sure we're at the right revision."

        rev_contents = {1: "one", 1.1: "one dot one", 1.2: "one dot two",
                        1.3: "one dot three", 2: "two", 3: "three",
                        4: "four", 5: "five"}

        test_file = open("test_file")
        content = test_file.read().strip()
        if content != rev_contents[rev]:
            rev_ids = dict((rev_contents[k], k) for k in rev_contents.keys())
            found_rev = rev_ids[content]
            raise AssertionError("expected rev %0.1f, found rev %0.1f"
                                 % (rev, found_rev))

    def setUp(self):
        bzrlib.tests.TestCaseWithTransport.setUp(self)

        # These tests assume a branch with five revisions, and
        # a branch from version 1 containing three revisions
        # merged at version 2.

        self.tree = self.make_branch_and_tree(".")

        test_file = open("test_file", "w")
        test_file.write("one")
        test_file.close()
        self.tree.add(self.tree.relpath(os.path.join(os.getcwd(),
                                                     'test_file')))
        self.tree.commit(message = "add test file")

        bzrlib.bzrdir.BzrDir.open(".").sprout("../temp-clone")
        clone_bzrdir = bzrlib.bzrdir.BzrDir.open("../temp-clone")
        clone_tree = clone_bzrdir.open_workingtree()
        for content in ["one dot one", "one dot two", "one dot three"]:
            test_file = open("../temp-clone/test_file", "w")
            test_file.write(content)
            test_file.close()
            clone_tree.commit(message = "make branch test change")
            saved_subtree_revid = clone_tree.branch.last_revision()

        self.tree.merge_from_branch(clone_tree.branch)
        test_file = open("test_file", "w")
        test_file.write("two")
        test_file.close()
        self.tree.commit(message = "merge external branch")
        shutil.rmtree("../temp-clone")

        self.subtree_rev = saved_subtree_revid

        file_contents = ["three", "four", "five"]
        for content in file_contents:
            test_file = open("test_file", "w")
            test_file.write(content)
            test_file.close()
            self.tree.commit(message = "make test change")


class BisectHarnessTests(BisectTestCase):
    "Tests for the harness itself."

    def testLastRev(self):
        "Test that the last revision is correct."
        repo = self.tree.branch.repository
        top_revtree = repo.revision_tree(self.tree.last_revision())
        top_revtree.lock_read()
        top_file = top_revtree.get_file(top_revtree.path2id("test_file"))
        test_content = top_file.read().strip()
        top_file.close()
        top_revtree.unlock()
        assert test_content == "five"

    def testSubtreeRev(self):
        "Test that the last revision in a subtree is correct."
        repo = self.tree.branch.repository
        sub_revtree = repo.revision_tree(self.subtree_rev)
        sub_revtree.lock_read()
        sub_file = sub_revtree.get_file(sub_revtree.path2id("test_file"))
        test_content = sub_file.read().strip()
        sub_file.close()
        sub_revtree.unlock()
        assert test_content == "one dot three"


class BisectMetaTests(BisectTestCase):
    "Test the metadata provided by the package."

    def testVersionPresent(self):
        assert bisect.version_info

    def testBzrVersioning(self):
        assert bisect.bzr_minimum_api >= bzrlib.api_minimum_version
        assert bisect.bzr_minimum_api <= bzrlib.version_info[:3]


class BisectCurrentUnitTests(BisectTestCase):
    "Test the BisectCurrent class."

    def testShowLog(self):
        "Test that the log can be shown."
        # Not a very good test; just makes sure the code doesn't fail,
        # not that the output makes any sense.
        bisect.BisectCurrent().show_rev_log()

    def testShowLogSubtree(self):
        "Test that a subtree's log can be shown."
        current = bisect.BisectCurrent()
        current.switch(self.subtree_rev)
        current.show_rev_log()

    def testSwitchVersions(self):
        "Test switching versions."
        current = bisect.BisectCurrent()
        self.assertRevno(5)
        current.switch(4)
        self.assertRevno(4)

    def testReset(self):
        "Test resetting the working tree to a non-bisected state."
        current = bisect.BisectCurrent()
        current.switch(4)
        current.reset()
        self.assertRevno(5)
        assert not os.path.exists(bisect.bisect_rev_path)

    def testIsMergePoint(self):
        "Test merge point detection."
        current = bisect.BisectCurrent()
        self.assertRevno(5)
        assert not current.is_merge_point()
        current.switch(2)
        assert current.is_merge_point()


class BisectLogUnitTests(BisectTestCase):
    "Test the BisectLog class."

    def testCreateBlank(self):
        "Test creation of new log."
        bisect_log = bisect.BisectLog()
        bisect_log.save()
        assert os.path.exists(bisect.bisect_info_path)

    def testLoad(self):
        "Test loading a log."
        preloaded_log = open(bisect.bisect_info_path, "w")
        preloaded_log.write("rev1 yes\nrev2 no\nrev3 yes\n")
        preloaded_log.close()

        bisect_log = bisect.BisectLog()
        assert len(bisect_log._items) == 3
        assert bisect_log._items[0] == ("rev1", "yes")
        assert bisect_log._items[1] == ("rev2", "no")
        assert bisect_log._items[2] == ("rev3", "yes")

    def testSave(self):
        "Test saving the log."
        bisect_log = bisect.BisectLog()
        bisect_log._items = [("rev1", "yes"), ("rev2", "no"), ("rev3", "yes")]
        bisect_log.save()

        logfile = open(bisect.bisect_info_path)
        assert logfile.read() == "rev1 yes\nrev2 no\nrev3 yes\n"


class BisectFuncTests(BisectTestCase):
    "Functional tests for the bisect plugin."

    def testWorkflow(self):
        "Run through a basic usage scenario."

        # Start up the bisection.  When the two ends are set, we should
        # end up in the middle.

        self.run_bzr(['bisect', 'start'])
        self.run_bzr(['bisect', 'yes'])
        self.run_bzr(['bisect', 'no', '-r', '1'])
        self.assertRevno(3)

        # Mark feature as present in the middle.  Should move us
        # halfway back between the current middle and the start.

        self.run_bzr(['bisect', 'yes'])
        self.assertRevno(2)

        # Mark feature as not present.  Since this is only one
        # rev back from the lowest marked revision with the feature,
        # the process should end, with the current rev set to the
        # rev following.

        self.run_bzr(['bisect', 'no'])
        self.assertRevno(3)

        # Run again.  Since we're done, this should do nothing.

        self.run_bzr(['bisect', 'no'])
        self.assertRevno(3)

    def testWorkflowSubtree(self):
        """Run through a usage scenario where the offending change
        is in a subtree."""

        # Similar to testWorkflow, but make sure the plugin traverses
        # subtrees when the "final" revision is a merge point.

        # This part is similar to testWorkflow.

        self.run_bzr(['bisect', 'start'])
        self.run_bzr(['bisect', 'yes'])
        self.run_bzr(['bisect', 'no', '-r', '1'])
        self.run_bzr(['bisect', 'yes'])

        # Check to make sure we're where we expect to be.

        self.assertRevno(2)

        # Now, mark the merge point revno, meaning the feature
        # appeared at a merge point.

        self.run_bzr(['bisect', 'yes'])
        self.assertRevno(1.2)

        # Continue bisecting along the subtree to the real conclusion.

        self.run_bzr(['bisect', 'yes'])
        self.assertRevno(1.1)
        self.run_bzr(['bisect', 'yes'])
        self.assertRevno(1.1)

        # Run again.  Since we're done, this should do nothing.

        self.run_bzr(['bisect', 'yes'])
        self.assertRevno(1.1)

    def testMove(self):
        "Test manually moving to a different revision during the bisection."

        # Set up a bisection in progress.

        self.run_bzr(['bisect', 'start'])
        self.run_bzr(['bisect', 'yes'])
        self.run_bzr(['bisect', 'no', '-r', '1'])

        # Move.

        self.run_bzr(['bisect', 'move', '-r', '2'])
        self.assertRevno(2)

    def testReset(self):
        "Test resetting the tree."

        # Set up a bisection in progress.

        self.run_bzr(['bisect', 'start'])
        self.run_bzr(['bisect', 'yes'])
        self.run_bzr(['bisect', 'no', '-r', '1'])
        self.run_bzr(['bisect', 'yes'])

        # Now reset.

        self.run_bzr(['bisect', 'reset'])
        self.assertRevno(5)

        # Check that reset doesn't do anything unless there's a
        # bisection in progress.

        test_file = open("test_file", "w")
        test_file.write("keep me")
        test_file.close()

        self.run_bzr(['bisect', 'reset'])

        test_file = open("test_file")
        content = test_file.read().strip()
        test_file.close()
        self.failUnless(content == "keep me")

    def testLog(self):
        "Test saving the current bisection state, and re-loading it."

        # Set up a bisection in progress.

        self.run_bzr(['bisect', 'start'])
        self.run_bzr(['bisect', 'yes'])
        self.run_bzr(['bisect', 'no', '-r', '1'])
        self.run_bzr(['bisect', 'yes'])

        # Now save the log.

        self.run_bzr(['bisect', 'log', '-o', 'bisect_log'])

        # Reset.

        self.run_bzr(['bisect', 'reset'])

        # Read it back in.

        self.run_bzr(['bisect', 'replay', 'bisect_log'])
        self.assertRevno(2)

        # Mark another state, and see if the bisect moves in the
        # right way.

        self.run_bzr(['bisect', 'no'])
        self.assertRevno(3)


def test_suite():
    "Set up the bisect plugin test suite."
    from bzrlib.tests.TestUtil import TestLoader, TestSuite
    from bzrlib.plugins.bisect import tests
    suite = TestSuite()
    suite.addTest(TestLoader().loadTestsFromTestCase(tests.BisectHarnessTests))
    suite.addTest(TestLoader().loadTestsFromTestCase(tests.BisectMetaTests))
    suite.addTest(TestLoader().loadTestsFromTestCase(tests.BisectFuncTests))
    suite.addTest(TestLoader().loadTestsFromTestCase(
        tests.BisectCurrentUnitTests))
    suite.addTest(TestLoader().loadTestsFromTestCase(tests.BisectLogUnitTests))
    return suite
