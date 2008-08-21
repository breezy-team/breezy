# index2, a bzr plugin providing experimental index types.
# Copyright (C) 2008 Canonical Limited.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as published
# by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301 USA
#

"""B+Tree index parsing."""

def _parse_leaf_lines(bytes, key_length, ref_list_length):
    lines = bytes.split('\n')
    nodes = []
    for line in lines[1:]:
        if line == '':
            return nodes
        elements = line.split('\0', key_length)
        # keys are tuples
        key = tuple(elements[:key_length])
        line = elements[-1]
        references, value = line.rsplit('\0', 1)
        if ref_list_length:
            ref_lists = []
            for ref_string in references.split('\t'):
                ref_lists.append(tuple([
                    tuple(ref.split('\0')) for ref in ref_string.split('\r') if ref
                    ]))
            ref_lists = tuple(ref_lists)
            node_value = (value, ref_lists)
        else:
            node_value = (value, ())
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
        flattened_references = ['\r'.join(['\x00'.join(reference)
                                           for reference in ref_list])
                                for ref_list in node[3]]
    else:
        flattened_references = []
    string_key = '\x00'.join(node[1])
    line = ("%s\x00%s\x00%s\n" % (string_key,
        '\t'.join(flattened_references), node[2]))
    return string_key, line
