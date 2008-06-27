# Copyright (C) 2005-2007 Jelmer Vernooij <jelmer@samba.org>
 
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""Subversion client library tests."""

from bzrlib.tests import TestCase
from bzrlib.plugins.svn import client
from bzrlib.plugins.svn.tests import TestCaseWithSubversionRepository

class TestClient(TestCaseWithSubversionRepository):
    def setUp(self):
        super(TestClient, self).setUp()
        self.repos_url = self.make_client("d", "dc")
        self.client = client.Client()

    def test_add(self):
        self.build_tree({"dc/foo": None})
        self.client.add("dc/foo")

    def test_get_config(self):
        self.assertIsInstance(client.get_config().__dict__, dict)

