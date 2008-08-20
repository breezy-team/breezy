# Copyright (C) 2005, 2006, 2007, 2008 Canonical Ltd
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

from bzrlib import (
    cache_utf8,
    inventory,
    xml6,
    xml8,
    )

class Serializer_v5(xml6.Serializer_v6):
    """Version 5 serializer

    Packs objects into XML and vice versa.
    """
    format_num = '5'
    root_id = inventory.ROOT_ID

    def _unpack_inventory(self, elt, revision_id):
        """Construct from XML Element
        """
        root_id = elt.get('file_id') or inventory.ROOT_ID
        root_id = xml8._get_utf8_or_ascii(root_id)

        format = elt.get('format')
        if format is not None:
            if format != '5':
                raise BzrError("invalid format version %r on inventory"
                                % format)
        data_revision_id = elt.get('revision_id')
        if data_revision_id is not None:
            revision_id = cache_utf8.encode(data_revision_id)
        inv = inventory.Inventory(root_id, revision_id=revision_id)
        for e in elt:
            ie = self._unpack_entry(e)
            if ie.parent_id is None:
                ie.parent_id = root_id
            inv.add(ie)
        if revision_id is not None:
            inv.root.revision = revision_id
        return inv

    def _check_revisions(self, inv):
        """Extension point for subclasses to check during serialisation.

        In this version, no checking is done.

        :param inv: An inventory about to be serialised, to be checked.
        :raises: AssertionError if an error has occured.
        """

    def _append_inventory_root(self, append, inv):
        """Append the inventory root to output."""
        if inv.root.file_id not in (None, inventory.ROOT_ID):
            fileid1 = ' file_id="'
            fileid2 = xml8._encode_and_escape(inv.root.file_id)
        else:
            fileid1 = ""
            fileid2 = ""
        if inv.revision_id is not None:
            revid1 = ' revision_id="'
            revid2 = xml8._encode_and_escape(inv.revision_id)
        else:
            revid1 = ""
            revid2 = ""
        append('<inventory%s%s format="5"%s%s>\n' % (
            fileid1, fileid2, revid1, revid2))


serializer_v5 = Serializer_v5()
