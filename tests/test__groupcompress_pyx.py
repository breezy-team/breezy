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
        self.assertEqual('DeltaIndex(10)', repr(di))

    def test_make_delta(self):
        di = self._gc_module.DeltaIndex(_text1)
        delta = di.make_delta(_text2)
        self.assertEqual('MN\x90/\x1fdiffer from\nagainst other text\n', delta)
