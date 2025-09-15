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

from typing import Optional
from xml.etree.ElementTree import (  # noqa: F401
    Element,
    ElementTree,
    ParseError,
    SubElement,
    fromstring,
    fromstringlist,
)

from . import inventory, serializer


class XMLRevisionSerializer(serializer.RevisionSerializer):
    """Abstract XML object serialize/deserialize."""

    squashes_xml_invalid_characters = True

    def _unpack_revision(self, element):
        raise NotImplementedError(self._unpack_revision)

    def write_revision_to_string(self, rev):
        """Serialize a revision object to a UTF-8 string."""
        return b"".join(self.write_revision_to_lines(rev))

    def read_revision(self, f):
        """Read a revision from an open file object."""
        return self._unpack_revision(self._read_element(f))

    def read_revision_from_string(self, xml_string):
        """Read a revision from an XML string."""
        return self._unpack_revision(fromstring(xml_string))  # noqa: S314

    def _read_element(self, f):
        return ElementTree().parse(f)


class XMLInventorySerializer(serializer.InventorySerializer):
    """Abstract XML object serialize/deserialize."""

    def read_inventory_from_lines(
        self, lines, revision_id=None, entry_cache=None, return_from_cache=False
    ):
        """Read xml_string into an inventory object.

        :param chunks: The xml to read.
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
        try:
            return self._unpack_inventory(
                fromstringlist(lines),
                revision_id,
                entry_cache=entry_cache,
                return_from_cache=return_from_cache,
            )
        except ParseError as e:
            raise serializer.UnexpectedInventoryFormat(str(e)) from e

    def _unpack_inventory(
        self,
        element,
        revision_id: Optional[bytes] = None,
        entry_cache=None,
        return_from_cache=False,
    ):
        raise NotImplementedError(self._unpack_inventory)

    def read_inventory(self, f, revision_id=None):
        """Read an inventory from an open file object."""
        try:
            try:
                return self._unpack_inventory(self._read_element(f), revision_id=None)
            finally:
                f.close()
        except ParseError as e:
            raise serializer.UnexpectedInventoryFormat(str(e)) from e

    def _read_element(self, f):
        return ElementTree().parse(f)


def get_utf8_or_ascii(a_str):
    """Return a cached version of the string.

    cElementTree will return a plain string if the XML is plain ascii. It only
    returns Unicode when it needs to. We want to work in utf-8 strings. So if
    cElementTree returns a plain string, we can just return the cached version.
    If it is Unicode, then we need to encode it.

    :param a_str: An 8-bit string or Unicode as returned by
                  cElementTree.Element.get()
    :return: A utf-8 encoded 8-bit string.
    """
    # This is fairly optimized because we know what cElementTree does, this is
    # not meant as a generic function for all cases. Because it is possible for
    # an 8-bit string to not be ascii or valid utf8.
    if a_str.__class__ is str:
        return a_str.encode("utf-8")
    else:
        return a_str


from .._bzr_rs import encode_and_escape, escape_invalid_chars  # noqa: F401


def unpack_inventory_entry(
    elt, entry_cache=None, return_from_cache=False, root_id=None
):
    """Unpack an inventory entry from XML element."""
    elt_get = elt.get
    file_id = elt_get("file_id")
    revision = elt_get("revision")
    # Check and see if we have already unpacked this exact entry
    # Some timings for "repo.revision_trees(last_100_revs)"
    #               bzr     mysql
    #   unmodified  4.1s    40.8s
    #   using lru   3.5s
    #   using fifo  2.83s   29.1s
    #   lru._cache  2.8s
    #   dict        2.75s   26.8s
    #   inv.add     2.5s    26.0s
    #   no_copy     2.00s   20.5s
    #   no_c,dict   1.95s   18.0s
    # Note that a cache of 10k nodes is more than sufficient to hold all of
    # the inventory for the last 100 revs for bzr, but not for mysql (20k
    # is enough for mysql, which saves the same 2s as using a dict)

    # Breakdown of mysql using time.clock()
    #   4.1s    2 calls to element.get for file_id, revision_id
    #   4.5s    cache_hit lookup
    #   7.1s    InventoryFile.copy()
    #   2.4s    InventoryDirectory.copy()
    #   0.4s    decoding unique entries
    #   1.6s    decoding entries after FIFO fills up
    #   0.8s    Adding nodes to FIFO (including flushes)
    #   0.1s    cache miss lookups
    # Using an LRU cache
    #   4.1s    2 calls to element.get for file_id, revision_id
    #   9.9s    cache_hit lookup
    #   10.8s   InventoryEntry.copy()
    #   0.3s    cache miss lookus
    #   1.2s    decoding entries
    #   1.0s    adding nodes to LRU
    if entry_cache is not None and revision is not None:
        key = (file_id, revision)
        try:
            # We copy it, because some operations may mutate it
            cached_ie = entry_cache[key]
        except KeyError:
            pass
        else:
            # Only copying directory entries drops us 2.85s => 2.35s
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
        # We cache a copy() because callers like to mutate objects, and
        # that would cause the item in cache to mutate as well.
        # This has a small effect on many-inventory performance, because
        # the majority fraction is spent in cache hits, not misses.
        entry_cache[key] = ie.copy()

    return ie


def unpack_inventory_flat(
    elt, format_num, unpack_entry, entry_cache=None, return_from_cache=False
):
    """Unpack a flat XML inventory.

    :param elt: XML element for the inventory
    :param format_num: Expected format number
    :param unpack_entry: Function for unpacking inventory entries
    :return: An inventory
    :raise UnexpectedInventoryFormat: When unexpected elements or data is
        encountered
    """
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
    """Serialize an inventory to a flat XML file.

    :param inv: Inventory to serialize
    :param append: Function for writing a line of output
    :param working: If True skip history data - text_sha1, text_size,
        reference_revision, symlink_target.
    """
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
