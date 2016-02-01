# Copyright (C) 2009, 2010, 2011, 2016 Canonical Ltd
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

from bzrlib.chk_serializer import (
    chk_bencode_serializer,
    )
from bzrlib.revision import (
    Revision,
    )
from bzrlib.tests import TestCase

_working_revision_bencode1 = ('l'
    'l6:formati10ee'
    'l9:committer54:Canonical.com Patch Queue Manager <pqm@pqm.ubuntu.com>e'
    'l8:timezonei3600ee'
    'l10:propertiesd11:branch-nick6:+trunkee'
    'l9:timestamp14:1242300770.844e'
    'l11:revision-id50:pqm@pqm.ubuntu.com-20090514113250-jntkkpminfn3e0tze'
    'l10:parent-ids'
        'l'
        '50:pqm@pqm.ubuntu.com-20090514104039-kggemn7lrretzpvc'
        '48:jelmer@samba.org-20090510012654-jp9ufxquekaokbeo'
        'ee'
    'l14:inventory-sha140:4a2c7fb50e077699242cf6eb16a61779c7b680a7e'
    'l7:message35:(Jelmer) Move dpush to InterBranch.e'
    'e')

_working_revision_bencode1_no_timezone = ('l'
    'l6:formati10ee'
    'l9:committer54:Canonical.com Patch Queue Manager <pqm@pqm.ubuntu.com>e'
    'l9:timestamp14:1242300770.844e'
    'l10:propertiesd11:branch-nick6:+trunkee'
    'l11:revision-id50:pqm@pqm.ubuntu.com-20090514113250-jntkkpminfn3e0tze'
    'l10:parent-ids'
        'l'
        '50:pqm@pqm.ubuntu.com-20090514104039-kggemn7lrretzpvc'
        '48:jelmer@samba.org-20090510012654-jp9ufxquekaokbeo'
        'ee'
    'l14:inventory-sha140:4a2c7fb50e077699242cf6eb16a61779c7b680a7e'
    'l7:message35:(Jelmer) Move dpush to InterBranch.e'
    'e')


class TestBEncodeSerializer1(TestCase):
    """Test BEncode serialization"""

    def test_unpack_revision(self):
        """Test unpacking a revision"""
        rev = chk_bencode_serializer.read_revision_from_string(
                _working_revision_bencode1)
        self.assertEqual(rev.committer,
           "Canonical.com Patch Queue Manager <pqm@pqm.ubuntu.com>")
        self.assertEqual(rev.inventory_sha1,
           "4a2c7fb50e077699242cf6eb16a61779c7b680a7")
        self.assertEqual(["pqm@pqm.ubuntu.com-20090514104039-kggemn7lrretzpvc",
            "jelmer@samba.org-20090510012654-jp9ufxquekaokbeo"],
            rev.parent_ids)
        self.assertEqual("(Jelmer) Move dpush to InterBranch.", rev.message)
        self.assertEqual("pqm@pqm.ubuntu.com-20090514113250-jntkkpminfn3e0tz",
           rev.revision_id)
        self.assertEqual({"branch-nick": u"+trunk"}, rev.properties)
        self.assertEqual(3600, rev.timezone)

    def test_written_form_matches(self):
        rev = chk_bencode_serializer.read_revision_from_string(
                _working_revision_bencode1)
        as_str = chk_bencode_serializer.write_revision_to_string(rev)
        self.assertEqualDiff(_working_revision_bencode1, as_str)

    def test_unpack_revision_no_timezone(self):
        rev = chk_bencode_serializer.read_revision_from_string(
            _working_revision_bencode1_no_timezone)
        self.assertEqual(None, rev.timezone)

    def assertRoundTrips(self, serializer, orig_rev):
        text = serializer.write_revision_to_string(orig_rev)
        new_rev = serializer.read_revision_from_string(text)
        self.assertEqual(orig_rev, new_rev)

    def test_roundtrips_non_ascii(self):
        rev = Revision("revid1")
        rev.message = u"\n\xe5me"
        rev.committer = u'Erik B\xe5gfors'
        rev.timestamp = 1242385452
        rev.inventory_sha1 = "4a2c7fb50e077699242cf6eb16a61779c7b680a7"
        rev.timezone = 3600
        self.assertRoundTrips(chk_bencode_serializer, rev)

    def test_roundtrips_xml_invalid_chars(self):
        rev = Revision("revid1")
        rev.message = "\t\ue000"
        rev.committer = u'Erik B\xe5gfors'
        rev.timestamp = 1242385452
        rev.timezone = 3600
        rev.inventory_sha1 = "4a2c7fb50e077699242cf6eb16a61779c7b680a7"
        self.assertRoundTrips(chk_bencode_serializer, rev)
