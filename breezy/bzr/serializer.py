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

from .. import errors, registry


class BadInventoryFormat(errors.BzrError):

    _fmt = "Root class for inventory serialization errors"


class UnexpectedInventoryFormat(BadInventoryFormat):

    _fmt = "The inventory was not in the expected format:\n %(msg)s"

    def __init__(self, msg):
        BadInventoryFormat.__init__(self, msg=msg)


class UnsupportedInventoryKind(errors.BzrError):

    _fmt = """Unsupported entry kind %(kind)s"""

    def __init__(self, kind):
        self.kind = kind


class Serializer(object):
    """Inventory and revision serialization/deserialization."""

    squashes_xml_invalid_characters = False

    def write_inventory(self, inv, f):
        """Write inventory to a file.

        Note: this is a *whole inventory* operation, and should only be used
        sparingly, as it does not scale well with large trees.
        """
        raise NotImplementedError(self.write_inventory)

    def write_inventory_to_chunks(self, inv):
        """Produce a simple bytestring chunk representation of an inventory.

        Note: this is a *whole inventory* operation, and should only be used
        sparingly, as it does not scale well with large trees.

        The requirement for the contents of the string is that it can be passed
        to read_inventory_from_lines and the result is an identical inventory
        in memory.
        """
        raise NotImplementedError(self.write_inventory_to_chunks)

    def write_inventory_to_lines(self, inv):
        """Produce a simple lines representation of an inventory.

        Note: this is a *whole inventory* operation, and should only be used
        sparingly, as it does not scale well with large trees.

        The requirement for the contents of the string is that it can be passed
        to read_inventory_from_lines and the result is an identical inventory
        in memory.
        """
        raise NotImplementedError(self.write_inventory_to_lines)

    def read_inventory_from_lines(self, lines, revision_id=None,
                                  entry_cache=None, return_from_cache=False):
        """Read bytestring chunks into an inventory object.

        :param lines: The serialized inventory to read.
        :param revision_id: If not-None, the expected revision id of the
            inventory. Some serialisers use this to set the results' root
            revision. This should be supplied for deserialising all
            from-repository inventories so that xml5 inventories that were
            serialised without a revision identifier can be given the right
            revision id (but not for working tree inventories where users can
            edit the data without triggering checksum errors or anything).
        :param entry_cache: An optional cache of InventoryEntry objects. If
            supplied we will look up entries via (file_id, revision_id) which
            should map to a valid InventoryEntry (File/Directory/etc) object.
        :param return_from_cache: Return entries directly from the cache,
            rather than copying them first. This is only safe if the caller
            promises not to mutate the returned inventory entries, but it can
            make some operations significantly faster.
        """
        raise NotImplementedError(self.read_inventory_from_lines)

    def read_inventory(self, f, revision_id=None):
        """See read_inventory_from_lines."""
        raise NotImplementedError(self.read_inventory)

    def write_revision_to_string(self, rev):
        raise NotImplementedError(self.write_revision_to_string)

    def write_revision_to_lines(self, rev):
        raise NotImplementedError(self.write_revision_to_lines)

    def read_revision(self, f):
        raise NotImplementedError(self.read_revision)

    def read_revision_from_string(self, xml_string):
        raise NotImplementedError(self.read_revision_from_string)


class SerializerRegistry(registry.Registry):
    """Registry for serializer objects"""


format_registry = SerializerRegistry()
format_registry.register_lazy('5', 'breezy.bzr.xml5', 'serializer_v5')
format_registry.register_lazy('6', 'breezy.bzr.xml6', 'serializer_v6')
format_registry.register_lazy('7', 'breezy.bzr.xml7', 'serializer_v7')
format_registry.register_lazy('8', 'breezy.bzr.xml8', 'serializer_v8')
format_registry.register_lazy('9', 'breezy.bzr.chk_serializer',
                              'chk_serializer_255_bigpage')
format_registry.register_lazy('10', 'breezy.bzr.chk_serializer',
                              'chk_bencode_serializer')
