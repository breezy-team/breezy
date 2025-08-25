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

from . import serializer


class CHKSerializer(serializer.InventorySerializer):
    """A CHKInventory based serializer with 'plain' behaviour."""

    support_altered_by_hack = False
    supported_kinds = {"file", "directory", "symlink", "tree-reference"}

    def __init__(self, format_num, node_size, search_key_name):
        """Initialize a CHKSerializer instance.

        Args:
            format_num: The format number for the serializer (e.g., b"9" or b"10").
            node_size: The maximum size for CHK nodes (typically 65536).
            search_key_name: The name of the search key algorithm (e.g., b"hash-255-way").
        """
        self.format_num = format_num
        self.maximum_size = node_size
        self.search_key_name = search_key_name

    def _unpack_inventory(
        self, elt, revision_id=None, entry_cache=None, return_from_cache=False
    ):
        """Construct from XML Element."""
        from .xml_serializer import unpack_inventory_entry, unpack_inventory_flat

        inv = unpack_inventory_flat(
            elt, self.format_num, unpack_inventory_entry, entry_cache, return_from_cache
        )
        return inv

    def read_inventory_from_lines(
        self, xml_lines, revision_id=None, entry_cache=None, return_from_cache=False
    ):
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
        from .xml_serializer import ParseError, fromstringlist

        try:
            return self._unpack_inventory(
                fromstringlist(xml_lines),
                revision_id,
                entry_cache=entry_cache,
                return_from_cache=return_from_cache,
            )
        except ParseError as e:
            raise serializer.UnexpectedInventoryFormat(e) from e

    def read_inventory(self, f, revision_id=None):
        """Read an inventory from a file-like object."""
        from .xml_serializer import ParseError

        try:
            try:
                return self._unpack_inventory(self._read_element(f), revision_id=None)
            finally:
                f.close()
        except ParseError as e:
            raise serializer.UnexpectedInventoryFormat(e) from e

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
        from .xml_serializer import encode_and_escape, serialize_inventory_flat

        output = []
        append = output.append
        if inv.revision_id is not None:
            revid = b"".join(
                [b' revision_id="', encode_and_escape(inv.revision_id), b'"']
            )
        else:
            revid = b""
        append(b'<inventory format="%s"%s>\n' % (self.format_num, revid))
        append(
            b'<directory file_id="%s" name="%s" revision="%s" />\n'
            % (
                encode_and_escape(inv.root.file_id),
                encode_and_escape(inv.root.name),
                encode_and_escape(inv.root.revision),
            )
        )
        serialize_inventory_flat(
            inv,
            append,
            root_id=None,
            supported_kinds=self.supported_kinds,
            working=working,
        )
        if f is not None:
            f.writelines(output)
        return output


# A CHKInventory based serializer with 'plain' behaviour.
inventory_chk_serializer_255_bigpage_9 = CHKSerializer(b"9", 65536, b"hash-255-way")
inventory_chk_serializer_255_bigpage_10 = CHKSerializer(b"10", 65536, b"hash-255-way")
