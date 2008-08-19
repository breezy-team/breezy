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
