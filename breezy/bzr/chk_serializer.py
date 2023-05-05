# Copyright (C) 2008, 2009, 2010 Canonical Ltd
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

"""Serializer object for CHK based inventory storage."""

from .. import lazy_import

lazy_import.lazy_import(globals(),
                        """
from breezy.bzr import (
    xml_serializer,
    )
""")
from . import serializer


class CHKSerializer(serializer.InventorySerializer):
    """A CHKInventory based serializer with 'plain' behaviour."""

    support_altered_by_hack = False
    supported_kinds = {'file', 'directory', 'symlink', 'tree-reference'}

    def __init__(self, format_num, node_size, search_key_name):
        self.format_num = format_num
        self.maximum_size = node_size
        self.search_key_name = search_key_name

    def _unpack_inventory(self, elt, revision_id=None, entry_cache=None,
                          return_from_cache=False):
        """Construct from XML Element"""
        inv = xml_serializer.unpack_inventory_flat(elt, self.format_num,
                                                   xml_serializer.unpack_inventory_entry, entry_cache,
                                                   return_from_cache)
        return inv

    def read_inventory_from_lines(self, xml_lines, revision_id=None,
                                  entry_cache=None, return_from_cache=False):
        """Read xml_string into an inventory object.

        :param xml_string: The xml to read.
        :param revision_id: If not-None, the expected revision id of the
            inventory.
        :param entry_cache: An optional cache of InventoryEntry objects. If
            supplied we will look up entries via (file_id, revision_id) which
            should map to a valid InventoryEntry (File/Directory/etc) object.
        :param return_from_cache: Return entries directly from the cache,
            rather than copying them first. This is only safe if the caller
            promises not to mutate the returned inventory entries, but it can
            make some operations significantly faster.
        """
        try:
            return self._unpack_inventory(
                xml_serializer.fromstringlist(xml_lines), revision_id,
                entry_cache=entry_cache,
                return_from_cache=return_from_cache)
        except xml_serializer.ParseError as e:
            raise serializer.UnexpectedInventoryFormat(e)

    def read_inventory(self, f, revision_id=None):
        """Read an inventory from a file-like object."""
        try:
            try:
                return self._unpack_inventory(self._read_element(f),
                                              revision_id=None)
            finally:
                f.close()
        except xml_serializer.ParseError as e:
            raise serializer.UnexpectedInventoryFormat(e)

    def write_inventory_to_lines(self, inv):
        """Return a list of lines with the encoded inventory."""
        return self.write_inventory(inv, None)

    def write_inventory_to_chunks(self, inv):
        """Return a list of lines with the encoded inventory."""
        return self.write_inventory(inv, None)

    def write_inventory(self, inv, f, working=False):
        """Write inventory to a file.

        :param inv: the inventory to write.
        :param f: the file to write. (May be None if the lines are the desired
            output).
        :param working: If True skip history data - text_sha1, text_size,
            reference_revision, symlink_target.
        :return: The inventory as a list of lines.
        """
        output = []
        append = output.append
        if inv.revision_id is not None:
            revid = b''.join(
                [b' revision_id="',
                 xml_serializer.encode_and_escape(inv.revision_id), b'"'])
        else:
            revid = b""
        append(b'<inventory format="%s"%s>\n' % (
            self.format_num, revid))
        append(b'<directory file_id="%s" name="%s" revision="%s" />\n' % (
            xml_serializer.encode_and_escape(inv.root.file_id),
            xml_serializer.encode_and_escape(inv.root.name),
            xml_serializer.encode_and_escape(inv.root.revision)))
        xml_serializer.serialize_inventory_flat(inv,
                                                append,
                                                root_id=None, supported_kinds=self.supported_kinds,
                                                working=working)
        if f is not None:
            f.writelines(output)
        return output


# A CHKInventory based serializer with 'plain' behaviour.
inventory_chk_serializer_255_bigpage_9 = CHKSerializer(b'9', 65536, b'hash-255-way')
inventory_chk_serializer_255_bigpage_10 = CHKSerializer(b'10', 65536, b'hash-255-way')
