#! /usr/bin/env python

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


from bzrlib.xml import ElementTree, SubElement, Element, Serializer
from bzrlib.inventory import ROOT_ID, Inventory, InventoryEntry
from bzrlib.revision import Revision        
from bzrlib.errors import BzrError






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

        for f in ['text_id', 'text_sha1']:
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
            for i, parent_id in enumerate(rev.parents):
                p = SubElement(pelts, 'revision_ref')
                p.tail = '\n'
                assert parent_id
                p.set('revision_id', parent_id)
                if i < len(rev.parent_sha1s):
                    p.set('revision_sha1', rev.parent_sha1s[i])
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
                rev.parent_ids.append(p.get('revision_id'))
                rev.parent_sha1s.append(p.get('revision_sha1'))
            if precursor:
                # must be consistent
                prec_parent = rev.parent_ids[0].revision_id
                assert prec_parent == precursor
        elif precursor:
            # revisions written prior to 0.0.5 have a single precursor
            # give as an attribute
            rev.parent_ids.append(precursor)
            rev.parent_sha1s.append(precursor_sha1)

        v = elt.get('timezone')
        rev.timezone = v and int(v)

        rev.message = elt.findtext('message') # text of <message>
        return rev




"""singleton instance"""
serializer_v4 = _Serializer_v4()

