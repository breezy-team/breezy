# Copyright (C) 2006, 2007 Canonical Ltd
#   Authors: Robert Collins <robert.collins@canonical.com>
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

"""Symbol versioning tests."""

import bzrlib.symbol_versioning as symbol_versioning
from bzrlib.tests import TestCase


@symbol_versioning.deprecated_function(symbol_versioning.zero_seven)
def deprecated_function():
    """Deprecated function docstring."""
    return 1


a_deprecated_list = symbol_versioning.deprecated_list(symbol_versioning.zero_nine,
    'a_deprecated_list', ['one'], extra="Don't use me")


a_deprecated_dict = symbol_versioning.DeprecatedDict(
    symbol_versioning.zero_fourteen,
    'a_deprecated_dict',
    dict(a=42),
    advice='Pull the other one!',
    )


class TestDeprecationWarnings(TestCase):

    def capture_warning(self, message, category, stacklevel=None):
        self._warnings.append((message, category, stacklevel))

    def setUp(self):
        super(TestDeprecationWarnings, self).setUp()
        self._warnings = []
    
    @symbol_versioning.deprecated_method(symbol_versioning.zero_seven)
    def deprecated_method(self):
        """Deprecated method docstring.
        
        This might explain stuff.
        """
        return 1

    def test_deprecated_method(self):
        expected_warning = (
            "bzrlib.tests.test_symbol_versioning."
            "TestDeprecationWarnings.deprecated_method "
            "was deprecated in version 0.7.", DeprecationWarning, 2)
        expected_docstring = ('Deprecated method docstring.\n'
                              '        \n'
                              '        This might explain stuff.\n'
                              '        \n'
                              '        This method was deprecated in version 0.7.\n'
                              '        ')
        self.check_deprecated_callable(expected_warning, expected_docstring,
                                       "deprecated_method",
                                       "bzrlib.tests.test_symbol_versioning",
                                       self.deprecated_method)

    def test_deprecated_function(self):
        expected_warning = (
            "bzrlib.tests.test_symbol_versioning.deprecated_function "
            "was deprecated in version 0.7.", DeprecationWarning, 2)
        expected_docstring = ('Deprecated function docstring.\n'
                              '\n'
                              'This function was deprecated in version 0.7.\n'
                              )
        self.check_deprecated_callable(expected_warning, expected_docstring,
                                       "deprecated_function",
                                       "bzrlib.tests.test_symbol_versioning",
                                       deprecated_function)

    def test_deprecated_list(self):
        expected_warning = (
            "Modifying a_deprecated_list was deprecated in version 0.9."
            " Don't use me", DeprecationWarning, 3)
        old_warning_method = symbol_versioning.warn
        try:
            symbol_versioning.set_warning_method(self.capture_warning)
            self.assertEqual(['one'], a_deprecated_list)
            self.assertEqual([], self._warnings)

            a_deprecated_list.append('foo')
            self.assertEqual([expected_warning], self._warnings)
            self.assertEqual(['one', 'foo'], a_deprecated_list)

            a_deprecated_list.extend(['bar', 'baz'])
            self.assertEqual([expected_warning]*2, self._warnings)
            self.assertEqual(['one', 'foo', 'bar', 'baz'], a_deprecated_list)

            a_deprecated_list.insert(1, 'xxx')
            self.assertEqual([expected_warning]*3, self._warnings)
            self.assertEqual(['one', 'xxx', 'foo', 'bar', 'baz'], a_deprecated_list)

            a_deprecated_list.remove('foo')
            self.assertEqual([expected_warning]*4, self._warnings)
            self.assertEqual(['one', 'xxx', 'bar', 'baz'], a_deprecated_list)

            val = a_deprecated_list.pop()
            self.assertEqual([expected_warning]*5, self._warnings)
            self.assertEqual('baz', val)
            self.assertEqual(['one', 'xxx', 'bar'], a_deprecated_list)

            val = a_deprecated_list.pop(1)
            self.assertEqual([expected_warning]*6, self._warnings)
            self.assertEqual('xxx', val)
            self.assertEqual(['one', 'bar'], a_deprecated_list)
        finally:
            symbol_versioning.set_warning_method(old_warning_method)

    def test_deprecated_dict(self):
        expected_warning = (
            "access to a_deprecated_dict was deprecated in version 0.14."
            " Pull the other one!", DeprecationWarning, 2)
        old_warning_method = symbol_versioning.warn
        try:
            symbol_versioning.set_warning_method(self.capture_warning)
            self.assertEqual(len(a_deprecated_dict), 1)
            self.assertEqual([expected_warning], self._warnings)

            a_deprecated_dict['b'] = 42
            self.assertEqual(a_deprecated_dict['b'], 42)
            self.assertTrue('b' in a_deprecated_dict)
            del a_deprecated_dict['b']
            self.assertFalse('b' in a_deprecated_dict)
            self.assertEqual([expected_warning] * 6, self._warnings)
        finally:
            symbol_versioning.set_warning_method(old_warning_method)


    def check_deprecated_callable(self, expected_warning, expected_docstring,
                                  expected_name, expected_module,
                                  deprecated_callable):
        old_warning_method = symbol_versioning.warn
        try:
            symbol_versioning.set_warning_method(self.capture_warning)
            self.assertEqual(1, deprecated_callable())
            self.assertEqual([expected_warning], self._warnings)
            deprecated_callable()
            self.assertEqual([expected_warning, expected_warning],
                             self._warnings)
            self.assertEqualDiff(expected_docstring, deprecated_callable.__doc__)
            self.assertEqualDiff(expected_name, deprecated_callable.__name__)
            self.assertEqualDiff(expected_module, deprecated_callable.__module__)
            self.assertTrue(deprecated_callable.is_deprecated)
        finally:
            symbol_versioning.set_warning_method(old_warning_method)
    
    def test_deprecated_passed(self):
        self.assertEqual(True, symbol_versioning.deprecated_passed(None))
        self.assertEqual(True, symbol_versioning.deprecated_passed(True))
        self.assertEqual(True, symbol_versioning.deprecated_passed(False))
        self.assertEqual(False,
                         symbol_versioning.deprecated_passed(
                            symbol_versioning.DEPRECATED_PARAMETER))

    def test_deprecation_string(self):
        """We can get a deprecation string for a method or function."""
        self.assertEqual('bzrlib.tests.test_symbol_versioning.'
            'TestDeprecationWarnings.test_deprecation_string was deprecated in '
            'version 0.11.',
            symbol_versioning.deprecation_string(
            self.test_deprecation_string, symbol_versioning.zero_eleven))
        self.assertEqual('bzrlib.symbol_versioning.deprecated_function was '
            'deprecated in version 0.11.',
            symbol_versioning.deprecation_string(
                symbol_versioning.deprecated_function,
                symbol_versioning.zero_eleven))
