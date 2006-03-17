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

class TestSharedRepo(TestCaseInTempDir):
    def test_make_repository(self):
        self.run_bzr("make-repository", "a")
        self.assertIs(os.path.exists("a/.bzr/repository"), True)
        self.assertIs(os.path.exists("a/.bzr/branch"), False)
        self.assertIs(os.path.exists("a/.bzr/checkout"), False)

    def test_init(self):
        self.run_bzr("make-repo", "a")
        self.run_bzr("init", "--format=metadir", "a/b")
        self.assertIs(os.path.exists("a/.bzr/repository"), True)
        self.assertIs(os.path.exists("a/b/.bzr/branch/revision-history"), True)
        self.assertIs(os.path.exists("a/b/.bzr/repository"), False)

    def test_branch(self):
        self.run_bzr("make-repo", "a")
        self.run_bzr("init", "--format=metadir", "a/b")
        self.run_bzr('branch', 'a/b', 'a/c')
        self.assertIs(os.path.exists("a/c/.bzr/branch/revision-history"), True)
        self.assertIs(os.path.exists("a/c/.bzr/repository"), False)
