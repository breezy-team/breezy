# Copyright (C) 2006 Canonical Ltd
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
from unittest import TestCase
import zlib


from bzrlib import tuned_gzip


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


class TestFakeDecompress(TestCase):
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


class TestGzip(TestCase):

    def test__read_short_remainder(self):
        # a _read call at the end of a compressed hunk should
        # read more bytes if there is less than 8 bytes (the
        # gzip trailer) unread.
        stream = StringIO('\0\0\0\0\0\0\0\0')
        myfile = tuned_gzip.GzipFile(fileobj=stream)
        # disable the _new_member check, we are microtesting.
        myfile._new_member = False
        myfile.crc = zlib.crc32('')
        myfile.decompress = FakeDecompress()
        myfile.size = 0
        myfile._read(1)
        # all the data should have been read now
        self.assertEqual('', stream.read())
        # and it should be new member time in the stream.
        self.failUnless(myfile._new_member)


class TestToGzip(TestCase):

    def assertToGzip(self, chunks):
        bytes = ''.join(chunks)
        gzfromchunks = tuned_gzip.chunks_to_gzip(chunks)
        gzfrombytes = tuned_gzip.bytes_to_gzip(bytes)
        self.assertEqual(gzfrombytes, gzfromchunks)
        decoded = tuned_gzip.GzipFile(fileobj=StringIO(gzfromchunks)).read()
        self.assertEqual(bytes, decoded)

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
