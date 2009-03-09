# Copyright (C) 2009 Canonical Ltd
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

"""Tests for _chk_map_*."""

from bzrlib import tests


def load_tests(standard_tests, module, loader):
    # parameterize all tests in this module
    suite = loader.suiteClass()
    applier = tests.TestScenarioApplier()
    import bzrlib._chk_map_py as py_module
    applier.scenarios = [('python', {'module': py_module})]
    if CompiledChkMapFeature.available():
        import bzrlib._chk_map_pyx as c_module
        applier.scenarios.append(('C', {'module': c_module}))
    else:
        # the compiled module isn't available, so we add a failing test
        class FailWithoutFeature(tests.TestCase):
            def test_fail(self):
                self.requireFeature(CompiledChkMapFeature)
        suite.addTest(loader.loadTestsFromTestCase(FailWithoutFeature))
    tests.adapt_tests(standard_tests, applier, suite)
    return suite


class _CompiledChkMapFeature(tests.Feature):

    def _probe(self):
        try:
            import bzrlib._chk_map_pyx
        except ImportError:
            return False
        return True

    def feature_name(self):
        return 'bzrlib._chk_map_pyx'

CompiledChkMapFeature = _CompiledChkMapFeature()


class TestSearchKeys(tests.TestCase):

    module = None # Filled in by test parameterization

    def assertSearchKey16(self, expected, key):
        self.assertEqual(expected, self.module._search_key_16(key))

    def assertSearchKey255(self, expected, key):
        actual = self.module._search_key_255(key)
        self.assertEqual(expected, actual, 'actual: %r' % (actual,))

    def test_simple_16(self):
        self.assertSearchKey16('8C736521', ('foo',))
        self.assertSearchKey16('8C736521\x008C736521', ('foo', 'foo'))
        self.assertSearchKey16('8C736521\x0076FF8CAA', ('foo', 'bar'))
        self.assertSearchKey16('ED82CD11', ('abcd',))

    def test_simple_255(self):
        self.assertSearchKey255('\x8cse!', ('foo',))
        self.assertSearchKey255('\x8cse!\x00\x8cse!', ('foo', 'foo'))
        self.assertSearchKey255('\x8cse!\x00v\xff\x8c\xaa', ('foo', 'bar'))
        # The standard mapping for these would include '\n', so it should be
        # mapped to '_'
        self.assertSearchKey255('\xfdm\x93_\x00P_\x1bL', ('<', 'V'))

    def test_255_does_not_include_newline(self):
        # When mapping via _search_key_255, we should never have the '\n'
        # character, but all other 255 values should be present
        chars_used = set()
        for char_in in range(256):
            search_key = self.module._search_key_255((chr(char_in),))
            chars_used.update(search_key)
        all_chars = set([chr(x) for x in range(256)])
        unused_chars = all_chars.symmetric_difference(chars_used)
        self.assertEqual(set('\n'), unused_chars)
