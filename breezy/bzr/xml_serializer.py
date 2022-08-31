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

import re

try:
    import xml.etree.cElementTree as elementtree
    from xml.etree.ElementTree import ParseError
except ImportError:
    # Fall back to pure python implementation if C extension is unavailable
    import xml.etree.ElementTree as elementtree
    try:
        from xml.etree.ElementTree import ParseError
    except ImportError:
        from xml.parsers.expat import ExpatError as ParseError

(ElementTree, SubElement, Element, fromstringlist, tostringlist, tostring,
 fromstring) = (
    elementtree.ElementTree, elementtree.SubElement, elementtree.Element,
    elementtree.fromstringlist, elementtree.tostringlist, elementtree.tostring,
    elementtree.fromstring)


from .. import (
    errors,
    lazy_regex,
    )
from . import (
    inventory,
    serializer,
    )


class XMLSerializer(serializer.Serializer):
    """Abstract XML object serialize/deserialize"""

    squashes_xml_invalid_characters = True

    def read_inventory_from_lines(self, lines, revision_id=None,
                                  entry_cache=None, return_from_cache=False):
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
            return self._unpack_inventory(fromstringlist(lines), revision_id,
                                          entry_cache=entry_cache,
                                          return_from_cache=return_from_cache)
        except ParseError as e:
            raise serializer.UnexpectedInventoryFormat(str(e))

    def read_inventory(self, f, revision_id=None):
        try:
            try:
                return self._unpack_inventory(self._read_element(f),
                                              revision_id=None)
            finally:
                f.close()
        except ParseError as e:
            raise serializer.UnexpectedInventoryFormat(str(e))

    def write_revision_to_string(self, rev):
        return b''.join(self.write_revision_to_lines(rev))

    def read_revision(self, f):
        return self._unpack_revision(self._read_element(f))

    def read_revision_from_string(self, xml_string):
        return self._unpack_revision(fromstring(xml_string))

    def _read_element(self, f):
        return ElementTree().parse(f)


def escape_invalid_chars(message):
    """Escape the XML-invalid characters in a commit message.

    :param message: Commit message to escape
    :return: tuple with escaped message and number of characters escaped
    """
    if message is None:
        return None, 0
    # Python strings can include characters that can't be
    # represented in well-formed XML; escape characters that
    # aren't listed in the XML specification
    # (http://www.w3.org/TR/REC-xml/#NT-Char).
    return re.subn(u'[^\x09\x0A\x0D\u0020-\uD7FF\uE000-\uFFFD]+',
                   lambda match: match.group(0).encode(
                       'unicode_escape').decode('ascii'),
                   message)


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
        return a_str.encode('utf-8')
    else:
        return a_str


_utf8_re = lazy_regex.lazy_compile(b'[&<>\'\"]|[\x80-\xff]+')
_unicode_re = lazy_regex.lazy_compile(u'[&<>\'\"\u0080-\uffff]')


_xml_escape_map = {
    "&": '&amp;',
    "'": "&apos;",  # FIXME: overkill
    "\"": "&quot;",
    "<": "&lt;",
    ">": "&gt;",
    }


def _unicode_escape_replace(match, _map=_xml_escape_map):
    """Replace a string of non-ascii, non XML safe characters with their escape

    This will escape both Standard XML escapes, like <>"', etc.
    As well as escaping non ascii characters, because ElementTree did.
    This helps us remain compatible to older versions of bzr. We may change
    our policy in the future, though.
    """
    # jam 20060816 Benchmarks show that try/KeyError is faster if you
    # expect the entity to rarely miss. There is about a 10% difference
    # in overall time. But if you miss frequently, then if None is much
    # faster. For our use case, we *rarely* have a revision id, file id
    # or path name that is unicode. So use try/KeyError.
    try:
        return _map[match.group()]
    except KeyError:
        return "&#%d;" % ord(match.group())


def _utf8_escape_replace(match, _map=_xml_escape_map):
    """Escape utf8 characters into XML safe ones.

    This uses 2 tricks. It is either escaping "standard" characters, like "&<>,
    or it is handling characters with the high-bit set. For ascii characters,
    we just lookup the replacement in the dictionary. For everything else, we
    decode back into Unicode, and then use the XML escape code.
    """
    try:
        return _map[match.group().decode('ascii', 'replace')].encode()
    except KeyError:
        return b''.join(b'&#%d;' % ord(uni_chr)
                        for uni_chr in match.group().decode('utf8'))


_to_escaped_map = {}


def encode_and_escape(unicode_or_utf8_str, _map=_to_escaped_map):
    """Encode the string into utf8, and escape invalid XML characters"""
    # We frequently get entities we have not seen before, so it is better
    # to check if None, rather than try/KeyError
    text = _map.get(unicode_or_utf8_str)
    if text is None:
        if isinstance(unicode_or_utf8_str, str):
            # The alternative policy is to do a regular UTF8 encoding
            # and then escape only XML meta characters.
            # Performance is equivalent once you use codecs. *However*
            # this makes the serialized texts incompatible with old versions
            # of bzr. So no net gain. (Perhaps the read code would handle utf8
            # better than entity escapes, but cElementTree seems to do just
            # fine either way)
            text = _unicode_re.sub(
                _unicode_escape_replace, unicode_or_utf8_str).encode()
        else:
            # Plain strings are considered to already be in utf-8 so we do a
            # slightly different method for escaping.
            text = _utf8_re.sub(_utf8_escape_replace,
                                unicode_or_utf8_str)
        _map[unicode_or_utf8_str] = text
    return text


def _clear_cache():
    """Clean out the unicode => escaped map"""
    _to_escaped_map.clear()


def unpack_inventory_entry(elt, entry_cache=None, return_from_cache=False):
    elt_get = elt.get
    file_id = elt_get('file_id')
    revision = elt_get('revision')
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
                if cached_ie.kind == 'directory':
                    return cached_ie.copy()
                return cached_ie
            return cached_ie.copy()

    kind = elt.tag
    if not inventory.InventoryEntry.versionable_kind(kind):
        raise AssertionError('unsupported entry kind %s' % kind)

    file_id = get_utf8_or_ascii(file_id)
    if revision is not None:
        revision = get_utf8_or_ascii(revision)
    parent_id = elt_get('parent_id')
    if parent_id is not None:
        parent_id = get_utf8_or_ascii(parent_id)

    if kind == 'directory':
        ie = inventory.InventoryDirectory(file_id,
                                          elt_get('name'),
                                          parent_id)
    elif kind == 'file':
        ie = inventory.InventoryFile(file_id,
                                     elt_get('name'),
                                     parent_id)
        ie.text_sha1 = elt_get('text_sha1')
        if ie.text_sha1 is not None:
            ie.text_sha1 = ie.text_sha1.encode('ascii')
        if elt_get('executable') == 'yes':
            ie.executable = True
        v = elt_get('text_size')
        ie.text_size = v and int(v)
    elif kind == 'symlink':
        ie = inventory.InventoryLink(file_id,
                                     elt_get('name'),
                                     parent_id)
        ie.symlink_target = elt_get('symlink_target')
    elif kind == 'tree-reference':
        file_id = get_utf8_or_ascii(elt.attrib['file_id'])
        name = elt.attrib['name']
        parent_id = get_utf8_or_ascii(elt.attrib['parent_id'])
        revision = get_utf8_or_ascii(elt.get('revision'))
        reference_revision = get_utf8_or_ascii(elt.get('reference_revision'))
        ie = inventory.TreeReference(file_id, name, parent_id, revision,
                                     reference_revision)
    else:
        raise serializer.UnsupportedInventoryKind(kind)
    ie.revision = revision
    if revision is not None and entry_cache is not None:
        # We cache a copy() because callers like to mutate objects, and
        # that would cause the item in cache to mutate as well.
        # This has a small effect on many-inventory performance, because
        # the majority fraction is spent in cache hits, not misses.
        entry_cache[key] = ie.copy()

    return ie


def unpack_inventory_flat(elt, format_num, unpack_entry,
                          entry_cache=None, return_from_cache=False):
    """Unpack a flat XML inventory.

    :param elt: XML element for the inventory
    :param format_num: Expected format number
    :param unpack_entry: Function for unpacking inventory entries
    :return: An inventory
    :raise UnexpectedInventoryFormat: When unexpected elements or data is
        encountered
    """
    if elt.tag != 'inventory':
        raise serializer.UnexpectedInventoryFormat('Root tag is %r' % elt.tag)
    format = elt.get('format')
    if ((format is None and format_num is not None) or
            format.encode() != format_num):
        raise serializer.UnexpectedInventoryFormat('Invalid format version %r' % format)
    revision_id = elt.get('revision_id')
    if revision_id is not None:
        revision_id = revision_id.encode('utf-8')
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
        reference_revision, symlink_target.    self._check_revisions(inv)
    """
    entries = inv.iter_entries()
    # Skip the root
    root_path, root_ie = next(entries)
    for path, ie in entries:
        if ie.parent_id != root_id:
            parent_str = b''.join(
                [b' parent_id="', encode_and_escape(ie.parent_id), b'"'])
        else:
            parent_str = b''
        if ie.kind == 'file':
            if ie.executable:
                executable = b' executable="yes"'
            else:
                executable = b''
            if not working:
                append(b'<file%s file_id="%s" name="%s"%s revision="%s" '
                       b'text_sha1="%s" text_size="%d" />\n' % (
                           executable, encode_and_escape(ie.file_id),
                           encode_and_escape(ie.name), parent_str,
                           encode_and_escape(ie.revision), ie.text_sha1,
                           ie.text_size))
            else:
                append(b'<file%s file_id="%s" name="%s"%s />\n' % (
                    executable, encode_and_escape(ie.file_id),
                    encode_and_escape(ie.name), parent_str))
        elif ie.kind == 'directory':
            if not working:
                append(b'<directory file_id="%s" name="%s"%s revision="%s" '
                       b'/>\n' % (
                           encode_and_escape(ie.file_id),
                           encode_and_escape(ie.name),
                           parent_str,
                           encode_and_escape(ie.revision)))
            else:
                append(b'<directory file_id="%s" name="%s"%s />\n' % (
                    encode_and_escape(ie.file_id),
                    encode_and_escape(ie.name),
                    parent_str))
        elif ie.kind == 'symlink':
            if not working:
                append(b'<symlink file_id="%s" name="%s"%s revision="%s" '
                       b'symlink_target="%s" />\n' % (
                           encode_and_escape(ie.file_id),
                           encode_and_escape(ie.name),
                           parent_str,
                           encode_and_escape(ie.revision),
                           encode_and_escape(ie.symlink_target)))
            else:
                append(b'<symlink file_id="%s" name="%s"%s />\n' % (
                    encode_and_escape(ie.file_id),
                    encode_and_escape(ie.name),
                    parent_str))
        elif ie.kind == 'tree-reference':
            if ie.kind not in supported_kinds:
                raise serializer.UnsupportedInventoryKind(ie.kind)
            if not working:
                append(b'<tree-reference file_id="%s" name="%s"%s '
                       b'revision="%s" reference_revision="%s" />\n' % (
                           encode_and_escape(ie.file_id),
                           encode_and_escape(ie.name),
                           parent_str,
                           encode_and_escape(ie.revision),
                           encode_and_escape(ie.reference_revision)))
            else:
                append(b'<tree-reference file_id="%s" name="%s"%s />\n' % (
                    encode_and_escape(ie.file_id),
                    encode_and_escape(ie.name),
                    parent_str))
        else:
            raise serializer.UnsupportedInventoryKind(ie.kind)
    append(b'</inventory>\n')
