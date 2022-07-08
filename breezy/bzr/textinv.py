# Copyright (C) 2005 Canonical Ltd
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

from .errors import BzrError
from .inventory import Inventory


START_MARK = "# bzr inventory format 3\n"
END_MARK = "# end of inventory\n"


def escape(s):
    """Very simple URL-like escaping.

    (Why not just use backslashes?  Because then we couldn't parse
    lines just by splitting on spaces.)"""
    return (s.replace('\\', r'\x5c')
            .replace(' ', r'\x20')
            .replace('\t', r'\x09')
            .replace('\n', r'\x0a'))


def unescape(s):
    if s.find(' ') != -1:
        raise AssertionError()
    s = (s.replace(r'\x20', ' ')
         .replace(r'\x09', '\t')
         .replace(r'\x0a', '\n')
         .replace(r'\x5c', '\\'))

    # TODO: What if there's anything else?

    return s


def write_text_inventory(inv, outf):
    """Write out inv in a simple trad-unix text format."""
    outf.write(START_MARK)
    for path, ie in inv.iter_entries():
        if inv.is_root(ie.file_id):
            continue

        outf.write(ie.file_id + ' ')
        outf.write(escape(ie.name) + ' ')
        outf.write(ie.kind + ' ')
        outf.write(ie.parent_id + ' ')

        if ie.kind == 'file':
            outf.write(ie.text_id)
            outf.write(' ' + ie.text_sha1)
            outf.write(' ' + str(ie.text_size))
        outf.write("\n")
    outf.write(END_MARK)


def read_text_inventory(tf):
    """Return an inventory read in from tf"""
    if tf.readline() != START_MARK:
        raise BzrError("missing start mark")

    inv = Inventory()

    for l in tf:
        fields = l.split(' ')
        if fields[0] == '#':
            break
        ie = {'file_id': fields[0],
              'name': unescape(fields[1]),
              'kind': fields[2],
              'parent_id': fields[3]}
        # inv.add(ie)

    if l != END_MARK:
        raise BzrError("missing end mark")
    return inv
