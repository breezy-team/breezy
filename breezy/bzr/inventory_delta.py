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

InventoryDeltaError = _inventory_delta_rs.InventoryDeltaError
IncompatibleInventoryDelta = _inventory_delta_rs.IncompatibleInventoryDelta
parse_inventory_entry = _inventory_delta_rs.parse_inventory_entry
serialize_inventory_entry = _inventory_delta_rs.serialize_inventory_entry
InventoryDelta = _inventory_delta_rs.InventoryDelta


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
