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
    el.text = '\n'
    
    root = Element('root_directory', {'id': inv.root.file_id})
    root.tail = root.text = '\n'
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
            raise BzrError('unknown InventoryEntry kind %r' % kind)

        el.tail = '\n'
        parent_el.append(el)

        if kind == 'directory':
            el.text = '\n' # break before having children
            l = ie.children.items()
            l.sort()
            for child_name, child_ie in l:
                descend(el, child_ie)
                
        
    # walk down through inventory, adding all directories

    l = inv.root.children.items()
    l.sort()
    for entry_name, ie in l:
        descend(root, ie)
    
    ElementTree(el).write(f, 'utf-8')
    f.write('\n')



def escape_attr(text):
    return text.replace("&", "&amp;") \
           .replace("'", "&apos;") \
           .replace('"', "&quot;") \
           .replace("<", "&lt;") \
           .replace(">", "&gt;")


# This writes out an inventory without building an XML tree first,
# just to see if it's faster.  Not currently used.
def write_slacker_inventory(inv, f):
    def descend(ie):
        kind = ie.kind
        f.write('<%s name="%s" id="%s" ' % (kind, escape_attr(ie.name),
                                            escape_attr(ie.file_id)))

        if kind == 'file':
            if ie.text_id:
                f.write('text_id="%s" ' % ie.text_id)
            if ie.text_sha1:
                f.write('text_sha1="%s" ' % ie.text_sha1)
            if ie.text_size != None:
                f.write('text_size="%d" ' % ie.text_size)
            f.write('/>\n')
        elif kind == 'directory':
            f.write('>\n')
            
            l = ie.children.items()
            l.sort()
            for child_name, child_ie in l:
                descend(child_ie)

            f.write('</directory>\n')
        else:
            raise BzrError('unknown InventoryEntry kind %r' % kind)

    f.write('<inventory>\n')
    f.write('<root_directory id="%s">\n' % escape_attr(inv.root.file_id))

    l = inv.root.children.items()
    l.sort()
    for entry_name, ie in l:
        descend(ie)

    f.write('</root_directory>\n')
    f.write('</inventory>\n')
    


def read_new_inventory(f):
    from inventory import Inventory, InventoryEntry
    
    def descend(parent_ie, el):
        kind = el.tag
        name = el.get('name')
        file_id = el.get('id')
        ie = InventoryEntry(file_id, name, el.tag)
        parent_ie.children[name] = ie
        inv._byid[file_id] = ie
        if kind == 'directory':
            for child_el in el:
                descend(ie, child_el)
        elif kind == 'file':
            assert len(el) == 0
            ie.text_id = el.get('text_id')
            v = el.get('text_size')
            ie.text_size = v and int(v)
            ie.text_sha1 = el.get('text_sha1')
        else:
            raise BzrError("unknown inventory entry %r" % kind)

    inv_el = ElementTree().parse(f)
    assert inv_el.tag == 'inventory'
    root_el = inv_el[0]
    assert root_el.tag == 'root_directory'

    inv = Inventory()
    for el in root_el:
        descend(inv.root, el)
