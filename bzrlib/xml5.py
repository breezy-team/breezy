# Copyright (C) 2005, 2006 Canonical Ltd
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
    inventory,
    )
from bzrlib.xml_serializer import SubElement, Element, Serializer
from bzrlib.inventory import ROOT_ID, Inventory, InventoryEntry
from bzrlib.revision import Revision
from bzrlib.errors import BzrError


_utf8_re = None
_utf8_escape_map = {
    "&":'&amp;',
    "'":"&apos;", # FIXME: overkill
    "\"":"&quot;",
    "<":"&lt;",
    ">":"&gt;",
    }


def _ensure_utf8_re():
    """Make sure the _utf8_re regex has been compiled"""
    global _utf8_re
    if _utf8_re is not None:
        return
    _utf8_re = re.compile(u'[&<>\'\"\u0080-\uffff]')


def _utf8_escape_replace(match, _map=_utf8_escape_map):
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


_unicode_to_escaped_map = {}

def _encode_and_escape(unicode_str, _map=_unicode_to_escaped_map):
    """Encode the string into utf8, and escape invalid XML characters"""
    # We frequently get entities we have not seen before, so it is better
    # to check if None, rather than try/KeyError
    text = _map.get(unicode_str)
    if text is None:
        # The alternative policy is to do a regular UTF8 encoding
        # and then escape only XML meta characters.
        # Performance is equivalent once you use cache_utf8. *However*
        # this makes the serialized texts incompatible with old versions
        # of bzr. So no net gain. (Perhaps the read code would handle utf8
        # better than entity escapes, but cElementTree seems to do just fine
        # either way)
        text = str(_utf8_re.sub(_utf8_escape_replace, unicode_str)) + '"'
        _map[unicode_str] = text
    return text


def _clear_cache():
    """Clean out the unicode => escaped map"""
    _unicode_to_escaped_map.clear()


class Serializer_v5(Serializer):
    """Version 5 serializer

    Packs objects into XML and vice versa.
    """
    
    __slots__ = []

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
        assert InventoryEntry.versionable_kind(ie.kind), \
            'unsupported entry kind %s' % ie.kind

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
        append(" />\n")
        return

    def _parent_condition(self, ie):
        return ie.parent_id != ROOT_ID

    def _pack_revision(self, rev):
        """Revision object -> xml tree"""
        root = Element('revision',
                       committer = rev.committer,
                       timestamp = '%.9f' % rev.timestamp,
                       revision_id = rev.revision_id,
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
                p = SubElement(pelts, 'revision_ref')
                p.tail = '\n'
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
        format = elt.get('format')
        if format is not None:
            if format != '5':
                raise BzrError("invalid format version %r on inventory"
                                % format)
        revision_id = elt.get('revision_id')
        if revision_id is not None:
            revision_id = cache_utf8.get_cached_unicode(revision_id)
        inv = Inventory(root_id, revision_id=revision_id)
        for e in elt:
            ie = self._unpack_entry(e)
            if ie.parent_id == ROOT_ID:
                ie.parent_id = root_id
            inv.add(ie)
        return inv

    def _unpack_entry(self, elt, none_parents=False):
        kind = elt.tag
        if not InventoryEntry.versionable_kind(kind):
            raise AssertionError('unsupported entry kind %s' % kind)

        get_cached = cache_utf8.get_cached_unicode

        parent_id = elt.get('parent_id')
        if parent_id is None and not none_parents:
            parent_id = ROOT_ID
        # TODO: jam 20060817 At present, caching file ids costs us too 
        #       much time. It slows down overall read performances from
        #       approx 500ms to 700ms. And doesn't improve future reads.
        #       it might be because revision ids and file ids are mixing.
        #       Consider caching *just* the file ids, for a limited period
        #       of time.
        #parent_id = get_cached(parent_id)
        #file_id = get_cached(elt.get('file_id'))
        file_id = elt.get('file_id')

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
            raise BzrError("unknown kind %r" % kind)
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
        get_cached = cache_utf8.get_cached_unicode
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
