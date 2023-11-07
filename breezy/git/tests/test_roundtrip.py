# Copyright (C) 2010-2018 Jelmer Vernooij <jelmer@jelmer.uk>
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

from ...tests import TestCase
from ..roundtrip import (
    CommitSupplement,
    extract_bzr_metadata,
    generate_roundtripping_metadata,
    inject_bzr_metadata,
    parse_roundtripping_metadata,
)


class RoundtripTests(TestCase):
    def test_revid(self):
        md = parse_roundtripping_metadata(b"revision-id: foo\n")
        self.assertEqual(b"foo", md.revision_id)

    def test_parent_ids(self):
        md = parse_roundtripping_metadata(b"parent-ids: foo bar\n")
        self.assertEqual((b"foo", b"bar"), md.explicit_parent_ids)

    def test_properties(self):
        md = parse_roundtripping_metadata(b"property-foop: blar\n")
        self.assertEqual({b"foop": b"blar"}, md.properties)


class FormatTests(TestCase):
    def test_revid(self):
        metadata = CommitSupplement()
        metadata.revision_id = b"bla"
        self.assertEqual(
            b"revision-id: bla\n", generate_roundtripping_metadata(metadata, "utf-8")
        )

    def test_parent_ids(self):
        metadata = CommitSupplement()
        metadata.explicit_parent_ids = (b"foo", b"bar")
        self.assertEqual(
            b"parent-ids: foo bar\n", generate_roundtripping_metadata(metadata, "utf-8")
        )

    def test_properties(self):
        metadata = CommitSupplement()
        metadata.properties = {b"foo": b"bar"}
        self.assertEqual(
            b"property-foo: bar\n", generate_roundtripping_metadata(metadata, "utf-8")
        )

    def test_empty(self):
        metadata = CommitSupplement()
        self.assertEqual(b"", generate_roundtripping_metadata(metadata, "utf-8"))


class ExtractMetadataTests(TestCase):
    def test_roundtrip(self):
        (msg, metadata) = extract_bzr_metadata(
            b"""Foo
--BZR--
revision-id: foo
"""
        )
        self.assertEqual(b"Foo", msg)
        self.assertEqual(b"foo", metadata.revision_id)


class GenerateMetadataTests(TestCase):
    def test_roundtrip(self):
        metadata = CommitSupplement()
        metadata.revision_id = b"myrevid"
        msg = inject_bzr_metadata(b"Foo", metadata, "utf-8")
        self.assertEqual(
            b"""Foo
--BZR--
revision-id: myrevid
""",
            msg,
        )

    def test_no_metadata(self):
        metadata = CommitSupplement()
        msg = inject_bzr_metadata(b"Foo", metadata, "utf-8")
        self.assertEqual(b"Foo", msg)
