# (C) 2005 Matt Mackall

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

import difflib, sys, struct

def linesplit(a):
    al, ap = [], []
    last = 0

    n = a.find("\n") + 1
    while n > 0:
        ap.append(last)
        al.append(a[last:n])
        last = n
        n = a.find("\n", n) + 1

    return (al, ap)

def diff(a, b):
    (al, ap) = linesplit(a)
    (bl, bp) = linesplit(b)

    d = difflib.SequenceMatcher(None, al, bl)
    ops = []
    for o, m, n, s, t in d.get_opcodes():
        if o == 'equal': continue
        ops.append((ap[m], ap[n], "".join(bl[s:t])))

    return ops

def tobinary(ops):
    b = ""
    for f in ops:
        b += struct.pack(">lll", f[0], f[1], len(f[2])) + f[2]
    return b

def bdiff(a, b):
    return tobinary(diff(a, b))

def patch(t, ops):
    last = 0
    r = []

    for p1, p2, sub in ops:
        r.append(t[last:p1])
        r.append(sub)
        last = p2

    r.append(t[last:])
    return "".join(r)

def frombinary(b):
    ops = []
    while b:
        p = b[:12]
        m, n, l = struct.unpack(">lll", p)
        ops.append((m, n, b[12:12 + l]))
        b = b[12 + l:]

    return ops

def bpatch(t, b):
    return patch(t, frombinary(b))




