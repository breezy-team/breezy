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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Tests for bencode structured encoding"""

from bzrlib import tests

def load_tests(standard_tests, module, loader):
    # parameterize all tests in this module
    suite = loader.suiteClass()
    import bzrlib._bencode_py as py_module
    scenarios = [('python', {'bencode': py_module})]
    if CompiledBencodeFeature.available():
        import bzrlib._bencode_c as c_module
        scenarios.append(('C', {'bencode': c_module}))
    else:
        # the compiled module isn't available, so we add a failing test
        class FailWithoutFeature(tests.TestCase):
            def test_fail(self):
                self.requireFeature(CompiledBencodeFeature)
        suite.addTest(loader.loadTestsFromTestCase(FailWithoutFeature))
    tests.multiply_tests(standard_tests, scenarios, suite)
    return suite


class _CompiledBencodeFeature(tests.Feature):

    def _probe(self):
        try:
            import bzrlib._bencode_c
        except ImportError:
            return False
        return True

    def feature_name(self):
        return 'bzrlib._bencode_c'

CompiledBencodeFeature = _CompiledBencodeFeature()


class TestBencodeDecode(tests.TestCase):

    bencode = None

    def _check(self, expected, source):
        self.assertEquals(expected, self.bencode.bdecode(source))

    def _run_check(self, pairs):
        """Run _check for each (expected, source) in pairs list"""
        for expected, source in pairs:
            self._check(expected, source)

    def _run_check_error(self, exc, bads):
        """Check that bdecoding each string raises a particular exception."""
        for x in bads:
            self.assertRaises(exc, self.bencode.bdecode, x)

    def test_int(self):
        self._run_check([(0, 'i0e'),
                         (4, 'i4e'),
                         (123456789, 'i123456789e'),
                         (-10, 'i-10e')])

    def test_long(self):
        self._run_check([(12345678901234567890L, 'i12345678901234567890e'),
                         (-12345678901234567890L, 'i-12345678901234567890e')])

    def test_malformed_int(self):
        self._run_check_error(ValueError, ['ie', 'i-e', 'i-010e',
                               'i-0e', 'i00e', 'i01e', 'i-03e',
                               'i', 'i123', 
                               'i341foo382e'])

    def test_string(self):
        self._run_check([('', '0:'),
                         ('abc', '3:abc'),
                         ('1234567890', '10:1234567890')])

    def test_large_string(self):
        self.assertRaises(ValueError, self.bencode.bdecode, "2147483639:foo")

    def test_malformed_string(self):
        self._run_check_error(ValueError, ['10:x', '10:', '10',
                               '01:x', '00:',
                               '35208734823ljdahflajhdf',
                               '432432432432432:foo'])

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
        self._run_check_error(ValueError, [
            'l', 'l01:ae', 'l0:', 'li1e', 'l-3:e'])

    def test_dict(self):
        self._run_check([({}, 'de'),
                         ({'':3}, 'd0:i3ee'),
                         ({'age': 25, 'eyes': 'blue'},
                            'd3:agei25e4:eyes4:bluee'),
                         ({'spam.mp3': {'author': 'Alice', 'length': 100000}},
                            'd8:spam.mp3d6:author5:Alice6:lengthi100000eee')])

    def test_malformed_dict(self):
        self._run_check_error(ValueError, ['d', 'defoobar',
                               'd3:fooe', 'di1e0:e',
                               'd1:b0:1:a0:e',
                               'd1:a0:1:a0:e',
                               'd0:0:', 'd0:',
                               'd432432432432432432:e', ])

    def test_empty_string(self):
        self.assertRaises(ValueError, self.bencode.bdecode, '')

    def test_junk(self):
        self._run_check_error(ValueError, ['i6easd', '2:abfdjslhfld',
                               '0:0:', 'leanfdldjfh'])

    def test_unknown_object(self):
        self.assertRaises(ValueError, self.bencode.bdecode, 'relwjhrlewjh')

    def test_unsupported_type(self):
        self._run_check_error(TypeError, [
            float(1.5), None, lambda x: x, object, u"ie"])

    def test_decoder_type_error(self):
        self.assertRaises(TypeError, self.bencode.bdecode, 1)


class TestBencodeEncode(tests.TestCase):

    bencode = None

    def _check(self, expected, source):
        self.assertEquals(expected, self.bencode.bencode(source))

    def _run_check(self, pairs):
        for expected, source in pairs:
            self._check(expected, source)

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

    def test_list_as_tuple(self):
        self._run_check([('le', ()),
                         ('li1ei2ei3ee', (1, 2, 3)),
                         ('ll5:Alice3:Bobeli2ei3eee',
                            (('Alice', 'Bob'), (2, 3)))
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
        self.assertRaises(TypeError, self.bencode.bencode, {1:"foo"})

    def test_bool(self):
        self._run_check([('i1e', True),
                         ('i0e', False)])

