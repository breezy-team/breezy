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

from bzrlib.plugins.svn.log import show_subversion_properties
from bzrlib.revision import Revision

from bzrlib.tests import TestCase

class LogTestCase(TestCase):
    def test_notsvn(self):
        self.assertEquals({}, show_subversion_properties(Revision("foo")))

    def test_svnprops(self):
        rev = Revision("foo")
        rev.svn_revision = 2
        rev.svn_branch = "bar"
        self.assertEquals({"svn revno": "2 (on /bar)"}, 
                          show_subversion_properties(rev))

    def test_svnrevid(self):
        rev = Revision("svn-v3-trunk0:someuuid:lala:23")
        self.assertEquals({"svn revno": "23 (on /lala)"},
                          show_subversion_properties(rev))

