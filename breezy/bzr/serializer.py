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

from bzrformats.serializer import (
    BadInventoryFormat,  # noqa: F401
    InventorySerializer,
    RevisionSerializer,
    SerializerRegistry,
    UnexpectedInventoryFormat,  # noqa: F401
    UnsupportedInventoryKind,  # noqa: F401
)


class Serializer(InventorySerializer, RevisionSerializer):
    """Inventory and revision serialization/deserialization."""

    squashes_xml_invalid_characters = False


format_registry = SerializerRegistry()
format_registry.register_lazy("5", "bzrformats.xml5", "inventory_serializer_v5")
format_registry.register_lazy("6", "breezy.bzr.xml6", "serializer_v6")
format_registry.register_lazy("7", "breezy.bzr.xml7", "serializer_v7")
format_registry.register_lazy("8", "breezy.bzr.xml8", "serializer_v8")
format_registry.register_lazy(
    "9", "breezy.bzr.chk_serializer", "chk_serializer_255_bigpage"
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
