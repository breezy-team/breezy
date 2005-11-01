# Copyright (C) 2005 by Canonical Ltd
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""basic_io - simple text metaformat

The stored data consists of a series of *stanzas*, each of which contains
*fields* identified by an ascii name.  The contents of each field can be
either an integer (scored in decimal) or a Unicode string.
"""

import re

# XXX: basic_io is kind of a dumb name; it seems to imply an io layer not a
# format
#
# XXX: should these be BasicIOWriter, etc?
#
# XXX: some redundancy is allowing to write stanzas in isolation as well as
# through a writer object.  also a bit confused to have a StanzaWriter but to 
# have parsing done inside the Stanza.

class BasicWriter(object):
    def __init__(self, to_file):
        self._soft_nl = False
        self._to_file = to_file

    def write_stanza(self, stanza):
        if self._soft_nl:
            print >>self._to_file
        stanza.write(self._to_file)
        self._soft_nl = True


class BasicReader(object):
    """Read stanzas from a file as a sequence
    
    to_file can be anything that can be enumerated as a sequence of 
    lines (with newlines.)
    """
    def __init__(self, from_file):
        self._from_file = from_file

    def __iter__(self):
        while True:
            s = Stanza.from_file(self._from_file)
            if s is None:
                break
            else:
                yield s


class _StanzaWriter(object):
    """Convert Stanza to external form."""
    def __init__(self, items):
        self.items = items

    def to_lines(self):
        indent = max(len(kv[0]) for kv in self.items)
        for tag, value in self.items:
            if isinstance(value, (int, long)):
                # must use %d so bools are written as ints
                yield '%*s %d\n' % (indent, tag, value)
            elif isinstance(value, (str, unicode)):
                yield '%*s %s\n' % (indent, tag, self.quote_string(value))
            else:
                raise ValueError("invalid value %r" % value)

    def quote_string(self, value):
        qv = value.replace('\\', r'\\') \
                  .replace('"', r'\"') 
        return '"' + qv + '"'


class Stanza(object):
    """One stanza for basic_io.

    Each stanza contains a set of named fields.  
    
    Names must be non-empty ascii alphanumeric plus _.  Names can be repeated
    within a stanza.  Names are case-sensitive.  The ordering of fields is
    preserved.

    Each field value must be either an int or a string.
    """

    def __init__(self, **kwargs):
        """Construct a new Stanza.

        The keyword arguments, if any, are added in sorted order to the stanza.
        """
        self.items = list()
        if kwargs:
            for tag, value in sorted(kwargs.items()):
                self.add(tag, value)

    def add(self, tag, value):
        """Append a name and value to the stanza."""
        if not valid_tag(tag):
            raise ValueError("invalid tag %r" % tag)
        if not isinstance(value, (int, long, str, unicode)):
            raise ValueError("invalid value %r" % value)
        self.items.append((tag, value))
        
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
        """Generate sequence of lines for external version of this file."""
        return _StanzaWriter(self.items).to_lines()

    def to_string(self):
        """Return stanza as a single string"""
        return ''.join(self.to_lines())

    def write(self, to_file):
        """Write stanza to a file"""
        to_file.writelines(self.to_lines())

    @classmethod
    def from_lines(klass, from_lines):
        """Return new Stanza read from list of lines"""
        self = klass()
        line_iter = from_lines #  iter(from_lines)
        first = True
        for l in line_iter:
            assert l[-1] == '\n'
            if l == None or l == '' or l == '\n':
                break
            first = False
            tag, rest = l.split(None, 1)
            assert valid_tag(tag), \
                    "invalid basic_io tag %r" % tag
            if rest[0] == '"':
                # keep reading in lines, accumulating into value, until we're done
                assert rest[-2] == '"'
                value = rest[1:-2]
                # line_values = []
##                 while True:
##                     content, end = self._parse_string_line(line)
##                     line_values.append(content)
##                     if end: 
##                         break
##                     try:
##                         line = line_iter.next()
##                     except StopIteration:
##                         raise ValueError('unexpected end in quoted string %r' % value)
##                 value = ''.join(line_values)
            elif rest[0] in '-0123456789':
                value = int(rest)
            else:
                raise ValueError("invalid basic_io line %r" % l)
            self.items.append((tag, value))
        if first:
            return None         # didn't see any content
        else:
            return self

    def _parse_string_line(self, line):
        """Read one line of a quoted string.

        The line always has the trailing newline still present.

        Returns parsed unquoted content, and a flag saying whether we've got
        to the end of the string.

        Lines end if they have a doublequote at the end which is not escaped; 
        """
        # lines can only possibly end if they finish with a doublequote;
        # but they only end there if it's not quoted
        # Is iterating every character too slow in Python?
        assert line[-1] == '\n'
        # hack for testing - lines must be single lines
        assert line[-2] == '"'
        return line[:-2].replace(r'\"', '"').replace(r'\\', '\\'), True
        r = ''
        l = len(line)
        quotech = False
        for i in range(l-2):
            c = line[i]
            if quotech:
                assert c in r'\"'
                r += c
                quotech = False
            elif c == '\\':
                quotech = True       
            else:
                quotech = False
                r += c
        # last non-newline character
        i += 1
        c = line[i]
        if quotech:
            assert c in r'\"'
            r += c + '\n'
        elif c == '"':
            # omit quote and newline, finished string
            return r, True
        else:
            assert c != '\\'
            r += c + '\n'
        return r, False

    @classmethod
    def from_file(klass, from_file):
        """Return new Stanza read from a file.

        This consumes the blank line following the stanza, if there is one.
        """
        return klass.from_lines(from_file)

    @classmethod
    def from_string(klass, s):
        return klass.from_lines(s.splitlines(True))

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
         
TAG_RE = re.compile(r'^[-a-zA-Z0-9_]+$')
def valid_tag(tag):
    return bool(TAG_RE.match(tag))


############################################################

# XXX: Move these to object serialization code. 

def write_revision(writer, revision):
    s = Stanza(revision=revision.revision_id,
               committer=revision.committer, 
               timezone=long(revision.timezone),
               timestamp=long(revision.timestamp),
               inventory_sha1=revision.inventory_sha1)
    for parent_id in revision.parent_ids:
        s.add('parent', parent_id)
    for prop_name, prop_value in revision.properties.items():
        s.add(prop_name, prop_value)
    s.write(writer)

def write_inventory(writer, inventory):
    s = Stanza(inventory_version=7)
    writer.write_stanza(s)

    for path, ie in inventory.iter_entries():
        s = Stanza()
        s.add(ie.kind, ie.file_id)
        for attr in ['name', 'parent_id', 'revision',
                     'text_sha1', 'text_size', 'executable', 'symlink_target',
                     ]:
            attr_val = getattr(ie, attr, None)
            if attr == 'executable' and attr_val == 0:
                continue
            if attr == 'parent_id' and attr_val == 'TREE_ROOT':
                continue
            if attr_val is not None:
                s.add(attr, attr_val)
        writer.write_stanza(s)


def read_inventory(inv_file):
    """Read inventory object from basic_io formatted inventory file"""
    from bzrlib.inventory import Inventory, InventoryFile
    s = Stanza.from_file(inv_file)
    assert s['inventory_version'] == 7
    inv = Inventory()
    for s in BasicReader(inv_file):
        kind, file_id = s.items[0]
        parent_id = None
        if 'parent_id' in s:
            parent_id = s['parent_id']
        if kind == 'file':
            ie = InventoryFile(file_id, s['name'], parent_id)
        else:
            raise NotImplementedError()
        inv.add(ie)
    return inv
