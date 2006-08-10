# Copyright (C) 2006 by Canonical Ltd
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as published by
# the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Tests for encoding performance."""

from bzrlib import (
    revision,
    osutils,
    )

from bzrlib.benchmarks import Benchmark


_normal_revision_id = (u'john@arbash-meinel.com-20060801200018'
                       u'-cafa6272d9b8cac4')
_unicode_revision_id = (u'\u062c\u0648\u062c\u0648@\xe5rbash-meinel.com-'
                        u'\xb5\xb5\xb5-20060801200018-cafa6272d9b8cac4')

_normal_revision_id_utf8 = _normal_revision_id.encode('utf-8')
_unicode_revision_id_utf8 = _unicode_revision_id.encode('utf-8')


class EncodingBenchmark(Benchmark):

    def setUp(self):
        super(EncodingBenchmark, self).setUp()
        # Make sure we start and end with a clean cache
        revision.clear_encoding_cache()
        self.addCleanup(revision.clear_encoding_cache)

    def encode_1M(self, revision_id):
        """Encode the given revision id 1 million times"""
        # In a real kernel tree there are 7.7M lines of code
        # so the initial import actually has to encode a revision
        # id to store annotated lines one time for every line.
        for i in xrange(1000000):
            revision_id.encode('utf8')

    def encode_cached_1M(self, revision_id):
        """Encode the given revision id 1 million times using the cache"""
        encode_utf8 = revision.encode_utf8
        for i in xrange(1000000):
            encode_utf8(revision_id)

    def encode_multi(self, revision_list, count):
        """Encode each entry in the list count times"""
        for i in xrange(count):
            for revision_id in revision_list:
                revision_id.encode('utf-8')

    def encode_cached_multi(self, revision_list, count):
        """Encode each entry in the list count times"""
        encode_utf8 = revision.encode_utf8
        for i in xrange(count):
            for revision_id in revision_list:
                encode_utf8(revision_id)

    def test_encode_1_by_1M_ascii(self):
        """Test encoding a single revision id 1 million times."""
        self.time(self.encode_1M, _normal_revision_id)

    def test_encode_1_by_1M_ascii_cached(self):
        """Test encoding a single revision id 1 million times."""
        self.time(self.encode_cached_1M, _normal_revision_id)

    def test_encode_1_by_1M_ascii_str(self):
        # We have places that think they have a unicode revision id
        # but actually, they have a plain string. So .encode(utf8)
        # actually has to decode from ascii, and then encode into utf8
        self.time(self.encode_1M, str(_normal_revision_id))

    def test_encode_1_by_1M_ascii_str_cached(self):
        self.time(self.encode_cached_1M, str(_normal_revision_id))

    def test_encode_1_by_1M_unicode(self):
        """Test encoding a single revision id 1 million times."""
        self.time(self.encode_1M, _unicode_revision_id)

    def test_encode_1_by_1M_unicode_cached(self):
        """Test encoding a single revision id 1 million times."""
        self.time(self.encode_cached_1M, _unicode_revision_id)

    def test_encode_1k_by_1k_ascii(self):
        """Test encoding 5 revisions 100k times"""
        revisions = [unicode(osutils.rand_chars(60)) for x in xrange(1000)]
        self.time(self.encode_multi, revisions, 1000)

    def test_encode_1k_by_1k_ascii_cached(self):
        """Test encoding 5 revisions 100k times"""
        revisions = [unicode(osutils.rand_chars(60)) for x in xrange(1000)]
        self.time(self.encode_cached_multi, revisions, 1000)

    def test_encode_1k_by_1k_unicode(self):
        """Test encoding 5 revisions 100k times"""
        revisions = ['\u062c\u0648\u062c\u0648' +
                     unicode(osutils.rand_chars(60)) for x in xrange(1000)]
        self.time(self.encode_multi, revisions, 1000)

    def test_encode_1k_by_1k_unicode_cached(self):
        """Test encoding 5 revisions 100k times"""
        revisions = ['\u062c\u0648\u062c\u0648' +
                     unicode(osutils.rand_chars(60)) for x in xrange(1000)]
        self.time(self.encode_cached_multi, revisions, 1000)


class DecodingBenchmarks(Benchmark):

    def setUp(self):
        super(DecodingBenchmarks, self).setUp()
        # Make sure we start and end with a clean cache
        revision.clear_encoding_cache()
        self.addCleanup(revision.clear_encoding_cache)

    def decode_1M(self, revision_id):
        for i in xrange(1000000):
            revision_id.decode('utf8')

    def decode_cached_1M(self, revision_id):
        decode_utf8 = revision.decode_utf8
        for i in xrange(1000000):
            decode_utf8(revision_id)

    def decode_multi(self, revision_list, count):
        for i in xrange(count):
            for revision_id in revision_list:
                revision_id.decode('utf-8')

    def decode_cached_multi(self, revision_list, count):
        decode_utf8 = revision.decode_utf8
        for i in xrange(count):
            for revision_id in revision_list:
                decode_utf8(revision_id)

    def test_decode_1_by_1M_ascii(self):
        """Test decoding a single revision id 1 million times."""
        self.time(self.decode_1M, _normal_revision_id_utf8)

    def test_decode_1_by_1M_ascii_cached(self):
        """Test decoding a single revision id 1 million times."""
        self.time(self.decode_cached_1M, _normal_revision_id_utf8)

    def test_decode_1_by_1M_unicode(self):
        """Test decoding a single revision id 1 million times."""
        self.time(self.decode_1M, _unicode_revision_id_utf8)

    def test_decode_1_by_1M_unicode_cached(self):
        """Test decoding a single revision id 1 million times."""
        self.time(self.decode_cached_1M, _unicode_revision_id_utf8)

    def test_decode_1k_by_1k_ascii(self):
        """Test decoding 5 revisions 100k times"""
        revisions = [osutils.rand_chars(60) for x in xrange(1000)]
        self.time(self.decode_multi, revisions, 1000)

    def test_decode_1k_by_1k_ascii_cached(self):
        """Test decoding 5 revisions 100k times"""
        revisions = [osutils.rand_chars(60) for x in xrange(1000)]
        self.time(self.decode_cached_multi, revisions, 1000)

    def test_decode_1k_by_1k_unicode(self):
        """Test decoding 5 revisions 100k times"""
        revisions = [('\u062c\u0648\u062c\u0648' +
                      unicode(osutils.rand_chars(60))).encode('utf8')
                     for x in xrange(1000)]
        self.time(self.decode_multi, revisions, 1000)

    def test_decode_1k_by_1k_unicode_cached(self):
        """Test decoding 5 revisions 100k times"""
        revisions = [('\u062c\u0648\u062c\u0648' +
                      unicode(osutils.rand_chars(60))).encode('utf8')
                     for x in xrange(1000)]
        self.time(self.decode_cached_multi, revisions, 1000)
