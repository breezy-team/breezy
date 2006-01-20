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
import bzrlib.inventory as inventory
from bzrlib.revision import Revision        
from bzrlib.errors import BzrError


class Serializer_v5(Serializer):
    """Version 5 serializer

    Packs objects into XML and vice versa.
    """
    
    __slots__ = []
    
    def _pack_inventory(self, inv):
        """Convert to XML Element"""
        e = Element('inventory',
                    format='5')
        e.text = '\n'
        if inv.root.file_id not in (None, ROOT_ID):
            e.set('file_id', inv.root.file_id)
        for path, ie in inv.iter_entries():
            e.append(self._pack_entry(ie))
        return e


    def _pack_entry(self, ie):
        """Convert InventoryEntry to XML element"""
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
        inv = Inventory(root_id)
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

        parent_id = elt.get('parent_id')
        if parent_id == None:
            parent_id = ROOT_ID

        if kind == 'directory':
            ie = inventory.InventoryDirectory(elt.get('file_id'),
                                              elt.get('name'),
                                              parent_id)
        elif kind == 'file':
            ie = inventory.InventoryFile(elt.get('file_id'),
                                         elt.get('name'),
                                         parent_id)
            ie.text_sha1 = elt.get('text_sha1')
            if elt.get('executable') == 'yes':
                ie.executable = True
            v = elt.get('text_size')
            ie.text_size = v and int(v)
        elif kind == 'symlink':
            ie = inventory.InventoryLink(elt.get('file_id'),
                                         elt.get('name'),
                                         parent_id)
            ie.symlink_target = elt.get('symlink_target')
        else:
            raise BzrError("unknown kind %r" % kind)
        ie.revision = elt.get('revision')

        return ie


    def _unpack_revision(self, elt):
        """XML Element -> Revision object"""
        assert elt.tag == 'revision'
        format = elt.get('format')
        if format is not None:
            if format != '5':
                raise BzrError("invalid format version %r on inventory"
                                % format)
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
        self._unpack_revision_properties(elt, rev)
        v = elt.get('timezone')
        rev.timezone = v and int(v)
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
                "bad tag under properties list: %r" % p.tag
            name = prop_elt.get('name')
            value = prop_elt.text
            assert name not in rev.properties, \
                "repeated property %r" % p.name
            rev.properties[name] = value


serializer_v5 = Serializer_v5()
