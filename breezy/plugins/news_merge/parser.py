# Copyright (C) 2010 Canonical Ltd
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

"""Simple parser for bzr's NEWS file.

Simple as this is, it's a bit over-powered for news_merge's needs, which only
cares about 'bullet' and 'everything else'.

This module can be run as a standalone Python program; pass it a filename and
it will print the parsed form of a file (a series of 2-tuples, see
simple_parse's docstring).
"""

def simple_parse_lines(lines):
    """Same as simple_parse, but takes an iterable of strs rather than a single
    str.
    """
    return simple_parse(''.join(lines))


def simple_parse(content):
    """Returns blocks, where each block is a 2-tuple (kind, text).

    :kind: one of 'heading', 'release', 'section', 'empty' or 'text'.
    :text: a str, including newlines.
    """
    blocks = content.split('\n\n')
    for block in blocks:
        if block.startswith('###'):
            # First line is ###...: Top heading
            yield 'heading', block
            continue
        last_line = block.rsplit('\n', 1)[-1]
        if last_line.startswith('###'):
            # last line is ###...: 2nd-level heading
            yield 'release', block
        elif last_line.startswith('***'):
            # last line is ***...: 3rd-level heading
            yield 'section', block
        elif block.startswith('* '):
            # bullet
            yield 'bullet', block
        elif block.strip() == '':
            # empty
            yield 'empty', block
        else:
            # plain text
            yield 'text', block


if __name__ == '__main__':
    import sys
    with open(sys.argv[1], 'rb') as f:
        content = f.read()
    for result in simple_parse(content):
        print(result)
