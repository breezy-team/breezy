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

from .. import tests


def load_tests(loader, standard_tests, pattern):
    suite, _ = tests.permute_tests_for_extension(standard_tests, loader,
                                                 'breezy.util._bencode_py', 'breezy._bencode_pyx')
    return suite


class RecursionLimit(object):
    """Context manager that lowers recursion limit for testing."""

    def __init__(self, limit=100):
        self._new_limit = limit
        self._old_limit = sys.getrecursionlimit()

    def __enter__(self):
        sys.setrecursionlimit(self._new_limit)
        return self

    def __exit__(self, *exc_info):
        sys.setrecursionlimit(self._old_limit)


class TestBencodeDecode(tests.TestCase):

    module = None

    def _check(self, expected, source):
        self.assertEqual(expected, self.module.bdecode(source))

    def _run_check_error(self, exc, bad):
        """Check that bdecoding a string raises a particular exception."""
        self.assertRaises(exc, self.module.bdecode, bad)

    def test_int(self):
        self._check(0, b'i0e')
        self._check(4, b'i4e')
        self._check(123456789, b'i123456789e')
        self._check(-10, b'i-10e')
        self._check(int('1' * 1000), b'i' + (b'1' * 1000) + b'e')

    def test_long(self):
        self._check(12345678901234567890, b'i12345678901234567890e')
        self._check(-12345678901234567890, b'i-12345678901234567890e')

    def test_malformed_int(self):
        self._run_check_error(ValueError, b'ie')
        self._run_check_error(ValueError, b'i-e')
        self._run_check_error(ValueError, b'i-010e')
        self._run_check_error(ValueError, b'i-0e')
        self._run_check_error(ValueError, b'i00e')
        self._run_check_error(ValueError, b'i01e')
        self._run_check_error(ValueError, b'i-03e')
        self._run_check_error(ValueError, b'i')
        self._run_check_error(ValueError, b'i123')
        self._run_check_error(ValueError, b'i341foo382e')

    def test_string(self):
        self._check(b'', b'0:')
        self._check(b'abc', b'3:abc')
        self._check(b'1234567890', b'10:1234567890')

    def test_large_string(self):
        self.assertRaises(ValueError, self.module.bdecode, b"2147483639:foo")

    def test_malformed_string(self):
        self._run_check_error(ValueError, b'10:x')
        self._run_check_error(ValueError, b'10:')
        self._run_check_error(ValueError, b'10')
        self._run_check_error(ValueError, b'01:x')
        self._run_check_error(ValueError, b'00:')
        self._run_check_error(ValueError, b'35208734823ljdahflajhdf')
        self._run_check_error(ValueError, b'432432432432432:foo')
        self._run_check_error(ValueError, b' 1:x')  # leading whitespace
        self._run_check_error(ValueError, b'-1:x')  # negative
        self._run_check_error(ValueError, b'1 x')  # space vs colon
        self._run_check_error(ValueError, b'1x')  # missing colon
        self._run_check_error(ValueError, (b'1' * 1000) + b':')

    def test_list(self):
        self._check([], b'le')
        self._check([b'', b'', b''], b'l0:0:0:e')
        self._check([1, 2, 3], b'li1ei2ei3ee')
        self._check([b'asd', b'xy'], b'l3:asd2:xye')
        self._check([[b'Alice', b'Bob'], [2, 3]], b'll5:Alice3:Bobeli2ei3eee')

    def test_list_deepnested(self):
        with RecursionLimit():
            self._run_check_error(RuntimeError, (b"l" * 100) + (b"e" * 100))

    def test_malformed_list(self):
        self._run_check_error(ValueError, b'l')
        self._run_check_error(ValueError, b'l01:ae')
        self._run_check_error(ValueError, b'l0:')
        self._run_check_error(ValueError, b'li1e')
        self._run_check_error(ValueError, b'l-3:e')

    def test_dict(self):
        self._check({}, b'de')
        self._check({b'': 3}, b'd0:i3ee')
        self._check({b'age': 25, b'eyes': b'blue'}, b'd3:agei25e4:eyes4:bluee')
        self._check({b'spam.mp3': {b'author': b'Alice', b'length': 100000}},
                    b'd8:spam.mp3d6:author5:Alice6:lengthi100000eee')

    def test_dict_deepnested(self):
        with RecursionLimit():
            self._run_check_error(
                RuntimeError, (b"d0:" * 1000) + b'i1e' + (b"e" * 1000))

    def test_malformed_dict(self):
        self._run_check_error(ValueError, b'd')
        self._run_check_error(ValueError, b'defoobar')
        self._run_check_error(ValueError, b'd3:fooe')
        self._run_check_error(ValueError, b'di1e0:e')
        self._run_check_error(ValueError, b'd1:b0:1:a0:e')
        self._run_check_error(ValueError, b'd1:a0:1:a0:e')
        self._run_check_error(ValueError, b'd0:0:')
        self._run_check_error(ValueError, b'd0:')
        self._run_check_error(ValueError, b'd432432432432432432:e')

    def test_empty_string(self):
        self.assertRaises(ValueError, self.module.bdecode, b'')

    def test_junk(self):
        self._run_check_error(ValueError, b'i6easd')
        self._run_check_error(ValueError, b'2:abfdjslhfld')
        self._run_check_error(ValueError, b'0:0:')
        self._run_check_error(ValueError, b'leanfdldjfh')

    def test_unknown_object(self):
        self.assertRaises(ValueError, self.module.bdecode, b'relwjhrlewjh')

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
        self._check(b'i4e', 4)
        self._check(b'i0e', 0)
        self._check(b'i-10e', -10)

    def test_long(self):
        self._check(b'i12345678901234567890e', 12345678901234567890)
        self._check(b'i-12345678901234567890e', -12345678901234567890)

    def test_string(self):
        self._check(b'0:', b'')
        self._check(b'3:abc', b'abc')
        self._check(b'10:1234567890', b'1234567890')

    def test_list(self):
        self._check(b'le', [])
        self._check(b'li1ei2ei3ee', [1, 2, 3])
        self._check(b'll5:Alice3:Bobeli2ei3eee', [[b'Alice', b'Bob'], [2, 3]])

    def test_list_as_tuple(self):
        self._check(b'le', ())
        self._check(b'li1ei2ei3ee', (1, 2, 3))
        self._check(b'll5:Alice3:Bobeli2ei3eee', ((b'Alice', b'Bob'), (2, 3)))

    def test_list_deep_nested(self):
        top = []
        l = top
        for i in range(1000):
            l.append([])
            l = l[0]
        with RecursionLimit():
            self.assertRaises(RuntimeError, self.module.bencode, top)

    def test_dict(self):
        self._check(b'de', {})
        self._check(b'd3:agei25e4:eyes4:bluee', {b'age': 25, b'eyes': b'blue'})
        self._check(b'd8:spam.mp3d6:author5:Alice6:lengthi100000eee',
                    {b'spam.mp3': {b'author': b'Alice', b'length': 100000}})

    def test_dict_deep_nested(self):
        d = top = {}
        for i in range(1000):
            d[b''] = {}
            d = d[b'']
        with RecursionLimit():
            self.assertRaises(RuntimeError, self.module.bencode, top)

    def test_bencached(self):
        self._check(b'i3e', self.module.Bencached(self.module.bencode(3)))

    def test_invalid_dict(self):
        self.assertRaises(TypeError, self.module.bencode, {1: b"foo"})

    def test_bool(self):
        self._check(b'i1e', True)
        self._check(b'i0e', False)
