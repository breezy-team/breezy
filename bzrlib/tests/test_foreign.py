# Copyright (C) 2008 Canonical Ltd
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


"""Tests for foreign VCS utility code."""

from bzrlib import errors, foreign
from bzrlib.bzrdir import BzrDirFormat, BzrDirMeta1
from bzrlib.inventory import Inventory
from bzrlib.revision import Revision
from bzrlib.tests import TestCase, TestCaseWithTransport

# This is the dummy foreign revision control system, used 
# mainly here in the testsuite to test the foreign VCS infrastructure.
# It is basically standard Bazaar with some minor modifications to 
# make it "foreign". 
# 
# It has the following differences to "regular" Bazaar:
# - The revision ids are tuples, not strings.


class DummyForeignVcsMapping(foreign.VcsMapping):
    """A simple mapping for the dummy Foreign VCS, for use with testing."""

    def __eq__(self, other):
        return type(self) == type(other)

    def revision_id_bzr_to_foreign(self, bzr_revid):
        return tuple(bzr_revid[len("dummy-v1:"):].split("-")), self

    def revision_id_foreign_to_bzr(self, foreign_revid):
        return "dummy-v1:%s-%s-%s" % foreign_revid


class DummyForeignVcsMappingRegistry(foreign.VcsMappingRegistry):

    def revision_id_bzr_to_foreign(self, revid):
        if not revid.startswith("dummy-"):
            raise errors.InvalidRevisionId(revid, None)
        mapping_version = revid[len("dummy-"):len("dummy-vx")]
        mapping = self.get(mapping_version)
        return mapping.revision_id_bzr_to_foreign(revid)


class DummyForeignVcs(foreign.ForeignVcs):
    """A dummy Foreign VCS, for use with testing.
    
    It has revision ids that are a tuple with three strings.
    """

    def __init__(self):
        self.mapping_registry = DummyForeignVcsMappingRegistry()
        self.mapping_registry.register("v1", DummyForeignVcsMapping(self), 
                                       "Version 1")

    def show_foreign_revid(self, foreign_revid):
        return { "dummy ding": "%s/%s\\%s" % foreign_revid }



class DummyForeignVcsBzrDirFormat(BzrDirMeta1):
    """BzrDirFormat for the dummy foreign VCS."""

    def get_format_string(self):
        return "A Dummy VCS Dir"

    def get_description_string(self):
        return "A Dummy VCS Dir"


class ForeignVcsRegistryTests(TestCase):
    """Tests for the ForeignVcsRegistry class."""

    def test_parse_revision_id_no_dash(self):       
        reg = foreign.ForeignVcsRegistry()
        self.assertRaises(errors.InvalidRevisionId, 
                          reg.parse_revision_id, "invalid")
        
    def test_parse_revision_id_unknown_mapping(self):       
        reg = foreign.ForeignVcsRegistry()
        self.assertRaises(errors.InvalidRevisionId, 
                          reg.parse_revision_id, "unknown-foreignrevid")

    def test_parse_revision_id(self):
        reg = foreign.ForeignVcsRegistry()
        vcs = DummyForeignVcs()
        reg.register("dummy", vcs, "Dummy VCS")
        self.assertEquals((("some", "foreign", "revid"), DummyForeignVcsMapping(vcs)),
                          reg.parse_revision_id("dummy-v1:some-foreign-revid"))


class ForeignRevisionTests(TestCase):
    """Tests for the ForeignRevision class."""

    def test_create(self):
        mapp = DummyForeignVcsMapping(DummyForeignVcs())
        rev = foreign.ForeignRevision(("a", "foreign", "revid"), 
                                      mapp, "roundtripped-revid")
        self.assertEquals("", rev.inventory_sha1)
        self.assertEquals(("a", "foreign", "revid"), rev.foreign_revid)
        self.assertEquals(mapp, rev.mapping)


class ShowForeignPropertiesTests(TestCase):
    """Tests for the show_foreign_properties() function."""

    def setUp(self):
        super(ShowForeignPropertiesTests, self).setUp()
        self.vcs = DummyForeignVcs()
        foreign.foreign_vcs_registry.register("dummy", 
            self.vcs, "Dummy VCS")

    def tearDown(self):
        super(ShowForeignPropertiesTests, self).tearDown()
        foreign.foreign_vcs_registry.remove("dummy")

    def test_show_non_foreign(self):
        """Test use with a native (non-foreign) bzr revision."""
        self.assertEquals({}, foreign.show_foreign_properties(Revision("arevid")))

    def test_show_imported(self):
        rev = Revision("dummy-v1:my-foreign-revid")
        self.assertEquals({ "dummy ding": "my/foreign\\revid" },
                          foreign.show_foreign_properties(rev))

    def test_show_direct(self):
        rev = foreign.ForeignRevision(("some", "foreign", "revid"), 
                                      DummyForeignVcsMapping(self.vcs), 
                                      "roundtrip-revid")
        self.assertEquals({ "dummy ding": "some/foreign\\revid" },
                          foreign.show_foreign_properties(rev))


class WorkingTreeFileUpdateTests(TestCaseWithTransport):
    """Tests for determine_fileid_renames()."""

    def test_det_renames_same(self):
        a = Inventory()
        a.add_path("bla", "directory", "bla-a")
        b = Inventory()
        b.add_path("bla", "directory", "bla-a")
        self.assertEquals( {}, foreign.determine_fileid_renames(a, b))

    def test_det_renames_simple(self):
        a = Inventory()
        a.add_path("bla", "directory", "bla-a")
        b = Inventory()
        b.add_path("bla", "directory", "bla-b")
        self.assertEquals(
                {"bla": ("bla-a", "bla-b")},
                foreign.determine_fileid_renames(a, b))

    def test_det_renames_root(self):
        a = Inventory()
        a.add_path("", "directory", "bla-a")
        b = Inventory()
        b.add_path("", "directory", "bla-b")
        self.assertEquals(
                {"": ("bla-a", "bla-b")},
                foreign.determine_fileid_renames(a, b))

    def test_update_workinginv(self):
        a = Inventory()
        a.add_path("bla", "directory", "bla-a")
        b = Inventory()
        b.add_path("bla", "directory", "bla-b")
        wt = self.make_branch_and_tree('br1')
        self.build_tree_contents([('br1/bla', 'original contents\n')])
        wt.add('bla', 'bla-a')
        foreign.update_workinginv_fileids(wt, a, b)
        wt.lock_read()
        try:
            self.assertEquals(["TREE_ROOT", "bla-b"], list(wt.inventory))
        finally:
            wt.unlock()
