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

"""Tests for bencode structured encoding"""

from bzrlib.tests import TestCase, Feature

from bzrlib import bencode as bencode_default
from bzrlib.util import bencode as bencode_py
try:
    from bzrlib import _bencode_c as bencode_c
except ImportError:
    bencode_c = None


class _BencodeCFeature(Feature):

    def _probe(self):
        return bencode_c is not None

    def feature_name(self):
        return 'bzrlib._bencode_c'

BencodeCFeature = _BencodeCFeature()


class TestBencodeDecode(TestCase):

    bencode = bencode_default

    def _check(self, expected, source):
        self.assertEquals(expected, self.bencode.bdecode(source))

    def _run_check(self, pairs):
        """Run _check for each (expected, source) in pairs list"""
        for expected, source in pairs:
            self._check(expected, source)

    def _check_error(self, x):
        self.assertRaises(ValueError, self.bencode.bdecode, x)

    def _run_check_error(self, bads):
        """Run _check_error for each x in bads list"""
        for x in bads:
            self._check_error(x)

    def test_int(self):
        self._run_check([(0, 'i0e'),
                         (4, 'i4e'),
                         (123456789, 'i123456789e'),
                         (-10, 'i-10e')])

    def test_long(self):
        self._run_check([(12345678901234567890L, 'i12345678901234567890e'),
                         (-12345678901234567890L, 'i-12345678901234567890e')])

    def test_malformed_int(self):
        self._run_check_error(['ie', 'i-e',
                               'i-0e', 'i00e', 'i01e', 'i-03e',
                               'i', 'i123',
                               'i341foo382e'])

    def test_string(self):
        self._run_check([('', '0:'),
                         ('abc', '3:abc'),
                         ('1234567890', '10:1234567890')])

    def test_malformed_string(self):
        self._run_check_error(['10:x', '10:', '10',
                               '01:x', '00:',
                               '35208734823ljdahflajhdf'])

    def test_list(self):
        self._run_check([
                         ([], 'le'),
                         (['', '', ''], 'l0:0:0:e'),
                         ([1, 2, 3], 'li1ei2ei3ee'),
                         (['asd', 'xy'], 'l3:asd2:xye'),
                         ([['Alice', 'Bob'], [2, 3]],
                              'll5:Alice3:Bobeli2ei3eee'),
                        ])

    def test_malformed_list(self):
        self._run_check_error(['l', 'l01:ae', 'l0:', 'li1e', 'l-3:e'])

    def test_dict(self):
        self._run_check([({}, 'de'),
                         ({'':3}, 'd0:i3ee'),
                         ({'age': 25, 'eyes': 'blue'},
                            'd3:agei25e4:eyes4:bluee'),
                         ({'spam.mp3': {'author': 'Alice', 'length': 100000}},
                            'd8:spam.mp3d6:author5:Alice6:lengthi100000eee')])

    def test_malformed_dict(self):
        self._run_check_error(['d', 'defoobar',
                               'd3:fooe', 'di1e0:e',
                               'd1:b0:1:a0:e',
                               'd1:a0:1:a0:e',
                               'd0:0:', 'd0:'])

    def test_empty_string(self):
        self._check_error('')

    def test_junk(self):
        self._run_check_error(['i6easd', '2:abfdjslhfld',
                               '0:0:', 'leanfdldjfh'])

    def test_unknown_object(self):
        self._check_error('relwjhrlewjh')


class TestBencodeEncode(TestCase):

    bencode = bencode_default

    def _check(self, expected, source):
        self.assertEquals(expected, self.bencode.bencode(source))

    def _run_check(self, pairs):
        for expected, source in pairs:
            self._check(expected, source)

    def _check_error(self, x):
        self.assertRaises(TypeError, self.bencode.bencode, x)

    def test_int(self):
        self._run_check([('i4e', 4),
                         ('i0e', 0),
                         ('i-10e', -10)])

    def test_long(self):
        self._run_check([('i12345678901234567890e', 12345678901234567890L),
                         ('i-12345678901234567890e', -12345678901234567890L)])

    def test_string(self):
        self._run_check([('0:', ''),
                         ('3:abc', 'abc'),
                         ('10:1234567890', '1234567890')])

    def test_list(self):
        self._run_check([('le', []),
                         ('li1ei2ei3ee', [1, 2, 3]),
                         ('ll5:Alice3:Bobeli2ei3eee',
                            [['Alice', 'Bob'], [2, 3]])
                        ])

    def test_dict(self):
        self._run_check([('de', {}),
                         ('d3:agei25e4:eyes4:bluee',
                            {'age': 25, 'eyes': 'blue'}),
                         ('d8:spam.mp3d6:author5:Alice6:lengthi100000eee',
                            {'spam.mp3': {'author': 'Alice',
                                          'length': 100000}})
                         ])

    def test_bencached(self):
        self._check('i3e', self.bencode.Bencached(self.bencode.bencode(3)))

    def test_invalid_dict(self):
        self._check_error({1: 'foo'})

    def test_bool(self):
        self._run_check([('i1e', True),
                         ('i0e', False)])


class TestBencodePyDecode(TestBencodeDecode):
    bencode = bencode_py


class TestBencodePyEncode(TestBencodeEncode):
    bencode = bencode_py


class TestBencodeCDecode(TestBencodeDecode):
    _test_needs_features = [BencodeCFeature]
    bencode = bencode_c


class TestBencodeCEncode(TestBencodeEncode):
    _test_needs_features = [BencodeCFeature]
    bencode = bencode_c

    def test_unsupported_type(self):
        self._check_error(float(1.5))
        self._check_error(None)
        self._check_error(lambda x: x)
        self._check_error(object)


class TestBencodeC(TestCase):

    _test_needs_features = [BencodeCFeature]

    def test_decoder_repr(self):
        self.assertEquals("Decoder('123')", repr(bencode_c.Decoder('123')))

    def test_decoder_type_error(self):
        self.assertRaises(TypeError, bencode_c.Decoder, 1)

    def test_encoder_buffer_overflow(self):
        e = bencode_c.Encoder(256)
        shouldbe = []
        for i in '1234567890':
            s = i * 124
            e.process(s)
            shouldbe.extend(('124:', s))
        self.assertEquals(1280, len(str(e)))
        self.assertEquals(2048, e.maxsize)
        self.assertEquals(''.join(shouldbe), str(e))

    def test_encoder_buffer_overflow2(self):
        e = bencode_c.Encoder(4)
        e.process('1234567890')
        self.assertEquals(64, e.maxsize)
        self.assertEquals('10:1234567890', str(e))
