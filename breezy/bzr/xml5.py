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

from .. import errors, osutils
from bzrformats import inventory
from . import xml6
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
        inv = inventory.Inventory(root_id, revision_id=revision_id)
        if revision_id is not None:
            # Replace root with one that has revision set
            inv.delete(root_id)
            inv.add(inventory.InventoryDirectory(root_id, "", None, revision=revision_id))
        for e in elt:
            ie = unpack_inventory_entry(
                e,
                entry_cache=entry_cache,
                return_from_cache=return_from_cache,
                root_id=root_id,
            )
            parent_id = ie.parent_id
            if parent_id is None:
                parent_id = root_id
                ie = type(ie)(ie.file_id, ie.name, root_id, revision=ie.revision)
            if not inv.has_id(parent_id):
                raise errors.BzrError(
                    "parent_id {{{}}} not in inventory".format(parent_id)
                )
            inv.add(ie)
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
