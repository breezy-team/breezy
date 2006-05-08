# Copyright (C) 2006 Jelmer Vernooij <jelmer@samba.org>

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

import svn.repos
import os
from bzrlib import osutils
from bzrlib.bzrdir import BzrDir
from bzrlib.tests import TestCaseInTempDir

class TestCaseWithSubversionRepository(TestCaseInTempDir):
    def setUp(self):
        TestCaseInTempDir.setUp(self)

        self.repos_path = os.path.join(self.test_dir, "svn_repos")
        self.repos = svn.repos.create(self.repos_path, '', '', None, None)
        self.repos_url = "file://%s" % self.repos_path

        self.fs = svn.repos.fs(self.repos)

    def open_bzrdir(self):
        return BzrDir.open("svn+"+self.repos_url)
