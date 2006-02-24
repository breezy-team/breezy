# Copyright (C) 2006 Canonical

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

from urllib import unquote

from bzrlib.errors import UnknownSplatFormat, MalformedSplat

SPLATFILE_1_HEADER = "BZR Splatfile Format 1"
FORBIDDEN = ' \t\r\n%'

def write_splat(fileobj, pairs):
    fileobj.write(SPLATFILE_1_HEADER+'\n')
    for key, value in pairs:
        fileobj.write("%s %s\n" % (escape(key), escape(value)))


def escape(value):
    result = []
    for c in value.encode('UTF-8'):
        if c in FORBIDDEN:
            result.append('%%%.2x' % ord(c))
        else:
            result.append(c)
    return ''.join(result)


def read_splat(fileobj):
    header = fileobj.next().rstrip('\n')
    if header != SPLATFILE_1_HEADER:
        raise UnknownSplatFormat(header)
    for line in fileobj:
        try:
            key, value = line.rstrip('\n').split(' ')
        except ValueError:
            raise MalformedSplat(line)
        yield unescape(key), unescape(value)


def unescape(input):
    return unquote(input).decode('UTF-8')


def dump_dict(my_file, dict):
    write_splat(my_file, dict.iteritems())


def read_dict(my_file):
    result = {}
    for key, value in read_splat(my_file):
        result[key] = value
    return result
