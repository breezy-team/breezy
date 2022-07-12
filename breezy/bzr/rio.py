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

# \subsection{\emph{rio} - simple text metaformat}
#
# \emph{r} stands for `restricted', `reproducible', or `rfc822-like'.
#
# The stored data consists of a series of \emph{stanzas}, each of which contains
# \emph{fields} identified by an ascii name, with Unicode or string contents.
# The field tag is constrained to alphanumeric characters.
# There may be more than one field in a stanza with the same name.
#
# The format itself does not deal with character encoding issues, though
# the result will normally be written in Unicode.
#
# The format is intended to be simple enough that there is exactly one character
# stream representation of an object and vice versa, and that this relation
# will continue to hold for future versions of bzr.

import re

from .. import osutils
from ..iterablefile import IterableFile

# XXX: some redundancy is allowing to write stanzas in isolation as well as
# through a writer object.


class RioWriter(object):

    def __init__(self, to_file):
        self._soft_nl = False
        self._to_file = to_file

    def write_stanza(self, stanza):
        if self._soft_nl:
            self._to_file.write(b'\n')
        stanza.write(self._to_file)
        self._soft_nl = True


class RioReader(object):
    """Read stanzas from a file as a sequence

    to_file can be anything that can be enumerated as a sequence of
    lines (with newlines.)
    """

    def __init__(self, from_file):
        self._from_file = from_file

    def __iter__(self):
        while True:
            s = read_stanza(self._from_file)
            if s is None:
                break
            else:
                yield s


def rio_file(stanzas, header=None):
    """Produce a rio IterableFile from an iterable of stanzas"""
    def str_iter():
        if header is not None:
            yield header + b'\n'
        first_stanza = True
        for s in stanzas:
            if first_stanza is not True:
                yield b'\n'
            for line in s.to_lines():
                yield line
            first_stanza = False
    return IterableFile(str_iter())


def read_stanzas(from_file):

    while True:
        s = read_stanza(from_file)
        if s is None:
            break
        yield s


class Stanza(object):
    """One stanza for rio.

    Each stanza contains a set of named fields.

    Names must be non-empty ascii alphanumeric plus _.  Names can be repeated
    within a stanza.  Names are case-sensitive.  The ordering of fields is
    preserved.

    Each field value must be either an int or a string.
    """

    __slots__ = ['items']

    def __init__(self, **kwargs):
        """Construct a new Stanza.

        The keyword arguments, if any, are added in sorted order to the stanza.
        """
        self.items = []
        if kwargs:
            for tag, value in sorted(kwargs.items()):
                self.add(tag, value)

    def add(self, tag, value):
        """Append a name and value to the stanza."""
        if not valid_tag(tag):
            raise ValueError("invalid tag %r" % (tag,))
        if isinstance(value, bytes):
            pass
        elif isinstance(value, str):
            pass
        elif isinstance(value, Stanza):
            pass
        else:
            raise TypeError("invalid type for rio value: %r of type %s"
                            % (value, type(value)))
        self.items.append((tag, value))

    @classmethod
    def from_pairs(cls, pairs):
        ret = cls()
        ret.items = pairs
        return ret

    def __contains__(self, find_tag):
        """True if there is any field in this stanza with the given tag."""
        for tag, value in self.items:
            if tag == find_tag:
                return True
        return False

    def __len__(self):
        """Return number of pairs in the stanza."""
        return len(self.items)

    def __eq__(self, other):
        if not isinstance(other, Stanza):
            return False
        return self.items == other.items

    def __ne__(self, other):
        return not self.__eq__(other)

    def __repr__(self):
        return "Stanza(%r)" % self.items

    def iter_pairs(self):
        """Return iterator of tag, value pairs."""
        return iter(self.items)

    def to_lines(self):
        """Generate sequence of lines for external version of this file.

        The lines are always utf-8 encoded strings.
        """
        if not self.items:
            # max() complains if sequence is empty
            return []
        result = []
        for text_tag, text_value in self.items:
            tag = text_tag.encode('ascii')
            if isinstance(text_value, str):
                value = text_value.encode('utf-8', 'surrogateescape')
            elif isinstance(text_value, Stanza):
                value = text_value.to_string()
            else:
                value = text_value
            if value == b'':
                result.append(tag + b': \n')
            elif b'\n' in value:
                # don't want splitlines behaviour on empty lines
                val_lines = value.split(b'\n')
                result.append(tag + b': ' + val_lines[0] + b'\n')
                for line in val_lines[1:]:
                    result.append(b'\t' + line + b'\n')
            else:
                result.append(tag + b': ' + value + b'\n')
        return result

    def to_string(self):
        """Return stanza as a single string"""
        return b''.join(self.to_lines())

    def write(self, to_file):
        """Write stanza to a file"""
        to_file.writelines(self.to_lines())

    def get(self, tag):
        """Return the value for a field wih given tag.

        If there is more than one value, only the first is returned.  If the
        tag is not present, KeyError is raised.
        """
        for t, v in self.items:
            if t == tag:
                return v
        else:
            raise KeyError(tag)

    __getitem__ = get

    def get_all(self, tag):
        r = []
        for t, v in self.items:
            if t == tag:
                r.append(v)
        return r

    def as_dict(self):
        """Return a dict containing the unique values of the stanza.
        """
        d = {}
        for tag, value in self.items:
            d[tag] = value
        return d


def valid_tag(tag):
    return _valid_tag(tag)


def read_stanza(line_iter):
    """Return new Stanza read from list of lines or a file

    Returns one Stanza that was read, or returns None at end of file.  If a
    blank line follows the stanza, it is consumed.  It's not an error for
    there to be no blank at end of file.  If there is a blank file at the
    start of the input this is really an empty stanza and that is returned.

    Only the stanza lines and the trailing blank (if any) are consumed
    from the line_iter.

    The raw lines must be in utf-8 encoding.
    """
    return _read_stanza_utf8(line_iter)


def to_patch_lines(stanza, max_width=72):
    """Convert a stanza into RIO-Patch format lines.

    RIO-Patch is a RIO variant designed to be e-mailed as part of a patch.
    It resists common forms of damage such as newline conversion or the removal
    of trailing whitespace, yet is also reasonably easy to read.

    :param max_width: The maximum number of characters per physical line.
    :return: a list of lines
    """
    if max_width <= 6:
        raise ValueError(max_width)
    max_rio_width = max_width - 4
    lines = []
    for pline in stanza.to_lines():
        for line in pline.split(b'\n')[:-1]:
            line = re.sub(b'\\\\', b'\\\\\\\\', line)
            while len(line) > 0:
                partline = line[:max_rio_width]
                line = line[max_rio_width:]
                if len(line) > 0 and line[:1] != [b' ']:
                    break_index = -1
                    break_index = partline.rfind(b' ', -20)
                    if break_index < 3:
                        break_index = partline.rfind(b'-', -20)
                        break_index += 1
                    if break_index < 3:
                        break_index = partline.rfind(b'/', -20)
                    if break_index >= 3:
                        line = partline[break_index:] + line
                        partline = partline[:break_index]
                if len(line) > 0:
                    line = b'  ' + line
                partline = re.sub(b'\r', b'\\\\r', partline)
                blank_line = False
                if len(line) > 0:
                    partline += b'\\'
                elif re.search(b' $', partline):
                    partline += b'\\'
                    blank_line = True
                lines.append(b'# ' + partline + b'\n')
                if blank_line:
                    lines.append(b'#   \n')
    return lines


def _patch_stanza_iter(line_iter):
    map = {b'\\\\': b'\\',
           b'\\r': b'\r',
           b'\\\n': b''}

    def mapget(match):
        return map[match.group(0)]

    last_line = None
    for line in line_iter:
        if line.startswith(b'# '):
            line = line[2:]
        elif line.startswith(b'#'):
            line = line[1:]
        else:
            raise ValueError("bad line %r" % (line,))
        if last_line is not None and len(line) > 2:
            line = line[2:]
        line = re.sub(b'\r', b'', line)
        line = re.sub(b'\\\\(.|\n)', mapget, line)
        if last_line is None:
            last_line = line
        else:
            last_line += line
        if last_line[-1:] == b'\n':
            yield last_line
            last_line = None
    if last_line is not None:
        yield last_line


def read_patch_stanza(line_iter):
    """Convert an iterable of RIO-Patch format lines into a Stanza.

    RIO-Patch is a RIO variant designed to be e-mailed as part of a patch.
    It resists common forms of damage such as newline conversion or the removal
    of trailing whitespace, yet is also reasonably easy to read.

    :return: a Stanza
    """
    return read_stanza(_patch_stanza_iter(line_iter))


try:
    from ._rio_pyx import (
        _read_stanza_utf8,
        )
    from ._rio_rs import (
        _valid_tag,
        )
except ImportError as e:
    osutils.failed_to_load_extension(e)
    from ._rio_py import (
        _read_stanza_utf8,
        _valid_tag,
        )
