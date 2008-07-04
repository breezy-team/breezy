# -*- coding: utf-8 -*-

# Copyright (C) 2005-2008 Jelmer Vernooij <jelmer@samba.org>
 
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

import sha

from bzrlib.errors import InvalidRevisionId
from bzrlib.tests import TestCase, adapt_tests, TestNotApplicable
from bzrlib.revision import Revision
from bzrlib.trace import mutter

from bzrlib.plugins.svn.errors import InvalidPropertyValue
from bzrlib.plugins.svn.mapping import (generate_revision_metadata, parse_revision_metadata, 
                     parse_revid_property, parse_merge_property, 
                     BzrSvnMappingv1, BzrSvnMappingv2, 
                     BzrSvnMappingv4, parse_revision_id)
from bzrlib.plugins.svn.mapping3 import (BzrSvnMappingv3FileProps, BzrSvnMappingv3RevProps, 
                      BzrSvnMappingv3Hybrid)
from bzrlib.plugins.svn.mapping3.scheme import NoBranchingScheme


class MetadataMarshallerTests(TestCase):
    def test_generate_revision_metadata_none(self):
        self.assertEquals("", 
                generate_revision_metadata(None, None, None, None))

    def test_generate_revision_metadata_committer(self):
        self.assertEquals("committer: bla\n", 
                generate_revision_metadata(None, None, "bla", None))

    def test_generate_revision_metadata_timestamp(self):
        self.assertEquals("timestamp: 2005-06-30 17:38:52.350850105 +0000\n", 
                generate_revision_metadata(1120153132.350850105, 0, 
                    None, None))
            
    def test_generate_revision_metadata_properties(self):
        self.assertEquals("properties: \n" + 
                "\tpropbla: bloe\n" +
                "\tpropfoo: bla\n",
                generate_revision_metadata(None, None,
                    None, {"propbla": "bloe", "propfoo": "bla"}))

    def test_parse_revision_metadata_empty(self):
        parse_revision_metadata("", None)

    def test_parse_revision_metadata_committer(self):
        rev = Revision('someid')
        parse_revision_metadata("committer: somebody\n", rev)
        self.assertEquals("somebody", rev.committer)

    def test_parse_revision_metadata_timestamp(self):
        rev = Revision('someid')
        parse_revision_metadata("timestamp: 2005-06-30 12:38:52.350850105 -0500\n", rev)
        self.assertEquals(1120153132.3508501, rev.timestamp)
        self.assertEquals(-18000, rev.timezone)

    def test_parse_revision_metadata_timestamp_day(self):
        rev = Revision('someid')
        parse_revision_metadata("timestamp: Thu 2005-06-30 12:38:52.350850105 -0500\n", rev)
        self.assertEquals(1120153132.3508501, rev.timestamp)
        self.assertEquals(-18000, rev.timezone)

    def test_parse_revision_metadata_properties(self):
        rev = Revision('someid')
        parse_revision_metadata("properties: \n" + 
                                "\tfoo: bar\n" + 
                                "\tha: ha\n", rev)
        self.assertEquals({"foo": "bar", "ha": "ha"}, rev.properties)

    def test_parse_revision_metadata_no_colon(self):
        rev = Revision('someid')
        self.assertRaises(InvalidPropertyValue, 
                lambda: parse_revision_metadata("bla", rev))

    def test_parse_revision_metadata_specialchar(self):
        rev = Revision('someid')
        parse_revision_metadata("committer: Adeodato Simó <dato@net.com.org.es>", rev)
        self.assertEquals(u"Adeodato Simó <dato@net.com.org.es>", rev.committer)

    def test_parse_revision_metadata_invalid_name(self):
        rev = Revision('someid')
        self.assertRaises(InvalidPropertyValue, 
                lambda: parse_revision_metadata("bla: b", rev))

    def test_parse_revid_property(self):
        self.assertEquals((1, "bloe"), parse_revid_property("1 bloe"))

    def test_parse_revid_property_space(self):
        self.assertEquals((42, "bloe bla"), parse_revid_property("42 bloe bla"))

    def test_parse_revid_property_invalid(self):
        self.assertRaises(InvalidPropertyValue, 
                lambda: parse_revid_property("blabla"))

    def test_parse_revid_property_empty_revid(self):
        self.assertRaises(InvalidPropertyValue, 
                lambda: parse_revid_property("2 "))

    def test_parse_revid_property_newline(self):
        self.assertRaises(InvalidPropertyValue, 
                lambda: parse_revid_property("foo\nbar"))


class ParseMergePropertyTestCase(TestCase):
    def test_parse_merge_space(self):
        self.assertEqual((), parse_merge_property("bla bla"))

    def test_parse_merge_empty(self):
        self.assertEqual((), parse_merge_property(""))

    def test_parse_merge_simple(self):
        self.assertEqual(("bla", "bloe"), parse_merge_property("bla\tbloe"))


class MappingTestAdapter(object):
    def test_roundtrip_revision(self):
        revid = self.mapping.generate_revision_id("myuuid", 42, "path")
        (uuid, path, revnum, mapping) = self.mapping.parse_revision_id(revid)
        self.assertEquals(uuid, "myuuid")
        self.assertEquals(revnum, 42)
        self.assertEquals(path, "path")
        self.assertEquals(mapping, self.mapping)

    def test_fileid_map(self):
        if not self.mapping.supports_roundtripping():
            raise TestNotApplicable
        revprops = {}
        fileprops = {}
        fileids = {"": "some-id", "bla/blie": "other-id"}
        self.mapping.export_fileid_map(fileids, revprops, fileprops)
        revprops["svn:date"] = "2008-11-03T09:33:00.716938Z"
        self.assertEquals(fileids, 
                self.mapping.import_fileid_map(revprops, fileprops))

    def test_message(self):
        if not self.mapping.supports_roundtripping():
            raise TestNotApplicable
        (revprops, fileprops) = self.mapping.export_revision("branchp", 432432432.0, 0, "somebody", 
                                     {"arevprop": "val"}, "arevid", 4, ["merge1"], dict())
        revprops["svn:date"] = "2008-11-03T09:33:00.716938Z"
        try:
            self.mapping.export_message("My Commit message", revprops, fileprops)
        except NotImplementedError:
            raise TestNotApplicable
        targetrev = Revision(None)
        self.mapping.import_revision(revprops, fileprops, "someuuid", "somebp", 4, targetrev)
        self.assertEquals("My Commit message", targetrev.message)

    def test_revision(self):
        if not self.mapping.supports_roundtripping():
            raise TestNotApplicable
        (revprops, fileprops) = self.mapping.export_revision("branchp", 432432432.0, 0, "somebody", 
                                     {"arevprop": "val" }, "arevid", 4, ["merge1"], dict())
        targetrev = Revision(None)
        revprops["svn:date"] = "2008-11-03T09:33:00.716938Z"
        self.mapping.import_revision(revprops, fileprops, "someuuid", "somebp", 4, targetrev)
        self.assertEquals(targetrev.committer, "somebody")
        self.assertEquals(targetrev.properties, {"arevprop": "val"})
        self.assertEquals(targetrev.timestamp, 432432432.0)
        self.assertEquals(targetrev.timezone, 0)

    def test_revision_id(self):
        if not self.mapping.supports_roundtripping():
            raise TestNotApplicable
        (revprops, fileprops) = self.mapping.export_revision("branchp", 432432432.0, 0, "somebody", {}, "arevid", 4, ["merge1"], dict())
        self.assertEquals((4, "arevid"), self.mapping.get_revision_id("branchp", revprops, fileprops))
    
    def test_revision_id_none(self):
        if not self.mapping.supports_roundtripping():
            raise TestNotApplicable
        self.assertEquals((None, None), self.mapping.get_revision_id("bp", {}, dict()))

    def test_parse_revision_id_unknown(self):
        self.assertRaises(InvalidRevisionId, 
                lambda: self.mapping.parse_revision_id("bla"))

    def test_parse_revision_id(self):
        self.assertEquals(("myuuid", "bla", 5, self.mapping), 
            self.mapping.parse_revision_id(
                self.mapping.generate_revision_id("myuuid", 5, "bla")))


class Mappingv1Tests(MappingTestAdapter,TestCase):
    def setUp(self):
        self.mapping = BzrSvnMappingv1()


class Mappingv2Tests(MappingTestAdapter,TestCase):
    def setUp(self):
        self.mapping = BzrSvnMappingv2()


def sha1(text):
    return sha.new(text).hexdigest()


class Mappingv3FilePropTests(MappingTestAdapter,TestCase):
    def setUp(self):
        self.mapping = BzrSvnMappingv3FileProps(NoBranchingScheme())

    def test_generate_revid(self):
        self.assertEqual("svn-v3-undefined:myuuid:branch:5", 
                         BzrSvnMappingv3FileProps._generate_revision_id("myuuid", 5, "branch", "undefined"))

    def test_generate_revid_nested(self):
        self.assertEqual("svn-v3-undefined:myuuid:branch%2Fpath:5", 
                  BzrSvnMappingv3FileProps._generate_revision_id("myuuid", 5, "branch/path", "undefined"))

    def test_generate_revid_special_char(self):
        self.assertEqual("svn-v3-undefined:myuuid:branch%2C:5", 
             BzrSvnMappingv3FileProps._generate_revision_id("myuuid", 5, "branch\x2c", "undefined"))

    def test_generate_revid_nordic(self):
        self.assertEqual("svn-v3-undefined:myuuid:branch%C3%A6:5", 
             BzrSvnMappingv3FileProps._generate_revision_id("myuuid", 5, u"branch\xe6".encode("utf-8"), "undefined"))

    def test_parse_revid_simple(self):
        self.assertEqual(("uuid", "", 4, "undefined"),
                         BzrSvnMappingv3FileProps._parse_revision_id(
                             "svn-v3-undefined:uuid::4"))

    def test_parse_revid_nested(self):
        self.assertEqual(("uuid", "bp/data", 4, "undefined"),
                         BzrSvnMappingv3FileProps._parse_revision_id(
                     "svn-v3-undefined:uuid:bp%2Fdata:4"))

    def test_generate_file_id_root(self):
        self.assertEqual("2@uuid:bp:", self.mapping.generate_file_id("uuid", 2, "bp", u""))

    def test_generate_file_id_path(self):
        self.assertEqual("2@uuid:bp:mypath", 
                self.mapping.generate_file_id("uuid", 2, "bp", u"mypath"))

    def test_generate_file_id_long(self):
        dir = "this/is/a" + ("/very"*40) + "/long/path/"
        self.assertEqual("2@uuid:bp;" + sha1(dir+"filename"), 
                self.mapping.generate_file_id("uuid", 2, "bp", dir+u"filename"))

    def test_generate_file_id_long_nordic(self):
        dir = "this/is/a" + ("/very"*40) + "/long/path/"
        self.assertEqual("2@uuid:bp;" + sha1((dir+u"filename\x2c\x8a").encode('utf-8')), 
                self.mapping.generate_file_id("uuid", 2, "bp", dir+u"filename\x2c\x8a"))

    def test_generate_file_id_special_char(self):
        self.assertEqual("2@uuid:bp:mypath%2C%C2%8A",
                         self.mapping.generate_file_id("uuid", 2, "bp", u"mypath\x2c\x8a"))

    def test_generate_svn_file_id(self):
        self.assertEqual("2@uuid:bp:path", 
                self.mapping.generate_file_id("uuid", 2, "bp", u"path"))

    def test_generate_svn_file_id_nordic(self):
        self.assertEqual("2@uuid:bp:%C3%A6%C3%B8%C3%A5", 
                self.mapping.generate_file_id("uuid", 2, "bp", u"\xe6\xf8\xe5"))

    def test_generate_svn_file_id_nordic_branch(self):
        self.assertEqual("2@uuid:%C3%A6:%C3%A6%C3%B8%C3%A5", 
                self.mapping.generate_file_id("uuid", 2, u"\xe6".encode('utf-8'), u"\xe6\xf8\xe5"))


class Mappingv3RevPropTests(MappingTestAdapter,TestCase):
    def setUp(self):
        self.mapping = BzrSvnMappingv3RevProps(NoBranchingScheme())


class Mappingv3HybridTests(MappingTestAdapter,TestCase):
    def setUp(self):
        self.mapping = BzrSvnMappingv3Hybrid(NoBranchingScheme())


class Mappingv4TestAdapter(MappingTestAdapter,TestCase):
    def setUp(self):
        self.mapping = BzrSvnMappingv4()


class ParseRevisionIdTests(object):
    def test_current(self):
        self.assertEqual(("uuid", "trunk", 1, BzrSvnMappingv3FileProps(TrunkBranchingScheme())), 
                parse_revision_id("svn-v3-trunk0:uuid:trunk:1"))

    def test_current_undefined(self):
        self.assertEqual(("uuid", "trunk", 1, BzrSvnMappingv3FileProps(TrunkBranchingScheme())), 
                parse_revision_id("svn-v3-undefined:uuid:trunk:1"))

    def test_legacy2(self):
        self.assertEqual(("uuid", "trunk", 1, BzrSvnMappingv2()), 
                         parse_revision_id("svn-v2:1@uuid-trunk"))

    def test_legacy(self):
        self.assertEqual(("uuid", "trunk", 1, BzrSvnMappingv1()), 
                         parse_revision_id("svn-v1:1@uuid-trunk"))

    def test_except(self):
        self.assertRaises(InvalidRevisionId, 
                         parse_revision_id, "svn-v0:1@uuid-trunk")

    def test_except_nonsvn(self):
        self.assertRaises(InvalidRevisionId, 
                         parse_revision_id, "blah")
