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

from bzrlib import (
    cache_utf8,
    inventory,
    )
from bzrlib.xml_serializer import SubElement, Element, Serializer
from bzrlib.inventory import ROOT_ID, Inventory, InventoryEntry
from bzrlib.revision import Revision
from bzrlib.errors import BzrError


class Serializer_v5(Serializer):
    """Version 5 serializer

    Packs objects into XML and vice versa.
    """
    
    __slots__ = ['_utf8_re']

    def __init__(self):
        self._utf8_re = None
    
    def write_inventory_to_string(self, inv):
        sio = cStringIO.StringIO()
        self.write_inventory(inv, sio)
        return sio.getvalue()

    def write_inventory(self, inv, f):
        """Write inventory to a file.
        
        :param inv: the inventory to write.
        :param f: the file to write.
        """
        output = []
        self._append_inventory_root(output, inv)
        entries = inv.iter_entries()
        root_path, root_ie = entries.next()
        for path, ie in entries:
            self._append_entry(output, ie)
        f.write(''.join(output))
#        elt = self._pack_inventory(inv)
#        for child in elt.getchildren():
#            if isinstance(child, inventory.InventoryDirectory):
#                print "foo\nbar\n"
#            print child
#            ElementTree(child).write(f, 'utf-8')
        f.write('</inventory>\n')

    def _append_inventory_root(self, output, inv):
        """Append the inventory root to output."""
        output.append('<inventory')
        if inv.root.file_id not in (None, ROOT_ID):
            output.append(' file_id="')
            self._append_utf8_escaped(output, inv.root.file_id)
        output.append(' format="5"')
        if inv.revision_id is not None:
            output.append(' revision_id="')
            self._append_utf8_escaped(output, inv.revision_id)
        output.append('>\n')
        
    def _append_entry(self, output, ie):
        """Convert InventoryEntry to XML element and append to output."""
        # TODO: should just be a plain assertion
        assert InventoryEntry.versionable_kind(ie.kind), \
            'unsupported entry kind %s' % ie.kind

        output.append("<")
        output.append(ie.kind)
        if ie.executable:
            output.append(' executable="yes"')
        output.append(' file_id="')
        self._append_utf8_escaped(output, ie.file_id)
        output.append(' name="')
        self._append_utf8_escaped(output, ie.name)
        if ie.parent_id != ROOT_ID:
            assert isinstance(ie.parent_id, basestring)
            output.append(' parent_id="')
            self._append_utf8_escaped(output, ie.parent_id)
        if ie.revision is not None:
            output.append(' revision="')
            self._append_utf8_escaped(output, ie.revision)
        if ie.symlink_target is not None:
            output.append(' symlink_target="')
            self._append_utf8_escaped(output, ie.symlink_target)
        if ie.text_sha1 is not None:
            output.append(' text_size="')
            output.append(ie.text_sha1)
            output.append('"')
        if ie.text_size is not None:
            output.append(' text_size="%d"' % ie.text_size)
        output.append(" />\n")
        return

    def _append_utf8_escaped(self, output, a_string):
        """Append a_string to output as utf8."""
        if self._utf8_re is None:
            import re
            self._utf8_re = re.compile("[&'\"<>]")
        # escape attribute value
        text = a_string.encode('utf8')
        output.append(self._utf8_re.sub(self._utf8_escape_replace, text))
        output.append('"')

    _utf8_escape_map = {
        "&":'&amp;',
        "'":"&apos;", # FIXME: overkill
        "\"":"&quot;",
        "<":"&lt;",
        ">":"&gt;",
        }
    def _utf8_escape_replace(self, match, map=_utf8_escape_map):
        return map[match.group()]

    def _pack_inventory(self, inv):
        """Convert to XML Element"""
        entries = inv.iter_entries()
        e = Element('inventory',
                    format='5')
        e.text = '\n'
        path, root = entries.next()
        if root.file_id not in (None, ROOT_ID):
            e.set('file_id', root.file_id)
        if inv.revision_id is not None:
            e.set('revision_id', inv.revision_id)
        for path, ie in entries:
            e.append(self._pack_entry(ie))
        return e

    def _pack_entry(self, ie):
        """Convert InventoryEntry to XML element"""
        # TODO: should just be a plain assertion
        if not InventoryEntry.versionable_kind(ie.kind):
            raise AssertionError('unsupported entry kind %s' % ie.kind)
        e = Element(ie.kind)
        e.set('name', ie.name)
        e.set('file_id', ie.file_id)

        if ie.text_size != None:
            e.set('text_size', '%d' % ie.text_size)

        for f in ['text_sha1', 'revision', 'symlink_target']:
            v = getattr(ie, f)
            if v != None:
                e.set(f, v)

        if ie.executable:
            e.set('executable', 'yes')

        # to be conservative, we don't externalize the root pointers
        # for now, leaving them as null in the xml form.  in a future
        # version it will be implied by nested elements.
        if ie.parent_id != ROOT_ID:
            assert isinstance(ie.parent_id, basestring)
            e.set('parent_id', ie.parent_id)
        e.tail = '\n'
        return e

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


    def _unpack_entry(self, elt):
        kind = elt.tag
        if not InventoryEntry.versionable_kind(kind):
            raise AssertionError('unsupported entry kind %s' % kind)

        get_cached = cache_utf8.get_cached_unicode

        parent_id = elt.get('parent_id')
        if parent_id == None:
            parent_id = ROOT_ID
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
