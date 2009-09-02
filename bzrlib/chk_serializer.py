# Copyright (C) 2008, 2009 Canonical Ltd
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

from bzrlib import (
    bencode,
    cache_utf8,
    inventory,
    revision as _mod_revision,
    xml6,
    xml7,
    )


def _validate_properties(props, _decode=cache_utf8._utf8_decode):
    # TODO: we really want an 'isascii' check for key
    # Cast the utf8 properties into Unicode 'in place'
    for key, value in props.iteritems():
        props[key] = _decode(value)[0]
    return props


def _is_format_10(value):
    if value != 10:
        raise ValueError('Format number was not recognized, expected 10 got %d'
                         % (value,))
    return 10


class BEncodeRevisionSerializer1(object):
    """Simple revision serializer based around bencode.
    """

    squashes_xml_invalid_characters = False

    # Maps {key:(Revision attribute, bencode_type, validator)}
    # This tells us what kind we expect bdecode to create, what variable on
    # Revision we should be using, and a function to call to validate/transform
    # the type.
    # TODO: add a 'validate_utf8' for things like revision_id and file_id
    #       and a validator for parent-ids
    _schema = {'format': (None, int, _is_format_10),
               'committer': ('committer', str, cache_utf8.decode),
               'timezone': ('timezone', int, None),
               'timestamp': ('timestamp', str, float),
               'revision-id': ('revision_id', str, None),
               'parent-ids': ('parent_ids', list, None),
               'inventory-sha1': ('inventory_sha1', str, None),
               'message': ('message', str, cache_utf8.decode),
               'properties': ('properties', dict, _validate_properties),
    }

    def write_revision_to_string(self, rev):
        encode_utf8 = cache_utf8._utf8_encode
        # Use a list of tuples rather than a dict
        # This lets us control the ordering, so that we are able to create
        # smaller deltas
        ret = [
            ("format", 10),
            ("committer", encode_utf8(rev.committer)[0]),
        ]
        if rev.timezone is not None:
            ret.append(("timezone", rev.timezone))
        # For bzr revisions, the most common property is just 'branch-nick'
        # which changes infrequently.
        revprops = {}
        for key, value in rev.properties.iteritems():
            revprops[key] = encode_utf8(value)[0]
        ret.append(('properties', revprops))
        ret.extend([
            ("timestamp", "%.3f" % rev.timestamp),
            ("revision-id", rev.revision_id),
            ("parent-ids", rev.parent_ids),
            ("inventory-sha1", rev.inventory_sha1),
            ("message", encode_utf8(rev.message)[0]),
        ])
        return bencode.bencode(ret)

    def write_revision(self, rev, f):
        f.write(self.write_revision_to_string(rev))

    def read_revision_from_string(self, text):
        # TODO: consider writing a Revision decoder, rather than using the
        #       generic bencode decoder
        #       However, to decode all 25k revisions of bzr takes approx 1.3s
        #       If we remove all extra validation that goes down to about 1.2s.
        #       Of that time, probably 0.6s is spend in bencode.bdecode().
        #       Regardless 'time bzr log' of everything is 7+s, so 1.3s to
        #       extract revision texts isn't a majority of time.
        ret = bencode.bdecode(text)
        if not isinstance(ret, list):
            raise ValueError("invalid revision text")
        schema = self._schema
        # timezone is allowed to be missing, but should be set
        bits = {'timezone': None}
        for key, value in ret:
            # Will raise KeyError if not a valid part of the schema, or an
            # entry is given 2 times.
            var_name, expected_type, validator = schema[key]
            if value.__class__ is not expected_type:
                raise ValueError('key %s did not conform to the expected type'
                                 ' %s, but was %s'
                                 % (key, expected_type, type(value)))
            if validator is not None:
                value = validator(value)
            bits[var_name] = value
        if len(bits) != len(schema):
            missing = [key for key, (var_name, _, _) in schema.iteritems()
                       if var_name not in bits]
            raise ValueError('Revision text was missing expected keys %s.'
                             ' text %r' % (missing, text))
        del bits[None]  # Get rid of 'format' since it doesn't get mapped
        rev = _mod_revision.Revision(**bits)
        return rev

    def read_revision(self, f):
        return self.read_revision_from_string(f.read())


class CHKSerializerSubtree(BEncodeRevisionSerializer1, xml7.Serializer_v7):
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
            return xml7.Serializer_v7._unpack_entry(self, elt)

    def __init__(self, node_size, search_key_name):
        self.maximum_size = node_size
        self.search_key_name = search_key_name


class CHKSerializer(xml6.Serializer_v6):
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
