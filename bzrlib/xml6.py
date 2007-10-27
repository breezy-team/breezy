# Copyright (C) 2005, 2006, 2007 Canonical Ltd
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
    """This serialiser adds rich roots."""

    format_num = '6'
    root_id = None

    def _append_inventory_root(self, append, inv):
        """Append the inventory root to output."""
        if inv.revision_id is not None:
            revid1 = ' revision_id="'
            revid2 = xml5._encode_and_escape(inv.revision_id)
        else:
            revid1 = ""
            revid2 = ""
        append('<inventory format="%s"%s%s>\n' % (
            self.format_num, revid1, revid2))
        append('<directory file_id="%s name="%s revision="%s />\n' % (
            xml5._encode_and_escape(inv.root.file_id),
            xml5._encode_and_escape(inv.root.name),
            xml5._encode_and_escape(inv.root.revision)))

    def _check_revisions(self, inv):
        """Extension point for subclasses to check during serialisation.

        By default no checking is done.

        :param inv: An inventory about to be serialised, to be checked.
        :raises: AssertionError if an error has occured.
        """
        assert inv.revision_id is not None
        assert inv.root.revision is not None

    def _unpack_inventory(self, elt, revision_id=None):
        """Construct from XML Element"""
        if elt.tag != 'inventory':
            raise errors.UnexpectedInventoryFormat('Root tag is %r' % elt.tag)
        format = elt.get('format')
        if format != self.format_num:
            raise errors.UnexpectedInventoryFormat('Invalid format version %r'
                                                   % format)
        revision_id = elt.get('revision_id')
        if revision_id is not None:
            revision_id = cache_utf8.encode(revision_id)
        inv = inventory.Inventory(root_id=None, revision_id=revision_id)
        for e in elt:
            ie = self._unpack_entry(e)
            inv.add(ie)
        assert inv.root.revision is not None
        return inv


serializer_v6 = Serializer_v6()
