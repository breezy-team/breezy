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

"""XML externalization support."""

# "XML is like violence: if it doesn't solve your problem, you aren't
# using enough of it." -- various

# importing this module is fairly slow because it has to load several
# ElementTree bits

__all__ = [
    "Element",
    "ElementTree",
    "SubElement",
    "escape_invalid_chars",
    "fromstring",
    "fromstringlist",
    "get_utf8_or_ascii",
    "serialize_inventory_flat",
    "tostring",
    "tostringlist",
    "unpack_inventory_entry",
    "unpack_inventory_flat",
]

import re
from xml.etree.ElementTree import (  # noqa: F401
    Element,
    ElementTree,
    ParseError,
    SubElement,
    fromstring,
    fromstringlist,
    tostring,
    tostringlist,
)

from bzrformats.xml_serializer import (
    XMLInventorySerializer,
    XMLRevisionSerializer,
    encode_and_escape,  # noqa: F401
    get_utf8_or_ascii,  # noqa: F401
)

from . import inventory, serializer


class XMLSerializer(XMLInventorySerializer, XMLRevisionSerializer):
    """Combined XML inventory and revision serialize/deserialize."""


def escape_invalid_chars(message):
    """Escape the XML-invalid characters in a commit message.

    :param message: Commit message to escape
    :return: tuple with escaped message and number of characters escaped
    """
    if message is None:
        return None, 0
    return re.subn(
        "[^\x09\x0a\x0d\u0020-\ud7ff\ue000-\ufffd]+",
        lambda match: match.group(0).encode("unicode_escape").decode("ascii"),
        message,
    )


def _clear_cache():
    """No-op, cache is managed by bzrformats Rust code."""


def unpack_inventory_entry(elt, entry_cache=None, return_from_cache=False):
    elt_get = elt.get
    file_id = elt_get("file_id")
    revision = elt_get("revision")
    if entry_cache is not None and revision is not None:
        key = (file_id, revision)
        try:
            cached_ie = entry_cache[key]
        except KeyError:
            pass
        else:
            if return_from_cache:
                if cached_ie.kind == "directory":
                    return cached_ie.copy()
                return cached_ie
            return cached_ie.copy()

    kind = elt.tag
    if not inventory.InventoryEntry.versionable_kind(kind):
        raise AssertionError(f"unsupported entry kind {kind}")

    file_id = get_utf8_or_ascii(file_id)
    if revision is not None:
        revision = get_utf8_or_ascii(revision)
    parent_id = elt_get("parent_id")
    parent_id = get_utf8_or_ascii(parent_id) if parent_id is not None else root_id

    if kind == "directory":
        ie = inventory.InventoryDirectory(file_id, elt_get("name"), parent_id, revision)
    elif kind == "file":
        text_sha1 = elt_get("text_sha1")
        if text_sha1 is not None:
            text_sha1 = text_sha1.encode("ascii")
        executable = elt_get("executable") == "yes"
        v = elt_get("text_size")
        text_size = v and int(v)
        ie = inventory.InventoryFile(
            file_id,
            elt_get("name"),
            parent_id,
            revision,
            text_sha1=text_sha1,
            executable=executable,
            text_size=text_size,
        )
    elif kind == "symlink":
        symlink_target = elt_get("symlink_target")
        ie = inventory.InventoryLink(
            file_id, elt_get("name"), parent_id, revision, symlink_target=symlink_target
        )
    elif kind == "tree-reference":
        file_id = get_utf8_or_ascii(elt.attrib["file_id"])
        name = elt.attrib["name"]
        parent_id = get_utf8_or_ascii(elt.attrib["parent_id"])
        revision = get_utf8_or_ascii(elt.get("revision"))
        reference_revision = get_utf8_or_ascii(elt.get("reference_revision"))
        ie = inventory.TreeReference(
            file_id, name, parent_id, revision, reference_revision
        )
    else:
        raise serializer.UnsupportedInventoryKind(kind)
    if revision is not None and entry_cache is not None:
        entry_cache[key] = ie.copy()

    return ie


def unpack_inventory_flat(
    elt, format_num, unpack_entry, entry_cache=None, return_from_cache=False
):
    """Unpack a flat XML inventory."""
    if elt.tag != "inventory":
        raise serializer.UnexpectedInventoryFormat(f"Root tag is {elt.tag!r}")
    format = elt.get("format")
    if (format is None and format_num is not None) or format.encode() != format_num:
        raise serializer.UnexpectedInventoryFormat(f"Invalid format version {format!r}")
    revision_id = elt.get("revision_id")
    if revision_id is not None:
        revision_id = revision_id.encode("utf-8")
    inv = inventory.Inventory(root_id=None, revision_id=revision_id)
    for e in elt:
        ie = unpack_entry(e, entry_cache, return_from_cache)
        inv.add(ie)
    return inv


def serialize_inventory_flat(inv, append, root_id, supported_kinds, working):
    """Serialize an inventory to a flat XML file."""
    entries = inv.iter_entries()
    # Skip the root
    _root_path, _root_ie = next(entries)
    for _path, ie in entries:
        if ie.parent_id != root_id:
            parent_str = b"".join(
                [b' parent_id="', encode_and_escape(ie.parent_id), b'"']
            )
        else:
            parent_str = b""
        if ie.kind == "file":
            executable = b' executable="yes"' if ie.executable else b""
            if not working:
                append(
                    b'<file%s file_id="%s" name="%s"%s revision="%s" '
                    b'text_sha1="%s" text_size="%d" />\n'
                    % (
                        executable,
                        encode_and_escape(ie.file_id),
                        encode_and_escape(ie.name),
                        parent_str,
                        encode_and_escape(ie.revision),
                        ie.text_sha1,
                        ie.text_size,
                    )
                )
            else:
                append(
                    b'<file%s file_id="%s" name="%s"%s />\n'
                    % (
                        executable,
                        encode_and_escape(ie.file_id),
                        encode_and_escape(ie.name),
                        parent_str,
                    )
                )
        elif ie.kind == "directory":
            if not working:
                append(
                    b'<directory file_id="%s" name="%s"%s revision="%s" '
                    b"/>\n"
                    % (
                        encode_and_escape(ie.file_id),
                        encode_and_escape(ie.name),
                        parent_str,
                        encode_and_escape(ie.revision),
                    )
                )
            else:
                append(
                    b'<directory file_id="%s" name="%s"%s />\n'
                    % (
                        encode_and_escape(ie.file_id),
                        encode_and_escape(ie.name),
                        parent_str,
                    )
                )
        elif ie.kind == "symlink":
            if not working:
                append(
                    b'<symlink file_id="%s" name="%s"%s revision="%s" '
                    b'symlink_target="%s" />\n'
                    % (
                        encode_and_escape(ie.file_id),
                        encode_and_escape(ie.name),
                        parent_str,
                        encode_and_escape(ie.revision),
                        encode_and_escape(ie.symlink_target),
                    )
                )
            else:
                append(
                    b'<symlink file_id="%s" name="%s"%s />\n'
                    % (
                        encode_and_escape(ie.file_id),
                        encode_and_escape(ie.name),
                        parent_str,
                    )
                )
        elif ie.kind == "tree-reference":
            if ie.kind not in supported_kinds:
                raise serializer.UnsupportedInventoryKind(ie.kind)
            if not working:
                append(
                    b'<tree-reference file_id="%s" name="%s"%s '
                    b'revision="%s" reference_revision="%s" />\n'
                    % (
                        encode_and_escape(ie.file_id),
                        encode_and_escape(ie.name),
                        parent_str,
                        encode_and_escape(ie.revision),
                        encode_and_escape(ie.reference_revision),
                    )
                )
            else:
                append(
                    b'<tree-reference file_id="%s" name="%s"%s />\n'
                    % (
                        encode_and_escape(ie.file_id),
                        encode_and_escape(ie.name),
                        parent_str,
                    )
                )
        else:
            raise serializer.UnsupportedInventoryKind(ie.kind)
    append(b"</inventory>\n")
