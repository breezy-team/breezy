# Copyright (C) 2006, 2007 Canonical Ltd
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

"""Tests for interface conformance of 'WorkingTree.remove'"""

from bzrlib.tests.workingtree_implementations import TestCaseWithWorkingTree

class TestRemove(TestCaseWithWorkingTree):
    """Tests WorkingTree.remove"""

    files=['a', 'b/', 'b/c']
    b = ['b']
    b_c = ['b', 'b/c']

    def getTree(self):
        self.makeAndChdirToTestDir()
        tree = self.make_branch_and_tree('.')
        self.build_tree(TestRemove.files)
        return tree

    def test_remove_unchanged_files(self):
        """check that unchanged files are removed and deleted."""
        tree = self.getTree()
        tree.add(TestRemove.files)
        tree.commit("files must not have changes")

        self.assertInWorkingTree(TestRemove.files)

        tree.remove(TestRemove.files, keep_files=False)

        self.assertNotInWorkingTree(TestRemove.files)
        self.failIfExists(TestRemove.files)

    def test_remove_changed_files(self):
        """check that changed files are removed but not deleted."""
        tree = self.getTree()
        tree.add(TestRemove.files)
        self.assertInWorkingTree(TestRemove.files)

        tree.remove(TestRemove.files, keep_files=False)

        self.assertNotInWorkingTree(TestRemove.files)
        self.failUnlessExists(TestRemove.files)

    def test_force_remove_changed_files(self):
        """check that changed files are removed and deleted when forced."""
        tree = self.getTree()
        tree.add(TestRemove.files)
        self.assertInWorkingTree(TestRemove.files)

        tree.remove(TestRemove.files, keep_files=False, force=True)

        self.assertNotInWorkingTree(TestRemove.files)
        self.failIfExists(TestRemove.files)

    def test_remove_nonexisting_files(self):
        """delete files which does not exist."""
        tree = self.getTree()
        tree.remove(TestRemove.files, keep_files=False)
        tree.remove([''], keep_files=False)
        tree.remove(TestRemove.b, keep_files=False)

    def test_remove_nonempty_directory(self):
        tree = self.getTree()
        tree.add(TestRemove.files)
        tree.commit("make sure b is versioned")
        self.assertInWorkingTree(TestRemove.files)
        self.failUnlessExists(TestRemove.files)
        tree.remove(TestRemove.b, keep_files=False)
        self.assertNotInWorkingTree(TestRemove.b)
        self.failUnlessExists(TestRemove.b)

    def test_force_remove_nonempty_directory(self):
        tree = self.getTree()
        tree.add(TestRemove.files)
        tree.commit("make sure b is versioned")
        self.assertInWorkingTree(TestRemove.files)
        self.failUnlessExists(TestRemove.files)
        tree.remove(TestRemove.b, keep_files=False, force=True)
        self.assertNotInWorkingTree(TestRemove.b_c)
        self.failIfExists(TestRemove.b_c)

    def test_remove_keep(self):
        """check that files are unversioned but not delete."""
        tree = self.getTree()
        tree.add(TestRemove.files)
        self.assertInWorkingTree(TestRemove.files)

        tree.remove(TestRemove.files)
        self.assertNotInWorkingTree(TestRemove.files)
        self.failUnlessExists(TestRemove.files)
