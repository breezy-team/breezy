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
    rio,
    xml5,
    xml6,
    )

class RIORevisionSerializer1(object):
    """Simple line-based revision serializer. 
    
    This writes simple key/value pairs for all elements on the revision, 
    each on a separate line and using colons to separate key and value. Newlines
    are backslash-escaped where necessary.

    The commit message is always serialized last and can span multiple lines.
    """

    def write_revision(self, rev, f):
        decode_utf8 = cache_utf8.decode
        w = rio.RioWriter(f)
        s = rio.Stanza()
        revision_id = rev.revision_id
        if isinstance(revision_id, str):
            revision_id = decode_utf8(revision_id)
        s.add("revision-id", revision_id)
        s.add("timestamp", "%.3f" % rev.timestamp)
        if rev.parent_ids:
            s.add("parent-ids", 
                " ".join([decode_utf8(p) for p in rev.parent_ids]))
        s.add("inventory-sha1", rev.inventory_sha1)
        s.add("committer", rev.committer)
        if rev.timezone is not None:
            s.add("timezone", str(rev.timezone))
        if rev.properties:
            revprops_stanza = rio.Stanza()
            for k, v in rev.properties.iteritems():
                if isinstance(v, str):
                    v = decode_utf8(v)
                revprops_stanza.add(decode_utf8(k), v)
            s.add("properties", revprops_stanza.to_unicode())
        s.add("message", rev.message)
        w.write_stanza(s)

    def write_revision_to_string(self, rev):
        f = StringIO()
        self.write_revision(rev, f)
        return f.getvalue()

    def read_revision(self, f):
        s = rio.read_stanza(f)
        rev = _mod_revision.Revision(None)
        for (field, value) in s.iter_pairs():
            if field == "revision-id":
                rev.revision_id = cache_utf8.encode(value)
            elif field == "parent-ids":
                rev.parent_ids = [cache_utf8.encode(p) for p in value.split(" ")]
            elif field == "committer":
                rev.committer = value
            elif field == "inventory-sha1":
                rev.inventory_sha1 = value
            elif field == "timezone":
                rev.timezone = int(value)
            elif field == "timestamp":
                rev.timestamp = float(value)
            elif field == "message":
                rev.message = value
            elif field == "properties":
                rev.properties = rio.read_stanza_unicode(
                    osutils.split_lines(value)).as_dict()
            else:
                raise AssertionError("Unknown field %s" % field)
            l = f.readline()
        return rev

    def read_revision_from_string(self, xml_string):
        f = StringIO(xml_string)
        rev = self.read_revision(f)
        return rev


class CHKSerializerSubtree(RIORevisionSerializer1,xml6.Serializer_v6):
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


class CHKSerializer(RIORevisionSerializer1,xml5.Serializer_v5):
    """A CHKInventory based serializer with 'plain' behaviour."""

    format_num = '9'
    revision_format_num = None
    support_altered_by_hack = False

    def __init__(self, node_size, search_key_name):
        self.maximum_size = node_size
        self.search_key_name = search_key_name


chk_serializer_255_bigpage = CHKSerializer(65536, 'hash-255-way')
