


# \subsection{Example usage}
# 
# \textbf{XXX:} Move these to object serialization code. 

def write_revision(writer, revision):
    s = Stanza(revision=revision.revision_id,
               committer=revision.committer, 
               timezone=long(revision.timezone),
               timestamp=long(revision.timestamp),
               inventory_sha1=revision.inventory_sha1,
               message=revision.message)
    for parent_id in revision.parent_ids:
        s.add('parent', parent_id)
    for prop_name, prop_value in revision.properties.items():
        s.add(prop_name, prop_value)
    writer.write_stanza(s)


def write_inventory(writer, inventory):
    s = Stanza(inventory_version=7)
    writer.write_stanza(s)

    for path, ie in inventory.iter_entries():
        s = Stanza()
        s.add(ie.kind, ie.file_id)
        for attr in ['name', 'parent_id', 'revision', \
                     'text_sha1', 'text_size', 'executable', \
                     'symlink_target', \
                     ]:
            attr_val = getattr(ie, attr, None)
            if attr == 'executable' and attr_val == 0:
                continue
            if attr == 'parent_id' and attr_val == b'TREE_ROOT':
                continue
            if attr_val is not None:
                s.add(attr, attr_val)
        writer.write_stanza(s)


def read_inventory(inv_file):
    """Read inventory object from rio formatted inventory file"""
    from breezy.bzr.inventory import Inventory, InventoryFile
    s = read_stanza(inv_file)
    assert s['inventory_version'] == 7
    inv = Inventory()
    for s in read_stanzas(inv_file):
        kind, file_id = s.items[0]
        parent_id = None
        if 'parent_id' in s:
            parent_id = s['parent_id']
        if kind == 'file':
            ie = InventoryFile(file_id, s['name'], parent_id)
            ie.text_sha1 = s['text_sha1']
            ie.text_size = s['text_size']
        else:
            raise NotImplementedError()
        inv.add(ie)
    return inv
