# Copyright (C) 2009 Canonical Ltd
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

"""Pyrex implementation of _read_stanza_*."""

import re

from bzrlib.rio import Stanza

_tag_re = re.compile(r'^[-a-zA-Z0-9_]+$')
def _valid_tag(tag):
    return bool(_tag_re.match(tag))


def _read_stanza_utf8(line_iter):
    stanza = Stanza()
    tag = None
    accum_value = None

    # TODO: jam 20060922 This code should raise real errors rather than
    #       using 'assert' to process user input, or raising ValueError
    #       rather than a more specific error.
    for line in line_iter:
        if line is None or line == '':
            break       # end of file
        if line == '\n':
            break       # end of stanza
        real_l = line
        if line[0] == '\t': # continues previous value
            if tag is None:
                raise ValueError('invalid continuation line %r' % real_l)
            accum_value.append('\n' + line[1:-1])
        else: # new tag:value line
            if tag is not None:
                stanza.add(tag, ''.join(accum_value).decode('utf-8'))
            try:
                colon_index = line.index(': ')
            except ValueError:
                raise ValueError('tag/value separator not found in line %r'
                                 % real_l)
            tag = line[:colon_index]
            if not _valid_tag(tag):
                raise ValueError("invalid rio tag %r" % (tag,))
            accum_value = line[colon_index+2:-1]
    if tag is not None: # add last tag-value
        stanza.add(tag, ''.join(accum_value).decode('utf-8'))
        return stanza
    else:     # didn't see any content
        return None


def _read_stanza_unicode(unicode_iter):
    stanza = Stanza()
    tag = None
    accum_value = None

    # TODO: jam 20060922 This code should raise real errors rather than
    #       using 'assert' to process user input, or raising ValueError
    #       rather than a more specific error.
    for line in unicode_iter:
        if line is None or line == '':
            break       # end of file
        if line == '\n':
            break       # end of stanza
        real_l = line
        if line[0] == '\t': # continues previous value
            if tag is None:
                raise ValueError('invalid continuation line %r' % real_l)
            accum_value += '\n' + line[1:-1]
        else: # new tag:value line
            if tag is not None:
                stanza.add(tag, accum_value)
            try:
                colon_index = line.index(': ')
            except ValueError:
                raise ValueError('tag/value separator not found in line %r'
                                 % real_l)
            tag = str(line[:colon_index])
            if not _valid_tag(tag):
                raise ValueError("invalid rio tag %r" % (tag,))
            accum_value = line[colon_index+2:-1]

    if tag is not None: # add last tag-value
        stanza.add(tag, accum_value)
        return stanza
    else:     # didn't see any content
        return None


