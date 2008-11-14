# Copyright (C) 2008 Canonical Ltd
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

"""Serializer object for CHK based inventory storage."""

from bzrlib import (
    inventory,
    xml5,
    xml6,
    )


class CHKSerializerSubtree(xml6.Serializer_v6):
    """A CHKInventory based serializer that supports tree references"""

    supported_kinds = set(['file', 'directory', 'symlink', 'tree-reference'])
    format_num = '9'
    revision_format_num = None
    support_altered_by_hack = False

    def _unpack_entry(self, elt):
        kind = elt.tag
        if not kind in self.supported_kinds:
            raise AssertionError('unsupported entry kind %s' % kind)
        if kind == 'tree-reference':
            file_id = elt.attrib['file_id']
            name = elt.attrib['name']
            parent_id = elt.attrib['parent_id']
            revision = elt.get('revision')
            reference_revision = elt.get('reference_revision')
            return inventory.TreeReference(file_id, name, parent_id, revision,
                                           reference_revision)
        else:
            return xml6.Serializer_v6._unpack_entry(self, elt)

    def __init__(self, node_size, parent_id_basename_index):
        self.maximum_size = node_size
        self.parent_id_basename_index = parent_id_basename_index


class CHKSerializer(xml5.Serializer_v5):
    """A CHKInventory based serializer with 'plain' behaviour."""

    format_num = '9'
    revision_format_num = None
    support_altered_by_hack = False

    def __init__(self, node_size, parent_id_basename_index):
        self.maximum_size = node_size
        self.parent_id_basename_index = parent_id_basename_index


chk_serializer_subtree = CHKSerializerSubtree(4096, False)
chk_serializer = CHKSerializer(4096, False)
chk_serializer_subtree_parent_id = CHKSerializerSubtree(4096, True)
chk_serializer_parent_id = CHKSerializer(4096, True)
