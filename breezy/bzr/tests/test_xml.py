# Copyright (C) 2005-2011 Canonical Ltd
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

from io import BytesIO

import breezy.bzr.xml5

from ... import fifo_cache
from .. import inventory, serializer, xml6, xml7, xml8
from ..inventory import Inventory
from . import TestCase

_revision_v5 = b"""<revision committer="Martin Pool &lt;mbp@sourcefrog.net&gt;"
    inventory_sha1="e79c31c1deb64c163cf660fdedd476dd579ffd41"
    revision_id="mbp@sourcefrog.net-20050905080035-e0439293f8b6b9f9"
    timestamp="1125907235.212"
    timezone="36000">
<message>- start splitting code for xml (de)serialization away from objects
  preparatory to supporting multiple formats by a single library
</message>
<parents>
<revision_ref revision_id="mbp@sourcefrog.net-20050905063503-43948f59fa127d92"/>
</parents>
</revision>
"""

_revision_v5_utc = b"""\
<revision committer="Martin Pool &lt;mbp@sourcefrog.net&gt;"
    inventory_sha1="e79c31c1deb64c163cf660fdedd476dd579ffd41"
    revision_id="mbp@sourcefrog.net-20050905080035-e0439293f8b6b9f9"
    timestamp="1125907235.212"
    timezone="0">
<message>- start splitting code for xml (de)serialization away from objects
  preparatory to supporting multiple formats by a single library
</message>
<parents>
<revision_ref revision_id="mbp@sourcefrog.net-20050905063503-43948f59fa127d92"/>
</parents>
</revision>
"""

_committed_inv_v5 = b"""<inventory>
<file file_id="bar-20050901064931-73b4b1138abc9cd2"
      name="bar" parent_id="TREE_ROOT"
      revision="mbp@foo-123123"
      text_sha1="A" text_size="1"/>
<directory name="subdir"
           file_id="foo-20050801201819-4139aa4a272f4250"
           parent_id="TREE_ROOT"
           revision="mbp@foo-00"/>
<file executable="yes" file_id="bar-20050824000535-6bc48cfad47ed134"
      name="bar" parent_id="foo-20050801201819-4139aa4a272f4250"
      revision="mbp@foo-00"
      text_sha1="B" text_size="0"/>
</inventory>
"""

_basis_inv_v5 = b"""<inventory revision_id="mbp@sourcefrog.net-20050905063503-43948f59fa127d92">
<file file_id="bar-20050901064931-73b4b1138abc9cd2"
      name="bar" parent_id="TREE_ROOT"
      revision="mbp@foo-123123"/>
<directory name="subdir"
           file_id="foo-20050801201819-4139aa4a272f4250"
           parent_id="TREE_ROOT"
           revision="mbp@foo-00"/>
<file file_id="bar-20050824000535-6bc48cfad47ed134"
      name="bar" parent_id="foo-20050801201819-4139aa4a272f4250"
      revision="mbp@foo-00"/>
</inventory>
"""


# DO NOT REFLOW THIS. Its the exact revision we want.
_expected_rev_v5 = b"""<revision committer="Martin Pool &lt;mbp@sourcefrog.net&gt;" format="5" inventory_sha1="e79c31c1deb64c163cf660fdedd476dd579ffd41" revision_id="mbp@sourcefrog.net-20050905080035-e0439293f8b6b9f9" timestamp="1125907235.212" timezone="36000">
<message>- start splitting code for xml (de)serialization away from objects
  preparatory to supporting multiple formats by a single library
</message>
<parents>
<revision_ref revision_id="mbp@sourcefrog.net-20050905063503-43948f59fa127d92" />
</parents>
</revision>
"""


# DO NOT REFLOW THIS. Its the exact inventory we want.
_expected_inv_v5 = b"""<inventory format="5">
<file file_id="bar-20050901064931-73b4b1138abc9cd2" name="bar" revision="mbp@foo-123123" text_sha1="A" text_size="1" />
<directory file_id="foo-20050801201819-4139aa4a272f4250" name="subdir" revision="mbp@foo-00" />
<file executable="yes" file_id="bar-20050824000535-6bc48cfad47ed134" name="bar" parent_id="foo-20050801201819-4139aa4a272f4250" revision="mbp@foo-00" text_sha1="B" text_size="0" />
</inventory>
"""


_expected_inv_v5_root = b"""<inventory file_id="f&lt;" format="5" revision_id="mother!">
<file file_id="bar-20050901064931-73b4b1138abc9cd2" name="bar" parent_id="f&lt;" revision="mbp@foo-123123" text_sha1="A" text_size="1" />
<directory file_id="foo-20050801201819-4139aa4a272f4250" name="subdir" parent_id="f&lt;" revision="mbp@foo-00" />
<file executable="yes" file_id="bar-20050824000535-6bc48cfad47ed134" name="bar" parent_id="foo-20050801201819-4139aa4a272f4250" revision="mbp@foo-00" text_sha1="B" text_size="0" />
<symlink file_id="link-1" name="link" parent_id="foo-20050801201819-4139aa4a272f4250" revision="mbp@foo-00" symlink_target="a" />
</inventory>
"""

_expected_inv_v6 = b"""<inventory format="6" revision_id="rev_outer">
<directory file_id="tree-root-321" name="" revision="rev_outer" />
<directory file_id="dir-id" name="dir" parent_id="tree-root-321" revision="rev_outer" />
<file file_id="file-id" name="file" parent_id="tree-root-321" revision="rev_outer" text_sha1="A" text_size="1" />
<symlink file_id="link-id" name="link" parent_id="tree-root-321" revision="rev_outer" symlink_target="a" />
</inventory>
"""

_expected_inv_v7 = b"""<inventory format="7" revision_id="rev_outer">
<directory file_id="tree-root-321" name="" revision="rev_outer" />
<directory file_id="dir-id" name="dir" parent_id="tree-root-321" revision="rev_outer" />
<file file_id="file-id" name="file" parent_id="tree-root-321" revision="rev_outer" text_sha1="A" text_size="1" />
<symlink file_id="link-id" name="link" parent_id="tree-root-321" revision="rev_outer" symlink_target="a" />
<tree-reference file_id="nested-id" name="nested" parent_id="tree-root-321" revision="rev_outer" reference_revision="rev_inner" />
</inventory>
"""

_expected_rev_v8 = b"""<revision committer="Martin Pool &lt;mbp@sourcefrog.net&gt;" format="8" inventory_sha1="e79c31c1deb64c163cf660fdedd476dd579ffd41" revision_id="mbp@sourcefrog.net-20050905080035-e0439293f8b6b9f9" timestamp="1125907235.212" timezone="36000">
<message>- start splitting code for xml (de)serialization away from objects
  preparatory to supporting multiple formats by a single library
</message>
<parents>
<revision_ref revision_id="mbp@sourcefrog.net-20050905063503-43948f59fa127d92" />
</parents>
</revision>
"""

_expected_inv_v8 = b"""<inventory format="8" revision_id="rev_outer">
<directory file_id="tree-root-321" name="" revision="rev_outer" />
<directory file_id="dir-id" name="dir" parent_id="tree-root-321" revision="rev_outer" />
<file file_id="file-id" name="file" parent_id="tree-root-321" revision="rev_outer" text_sha1="A" text_size="1" />
<symlink file_id="link-id" name="link" parent_id="tree-root-321" revision="rev_outer" symlink_target="a" />
</inventory>
"""

_revision_utf8_v5 = b"""<revision committer="Erik B&#229;gfors &lt;erik@foo.net&gt;"
    inventory_sha1="e79c31c1deb64c163cf660fdedd476dd579ffd41"
    revision_id="erik@b&#229;gfors-02"
    timestamp="1125907235.212"
    timezone="36000">
<message>Include &#181;nicode characters
</message>
<parents>
<revision_ref revision_id="erik@b&#229;gfors-01"/>
</parents>
</revision>
"""

_expected_rev_v8_complex = b"""<revision committer="Erik B&#229;gfors &lt;erik@foo.net&gt;" format="8" inventory_sha1="e79c31c1deb64c163cf660fdedd476dd579ffd41" revision_id="erik@b&#229;gfors-02" timestamp="1125907235.212" timezone="36000">
<message>Include &#181;nicode characters
</message>
<parents>
<revision_ref revision_id="erik@b&#229;gfors-01" />
<revision_ref revision_id="erik@bagfors-02" />
</parents>
<properties><property name="bar" />
<property name="foo">this has a
newline in it</property>
</properties>
</revision>
"""


_inventory_utf8_v5 = b"""<inventory file_id="TRE&#233;_ROOT" format="5"
                                   revision_id="erik@b&#229;gfors-02">
<file file_id="b&#229;r-01"
      name="b&#229;r" parent_id="TRE&#233;_ROOT"
      revision="erik@b&#229;gfors-01"/>
<directory name="s&#181;bdir"
           file_id="s&#181;bdir-01"
           parent_id="TRE&#233;_ROOT"
           revision="erik@b&#229;gfors-01"/>
<file executable="yes" file_id="b&#229;r-02"
      name="b&#229;r" parent_id="s&#181;bdir-01"
      revision="erik@b&#229;gfors-02"/>
</inventory>
"""

# Before revision_id was always stored as an attribute
_inventory_v5a = b"""<inventory format="5">
</inventory>
"""

# Before revision_id was always stored as an attribute
_inventory_v5b = b"""<inventory format="5" revision_id="a-rev-id">
</inventory>
"""


class TestSerializer(TestCase):
    """Test XML serialization."""

    def test_unpack_revision_5(self):
        """Test unpacking a canned revision v5."""
        inp = BytesIO(_revision_v5)
        rev = breezy.bzr.xml5.serializer_v5.read_revision(inp)
        eq = self.assertEqual
        eq(rev.committer, "Martin Pool <mbp@sourcefrog.net>")
        eq(len(rev.parent_ids), 1)
        eq(rev.timezone, 36000)
        eq(rev.parent_ids[0], b"mbp@sourcefrog.net-20050905063503-43948f59fa127d92")

    def test_unpack_revision_5_utc(self):
        inp = BytesIO(_revision_v5_utc)
        rev = breezy.bzr.xml5.serializer_v5.read_revision(inp)
        eq = self.assertEqual
        eq(rev.committer, "Martin Pool <mbp@sourcefrog.net>")
        eq(len(rev.parent_ids), 1)
        eq(rev.timezone, 0)
        eq(rev.parent_ids[0], b"mbp@sourcefrog.net-20050905063503-43948f59fa127d92")

    def test_unpack_inventory_5(self):
        """Unpack canned new-style inventory."""
        inp = BytesIO(_committed_inv_v5)
        inv = breezy.bzr.xml5.serializer_v5.read_inventory(inp)
        eq = self.assertEqual
        eq(len(inv), 4)
        ie = inv.get_entry(b"bar-20050824000535-6bc48cfad47ed134")
        eq(ie.kind, "file")
        eq(ie.revision, b"mbp@foo-00")
        eq(ie.name, "bar")
        eq(inv.get_entry(ie.parent_id).kind, "directory")

    def test_unpack_basis_inventory_5(self):
        """Unpack canned new-style inventory."""
        inv = breezy.bzr.xml5.serializer_v5.read_inventory_from_lines(
            breezy.osutils.split_lines(_basis_inv_v5)
        )
        eq = self.assertEqual
        eq(len(inv), 4)
        eq(inv.revision_id, b"mbp@sourcefrog.net-20050905063503-43948f59fa127d92")
        ie = inv.get_entry(b"bar-20050824000535-6bc48cfad47ed134")
        eq(ie.kind, "file")
        eq(ie.revision, b"mbp@foo-00")
        eq(ie.name, "bar")
        eq(inv.get_entry(ie.parent_id).kind, "directory")

    def test_unpack_inventory_5a(self):
        inv = breezy.bzr.xml5.serializer_v5.read_inventory_from_lines(
            breezy.osutils.split_lines(_inventory_v5a), revision_id=b"test-rev-id"
        )
        self.assertEqual(b"test-rev-id", inv.root.revision)

    def test_unpack_inventory_5a_cache_and_copy(self):
        # Passing an entry_cache should get populated with the objects
        # But the returned objects should be copies if return_from_cache is
        # False
        entry_cache = fifo_cache.FIFOCache()
        inv = breezy.bzr.xml5.serializer_v5.read_inventory_from_lines(
            breezy.osutils.split_lines(_inventory_v5a),
            revision_id=b"test-rev-id",
            entry_cache=entry_cache,
            return_from_cache=False,
        )
        for entry in inv.iter_just_entries():
            key = (entry.file_id, entry.revision)
            if entry.file_id is inv.root.file_id:
                # The root id is inferred for xml v5
                self.assertFalse(key in entry_cache)
            else:
                self.assertIsNot(entry, entry_cache[key])

    def test_unpack_inventory_5a_cache_no_copy(self):
        # Passing an entry_cache should get populated with the objects
        # The returned objects should be exact if return_from_cache is
        # True
        entry_cache = fifo_cache.FIFOCache()
        inv = breezy.bzr.xml5.serializer_v5.read_inventory_from_lines(
            breezy.osutils.split_lines(_inventory_v5a),
            revision_id=b"test-rev-id",
            entry_cache=entry_cache,
            return_from_cache=True,
        )
        for entry in inv.iter_just_entries():
            key = (entry.file_id, entry.revision)
            if entry.file_id is inv.root.file_id:
                # The root id is inferred for xml v5
                self.assertFalse(key in entry_cache)
            else:
                self.assertIs(entry, entry_cache[key])

    def test_unpack_inventory_5b(self):
        inv = breezy.bzr.xml5.serializer_v5.read_inventory_from_lines(
            breezy.osutils.split_lines(_inventory_v5b), revision_id=b"test-rev-id"
        )
        self.assertEqual(b"a-rev-id", inv.root.revision)

    def test_repack_inventory_5(self):
        inv = breezy.bzr.xml5.serializer_v5.read_inventory_from_lines(
            breezy.osutils.split_lines(_committed_inv_v5)
        )
        outp = BytesIO()
        breezy.bzr.xml5.serializer_v5.write_inventory(inv, outp)
        self.assertEqualDiff(_expected_inv_v5, outp.getvalue())
        inv2 = breezy.bzr.xml5.serializer_v5.read_inventory_from_lines(
            breezy.osutils.split_lines(outp.getvalue())
        )
        self.assertEqual(inv, inv2)

    def assertRoundTrips(self, xml_string):
        inp = BytesIO(xml_string)
        inv = breezy.bzr.xml5.serializer_v5.read_inventory(inp)
        outp = BytesIO()
        breezy.bzr.xml5.serializer_v5.write_inventory(inv, outp)
        self.assertEqualDiff(xml_string, outp.getvalue())
        lines = breezy.bzr.xml5.serializer_v5.write_inventory_to_lines(inv)
        outp.seek(0)
        self.assertEqual(outp.readlines(), lines)
        inv2 = breezy.bzr.xml5.serializer_v5.read_inventory(BytesIO(outp.getvalue()))
        self.assertEqual(inv, inv2)

    def tests_serialize_inventory_v5_with_root(self):
        self.assertRoundTrips(_expected_inv_v5_root)

    def check_repack_revision(self, txt):
        """Check that repacking a revision yields the same information."""
        inp = BytesIO(txt)
        rev = breezy.bzr.xml5.serializer_v5.read_revision(inp)
        outfile_contents = breezy.bzr.xml5.serializer_v5.write_revision_to_string(rev)
        rev2 = breezy.bzr.xml5.serializer_v5.read_revision(BytesIO(outfile_contents))
        self.assertEqual(rev, rev2)

    def test_repack_revision_5(self):
        """Round-trip revision to XML v5."""
        self.check_repack_revision(_revision_v5)

    def test_repack_revision_5_utc(self):
        self.check_repack_revision(_revision_v5_utc)

    def test_pack_revision_5(self):
        """Pack revision to XML v5."""
        # fixed 20051025, revisions should have final newline
        rev = breezy.bzr.xml5.serializer_v5.read_revision_from_string(_revision_v5)
        outfile_contents = breezy.bzr.xml5.serializer_v5.write_revision_to_string(rev)
        self.assertEqual(outfile_contents[-1:], b"\n")
        self.assertEqualDiff(
            outfile_contents,
            b"".join(breezy.bzr.xml5.serializer_v5.write_revision_to_lines(rev)),
        )
        self.assertEqualDiff(outfile_contents, _expected_rev_v5)

    def test_empty_property_value(self):
        """Create an empty property value check that it serializes correctly."""
        s_v5 = breezy.bzr.xml5.serializer_v5
        rev = s_v5.read_revision_from_string(_revision_v5)
        props = {"empty": "", "one": "one"}
        rev.properties = props
        txt = b"".join(s_v5.write_revision_to_lines(rev))
        new_rev = s_v5.read_revision_from_string(txt)
        self.assertEqual(props, new_rev.properties)

    def get_sample_inventory(self):
        inv = Inventory(b"tree-root-321", revision_id=b"rev_outer")
        inv.add(inventory.InventoryFile(b"file-id", "file", b"tree-root-321"))
        inv.add(inventory.InventoryDirectory(b"dir-id", "dir", b"tree-root-321"))
        inv.add(inventory.InventoryLink(b"link-id", "link", b"tree-root-321"))
        inv.get_entry(b"tree-root-321").revision = b"rev_outer"
        inv.get_entry(b"dir-id").revision = b"rev_outer"
        inv.get_entry(b"file-id").revision = b"rev_outer"
        inv.get_entry(b"file-id").text_sha1 = b"A"
        inv.get_entry(b"file-id").text_size = 1
        inv.get_entry(b"link-id").revision = b"rev_outer"
        inv.get_entry(b"link-id").symlink_target = "a"
        return inv

    def test_roundtrip_inventory_v7(self):
        inv = self.get_sample_inventory()
        inv.add(
            inventory.TreeReference(
                b"nested-id", "nested", b"tree-root-321", b"rev_outer", b"rev_inner"
            )
        )
        lines = xml7.serializer_v7.write_inventory_to_lines(inv)
        self.assertEqualDiff(_expected_inv_v7, b"".join(lines))
        inv2 = xml7.serializer_v7.read_inventory_from_lines(lines)
        self.assertEqual(5, len(inv2))
        for _path, ie in inv.iter_entries():
            self.assertEqual(ie, inv2.get_entry(ie.file_id))

    def test_roundtrip_inventory_v6(self):
        inv = self.get_sample_inventory()
        lines = xml6.serializer_v6.write_inventory_to_lines(inv)
        self.assertEqualDiff(_expected_inv_v6, b"".join(lines))
        inv2 = xml6.serializer_v6.read_inventory_from_lines(lines)
        self.assertEqual(4, len(inv2))
        for _path, ie in inv.iter_entries():
            self.assertEqual(ie, inv2.get_entry(ie.file_id))

    def test_wrong_format_v7(self):
        """Can't accidentally open a file with wrong serializer."""
        s_v6 = breezy.bzr.xml6.serializer_v6
        s_v7 = xml7.serializer_v7
        self.assertRaises(
            serializer.UnexpectedInventoryFormat,
            s_v7.read_inventory_from_lines,
            breezy.osutils.split_lines(_expected_inv_v5),
        )
        self.assertRaises(
            serializer.UnexpectedInventoryFormat,
            s_v6.read_inventory_from_lines,
            breezy.osutils.split_lines(_expected_inv_v7),
        )

    def test_tree_reference(self):
        s_v5 = breezy.bzr.xml5.serializer_v5
        s_v6 = breezy.bzr.xml6.serializer_v6
        s_v7 = xml7.serializer_v7
        inv = Inventory(b"tree-root-321", revision_id=b"rev-outer")
        inv.root.revision = b"root-rev"
        inv.add(
            inventory.TreeReference(
                b"nested-id", "nested", b"tree-root-321", b"rev-outer", b"rev-inner"
            )
        )
        self.assertRaises(
            serializer.UnsupportedInventoryKind, s_v5.write_inventory_to_lines, inv
        )
        self.assertRaises(
            serializer.UnsupportedInventoryKind, s_v6.write_inventory_to_lines, inv
        )
        lines = s_v7.write_inventory_to_chunks(inv)
        inv2 = s_v7.read_inventory_from_lines(lines)
        self.assertEqual(b"tree-root-321", inv2.get_entry(b"nested-id").parent_id)
        self.assertEqual(b"rev-outer", inv2.get_entry(b"nested-id").revision)
        self.assertEqual(b"rev-inner", inv2.get_entry(b"nested-id").reference_revision)

    def test_roundtrip_inventory_v8(self):
        inv = self.get_sample_inventory()
        lines = xml8.serializer_v8.write_inventory_to_lines(inv)
        inv2 = xml8.serializer_v8.read_inventory_from_lines(lines)
        self.assertEqual(4, len(inv2))
        for _path, ie in inv.iter_entries():
            self.assertEqual(ie, inv2.get_entry(ie.file_id))

    def test_inventory_text_v8(self):
        inv = self.get_sample_inventory()
        lines = xml8.serializer_v8.write_inventory_to_lines(inv)
        self.assertEqualDiff(_expected_inv_v8, b"".join(lines))

    def test_revision_text_v6(self):
        """Pack revision to XML v6."""
        rev = breezy.bzr.xml6.serializer_v6.read_revision_from_string(_expected_rev_v5)
        serialized = breezy.bzr.xml6.serializer_v6.write_revision_to_lines(rev)
        self.assertEqualDiff(b"".join(serialized), _expected_rev_v5)

    def test_revision_text_v7(self):
        """Pack revision to XML v7."""
        rev = breezy.bzr.xml7.serializer_v7.read_revision_from_string(_expected_rev_v5)
        serialized = breezy.bzr.xml7.serializer_v7.write_revision_to_lines(rev)
        self.assertEqualDiff(b"".join(serialized), _expected_rev_v5)

    def test_revision_text_v8(self):
        """Pack revision to XML v8."""
        rev = breezy.bzr.xml8.serializer_v8.read_revision_from_string(_expected_rev_v8)
        serialized = breezy.bzr.xml8.serializer_v8.write_revision_to_lines(rev)
        self.assertEqualDiff(b"".join(serialized), _expected_rev_v8)

    def test_revision_text_v8_complex(self):
        """Pack revision to XML v8."""
        rev = breezy.bzr.xml8.serializer_v8.read_revision_from_string(
            _expected_rev_v8_complex
        )
        serialized = breezy.bzr.xml8.serializer_v8.write_revision_to_lines(rev)
        self.assertEqualDiff(b"".join(serialized), _expected_rev_v8_complex)

    def test_revision_ids_are_utf8(self):
        """Parsed revision_ids should all be utf-8 strings, not unicode."""
        s_v5 = breezy.bzr.xml5.serializer_v5
        rev = s_v5.read_revision_from_string(_revision_utf8_v5)
        self.assertEqual(b"erik@b\xc3\xa5gfors-02", rev.revision_id)
        self.assertIsInstance(rev.revision_id, bytes)
        self.assertEqual([b"erik@b\xc3\xa5gfors-01"], rev.parent_ids)
        for parent_id in rev.parent_ids:
            self.assertIsInstance(parent_id, bytes)
        self.assertEqual("Include \xb5nicode characters\n", rev.message)
        self.assertIsInstance(rev.message, str)

        # ie.revision should either be None or a utf-8 revision id
        inv = s_v5.read_inventory_from_lines(
            breezy.osutils.split_lines(_inventory_utf8_v5)
        )
        rev_id_1 = "erik@b\xe5gfors-01".encode()
        rev_id_2 = "erik@b\xe5gfors-02".encode()
        fid_root = "TRE\xe9_ROOT".encode()
        fid_bar1 = "b\xe5r-01".encode()
        fid_sub = "s\xb5bdir-01".encode()
        fid_bar2 = "b\xe5r-02".encode()
        expected = [
            ("", fid_root, None, rev_id_2),
            ("b\xe5r", fid_bar1, fid_root, rev_id_1),
            ("s\xb5bdir", fid_sub, fid_root, rev_id_1),
            ("s\xb5bdir/b\xe5r", fid_bar2, fid_sub, rev_id_2),
        ]
        self.assertEqual(rev_id_2, inv.revision_id)
        self.assertIsInstance(inv.revision_id, bytes)

        actual = list(inv.iter_entries_by_dir())
        for (exp_path, exp_file_id, exp_parent_id, exp_rev_id), (
            act_path,
            act_ie,
        ) in zip(expected, actual, strict=False):
            self.assertEqual(exp_path, act_path)
            self.assertIsInstance(act_path, str)
            self.assertEqual(exp_file_id, act_ie.file_id)
            self.assertIsInstance(act_ie.file_id, bytes)
            self.assertEqual(exp_parent_id, act_ie.parent_id)
            if exp_parent_id is not None:
                self.assertIsInstance(act_ie.parent_id, bytes)
            self.assertEqual(exp_rev_id, act_ie.revision)
            if exp_rev_id is not None:
                self.assertIsInstance(act_ie.revision, bytes)

        self.assertEqual(len(expected), len(actual))

    def test_serialization_error(self):
        s_v5 = breezy.bzr.xml5.serializer_v5
        e = self.assertRaises(
            serializer.UnexpectedInventoryFormat,
            s_v5.read_inventory_from_lines,
            [b"<Notquitexml"],
        )
        self.assertEqual(str(e), "unclosed token: line 1, column 0")


class TestEncodeAndEscape(TestCase):
    """Whitebox testing of the _encode_and_escape function."""

    def setUp(self):
        super().setUp()
        # Keep the cache clear before and after the test
        breezy.bzr.xml_serializer._clear_cache()
        self.addCleanup(breezy.bzr.xml_serializer._clear_cache)

    def test_simple_ascii(self):
        # _encode_and_escape always appends a final ", because these parameters
        # are being used in xml attributes, and by returning it now, we have to
        # do fewer string operations later.
        val = breezy.bzr.xml_serializer.encode_and_escape("foo bar")
        self.assertEqual(b"foo bar", val)
        # The second time should be cached
        val2 = breezy.bzr.xml_serializer.encode_and_escape("foo bar")
        self.assertIs(val2, val)

    def test_ascii_with_xml(self):
        self.assertEqual(
            b"&amp;&apos;&quot;&lt;&gt;",
            breezy.bzr.xml_serializer.encode_and_escape("&'\"<>"),
        )

    def test_utf8_with_xml(self):
        # u'\xb5\xe5&\u062c'
        utf8_str = b"\xc2\xb5\xc3\xa5&\xd8\xac"
        self.assertEqual(
            b"&#181;&#229;&amp;&#1580;",
            breezy.bzr.xml_serializer.encode_and_escape(utf8_str),
        )

    def test_unicode(self):
        uni_str = "\xb5\xe5&\u062c"
        self.assertEqual(
            b"&#181;&#229;&amp;&#1580;",
            breezy.bzr.xml_serializer.encode_and_escape(uni_str),
        )


class TestMisc(TestCase):
    def test_unescape_xml(self):
        """We get some kind of error when malformed entities are passed."""
        self.assertRaises(KeyError, breezy.bzr.xml8._unescape_xml, b"foo&bar;")
