# Copyright (C) 2009, 2011 Canonical Ltd
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

"""Tests for eol conversion."""


from .. import (
    errors,
    )
from ..filters import _get_filter_stack_for
from ..filters.eol import (
    _to_crlf_converter,
    _to_lf_converter,
    )
from . import TestCase


# Sample files
_sample_file1 = b"""hello\nworld\r\n"""


class TestEolFilters(TestCase):

    def test_to_lf(self):
        result = _to_lf_converter([_sample_file1])
        self.assertEqual([b"hello\nworld\n"], result)

    def test_to_crlf(self):
        result = _to_crlf_converter([_sample_file1])
        self.assertEqual([b"hello\r\nworld\r\n"], result)


class TestEolRulesSpecifications(TestCase):

    def test_exact_value(self):
        """'eol = exact' should have no content filters"""
        prefs = (('eol', 'exact'),)
        self.assertEqual([], _get_filter_stack_for(prefs))

    def test_other_known_values(self):
        """These known eol values have corresponding filters."""
        known_values = ('lf', 'crlf', 'native',
                        'native-with-crlf-in-repo', 'lf-with-crlf-in-repo',
                        'crlf-with-crlf-in-repo')
        for value in known_values:
            prefs = (('eol', value),)
            self.assertNotEqual([], _get_filter_stack_for(prefs))

    def test_unknown_value(self):
        """
        Unknown eol values should raise an error.
        """
        prefs = (('eol', 'unknown-value'),)
        self.assertRaises(errors.BzrError, _get_filter_stack_for, prefs)

    def test_eol_missing_altogether_is_ok(self):
        """
        Not having eol in the set of preferences should be ok.
        """
        # In this case, 'eol' is looked up with a value of None.
        prefs = (('eol', None),)
        self.assertEqual([], _get_filter_stack_for(prefs))
