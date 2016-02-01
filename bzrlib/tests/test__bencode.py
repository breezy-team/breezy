# Copyright (C) 2007, 2009, 2010, 2016 Canonical Ltd
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

"""Tests for bencode structured encoding"""

import sys

from bzrlib import tests

def load_tests(standard_tests, module, loader):
    suite, _ = tests.permute_tests_for_extension(standard_tests, loader,
        'bzrlib.util._bencode_py', 'bzrlib._bencode_pyx')
    return suite


class TestBencodeDecode(tests.TestCase):

    module = None

    def _check(self, expected, source):
        self.assertEqual(expected, self.module.bdecode(source))

    def _run_check_error(self, exc, bad):
        """Check that bdecoding a string raises a particular exception."""
        self.assertRaises(exc, self.module.bdecode, bad)

    def test_int(self):
        self._check(0, 'i0e')
        self._check(4, 'i4e')
        self._check(123456789, 'i123456789e')
        self._check(-10, 'i-10e')
        self._check(int('1' * 1000), 'i' + ('1' * 1000) + 'e')

    def test_long(self):
        self._check(12345678901234567890L, 'i12345678901234567890e')
        self._check(-12345678901234567890L, 'i-12345678901234567890e')

    def test_malformed_int(self):
        self._run_check_error(ValueError, 'ie')
        self._run_check_error(ValueError, 'i-e')
        self._run_check_error(ValueError, 'i-010e')
        self._run_check_error(ValueError, 'i-0e')
        self._run_check_error(ValueError, 'i00e')
        self._run_check_error(ValueError, 'i01e')
        self._run_check_error(ValueError, 'i-03e')
        self._run_check_error(ValueError, 'i')
        self._run_check_error(ValueError, 'i123')
        self._run_check_error(ValueError, 'i341foo382e')

    def test_string(self):
        self._check('', '0:')
        self._check('abc', '3:abc')
        self._check('1234567890', '10:1234567890')

    def test_large_string(self):
        self.assertRaises(ValueError, self.module.bdecode, "2147483639:foo")

    def test_malformed_string(self):
        self._run_check_error(ValueError, '10:x')
        self._run_check_error(ValueError, '10:')
        self._run_check_error(ValueError, '10')
        self._run_check_error(ValueError, '01:x')
        self._run_check_error(ValueError, '00:')
        self._run_check_error(ValueError, '35208734823ljdahflajhdf')
        self._run_check_error(ValueError, '432432432432432:foo')
        self._run_check_error(ValueError, ' 1:x') # leading whitespace
        self._run_check_error(ValueError, '-1:x') # negative
        self._run_check_error(ValueError, '1 x') # space vs colon
        self._run_check_error(ValueError, '1x') # missing colon
        self._run_check_error(ValueError, ('1' * 1000) + ':')

    def test_list(self):
        self._check([], 'le')
        self._check(['', '', ''], 'l0:0:0:e')
        self._check([1, 2, 3], 'li1ei2ei3ee')
        self._check(['asd', 'xy'], 'l3:asd2:xye')
        self._check([['Alice', 'Bob'], [2, 3]], 'll5:Alice3:Bobeli2ei3eee')

    def test_list_deepnested(self):
        self._run_check_error(RuntimeError, ("l" * 10000) + ("e" * 10000))

    def test_malformed_list(self):
        self._run_check_error(ValueError, 'l')
        self._run_check_error(ValueError, 'l01:ae')
        self._run_check_error(ValueError, 'l0:')
        self._run_check_error(ValueError, 'li1e')
        self._run_check_error(ValueError, 'l-3:e')

    def test_dict(self):
        self._check({}, 'de')
        self._check({'':3}, 'd0:i3ee')
        self._check({'age': 25, 'eyes': 'blue'}, 'd3:agei25e4:eyes4:bluee')
        self._check({'spam.mp3': {'author': 'Alice', 'length': 100000}},
                            'd8:spam.mp3d6:author5:Alice6:lengthi100000eee')

    def test_dict_deepnested(self):
        # The recursion here provokes CPython into emitting a warning on
        # stderr, "maximum recursion depth exceeded in __subclasscheck__", due
        # to running out of stack space while evaluating "except (...):" in
        # _bencode_py.  This is harmless, so we temporarily override stderr to
        # avoid distracting noise in the test output.
        self.overrideAttr(sys, 'stderr', self._log_file)
        self._run_check_error(
            RuntimeError, ("d0:" * 10000) + 'i1e' + ("e" * 10000))

    def test_malformed_dict(self):
        self._run_check_error(ValueError, 'd')
        self._run_check_error(ValueError, 'defoobar')
        self._run_check_error(ValueError, 'd3:fooe')
        self._run_check_error(ValueError, 'di1e0:e')
        self._run_check_error(ValueError, 'd1:b0:1:a0:e')
        self._run_check_error(ValueError, 'd1:a0:1:a0:e')
        self._run_check_error(ValueError, 'd0:0:')
        self._run_check_error(ValueError, 'd0:')
        self._run_check_error(ValueError, 'd432432432432432432:e')

    def test_empty_string(self):
        self.assertRaises(ValueError, self.module.bdecode, '')

    def test_junk(self):
        self._run_check_error(ValueError, 'i6easd')
        self._run_check_error(ValueError, '2:abfdjslhfld')
        self._run_check_error(ValueError, '0:0:')
        self._run_check_error(ValueError, 'leanfdldjfh')

    def test_unknown_object(self):
        self.assertRaises(ValueError, self.module.bdecode, 'relwjhrlewjh')

    def test_unsupported_type(self):
        self._run_check_error(TypeError, float(1.5))
        self._run_check_error(TypeError, None)
        self._run_check_error(TypeError, lambda x: x)
        self._run_check_error(TypeError, object)
        self._run_check_error(TypeError, u"ie")

    def test_decoder_type_error(self):
        self.assertRaises(TypeError, self.module.bdecode, 1)


class TestBencodeEncode(tests.TestCase):

    module = None

    def _check(self, expected, source):
        self.assertEqual(expected, self.module.bencode(source))

    def test_int(self):
        self._check('i4e', 4)
        self._check('i0e', 0)
        self._check('i-10e', -10)

    def test_long(self):
        self._check('i12345678901234567890e', 12345678901234567890L)
        self._check('i-12345678901234567890e', -12345678901234567890L)

    def test_string(self):
        self._check('0:', '')
        self._check('3:abc', 'abc')
        self._check('10:1234567890', '1234567890')

    def test_list(self):
        self._check('le', [])
        self._check('li1ei2ei3ee', [1, 2, 3])
        self._check('ll5:Alice3:Bobeli2ei3eee', [['Alice', 'Bob'], [2, 3]])

    def test_list_as_tuple(self):
        self._check('le', ())
        self._check('li1ei2ei3ee', (1, 2, 3))
        self._check('ll5:Alice3:Bobeli2ei3eee', (('Alice', 'Bob'), (2, 3)))

    def test_list_deep_nested(self):
        top = []
        l = top
        for i in range(10000):
            l.append([])
            l = l[0]
        self.assertRaises(RuntimeError, self.module.bencode, 
            top)

    def test_dict(self):
        self._check('de', {})
        self._check('d3:agei25e4:eyes4:bluee', {'age': 25, 'eyes': 'blue'})
        self._check('d8:spam.mp3d6:author5:Alice6:lengthi100000eee',
                            {'spam.mp3': {'author': 'Alice',
                                          'length': 100000}})

    def test_dict_deep_nested(self):
        d = top = {}
        for i in range(10000):
            d[''] = {}
            d = d['']
        self.assertRaises(RuntimeError, self.module.bencode, 
            top)

    def test_bencached(self):
        self._check('i3e', self.module.Bencached(self.module.bencode(3)))

    def test_invalid_dict(self):
        self.assertRaises(TypeError, self.module.bencode, {1:"foo"})

    def test_bool(self):
        self._check('i1e', True)
        self._check('i0e', False)

