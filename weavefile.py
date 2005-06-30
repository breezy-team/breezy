#! /usr/bin/python

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

Each version marker has 'v' and the version, then 'i' and the included
previous versions.

The weave is bracketed by 'w' and 'W' lines, and includes the '{}[]'
processing instructions.  Lines of text are prefixed by '.' if the
line contains a newline, or ',' if not.
"""

# TODO: When extracting a single version it'd be enough to just pass
# an iterator returning the weave lines...

FORMAT_1 = '# bzr weave file v1'




def write_weave_v1(weave, f):
    """Write weave to file f."""
    print >>f, FORMAT_1
    print >>f

    for version, verinfo in enumerate(weave._v):
        print >>f, 'v', version
        if verinfo.included:
            included = list(verinfo.included)
            included.sort()
            assert included[0] >= 0
            assert included[-1] < version
            print >>f, 'i',
            for i in included:
                print >>f, i,
            print >>f
        else:
            print >>f, 'i'
        print >>f

    print >>f, 'w'

    for l in weave._l:
        if isinstance(l, tuple):
            assert len(l) == 2
            assert l[0] in '{}[]'
            print >>f, '%s %d' % l
        else: # text line
            if not l:
                print >>f, ', '
            elif l[-1] == '\n':
                assert '\n' not in l[:-1]
                print >>f, '.', l,
            else:
                print >>f, ',', l

    print >>f, 'W'


def read_weave_v1(f):
    from weave import Weave, VerInfo
    w = Weave()

    assert f.readline() == FORMAT_1+'\n'
    assert f.readline() == '\n'

    while True:
        l = f.readline()
        if l[0] == 'v':
            l = f.readline()[:-1]
            if l[0] != 'i':
                raise Exception(`l`)
            if len(l) > 2:
                included = map(int, l[2:].split(' '))
                w._v.append(VerInfo(included))
            else:
                w._v.append(VerInfo())
            assert f.readline() == '\n'
        elif l[0] == 'w':
            break
        else:
            assert 0, l

    while True:
        l = f.readline()
        if l == 'W\n':
            break
        elif l[:2] == '. ':
            w._l.append(l[2:])           # include newline
        elif l[:2] == ', ':
            w._l.append(l[2:-1])        # exclude newline
        else:
            assert l[0] in '{}[]', l
            assert l[1] == ' ', l
            w._l.append((l[0], int(l[2:])))

    return w
    
