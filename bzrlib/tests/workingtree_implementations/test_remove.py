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

import re
from bzrlib.tests.workingtree_implementations import TestCaseWithWorkingTree
from bzrlib import errors, osutils

class TestRemove(TestCaseWithWorkingTree):
    """Tests WorkingTree.remove"""

    files = ['a', 'b/', 'b/c', 'd/']
    rfiles = ['b/c', 'b', 'a', 'd']
    a = ['a']
    b = ['b']
    b_c = ['b', 'b/c']

    def getTree(self):
        self.makeAndChdirToTestDir()
        tree = self.make_branch_and_tree('.')
        self.build_tree(TestRemove.files)
        return tree

    def _assertRemoveErrorContainsRe(self, e, file_detail_re):
        # since assertContainsRe can't take a DOTALL parameter like
        # normal re.match, use the following to disregard newlines
        err = ' '.join(str(e).split())
        self.assertContainsRe(err, 'Can\'t remove changed or unknown'
            ' files:.*' + file_detail_re)

    def test_remove_keep(self):
        """Check that files are unversioned but not deleted."""
        tree = self.getTree()
        tree.add(TestRemove.files)
        self.assertInWorkingTree(TestRemove.files)

        tree.remove(TestRemove.files)
        self.assertNotInWorkingTree(TestRemove.files)
        self.failUnlessExists(TestRemove.files)

    def test_remove_unchanged_files(self):
        """Check that unchanged files are removed and deleted."""
        tree = self.getTree()
        tree.add(TestRemove.files)
        tree.commit("files must not have changes")
        self.assertInWorkingTree(TestRemove.files)

        tree.remove(TestRemove.files, keep_files=False)

        self.assertNotInWorkingTree(TestRemove.files)
        self.failIfExists(TestRemove.files)

    def test_remove_added_files(self):
        """Removal of newly added files must fail."""
        tree = self.getTree()
        tree.add(TestRemove.files)
        self.assertInWorkingTree(TestRemove.files)
        e = self.assertRaises(errors.BzrRemoveChangedFilesError, tree.remove,
            TestRemove.files, keep_files=False)
        self._assertRemoveErrorContainsRe(e, 'added:.*a.*b.*b/c.*d')
        self.assertInWorkingTree(TestRemove.files)
        self.failUnlessExists(TestRemove.files)

    def test_remove_changed_file(self):
        """Removal of a changed files must fail."""
        tree = self.getTree()
        tree.add(TestRemove.a)
        tree.commit("make sure a is versioned")
        self.build_tree_contents([('a', "some other new content!")])
        self.assertInWorkingTree(TestRemove.a)
        e = self.assertRaises(errors.BzrRemoveChangedFilesError, tree.remove,
            TestRemove.a, keep_files=False)
        self._assertRemoveErrorContainsRe(e, 'modified:.*a')
        self.assertInWorkingTree(TestRemove.a)
        self.failUnlessExists(TestRemove.a)

    def test_remove_deleted_files(self):
        """Check that files are removed if they don't exist any more."""
        tree = self.getTree()
        tree.add(TestRemove.files)
        tree.commit("make sure files are versioned")
        for f in TestRemove.rfiles:
            osutils.delete_any(f)
        self.assertInWorkingTree(TestRemove.files)
        self.failIfExists(TestRemove.files)

        tree.remove(TestRemove.files, keep_files=False)

        self.assertNotInWorkingTree(TestRemove.files)
        self.failIfExists(TestRemove.files)

    def test_remove_renamed_files(self):
        """Check that files are removed even if they are renamed."""
        tree = self.getTree()
        tree.add(TestRemove.files)
        tree.commit("make sure files are versioned")

        for f in TestRemove.rfiles:
            tree.rename_one(f,f+'x')
        rfilesx = ['bx/cx', 'bx', 'ax', 'dx']
        self.assertInWorkingTree(rfilesx)
        self.failUnlessExists(rfilesx)

        tree.remove(rfilesx, keep_files=False)

        self.assertNotInWorkingTree(rfilesx)
        self.failIfExists(rfilesx)

    def test_remove_renamed_changed_files(self):
        """Check that files are not removed if they are renamed and changed."""
        tree = self.getTree()
        tree.add(TestRemove.files)
        tree.commit("make sure files are versioned")

        for f in TestRemove.rfiles:
            tree.rename_one(f,f+'x')
        rfilesx = ['bx/cx', 'bx', 'ax', 'dx']
        self.build_tree_contents([('ax','changed and renamed!'),
                                  ('bx/cx','changed and renamed!')])
        self.assertInWorkingTree(rfilesx)
        self.failUnlessExists(rfilesx)

        e = self.assertRaises(errors.BzrRemoveChangedFilesError, tree.remove,
            rfilesx, keep_files=False)
        self._assertRemoveErrorContainsRe(e, 'modified:.*ax.*bx/cx')
        self.assertInWorkingTree(rfilesx)
        self.failUnlessExists(rfilesx)

    def test_force_remove_changed_files(self):
        """Check that changed files are removed and deleted when forced."""
        tree = self.getTree()
        tree.add(TestRemove.files)
        self.assertInWorkingTree(TestRemove.files)

        tree.remove(TestRemove.files, keep_files=False, force=True)

        self.assertNotInWorkingTree(TestRemove.files)
        self.failIfExists(TestRemove.files)

    def test_remove_unknown_files(self):
        """Try to delete unknown files."""
        tree = self.getTree()
        e = self.assertRaises(errors.BzrRemoveChangedFilesError, tree.remove,
            TestRemove.files, keep_files=False)
        self._assertRemoveErrorContainsRe(e, 'unknown:.*b/c.*b.*a.*d')

    def test_remove_nonexisting_files(self):
        """Try to delete non-existing files."""
        tree = self.getTree()
        tree.remove([''], keep_files=False)
        tree.remove(['xyz', 'abc/def'], keep_files=False)

    def test_remove_nonempty_directory(self):
        """Unchanged non-empty directories should be deleted."""
        tree = self.getTree()
        tree.add(TestRemove.files)
        tree.commit("make sure b is versioned")
        self.assertInWorkingTree(TestRemove.files)
        self.failUnlessExists(TestRemove.files)
        tree.remove(TestRemove.b, keep_files=False)
        self.assertNotInWorkingTree(TestRemove.b)
        self.failIfExists(TestRemove.b)

    def test_remove_nonempty_directory_with_unknowns(self):
        """Unchanged non-empty directories should be deleted."""
        tree = self.getTree()
        tree.add(TestRemove.files)
        tree.commit("make sure b is versioned")
        self.assertInWorkingTree(TestRemove.files)
        self.failUnlessExists(TestRemove.files)
        self.build_tree(['b/my_unknown_file'])
        e = self.assertRaises(errors.BzrRemoveChangedFilesError, tree.remove,
            TestRemove.b, keep_files=False)
        self._assertRemoveErrorContainsRe(e, 'unknown:.*b/my_unknown_file')
        self.assertInWorkingTree(TestRemove.b)
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

    def test_remove_directory_with_changed_file(self):
        """Refuse to delete directories with changed files."""
        tree = self.getTree()
        tree.add(TestRemove.b_c)
        tree.commit("make sure b and c are versioned")
        self.build_tree_contents([('b/c', "some other new content!")])
        self.assertInWorkingTree(TestRemove.b_c)
        e = self.assertRaises(errors.BzrRemoveChangedFilesError, tree.remove,
            TestRemove.b, keep_files=False)
        self._assertRemoveErrorContainsRe(e, 'modified:.*b/c')
        self.assertInWorkingTree(TestRemove.b_c)
        self.failUnlessExists(TestRemove.b_c)

        #see if we can force it now..
        tree.remove(TestRemove.b, keep_files=False, force=True)
        self.assertNotInWorkingTree(TestRemove.b_c)
        self.failIfExists(TestRemove.b_c)
