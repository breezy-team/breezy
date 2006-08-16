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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Tests for utf8 caching."""

from bzrlib import (
    cache_utf8,
    )
from bzrlib.tests import TestCase


class TestEncodeCache(TestCase):
    
    def setUp(self):
        super(TestEncodeCache, self).setUp()
        cache_utf8.clear_encoding_cache()
        self.addCleanup(cache_utf8.clear_encoding_cache)

    def check_encode(self, rev_id):
        rev_id_utf8 = rev_id.encode('utf-8')
        self.failIf(rev_id in cache_utf8._unicode_to_utf8_map)
        self.failIf(rev_id_utf8 in cache_utf8._utf8_to_unicode_map)

        # After a single encode, the mapping should exist for
        # both directions
        self.assertEqual(rev_id_utf8, cache_utf8.encode(rev_id))
        self.failUnless(rev_id in cache_utf8._unicode_to_utf8_map)
        self.failUnless(rev_id_utf8 in cache_utf8._utf8_to_unicode_map)

        self.assertEqual(rev_id, cache_utf8.decode(rev_id_utf8))

        cache_utf8.clear_encoding_cache()
        self.failIf(rev_id in cache_utf8._unicode_to_utf8_map)
        self.failIf(rev_id_utf8 in cache_utf8._utf8_to_unicode_map)

    def check_decode(self, rev_id):
        rev_id_utf8 = rev_id.encode('utf-8')
        self.failIf(rev_id in cache_utf8._unicode_to_utf8_map)
        self.failIf(rev_id_utf8 in cache_utf8._utf8_to_unicode_map)

        # After a single decode, the mapping should exist for
        # both directions
        self.assertEqual(rev_id, cache_utf8.decode(rev_id_utf8))
        self.failUnless(rev_id in cache_utf8._unicode_to_utf8_map)
        self.failUnless(rev_id_utf8 in cache_utf8._utf8_to_unicode_map)

        self.assertEqual(rev_id_utf8, cache_utf8.encode(rev_id))
        cache_utf8.clear_encoding_cache()

        self.failIf(rev_id in cache_utf8._unicode_to_utf8_map)
        self.failIf(rev_id_utf8 in cache_utf8._utf8_to_unicode_map)

    def test_ascii(self):
        self.check_decode(u'all_ascii_characters123123123')
        self.check_encode(u'all_ascii_characters123123123')

    def test_unicode(self):
        self.check_encode(u'some_\xb5_unicode_\xe5_chars')
        self.check_decode(u'some_\xb5_unicode_\xe5_chars')

    def test_cached_unicode(self):
        x = u'\xb5yy' + u'\xe5zz'
        y = u'\xb5yy' + u'\xe5zz'
        self.failIf(x is y)
        xp = cache_utf8.get_cached_unicode(x)
        yp = cache_utf8.get_cached_unicode(y)

        self.failUnless(xp is x)
        self.failUnless(xp is yp)

