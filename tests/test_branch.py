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

import svn.core, svn.client
import format
from tests import TestCaseWithSubversionRepository
from bzrlib.branch import Branch
from bzrlib.bzrdir import BzrDir, BzrDirTestProviderAdapter, BzrDirFormat
from bzrlib.repository import Repository

class WorkingSubversionBranch(TestCaseWithSubversionRepository):
    def test_num_revnums(self):
        repos_url = self.make_client('a', 'dc')
        bzrdir = BzrDir.open("svn+"+repos_url)
        branch = bzrdir.open_branch()
        self.assertEqual(None, branch.last_revision())

        self.build_tree({'dc/foo': "data"})
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")
        
        bzrdir = BzrDir.open("svn+"+repos_url)
        branch = bzrdir.open_branch()
        repos = bzrdir.open_repository()

        self.assertEqual("svn-v1:1@%s-" % repos.uuid, branch.last_revision())

        self.build_tree({'dc/foo': "data2"})
        self.client_commit("dc", "My Message")

        branch = Branch.open("svn+"+repos_url)
        repos = Repository.open("svn+"+repos_url)

        self.assertEqual("svn-v1:2@%s-" % repos.uuid, branch.last_revision())

    def test_revision_history(self):
        repos_url = self.make_client('a', 'dc')

        branch = Branch.open("svn+"+repos_url)
        self.assertEqual([], branch.revision_history())

        self.build_tree({'dc/foo': "data"})
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")
        
        branch = Branch.open("svn+"+repos_url)
        repos = Repository.open("svn+"+repos_url)

        self.assertEqual(["svn-v1:1@%s-" % repos.uuid], branch.revision_history())

        self.build_tree({'dc/foo': "data34"})
        self.client_commit("dc", "My Message")

        branch = Branch.open("svn+"+repos_url)
        repos = Repository.open("svn+"+repos_url)

        self.assertEqual([
            "svn-v1:1@%s-" % repos.uuid, 
            "svn-v1:2@%s-" % repos.uuid],
            branch.revision_history())

    def test_get_nick(self):
        repos_url = self.make_client('a', 'dc')

        self.build_tree({'dc/foo': "data"})
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")

        branch = Branch.open("svn+"+repos_url)

        self.assertIs(None, branch.nick)
 
