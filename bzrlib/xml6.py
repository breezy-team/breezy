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

from bzrlib import cache_utf8, inventory, errors, xml5


class Serializer_v6(xml5.Serializer_v5):

    format_num = '6'

    def _append_inventory_root(self, append, inv):
        """Append the inventory root to output."""
        append('<inventory')
        append(' format="%s"' % self.format_num)
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
        if format != self.format_num:
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
