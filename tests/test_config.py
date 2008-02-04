# Copyright (C) 2007 Jelmer Vernooij <jelmer@samba.org>

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

"""Config tests."""

from config import SvnRepositoryConfig
from scheme import TrunkBranchingScheme

from bzrlib.tests import TestCaseInTempDir

class ReposConfigTests(TestCaseInTempDir):
    def test_create(self):
        SvnRepositoryConfig("blabla")

    def test_get_empty_locations(self):
        c = SvnRepositoryConfig("blabla6")
        self.assertEquals(set(), c.get_locations())

    def test_get_location_one(self):
        c = SvnRepositoryConfig("blabla5")
        c.add_location("foobar")
        self.assertEquals(set(["foobar"]), c.get_locations())

    def test_get_location_two(self):
        c = SvnRepositoryConfig("blabla4")
        c.add_location("foobar")
        c.add_location("brainslug")
        self.assertEquals(set(["foobar", "brainslug"]), c.get_locations())

    def test_get_scheme_none(self):
        c = SvnRepositoryConfig("blabla3")
        self.assertEquals(None, c.get_branching_scheme())

    def test_get_scheme_set(self):
        c = SvnRepositoryConfig("blabla2")
        c.set_branching_scheme(TrunkBranchingScheme())
        self.assertEquals("trunk0", str(c.get_branching_scheme()))

    def test_get_scheme_mandatory_none(self):
        c = SvnRepositoryConfig("blabla3")
        self.assertEquals(False, c.branching_scheme_is_mandatory())

    def test_get_scheme_mandatory_set(self):
        c = SvnRepositoryConfig("blabla3")
        c.set_branching_scheme(TrunkBranchingScheme(), mandatory=True)
        self.assertEquals(True, c.branching_scheme_is_mandatory())
        c.set_branching_scheme(TrunkBranchingScheme(), mandatory=False)
        self.assertEquals(False, c.branching_scheme_is_mandatory())

    def test_override_revprops(self):
        c = SvnRepositoryConfig("blabla2")
        self.assertEquals(None, c.get_override_svn_revprops())
        c.set_user_option("override-svn-revprops", "True")
        self.assertEquals(True, c.get_override_svn_revprops())
        c.set_user_option("override-svn-revprops", "False")
        self.assertEquals(False, c.get_override_svn_revprops())

    def test_set_revprops(self):
        c = SvnRepositoryConfig("blabla2")
        self.assertEquals(None, c.get_set_revprops())
        c.set_user_option("set-revprops", "True")
        self.assertEquals(True, c.get_set_revprops())
        c.set_user_option("set-revprops", "False")
        self.assertEquals(False, c.get_set_revprops())

    def test_supports_change_revprop(self):
        c = SvnRepositoryConfig("blabla2")
        self.assertEquals(None, c.get_supports_change_revprop())
        c.set_user_option("supports-change-revprop", "True")
        self.assertEquals(True, c.get_supports_change_revprop())
        c.set_user_option("supports-change-revprop", "False")
        self.assertEquals(False, c.get_supports_change_revprop())
