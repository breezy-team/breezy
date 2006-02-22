# Copyright (C) 2005 Canonical Ltd

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

# Author: Martin Pool <mbp@canonical.com>




"""Store and retrieve weaves in files.

There is one format marker followed by a blank line, followed by a
series of version headers, followed by the weave itself.

Each version marker has

 'i'   parent version indexes
 '1'   SHA-1 of text
 'n'   name

The inclusions do not need to list versions included by a parent.

The weave is bracketed by 'w' and 'W' lines, and includes the '{}[]'
processing instructions.  Lines of text are prefixed by '.' if the
line contains a newline, or ',' if not.
"""

# TODO: When extracting a single version it'd be enough to just pass
# an iterator returning the weave lines...  We don't really need to
# deserialize it into memory.

FORMAT_1 = '# bzr weave file v5\n'


def write_weave(weave, f, format=None):
    if format == None or format == 1:
        return write_weave_v5(weave, f)
    else:
        raise ValueError("unknown weave format %r" % format)


def write_weave_v5(weave, f):
    """Write weave to file f."""
    print >>f, FORMAT_1,

    for version, included in enumerate(weave._parents):
        if included:
            # mininc = weave.minimal_parents(version)
            mininc = included
            print >>f, 'i',
            for i in mininc:
                print >>f, i,
            print >>f
        else:
            print >>f, 'i'
        print >>f, '1', weave._sha1s[version]
        print >>f, 'n', weave._names[version]
        print >>f

    print >>f, 'w'

    for l in weave._weave:
        if isinstance(l, tuple):
            assert l[0] in '{}[]'
            if l[0] == '}':
                print >>f, '}'
            else:
                print >>f, '%s %d' % l
        else: # text line
            if not l:
                print >>f, ', '
            elif l[-1] == '\n':
                assert l.find('\n', 0, -1) == -1
                print >>f, '.', l,
            else:
                assert l.find('\n') == -1
                print >>f, ',', l

    print >>f, 'W'



def read_weave(f, prelude=False):
    # FIXME: detect the weave type and dispatch
    from bzrlib.trace import mutter
    return _read_weave_v5(f, prelude=prelude)


def _read_weave_v5(f, prelude=False):
    """Private helper routine to read a weave format 5 file into memory."""
    from weave import WeaveFormatError, Weave
    w = Weave(getattr(f, 'name', None))

    l = f.readline()
    if l != FORMAT_1:
        raise WeaveFormatError('invalid weave file header: %r' % l)

    ver = 0
    while True:
        l = f.readline()
        if l[0] == 'i':
            if len(l) > 2:
                w._parents.append(map(int, l[2:].split(' ')))
            else:
                w._parents.append([])

            l = f.readline()[:-1]
            assert l.startswith('1 ')
            w._sha1s.append(l[2:])
                
            l = f.readline()
            assert l.startswith('n ')
            name = l[2:-1]
            assert name not in w._name_map
            w._names.append(name)
            w._name_map[name] = ver
                
            l = f.readline()
            assert l == '\n'

            ver += 1
        elif l == 'w\n':
            break
        else:
            raise WeaveFormatError('unexpected line %r' % l)

    if prelude:
        return w

    while True:
        l = f.readline()
        if l == 'W\n':
            break
        elif l.startswith('. '):
            w._weave.append(l[2:])  # include newline
        elif l.startswith(', '):
            w._weave.append(l[2:-1])        # exclude newline
        elif l == '}\n':
            w._weave.append(('}', None))
        else:
            assert l[0] in '{[]', l
            assert l[1] == ' ', l
            w._weave.append((intern(l[0]), int(l[2:])))

    return w
    
