# Copyright (C) 2008 Canonical Limited.
# 
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as published
# by the Free Software Foundation.
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

"""Tests for the pyrex extension of groupcompress"""

from bzrlib import tests

from bzrlib.plugins.groupcompress_rabin import groupcompress


class _CompiledGroupCompress(tests.Feature):

    def _probe(self):
        try:
            import bzrlib.plugins.groupcompress_rabin._groupcompress_pyx
        except ImportError:
            return False
        else:
            return True

    def feature_name(self):
        return 'bzrlib.plugins.groupcompress_rabin._groupcompress_pyx'

CompiledGroupCompress = _CompiledGroupCompress()

_text1 = """\
This is a bit
of source text
which is meant to be matched
against other text
"""

_text2 = """\
This is a bit
of source text
which is meant to differ from
against other text
"""

_text3 = """\
This is a bit
of source text
which is meant to be matched
against other text
except it also
has a lot more data
at the end of the file
"""

_first_text = """\
a bit of text, that
does not have much in
common with the next text
"""

_second_text = """\
some more bits of text
which does have a little bit in
common with the previous text
"""


_third_text = """\
a bit of text, that
has some in common with the previous text
and not much in
common with the next text
"""


class Test_GroupCompress(tests.TestCase):
    """Direct tests for the compiled extension."""

    def setUp(self):
        super(Test_GroupCompress, self).setUp()
        self.requireFeature(CompiledGroupCompress)
        from bzrlib.plugins.groupcompress_rabin import _groupcompress_pyx
        self._gc_module = _groupcompress_pyx


class TestMakeAndApplyDelta(Test_GroupCompress):

    def setUp(self):
        super(TestMakeAndApplyDelta, self).setUp()
        self.make_delta = self._gc_module.make_delta
        self.apply_delta = self._gc_module.apply_delta

    def test_make_delta_is_typesafe(self):
        self.make_delta('a string', 'another string')
        self.assertRaises(TypeError,
            self.make_delta, 'a string', object())
        self.assertRaises(TypeError,
            self.make_delta, 'a string', u'not a string')
        self.assertRaises(TypeError,
            self.make_delta, object(), 'a string')
        self.assertRaises(TypeError,
            self.make_delta, u'not a string', 'a string')

    def test_make_noop_delta(self):
        ident_delta = self.make_delta(_text1, _text1)
        self.assertEqual('MM\x90M', ident_delta)
        ident_delta = self.make_delta(_text2, _text2)
        self.assertEqual('NN\x90N', ident_delta)
        ident_delta = self.make_delta(_text3, _text3)
        self.assertEqual('\x87\x01\x87\x01\x90\x87', ident_delta)

    def test_make_delta(self):
        delta = self.make_delta(_text1, _text2)
        self.assertEqual('MN\x90/\x1fdiffer from\nagainst other text\n', delta)
        delta = self.make_delta(_text2, _text1)
        self.assertEqual('NM\x90/\x1ebe matched\nagainst other text\n', delta)
        delta = self.make_delta(_text3, _text1)
        self.assertEqual('\x87\x01M\x90M', delta)
        delta = self.make_delta(_text3, _text2)
        self.assertEqual('\x87\x01N\x90/\x1fdiffer from\nagainst other text\n',
                         delta)

    def test_apply_delta_is_typesafe(self):
        self.apply_delta(_text1, 'MM\x90M')
        self.assertRaises(TypeError,
            self.apply_delta, object(), 'MM\x90M')
        self.assertRaises(TypeError,
            self.apply_delta, unicode(_text1), 'MM\x90M')
        self.assertRaises(TypeError,
            self.apply_delta, _text1, u'MM\x90M')
        self.assertRaises(TypeError,
            self.apply_delta, _text1, object())

    def test_apply_delta(self):
        target = self.apply_delta(_text1,
                    'MN\x90/\x1fdiffer from\nagainst other text\n')
        self.assertEqual(_text2, target)
        target = self.apply_delta(_text2,
                    'NM\x90/\x1ebe matched\nagainst other text\n')
        self.assertEqual(_text1, target)


class TestDeltaIndex(Test_GroupCompress):

    def test_repr(self):
        di = self._gc_module.DeltaIndex('test text\n')
        self.assertEqual('DeltaIndex(1, 10, 1)', repr(di))

    def test_make_delta(self):
        di = self._gc_module.DeltaIndex(_text1)
        delta = di.make_delta(_text2)
        self.assertEqual('MN\x90/\x1fdiffer from\nagainst other text\n', delta)

    def test_delta_against_multiple_sources(self):
        di = self._gc_module.DeltaIndex()
        di.add_source(_first_text, 0)
        self.assertEqual(1, di._num_indexes)
        self.assertEqual(1024, di._max_num_indexes)
        self.assertEqual(len(_first_text), di._source_offset)
        di.add_source(_second_text, 0)
        self.assertEqual(2, di._num_indexes)
        self.assertEqual(1024, di._max_num_indexes)
        self.assertEqual(len(_first_text) + len(_second_text), di._source_offset)
        delta = di.make_delta(_third_text)
        result = self._gc_module.apply_delta(_first_text + _second_text, delta)
        self.assertEqualDiff(_third_text, result)
        self.assertEqual('\x99\x01h\x90\x14\x0chas some in '
                         '\x91{\x1e\x07and not\x91!#', delta)

    def test_delta_with_offsets(self):
        di = self._gc_module.DeltaIndex()
        di.add_source(_first_text, 5)
        self.assertEqual(1, di._num_indexes)
        self.assertEqual(1024, di._max_num_indexes)
        self.assertEqual(len(_first_text) + 5, di._source_offset)
        di.add_source(_second_text, 10)
        self.assertEqual(2, di._num_indexes)
        self.assertEqual(1024, di._max_num_indexes)
        self.assertEqual(len(_first_text) + len(_second_text) + 15,
                         di._source_offset)
        delta = di.make_delta(_third_text)
        self.assertIsNot(None, delta)
        result = self._gc_module.apply_delta(
            '12345' + _first_text + '1234567890' + _second_text, delta)
        self.assertIsNot(None, result)
        self.assertEqualDiff(_third_text, result)
        self.assertEqual('\xa8\x01h\x91\x05\x14\x0chas some in '
                         '\x91\x8a\x1e\x07and not\x91&#', delta)
