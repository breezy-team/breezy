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

from breezy.revision import Revision
from breezy.tests import TestCase

from .._bzr_rs import revision_bencode_serializer

_working_revision_bencode1 = (
    b"l"
    b"l6:formati10ee"
    b"l9:committer54:Canonical.com Patch Queue Manager <pqm@pqm.ubuntu.com>e"
    b"l8:timezonei3600ee"
    b"l10:propertiesd11:branch-nick6:+trunkee"
    b"l9:timestamp14:1242300770.844e"
    b"l11:revision-id50:pqm@pqm.ubuntu.com-20090514113250-jntkkpminfn3e0tze"
    b"l10:parent-ids"
    b"l"
    b"50:pqm@pqm.ubuntu.com-20090514104039-kggemn7lrretzpvc"
    b"48:jelmer@samba.org-20090510012654-jp9ufxquekaokbeo"
    b"ee"
    b"l14:inventory-sha140:4a2c7fb50e077699242cf6eb16a61779c7b680a7e"
    b"l7:message35:(Jelmer) Move dpush to InterBranch.e"
    b"e"
)

_working_revision_bencode1_no_timezone = (
    b"l"
    b"l6:formati10ee"
    b"l9:committer54:Canonical.com Patch Queue Manager <pqm@pqm.ubuntu.com>e"
    b"l9:timestamp14:1242300770.844e"
    b"l10:propertiesd11:branch-nick6:+trunkee"
    b"l11:revision-id50:pqm@pqm.ubuntu.com-20090514113250-jntkkpminfn3e0tze"
    b"l10:parent-ids"
    b"l"
    b"50:pqm@pqm.ubuntu.com-20090514104039-kggemn7lrretzpvc"
    b"48:jelmer@samba.org-20090510012654-jp9ufxquekaokbeo"
    b"ee"
    b"l14:inventory-sha140:4a2c7fb50e077699242cf6eb16a61779c7b680a7e"
    b"l7:message35:(Jelmer) Move dpush to InterBranch.e"
    b"e"
)


class TestBEncodeSerializer1(TestCase):
    """Test BEncode serialization."""

    def test_unpack_revision(self):
        """Test unpacking a revision."""
        rev = revision_bencode_serializer.read_revision_from_string(
            _working_revision_bencode1
        )
        self.assertEqual(
            rev.committer, "Canonical.com Patch Queue Manager <pqm@pqm.ubuntu.com>"
        )
        self.assertEqual(
            rev.inventory_sha1, b"4a2c7fb50e077699242cf6eb16a61779c7b680a7"
        )
        self.assertEqual(
            [
                b"pqm@pqm.ubuntu.com-20090514104039-kggemn7lrretzpvc",
                b"jelmer@samba.org-20090510012654-jp9ufxquekaokbeo",
            ],
            rev.parent_ids,
        )
        self.assertEqual("(Jelmer) Move dpush to InterBranch.", rev.message)
        self.assertEqual(
            b"pqm@pqm.ubuntu.com-20090514113250-jntkkpminfn3e0tz", rev.revision_id
        )
        self.assertEqual({"branch-nick": "+trunk"}, rev.properties)
        self.assertEqual(3600, rev.timezone)

    def test_written_form_matches(self):
        rev = revision_bencode_serializer.read_revision_from_string(
            _working_revision_bencode1
        )
        as_str = revision_bencode_serializer.write_revision_to_string(rev)
        self.assertEqualDiff(_working_revision_bencode1, as_str)

    def test_unpack_revision_no_timezone(self):
        rev = revision_bencode_serializer.read_revision_from_string(
            _working_revision_bencode1_no_timezone
        )
        self.assertEqual(None, rev.timezone)

    def assertRoundTrips(self, serializer, orig_rev):
        lines = serializer.write_revision_to_lines(orig_rev)
        new_rev = serializer.read_revision_from_string(b"".join(lines))
        self.assertEqual(orig_rev, new_rev)

    def test_roundtrips_non_ascii(self):
        rev = Revision(
            b"revid1",
            message="\n\xe5me",
            committer="Erik B\xe5gfors",
            timestamp=1242385452,
            inventory_sha1=b"4a2c7fb50e077699242cf6eb16a61779c7b680a7",
            parent_ids=[],
            properties={},
            timezone=3600,
        )
        self.assertRoundTrips(revision_bencode_serializer, rev)

    def test_roundtrips_xml_invalid_chars(self):
        rev = Revision(
            b"revid1",
            properties={},
            parent_ids=[],
            message="\t\ue000",
            committer="Erik B\xe5gfors",
            timestamp=1242385452,
            timezone=3600,
            inventory_sha1=b"4a2c7fb50e077699242cf6eb16a61779c7b680a7",
        )
        self.assertRoundTrips(revision_bencode_serializer, rev)
