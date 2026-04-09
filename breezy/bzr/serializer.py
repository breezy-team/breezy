# Copyright (C) 2009, 2010 Canonical Ltd
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

"""Inventory/revision serialization."""

from .. import errors
from bzrformats.serializer import (
    InventorySerializer,
    RevisionSerializer,
    SerializerRegistry,
)


class BadInventoryFormat(errors.BzrError):
    """Base exception class for inventory serialization errors."""

    _fmt = "Root class for inventory serialization errors"


class UnexpectedInventoryFormat(BadInventoryFormat):
    """Raised when an inventory is not in the expected format."""

    _fmt = "The inventory was not in the expected format:\n %(msg)s"

    def __init__(self, msg):
        """Initialize UnexpectedInventoryFormat exception.

        Args:
            msg: Error message describing the unexpected format.
        """
        BadInventoryFormat.__init__(self, msg=msg)


class UnsupportedInventoryKind(errors.BzrError):
    """Raised when an unsupported inventory entry kind is encountered."""

    _fmt = """Unsupported entry kind %(kind)s"""

    def __init__(self, kind):
        """Initialize UnsupportedInventoryKind exception.

        Args:
            kind: The unsupported entry kind.
        """
        self.kind = kind


class Serializer(InventorySerializer, RevisionSerializer):
    """Inventory and revision serialization/deserialization."""

    squashes_xml_invalid_characters = False


revision_format_registry = SerializerRegistry()
revision_format_registry.register_lazy("5", "breezy._bzr_rs", "revision_serializer_v5")
revision_format_registry.register_lazy("8", "breezy._bzr_rs", "revision_serializer_v8")
revision_format_registry.register_lazy(
    "10", "breezy._bzr_rs", "revision_bencode_serializer"
)


inventory_format_registry = SerializerRegistry()
inventory_format_registry.register_lazy(
    "5", "breezy.bzr.xml5", "inventory_serializer_v5"
)
inventory_format_registry.register_lazy(
    "6", "breezy.bzr.xml6", "inventory_serializer_v6"
)
inventory_format_registry.register_lazy(
    "7", "breezy.bzr.xml7", "inventory_serializer_v7"
)
inventory_format_registry.register_lazy(
    "8", "breezy.bzr.xml8", "inventory_serializer_v8"
)
inventory_format_registry.register_lazy(
    "9", "breezy.bzr.chk_serializer", "inventory_chk_serializer_255_bigpage_9"
)
inventory_format_registry.register_lazy(
    "10", "breezy.bzr.chk_serializer", "inventory_chk_serializer_255_bigpage_10"
)
