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

from bzrlib.errors import NoSuchRevision, InvalidRevisionId
from bzrlib.repository import Repository
from bzrlib.tests import TestCase

from repository import (MAPPING_VERSION, svk_feature_to_revision_id, 
                        revision_id_to_svk_feature)
from revids import RevidMap, parse_svn_revision_id, generate_svn_revision_id
from tests import TestCaseWithSubversionRepository

class TestRevidMap(TestCase):
    def test_create(self):
        revidmap = RevidMap()

    def test_lookup_revid_nonexistant(self):
        revidmap = RevidMap()
        self.assertRaises(NoSuchRevision, lambda: revidmap.lookup_revid("bla"))

    def test_lookup_revid(self):
        revidmap = RevidMap()
        revidmap.insert_revid("bla", "mypath", 42, 42, "brainslug")
        self.assertEquals(("mypath", 42, 42, "brainslug"), 
                revidmap.lookup_revid("bla"))

    def test_lookup_branch(self):
        revidmap = RevidMap()
        revidmap.insert_revid("bla", "mypath", 42, 42, "brainslug")
        self.assertEquals("bla", 
                revidmap.lookup_branch_revnum(42, "mypath", "brainslug"))

    def test_lookup_dist(self):
        revidmap = RevidMap()
        revidmap.insert_revid("bla", "mypath", 42, 42, "brainslug", 
                                    50)
        self.assertEquals(50,
                revidmap.lookup_dist_to_origin("bla"))

    def test_lookup_dist_notset(self):
        revidmap = RevidMap()
        revidmap.insert_revid("bloe", "someotherpath", 42, 42, "brainslug") 
        self.assertIs(None,
                revidmap.lookup_dist_to_origin("bloe"))

    def test_insert_revhistory(self):
        revidmap = RevidMap()
        revidmap.insert_revision_history(["bla", "bloe", "blo"])
        self.assertIs(1,
                revidmap.lookup_dist_to_origin("bla"))
        self.assertIs(2,
                revidmap.lookup_dist_to_origin("bloe"))
        self.assertIs(3,
                revidmap.lookup_dist_to_origin("blo"))

    def test_lookup_dist_notfound(self):
        revidmap = RevidMap()
        self.assertIs(None,
                revidmap.lookup_dist_to_origin("blabla"))

    def test_lookup_branch_nonexistant(self):
        revidmap = RevidMap()
        self.assertIs(None,
                revidmap.lookup_branch_revnum(42, "mypath", "foo"))

    def test_lookup_branch_incomplete(self):
        revidmap = RevidMap()
        revidmap.insert_revid("bla", "mypath", 200, 42, "brainslug")
        self.assertEquals(None, 
                revidmap.lookup_branch_revnum(42, "mypath", "brainslug"))


class TestParseRevisionId(TestCase):
    def test_parse_revision_id_unknown(self):
        self.assertRaises(InvalidRevisionId, 
                lambda: parse_svn_revision_id("bla"))

    def test_parse_revision_id(self):
        self.assertEquals(("myuuid", "bla", 5, "foobar"), 
            parse_svn_revision_id(
                generate_svn_revision_id("myuuid", 5, "bla", "foobar")))


class RevisionIdMappingTest(TestCase):
    def test_generate_revid(self):
        self.assertEqual("svn-v%d-undefined:myuuid:branch:5" % MAPPING_VERSION, 
                         generate_svn_revision_id("myuuid", 5, "branch", "undefined"))

    def test_generate_revid_nested(self):
        self.assertEqual("svn-v%d-undefined:myuuid:branch%%2Fpath:5" % MAPPING_VERSION, 
                  generate_svn_revision_id("myuuid", 5, "branch/path", "undefined"))

    def test_generate_revid_special_char(self):
        self.assertEqual(u"svn-v%d-undefined:myuuid:branch%%2C:5" % MAPPING_VERSION, 
             generate_svn_revision_id("myuuid", 5, u"branch\x2c", "undefined"))

    def test_generate_revid_special_char_ascii(self):
        self.assertEqual("svn-v%d-undefined:myuuid:branch%%2C:5" % MAPPING_VERSION, 
             generate_svn_revision_id("myuuid", 5, "branch\x2c", "undefined"))

    def test_generate_revid_nordic(self):
        self.assertEqual("svn-v%d-undefined:myuuid:branch%%C3%%A6:5" % MAPPING_VERSION, 
             generate_svn_revision_id("myuuid", 5, u"branch\xe6", "undefined"))

    def test_parse_revid_simple(self):
        self.assertEqual(("uuid", "", 4, "undefined"),
                         parse_svn_revision_id(
                             "svn-v%d-undefined:uuid::4" % MAPPING_VERSION))

    def test_parse_revid_nested(self):
        self.assertEqual(("uuid", "bp/data", 4, "undefined"),
                         parse_svn_revision_id(
                     "svn-v%d-undefined:uuid:bp%%2Fdata:4" % MAPPING_VERSION))

    def test_svk_revid_map_root(self):
        self.assertEqual("svn-v%d-undef:auuid::6" % MAPPING_VERSION,
                 svk_feature_to_revision_id("auuid:/:6", "undef"))

    def test_svk_revid_map_nested(self):
        self.assertEqual("svn-v%d-undef:auuid:bp:6" % MAPPING_VERSION,
                         svk_feature_to_revision_id("auuid:/bp:6", "undef"))

    def test_revid_svk_map(self):
        self.assertEqual("auuid:/:6", 
              revision_id_to_svk_feature("svn-v%d-undefined:auuid::6" % MAPPING_VERSION))


