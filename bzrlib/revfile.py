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
from binascii import hexlify, unhexlify

factor = 10

_RECORDSIZE = 48

_HEADER = "bzr revfile v1\n"
_HEADER = _HEADER + ('\xff' * (_RECORDSIZE - len(_HEADER)))
_NO_RECORD = 0xFFFFFFFFL

# fields in the index record
I_SHA = 0
I_BASE = 1
I_FLAGS = 2
I_OFFSET = 3
I_LEN = 4

FL_GZIP = 1


class RevfileError(Exception):
    pass



class Revfile:
    def __init__(self, basename):
        # TODO: Option to open readonly

        # TODO: Lock file  while open

        # TODO: advise of random access

        self.basename = basename
        
        idxname = basename + '.irev'
        dataname = basename + '.drev'

        self.idxpos = 0L

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
            self.datafile = open(dataname, 'r+b')
            
            h = self.idxfile.read(_RECORDSIZE)
            if h != _HEADER:
                raise RevfileError("bad header %r in index of %r"
                                   % (h, self.basename))



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


    def _check_index(self, idx):
        if idx < 0 or idx > len(self):
            raise RevfileError("invalid index %r" % idx)


    def find_sha(self, s):
        assert isinstance(s, str)
        assert len(s) == 20
        
        for idx, idxrec in enumerate(self):
            if idxrec[I_SHA] == s:
                return idx
        else:
            return _NO_RECORD        


    def _add_common(self, text_sha, data, base):
        """Add pre-processed data, can be either full text or delta.

        This does the compression if that makes sense."""

        flags = 0
        data_len = len(data)
        if data_len > 50:
            # don't do compression if it's too small; it's unlikely to win
            # enough to be worthwhile
            compr_data = zlib.compress(data)
            compr_len = len(compr_data)
            if compr_len < data_len:
                data = compr_data
                flags = FL_GZIP
                print '- compressed %d -> %d, %.1f%%' \
                      % (data_len, compr_len, float(compr_len)/float(data_len) * 100.0)
        
        idx = len(self)
        self.datafile.seek(0, 2)        # to end
        self.idxfile.seek(0, 2)
        assert self.idxfile.tell() == _RECORDSIZE * (idx + 1)
        data_offset = self.datafile.tell()

        assert isinstance(data, str) # not unicode or anything wierd

        self.datafile.write(data)
        self.datafile.flush()

        assert isinstance(text_sha, str)
        entry = text_sha
        entry += struct.pack(">IIII12x", base, flags, data_offset, len(data))
        assert len(entry) == _RECORDSIZE

        self.idxfile.write(entry)
        self.idxfile.flush()

        return idx
        


    def _add_full_text(self, text, text_sha):
        """Add a full text to the file.

        This is not compressed against any reference version.

        Returns the index for that text."""
        return self._add_common(text_sha, text, _NO_RECORD)


    def _add_delta(self, text, text_sha, base):
        """Add a text stored relative to a previous text."""
        self._check_index(base)
        base_text = self.get(base)
        data = mdiff.bdiff(base_text, text)
        return self._add_common(text_sha, data, base)


    def add(self, text, base=_NO_RECORD):
        text_sha = sha.new(text).digest()

        idx = self.find_sha(text_sha)
        if idx != _NO_RECORD:
            return idx                  # already present
        
        if base == _NO_RECORD:
            return self._add_full_text(text, text_sha)
        else:
            return self._add_delta(text, text_sha, base)



    def get(self, idx):
        idxrec = self[idx]
        base = idxrec[I_BASE]
        if base == _NO_RECORD:
            text = self._get_full_text(idx, idxrec)
        else:
            text = self._get_patched(idx, idxrec)

        if sha.new(text).digest() != idxrec[I_SHA]:
            raise RevfileError("corrupt SHA-1 digest on record %d"
                               % idx)

        return text



    def _get_raw(self, idx, idxrec):
        flags = idxrec[I_FLAGS]
        if flags & ~FL_GZIP:
            raise RevfileError("unsupported index flags %#x on index %d"
                               % (flags, idx))
        
        l = idxrec[I_LEN]
        if l == 0:
            return ''

        self.datafile.seek(idxrec[I_OFFSET])

        data = self.datafile.read(l)
        if len(data) != l:
            raise RevfileError("short read %d of %d "
                               "getting text for record %d in %r"
                               % (len(data), l, idx, self.basename))

        if flags & FL_GZIP:
            data = zlib.decompress(data)

        return data
        

    def _get_full_text(self, idx, idxrec):
        assert idxrec[I_BASE] == _NO_RECORD

        text = self._get_raw(idx, idxrec)

        return text


    def _get_patched(self, idx, idxrec):
        base = idxrec[I_BASE]
        assert base >= 0
        assert base < idx    # no loops!

        base_text = self.get(base)
        patch = self._get_raw(idx, idxrec)

        text = mdiff.bpatch(base_text, patch)

        return text



    def __len__(self):
        """Return number of revisions."""
        l = os.fstat(self.idxfile.fileno())[stat.ST_SIZE]
        if l % _RECORDSIZE:
            raise RevfileError("bad length %d on index of %r" % (l, self.basename))
        if l < _RECORDSIZE:
            raise RevfileError("no header present in index of %r" % (self.basename))
        return int(l / _RECORDSIZE) - 1


    def __getitem__(self, idx):
        """Index by sequence id returns the index field"""
        ## TODO: Can avoid seek if we just moved there...
        self._seek_index(idx)
        return self._read_next_index()


    def _seek_index(self, idx):
        if idx < 0:
            raise RevfileError("invalid index %r" % idx)
        self.idxfile.seek((idx + 1) * _RECORDSIZE)
        

    def _read_next_index(self):
        rec = self.idxfile.read(_RECORDSIZE)
        if not rec:
            raise IndexError("end of index file")
        elif len(rec) != _RECORDSIZE:
            raise RevfileError("short read of %d bytes getting index %d from %r"
                               % (len(rec), idx, self.basename))
        
        return struct.unpack(">20sIIII12x", rec)

        
    def dump(self, f=sys.stdout):
        f.write('%-8s %-40s %-8s %-8s %-8s %-8s\n' 
                % tuple('idx sha1 base flags offset len'.split()))
        f.write('-------- ---------------------------------------- ')
        f.write('-------- -------- -------- --------\n')

        for i, rec in enumerate(self):
            f.write("#%-7d %40s " % (i, hexlify(rec[0])))
            if rec[1] == _NO_RECORD:
                f.write("(none)   ")
            else:
                f.write("#%-7d " % rec[1])
                
            f.write("%8x %8d %8d\n" % (rec[2], rec[3], rec[4]))
        


def main(argv):
    r = Revfile("testrev")

    try:
        cmd = argv[1]
    except IndexError:
        sys.stderr.write("usage: revfile dump\n"
                         "       revfile add\n"
                         "       revfile add-delta BASE\n"
                         "       revfile get IDX\n"
                         "       revfile find-sha HEX\n")
        return 1
        

    if cmd == 'add':
        new_idx = r.add(sys.stdin.read())
        print 'added idx %d' % new_idx
    elif cmd == 'add-delta':
        new_idx = r.add(sys.stdin.read(), int(argv[2]))
        print 'added idx %d' % new_idx
    elif cmd == 'dump':
        r.dump()
    elif cmd == 'get':
        try:
            idx = int(argv[2])
        except IndexError:
            sys.stderr.write("usage: revfile get IDX\n")
            return 1

        if idx < 0 or idx >= len(r):
            sys.stderr.write("invalid index %r\n" % idx)
            return 1

        sys.stdout.write(r.get(idx))
    elif cmd == 'find-sha':
        try:
            s = unhexlify(argv[2])
        except IndexError:
            sys.stderr.write("usage: revfile find-sha HEX\n")
            return 1

        idx = r.find_sha(s)
        if idx == _NO_RECORD:
            sys.stderr.write("no such record\n")
            return 1
        else:
            print idx
            
    else:
        sys.stderr.write("unknown command %r\n" % cmd)
        return 1
    

if __name__ == '__main__':
    import sys
    sys.exit(main(sys.argv) or 0)
