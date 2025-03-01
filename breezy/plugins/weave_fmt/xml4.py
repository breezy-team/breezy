# Copyright (C) 2005-2010 Canonical Ltd
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

from typing import List

from ...bzr import inventory
from ...bzr.inventory import ROOT_ID, Inventory
from ...bzr.xml_serializer import (
    Element,
    SubElement,
    XMLSerializer,
    escape_invalid_chars,
)
from ...errors import BzrError
from ...revision import Revision


class _Serializer_v4(XMLSerializer):
    """Version 0.0.4 serializer.

    You should use the serializer_v4 singleton.

    v4 serialisation is no longer supported, only deserialisation.
    """

    __slots__: List[str] = []

    def _pack_entry(self, ie):
        """Convert InventoryEntry to XML element."""
        e = Element("entry")
        e.set("name", ie.name)
        e.set("file_id", ie.file_id.decode("ascii"))
        e.set("kind", ie.kind)

        if ie.text_size is not None:
            e.set("text_size", "%d" % ie.text_size)

        for f in ["text_id", "text_sha1", "symlink_target"]:
            v = getattr(ie, f)
            if v is not None:
                e.set(f, v)

        # to be conservative, we don't externalize the root pointers
        # for now, leaving them as null in the xml form.  in a future
        # version it will be implied by nested elements.
        if ie.parent_id != ROOT_ID:
            e.set("parent_id", ie.parent_id)

        e.tail = "\n"

        return e

    def _unpack_inventory(
        self, elt, revision_id=None, entry_cache=None, return_from_cache=False
    ):
        """Construct from XML Element.

        :param revision_id: Ignored parameter used by xml5.
        """
        root_id = elt.get("file_id")
        root_id = root_id.encode("ascii") if root_id else ROOT_ID
        inv = Inventory(root_id)
        for e in elt:
            ie = self._unpack_entry(
                e, entry_cache=entry_cache, return_from_cache=return_from_cache
            )
            if ie.parent_id == ROOT_ID:
                ie.parent_id = root_id
            inv.add(ie)
        return inv

    def _unpack_entry(self, elt, entry_cache=None, return_from_cache=False):
        # original format inventories don't have a parent_id for
        # nodes in the root directory, but it's cleaner to use one
        # internally.
        parent_id = elt.get("parent_id")
        parent_id = parent_id.encode("ascii") if parent_id else ROOT_ID

        file_id = elt.get("file_id").encode("ascii")
        kind = elt.get("kind")
        if kind == "directory":
            ie = inventory.InventoryDirectory(file_id, elt.get("name"), parent_id)
        elif kind == "file":
            ie = inventory.InventoryFile(file_id, elt.get("name"), parent_id)
            ie.text_id = elt.get("text_id")
            if ie.text_id is not None:
                ie.text_id = ie.text_id.encode("utf-8")
            ie.text_sha1 = elt.get("text_sha1")
            if ie.text_sha1 is not None:
                ie.text_sha1 = ie.text_sha1.encode("ascii")
            v = elt.get("text_size")
            ie.text_size = v and int(v)
        elif kind == "symlink":
            ie = inventory.InventoryLink(file_id, elt.get("name"), parent_id)
            ie.symlink_target = elt.get("symlink_target")
        else:
            raise BzrError("unknown kind {!r}".format(kind))

        ## mutter("read inventoryentry: %r", elt.attrib)

        return ie

    def _pack_revision(self, rev):
        """Revision object -> xml tree."""
        root = Element(
            "revision",
            committer=rev.committer,
            timestamp="{:.9f}".format(rev.timestamp),
            revision_id=rev.revision_id,
            inventory_id=rev.inventory_id,
            inventory_sha1=rev.inventory_sha1,
        )
        if rev.timezone:
            root.set("timezone", str(rev.timezone))
        root.text = "\n"

        msg = SubElement(root, "message")
        msg.text = escape_invalid_chars(rev.message)[0]
        msg.tail = "\n"

        if rev.parents:
            pelts = SubElement(root, "parents")
            pelts.tail = pelts.text = "\n"
            for i, parent_id in enumerate(rev.parents):
                p = SubElement(pelts, "revision_ref")
                p.tail = "\n"
                p.set("revision_id", parent_id)
                if i < len(rev.parent_sha1s):
                    p.set("revision_sha1", rev.parent_sha1s[i])
        return root

    def write_revision_to_string(self, rev):
        return tostring(self._pack_revision(rev)) + b"\n"

    def _write_element(self, elt, f):
        ElementTree(elt).write(f, "utf-8")
        f.write(b"\n")

    def _unpack_revision(self, elt):
        """XML Element -> Revision object."""
        # <changeset> is deprecated...
        if elt.tag not in ("revision", "changeset"):
            raise BzrError("unexpected tag in revision file: {!r}".format(elt))

        rev = Revision(
            committer=elt.get("committer"),
            timestamp=float(elt.get("timestamp")),
            revision_id=elt.get("revision_id"),
            inventory_id=elt.get("inventory_id"),
            inventory_sha1=elt.get("inventory_sha1"),
        )

        precursor = elt.get("precursor")
        precursor_sha1 = elt.get("precursor_sha1")

        pelts = elt.find("parents")

        if pelts is not None:
            for p in pelts:
                rev.parent_ids.append(p.get("revision_id"))
                rev.parent_sha1s.append(p.get("revision_sha1"))
            if precursor:
                # must be consistent
                rev.parent_ids[0]
        elif precursor:
            # revisions written prior to 0.0.5 have a single precursor
            # give as an attribute
            rev.parent_ids.append(precursor)
            rev.parent_sha1s.append(precursor_sha1)

        v = elt.get("timezone")
        rev.timezone = v and int(v)

        rev.message = elt.findtext("message")  # text of <message>
        return rev


"""singleton instance"""
serializer_v4 = _Serializer_v4()
