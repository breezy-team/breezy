# Copyright (C) 2008, 2009, 2010 Canonical Ltd
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
#

"""B+Tree index parsing."""

from . import static_tuple


def _parse_leaf_lines(data, key_length, ref_list_length):
    lines = data.split(b'\n')
    nodes = []
    as_st = static_tuple.StaticTuple.from_sequence
    stuple = static_tuple.StaticTuple
    for line in lines[1:]:
        if line == b'':
            return nodes
        elements = line.split(b'\0', key_length)
        # keys are tuples
        key = as_st(elements[:key_length]).intern()
        line = elements[-1]
        references, value = line.rsplit(b'\0', 1)
        if ref_list_length:
            ref_lists = []
            for ref_string in references.split(b'\t'):
                ref_list = as_st([as_st(ref.split(b'\0')).intern()
                                  for ref in ref_string.split(b'\r') if ref])
                ref_lists.append(ref_list)
            ref_lists = as_st(ref_lists)
            node_value = stuple(value, ref_lists)
        else:
            node_value = stuple(value, stuple())
        # No need for StaticTuple here as it is put into a dict
        nodes.append((key, node_value))
    return nodes


def _flatten_node(node, reference_lists):
    """Convert a node into the serialized form.

    :param node: A tuple representing a node (key_tuple, value, references)
    :param reference_lists: Does this index have reference lists?
    :return: (string_key, flattened)
        string_key  The serialized key for referencing this node
        flattened   A string with the serialized form for the contents
    """
    if reference_lists:
        # TODO: Consider turning this back into the 'unoptimized' nested loop
        #       form. It is probably more obvious for most people, and this is
        #       just a reference implementation.
        flattened_references = [b'\r'.join([b'\x00'.join(reference)
                                            for reference in ref_list])
                                for ref_list in node[3]]
    else:
        flattened_references = []
    string_key = b'\x00'.join(node[1])
    line = (b"%s\x00%s\x00%s\n" % (string_key,
                                   b'\t'.join(flattened_references), node[2]))
    return string_key, line
