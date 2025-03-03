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

import fastbencode as bencode

from .. import lazy_import

lazy_import.lazy_import(
    globals(),
    """
from breezy.bzr import (
    serializer,
    xml_serializer,
    )
""",
)
from .. import cache_utf8
from .. import revision as _mod_revision
from . import serializer


def _validate_properties(props, _decode=cache_utf8._utf8_decode):
    # TODO: we really want an 'isascii' check for key
    # Cast the utf8 properties into Unicode 'in place'
    return {
        _decode(key)[0]: _decode(value, "surrogateescape")[0]
        for key, value in props.items()
    }


def _is_format_10(value):
    if value != 10:
        raise ValueError(f"Format number was not recognized, expected 10 got {value!r}")
    return 10


class BEncodeRevisionSerializer1:
    """Simple revision serializer based around bencode."""

    squashes_xml_invalid_characters = False

    # Maps {key:(Revision attribute, bencode_type, validator)}
    # This tells us what kind we expect bdecode to create, what variable on
    # Revision we should be using, and a function to call to validate/transform
    # the type.
    # TODO: add a 'validate_utf8' for things like revision_id and file_id
    #       and a validator for parent-ids
    _schema = {
        b"format": (None, int, _is_format_10),
        b"committer": ("committer", bytes, cache_utf8.decode),
        b"timezone": ("timezone", int, None),
        b"timestamp": ("timestamp", bytes, float),
        b"revision-id": ("revision_id", bytes, None),
        b"parent-ids": ("parent_ids", list, None),
        b"inventory-sha1": ("inventory_sha1", bytes, None),
        b"message": ("message", bytes, cache_utf8.decode),
        b"properties": ("properties", dict, _validate_properties),
    }

    def write_revision_to_string(self, rev):
        encode_utf8 = cache_utf8._utf8_encode
        # Use a list of tuples rather than a dict
        # This lets us control the ordering, so that we are able to create
        # smaller deltas
        ret = [
            (b"format", 10),
            (b"committer", encode_utf8(rev.committer)[0]),
        ]
        if rev.timezone is not None:
            ret.append((b"timezone", rev.timezone))
        # For bzr revisions, the most common property is just 'branch-nick'
        # which changes infrequently.
        revprops = {}
        for key, value in rev.properties.items():
            revprops[encode_utf8(key)[0]] = encode_utf8(value, "surrogateescape")[0]
        ret.append((b"properties", revprops))
        ret.extend(
            [
                (b"timestamp", b"%.3f" % rev.timestamp),
                (b"revision-id", rev.revision_id),
                (b"parent-ids", rev.parent_ids),
                (b"inventory-sha1", rev.inventory_sha1),
                (b"message", encode_utf8(rev.message)[0]),
            ]
        )
        return bencode.bencode(ret)

    def write_revision_to_lines(self, rev):
        return self.write_revision_to_string(rev).splitlines(True)

    def read_revision_from_string(self, text):
        # TODO: consider writing a Revision decoder, rather than using the
        #       generic bencode decoder
        #       However, to decode all 25k revisions of bzr takes approx 1.3s
        #       If we remove all extra validation that goes down to about 1.2s.
        #       Of that time, probably 0.6s is spend in bencode.bdecode().
        #       Regardless 'time brz log' of everything is 7+s, so 1.3s to
        #       extract revision texts isn't a majority of time.
        ret = bencode.bdecode(text)
        if not isinstance(ret, list):
            raise ValueError("invalid revision text")
        schema = self._schema
        # timezone is allowed to be missing, but should be set
        bits = {"timezone": None}
        for key, value in ret:
            # Will raise KeyError if not a valid part of the schema, or an
            # entry is given 2 times.
            var_name, expected_type, validator = schema[key]
            if value.__class__ is not expected_type:
                raise ValueError(
                    "key {} did not conform to the expected type {}, but was {}".format(
                        key, expected_type, type(value)
                    )
                )
            if validator is not None:
                value = validator(value)
            bits[var_name] = value
        if len(bits) != len(schema):
            missing = [
                key for key, (var_name, _, _) in schema.items() if var_name not in bits
            ]
            raise ValueError(
                "Revision text was missing expected keys {}. text {!r}".format(
                    missing, text
                )
            )
        del bits[None]  # Get rid of 'format' since it doesn't get mapped
        rev = _mod_revision.Revision(**bits)
        return rev

    def read_revision(self, f):
        return self.read_revision_from_string(f.read())


class CHKSerializer(serializer.Serializer):
    """A CHKInventory based serializer with 'plain' behaviour."""

    format_num = b"9"
    revision_format_num = None
    support_altered_by_hack = False
    supported_kinds = {"file", "directory", "symlink", "tree-reference"}

    def __init__(self, node_size, search_key_name):
        self.maximum_size = node_size
        self.search_key_name = search_key_name

    def _unpack_inventory(
        self, elt, revision_id=None, entry_cache=None, return_from_cache=False
    ):
        """Construct from XML Element."""
        inv = xml_serializer.unpack_inventory_flat(
            elt,
            self.format_num,
            xml_serializer.unpack_inventory_entry,
            entry_cache,
            return_from_cache,
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
        try:
            return self._unpack_inventory(
                xml_serializer.fromstringlist(xml_lines),
                revision_id,
                entry_cache=entry_cache,
                return_from_cache=return_from_cache,
            )
        except xml_serializer.ParseError as e:
            raise serializer.UnexpectedInventoryFormat(e) from e

    def read_inventory(self, f, revision_id=None):
        """Read an inventory from a file-like object."""
        try:
            try:
                return self._unpack_inventory(self._read_element(f), revision_id=None)
            finally:
                f.close()
        except xml_serializer.ParseError as e:
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
        output = []
        append = output.append
        if inv.revision_id is not None:
            revid = b"".join(
                [
                    b' revision_id="',
                    xml_serializer.encode_and_escape(inv.revision_id),
                    b'"',
                ]
            )
        else:
            revid = b""
        append(b'<inventory format="%s"%s>\n' % (self.format_num, revid))
        append(
            b'<directory file_id="%s" name="%s" revision="%s" />\n'
            % (
                xml_serializer.encode_and_escape(inv.root.file_id),
                xml_serializer.encode_and_escape(inv.root.name),
                xml_serializer.encode_and_escape(inv.root.revision),
            )
        )
        xml_serializer.serialize_inventory_flat(
            inv,
            append,
            root_id=None,
            supported_kinds=self.supported_kinds,
            working=working,
        )
        if f is not None:
            f.writelines(output)
        return output


chk_serializer_255_bigpage = CHKSerializer(65536, b"hash-255-way")


class CHKBEncodeSerializer(BEncodeRevisionSerializer1, CHKSerializer):
    """A CHKInventory and BEncode based serializer with 'plain' behaviour."""

    format_num = b"10"


chk_bencode_serializer = CHKBEncodeSerializer(65536, b"hash-255-way")
