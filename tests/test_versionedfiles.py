# Copyright (C) 2011 Canonical Ltd
# Authors: Jelmer Vernooij <jelmer@canonical.com>
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

"""Tests for git-like versioned files."""

from dulwich.repo import Repo as GitRepo

from bzrlib.repository import Repository
from bzrlib.tests import TestCaseInTempDir

from bzrlib.plugins.git import tests

class GitRevisionsTests(TestCaseInTempDir):

    def setUp(self):
        super(GitRevisionsTests, self).setUp()
        self.gitrepo = GitRepo.init(self.test_dir)
        self.revisions = Repository.open(self.test_dir).revisions

    def _do_commit(self):
        builder = tests.GitBranchBuilder()
        builder.set_file('a', 'text for a\n', False)
        commit_handle = builder.commit('Joe Foo <joe@foo.com>', u'message')
        mapping = builder.finish()
        return mapping[commit_handle]

    def test_empty(self):
        self.assertEquals([], self.revisions.keys())

    def test_check(self):
        # Just a no-op at the moment
        self.assertTrue(self.revisions.check())

    def test_revision(self):
        gitsha = self._do_commit()
        self.assertEquals([(gitsha,)], self.revisions.keys())
