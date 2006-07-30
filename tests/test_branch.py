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

from bzrlib.branch import Branch
from bzrlib.bzrdir import BzrDir, BzrDirTestProviderAdapter, BzrDirFormat
from bzrlib.repository import Repository
from bzrlib.trace import mutter

import os

import svn.core, svn.client

import format
from tests import TestCaseWithSubversionRepository

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

    def test_fetch_odd(self):
        repos_url = self.make_client('d', 'dc')

        self.build_tree({'dc/trunk': None, 
                         'dc/trunk/hosts': 'hej1'})
        self.client_add("dc/trunk")
        self.client_commit("dc", "created trunk and added hosts") #1

        self.build_tree({'dc/trunk/hosts': 'hej2'})
        self.client_commit("dc", "rev 2") #2

        self.build_tree({'dc/trunk/hosts': 'hej3'})
        self.client_commit("dc", "rev 3") #3

        self.build_tree({'dc/branches': None})
        self.client_add("dc/branches")
        self.client_commit("dc", "added branches") #4

        self.client_copy("dc/trunk", "dc/branches/foobranch")
        self.client_commit("dc", "added branch foobranch") #5

        self.build_tree({'dc/branches/foobranch/hosts': 'foohosts'})
        self.client_commit("dc", "foohosts") #6

        os.mkdir("new")

        url = "svn+"+repos_url+"/branches/foobranch"
        mutter('open %r' % url)
        olddir = BzrDir.open(url)

        newdir = olddir.sprout("new")

        newbranch = newdir.open_branch()

        uuid = olddir.open_repository().uuid
        tree = newbranch.repository.revision_tree(
                "svn-v1:6@%s-branches%%2ffoobranch" % uuid)

        weave = tree.get_weave(tree.inventory.path2id("hosts"))
        self.assertEqual(['svn-v1:1@%s-trunk' % uuid, 
                          'svn-v1:2@%s-trunk' % uuid, 
                          'svn-v1:3@%s-trunk' % uuid, 
                          'svn-v1:6@%s-branches%%2ffoobranch' % uuid],
                          weave.versions())
 
    def test_fetch_branch(self):
        repos_url = self.make_client('d', 'sc')

        self.build_tree({'sc/foo/bla': "data"})
        self.client_add("sc/foo")
        self.client_commit("sc", "foo")

        olddir = BzrDir.open("sc")

        os.mkdir("dc")
        
        newdir = olddir.sprout('dc')

        self.assertEqual(
                olddir.open_branch().last_revision(),
                newdir.open_branch().last_revision())

    def test_ghost_workingtree(self):
        # Looks like bazaar has trouble creating a working tree of a 
        # revision that has ghost parents
        repos_url = self.make_client('d', 'sc')

        self.build_tree({'sc/foo/bla': "data"})
        self.client_add("sc/foo")
        self.client_set_prop("sc", "bzr:merge", "some-ghost\n")
        self.client_commit("sc", "foo")

        olddir = BzrDir.open("sc")

        os.mkdir("dc")
        
        newdir = olddir.sprout('dc')
        newdir.open_repository().get_revision(
                newdir.open_branch().last_revision())
        newdir.open_repository().get_revision_inventory(
                newdir.open_branch().last_revision())
