# Copyright (C) 2006, 2009, 2010, 2011 Canonical Ltd
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA


"""Tests for tuned_gzip."""


# do not use bzrlib test cases here - this should be suitable for sending
# upstream.
from cStringIO import StringIO
import zlib


from bzrlib import (
    symbol_versioning,
    tuned_gzip,
    tests,
    )


class FakeDecompress(object):
    """A fake decompressor for testing GzipFile."""

    def __init__(self):
        self.unused_data=''

    def decompress(self, buf):
        """Return an empty string as though we are at eof."""
        # note that the zlib module *overwrites* unused data
        # on writes after EOF.
        self.unused_data = buf
        return ''


class TestFakeDecompress(tests.TestCase):
    """We use a fake decompressor to test GzipFile.

    This class tests the behaviours we want from it.
    """

    def test_decompress(self):
        # decompressing returns no data.
        decompress = FakeDecompress()
        self.assertEqual('', decompress.decompress('0'))

    def test_unused_data(self):
        # after decompressing, we have 1 unused byte.
        # this is normally set by decompressors when they
        # detect the end of a compressed stream.
        decompress = FakeDecompress()
        decompress.decompress('0')
        self.assertEqual('0', decompress.unused_data)
        # decompressing again (when the short read is read)
        # will give us the latest input in the unused_data
        # this is arguably a bug in zlib but ...
        decompress.decompress('1234567')
        self.assertEqual('1234567', decompress.unused_data)


class TestGzip(tests.TestCase):

    def test__read_short_remainder(self):
        # a _read call at the end of a compressed hunk should
        # read more bytes if there is less than 8 bytes (the
        # gzip trailer) unread.
        stream = StringIO('\0\0\0\0\0\0\0\0')
        myfile = self.applyDeprecated(
            symbol_versioning.deprecated_in((2, 3, 0)),
            tuned_gzip.GzipFile, fileobj=stream)
        # disable the _new_member check, we are microtesting.
        myfile._new_member = False
        myfile.crc = zlib.crc32('')
        myfile.decompress = FakeDecompress()
        myfile.size = 0
        myfile._read(1)
        # all the data should have been read now
        self.assertEqual('', stream.read())
        # and it should be new member time in the stream.
        self.assertTrue(myfile._new_member)

    def test_negative_crc(self):
        """Content with a negative crc should not break when written"""
        sio = StringIO()
        gfile = self.applyDeprecated(
            symbol_versioning.deprecated_in((2, 3, 0)),
            tuned_gzip.GzipFile, mode="w", fileobj=sio)
        gfile.write("\xFF")
        gfile.close()
        self.assertEqual(gfile.crc & 0xFFFFFFFFL, 0xFF000000L)
        self.assertEqual(sio.getvalue()[-8:-4], "\x00\x00\x00\xFF")


class TestToGzip(tests.TestCase):

    def assertToGzip(self, chunks):
        raw_bytes = ''.join(chunks)
        gzfromchunks = tuned_gzip.chunks_to_gzip(chunks)
        gzfrombytes = tuned_gzip.bytes_to_gzip(raw_bytes)
        self.assertEqual(gzfrombytes, gzfromchunks)
        decoded = self.applyDeprecated(
            symbol_versioning.deprecated_in((2, 3, 0)),
            tuned_gzip.GzipFile, fileobj=StringIO(gzfromchunks)).read()
        lraw, ldecoded = len(raw_bytes), len(decoded)
        self.assertEqual(lraw, ldecoded,
                         'Expecting data length %d, got %d' % (lraw, ldecoded))
        self.assertEqual(raw_bytes, decoded)

    def test_single_chunk(self):
        self.assertToGzip(['a modest chunk\nwith some various\nbits\n'])

    def test_simple_text(self):
        self.assertToGzip(['some\n', 'strings\n', 'to\n', 'process\n'])

    def test_large_chunks(self):
        self.assertToGzip(['a large string\n'*1024])
        self.assertToGzip(['a large string\n']*1024)

    def test_enormous_chunks(self):
        self.assertToGzip(['a large string\n'*1024*256])
        self.assertToGzip(['a large string\n']*1024*256)
