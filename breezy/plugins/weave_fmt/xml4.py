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

"""XML serialization support for weave format version 4."""

from ... import revision as _mod_revision
from ...bzr import inventory
from ...bzr.inventory import ROOT_ID, Inventory
from ...bzr.xml_serializer import (
    Element,
    SubElement,
    XMLInventorySerializer,
    XMLRevisionSerializer,
    escape_invalid_chars,
)
from ...errors import BzrError


class Revision(_mod_revision.Revision):
    """Revision class with additional v4-specific attributes."""

    def __new__(cls, *args, **kwargs):
        """Create new Revision instance with inventory_id and parent_sha1s.

        Args:
            *args: Positional arguments passed to parent class.
            **kwargs: Keyword arguments, including inventory_id and parent_sha1s.

        Returns:
            New Revision instance with additional attributes.
        """
        inventory_id = kwargs.pop("inventory_id", None)
        parent_sha1s = kwargs.pop("parent_sha1s", None)
        self = _mod_revision.Revision.__new__(cls, *args, **kwargs)
        self.inventory_id = inventory_id
        self.parent_sha1s = parent_sha1s
        return self


class _RevisionSerializer_v4(XMLRevisionSerializer):
    """Version 0.0.4 serializer.

    You should use the revision_serializer_v4 singleton.

    v4 serialisation is no longer supported, only deserialisation.
    """

    __slots__: list[str] = []

    def _pack_revision(self, rev):
        """Revision object -> xml tree."""
        root = Element(
            "revision",
            committer=rev.committer,
            timestamp=f"{rev.timestamp:.9f}",
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
            raise BzrError(f"unexpected tag in revision file: {elt!r}")

        v = elt.get("timezone")
        timezone = v and int(v)

        message = elt.findtext("message")  # text of <message>

        precursor = elt.get("precursor")
        precursor_sha1 = elt.get("precursor_sha1")

        pelts = elt.find("parents")

        parent_ids = []
        parent_sha1s = []

        if pelts:
            for p in pelts:
                parent_ids.append(p.get("revision_id").encode("utf-8"))
                parent_sha1s.append(
                    p.get("revision_sha1").encode("utf-8")
                    if p.get("revision_sha1")
                    else None
                )
            if precursor:
                # must be consistent
                parent_ids[0]
        elif precursor:
            # revisions written prior to 0.0.5 have a single precursor
            # give as an attribute
            parent_ids.append(precursor)
            parent_sha1s.append(precursor_sha1)

        return Revision(
            committer=elt.get("committer"),
            timestamp=float(elt.get("timestamp")),
            revision_id=elt.get("revision_id").encode("utf-8"),
            inventory_id=elt.get("inventory_id").encode("utf-8"),
            inventory_sha1=elt.get("inventory_sha1").encode("utf-8"),
            timezone=timezone,
            message=message,
            parent_ids=parent_ids,
            parent_sha1s=parent_sha1s,
            properties={},
        )


class _InventorySerializer_v4(XMLInventorySerializer):
    """Version 0.0.4 serializer.

    You should use the inventory_serializer_v4 singleton.

    v4 serialisation is no longer supported, only deserialisation.
    """

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
                e,
                entry_cache=entry_cache,
                return_from_cache=return_from_cache,
                root_id=root_id,
            )
            inv.add(ie)
        return inv

    def _unpack_entry(self, elt, root_id, entry_cache=None, return_from_cache=False):
        # original format inventories don't have a parent_id for
        # nodes in the root directory, but it's cleaner to use one
        # internally.
        parent_id = elt.get("parent_id")
        parent_id = parent_id.encode("ascii") if parent_id else ROOT_ID
        if parent_id == ROOT_ID:
            parent_id = root_id
        file_id = elt.get("file_id").encode("ascii")
        kind = elt.get("kind")
        if kind == "directory":
            ie = inventory.InventoryDirectory(file_id, elt.get("name"), parent_id)
        elif kind == "file":
            text_id = elt.get("text_id")
            if text_id is not None:
                text_id = text_id.encode("utf-8")
            text_sha1 = elt.get("text_sha1")
            if text_sha1 is not None:
                text_sha1 = text_sha1.encode("ascii")
            v = elt.get("text_size")
            text_size = v and int(v)

            ie = inventory.InventoryFile(
                file_id,
                elt.get("name"),
                parent_id,
                text_size=text_size,
                text_sha1=text_sha1,
                text_id=text_id,
            )
        elif kind == "symlink":
            ie = inventory.InventoryLink(
                file_id,
                elt.get("name"),
                parent_id,
                symlink_target=elt.get("symlink_target"),
            )
        else:
            raise BzrError(f"unknown kind {kind!r}")

        ## mutter("read inventoryentry: %r", elt.attrib)

        return ie


revision_serializer_v4 = _RevisionSerializer_v4()
inventory_serializer_v4 = _InventorySerializer_v4()
