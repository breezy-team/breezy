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

"""Tests for breezy.bzr.inventory_delta.

See doc/developer/inventory.txt for more information.
"""

from io import BytesIO

from ... import osutils
from ...revision import NULL_REVISION
from .. import inventory, inventory_delta
from ..inventory import Inventory
from ..inventory_delta import InventoryDeltaError
from . import TestCase

### DO NOT REFLOW THESE TEXTS. NEW LINES ARE SIGNIFICANT. ###
empty_lines = b"""format: bzr inventory delta v1 (bzr 1.14)
parent: null:
version: null:
versioned_root: true
tree_references: true
"""

root_only_lines = b"""format: bzr inventory delta v1 (bzr 1.14)
parent: null:
version: entry-version
versioned_root: true
tree_references: true
None\x00/\x00an-id\x00\x00a@e\xc3\xa5ample.com--2004\x00dir
"""


root_change_lines = b"""format: bzr inventory delta v1 (bzr 1.14)
parent: entry-version
version: changed-root
versioned_root: true
tree_references: true
/\x00an-id\x00\x00different-version\x00dir
"""

corrupt_parent_lines = b"""format: bzr inventory delta v1 (bzr 1.14)
parent: entry-version
version: changed-root
versioned_root: false
tree_references: false
/\x00an-id\x00\x00different-version\x00dir
"""

root_only_unversioned = b"""format: bzr inventory delta v1 (bzr 1.14)
parent: null:
version: entry-version
versioned_root: false
tree_references: false
None\x00/\x00TREE_ROOT\x00\x00entry-version\x00dir
"""

reference_lines = b"""format: bzr inventory delta v1 (bzr 1.14)
parent: null:
version: entry-version
versioned_root: true
tree_references: true
None\x00/\x00TREE_ROOT\x00\x00a@e\xc3\xa5ample.com--2004\x00dir
None\x00/foo\x00id\x00TREE_ROOT\x00changed\x00tree\x00subtree-version
"""

change_tree_lines = b"""format: bzr inventory delta v1 (bzr 1.14)
parent: entry-version
version: change-tree
versioned_root: false
tree_references: false
/foo\x00id\x00TREE_ROOT\x00changed-twice\x00tree\x00subtree-version2
"""


class TestDeserialization(TestCase):
    """Test InventoryDeltaSerializer.parse_text_bytes."""

    def test_parse_no_bytes(self):
        deserializer = inventory_delta.InventoryDeltaDeserializer()
        err = self.assertRaises(InventoryDeltaError, deserializer.parse_text_bytes, [])
        self.assertContainsRe(str(err), "inventory delta is empty")

    def test_parse_bad_format(self):
        deserializer = inventory_delta.InventoryDeltaDeserializer()
        err = self.assertRaises(
            InventoryDeltaError, deserializer.parse_text_bytes, [b"format: foo\n"]
        )
        self.assertContainsRe(str(err), "unknown format")

    def test_parse_no_parent(self):
        deserializer = inventory_delta.InventoryDeltaDeserializer()
        err = self.assertRaises(
            InventoryDeltaError,
            deserializer.parse_text_bytes,
            [b"format: bzr inventory delta v1 (bzr 1.14)\n"],
        )
        self.assertContainsRe(str(err), "missing parent: marker")

    def test_parse_no_version(self):
        deserializer = inventory_delta.InventoryDeltaDeserializer()
        err = self.assertRaises(
            InventoryDeltaError,
            deserializer.parse_text_bytes,
            [b"format: bzr inventory delta v1 (bzr 1.14)\n", b"parent: null:\n"],
        )
        self.assertContainsRe(str(err), "missing version: marker")

    def test_parse_duplicate_key_errors(self):
        deserializer = inventory_delta.InventoryDeltaDeserializer()
        double_root_lines = b"""format: bzr inventory delta v1 (bzr 1.14)
parent: null:
version: null:
versioned_root: true
tree_references: true
None\x00/\x00an-id\x00\x00a@e\xc3\xa5ample.com--2004\x00dir\x00\x00
None\x00/\x00an-id\x00\x00a@e\xc3\xa5ample.com--2004\x00dir\x00\x00
"""
        err = self.assertRaises(
            InventoryDeltaError,
            deserializer.parse_text_bytes,
            osutils.split_lines(double_root_lines),
        )
        self.assertContainsRe(str(err), "duplicate file id")

    def test_parse_versioned_root_only(self):
        deserializer = inventory_delta.InventoryDeltaDeserializer()
        parse_result = deserializer.parse_text_bytes(
            osutils.split_lines(root_only_lines)
        )
        expected_entry = inventory.make_entry("directory", "", None, b"an-id")
        expected_entry.revision = b"a@e\xc3\xa5ample.com--2004"
        self.assertEqual(
            (
                b"null:",
                b"entry-version",
                True,
                True,
                [(None, "", b"an-id", expected_entry)],
            ),
            parse_result,
        )

    def test_parse_special_revid_not_valid_last_mod(self):
        deserializer = inventory_delta.InventoryDeltaDeserializer()
        root_only_lines = b"""format: bzr inventory delta v1 (bzr 1.14)
parent: null:
version: null:
versioned_root: false
tree_references: true
None\x00/\x00TREE_ROOT\x00\x00null:\x00dir\x00\x00
"""
        err = self.assertRaises(
            InventoryDeltaError,
            deserializer.parse_text_bytes,
            osutils.split_lines(root_only_lines),
        )
        self.assertContainsRe(str(err), "special revisionid found")

    def test_parse_versioned_root_versioned_disabled(self):
        deserializer = inventory_delta.InventoryDeltaDeserializer()
        root_only_lines = b"""format: bzr inventory delta v1 (bzr 1.14)
parent: null:
version: null:
versioned_root: false
tree_references: true
None\x00/\x00TREE_ROOT\x00\x00a@e\xc3\xa5ample.com--2004\x00dir\x00\x00
"""
        err = self.assertRaises(
            InventoryDeltaError,
            deserializer.parse_text_bytes,
            osutils.split_lines(root_only_lines),
        )
        self.assertContainsRe(str(err), "Versioned root found")

    def test_parse_unique_root_id_root_versioned_disabled(self):
        deserializer = inventory_delta.InventoryDeltaDeserializer()
        root_only_lines = b"""format: bzr inventory delta v1 (bzr 1.14)
parent: parent-id
version: a@e\xc3\xa5ample.com--2004
versioned_root: false
tree_references: true
None\x00/\x00an-id\x00\x00parent-id\x00dir\x00\x00
"""
        err = self.assertRaises(
            InventoryDeltaError,
            deserializer.parse_text_bytes,
            osutils.split_lines(root_only_lines),
        )
        self.assertContainsRe(str(err), "Versioned root found")

    def test_parse_unversioned_root_versioning_enabled(self):
        deserializer = inventory_delta.InventoryDeltaDeserializer()
        parse_result = deserializer.parse_text_bytes(
            osutils.split_lines(root_only_unversioned)
        )
        expected_entry = inventory.make_entry("directory", "", None, b"TREE_ROOT")
        expected_entry.revision = b"entry-version"
        self.assertEqual(
            (
                b"null:",
                b"entry-version",
                False,
                False,
                [(None, "", b"TREE_ROOT", expected_entry)],
            ),
            parse_result,
        )

    def test_parse_versioned_root_when_disabled(self):
        deserializer = inventory_delta.InventoryDeltaDeserializer(
            allow_versioned_root=False
        )
        err = self.assertRaises(
            inventory_delta.IncompatibleInventoryDelta,
            deserializer.parse_text_bytes,
            osutils.split_lines(root_only_lines),
        )
        self.assertEqual("versioned_root not allowed", str(err))

    def test_parse_tree_when_disabled(self):
        deserializer = inventory_delta.InventoryDeltaDeserializer(
            allow_tree_references=False
        )
        err = self.assertRaises(
            inventory_delta.IncompatibleInventoryDelta,
            deserializer.parse_text_bytes,
            osutils.split_lines(reference_lines),
        )
        self.assertEqual("Tree reference not allowed", str(err))

    def test_parse_tree_when_header_disallows(self):
        # A deserializer that allows tree_references to be set or unset.
        deserializer = inventory_delta.InventoryDeltaDeserializer()
        # A serialised inventory delta with a header saying no tree refs, but
        # that has a tree ref in its content.
        lines = b"""format: bzr inventory delta v1 (bzr 1.14)
parent: null:
version: entry-version
versioned_root: false
tree_references: false
None\x00/foo\x00id\x00TREE_ROOT\x00changed\x00tree\x00subtree-version
"""
        err = self.assertRaises(
            InventoryDeltaError,
            deserializer.parse_text_bytes,
            osutils.split_lines(lines),
        )
        self.assertContainsRe(str(err), "Tree reference found")

    def test_parse_versioned_root_when_header_disallows(self):
        # A deserializer that allows tree_references to be set or unset.
        deserializer = inventory_delta.InventoryDeltaDeserializer()
        # A serialised inventory delta with a header saying no tree refs, but
        # that has a tree ref in its content.
        lines = b"""format: bzr inventory delta v1 (bzr 1.14)
parent: null:
version: entry-version
versioned_root: false
tree_references: false
None\x00/\x00TREE_ROOT\x00\x00a@e\xc3\xa5ample.com--2004\x00dir
"""
        err = self.assertRaises(
            InventoryDeltaError,
            deserializer.parse_text_bytes,
            osutils.split_lines(lines),
        )
        self.assertContainsRe(str(err), "Versioned root found")

    def test_parse_last_line_not_empty(self):
        """Newpath must start with / if it is not None."""
        # Trim the trailing newline from a valid serialization
        lines = root_only_lines[:-1]
        deserializer = inventory_delta.InventoryDeltaDeserializer()
        err = self.assertRaises(
            InventoryDeltaError,
            deserializer.parse_text_bytes,
            osutils.split_lines(lines),
        )
        self.assertContainsRe(str(err), "last line not empty")

    def test_parse_invalid_newpath(self):
        """Newpath must start with / if it is not None."""
        lines = empty_lines
        lines += b"None\x00bad\x00TREE_ROOT\x00\x00version\x00dir\n"
        deserializer = inventory_delta.InventoryDeltaDeserializer()
        err = self.assertRaises(
            InventoryDeltaError,
            deserializer.parse_text_bytes,
            osutils.split_lines(lines),
        )
        self.assertContainsRe(str(err), "newpath invalid")

    def test_parse_invalid_oldpath(self):
        """Oldpath must start with / if it is not None."""
        lines = root_only_lines
        lines += b"bad\x00/new\x00file-id\x00\x00version\x00dir\n"
        deserializer = inventory_delta.InventoryDeltaDeserializer()
        err = self.assertRaises(
            InventoryDeltaError,
            deserializer.parse_text_bytes,
            osutils.split_lines(lines),
        )
        self.assertContainsRe(str(err), "oldpath invalid")

    def test_parse_new_file(self):
        """A new file is parsed correctly"""
        lines = root_only_lines
        fake_sha = b"deadbeef" * 5
        lines += (
            b"None\x00/new\x00file-id\x00an-id\x00version\x00file\x00123\x00"
            + b"\x00"
            + fake_sha
            + b"\n"
        )
        deserializer = inventory_delta.InventoryDeltaDeserializer()
        parse_result = deserializer.parse_text_bytes(osutils.split_lines(lines))
        expected_entry = inventory.make_entry("file", "new", b"an-id", b"file-id")
        expected_entry.revision = b"version"
        expected_entry.text_size = 123
        expected_entry.text_sha1 = fake_sha
        delta = parse_result[4]
        self.assertEqual((None, "new", b"file-id", expected_entry), delta[-1])

    def test_parse_delete(self):
        lines = root_only_lines
        lines += b"/old-file\x00None\x00deleted-id\x00\x00null:\x00deleted\x00\x00\n"
        deserializer = inventory_delta.InventoryDeltaDeserializer()
        parse_result = deserializer.parse_text_bytes(osutils.split_lines(lines))
        delta = parse_result[4]
        self.assertEqual(("old-file", None, b"deleted-id", None), delta[-1])


class TestSerialization(TestCase):
    """Tests for InventoryDeltaSerializer.delta_to_lines."""

    def test_empty_delta_to_lines(self):
        old_inv = Inventory(None)
        new_inv = Inventory(None)
        delta = new_inv._make_delta(old_inv)
        serializer = inventory_delta.InventoryDeltaSerializer(
            versioned_root=True, tree_references=True
        )
        self.assertEqual(
            BytesIO(empty_lines).readlines(),
            serializer.delta_to_lines(NULL_REVISION, NULL_REVISION, delta),
        )

    def test_root_only_to_lines(self):
        old_inv = Inventory(None)
        new_inv = Inventory(None)
        root = new_inv.make_entry("directory", "", None, b"an-id")
        root.revision = b"a@e\xc3\xa5ample.com--2004"
        new_inv.add(root)
        delta = new_inv._make_delta(old_inv)
        serializer = inventory_delta.InventoryDeltaSerializer(
            versioned_root=True, tree_references=True
        )
        self.assertEqual(
            BytesIO(root_only_lines).readlines(),
            serializer.delta_to_lines(NULL_REVISION, b"entry-version", delta),
        )

    def test_unversioned_root(self):
        old_inv = Inventory(None)
        new_inv = Inventory(None)
        root = new_inv.make_entry("directory", "", None, b"TREE_ROOT")
        # Implicit roots are considered modified in every revision.
        root.revision = b"entry-version"
        new_inv.add(root)
        delta = new_inv._make_delta(old_inv)
        serializer = inventory_delta.InventoryDeltaSerializer(
            versioned_root=False, tree_references=False
        )
        serialized_lines = serializer.delta_to_lines(
            NULL_REVISION, b"entry-version", delta
        )
        self.assertEqual(BytesIO(root_only_unversioned).readlines(), serialized_lines)
        deserializer = inventory_delta.InventoryDeltaDeserializer()
        self.assertEqual(
            (NULL_REVISION, b"entry-version", False, False, delta),
            deserializer.parse_text_bytes(serialized_lines),
        )

    def test_unversioned_non_root_errors(self):
        old_inv = Inventory(None)
        new_inv = Inventory(None)
        root = new_inv.make_entry("directory", "", None, b"TREE_ROOT")
        root.revision = b"a@e\xc3\xa5ample.com--2004"
        new_inv.add(root)
        non_root = new_inv.make_entry("directory", "foo", root.file_id, b"id")
        new_inv.add(non_root)
        delta = new_inv._make_delta(old_inv)
        serializer = inventory_delta.InventoryDeltaSerializer(
            versioned_root=True, tree_references=True
        )
        err = self.assertRaises(
            InventoryDeltaError,
            serializer.delta_to_lines,
            NULL_REVISION,
            b"entry-version",
            delta,
        )
        self.assertContainsRe(str(err), "^no version for fileid b?'id'$")

    def test_richroot_unversioned_root_errors(self):
        old_inv = Inventory(None)
        new_inv = Inventory(None)
        root = new_inv.make_entry("directory", "", None, b"TREE_ROOT")
        new_inv.add(root)
        delta = new_inv._make_delta(old_inv)
        serializer = inventory_delta.InventoryDeltaSerializer(
            versioned_root=True, tree_references=True
        )
        err = self.assertRaises(
            InventoryDeltaError,
            serializer.delta_to_lines,
            NULL_REVISION,
            b"entry-version",
            delta,
        )
        self.assertContainsRe(str(err), "no version for fileid b?'TREE_ROOT'$")

    def test_nonrichroot_versioned_root_errors(self):
        old_inv = Inventory(None)
        new_inv = Inventory(None)
        root = new_inv.make_entry("directory", "", None, b"TREE_ROOT")
        root.revision = b"a@e\xc3\xa5ample.com--2004"
        new_inv.add(root)
        delta = new_inv._make_delta(old_inv)
        serializer = inventory_delta.InventoryDeltaSerializer(
            versioned_root=False, tree_references=True
        )
        err = self.assertRaises(
            InventoryDeltaError,
            serializer.delta_to_lines,
            NULL_REVISION,
            b"entry-version",
            delta,
        )
        self.assertContainsRe(str(err), "^Version present for / in b?'TREE_ROOT'")

    def test_unknown_kind_errors(self):
        old_inv = Inventory(None)
        new_inv = Inventory(None)
        root = new_inv.make_entry("directory", "", None, b"my-rich-root-id")
        root.revision = b"changed"
        new_inv.add(root)

        class StrangeInventoryEntry(inventory.InventoryEntry):
            kind = "strange"

        non_root = StrangeInventoryEntry(b"id", "foo", root.file_id)
        non_root.revision = b"changed"
        new_inv.add(non_root)
        delta = new_inv._make_delta(old_inv)
        serializer = inventory_delta.InventoryDeltaSerializer(
            versioned_root=True, tree_references=True
        )
        # we expect keyerror because there is little value wrapping this.
        # This test aims to prove that it errors more than how it errors.
        err = self.assertRaises(
            KeyError, serializer.delta_to_lines, NULL_REVISION, b"entry-version", delta
        )
        self.assertEqual(("strange",), err.args)

    def test_tree_reference_disabled(self):
        old_inv = Inventory(None)
        new_inv = Inventory(None)
        root = new_inv.make_entry("directory", "", None, b"TREE_ROOT")
        root.revision = b"a@e\xc3\xa5ample.com--2004"
        new_inv.add(root)
        non_root = new_inv.make_entry("tree-reference", "foo", root.file_id, b"id")
        non_root.revision = b"changed"
        non_root.reference_revision = b"subtree-version"
        new_inv.add(non_root)
        delta = new_inv._make_delta(old_inv)
        serializer = inventory_delta.InventoryDeltaSerializer(
            versioned_root=True, tree_references=False
        )
        # we expect keyerror because there is little value wrapping this.
        # This test aims to prove that it errors more than how it errors.
        err = self.assertRaises(
            KeyError, serializer.delta_to_lines, NULL_REVISION, b"entry-version", delta
        )
        self.assertEqual(("tree-reference",), err.args)

    def test_tree_reference_enabled(self):
        old_inv = Inventory(None)
        new_inv = Inventory(None)
        root = new_inv.make_entry("directory", "", None, b"TREE_ROOT")
        root.revision = b"a@e\xc3\xa5ample.com--2004"
        new_inv.add(root)
        non_root = new_inv.make_entry("tree-reference", "foo", root.file_id, b"id")
        non_root.revision = b"changed"
        non_root.reference_revision = b"subtree-version"
        new_inv.add(non_root)
        delta = new_inv._make_delta(old_inv)
        serializer = inventory_delta.InventoryDeltaSerializer(
            versioned_root=True, tree_references=True
        )
        self.assertEqual(
            BytesIO(reference_lines).readlines(),
            serializer.delta_to_lines(NULL_REVISION, b"entry-version", delta),
        )

    def test_to_inventory_root_id_versioned_not_permitted(self):
        root_entry = inventory.make_entry("directory", "", None, b"TREE_ROOT")
        root_entry.revision = b"some-version"
        delta = [(None, "", b"TREE_ROOT", root_entry)]
        serializer = inventory_delta.InventoryDeltaSerializer(
            versioned_root=False, tree_references=True
        )
        self.assertRaises(
            InventoryDeltaError,
            serializer.delta_to_lines,
            b"old-version",
            b"new-version",
            delta,
        )

    def test_to_inventory_root_id_not_versioned(self):
        delta = [
            (None, "", b"an-id", inventory.make_entry("directory", "", None, b"an-id"))
        ]
        serializer = inventory_delta.InventoryDeltaSerializer(
            versioned_root=True, tree_references=True
        )
        self.assertRaises(
            InventoryDeltaError,
            serializer.delta_to_lines,
            b"old-version",
            b"new-version",
            delta,
        )

    def test_to_inventory_has_tree_not_meant_to(self):
        make_entry = inventory.make_entry
        tree_ref = make_entry("tree-reference", "foo", b"changed-in", b"ref-id")
        tree_ref.reference_revision = b"ref-revision"
        delta = [
            (None, "", b"an-id", make_entry("directory", "", b"changed-in", b"an-id")),
            (None, "foo", b"ref-id", tree_ref),
            # a file that followed the root move
        ]
        serializer = inventory_delta.InventoryDeltaSerializer(
            versioned_root=True, tree_references=True
        )
        self.assertRaises(
            InventoryDeltaError,
            serializer.delta_to_lines,
            b"old-version",
            b"new-version",
            delta,
        )

    def test_to_inventory_torture(self):
        def make_entry(kind, name, parent_id, file_id, **attrs):
            entry = inventory.make_entry(kind, name, parent_id, file_id)
            for name, value in attrs.items():
                setattr(entry, name, value)
            return entry

        # this delta is crafted to have all the following:
        # - deletes
        # - renamed roots
        # - deep dirs
        # - files moved after parent dir was renamed
        # - files with and without exec bit
        delta = [
            # new root:
            (
                None,
                "",
                b"new-root-id",
                make_entry(
                    "directory", "", None, b"new-root-id", revision=b"changed-in"
                ),
            ),
            # an old root:
            (
                "",
                "old-root",
                b"TREE_ROOT",
                make_entry(
                    "directory",
                    "subdir-now",
                    b"new-root-id",
                    b"TREE_ROOT",
                    revision=b"moved-root",
                ),
            ),
            # a file that followed the root move
            (
                "under-old-root",
                "old-root/under-old-root",
                b"moved-id",
                make_entry(
                    "file",
                    "under-old-root",
                    b"TREE_ROOT",
                    b"moved-id",
                    revision=b"old-rev",
                    executable=False,
                    text_size=30,
                    text_sha1=b"some-sha",
                ),
            ),
            # a deleted path
            ("old-file", None, b"deleted-id", None),
            # a tree reference moved to the new root
            (
                "ref",
                "ref",
                b"ref-id",
                make_entry(
                    "tree-reference",
                    "ref",
                    b"new-root-id",
                    b"ref-id",
                    reference_revision=b"tree-reference-id",
                    revision=b"new-rev",
                ),
            ),
            # a symlink now in a deep dir
            (
                "dir/link",
                "old-root/dir/link",
                b"link-id",
                make_entry(
                    "symlink",
                    "link",
                    b"deep-id",
                    b"link-id",
                    symlink_target="target",
                    revision=b"new-rev",
                ),
            ),
            # a deep dir
            (
                "dir",
                "old-root/dir",
                b"deep-id",
                make_entry(
                    "directory", "dir", b"TREE_ROOT", b"deep-id", revision=b"new-rev"
                ),
            ),
            # a file with an exec bit set
            (
                None,
                "configure",
                b"exec-id",
                make_entry(
                    "file",
                    "configure",
                    b"new-root-id",
                    b"exec-id",
                    executable=True,
                    text_size=30,
                    text_sha1=b"some-sha",
                    revision=b"old-rev",
                ),
            ),
        ]
        serializer = inventory_delta.InventoryDeltaSerializer(
            versioned_root=True, tree_references=True
        )
        lines = serializer.delta_to_lines(NULL_REVISION, b"something", delta)
        expected = b"""format: bzr inventory delta v1 (bzr 1.14)
parent: null:
version: something
versioned_root: true
tree_references: true
/\x00/old-root\x00TREE_ROOT\x00new-root-id\x00moved-root\x00dir
/dir\x00/old-root/dir\x00deep-id\x00TREE_ROOT\x00new-rev\x00dir
/dir/link\x00/old-root/dir/link\x00link-id\x00deep-id\x00new-rev\x00link\x00target
/old-file\x00None\x00deleted-id\x00\x00null:\x00deleted\x00\x00
/ref\x00/ref\x00ref-id\x00new-root-id\x00new-rev\x00tree\x00tree-reference-id
/under-old-root\x00/old-root/under-old-root\x00moved-id\x00TREE_ROOT\x00old-rev\x00file\x0030\x00\x00some-sha
None\x00/\x00new-root-id\x00\x00changed-in\x00dir
None\x00/configure\x00exec-id\x00new-root-id\x00old-rev\x00file\x0030\x00Y\x00some-sha
"""
        serialized = b"".join(lines)
        self.assertIsInstance(serialized, bytes)
        self.assertEqual(expected, serialized)


class TestContent(TestCase):
    """Test serialization of the content part of a line."""

    def test_dir(self):
        entry = inventory.make_entry("directory", "a dir", None)
        self.assertEqual(b"dir", inventory_delta._directory_content(entry))

    def test_file_0_short_sha(self):
        file_entry = inventory.make_entry("file", "a file", None, b"file-id")
        file_entry.text_sha1 = b""
        file_entry.text_size = 0
        self.assertEqual(
            b"file\x000\x00\x00", inventory_delta._file_content(file_entry)
        )

    def test_file_10_foo(self):
        file_entry = inventory.make_entry("file", "a file", None, b"file-id")
        file_entry.text_sha1 = b"foo"
        file_entry.text_size = 10
        self.assertEqual(
            b"file\x0010\x00\x00foo", inventory_delta._file_content(file_entry)
        )

    def test_file_executable(self):
        file_entry = inventory.make_entry("file", "a file", None, b"file-id")
        file_entry.executable = True
        file_entry.text_sha1 = b"foo"
        file_entry.text_size = 10
        self.assertEqual(
            b"file\x0010\x00Y\x00foo", inventory_delta._file_content(file_entry)
        )

    def test_file_without_size(self):
        file_entry = inventory.make_entry("file", "a file", None, b"file-id")
        file_entry.text_sha1 = b"foo"
        self.assertRaises(
            InventoryDeltaError, inventory_delta._file_content, file_entry
        )

    def test_file_without_sha1(self):
        file_entry = inventory.make_entry("file", "a file", None, b"file-id")
        file_entry.text_size = 10
        self.assertRaises(
            InventoryDeltaError, inventory_delta._file_content, file_entry
        )

    def test_link_empty_target(self):
        entry = inventory.make_entry("symlink", "a link", None)
        entry.symlink_target = ""
        self.assertEqual(b"link\x00", inventory_delta._link_content(entry))

    def test_link_unicode_target(self):
        entry = inventory.make_entry("symlink", "a link", None)
        entry.symlink_target = b" \xc3\xa5".decode("utf8")
        self.assertEqual(b"link\x00 \xc3\xa5", inventory_delta._link_content(entry))

    def test_link_space_target(self):
        entry = inventory.make_entry("symlink", "a link", None)
        entry.symlink_target = " "
        self.assertEqual(b"link\x00 ", inventory_delta._link_content(entry))

    def test_link_no_target(self):
        entry = inventory.make_entry("symlink", "a link", None)
        self.assertRaises(InventoryDeltaError, inventory_delta._link_content, entry)

    def test_reference_null(self):
        entry = inventory.make_entry("tree-reference", "a tree", None)
        entry.reference_revision = NULL_REVISION
        self.assertEqual(b"tree\x00null:", inventory_delta._reference_content(entry))

    def test_reference_revision(self):
        entry = inventory.make_entry("tree-reference", "a tree", None)
        entry.reference_revision = b"foo@\xc3\xa5b-lah"
        self.assertEqual(
            b"tree\x00foo@\xc3\xa5b-lah", inventory_delta._reference_content(entry)
        )

    def test_reference_no_reference(self):
        entry = inventory.make_entry("tree-reference", "a tree", None)
        self.assertRaises(
            InventoryDeltaError, inventory_delta._reference_content, entry
        )
