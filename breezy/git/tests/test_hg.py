# Copyright (C) 2018 Jelmer Vernooij <jelmer@jelmer.uk>
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

"""Tests for hg-git metadata parsing and formatting."""

from ...revision import Revision
from ...tests import TestCase
from ..hg import extract_hg_metadata, format_hg_metadata
from ..mapping import BzrGitMappingExperimental


class ExtractHgMetadataTests(TestCase):
    def test_no_trailer(self):
        self.assertEqual(
            (b"just a message", {}, None, {}),
            extract_hg_metadata(b"just a message"),
        )

    def test_branch(self):
        self.assertEqual(
            (b"msg", {}, "featurex", {}),
            extract_hg_metadata(b"msg\n--HG--\nbranch : featurex\n"),
        )

    def test_rename(self):
        self.assertEqual(
            (b"msg", {b"b": b"a"}, None, {}),
            extract_hg_metadata(b"msg\n--HG--\nrename : a => b\n"),
        )

    def test_extra(self):
        self.assertEqual(
            (b"msg", {}, None, {"k": b"hello world"}),
            extract_hg_metadata(b"msg\n--HG--\nextra : k : hello%20world\n"),
        )

    def test_empty_lines_skipped(self):
        self.assertEqual(
            (b"m", {}, "x", {}),
            extract_hg_metadata(b"m\n--HG--\n\nbranch : x\n\n"),
        )

    def test_unknown_command(self):
        self.assertRaises(KeyError, extract_hg_metadata, b"m\n--HG--\nbogus : x\n")


class FormatHgMetadataTests(TestCase):
    def test_empty(self):
        self.assertEqual(b"", format_hg_metadata([], "default", {}))

    def test_branch(self):
        self.assertEqual(
            b"\n--HG--\nbranch : featurex\n",
            format_hg_metadata([], "featurex", {}),
        )

    def test_rename(self):
        self.assertEqual(
            b"\n--HG--\nrename : a => b\n",
            format_hg_metadata([(b"a", b"b")], "default", {}),
        )

    def test_extra(self):
        self.assertEqual(
            b"\n--HG--\nextra : k : hello%20world\n",
            format_hg_metadata([], "default", {"k": b"hello world"}),
        )

    def test_extra_reserved_keys_skipped(self):
        self.assertEqual(
            b"",
            format_hg_metadata([], "default", {"branch": b"x", "message": b"y"}),
        )


class RoundtripTests(TestCase):
    def test_roundtrip(self):
        tail = format_hg_metadata([(b"old", b"new")], "featurex", {"k": b"v w"})
        (message, renames, branch, extra) = extract_hg_metadata(b"msg" + tail)
        self.assertEqual(b"msg", message)
        self.assertEqual({b"new": b"old"}, renames)
        self.assertEqual("featurex", branch)
        self.assertEqual({"k": b"v w"}, extra)


class MappingRoundtripTests(TestCase):
    """Round-trip hg-git metadata through the experimental mapping."""

    def test_roundtrip(self):
        mapping = BzrGitMappingExperimental()
        message = (
            b"the message\n--HG--\nbranch : feature\n"
            b"rename : old.txt => new.txt\nextra : mykey : hello%20world\n"
        )
        properties = {}
        stripped = mapping._extract_hg_metadata(properties, message)
        self.assertEqual(b"the message", stripped)
        self.assertEqual("feature", properties["hg:extra:branch"])

        rev = Revision(b"revid", properties=dict(properties))
        rev.message = "the message"
        tail = mapping._generate_hg_message_tail(rev)

        reextracted = {}
        mapping._extract_hg_metadata(reextracted, b"the message" + tail)
        self.assertEqual(properties, reextracted)
