# (C) 2005 Canonical Ltd

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

from cElementTree import Element, ElementTree, SubElement


def write_inventory(inv, f):
    el = Element('inventory', {'version': '2'})
    
    root = Element('root_directory', {'id': 'bogus-root-id'})
    el.append(root)

    def descend(parent_el, ie):
        kind = ie.kind
        el = Element(kind, {'name': ie.name,
                            'id': ie.file_id,})
        
        if kind == 'file':
            if ie.text_id:
                el.set('text_id', ie.text_id)
            if ie.text_sha1:
                el.set('text_sha1', ie.text_sha1)
            if ie.text_size != None:
                el.set('text_size', ('%d' % ie.text_size))
        elif kind != 'directory':
            bailout('unknown InventoryEntry kind %r' % kind)
            
        parent_el.append(el)

        if kind == 'directory':
            l = ie.children.items()
            l.sort()
            for child_name, child_ie in l:
                descend(el, child_ie)
                
        
    # walk down through inventory, adding all directories

    l = inv._root.children.items()
    l.sort()
    for entry_name, ie in l:
        descend(root, ie)
    
    ElementTree(el).write(f, 'utf-8')
    f.write('\n')
