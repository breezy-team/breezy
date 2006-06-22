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
from bzrlib.tests.repository_implementations.test_repository import TestCaseWithRepository

import os
import svn
import logwalker
from tests import TestCaseWithSubversionRepository

class TestLogWalker(TestCaseWithSubversionRepository):
    def setUp(self):
        super(TestLogWalker, self).setUp()

        logwalker.cache_dir = os.path.join(self.test_dir, "cache-dir")

    def test_create(self):
        repos_url = self.make_client("a", "ac")
        logwalker.LogWalker(repos_url=repos_url)

    def test_follow_history(self):
        repos_url = self.make_client("a", "dc")
        walker = logwalker.LogWalker(repos_url=repos_url)

        self.build_tree({'dc/foo': "data"})
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")

        for (paths, rev) in walker.follow_history("", 1):
           self.assertTrue(paths.has_key("foo"))
           self.assertEqual(rev, 1)

    def test_later_update(self):
        repos_url = self.make_client("a", "dc")

        walker = logwalker.LogWalker(repos_url=repos_url)

        self.build_tree({'dc/foo': "data"})
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")

        for (paths, rev) in walker.follow_history("", 1):
           self.assertTrue(paths.has_key("foo"))
           self.assertEqual(rev, 1)

        self.assertRaises(NoSuchRevision, self.follow_history, "", 2)
