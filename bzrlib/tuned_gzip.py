# Copyright (C) 2005, 2006 by Canonical Ltd
# Written by Robert Collins <robert.collins@canonical.com>
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

"""Bzrlib specific gzip tunings. We plan to feed these to the upstream gzip."""

# make GzipFile faster:
import gzip
from gzip import U32, LOWU32, FEXTRA, FCOMMENT, FNAME, FHCRC
import sys
import struct
import zlib

# we want a \n preserved, break on \n only splitlines.
import bzrlib

__all__ = ["GzipFile"]


class GzipFile(gzip.GzipFile):
    """Knit tuned version of GzipFile.

    This is based on the following lsprof stats:
    python 2.4 stock GzipFile write:
    58971      0   5644.3090   2721.4730   gzip:193(write)
    +58971     0   1159.5530   1159.5530   +<built-in method compress>
    +176913    0    987.0320    987.0320   +<len>
    +58971     0    423.1450    423.1450   +<zlib.crc32>
    +58971     0    353.1060    353.1060   +<method 'write' of 'cStringIO.
                                            StringO' objects>
    tuned GzipFile write:
    58971      0   4477.2590   2103.1120   bzrlib.knit:1250(write)
    +58971     0   1297.7620   1297.7620   +<built-in method compress>
    +58971     0    406.2160    406.2160   +<zlib.crc32>
    +58971     0    341.9020    341.9020   +<method 'write' of 'cStringIO.
                                            StringO' objects>
    +58971     0    328.2670    328.2670   +<len>


    Yes, its only 1.6 seconds, but they add up.
    """

    def _add_read_data(self, data):
        # 4169 calls in 183
        # temp var for len(data) and switch to +='s.
        # 4169 in 139
        len_data = len(data)
        self.crc = zlib.crc32(data, self.crc)
        self.extrabuf += data
        self.extrasize += len_data
        self.size += len_data

    def _read(self, size=1024):
        # various optimisations:
        # reduces lsprof count from 2500 to 
        # 8337 calls in 1272, 365 internal
        if self.fileobj is None:
            raise EOFError, "Reached EOF"

        if self._new_member:
            # If the _new_member flag is set, we have to
            # jump to the next member, if there is one.
            #
            # First, check if we're at the end of the file;
            # if so, it's time to stop; no more members to read.
            next_header_bytes = self.fileobj.read(10)
            if next_header_bytes == '':
                raise EOFError, "Reached EOF"

            self._init_read()
            self._read_gzip_header(next_header_bytes)
            self.decompress = zlib.decompressobj(-zlib.MAX_WBITS)
            self._new_member = False

        # Read a chunk of data from the file
        buf = self.fileobj.read(size)

        # If the EOF has been reached, flush the decompression object
        # and mark this object as finished.

        if buf == "":
            self._add_read_data(self.decompress.flush())
            assert len(self.decompress.unused_data) >= 8, "what does flush do?"
            self._gzip_tail = self.decompress.unused_data[0:8]
            self._read_eof()
            # tell the driving read() call we have stuffed all the data
            # in self.extrabuf
            raise EOFError, 'Reached EOF'

        self._add_read_data(self.decompress.decompress(buf))

        if self.decompress.unused_data != "":
            # Ending case: we've come to the end of a member in the file,
            # so seek back to the start of the data for the next member which
            # is the length of the decompress objects unused data - the first
            # 8 bytes for the end crc and size records.
            #
            # so seek back to the start of the unused data, finish up
            # this member, and read a new gzip header.
            # (The number of bytes to seek back is the length of the unused
            # data, minus 8 because those 8 bytes are part of this member.
            seek_length = len (self.decompress.unused_data) - 8
            if seek_length > 0:
                # we read too much data
                self.fileobj.seek(-seek_length, 1)
                self._gzip_tail = self.decompress.unused_data[0:8]
            elif seek_length < 0:
                # we haven't read enough to check the checksum.
                assert -8 < seek_length, "too great a seek."
                buf = self.fileobj.read(-seek_length)
                self._gzip_tail = self.decompress.unused_data + buf
            else:
                self._gzip_tail = self.decompress.unused_data

            # Check the CRC and file size, and set the flag so we read
            # a new member on the next call
            self._read_eof()
            self._new_member = True

    def _read_eof(self):
        """tuned to reduce function calls and eliminate file seeking:
        pass 1:
        reduces lsprof count from 800 to 288
        4168 in 296 
        avoid U32 call by using struct format L
        4168 in 200
        """
        # We've read to the end of the file, so we should have 8 bytes of 
        # unused data in the decompressor. If we dont, there is a corrupt file.
        # We use these 8 bytes to calculate the CRC and the recorded file size.
        # We then check the that the computed CRC and size of the
        # uncompressed data matches the stored values.  Note that the size
        # stored is the true file size mod 2**32.
        assert len(self._gzip_tail) == 8, "gzip trailer is incorrect length."
        crc32, isize = struct.unpack("<LL", self._gzip_tail)
        # note that isize is unsigned - it can exceed 2GB
        if crc32 != U32(self.crc):
            raise IOError, "CRC check failed %d %d" % (crc32, U32(self.crc))
        elif isize != LOWU32(self.size):
            raise IOError, "Incorrect length of data produced"

    def _read_gzip_header(self, bytes=None):
        """Supply bytes if the minimum header size is already read.
        
        :param bytes: 10 bytes of header data.
        """
        """starting cost: 300 in 3998
        15998 reads from 3998 calls
        final cost 168
        """
        if bytes is None:
            bytes = self.fileobj.read(10)
        magic = bytes[0:2]
        if magic != '\037\213':
            raise IOError, 'Not a gzipped file'
        method = ord(bytes[2:3])
        if method != 8:
            raise IOError, 'Unknown compression method'
        flag = ord(bytes[3:4])
        # modtime = self.fileobj.read(4) (bytes [4:8])
        # extraflag = self.fileobj.read(1) (bytes[8:9])
        # os = self.fileobj.read(1) (bytes[9:10])
        # self.fileobj.read(6)

        if flag & FEXTRA:
            # Read & discard the extra field, if present
            xlen = ord(self.fileobj.read(1))
            xlen = xlen + 256*ord(self.fileobj.read(1))
            self.fileobj.read(xlen)
        if flag & FNAME:
            # Read and discard a null-terminated string containing the filename
            while True:
                s = self.fileobj.read(1)
                if not s or s=='\000':
                    break
        if flag & FCOMMENT:
            # Read and discard a null-terminated string containing a comment
            while True:
                s = self.fileobj.read(1)
                if not s or s=='\000':
                    break
        if flag & FHCRC:
            self.fileobj.read(2)     # Read & discard the 16-bit header CRC

    def readline(self, size=-1):
        """Tuned to remove buffer length calls in _unread and...
        
        also removes multiple len(c) calls, inlines _unread,
        total savings - lsprof 5800 to 5300
        phase 2:
        4168 calls in 2233
        8176 calls to read() in 1684
        changing the min chunk size to 200 halved all the cache misses
        leading to a drop to:
        4168 calls in 1977
        4168 call to read() in 1646
        - i.e. just reduced the function call overhead. May be worth 
          keeping.
        """
        if size < 0: size = sys.maxint
        bufs = []
        readsize = min(200, size)    # Read from the file in small chunks
        while True:
            if size == 0:
                return "".join(bufs) # Return resulting line

            # c is the chunk
            c = self.read(readsize)
            # number of bytes read
            len_c = len(c)
            i = c.find('\n')
            if size is not None:
                # We set i=size to break out of the loop under two
                # conditions: 1) there's no newline, and the chunk is
                # larger than size, or 2) there is a newline, but the
                # resulting line would be longer than 'size'.
                if i==-1 and len_c > size: i=size-1
                elif size <= i: i = size -1

            if i >= 0 or c == '':
                # if i>= 0 we have a newline or have triggered the above
                # if size is not None condition.
                # if c == '' its EOF.
                bufs.append(c[:i+1])    # Add portion of last chunk
                # -- inlined self._unread --
                ## self._unread(c[i+1:], len_c - i)   # Push back rest of chunk
                self.extrabuf = c[i+1:] + self.extrabuf
                self.extrasize = len_c - i + self.extrasize
                self.offset -= len_c - i
                # -- end inlined self._unread --
                return ''.join(bufs)    # Return resulting line

            # Append chunk to list, decrease 'size',
            bufs.append(c)
            size = size - len_c
            readsize = min(size, readsize * 2)

    def readlines(self, sizehint=0):
        # optimise to avoid all the buffer manipulation
        # lsprof changed from:
        # 4168 calls in 5472 with 32000 calls to readline()
        # to :
        # 4168 calls in 417.
        # Negative numbers result in reading all the lines
        if sizehint <= 0:
            sizehint = -1
        content = self.read(sizehint)
        return bzrlib.osutils.split_lines(content)

    def _unread(self, buf, len_buf=None):
        """tuned to remove unneeded len calls.
        
        because this is such an inner routine in readline, and readline is
        in many inner loops, this has been inlined into readline().

        The len_buf parameter combined with the reduction in len calls dropped
        the lsprof ms count for this routine on my test data from 800 to 200 - 
        a 75% saving.
        """
        if len_buf is None:
            len_buf = len(buf)
        self.extrabuf = buf + self.extrabuf
        self.extrasize = len_buf + self.extrasize
        self.offset -= len_buf

    def write(self, data):
        if self.mode != gzip.WRITE:
            import errno
            raise IOError(errno.EBADF, "write() on read-only GzipFile object")

        if self.fileobj is None:
            raise ValueError, "write() on closed GzipFile object"
        data_len = len(data)
        if data_len > 0:
            self.size = self.size + data_len
            self.crc = zlib.crc32(data, self.crc)
            self.fileobj.write( self.compress.compress(data) )
            self.offset += data_len

    def writelines(self, lines):
        # profiling indicated a significant overhead 
        # calling write for each line.
        # this batch call is a lot faster :).
        # (4 seconds to 1 seconds for the sample upgrades I was testing).
        self.write(''.join(lines))


