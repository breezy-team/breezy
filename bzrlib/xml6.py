from bzrlib import cache_utf8, inventory, errors, xml5


class Serializer_v6(xml5.Serializer_v5):

    def _append_inventory_root(self, append, inv):
        """Append the inventory root to output."""
        append('<inventory')
        append(' format="6"')
        if inv.revision_id is not None:
            append(' revision_id="')
            append(xml5._encode_and_escape(inv.revision_id))
        append('>\n')
        self._append_entry(append, inv.root)

    def _parent_condition(self, ie):
        return ie.parent_id is not None

    def _unpack_inventory(self, elt):
        """Construct from XML Element"""
        if elt.tag != 'inventory':
            raise errors.UnexpectedInventoryFormat('Root tag is %r' % elt.tag)
        format = elt.get('format')
        if format != '6':
            raise errors.UnexpectedInventoryFormat('Invalid format version %r'
                                                   % format)
        revision_id = elt.get('revision_id')
        if revision_id is not None:
            revision_id = cache_utf8.get_cached_unicode(revision_id)
        inv = inventory.Inventory(root_id=None, revision_id=revision_id)
        for e in elt:
            ie = self._unpack_entry(e, none_parents=True)
            inv.add(ie)
        return inv


serializer_v6 = Serializer_v6()
