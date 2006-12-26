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
        logwalker.LogWalker(transport=SvnRaTransport(repos_url))

    def test_get_branch_log(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({'dc/foo': "data"})
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")

        walker = logwalker.LogWalker(transport=SvnRaTransport(repos_url))

        self.assertEqual(1, len(list(walker.follow_path("", 1))))

    def test_get_revision_paths(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({'dc/foo': "data"})
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")
        walker = logwalker.LogWalker(SvnRaTransport(repos_url))
        self.assertEqual({"foo": ('A', None, -1)}, walker.get_revision_paths(1))
        self.assertEqual({"foo": ('A', None, -1)}, walker.get_revision_paths(1, "foo"))
        self.assertEqual({"": ('A', None, -1)}, walker.get_revision_paths(0, "foo"))

    def test_get_revision_paths_zero(self):
        repos_url = self.make_client("a", "dc")
        walker = logwalker.LogWalker(SvnRaTransport(repos_url))
        self.assertEqual({'': ('A', None, -1)}, walker.get_revision_paths(0))

    def test_get_branch_invalid_revision(self):
        repos_url = self.make_client("a", "dc")
        walker = logwalker.LogWalker(transport=SvnRaTransport(repos_url))
        self.assertRaises(NoSuchRevision, list, 
                          walker.follow_path("/", 20))


    def test_branch_log_all(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({'dc/trunk/file': "data", "dc/foo/file":"data"})
        self.client_add("dc/trunk")
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")

        walker = logwalker.LogWalker(transport=SvnRaTransport(repos_url))

        self.assertEqual(1, len(list(walker.follow_path("", 1))))

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

        walker = logwalker.LogWalker(transport=SvnRaTransport(repos_url))

        self.assertEqual(1, len(list(walker.follow_path("branches/brancha",
            1))))

    def test_find_latest_none(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({'dc/branches': None})
        self.client_add("dc/branches")
        self.client_commit("dc", "My Message")

        walker = logwalker.LogWalker(transport=SvnRaTransport(repos_url))

        self.assertEqual(0, walker.find_latest_change("", 1))

    def test_find_latest_change(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({'dc/branches': None})
        self.client_add("dc/branches")
        self.client_commit("dc", "My Message")

        walker = logwalker.LogWalker(transport=SvnRaTransport(repos_url))

        self.assertEqual(1, walker.find_latest_change("branches", 1))

    def test_find_latest_change_children(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({'dc/branches': None})
        self.client_add("dc/branches")
        self.client_commit("dc", "My Message")
        self.build_tree({'dc/branches/foo': 'data'})
        self.client_add("dc/branches/foo")
        self.client_commit("dc", "My Message2")

        walker = logwalker.LogWalker(transport=SvnRaTransport(repos_url))

        self.assertEqual(1, walker.find_latest_change("branches", 2))

    def test_find_latest_change_prop(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({'dc/branches': None})
        self.client_add("dc/branches")
        self.client_commit("dc", "My Message")
        self.build_tree({'dc/branches/foo': 'data'})
        self.client_set_prop("dc/branches", "myprop", "mydata")
        self.client_commit("dc", "propchange")
        self.client_add("dc/branches/foo")
        self.client_commit("dc", "My Message2")

        walker = logwalker.LogWalker(transport=SvnRaTransport(repos_url))

        self.assertEqual(2, walker.find_latest_change("branches", 3))

    def test_find_latest_change_file(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({'dc/branches': None})
        self.client_add("dc/branches")
        self.client_commit("dc", "My Message")
        self.build_tree({'dc/branches/foo': 'data'})
        self.client_add("dc/branches/foo")
        self.client_commit("dc", "propchange")
        self.build_tree({'dc/branches/foo': 'data4'})
        self.client_commit("dc", "My Message2")

        walker = logwalker.LogWalker(transport=SvnRaTransport(repos_url))

        self.assertEqual(3, walker.find_latest_change("branches/foo", 3))

    def test_find_latest_change_newer(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({'dc/branches': None})
        self.client_add("dc/branches")
        self.client_commit("dc", "My Message")
        self.build_tree({'dc/branches/foo': 'data'})
        self.client_add("dc/branches/foo")
        self.client_commit("dc", "propchange")
        self.build_tree({'dc/branches/foo': 'data4'})
        self.client_commit("dc", "My Message2")

        walker = logwalker.LogWalker(transport=SvnRaTransport(repos_url))

        self.assertEqual(2, walker.find_latest_change("branches/foo", 2))

    def test_follow_history_branch_replace(self):
        repos_url = self.make_client("a", "dc")

        self.build_tree({'dc/trunk/data': "data"})
        self.client_add("dc/trunk")
        self.client_commit("dc", "Cm1")

        self.client_delete("dc/trunk")
        self.client_commit("dc", "Cm1")

        self.build_tree({'dc/trunk/data': "data"})
        self.client_add("dc/trunk")
        self.client_commit("dc", "Cm1")

        walker = logwalker.LogWalker(transport=SvnRaTransport(repos_url))
        self.assertEqual([("trunk", {"trunk/data": ('A', None, -1),
                                     "trunk": ('A', None, -1)}, 3)], 
                list(walker.follow_path("trunk", 3)))

    def test_follow_history(self):
        repos_url = self.make_client("a", "dc")
        walker = logwalker.LogWalker(transport=SvnRaTransport(repos_url))

        self.build_tree({'dc/foo': "data"})
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")

        for (branch, paths, rev) in walker.follow_path("", 1):
           self.assertEqual(branch, "")
           self.assertTrue(paths.has_key("foo"))
           self.assertEqual(rev, 1)

    def test_follow_history_nohist(self):
        repos_url = self.make_client("a", "dc")
        walker = logwalker.LogWalker(transport=SvnRaTransport(repos_url))

        self.assertEqual([], list(walker.follow_path("", 0)))

    def test_later_update(self):
        repos_url = self.make_client("a", "dc")

        walker = logwalker.LogWalker(transport=SvnRaTransport(repos_url))

        self.build_tree({'dc/foo': "data"})
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")

        for (branch, paths, rev) in walker.follow_path("", 1):
           self.assertEqual(branch, "")
           self.assertTrue(paths.has_key("foo"))
           self.assertEqual(rev, 1)

        iter = walker.follow_path("", 2)
        self.assertRaises(NoSuchRevision, list, iter)

    def test_get_branch_log_follow(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({'dc/trunk/afile': "data", "dc/branches": None})
        self.client_add("dc/trunk")
        self.client_add("dc/branches")
        self.client_commit("dc", "My Message")

        self.client_copy("dc/trunk", "dc/branches/abranch")
        self.client_commit("dc", "Create branch")

        walker = logwalker.LogWalker(transport=SvnRaTransport(repos_url))

        items = list(walker.follow_path("branches/abranch", 2))
        self.assertEqual(2, len(items))

    def test_touches_path(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({'dc/trunk/afile': "data"})
        self.client_add("dc/trunk")
        self.client_commit("dc", "My Message")

        walker = logwalker.LogWalker(transport=SvnRaTransport(repos_url))

        self.assertTrue(walker.touches_path("trunk", 1))

    def test_touches_path_null(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({'dc/trunk/afile': "data"})
        self.client_add("dc/trunk")
        self.client_commit("dc", "My Message")

        walker = logwalker.LogWalker(transport=SvnRaTransport(repos_url))

        self.assertTrue(walker.touches_path("", 0))

    def test_touches_path_not(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({'dc/trunk/afile': "data"})
        self.client_add("dc/trunk")
        self.client_commit("dc", "My Message")

        walker = logwalker.LogWalker(transport=SvnRaTransport(repos_url))

        self.assertFalse(walker.touches_path("", 1))

    def test_touches_path_child(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({'dc/trunk/afile': "data"})
        self.client_add("dc/trunk")
        self.client_commit("dc", "My Message")
        self.build_tree({'dc/trunk/afile': "data2"})
        self.client_commit("dc", "My Message")

        walker = logwalker.LogWalker(transport=SvnRaTransport(repos_url))

        self.assertFalse(walker.touches_path("trunk", 2))

    def test_get_previous_simple(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({'dc/trunk/afile': "data"})
        self.client_add("dc/trunk")
        self.client_commit("dc", "My Message")
        self.build_tree({'dc/trunk/afile': "data2"})
        self.client_set_prop("dc/trunk", "myprop", "mydata")
        self.client_commit("dc", "My Message")

        walker = logwalker.LogWalker(transport=SvnRaTransport(repos_url))

        self.assertEqual(("trunk", 1), walker.get_previous("trunk", 2))

    def test_get_previous_added(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({'dc/trunk/afile': "data"})
        self.client_add("dc/trunk")
        self.client_commit("dc", "My Message")
        self.build_tree({'dc/trunk/afile': "data2"})
        self.client_set_prop("dc/trunk", "myprop", "mydata")
        self.client_commit("dc", "My Message")

        walker = logwalker.LogWalker(transport=SvnRaTransport(repos_url))

        self.assertEqual((None, -1), walker.get_previous("trunk", 1))

    def test_get_previous_copy(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({'dc/trunk/afile': "data"})
        self.client_add("dc/trunk")
        self.client_commit("dc", "My Message")
        self.client_copy("dc/trunk", "dc/anotherfile")
        self.client_commit("dc", "My Message")

        walker = logwalker.LogWalker(transport=SvnRaTransport(repos_url))

        self.assertEqual(("trunk", 1), walker.get_previous("anotherfile", 2))

    def test_get_revision_info(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({'dc/trunk/afile': "data"})
        self.client_add("dc/trunk")
        self.client_commit("dc", "My Message")

        walker = logwalker.LogWalker(transport=SvnRaTransport(repos_url))

        info = walker.get_revision_info(1)

        self.assertEqual("", info[0])
        self.assertEqual("My Message", info[1])

    def test_find_children_empty(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({'dc/trunk': None})
        self.client_add("dc/trunk")
        self.client_commit("dc", "My Message")

        walker = logwalker.LogWalker(transport=SvnRaTransport(repos_url))

        self.assertEqual([], list(walker.find_children("trunk", 1)))

    def test_find_children_one(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({'dc/trunk/data': 'foo'})
        self.client_add("dc/trunk")
        self.client_commit("dc", "My Message")

        walker = logwalker.LogWalker(transport=SvnRaTransport(repos_url))

        self.assertEqual(['trunk/data'], list(walker.find_children("trunk", 1)))

    def test_find_children_nested(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({'dc/trunk/data/bla': 'foo', 'dc/trunk/file': 'bla'})
        self.client_add("dc/trunk")
        self.client_commit("dc", "My Message")

        walker = logwalker.LogWalker(transport=SvnRaTransport(repos_url))

        self.assertEqual(['trunk/data', 'trunk/data/bla', 'trunk/file'], 
                list(walker.find_children("trunk", 1)))

    def test_find_children_later(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({'dc/trunk/data/bla': 'foo'})
        self.client_add("dc/trunk")
        self.client_commit("dc", "My Message")
        self.build_tree({'dc/trunk/file': 'bla'})
        self.client_add("dc/trunk/file")
        self.client_commit("dc", "My Message")

        walker = logwalker.LogWalker(transport=SvnRaTransport(repos_url))

        self.assertEqual(['trunk/data', 'trunk/data/bla'], 
                list(walker.find_children("trunk", 1)))
        self.assertEqual(['trunk/data', 'trunk/data/bla', 'trunk/file'], 
                list(walker.find_children("trunk", 2)))
