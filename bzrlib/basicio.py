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
# XXX: some redundancy is allowing to write stanzas in isolation as well as
# through a writer object.  

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
            s = read_stanza(self._from_file)
            if s is None:
                break
            else:
                yield s

def read_stanzas(from_file):
    while True:
        s = read_stanza(from_file)
        if s is None:
            break
        else:
            yield s

class Stanza(object):
    """One stanza for basic_io.

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
        if kwargs:
            self.items = sorted(kwargs.items())
        else:
            self.items = []

    def add(self, tag, value):
        """Append a name and value to the stanza."""
##         if not valid_tag(tag):
##             raise ValueError("invalid tag %r" % tag)
##         if not isinstance(value, (int, long, str, unicode)):
##             raise ValueError("invalid value %r" % value)
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
        if not self.items:
            # max() complains if sequence is empty
            return 
        indent = max(len(kv[0]) for kv in self.items)
        for tag, value in self.items:
            if isinstance(value, (int, long)):
                # must use %d so bools are written as ints
                yield '%*s %d\n' % (indent, tag, value)
            else:
                assert isinstance(value, (str, unicode)), ("invalid value %r" % value)
                qv = value.replace('\\', r'\\') \
                          .replace('"',  r'\"')
                yield '%*s "%s"\n' % (indent, tag, qv)

    def to_string(self):
        """Return stanza as a single string"""
        return ''.join(self.to_lines())

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
         
TAG_RE = re.compile(r'^[-a-zA-Z0-9_]+$')
def valid_tag(tag):
    return bool(TAG_RE.match(tag))


def read_stanza(line_iter):
    """Return new Stanza read from list of lines or a file"""
    items = []
    got_lines = False
    for l in line_iter:
        if l == None or l == '':
            break # eof
        got_lines = True
        if l == '\n':
            break
        assert l[-1] == '\n'
        l = l.lstrip()
        space = l.index(' ')
        tag = l[:space]
        assert valid_tag(tag), \
                "invalid basic_io tag %r" % tag
        rest = l[space+1:]
        if l[space+1] == '"':
            value = ''
            valpart = l[space+2:]
            while True:
                assert valpart[-1] == '\n'
                if len(valpart) > 2 and valpart[-2] == '"':
                    # XXX: This seems wrong -- we ought to need special
                    # handling for constructs like '\\"' at end of line, and
                    # yet it seems to work.
                    # is this really the end, or just an escaped doublequote
                    # at end-of-line?  it's quoted if there are an odd number
                    # of doublequotes before it?
                    value += valpart[:-2]
                    break
                else:
                    value += valpart
                try:
                    valpart = line_iter.next()
                except StopIteration:
                    raise ValueError('end of file in quoted string after %r' % value)
            value = value.replace('\\"', '"').replace('\\\\', '\\')
        else:
            value = int(l[space+1:])
        items.append((tag, value))
    if not got_lines:
        return None         # didn't see any content
    s = Stanza()
    s.items = items
    return s


def _read_quoted_string(start, from_lines):
    r = []
    while True:

        assert l[-2] == '"'
        value = l[space+2:-2]
        value = value.replace(r'\"', '\"').replace(r'\\', '\\')



############################################################

# XXX: Move these to object serialization code. 

def write_revision(writer, revision):
    s = Stanza(revision=revision.revision_id,
               committer=revision.committer, 
               timezone=long(revision.timezone),
               timestamp=long(revision.timestamp),
               inventory_sha1=revision.inventory_sha1,
               message=revision.message)
    for parent_id in revision.parent_ids:
        s.add('parent', parent_id)
    for prop_name, prop_value in revision.properties.items():
        s.add(prop_name, prop_value)
    writer.write_stanza(s)

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
    s = read_stanza(inv_file)
    assert s['inventory_version'] == 7
    inv = Inventory()
    for s in read_stanzas(inv_file):
        kind, file_id = s.items[0]
        parent_id = None
        if 'parent_id' in s:
            parent_id = s['parent_id']
        if kind == 'file':
            ie = InventoryFile(file_id, s['name'], parent_id)
            ie.text_sha1 = s['text_sha1']
            ie.text_size = s['text_size']
        else:
            raise NotImplementedError()
        inv.add(ie)
    return inv
