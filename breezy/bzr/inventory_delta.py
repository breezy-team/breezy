# Copyright (C) 2008, 2009 Canonical Ltd
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

"""Inventory delta serialisation.

See doc/developers/inventory.txt for the description of the format.

In this module the interesting classes are:
 - InventoryDeltaSerializer - object to read/write inventory deltas.
"""

__all__ = ["InventoryDeltaSerializer"]

from .._bzr_rs import inventory as _inventory_delta_rs
from ..revision import RevisionID

FORMAT_1 = b"bzr inventory delta v1 (bzr 1.14)"


class InventoryDeltaError(errors.BzrError):
    """An error when serializing or deserializing an inventory delta."""

    # Most errors when serializing and deserializing are due to bugs, although
    # damaged input (i.e. a bug in a different process) could cause
    # deserialization errors too.
    internal_error = True

    def __init__(self, format_string, **kwargs):
        # Let each error supply a custom format string and arguments.
        self._fmt = format_string
        super().__init__(**kwargs)


class IncompatibleInventoryDelta(errors.BzrError):
    """The delta could not be deserialised because its contents conflict with
    the allow_versioned_root or allow_tree_references flags of the
    deserializer.
    """

    internal_error = False


def _directory_content(entry):
    """Serialize the content component of entry which is a directory.

    :param entry: An InventoryDirectory.
    """
    return b"dir"


def _file_content(entry):
    """Serialize the content component of entry which is a file.

    :param entry: An InventoryFile.
    """
    if entry.executable:
        exec_bytes = b"Y"
    else:
        exec_bytes = b""
    size_exec_sha = entry.text_size, exec_bytes, entry.text_sha1
    if None in size_exec_sha:
        raise InventoryDeltaError(
            "Missing size or sha for %(fileid)r", fileid=entry.file_id
        )
    return b"file\x00%d\x00%s\x00%s" % size_exec_sha


def _link_content(entry):
    """Serialize the content component of entry which is a symlink.

    :param entry: An InventoryLink.
    """
    target = entry.symlink_target
    if target is None:
        raise InventoryDeltaError("Missing target for %(fileid)r", fileid=entry.file_id)
    return b"link\x00%s" % target.encode("utf8")


def _reference_content(entry):
    """Serialize the content component of entry which is a tree-reference.

    :param entry: A TreeReference.
    """
    tree_revision = entry.reference_revision
    if tree_revision is None:
        raise InventoryDeltaError(
            "Missing reference revision for %(fileid)r", fileid=entry.file_id
        )
    return b"tree\x00%s" % tree_revision


def _dir_to_entry(
    content, name, parent_id, file_id, last_modified, _type=inventory.InventoryDirectory
):
    """Convert a dir content record to an InventoryDirectory."""
    return _type(file_id, name, parent_id, revision=last_modified)


def _file_to_entry(
    content, name, parent_id, file_id, last_modified, _type=inventory.InventoryFile
):
    """Convert a dir content record to an InventoryFile."""
    return _type(
        file_id,
        name,
        parent_id,
        revision=last_modified,
        text_size=int(content[1]),
        text_sha1=content[3],
        executable=bool(content[2]),
    )


def _link_to_entry(
    content, name, parent_id, file_id, last_modified, _type=inventory.InventoryLink
):
    """Convert a link content record to an InventoryLink."""
    return _type(
        file_id,
        name,
        parent_id,
        revision=last_modified,
        symlink_target=content[1].decode("utf8"),
    )


def _tree_to_entry(
    content, name, parent_id, file_id, last_modified, _type=inventory.TreeReference
):
    """Convert a tree content record to a TreeReference."""
    return _type(
        file_id, name, parent_id, revision=last_modified, reference_revision=content[1]
    )


class InventoryDeltaSerializer:
    """Serialize inventory deltas."""

    def __init__(self, versioned_root, tree_references):
        """Create an InventoryDeltaSerializer.

        :param versioned_root: If True, any root entry that is seen is expected
            to be versioned, and root entries can have any fileid.
        :param tree_references: If True support tree-reference entries.
        """
        self._versioned_root = versioned_root
        self._tree_references = tree_references

    def delta_to_lines(
        self,
        old_name: RevisionID,
        new_name: RevisionID,
        delta_to_new: _inventory_delta_rs.InventoryDelta,
    ):
        """Return a line sequence for delta_to_new.

        Both the versioned_root and tree_references flags must be set via
        require_flags before calling this.

        :param old_name: A UTF8 revision id for the old inventory.  May be
            NULL_REVISION if there is no older inventory and delta_to_new
            includes the entire inventory contents.
        :param new_name: The version name of the inventory we create with this
            delta.
        :param delta_to_new: An inventory delta such as Inventory.apply_delta
            takes.
        :return: The serialized delta as lines.
        """
        return _inventory_delta_rs.serialize_inventory_delta(
            old_name,
            new_name,
            delta_to_new,
            self._versioned_root,
            self._tree_references,
        )


class InventoryDeltaDeserializer:
    """Deserialize inventory deltas."""

    def __init__(self, allow_versioned_root=True, allow_tree_references=True):
        """Create an InventoryDeltaDeserializer.

        :param versioned_root: If True, any root entry that is seen is expected
            to be versioned, and root entries can have any fileid.
        :param tree_references: If True support tree-reference entries.
        """
        self._allow_versioned_root = allow_versioned_root
        self._allow_tree_references = allow_tree_references

    def parse_text_bytes(self, lines):
        """Parse the text bytes of a serialized inventory delta.

        If versioned_root and/or tree_references flags were set via
        require_flags, then the parsed flags must match or a BzrError will be
        raised.

        :param lines: The lines to parse. This can be obtained by calling
            delta_to_lines.
        :return: (parent_id, new_id, versioned_root, tree_references,
            inventory_delta)
        """
        return _inventory_delta_rs.parse_inventory_delta(
            lines, self._allow_versioned_root, self._allow_tree_references
        )
