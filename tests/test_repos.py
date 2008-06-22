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

"""Subversion rpeository library tests."""

import os
from bzrlib.plugins.svn import repos
from bzrlib.tests import TestCaseInTempDir

class TestClient(TestCaseInTempDir):
    def setUp(self):
        super(TestClient, self).setUp()

    def test_create(self):
        repos.create(os.path.join(self.test_dir, "foo"))

    def test_open(self):
        repos.create(os.path.join(self.test_dir, "foo"))
        repos.Repository("foo")

    def test_uuid(self):
        repos.create(os.path.join(self.test_dir, "foo"))
        self.assertIsInstance(repos.Repository("foo").fs().get_uuid(), str)
