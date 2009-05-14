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

#python2.4 support
cdef extern from "python-compat.h":
    pass

cdef extern from "Python.h":
    ctypedef int Py_ssize_t # Required for older pyrex versions
    char *PyString_AS_STRING(object s)
    Py_ssize_t PyString_GET_SIZE(object t)

cdef extern from "ctype.h":
     int isalnum(char c)

from bzrlib.rio import Stanza

def _valid_tag(tag):
    cdef char *c_tag
    cdef int c_len
    c_tag = PyString_AS_STRING(tag)
    c_len = PyString_GET_SIZE(tag)
    for i from 0 <= i < c_len:
        if (not isalnum(c_tag[i]) and not c_tag[i] == c'_' and 
            not c_tag[i] == c'-'):
            return False
    return True


def _read_stanza_utf8(line_iter):
    pairs = []
    tag = None
    accum_value = []

    # TODO: jam 20060922 This code should raise real errors rather than
    #       using 'assert' to process user input, or raising ValueError
    #       rather than a more specific error.
    for line in line_iter:
        if line is None or line == '':
            break       # end of file
        if line == '\n':
            break       # end of stanza
        if line[0] == '\t': # continues previous value
            if tag is None:
                raise ValueError('invalid continuation line %r' % line)
            accum_value.append('\n' + line[1:-1])
        else: # new tag:value line
            if tag is not None:
                pairs.append((tag, ''.join(accum_value).decode('utf-8')))
            try:
                colon_index = line.index(': ')
            except ValueError:
                raise ValueError('tag/value separator not found in line %r'
                                 % line)
            tag = line[:colon_index]
            #if not _valid_tag(tag):
            #    raise ValueError("invalid rio tag %r" % (tag,))
            accum_value = [line[colon_index+2:-1]]
    if tag is not None: # add last tag-value
        pairs.append((tag, ''.join(accum_value).decode('utf-8')))
        return Stanza.from_pairs(pairs)
    else:     # didn't see any content
        return None


def _read_stanza_unicode(unicode_iter):
    pairs = []
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
                pairs.append((tag, accum_value))
            try:
                colon_index = line.index(': ')
            except ValueError:
                raise ValueError('tag/value separator not found in line %r'
                                 % real_l)
            tag = str(line[:colon_index])
            #if not _valid_tag(tag):
            #    raise ValueError("invalid rio tag %r" % (tag,))
            accum_value = line[colon_index+2:-1]

    if tag is not None: # add last tag-value
        pairs.append((tag, accum_value))
        return Stanza.from_pairs(pairs)
    else:     # didn't see any content
        return None


