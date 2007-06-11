# Copyright (C) 2006-2007 Jelmer Vernooij <jelmer@samba.org>

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

"""Branch property access tests."""

from bzrlib.errors import NoSuchRevision

from tests import TestCaseWithSubversionRepository
from branchprops import BranchPropertyList
from logwalker import LogWalker
from transport import SvnRaTransport

try:
    import sqlite3
except ImportError:
    from pysqlite2 import dbapi2 as sqlite3

class TestBranchProps(TestCaseWithSubversionRepository):
    def setUp(self):
        super(TestBranchProps, self).setUp()
        self.db = sqlite3.connect(":memory:")

    def test_get_property(self):
        repos_url = self.make_client('d', 'dc')
        self.client_set_prop("dc", "myprop", "data")
        self.client_commit("dc", "My Message")

        logwalk = LogWalker(transport=SvnRaTransport(repos_url))

        bp = BranchPropertyList(logwalk, self.db)
        self.assertEqual("data", bp.get_property("", 1, "myprop"))

    def test_get_property_norev(self):
        repos_url = self.make_client('d', 'dc')
        self.client_set_prop("dc", "myprop", "data")
        self.client_commit("dc", "My Message")

        logwalk = LogWalker(transport=SvnRaTransport(repos_url))

        bp = BranchPropertyList(logwalk, self.db)
        self.assertRaises(NoSuchRevision, bp.get_property, "", 10, "myprop")

    def test_get_old_property(self):
        repos_url = self.make_client('d', 'dc')
        self.client_set_prop("dc", "myprop", "data")
        self.client_commit("dc", "My Message")
        self.build_tree({'dc/foo': "bla"})
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")

        logwalk = LogWalker(transport=SvnRaTransport(repos_url))

        bp = BranchPropertyList(logwalk, self.db)
        self.assertEqual("data", bp.get_property("", 2, "myprop"))

    def test_get_nonexistent_property(self):
        repos_url = self.make_client('d', 'dc')
        self.client_set_prop("dc", "myprop", "data")
        self.client_commit("dc", "My Message")

        logwalk = LogWalker(transport=SvnRaTransport(repos_url))

        bp = BranchPropertyList(logwalk, self.db)
        self.assertEqual(None, bp.get_property("", 1, "otherprop"))

    def test_get_properties(self):
        repos_url = self.make_client('d', 'dc')
        self.client_set_prop("dc", "myprop", "data")
        self.client_commit("dc", "My Message")

        transport = SvnRaTransport(repos_url)
        logwalk = LogWalker(transport=transport)

        bp = BranchPropertyList(logwalk, self.db)
        props = bp.get_properties("", 1)
        self.assertEqual("data", props["myprop"])
        self.assertEqual(transport.get_uuid(), props["svn:entry:uuid"])
        self.assertEqual('1', props["svn:entry:committed-rev"])
        self.assertTrue("svn:entry:last-author" in props)
        self.assertTrue("svn:entry:committed-date" in props)

    def test_get_property_diff(self):
        repos_url = self.make_client('d', 'dc')
        self.client_set_prop("dc", "myprop", "data\n")
        self.client_commit("dc", "My Message")
        self.client_set_prop("dc", "myprop", "data\ndata2\n")
        self.client_commit("dc", "My Message")

        logwalk = LogWalker(transport=SvnRaTransport(repos_url))

        bp = BranchPropertyList(logwalk, self.db)
        self.assertEqual("data2\n", bp.get_property_diff("", 2, "myprop"))

    def test_get_property_diff_ignore_origchange(self):
        repos_url = self.make_client('d', 'dc')
        self.client_set_prop("dc", "myprop", "foodata\n")
        self.client_commit("dc", "My Message")
        self.client_set_prop("dc", "myprop", "data\ndata2\n")
        self.client_commit("dc", "My Message")

        logwalk = LogWalker(transport=SvnRaTransport(repos_url))

        bp = BranchPropertyList(logwalk, self.db)
        self.assertEqual("", bp.get_property_diff("", 2, "myprop"))
