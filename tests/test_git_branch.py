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

"""Tests for interfacing with a Git Branch"""

import subprocess

from bzrlib import branch, revision

from bzrlib.plugins.git import tests
from bzrlib.plugins.git.gitlib import (
    git_branch,
    ids,
    )


class TestGitBranch(tests.TestCaseInTempDir):

    _test_needs_features = [tests.GitCommandFeature]

    def test_open_existing(self):
        tests.run_git('init')

        thebranch = branch.Branch.open('.')
        self.assertIsInstance(thebranch, git_branch.GitBranch)

    def test_last_revision_is_null(self):
        tests.run_git('init')

        thebranch = branch.Branch.open('.')
        self.assertEqual(revision.NULL_REVISION, thebranch.last_revision())
        self.assertEqual((0, revision.NULL_REVISION),
                         thebranch.last_revision_info())

    def test_last_revision_is_valid(self):
        tests.run_git('init')
        self.build_tree(['a'])
        tests.run_git('add', 'a')
        tests.run_git('commit', '-m', 'a')
        head = tests.run_git('rev-parse', 'HEAD').strip()

        thebranch = branch.Branch.open('.')
        self.assertEqual(ids.convert_revision_id_git_to_bzr(head),
                         thebranch.last_revision())
