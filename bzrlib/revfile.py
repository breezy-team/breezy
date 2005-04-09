#! /usr/bin/env python

# (C) 2005 Canonical Ltd

# based on an idea by Matt Mackall
# modified to squish into bzr by Martin Pool

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


"""Packed file revision storage.

A Revfile holds the text history of a particular source file, such
as Makefile.  It can represent a tree of text versions for that
file, allowing for microbranches within a single repository.

This is stored on disk as two files: an index file, and a data file.
The index file is short and always read completely into memory; the
data file is much longer and only the relevant bits of it,
identified by the index file, need to be read.

Each text version is identified by the SHA-1 of the full text of
that version.  It also has a sequence number within the file.

The index file has a short header and then a sequence of fixed-length
records:

* byte[20]    SHA-1 of text (as binary, not hex)
* uint32      sequence number this is based on, or -1 for full text
* uint32      flags: 1=zlib compressed
* uint32      offset in text file of start
* uint32      length of compressed delta in text file
* uint32[3]   reserved

total 48 bytes.

The header is also 48 bytes for tidyness and easy calculation.

Both the index and the text are only ever appended to; a consequence
is that sequence numbers are stable references.  But not every
repository in the world will assign the same sequence numbers,
therefore the SHA-1 is the only universally unique reference.

This is meant to scale to hold 100,000 revisions of a single file, by
which time the index file will be ~4.8MB and a bit big to read
sequentially.

Some of the reserved fields could be used to implement a (semi?)
balanced tree indexed by SHA1 so we can much more efficiently find the
index associated with a particular hash.  For 100,000 revs we would be
able to find it in about 17 random reads, which is not too bad.
"""
 

# TODO: Something like pread() would make this slightly simpler and
# perhaps more efficient.

# TODO: Could also try to mmap things...


import sys, zlib, struct, mdiff, stat, os, sha
from binascii import hexlify

factor = 10

_RECORDSIZE = 48

_HEADER = "bzr revfile v1\n"
_HEADER = _HEADER + ('\xff' * (_RECORDSIZE - len(_HEADER)))
_NO_BASE = 0xFFFFFFFFL

# fields in the index record
I_SHA = 0
I_BASE = 1
I_FLAGS = 2
I_OFFSET = 3
I_LEN = 4

class RevfileError(Exception):
    pass



class Revfile:
    def __init__(self, basename):
        self.basename = basename
        
        idxname = basename + '.irev'
        dataname = basename + '.drev'

        idx_exists = os.path.exists(idxname)
        data_exists = os.path.exists(dataname)

        if idx_exists != data_exists:
            raise RevfileError("half-assed revfile")
        
        if not idx_exists:
            self.idxfile = open(idxname, 'w+b')
            self.datafile = open(dataname, 'w+b')
            
            print 'init empty file'
            self.idxfile.write(_HEADER)
            self.idxfile.flush()
        else:
            self.idxfile = open(idxname, 'r+b')
            self.dataname = open(dataname, 'r+b')
            
            h = self.idxfile.read(_RECORDSIZE)
            if h != _HEADER:
                raise RevfileError("bad header %r in index of %r"
                                   % (h, self.basename))


    def last_idx(self):
        """Return last index already present, or -1 if none."""
        l = os.fstat(self.idxfile.fileno())[stat.ST_SIZE]
        if l == 0:
            return -1
        if l % _RECORDSIZE:
            raise RevfileError("bad length %d on index of %r" % (l, self.basename))
        return (l / _RECORDSIZE) - 1


    def revision(self, rev):
        base = self.index[rev][0]
        start = self.index[base][1]
        end = self.index[rev][1] + self.index[rev][2]
        f = open(self.datafile())

        f.seek(start)
        data = f.read(end - start)

        last = self.index[base][2]
        text = zlib.decompress(data[:last])

        for r in range(base + 1, rev + 1):
            s = self.index[r][2]
            b = zlib.decompress(data[last:last + s])
            text = mdiff.bpatch(text, b)
            last = last + s

        return text    


    def add_full_text(self, t):
        """Add a full text to the file.

        This is not compressed against any reference version.

        Returns the index for that text."""
        idx = self.last_idx() + 1
        self.datafile.seek(0, 2)        # to end
        self.idxfile.seek(0, 2)
        assert self.idxfile.tell() == _RECORDSIZE * idx
        data_offset = self.datafile.tell()

        assert isinstance(t, str) # not unicode or anything wierd

        self.datafile.write(t)
        self.datafile.flush()

        entry = sha.new(t).digest()
        entry += struct.pack(">IIII12x", 0xFFFFFFFFL, 0, data_offset, len(t))
        assert len(entry) == _RECORDSIZE

        self.idxfile.write(entry)
        self.idxfile.flush()

        return idx


    def _get_full_text(self, idx):
        idxrec = self[idx]
        assert idxrec[I_FLAGS] == 0
        assert idxrec[I_BASE] == _NO_BASE

        l = idxrec[I_LEN]
        if l == 0:
            return ''

        self.datafile.seek(idxrec[I_OFFSET])

        text = self.datafile.read(l)
        if len(text) != l:
            raise RevfileError("short read %d of %d "
                               "getting text for record %d in %r"
                               % (len(text), l, idx, self.basename))
        
        return text


    def __len__(self):
        return int(self.last_idx())


    def __getitem__(self, idx):
        """Index by sequence id returns the index field"""
        self._seek_index(idx)
        return self._read_next_index()


    def _seek_index(self, idx):
        self.idxfile.seek((idx + 1) * _RECORDSIZE)
        

    def _read_next_index(self):
        rec = self.idxfile.read(_RECORDSIZE)
        if not rec:
            raise IndexError("end of index file")
        elif len(rec) != _RECORDSIZE:
            raise RevfileError("short read of %d bytes getting index %d from %r"
                               % (len(rec), idx, self.basename))
        
        return struct.unpack(">20sIIII12x", rec)

        
        
    def addrevision(self, text, changeset):
        t = self.tip()
        n = t + 1

        if not n % factor:
            data = zlib.compress(text)
            base = n
        else:
            prev = self.revision(t)
            data = zlib.compress(mdiff.bdiff(prev, text))
            base = self.index[t][0]

        offset = 0
        if t >= 0:
            offset = self.index[t][1] + self.index[t][2]

        self.index.append((base, offset, len(data), changeset))
        entry = struct.pack(">llll", base, offset, len(data), changeset)

        open(self.indexfile(), "a").write(entry)
        open(self.datafile(), "a").write(data)

    def dump(self, f=sys.stdout):
        f.write('%-8s %-40s %-8s %-8s %-8s %-8s\n' 
                % tuple('idx sha1 base flags offset len'.split()))
        f.write('-------- ---------------------------------------- ')
        f.write('-------- -------- -------- --------\n')

        for i, rec in enumerate(self):
            f.write("#%-7d %40s " % (i, hexlify(rec[0])))
            if rec[1] == _NO_BASE:
                f.write("(none)   ")
            else:
                f.write("#%-7d " % rec[1])
                
            f.write("%8x %8d %8d\n" % (rec[2], rec[3], rec[4]))
        


def main(argv):
    r = Revfile("testrev")
    if len(argv) < 2:
        sys.stderr.write("usage: revfile dump\n"
                         "       revfile add\n"
                         "       revfile get IDX\n")
        sys.exit(1)
        
    if argv[1] == 'add':
        new_idx = r.add_full_text(sys.stdin.read())
        print 'added idx %d' % new_idx
    elif argv[1] == 'dump':
        r.dump()
    elif argv[1] == 'get':
        sys.stdout.write(r._get_full_text(int(argv[2])))
    else:
        sys.stderr.write("unknown command %r\n" % argv[1])
        sys.exit(1)
    

if __name__ == '__main__':
    import sys
    main(sys.argv)
