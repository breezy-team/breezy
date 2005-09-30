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





class Serializer_v5(Serializer):
    """Version 5 serializer

    Packs objects into XML and vice versa.
    """
    
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
        assert ie.kind in ('directory', 'file', 'symlink')
        e = Element(ie.kind)
        e.set('name', ie.name)
        e.set('file_id', ie.file_id)

        if ie.text_size != None:
            e.set('text_size', '%d' % ie.text_size)

        for f in ['text_sha1', 'revision', 'symlink_target']:
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
                       inventory_sha1 = rev.inventory_sha1,
                       )
        if rev.timezone:
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
        if not kind in ('directory', 'file', 'symlink'):
            raise AssertionError('unsupported entry kind %s' % kind)

        parent_id = elt.get('parent_id')
        if parent_id == None:
            parent_id = ROOT_ID

        ie = InventoryEntry(elt.get('file_id'),
                            elt.get('name'),
                            kind,
                            parent_id)
        ie.revision = elt.get('revision')
        ie.text_sha1 = elt.get('text_sha1')
        ie.symlink_target = elt.get('symlink_target')
        v = elt.get('text_size')
        ie.text_size = v and int(v)

        return ie


    def _unpack_revision(self, elt):
        """XML Element -> Revision object"""
        assert elt.tag == 'revision'
        
        rev = Revision(committer = elt.get('committer'),
                       timestamp = float(elt.get('timestamp')),
                       revision_id = elt.get('revision_id'),
                       inventory_sha1 = elt.get('inventory_sha1')
                       )

        parents = elt.find('parents') or []
        for p in parents:
            assert p.tag == 'revision_ref', \
                   "bad parent node tag %r" % p.tag
            rev.parent_ids.append(p.get('revision_id'))

        v = elt.get('timezone')
        rev.timezone = v and int(v)

        rev.message = elt.findtext('message') # text of <message>
        return rev



serializer_v5 = Serializer_v5()
