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

from __future__ import absolute_import

"""Tests for keyword expansion/contraction."""


from .... import tests
from ..keywords import (
    compress_keywords,
    expand_keywords,
    )


# Sample unexpanded and expanded pairs for a keyword dictionary
_keywords = {'Foo': 'FOO!', 'Bar': 'bar', 'CallMe': lambda c: "now!"}
_keywords_dicts = [{'Foo': 'FOO!'}, {'Bar': 'bar', 'CallMe': lambda c: "now!"}]
_samples = [
    (b'$Foo$',           b'$Foo: FOO! $'),
    (b'$Foo',            b'$Foo'),
    (b'Foo$',            b'Foo$'),
    (b'$Foo$ xyz',       b'$Foo: FOO! $ xyz'),
    (b'abc $Foo$',       b'abc $Foo: FOO! $'),
    (b'abc $Foo$ xyz',   b'abc $Foo: FOO! $ xyz'),
    (b'$Foo$$Bar$',      b'$Foo: FOO! $$Bar: bar $'),
    (b'abc $Foo$ xyz $Bar$ qwe', b'abc $Foo: FOO! $ xyz $Bar: bar $ qwe'),
    (b'$Unknown$$Bar$',  b'$Unknown$$Bar: bar $'),
    (b'$Unknown: unkn $$Bar$',  b'$Unknown: unkn $$Bar: bar $'),
    (b'$Foo$$Unknown$',  b'$Foo: FOO! $$Unknown$'),
    (b'$CallMe$',        b'$CallMe: now! $'),
    ]


class TestKeywordsConversion(tests.TestCase):

    def test_compression(self):
        # Test keyword expansion
        for raw, cooked in _samples:
            self.assertEqual(raw, compress_keywords(cooked, [_keywords]))

    def test_expansion(self):
        # Test keyword expansion
        for raw, cooked in _samples:
            self.assertEqual(cooked, expand_keywords(raw, [_keywords]))

    def test_expansion_across_multiple_dictionaries(self):
        # Check all still works when keywords in different dictionaries
        for raw, cooked in _samples:
            self.assertEqual(cooked, expand_keywords(raw, _keywords_dicts))

    def test_expansion_feedback_when_unsafe(self):
        kw_dict = {'Xxx': 'y$z'}
        self.assertEqual(b'$Xxx: (value unsafe to expand) $',
            expand_keywords(b'$Xxx$', [kw_dict]))

    def test_expansion_feedback_when_error(self):
        kw_dict = {'Xxx': lambda ctx: ctx.unknownMethod}
        self.assertEqual(b'$Xxx: (evaluation error) $',
            expand_keywords(b'$Xxx$', [kw_dict]))

    def test_expansion_replaced_if_already_expanded(self):
        s = b'$Xxx: old value $'
        kw_dict = {'Xxx': 'new value'}
        self.assertEqual(b'$Xxx: new value $', expand_keywords(s, [kw_dict]))

    def test_expansion_ignored_if_already_expanded_but_unknown(self):
        s = b'$Xxx: old value $'
        self.assertEqual(b'$Xxx: old value $', expand_keywords(s, [{}]))
