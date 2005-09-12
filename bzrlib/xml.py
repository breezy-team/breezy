#! /usr/bin/env python
# -*- coding: UTF-8 -*-

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""XML externalization support."""

# "XML is like violence: if it doesn't solve your problem, you aren't
# using enough of it." -- various

# importing this module is fairly slow because it has to load several
# ElementTree bits

try:
    from util.cElementTree import ElementTree, SubElement, Element
except ImportError:
    from util.elementtree.ElementTree import ElementTree, SubElement, Element

from bzrlib.inventory import ROOT_ID, Inventory, InventoryEntry
from bzrlib.revision import Revision, RevisionReference        
from bzrlib.errors import BzrError


class Serializer(object):
    """Abstract object serialize/deserialize"""
    def write_inventory(self, inv, f):
        """Write inventory to a file"""
        elt = self._pack_inventory(inv)
        self._write_element(elt, f)

    def read_inventory(self, f):
        return self._unpack_inventory(self._read_element(f))

    def write_revision(self, rev, f):
        self._write_element(self._pack_revision(rev), f)

    def read_revision(self, f):
        return self._unpack_revision(self._read_element(f))

    def _write_element(self, elt, f):
        ElementTree(elt).write(f, 'utf-8')
        f.write('\n')

    def _read_element(self, f):
        return ElementTree().parse(f)



class _Serializer_v4(Serializer):
    """Version 0.0.4 serializer

    You should use the serialzer_v4 singleton."""
    
    __slots__ = []
    
    def _pack_inventory(self, inv):
        """Convert to XML Element"""
        e = Element('inventory')
        e.text = '\n'
        if inv.root.file_id not in (None, ROOT_ID):
            e.set('file_id', inv.root.file_id)
        for path, ie in inv.iter_entries():
            e.append(self._pack_entry(ie))
        return e


    def _pack_entry(self, ie):
        """Convert InventoryEntry to XML element"""
        e = Element('entry')
        e.set('name', ie.name)
        e.set('file_id', ie.file_id)
        e.set('kind', ie.kind)

        if ie.text_size != None:
            e.set('text_size', '%d' % ie.text_size)

        for f in ['text_id', 'text_sha1', 'symlink_target']:
            v = getattr(ie, f)
            if v != None:
                e.set(f, v)

        # to be conservative, we don't externalize the root pointers
        # for now, leaving them as null in the xml form.  in a future
        # version it will be implied by nested elements.
        if ie.parent_id != ROOT_ID:
            assert isinstance(ie.parent_id, basestring)
            e.set('parent_id', ie.parent_id)

        e.tail = '\n'

        return e


    def _unpack_inventory(self, elt):
        """Construct from XML Element
        """
        assert elt.tag == 'inventory'
        root_id = elt.get('file_id') or ROOT_ID
        inv = Inventory(root_id)
        for e in elt:
            ie = self._unpack_entry(e)
            if ie.parent_id == ROOT_ID:
                ie.parent_id = root_id
            inv.add(ie)
        return inv


    def _unpack_entry(self, elt):
        assert elt.tag == 'entry'

        ## original format inventories don't have a parent_id for
        ## nodes in the root directory, but it's cleaner to use one
        ## internally.
        parent_id = elt.get('parent_id')
        if parent_id == None:
            parent_id = ROOT_ID

        ie = InventoryEntry(elt.get('file_id'),
                              elt.get('name'),
                              elt.get('kind'),
                              parent_id)
        ie.text_id = elt.get('text_id')
        ie.text_sha1 = elt.get('text_sha1')
        ie.symlink_target = elt.get('symlink_target')

        ## mutter("read inventoryentry: %r" % (elt.attrib))

        v = elt.get('text_size')
        ie.text_size = v and int(v)

        return ie


    def _pack_revision(self, rev):
        """Revision object -> xml tree"""
        root = Element('revision',
                       committer = rev.committer,
                       timestamp = '%.9f' % rev.timestamp,
                       revision_id = rev.revision_id,
                       inventory_id = rev.inventory_id,
                       inventory_sha1 = rev.inventory_sha1,
                       )
        if rev.timezone:
            root.set('timezone', str(rev.timezone))
        root.text = '\n'

        msg = SubElement(root, 'message')
        msg.text = rev.message
        msg.tail = '\n'

        if rev.parents:
            pelts = SubElement(root, 'parents')
            pelts.tail = pelts.text = '\n'
            for rr in rev.parents:
                assert isinstance(rr, RevisionReference)
                p = SubElement(pelts, 'revision_ref')
                p.tail = '\n'
                assert rr.revision_id
                p.set('revision_id', rr.revision_id)
                if rr.revision_sha1:
                    p.set('revision_sha1', rr.revision_sha1)

        return root

    
    def _unpack_revision(self, elt):
        """XML Element -> Revision object"""
        
        # <changeset> is deprecated...
        if elt.tag not in ('revision', 'changeset'):
            raise BzrError("unexpected tag in revision file: %r" % elt)

        rev = Revision(committer = elt.get('committer'),
                       timestamp = float(elt.get('timestamp')),
                       revision_id = elt.get('revision_id'),
                       inventory_id = elt.get('inventory_id'),
                       inventory_sha1 = elt.get('inventory_sha1')
                       )

        precursor = elt.get('precursor')
        precursor_sha1 = elt.get('precursor_sha1')

        pelts = elt.find('parents')

        if pelts:
            for p in pelts:
                assert p.tag == 'revision_ref', \
                       "bad parent node tag %r" % p.tag
                rev_ref = RevisionReference(p.get('revision_id'),
                                            p.get('revision_sha1'))
                rev.parents.append(rev_ref)

            if precursor:
                # must be consistent
                prec_parent = rev.parents[0].revision_id
                assert prec_parent == precursor
        elif precursor:
            # revisions written prior to 0.0.5 have a single precursor
            # give as an attribute
            rev_ref = RevisionReference(precursor, precursor_sha1)
            rev.parents.append(rev_ref)

        v = elt.get('timezone')
        rev.timezone = v and int(v)

        rev.message = elt.findtext('message') # text of <message>
        return rev



class _Serializer_v5(Serializer):
    """Version 5 serializer

    Packs objects into XML and vice versa.

    You should use the serialzer_v5 singleton."""
    
    __slots__ = []
    
    def _pack_inventory(self, inv):
        """Convert to XML Element"""
        e = Element('inventory')
        e.text = '\n'
        if inv.root.file_id not in (None, ROOT_ID):
            e.set('file_id', inv.root.file_id)
        for path, ie in inv.iter_entries():
            e.append(self._pack_entry(ie))
        return e


    def _pack_entry(self, ie):
        """Convert InventoryEntry to XML element"""
        assert ie.kind == 'directory' or ie.kind == 'file'
        e = Element(ie.kind)
        e.set('name', ie.name)
        e.set('file_id', ie.file_id)

        if ie.text_size != None:
            e.set('text_size', '%d' % ie.text_size)

        for f in ['text_version', 'text_sha1', 'entry_version']:
            v = getattr(ie, f)
            if v != None:
                e.set(f, v)

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
                       inventory_id = rev.inventory_id,
                       inventory_sha1 = rev.inventory_sha1,
                       )
        if rev.timezone:
            root.set('timezone', str(rev.timezone))
        root.text = '\n'

        msg = SubElement(root, 'message')
        msg.text = rev.message
        msg.tail = '\n'

        if rev.parents:
            pelts = SubElement(root, 'parents')
            pelts.tail = pelts.text = '\n'
            for rr in rev.parents:
                assert isinstance(rr, RevisionReference)
                p = SubElement(pelts, 'revision_ref')
                p.tail = '\n'
                assert rr.revision_id
                p.set('revision_id', rr.revision_id)

        return root

    

    def _unpack_inventory(self, elt):
        """Construct from XML Element
        """
        assert elt.tag == 'inventory'
        root_id = elt.get('file_id') or ROOT_ID
        inv = Inventory(root_id)
        for e in elt:
            ie = self._unpack_entry(e)
            if ie.parent_id == ROOT_ID:
                ie.parent_id = root_id
            inv.add(ie)
        return inv


    def _unpack_entry(self, elt):
        kind = elt.tag
        assert kind == 'directory' or kind == 'file'

        parent_id = elt.get('parent_id')
        if parent_id == None:
            parent_id = ROOT_ID

        ie = InventoryEntry(elt.get('file_id'),
                            elt.get('name'),
                            kind,
                            parent_id)
        ie.text_version = elt.get('text_version')
        ie.entry_version = elt.get('entry_version')
        ie.text_sha1 = elt.get('text_sha1')
        v = elt.get('text_size')
        ie.text_size = v and int(v)

        return ie


    def _unpack_revision(self, elt):
        """XML Element -> Revision object"""
        assert elt.tag == 'revision'
        
        rev = Revision(committer = elt.get('committer'),
                       timestamp = float(elt.get('timestamp')),
                       revision_id = elt.get('revision_id'),
                       inventory_id = elt.get('inventory_id'),
                       inventory_sha1 = elt.get('inventory_sha1')
                       )

        for p in elt.find('parents'):
            assert p.tag == 'revision_ref', \
                   "bad parent node tag %r" % p.tag
            rev_ref = RevisionReference(p.get('revision_id'))
            rev.parents.append(rev_ref)

        v = elt.get('timezone')
        rev.timezone = v and int(v)

        rev.message = elt.findtext('message') # text of <message>
        return rev



"""singleton instance"""
serializer_v4 = _Serializer_v4()

serializer_v5 = _Serializer_v5()
