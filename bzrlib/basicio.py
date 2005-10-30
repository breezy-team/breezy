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

class BasicWriter(object):
    def __init__(self):
        self.soft_nl = False

    def write_stanza(self, stanza):
        if self.soft_nl:
            print
        _StanzaWriter(stanza.items).write()
        self.soft_nl = True


class _StanzaWriter(object):
    def __init__(self, list):
        self.indent = 0
        self.items = list[:]

    def write_pair(self, tag, value):
        if not valid_tag(tag):
            raise ValueError("invalid basicio tag %r" % tag)
        if isinstance(value, basestring):
            self.write_string(tag, value)
        elif isinstance(value, (int, long)):
            self.write_number(tag, value)
        else:
            raise ValueError("invalid basicio value %r" % (value))

    def write_number(self, tag, value):
        print "%*s %d" % (self.indent, tag, value)

    def write_string(self, tag, value):
        print "%*s %s" % (self.indent, tag, self.quote_string(value))

    def quote_string(self, value):
        qv = value.replace('\\', '\\\\') \
                .replace('\n', '\\n') \
                .replace('\r', '\\r') \
                .replace('\t', '\\t') \
                .replace('"', '\\"') 
        return '"' + qv + '"'

    def write(self):
        self.indent = max(len(kv[0]) for kv in self.items)
        for tag, value in self.items:
            self.write_pair(tag, value)


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

    def __iter__(self):
        """Return iterator of tag, value pairs."""
        return iter(self.items)

         
TAG_RE = re.compile(r'^[-a-zA-Z0-9_]+$')
def valid_tag(tag):
    return bool(TAG_RE.match(tag))






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
    writer.write_stanza(s)

def write_inventory(writer, inventory):
    s = Stanza(inventory_version=7)
    writer.write_stanza(s)

    for path, ie in inventory.iter_entries():
        s = Stanza()
        for attr in ['kind', 'name', 'file_id', 'parent_id', 'revision',
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
