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

"""XML serialization format version 5 for inventories."""

from breezy._bzr_rs import revision_serializer_v5  # noqa: F401

from .. import errors
from . import inventory, xml6
from .xml_serializer import encode_and_escape, get_utf8_or_ascii, unpack_inventory_entry


class InventorySerializer_v5(xml6.InventorySerializer_v6):
    """Version 5 serializer.

    Packs objects into XML and vice versa.
    """

    format_num = b"5"
    root_id = inventory.ROOT_ID

    def _unpack_inventory(
        self, elt, revision_id, entry_cache=None, return_from_cache=False
    ):
        """Construct from XML Element."""
        root_id = elt.get("file_id") or inventory.ROOT_ID
        root_id = get_utf8_or_ascii(root_id)

        format = elt.get("format")
        if format is not None and format != "5":
            raise errors.BzrError(f"invalid format version {format!r} on inventory")
        data_revision_id = elt.get("revision_id")
        if data_revision_id is not None:
            revision_id = data_revision_id.encode("utf-8")
        inv = inventory.Inventory(root_id=None, revision_id=revision_id)
        root = inventory.InventoryDirectory(root_id, "", None, revision=revision_id)
        inv.add(root)

        # Optimizations tested
        #   baseline w/entry cache  2.85s
        #   using inv._byid         2.55s
        #   avoiding attributes     2.46s
        #   adding assertions       2.50s
        #   last_parent cache       2.52s (worse, removed)

        for e in elt:
            ie = unpack_inventory_entry(
                e,
                entry_cache=entry_cache,
                return_from_cache=return_from_cache,
                root_id=root_id,
            )
            inv.add(ie)
        self._check_cache_size(len(inv), entry_cache)
        return inv

    def _append_inventory_root(self, append, inv):
        """Append the inventory root to output."""
        if inv.root.file_id not in (None, inventory.ROOT_ID):
            fileid = b"".join(
                [b' file_id="', encode_and_escape(inv.root.file_id), b'"']
            )
        else:
            fileid = b""
        if inv.revision_id is not None:
            revid = b"".join(
                [b' revision_id="', encode_and_escape(inv.revision_id), b'"']
            )
        else:
            revid = b""
        append(b'<inventory%s format="5"%s>\n' % (fileid, revid))


inventory_serializer_v5 = InventorySerializer_v5()
