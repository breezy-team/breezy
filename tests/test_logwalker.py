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
from transport import SvnRaTransport

class TestLogWalker(TestCaseWithSubversionRepository):
    def setUp(self):
        super(TestLogWalker, self).setUp()

        logwalker.cache_dir = os.path.join(self.test_dir, "cache-dir")

    def test_create(self):
        repos_url = self.make_client("a", "ac")
        logwalker.LogWalker(NoBranchingScheme(), transport=SvnRaTransport(repos_url))

    def test_get_branch_log(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({'dc/foo': "data"})
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")

        walker = logwalker.LogWalker(NoBranchingScheme(), 
                                     transport=SvnRaTransport(repos_url))

        self.assertEqual(1, len(list(walker.follow_history("", 1))))

    def test_get_branch_invalid_revision(self):
        repos_url = self.make_client("a", "dc")
        walker = logwalker.LogWalker(NoBranchingScheme(), 
                                     transport=SvnRaTransport(repos_url))
        self.assertRaises(NoSuchRevision, list, 
                          walker.follow_history("/", 20))

    def test_invalid_branch_path(self):
        repos_url = self.make_client("a", "dc")
        walker = logwalker.LogWalker(NoBranchingScheme(), 
                                     transport=SvnRaTransport(repos_url))

        self.assertRaises(logwalker.NotSvnBranchPath, list, 
                          walker.follow_history("foobar", 0))

    def test_branch_log_all(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({'dc/trunk/file': "data", "dc/foo/file":"data"})
        self.client_add("dc/trunk")
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")

        walker = logwalker.LogWalker(TrunkBranchingScheme(), 
                                     transport=SvnRaTransport(repos_url))

        self.assertEqual(1, len(list(walker.follow_history(None, 1))))

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
                                     transport=SvnRaTransport(repos_url))

        self.assertEqual(1, len(list(walker.follow_history("branches/brancha",
            1))))

    def test_find_branches_no(self):
        repos_url = self.make_client("a", "dc")

        walker = logwalker.LogWalker(NoBranchingScheme(), 
                                     transport=SvnRaTransport(repos_url))

        self.assertEqual([("", 0, True)], list(walker.find_branches(0)))

    def test_find_branches_no_later(self):
        repos_url = self.make_client("a", "dc")

        walker = logwalker.LogWalker(NoBranchingScheme(), 
                                     transport=SvnRaTransport(repos_url))

        self.assertEqual([("", 0, True)], list(walker.find_branches(0)))

    def test_find_branches_trunk_empty(self):
        repos_url = self.make_client("a", "dc")

        walker = logwalker.LogWalker(TrunkBranchingScheme(), 
                                     transport=SvnRaTransport(repos_url))

        self.assertEqual([], list(walker.find_branches(0)))

    def test_find_branches_trunk_one(self):
        repos_url = self.make_client("a", "dc")

        walker = logwalker.LogWalker(TrunkBranchingScheme(), 
                                     transport=SvnRaTransport(repos_url))

        self.build_tree({'dc/trunk/foo': "data"})
        self.client_add("dc/trunk")
        self.client_commit("dc", "My Message")

        self.assertEqual([("trunk", 1, True)], list(walker.find_branches(1)))

    def test_find_branches_removed(self):
        repos_url = self.make_client("a", "dc")

        walker = logwalker.LogWalker(TrunkBranchingScheme(), 
                                     transport=SvnRaTransport(repos_url))

        self.build_tree({'dc/trunk/foo': "data"})
        self.client_add("dc/trunk")
        self.client_commit("dc", "My Message")

        self.client_delete("dc/trunk")
        self.client_commit("dc", "remove")

        self.assertEqual([("trunk", 1, True)], list(walker.find_branches(1)))
        self.assertEqual([("trunk", 2, False)], list(walker.find_branches(2)))

    def test_follow_history(self):
        repos_url = self.make_client("a", "dc")
        walker = logwalker.LogWalker(NoBranchingScheme(), 
                                     transport=SvnRaTransport(repos_url))

        self.build_tree({'dc/foo': "data"})
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")

        for (branch, paths, rev) in walker.follow_history("", 1):
           self.assertEqual(branch, "")
           self.assertTrue(paths.has_key("foo"))
           self.assertEqual(rev, 1)

    def test_later_update(self):
        repos_url = self.make_client("a", "dc")

        walker = logwalker.LogWalker(NoBranchingScheme(), 
                                     transport=SvnRaTransport(repos_url))

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
                                     transport=SvnRaTransport(repos_url))

        items = list(walker.follow_history("branches/abranch", 2))
        self.assertEqual(2, len(items))


