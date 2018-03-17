# Copyright (C) 2010 Jelmer Vernooij <jelmer@samba.org>
# -*- encoding: utf-8 -*-
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


"""Tests for roundtripping text parsing."""


from ....tests import TestCase

from ..roundtrip import (
    CommitSupplement,
    deserialize_fileid_map,
    extract_bzr_metadata,
    generate_roundtripping_metadata,
    inject_bzr_metadata,
    parse_roundtripping_metadata,
    serialize_fileid_map,
    )


class RoundtripTests(TestCase):

    def test_revid(self):
        md = parse_roundtripping_metadata("revision-id: foo\n")
        self.assertEquals("foo", md.revision_id)

    def test_parent_ids(self):
        md = parse_roundtripping_metadata("parent-ids: foo bar\n")
        self.assertEquals(("foo", "bar"), md.explicit_parent_ids)

    def test_properties(self):
        md = parse_roundtripping_metadata("property-foop: blar\n")
        self.assertEquals({"foop": "blar"}, md.properties)


class FormatTests(TestCase):

    def test_revid(self):
        metadata = CommitSupplement()
        metadata.revision_id = "bla"
        self.assertEquals("revision-id: bla\n",
            generate_roundtripping_metadata(metadata, "utf-8"))

    def test_parent_ids(self):
        metadata = CommitSupplement()
        metadata.explicit_parent_ids = ("foo", "bar")
        self.assertEquals("parent-ids: foo bar\n",
            generate_roundtripping_metadata(metadata, "utf-8"))

    def test_properties(self):
        metadata = CommitSupplement()
        metadata.properties = {"foo": "bar"}
        self.assertEquals("property-foo: bar\n",
            generate_roundtripping_metadata(metadata, "utf-8"))

    def test_empty(self):
        metadata = CommitSupplement()
        self.assertEquals("",
            generate_roundtripping_metadata(metadata, "utf-8"))


class ExtractMetadataTests(TestCase):

    def test_roundtrip(self):
        (msg, metadata) = extract_bzr_metadata("""Foo
--BZR--
revision-id: foo
""")
        self.assertEquals("Foo", msg)
        self.assertEquals("foo", metadata.revision_id)


class GenerateMetadataTests(TestCase):

    def test_roundtrip(self):
        metadata = CommitSupplement()
        metadata.revision_id = "myrevid"
        msg = inject_bzr_metadata("Foo", metadata, "utf-8")
        self.assertEquals("""Foo
--BZR--
revision-id: myrevid
""", msg)

    def test_no_metadata(self):
        metadata = CommitSupplement()
        msg = inject_bzr_metadata("Foo", metadata, "utf-8")
        self.assertEquals("Foo", msg)


class FileIdRoundTripTests(TestCase):

    def test_deserialize(self):
        self.assertEquals({"bar/bla": "fid"},
            deserialize_fileid_map("bar/bla\0fid\n"))

    def test_serialize(self):
        self.assertEquals(["bar/bla\0fid\n"],
            serialize_fileid_map({"bar/bla": "fid"}))

