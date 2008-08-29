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

import git

from bzrlib import revision
from bzrlib.branch import Branch

from bzrlib.plugins.git import (
    branch,
    tests,
    )
from bzrlib.plugins.git.mapping import default_mapping


class TestGitBranch(tests.TestCaseInTempDir):

    _test_needs_features = [tests.GitCommandFeature]

    def test_open_existing(self):
        tests.run_git('init')

        thebranch = Branch.open('.')
        self.assertIsInstance(thebranch, branch.GitBranch)

    def test_last_revision_is_null(self):
        tests.run_git('init')

        thebranch = Branch.open('.')
        self.assertEqual(revision.NULL_REVISION, thebranch.last_revision())
        self.assertEqual((0, revision.NULL_REVISION),
                         thebranch.last_revision_info())

    def simple_commit_a(self):
        tests.run_git('init')
        self.build_tree(['a'])
        tests.run_git('add', 'a')
        tests.run_git('commit', '-m', 'a')

    def test_last_revision_is_valid(self):
        self.simple_commit_a()
        head = tests.run_git('rev-parse', 'HEAD').strip()

        thebranch = Branch.open('.')
        self.assertEqual(default_mapping.revision_id_foreign_to_bzr(head),
                         thebranch.last_revision())

    def test_revision_history(self):
        self.simple_commit_a()
        reva = tests.run_git('rev-parse', 'HEAD').strip()
        self.build_tree(['b'])
        tests.run_git('add', 'b')
        tests.run_git('commit', '-m', 'b')
        revb = tests.run_git('rev-parse', 'HEAD').strip()

        thebranch = Branch.open('.')
        self.assertEqual([default_mapping.revision_id_foreign_to_bzr(r) for r in (reva, revb)],
                         thebranch.revision_history())

    def test_tags(self):
        self.simple_commit_a()
        reva = tests.run_git('rev-parse', 'HEAD').strip()
        
        tests.run_git('tag', '-a', '-m', 'add tag', 'foo')
        
        newid = open('.git/refs/tags/foo').read().rstrip()

        thebranch = Branch.open('.')
        self.assertEquals({"foo": default_mapping.revision_id_foreign_to_bzr(newid)},
                          thebranch.tags.get_tag_dict())
        

class TestWithGitBranch(tests.TestCaseWithTransport):

    def setUp(self):
        tests.TestCaseWithTransport.setUp(self)
        git.repo.Repo.create(self.test_dir)
        self.git_branch = Branch.open(self.test_dir)

    def test_get_parent(self):
        self.assertIs(None, self.git_branch.get_parent())

    def test_get_stacked_on_url(self):
        self.assertIs(None, self.git_branch.get_stacked_on_url())

    def test_get_physical_lock_status(self):
        self.assertFalse(self.git_branch.get_physical_lock_status())


class TestGitBranchFormat(tests.TestCase):

    def setUp(self):
        super(TestGitBranchFormat, self).setUp()
        self.format = branch.GitBranchFormat()

    def test_get_format_description(self):
        self.assertEquals("Git Branch", self.format.get_format_description())
