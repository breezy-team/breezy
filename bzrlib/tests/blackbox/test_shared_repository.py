# Copyright (C) 2005 by Canonical Ltd
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

"""Black-box tests for repositories with shared branches"""

import os

from bzrlib.tests import TestCaseInTempDir
import bzrlib.bzrdir
import bzrlib.errors as errors

class TestSharedRepo(TestCaseInTempDir):

    def test_make_repository(self):
        out, err = self.run_bzr("init-repository", "a")
        self.assertEqual(out, "")
        self.assertEqual(err, "")
        dir = bzrlib.bzrdir.BzrDir.open('a')
        self.assertIs(dir.open_repository().is_shared(), True)
        self.assertRaises(errors.NotBranchError, dir.open_branch)
        self.assertRaises(errors.NoWorkingTree, dir.open_workingtree)        

    def test_init(self):
        self.run_bzr("init-repo", "a")
        self.run_bzr("init", "--format=metadir", "a/b")
        dir = bzrlib.bzrdir.BzrDir.open('a')
        self.assertIs(dir.open_repository().is_shared(), True)
        self.assertRaises(errors.NotBranchError, dir.open_branch)
        self.assertRaises(errors.NoWorkingTree, dir.open_workingtree)
        bdir = bzrlib.bzrdir.BzrDir.open('a/b')
        bdir.open_branch()
        self.assertRaises(errors.NoRepositoryPresent, bdir.open_repository)
        self.assertRaises(errors.NoWorkingTree, bdir.open_workingtree)

    def test_branch(self):
        self.run_bzr("init-repo", "a")
        self.run_bzr("init", "--format=metadir", "a/b")
        self.run_bzr('branch', 'a/b', 'a/c')
        cdir = bzrlib.bzrdir.BzrDir.open('a/c')
        cdir.open_branch()
        self.assertRaises(errors.NoRepositoryPresent, cdir.open_repository)
        self.assertRaises(errors.NoWorkingTree, cdir.open_workingtree)

    def test_branch_tree(self):
        self.run_bzr("init-repo", "--trees", "a")
        self.run_bzr("init", "--format=metadir", "b")
        file('b/hello', 'wt').write('bar')
        self.run_bzr("add", "b/hello")
        self.run_bzr("commit", "-m", "bar", "b/hello")

        self.run_bzr('branch', 'b', 'a/c')
        cdir = bzrlib.bzrdir.BzrDir.open('a/c')
        cdir.open_branch()
        self.assertRaises(errors.NoRepositoryPresent, cdir.open_repository)
        self.failUnlessExists('a/c/hello')
        cdir.open_workingtree()

