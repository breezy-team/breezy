# Copyright (C) 2005 by Canonical Ltd
#
# Distributed under the GNU General Public Licence v2

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

# XXX: some redundancy is allowing to write stanzas in isolation as well as
# through a writer object.  

class RioWriter(object):
    def __init__(self, to_file):
        self._soft_nl = False
        self._to_file = to_file

    def write_stanza(self, stanza):
        if self._soft_nl:
            print >>self._to_file
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

def read_stanzas(from_file):
    while True:
        s = read_stanza(from_file)
        if s is None:
            break
        else:
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
        assert valid_tag(tag), \
            ("invalid tag %r" % tag)
        if isinstance(value, str):
            value = unicode(value)
        elif isinstance(value, unicode):
            pass
        ## elif isinstance(value, (int, long)):
        ##    value = str(value)           # XXX: python2.4 without L-suffix
        else:
            raise TypeError("invalid type for rio value: %r of type %s"
                            % (value, type(value)))
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
        """Generate sequence of lines for external version of this file.
        
        The lines are always utf-8 encoded strings.
        """
        if not self.items:
            # max() complains if sequence is empty
            return []
        result = []
        for tag, value in self.items:
            assert isinstance(tag, str)
            assert isinstance(value, unicode)
            if value == '':
                result.append(tag + ': \n')
            elif '\n' in value:
                # don't want splitlines behaviour on empty lines
                val_lines = value.split('\n')
                result.append(tag + ': ' + val_lines[0].encode('utf-8') + '\n')
                for line in val_lines[1:]:
                    result.append('\t' + line.encode('utf-8') + '\n')
            else:
                result.append(tag + ': ' + value.encode('utf-8') + '\n')
        return result

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

    def as_dict(self):
        """Return a dict containing the unique values of the stanza.
        """
        d = {}
        for tag, value in self.items:
            assert tag not in d
            d[tag] = value
        return d
         
_tag_re = re.compile(r'^[-a-zA-Z0-9_]+$')
def valid_tag(tag):
    return bool(_tag_re.match(tag))


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
    items = []
    stanza = Stanza()
    tag = None
    accum_value = None
    for line in line_iter:
        if line == None or line == '':
            break       # end of file
        if line == '\n':
            break       # end of stanza
        line = line.decode('utf-8')
        assert line[-1] == '\n'
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
                raise ValueError('tag/value separator not found in line %r' % real_l)
            tag = line[:colon_index]
            assert valid_tag(tag), \
                    "invalid rio tag %r" % tag
            accum_value = line[colon_index+2:-1]
    if tag is not None: # add last tag-value
        stanza.add(tag, accum_value)
        return stanza
    else:     # didn't see any content
        return None    
