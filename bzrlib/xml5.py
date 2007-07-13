# Copyright (C) 2005, 2006, 2007 Canonical Ltd
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

import cStringIO
import re

from bzrlib import (
    cache_utf8,
    errors,
    inventory,
    revision as _mod_revision,
    )
from bzrlib.xml_serializer import SubElement, Element, Serializer
from bzrlib.inventory import ROOT_ID, Inventory, InventoryEntry
from bzrlib.revision import Revision
from bzrlib.errors import BzrError


_utf8_re = None
_unicode_re = None
_xml_escape_map = {
    "&":'&amp;',
    "'":"&apos;", # FIXME: overkill
    "\"":"&quot;",
    "<":"&lt;",
    ">":"&gt;",
    }


def _ensure_utf8_re():
    """Make sure the _utf8_re and _unicode_re regexes have been compiled."""
    global _utf8_re, _unicode_re
    if _utf8_re is None:
        _utf8_re = re.compile('[&<>\'\"]|[\x80-\xff]+')
    if _unicode_re is None:
        _unicode_re = re.compile(u'[&<>\'\"\u0080-\uffff]')


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
        return _map[match.group()]
    except KeyError:
        return ''.join('&#%d;' % ord(uni_chr)
                       for uni_chr in match.group().decode('utf8'))


_to_escaped_map = {}

def _encode_and_escape(unicode_or_utf8_str, _map=_to_escaped_map):
    """Encode the string into utf8, and escape invalid XML characters"""
    # We frequently get entities we have not seen before, so it is better
    # to check if None, rather than try/KeyError
    text = _map.get(unicode_or_utf8_str)
    if text is None:
        if unicode_or_utf8_str.__class__ == unicode:
            # The alternative policy is to do a regular UTF8 encoding
            # and then escape only XML meta characters.
            # Performance is equivalent once you use cache_utf8. *However*
            # this makes the serialized texts incompatible with old versions
            # of bzr. So no net gain. (Perhaps the read code would handle utf8
            # better than entity escapes, but cElementTree seems to do just fine
            # either way)
            text = str(_unicode_re.sub(_unicode_escape_replace,
                                       unicode_or_utf8_str)) + '"'
        else:
            # Plain strings are considered to already be in utf-8 so we do a
            # slightly different method for escaping.
            text = _utf8_re.sub(_utf8_escape_replace,
                                unicode_or_utf8_str) + '"'
        _map[unicode_or_utf8_str] = text
    return text


def _get_utf8_or_ascii(a_str,
                       _encode_utf8=cache_utf8.encode,
                       _get_cached_ascii=cache_utf8.get_cached_ascii):
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
    if a_str.__class__ == unicode:
        return _encode_utf8(a_str)
    else:
        return _get_cached_ascii(a_str)


def _clear_cache():
    """Clean out the unicode => escaped map"""
    _to_escaped_map.clear()


class Serializer_v5(Serializer):
    """Version 5 serializer

    Packs objects into XML and vice versa.
    """
    
    __slots__ = []

    support_altered_by_hack = True
    # This format supports the altered-by hack that reads file ids directly out
    # of the versionedfile, without doing XML parsing.

    supported_kinds = set(['file', 'directory', 'symlink'])

    def write_inventory_to_string(self, inv):
        """Just call write_inventory with a StringIO and return the value"""
        sio = cStringIO.StringIO()
        self.write_inventory(inv, sio)
        return sio.getvalue()

    def write_inventory(self, inv, f):
        """Write inventory to a file.
        
        :param inv: the inventory to write.
        :param f: the file to write.
        """
        _ensure_utf8_re()
        output = []
        append = output.append
        self._append_inventory_root(append, inv)
        entries = inv.iter_entries()
        # Skip the root
        root_path, root_ie = entries.next()
        for path, ie in entries:
            self._append_entry(append, ie)
        append('</inventory>\n')
        f.writelines(output)
        # Just to keep the cache from growing without bounds
        # but we may actually not want to do clear the cache
        #_clear_cache()

    def _append_inventory_root(self, append, inv):
        """Append the inventory root to output."""
        append('<inventory')
        if inv.root.file_id not in (None, ROOT_ID):
            append(' file_id="')
            append(_encode_and_escape(inv.root.file_id))
        append(' format="5"')
        if inv.revision_id is not None:
            append(' revision_id="')
            append(_encode_and_escape(inv.revision_id))
        append('>\n')
        
    def _append_entry(self, append, ie):
        """Convert InventoryEntry to XML element and append to output."""
        # TODO: should just be a plain assertion
        if ie.kind not in self.supported_kinds:
            raise errors.UnsupportedInventoryKind(ie.kind)

        append("<")
        append(ie.kind)
        if ie.executable:
            append(' executable="yes"')
        append(' file_id="')
        append(_encode_and_escape(ie.file_id))
        append(' name="')
        append(_encode_and_escape(ie.name))
        if self._parent_condition(ie):
            assert isinstance(ie.parent_id, basestring)
            append(' parent_id="')
            append(_encode_and_escape(ie.parent_id))
        if ie.revision is not None:
            append(' revision="')
            append(_encode_and_escape(ie.revision))
        if ie.symlink_target is not None:
            append(' symlink_target="')
            append(_encode_and_escape(ie.symlink_target))
        if ie.text_sha1 is not None:
            append(' text_sha1="')
            append(ie.text_sha1)
            append('"')
        if ie.text_size is not None:
            append(' text_size="%d"' % ie.text_size)
        if getattr(ie, 'reference_revision', None) is not None:
            append(' reference_revision="')
            append(_encode_and_escape(ie.reference_revision))
        append(" />\n")
        return

    def _parent_condition(self, ie):
        return ie.parent_id != ROOT_ID

    def _pack_revision(self, rev):
        """Revision object -> xml tree"""
        # For the XML format, we need to write them as Unicode rather than as
        # utf-8 strings. So that cElementTree can handle properly escaping
        # them.
        decode_utf8 = cache_utf8.decode
        revision_id = rev.revision_id
        if isinstance(revision_id, str):
            revision_id = decode_utf8(revision_id)
        root = Element('revision',
                       committer = rev.committer,
                       timestamp = '%.3f' % rev.timestamp,
                       revision_id = revision_id,
                       inventory_sha1 = rev.inventory_sha1,
                       format='5',
                       )
        if rev.timezone is not None:
            root.set('timezone', str(rev.timezone))
        root.text = '\n'
        msg = SubElement(root, 'message')
        msg.text = rev.message
        msg.tail = '\n'
        if rev.parent_ids:
            pelts = SubElement(root, 'parents')
            pelts.tail = pelts.text = '\n'
            for parent_id in rev.parent_ids:
                assert isinstance(parent_id, basestring)
                _mod_revision.check_not_reserved_id(parent_id)
                p = SubElement(pelts, 'revision_ref')
                p.tail = '\n'
                if isinstance(parent_id, str):
                    parent_id = decode_utf8(parent_id)
                p.set('revision_id', parent_id)
        if rev.properties:
            self._pack_revision_properties(rev, root)
        return root

    def _pack_revision_properties(self, rev, under_element):
        top_elt = SubElement(under_element, 'properties')
        for prop_name, prop_value in sorted(rev.properties.items()):
            assert isinstance(prop_name, basestring) 
            assert isinstance(prop_value, basestring) 
            prop_elt = SubElement(top_elt, 'property')
            prop_elt.set('name', prop_name)
            prop_elt.text = prop_value
            prop_elt.tail = '\n'
        top_elt.tail = '\n'

    def _unpack_inventory(self, elt):
        """Construct from XML Element
        """
        assert elt.tag == 'inventory'
        root_id = elt.get('file_id') or ROOT_ID
        root_id = _get_utf8_or_ascii(root_id)

        format = elt.get('format')
        if format is not None:
            if format != '5':
                raise BzrError("invalid format version %r on inventory"
                                % format)
        revision_id = elt.get('revision_id')
        if revision_id is not None:
            revision_id = cache_utf8.encode(revision_id)
        inv = Inventory(root_id, revision_id=revision_id)
        for e in elt:
            ie = self._unpack_entry(e)
            if ie.parent_id is None:
                ie.parent_id = root_id
            inv.add(ie)
        return inv

    def _unpack_entry(self, elt):
        kind = elt.tag
        if not InventoryEntry.versionable_kind(kind):
            raise AssertionError('unsupported entry kind %s' % kind)

        get_cached = _get_utf8_or_ascii

        parent_id = elt.get('parent_id')
        if parent_id is not None:
            parent_id = get_cached(parent_id)
        file_id = get_cached(elt.get('file_id'))

        if kind == 'directory':
            ie = inventory.InventoryDirectory(file_id,
                                              elt.get('name'),
                                              parent_id)
        elif kind == 'file':
            ie = inventory.InventoryFile(file_id,
                                         elt.get('name'),
                                         parent_id)
            ie.text_sha1 = elt.get('text_sha1')
            if elt.get('executable') == 'yes':
                ie.executable = True
            v = elt.get('text_size')
            ie.text_size = v and int(v)
        elif kind == 'symlink':
            ie = inventory.InventoryLink(file_id,
                                         elt.get('name'),
                                         parent_id)
            ie.symlink_target = elt.get('symlink_target')
        else:
            raise errors.UnsupportedInventoryKind(kind)
        revision = elt.get('revision')
        if revision is not None:
            revision = get_cached(revision)
        ie.revision = revision

        return ie

    def _unpack_revision(self, elt):
        """XML Element -> Revision object"""
        assert elt.tag == 'revision'
        format = elt.get('format')
        if format is not None:
            if format != '5':
                raise BzrError("invalid format version %r on inventory"
                                % format)
        get_cached = _get_utf8_or_ascii
        rev = Revision(committer = elt.get('committer'),
                       timestamp = float(elt.get('timestamp')),
                       revision_id = get_cached(elt.get('revision_id')),
                       inventory_sha1 = elt.get('inventory_sha1')
                       )
        parents = elt.find('parents') or []
        for p in parents:
            assert p.tag == 'revision_ref', \
                   "bad parent node tag %r" % p.tag
            rev.parent_ids.append(get_cached(p.get('revision_id')))
        self._unpack_revision_properties(elt, rev)
        v = elt.get('timezone')
        if v is None:
            rev.timezone = 0
        else:
            rev.timezone = int(v)
        rev.message = elt.findtext('message') # text of <message>
        return rev

    def _unpack_revision_properties(self, elt, rev):
        """Unpack properties onto a revision."""
        props_elt = elt.find('properties')
        assert len(rev.properties) == 0
        if not props_elt:
            return
        for prop_elt in props_elt:
            assert prop_elt.tag == 'property', \
                "bad tag under properties list: %r" % prop_elt.tag
            name = prop_elt.get('name')
            value = prop_elt.text
            # If a property had an empty value ('') cElementTree reads
            # that back as None, convert it back to '', so that all
            # properties have string values
            if value is None:
                value = ''
            assert name not in rev.properties, \
                "repeated property %r" % name
            rev.properties[name] = value


serializer_v5 = Serializer_v5()
