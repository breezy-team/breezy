# Copyright (C) 2006-2007 Jelmer Vernooij <jelmer@samba.org>

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
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
from branchprops import PathPropertyProvider
from logwalker import LogWalker
from transport import SvnRaTransport

class TestBranchProps(TestCaseWithSubversionRepository):
    def setUp(self):
        super(TestBranchProps, self).setUp()

    def test_get_old_properties(self):
        repos_url = self.make_client('d', 'dc')
        self.client_set_prop("dc", "myprop", "data")
        self.client_commit("dc", "My Message")
        self.build_tree({'dc/foo': "bla"})
        self.client_add("dc/foo")
        self.client_commit("dc", "My Message")

        logwalk = LogWalker(transport=SvnRaTransport(repos_url))

        bp = PathPropertyProvider(logwalk)

        self.assertEqual("data", bp.get_properties("", 2)["myprop"])

    def test_get_properties(self):
        repos_url = self.make_client('d', 'dc')
        self.client_set_prop("dc", "myprop", "data")
        self.client_commit("dc", "My Message")

        transport = SvnRaTransport(repos_url)
        logwalk = LogWalker(transport=transport)

        bp = PathPropertyProvider(logwalk)
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

        bp = PathPropertyProvider(logwalk)
        self.assertEqual("data2\n", bp.get_property_diff("", 2, "myprop"))

    def test_get_changed_properties(self):
        repos_url = self.make_client('d', 'dc')
        self.client_set_prop("dc", "myprop", "data\n")
        self.client_commit("dc", "My Message")
        self.client_update("dc")
        self.client_set_prop("dc", "myprop", "newdata\n")
        self.client_commit("dc", "My Message")
        self.client_update("dc")
        self.client_set_prop("dc", "myp2", "newdata\n")
        self.client_commit("dc", "My Message")
        self.client_update("dc")

        logwalk = LogWalker(transport=SvnRaTransport(repos_url))

        bp = PathPropertyProvider(logwalk)
        self.assertEquals("data\n",
                          bp.get_changed_properties("", 1)["myprop"])

        bp = PathPropertyProvider(logwalk)
        self.assertEquals("newdata\n", 
                          bp.get_changed_properties("", 2)["myprop"])

        bp = PathPropertyProvider(logwalk)
        self.assertEquals("newdata\n", 
                          bp.get_changed_properties("", 3)["myp2"])

    def test_get_property_diff_ignore_origchange(self):
        repos_url = self.make_client('d', 'dc')
        self.client_set_prop("dc", "myprop", "foodata\n")
        self.client_commit("dc", "My Message")
        self.client_set_prop("dc", "myprop", "data\ndata2\n")
        self.client_commit("dc", "My Message")

        logwalk = LogWalker(transport=SvnRaTransport(repos_url))

        bp = PathPropertyProvider(logwalk)
        self.assertEqual("", bp.get_property_diff("", 2, "myprop"))
