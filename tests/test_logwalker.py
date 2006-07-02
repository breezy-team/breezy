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

from bzrlib.bzrdir import BzrDir
from bzrlib.errors import NoSuchRevision
from bzrlib.inventory import Inventory

import os
import logwalker
from scheme import NoBranchingScheme, TrunkBranchingScheme
from tests import TestCaseWithSubversionRepository

class TestLogWalker(TestCaseWithSubversionRepository):
    def setUp(self):
        super(TestLogWalker, self).setUp()

        logwalker.cache_dir = os.path.join(self.test_dir, "cache-dir")

    def test_create(self):
        repos_url = self.make_client("a", "ac")
        logwalker.LogWalker(NoBranchingScheme(), repos_url=repos_url)

    def test_get_branch_log(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({'dc/foo': "data"})
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")

        walker = logwalker.LogWalker(NoBranchingScheme(), repos_url=repos_url)

        self.assertEqual(1, len(list(walker.get_branch_log("", 1, 0))))

    def test_get_branch_invalid_revision(self):
        repos_url = self.make_client("a", "dc")
        walker = logwalker.LogWalker(NoBranchingScheme(), repos_url=repos_url)
        self.assertRaises(NoSuchRevision, list, 
                          walker.get_branch_log("/", 20, 1))

    def test_invalid_branch_path(self):
        repos_url = self.make_client("a", "dc")
        walker = logwalker.LogWalker(NoBranchingScheme(), repos_url=repos_url)

        self.assertRaises(logwalker.NotSvnBranchPath, list, 
                          walker.get_branch_log("foobar", 0, 0))

    def test_branch_log_all(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({'dc/trunk/file': "data", "dc/foo/file":"data"})
        self.client_add("dc/trunk")
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")

        walker = logwalker.LogWalker(TrunkBranchingScheme(), 
                                     repos_url=repos_url)

        self.assertEqual(1, len(list(walker.get_branch_log(None, 1, 0))))

    def test_branch_log_specific(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({
            'dc/branches': None,
            'dc/branches/brancha': None,
            'dc/branches/branchab': None,
            'dc/branches/brancha/data': "data", 
            "dc/branches/branchab/data":"data"})
        self.client_add("dc/branches")
        self.client_commit("dc", "My Message")

        walker = logwalker.LogWalker(TrunkBranchingScheme(), 
                                     repos_url=repos_url)

        self.assertEqual(1, len(list(walker.get_branch_log("branches/brancha",
            1, 0))))

    def test_follow_history(self):
        repos_url = self.make_client("a", "dc")
        walker = logwalker.LogWalker(NoBranchingScheme(), repos_url=repos_url)

        self.build_tree({'dc/foo': "data"})
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")

        for (branch, paths, rev) in walker.follow_history("", 1):
           self.assertEqual(branch, "")
           self.assertTrue(paths.has_key("foo"))
           self.assertEqual(rev, 1)

    def test_later_update(self):
        repos_url = self.make_client("a", "dc")

        walker = logwalker.LogWalker(NoBranchingScheme(), repos_url=repos_url)

        self.build_tree({'dc/foo': "data"})
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")

        for (branch, paths, rev) in walker.follow_history("", 1):
           self.assertEqual(branch, "")
           self.assertTrue(paths.has_key("foo"))
           self.assertEqual(rev, 1)

        iter = walker.follow_history("", 2)
        self.assertRaises(NoSuchRevision, list, iter)

    def test_get_branch_log_follow(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({'dc/trunk/afile': "data", "dc/branches": None})
        self.client_add("dc/trunk")
        self.client_add("dc/branches")
        self.client_commit("dc", "My Message")

        self.client_copy("dc/trunk", "dc/branches/abranch")
        self.client_commit("dc", "Create branch")

        walker = logwalker.LogWalker(TrunkBranchingScheme(), 
                                     repos_url=repos_url)

        items = list(walker.get_branch_log("branches/abranch", 2, 0))
        self.assertEqual(2, len(items))

    def test_get_offspring(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({'dc/trunk/afile': "data"})
        self.client_add("dc/trunk")
        self.client_commit("dc", "My Message")

        self.client_copy("dc/trunk/afile", "dc/trunk/bfile")
        self.client_commit("dc", "Create branch")

        walker = logwalker.LogWalker(TrunkBranchingScheme(), 
                                     repos_url=repos_url)

        self.assertEqual(["trunk/afile", "trunk/bfile"], 
                list(walker.get_offspring("trunk/afile", 1, 2)))

    def test_get_offspring_dir(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({'dc/trunk/afile': "data"})
        self.client_add("dc/trunk")
        self.client_commit("dc", "My Message")

        self.client_copy("dc/trunk", "dc/foobar")
        self.client_commit("dc", "Create branch")

        walker = logwalker.LogWalker(NoBranchingScheme(), 
                                     repos_url=repos_url)

        self.assertEqual(["trunk/afile", "foobar/afile"], 
            list(walker.get_offspring("trunk/afile", 1, 2)))

