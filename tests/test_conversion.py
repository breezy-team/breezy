# Copyright (C) 2008 Canonical Limited.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 2 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301 USA
#

"""Tests for keyword expansion/contraction."""


from bzrlib import tests
from bzrlib.plugins.keywords import expand_keywords


# Sample keyword expansions
_keywords = {
    'Foo': 'FOO!',
    'Bar': 'bar',
    }


# Sample unexpanded and expanded pairs
_samples = [
    ('$Foo$',           '$Foo: FOO! $'),
    ('$Foo',            '$Foo'),
    ('Foo$',            'Foo$'),
    ('$Foo$ xyz',       '$Foo: FOO! $ xyz'),
    ('abc $Foo$',       'abc $Foo: FOO! $'),
    ('abc $Foo$ xyz',   'abc $Foo: FOO! $ xyz'),
    ('$Foo$$Bar$',      '$Foo: FOO! $$Bar: bar $'),
    ('abc $Foo$ xyz $Bar$ qwe', 'abc $Foo: FOO! $ xyz $Bar: bar $ qwe'),
    ('$Unknown$$Bar$',  '$Unknown$$Bar: bar $'),
    ('$Foo$$Unknown$',  '$Foo: FOO! $$Unknown$'),
    ]


class TestKeywordConversion(tests.TestCase):

    def test_expansion(self):
        # Test keyword expansion
        for raw, cooked in _samples:
            self.assertEqual(cooked, expand_keywords(raw, _keywords))
