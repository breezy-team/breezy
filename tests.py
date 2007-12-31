# bisect plugin for Bazaar (bzr), test module.
# Copyright 2006-2007 Jeff Licquia.

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# at your option) any later version.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

import os
import shutil
import bzrlib.bzrdir
import bzrlib.tests
import bzrlib.plugins.bisect as bisect

class BisectTestCase(bzrlib.tests.TestCaseWithTransport):
    def assertRevno(self, rev):
        "Make sure we're at the right revision."

        rev_contents = { 1: "one", 1.1: "one dot one", 1.2: "one dot two",
                         1.3: "one dot three", 2: "two", 3: "three",
                         4: "four", 5: "five" }

        f = open("test_file")
        if f.read() != rev_contents[rev]:
            raise AssertionError("not at revision %0.1f" % rev)

    def setUp(self):
        bzrlib.tests.TestCaseWithTransport.setUp(self)

        # These tests assume a branch with five revisions, and
        # a branch from version 1 containing three revisions
        # merged at version 2.

        self.tree = self.make_branch_and_tree(".")

        f = open("test_file", "w")
        f.write("one")
        f.close()
        self.tree.add(self.tree.relpath(os.path.join(os.getcwd(), 'test_file')))
        self.tree.commit(message = "add test file")

        bzrlib.bzrdir.BzrDir.open(".").sprout("../temp-clone")
        clone_bzrdir = bzrlib.bzrdir.BzrDir.open("../temp-clone")
        clone_tree = clone_bzrdir.open_workingtree()
        for content in ["one dot one", "one dot two", "one dot three"]:
            f = open("../temp-clone/test_file", "w")
            f.write(content)
            f.close()
            clone_tree.commit(message = "make branch test change")

        self.tree.merge_from_branch(clone_tree.branch)
        f = open("test_file", "w")
        f.write("two")
        f.close()
        self.tree.commit(message = "merge external branch")
        shutil.rmtree("../temp-clone")

        file_contents = ["three", "four", "five"]
        for content in file_contents:
            f = open("test_file", "w")
            f.write(content)
            f.close()
            self.tree.commit(message = "make test change")

class BisectCurrentUnitTests(BisectTestCase):
    def testShowLog(self):
        # Not a very good test; just makes sure the code doesn't fail,
        # not that the output makes any sense.
        bisect.BisectCurrent().show_rev_log()

    def testSwitchVersions(self):
        bc = bisect.BisectCurrent()
        self.assertRevno(5)
        bc.switch(4)
        self.assertRevno(4)

    def testReset(self):
        bc = bisect.BisectCurrent()
        bc.switch(4)
        bc.reset()
        self.assertRevno(5)
        assert not os.path.exists(bisect.bisect_rev_path)

    def testIsMergePoint(self):
        bc = bisect.BisectCurrent()
        self.assertRevno(5)
        assert not bc.is_merge_point()
        bc.switch(2)
        assert bc.is_merge_point()

class BisectLogUnitTests(BisectTestCase):
    def testCreateBlank(self):
        bl = bisect.BisectLog()
        bl.save()
        assert os.path.exists(bisect.bisect_info_path)

    def testLoad(self):
        open(bisect.bisect_info_path, "w").write("rev1 yes\nrev2 no\nrev3 yes\n")

        bl = bisect.BisectLog()
        assert len(bl._items) == 3
        assert bl._items[0] == ("rev1", "yes")
        assert bl._items[1] == ("rev2", "no")
        assert bl._items[2] == ("rev3", "yes")

    def testSave(self):
        bl = bisect.BisectLog()
        bl._items = [("rev1", "yes"), ("rev2", "no"), ("rev3", "yes")]
        bl.save()

        f = open(bisect.bisect_info_path)
        assert f.read() == "rev1 yes\nrev2 no\nrev3 yes\n"

class BisectFuncTests(BisectTestCase):
    def testWorkflow(self):
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

    def testWorkflowSubtree(self):
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

    def testMove(self):
        # Set up a bisection in progress.

        self.run_bzr(['bisect', 'start'])
        self.run_bzr(['bisect', 'yes'])
        self.run_bzr(['bisect', 'no', '-r', '1'])

        # Move.

        self.run_bzr(['bisect', 'move', '-r', '2'])
        self.assertRevno(2)

    def testReset(self):
        # Set up a bisection in progress.

        self.run_bzr(['bisect', 'start'])
        self.run_bzr(['bisect', 'yes'])
        self.run_bzr(['bisect', 'no', '-r', '1'])
        self.run_bzr(['bisect', 'yes'])

        # Now reset.

        self.run_bzr(['bisect', 'reset'])
        self.assertRevno(5)

    def testLog(self):
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
