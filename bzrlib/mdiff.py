# (C) 2005 Matt Mackall
# (C) 2005 Canonical Ltd

# based on code by Matt Mackall, hacked by Martin Pool

# mm's code works line-by-line; this just works on byte strings.
# Possibly slower; possibly gives better results for code not
# regularly separated by newlines and anyhow a bit simpler.


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


# TODO: maybe work on files not strings?

# FIXME: doesn't work properly on files without trailing newlines

import unittest
import difflib, sys, struct
from cStringIO import StringIO

def linesplit(a):
    """Split into two lists: content and line positions.

    This returns (al, ap).

    al[i] is the string content of line i of the file, including its
    newline (if any).

    ap[i] is the byte position in the file where that line starts.

    ap[-1] is the byte position of the end of the file (i.e. the
    length of the file.)

    This transformation allows us to do a line-based diff and then map
    back to byte positions.
    """

    al, ap = [], []
    last = 0

    n = a.find("\n") + 1
    while n > 0:
        ap.append(last)
        al.append(a[last:n])
        last = n
        n = a.find("\n", n) + 1

    if last < len(a):
        al.append(a[last:])
        ap.append(last)

    # position at the end
    ap.append(len(a))

    return (al, ap)


def diff(a, b):
    # TODO: Use different splits, perhaps rsync-like, for binary files?
    
    (al, ap) = linesplit(a)
    (bl, bp) = linesplit(b)

    d = difflib.SequenceMatcher(None, al, bl)
    
    ## sys.stderr.write('  ~ real_quick_ratio: %.4f\n' % d.real_quick_ratio())
    
    for o, m, n, s, t in d.get_opcodes():
        if o == 'equal': continue
        # a[m:n] should be replaced by b[s:t]
        if s == t:
            yield ap[m], ap[n], ''
        else:
            yield ap[m], ap[n], ''.join(bl[s:t])


def tobinary(ops):
    b = StringIO()
    for f in ops:
        b.write(struct.pack(">III", f[0], f[1], len(f[2])))
        b.write(f[2])
    return b.getvalue()


def bdiff(a, b):
    return tobinary(diff(a, b))


def patch(t, ops):
    last = 0
    b = StringIO()

    for m, n, r in ops:
        b.write(t[last:m])
        if r:
            b.write(r)
        last = n
        
    b.write(t[last:])
    return b.getvalue()


def frombinary(b):
    bin = StringIO(b)
    while True:
        p = bin.read(12)
        if not p:
            break

        m, n, l = struct.unpack(">III", p)
        
        if l == 0:
            r = ''
        else:
            r = bin.read(l)
            if len(r) != l:
                raise Exception("truncated patch data")
            
        yield m, n, r


def bpatch(t, b):
    return patch(t, frombinary(b))




class TestDiffPatch(unittest.TestCase):
    def doDiffPatch(self, old, new):
        diff = bdiff(old, new)
        result = bpatch(old, diff)
        self.assertEquals(new, result)


    def testSimpleDiff(self):
        """Simply add a line at the end"""
        self.doDiffPatch('a\nb\n', 'a\nb\nc\n')
        

        
    def testTrailingLine(self):
        """Test diff that adds an unterminated line.

        (Old versions didn't do this properly.)"""
        self.doDiffPatch('a\nb\nc\n',
                         'a\nb\nc\nd')


if __name__ == '__main__':
    unittest.main()
