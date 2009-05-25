# Copyright (C) 2009 Canonical Ltd
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

from cStringIO import StringIO

from bzrlib import (
    errors,
    revision,
    serializer,
    )
from bzrlib.chk_serializer import (
    chk_bencode_serializer,
    )
from bzrlib.revision import (
    Revision,
    )
from bzrlib.tests import TestCase

_working_revision_bencode1 = """revision-id: pqm@pqm.ubuntu.com-20090514113250-jntkkpminfn3e0tz
timestamp: 1242300770.844
parent-id: pqm@pqm.ubuntu.com-20090514104039-kggemn7lrretzpvc
parent-id: jelmer@samba.org-20090510012654-jp9ufxquekaokbeo
inventory-sha1: 4a2c7fb50e077699242cf6eb16a61779c7b680a7
committer: Canonical.com Patch Queue Manager <pqm@pqm.ubuntu.com>
timezone: 3600
property-branch-nick: +trunk
message: (Jelmer) Move dpush to InterBranch.
"""

_working_revision_bencode1_no_timestamp = """revision-id: pqm@pqm.ubuntu.com-20090514113250-jntkkpminfn3e0tz
timestamp: 1242300770.844
parent-id: pqm@pqm.ubuntu.com-20090514104039-kggemn7lrretzpvc
parent-id: jelmer@samba.org-20090510012654-jp9ufxquekaokbeo
inventory-sha1: 4a2c7fb50e077699242cf6eb16a61779c7b680a7
committer: Canonical.com Patch Queue Manager <pqm@pqm.ubuntu.com>
property-branch-nick: +trunk
message: (Jelmer) Move dpush to InterBranch.
"""

class TestBEncodeSerializer1(TestCase):
    """Test BEncode serialization"""

    def test_unpack_revision(self):
        """Test unpacking a revision"""
        inp = StringIO()
        rev = chk_bencode_serializer.read_revision_from_string(
                _working_revision_bencode1)
        eq = self.assertEqual
        eq(rev.committer,
           "Canonical.com Patch Queue Manager <pqm@pqm.ubuntu.com>")
        eq(rev.inventory_sha1,
           "4a2c7fb50e077699242cf6eb16a61779c7b680a7")
        eq(["pqm@pqm.ubuntu.com-20090514104039-kggemn7lrretzpvc",
            "jelmer@samba.org-20090510012654-jp9ufxquekaokbeo"],
            rev.parent_ids)
        eq("(Jelmer) Move dpush to InterBranch.", rev.message)
        eq("pqm@pqm.ubuntu.com-20090514113250-jntkkpminfn3e0tz", 
           rev.revision_id)
        eq({"branch-nick": u"+trunk"}, rev.properties)
        eq(3600, rev.timezone)

    def test_unpack_revision_no_timestamp(self):
        rev = chk_bencode_serializer.read_revision_from_string(
            _working_revision_bencode1_no_timestamp)
        self.assertEquals(None, rev.timezone)

    def assertRoundTrips(self, serializer, orig_rev):
        text = serializer.write_revision_to_string(orig_rev)
        new_rev = serializer.read_revision_from_string(text)
        self.assertEquals(orig_rev, new_rev)

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
