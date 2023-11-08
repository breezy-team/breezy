# Copyright (C) 2008, 2009, 2012, 2016 Canonical Ltd
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

from io import BytesIO

from .. import filters
from ..filters import (
    ContentFilter,
    ContentFilterContext,
    _get_filter_stack_for,
    _get_registered_names,
    filtered_input_file,
    filtered_output_bytes,
    internal_size_sha_file_byname,
)
from ..osutils import sha_string
from . import TestCase, TestCaseInTempDir


# sample filter stacks
def _swapcase(chunks, context=None):
    return [s.swapcase() for s in chunks]


def _addjunk(chunks):
    return [b"junk\n"] + list(chunks)


def _deljunk(chunks, context):
    return list(chunks[1:])


_stack_1 = [
    ContentFilter(_swapcase, _swapcase),
]
_stack_2 = [
    ContentFilter(_swapcase, _swapcase),
    ContentFilter(_addjunk, _deljunk),
]

# sample data
_sample_external = [b"Hello\n", b"World\n"]
_internal_1 = [b"hELLO\n", b"wORLD\n"]
_internal_2 = [b"junk\n", b"hELLO\n", b"wORLD\n"]


class TestContentFilterContext(TestCase):
    def test_empty_filter_context(self):
        ctx = ContentFilterContext()
        self.assertEqual(None, ctx.relpath())

    def test_filter_context_with_path(self):
        ctx = ContentFilterContext("foo/bar")
        self.assertEqual("foo/bar", ctx.relpath())


class TestFilteredInput(TestCase):
    def test_filtered_input_file(self):
        # test an empty stack returns the same result
        external = b"".join(_sample_external)
        f = BytesIO(external)
        (fileobj, size) = filtered_input_file(f, [])
        self.assertEqual((external, 12), (fileobj.read(), size))
        # test a single item filter stack
        f = BytesIO(external)
        expected = b"".join(_internal_1)
        (fileobj, size) = filtered_input_file(f, _stack_1)
        self.assertEqual((expected, 12), (fileobj.read(), size))
        # test a multi item filter stack
        f = BytesIO(external)
        expected = b"".join(_internal_2)
        (fileobj, size) = filtered_input_file(f, _stack_2)
        self.assertEqual((expected, 17), (fileobj.read(), size))


class TestFilteredOutput(TestCase):
    def test_filtered_output_bytes(self):
        # test an empty stack returns the same result
        self.assertEqual(
            _sample_external, list(filtered_output_bytes(_sample_external, None))
        )
        # test a single item filter stack
        self.assertEqual(
            _sample_external, list(filtered_output_bytes(_internal_1, _stack_1))
        )
        # test a multi item filter stack
        self.assertEqual(
            _sample_external, list(filtered_output_bytes(_internal_2, _stack_2))
        )


class TestFilteredSha(TestCaseInTempDir):
    def test_filtered_size_sha(self):
        # check that the size and sha matches what's expected
        text = b"Foo Bar Baz\n"
        with open("a", "wb") as a:
            a.write(text)
        post_filtered_content = b"".join(_swapcase([text], None))
        expected_len = len(post_filtered_content)
        expected_sha = sha_string(post_filtered_content)
        self.assertEqual(
            (expected_len, expected_sha),
            internal_size_sha_file_byname("a", [ContentFilter(_swapcase, _swapcase)]),
        )


class TestFilterStackMaps(TestCase):
    def _register_map(self, pref, stk1, stk2):
        def stk_lookup(key):
            return {"v1": stk1, "v2": stk2}.get(key)

        filters.filter_stacks_registry.register(pref, stk_lookup)

    def test_filter_stack_maps(self):
        # Save the current registry
        original_registry = filters._reset_registry()
        self.addCleanup(filters._reset_registry, original_registry)
        # Test registration
        a_stack = [ContentFilter("b", "c")]
        z_stack = [ContentFilter("y", "x"), ContentFilter("w", "v")]
        self._register_map("foo", a_stack, z_stack)
        self.assertEqual(["foo"], _get_registered_names())
        self._register_map("bar", z_stack, a_stack)
        self.assertEqual(["bar", "foo"], _get_registered_names())
        # Test re-registration raises an error
        self.assertRaises(KeyError, self._register_map, "foo", [], [])

    def test_get_filter_stack_for(self):
        # Save the current registry
        original_registry = filters._reset_registry()
        self.addCleanup(filters._reset_registry, original_registry)
        # Test filter stack lookup
        a_stack = [ContentFilter("b", "c")]
        d_stack = [ContentFilter("d", "D")]
        z_stack = [ContentFilter("y", "x"), ContentFilter("w", "v")]
        self._register_map("foo", a_stack, z_stack)
        self._register_map("bar", d_stack, z_stack)
        prefs = (("foo", "v1"),)
        self.assertEqual(a_stack, _get_filter_stack_for(prefs))
        prefs = (("foo", "v2"),)
        self.assertEqual(z_stack, _get_filter_stack_for(prefs))
        prefs = (("foo", "v1"), ("bar", "v1"))
        self.assertEqual(a_stack + d_stack, _get_filter_stack_for(prefs))
        # Test an unknown preference
        prefs = (("baz", "v1"),)
        self.assertEqual([], _get_filter_stack_for(prefs))
        # Test an unknown value
        prefs = (("foo", "v3"),)
        self.assertEqual([], _get_filter_stack_for(prefs))
        # Test a value of None is skipped
        prefs = (("foo", None), ("bar", "v1"))
        self.assertEqual(d_stack, _get_filter_stack_for(prefs))
