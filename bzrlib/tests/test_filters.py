# Copyright (C) 2008 Canonical Ltd
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

import StringIO
from bzrlib import errors, filters
from bzrlib.filters import (
    ContentFilter,
    ContentFilterContext,
    filtered_input_file,
    filtered_output_lines,
    _get_filter_stack_for,
    _get_registered_names,
    sha_file_by_name,
    register_filter_stack_map,
    )
from bzrlib.osutils import sha_string
from bzrlib.tests import TestCase, TestCaseInTempDir


# sample filter stacks
_swapcase = lambda chunks, context=None: [s.swapcase() for s in chunks]
_addjunk = lambda chunks: ['junk\n'] + [s for s in chunks]
_deljunk = lambda chunks, context: [s for s in chunks[1:]]
_stack_1 = [
    ContentFilter(_swapcase, _swapcase),
    ]
_stack_2 = [
    ContentFilter(_swapcase, _swapcase),
    ContentFilter(_addjunk, _deljunk),
    ]

# sample data
_sample_external = ['Hello\n', 'World\n']
_internal_1 = ['hELLO\n', 'wORLD\n']
_internal_2 = ['junk\n', 'hELLO\n', 'wORLD\n']


class TestContentFilterContext(TestCase):

    def test_empty_filter_context(self):
        ctx = ContentFilterContext()
        self.assertRaises(NotImplementedError, ctx.relpath)

    def test_filter_context_with_path(self):
        ctx = ContentFilterContext('foo/bar')
        self.assertEquals('foo/bar', ctx.relpath())


class TestFilteredInput(TestCase):

    def test_filtered_input_file(self):
        # test an empty stack returns the same result
        external = ''.join(_sample_external)
        f = StringIO.StringIO(external)
        self.assertEqual(external, filtered_input_file(f, None).read())
        # test a single item filter stack
        f = StringIO.StringIO(external)
        expected = ''.join(_internal_1)
        self.assertEqual(expected, filtered_input_file(f, _stack_1).read())
        # test a multi item filter stack
        f = StringIO.StringIO(external)
        expected = ''.join(_internal_2)
        self.assertEqual(expected, filtered_input_file(f, _stack_2).read())


class TestFilteredOutput(TestCase):

    def test_filtered_output_lines(self):
        # test an empty stack returns the same result
        self.assertEqual(_sample_external, list(filtered_output_lines(
            _sample_external, None)))
        # test a single item filter stack
        self.assertEqual(_sample_external, list(filtered_output_lines(
            _internal_1, _stack_1)))
        # test a multi item filter stack
        self.assertEqual(_sample_external, list(filtered_output_lines(
            _internal_2, _stack_2)))


class TestFilteredSha(TestCaseInTempDir):

    def test_filtered_sha_byname(self):
        # check that the sha matches what's expected
        text = 'Foo Bar Baz\n'
        a = open('a', 'wb')
        a.write(text)
        a.close()
        expected_sha = sha_string(''.join(_swapcase([text], None)))
        self.assertEqual(expected_sha, sha_file_by_name('a',
            [ContentFilter(_swapcase, _swapcase)]))


class TestFilterStackMaps(TestCase):

    def _register_map(self, pref, stk1, stk2):
        register_filter_stack_map(pref, {'v1': stk1, 'v2': stk2})

    def test_filter_stack_maps(self):
        # Save the current registry
        original_registry = filters._reset_registry()
        # Test registration
        a_stack = [ContentFilter('b', 'c')]
        z_stack = [ContentFilter('y', 'x'), ContentFilter('w', 'v')]
        self._register_map('foo', a_stack, z_stack)
        self.assertEqual(['foo'], _get_registered_names())
        self._register_map('bar', z_stack, a_stack)
        self.assertEqual(['foo', 'bar'], _get_registered_names())
        # Test re-registration raises an error
        self.assertRaises(errors.BzrError, self._register_map, 'foo', [], [])
        # Restore the real registry
        filters._reset_registry(original_registry)

    def test_get_filter_stack_for(self):
        # Save the current registry
        original_registry = filters._reset_registry()
        # Test filter stack lookup
        a_stack = [ContentFilter('b', 'c')]
        d_stack = [ContentFilter('d', 'D')]
        z_stack = [ContentFilter('y', 'x'), ContentFilter('w', 'v')]
        self._register_map('foo', a_stack, z_stack)
        self._register_map('bar', d_stack, z_stack)
        prefs = (('foo','v1'),)
        self.assertEqual(a_stack, _get_filter_stack_for(prefs))
        prefs = (('foo','v2'),)
        self.assertEqual(z_stack, _get_filter_stack_for(prefs))
        prefs = (('foo','v1'),('bar','v1'))
        self.assertEqual(a_stack + d_stack, _get_filter_stack_for(prefs))
        # Test an unknown preference
        prefs = (('baz','v1'),)
        self.assertEqual([], _get_filter_stack_for(prefs))
        # Test an unknown value
        prefs = (('foo','v3'),)
        self.assertEqual([], _get_filter_stack_for(prefs))
        # Restore the real registry
        filters._reset_registry(original_registry)
