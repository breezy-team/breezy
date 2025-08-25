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

"""Tests for utf8 caching."""

from .. import cache_utf8
from . import TestCase


class TestEncodeCache(TestCase):
    def setUp(self):
        super().setUp()
        cache_utf8.clear_encoding_cache()
        self.addCleanup(cache_utf8.clear_encoding_cache)

    def check_encode(self, rev_id):
        rev_id_utf8 = rev_id.encode("utf-8")
        self.assertNotIn(rev_id, cache_utf8._unicode_to_utf8_map)
        self.assertNotIn(rev_id_utf8, cache_utf8._utf8_to_unicode_map)

        # After a single encode, the mapping should exist for
        # both directions
        self.assertEqual(rev_id_utf8, cache_utf8.encode(rev_id))
        self.assertIn(rev_id, cache_utf8._unicode_to_utf8_map)
        self.assertIn(rev_id_utf8, cache_utf8._utf8_to_unicode_map)

        self.assertEqual(rev_id, cache_utf8.decode(rev_id_utf8))

        cache_utf8.clear_encoding_cache()
        self.assertNotIn(rev_id, cache_utf8._unicode_to_utf8_map)
        self.assertNotIn(rev_id_utf8, cache_utf8._utf8_to_unicode_map)

    def check_decode(self, rev_id):
        rev_id_utf8 = rev_id.encode("utf-8")
        self.assertNotIn(rev_id, cache_utf8._unicode_to_utf8_map)
        self.assertNotIn(rev_id_utf8, cache_utf8._utf8_to_unicode_map)

        # After a single decode, the mapping should exist for
        # both directions
        self.assertEqual(rev_id, cache_utf8.decode(rev_id_utf8))
        self.assertIn(rev_id, cache_utf8._unicode_to_utf8_map)
        self.assertIn(rev_id_utf8, cache_utf8._utf8_to_unicode_map)

        self.assertEqual(rev_id_utf8, cache_utf8.encode(rev_id))
        cache_utf8.clear_encoding_cache()

        self.assertNotIn(rev_id, cache_utf8._unicode_to_utf8_map)
        self.assertNotIn(rev_id_utf8, cache_utf8._utf8_to_unicode_map)

    def test_ascii(self):
        self.check_decode("all_ascii_characters123123123")
        self.check_encode("all_ascii_characters123123123")

    def test_unicode(self):
        self.check_encode("some_\xb5_unicode_\xe5_chars")
        self.check_decode("some_\xb5_unicode_\xe5_chars")

    def test_cached_unicode(self):
        # Note that this is intentionally split, to prevent Python from
        # assigning x and y to the same object
        z = "\xe5zz"
        x = "\xb5yy" + z
        y = "\xb5yy" + z
        self.assertIsNot(x, y)
        xp = cache_utf8.get_cached_unicode(x)
        yp = cache_utf8.get_cached_unicode(y)

        self.assertIs(xp, x)
        self.assertIs(xp, yp)

    def test_cached_utf8(self):
        x = "\xb5yy\xe5zz".encode()
        y = "\xb5yy\xe5zz".encode()
        self.assertIsNot(x, y)
        xp = cache_utf8.get_cached_utf8(x)
        yp = cache_utf8.get_cached_utf8(y)

        self.assertIs(xp, x)
        self.assertIs(xp, yp)

    def test_cached_ascii(self):
        x = b"%s %s" % (b"simple", b"text")
        y = b"%s %s" % (b"simple", b"text")
        self.assertIsNot(x, y)
        xp = cache_utf8.get_cached_ascii(x)
        yp = cache_utf8.get_cached_ascii(y)

        self.assertIs(xp, x)
        self.assertIs(xp, yp)

        # after caching, encode and decode should also return the right
        # objects.
        uni_x = cache_utf8.decode(x)
        self.assertEqual("simple text", uni_x)
        self.assertIsInstance(uni_x, str)

        utf8_x = cache_utf8.encode(uni_x)
        self.assertIs(utf8_x, x)

    def test_decode_with_None(self):
        self.assertEqual(None, cache_utf8._utf8_decode_with_None(None))
        self.assertEqual("foo", cache_utf8._utf8_decode_with_None(b"foo"))
        self.assertEqual("f\xb5", cache_utf8._utf8_decode_with_None(b"f\xc2\xb5"))
