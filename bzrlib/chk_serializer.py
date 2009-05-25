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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Serializer object for CHK based inventory storage."""

from cStringIO import (
    StringIO,
    )

from bzrlib import (
    cache_utf8,
    inventory,
    osutils,
    revision as _mod_revision,
    xml5,
    xml6,
    )
from bzrlib.util.bencode import (
    bdecode,
    bencode,
    )

class BEncodeRevisionSerializer1(object):
    """Simple revision serializer based around bencode. 
    
    It tries to group entries together that are less likely
    to change often, to make it easier to do compression.
    """

    def write_revision_to_string(self, rev):
        encode_utf8 = cache_utf8.encode
        ret = {
            "revision-id": rev.revision_id,
            "timestamp": "%.3f" % rev.timestamp,
            "parent-ids": rev.parent_ids,
            "inventory-sha1": rev.inventory_sha1,
            "committer": encode_utf8(rev.committer),
            "message": encode_utf8(rev.message),
            }
        revprops = {}
        for key, value in rev.properties.iteritems():
            revprops[key] = encode_utf8(value)
        ret["properties"] = revprops
        if rev.timezone is not None:
            ret["timezone"] = str(rev.timezone)
        return bencode(ret)

    def write_revision(self, rev, f):
        f.write(self.write_revision_to_string(rev))

    def read_revision_from_string(self, text):
        decode_utf8 = cache_utf8.decode
        ret = bdecode(text)
        rev = _mod_revision.Revision(
            committer=decode_utf8(ret["committer"]),
            revision_id=ret["revision-id"],
            parent_ids=ret["parent-ids"],
            inventory_sha1=ret["inventory-sha1"],
            timestamp=float(ret["timestamp"]),
            message=decode_utf8(ret["message"]),
            properties={})
        if "timezone" in ret:
            rev.timezone = int(ret["timezone"])
        else:
            rev.timezone = None
        for key, value in ret["properties"].iteritems():
            rev.properties[key] = decode_utf8(value)
        return rev

    def read_revision(self, f):
        return self.read_revision_from_string(f.read())


class CHKSerializerSubtree(BEncodeRevisionSerializer1, xml6.Serializer_v6):
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

    def __init__(self, node_size, search_key_name):
        self.maximum_size = node_size
        self.search_key_name = search_key_name


class CHKSerializer(xml5.Serializer_v5):
    """A CHKInventory based serializer with 'plain' behaviour."""

    format_num = '9'
    revision_format_num = None
    support_altered_by_hack = False

    def __init__(self, node_size, search_key_name):
        self.maximum_size = node_size
        self.search_key_name = search_key_name


chk_serializer_255_bigpage = CHKSerializer(65536, 'hash-255-way')


class CHKBEncodeSerializer(BEncodeRevisionSerializer1, CHKSerializer):
    """A CHKInventory and BEncode based serializer with 'plain' behaviour."""

    format_num = '10'


chk_bencode_serializer = CHKBEncodeSerializer(65536, 'hash-255-way')
