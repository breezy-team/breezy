# Copyright (C) 2007 Canonical Ltd
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

"""Tests for interfacing with a Git Repository"""

import subprocess

from bzrlib import repository

from bzrlib.plugins.git import tests
from bzrlib.plugins.git.gitlib import git_repository


class TestGitRepository(tests.TestCaseInTempDir):

    _test_needs_features = [tests.GitCommandFeature]

    def test_open_existing(self):
        p = subprocess.Popen(['git', 'init'],
                             stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE)
        p.communicate()

        gd = repository.Repository.open('.')
        self.assertIsInstance(gd, git_repository.GitRepository)
