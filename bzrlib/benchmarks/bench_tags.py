# Copyright (C) 2007 Canonical Ltd
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

"""Test for tags serialization (indirect testing for bencode)"""


import time

from bzrlib.benchmarks import Benchmark
import bzrlib.bencode
import bzrlib.tag


class TagsBencodeBenchmark(Benchmark):
    """Benchmark for serialization/deserialization of tags"""

    def setUp(self):
        super(TagsBencodeBenchmark, self).setUp()
        self.tobj = bzrlib.tag.BasicTags(None)
        tags = {}
        revid = 'j.random@example.com-20070812132500-%016d'
        for i in xrange(100):
            tags[str(i)] = revid % i
        self.tags = tags
        self.bencoded_tags = bzrlib.bencode.bencode(tags)

    def time_N(self, N, kallable, *args, **kwargs):
        def _func(N, kallable, *args, **kwargs):
            for i in xrange(N):
                kallable(*args, **kwargs)
        self.time(_func, N, kallable, *args, **kwargs)

    def test_serialize_empty_tags(self):
        # Measure overhead of operation
        self.time_N(10000, self.tobj._serialize_tag_dict, {})

    def test_deserialize_empty_tags(self):
        # Measure overhead of operation
        self.time_N(10000, self.tobj._deserialize_tag_dict, 'de')

    def test_serialize_tags(self):
        self.time_N(1000, self.tobj._serialize_tag_dict, self.tags)

    def test_deserialize_tags(self):
        self.time_N(1000, self.tobj._deserialize_tag_dict, self.bencoded_tags)
