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
        


class Serializer(object):
    """Abstract object serialize/deserialize"""
    def write_inventory(self, inv, f):
        """Write inventory to a file"""
        elt = self._pack_inventory(inv)
        self._write_element(elt, f)

    def read_inventory(self, f):
        return self._unpack_inventory(self._read_element(f))

    def _write_element(self, elt, f):
        ElementTree(elt).write(f, 'utf-8')
        f.write('\n')

    def _read_element(self, f):
        return ElementTree().parse(f)



class _Serializer_v4(Serializer):
    """Version 0.0.4 serializer"""
    
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


"""singleton instance"""
serializer_v4 = _Serializer_v4()





def pack_xml(o, f):
    """Write object o to file f as XML.

    o must provide a to_element method.
    """
    ElementTree(o.to_element()).write(f, 'utf-8')
    f.write('\n')


def unpack_xml(cls, f):
    return cls.from_element(ElementTree().parse(f))
