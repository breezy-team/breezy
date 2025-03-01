# Copyright (C) 2010, 2011, 2012, 2016 Canonical Ltd
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

"""Tests of breezy test matchers."""

from ...tests import CapturedCall, TestCase
from ..smart.client import CallHookParams
from .matchers import *  # noqa: F403


class TestContainsNoVfsCalls(TestCase):
    def _make_call(self, method, args):
        return CapturedCall(CallHookParams(method, args, None, None, None), 0)

    def test__str__(self):
        self.assertEqual("ContainsNoVfsCalls()", str(ContainsNoVfsCalls()))

    def test_empty(self):
        self.assertIs(None, ContainsNoVfsCalls().match([]))

    def test_no_vfs_calls(self):
        calls = [self._make_call("Branch.get_config_file", [])]
        self.assertIs(None, ContainsNoVfsCalls().match(calls))

    def test_ignores_unknown(self):
        calls = [self._make_call("unknown", [])]
        self.assertIs(None, ContainsNoVfsCalls().match(calls))

    def test_match(self):
        calls = [
            self._make_call(b"append", [b"file"]),
            self._make_call(b"Branch.get_config_file", []),
        ]
        mismatch = ContainsNoVfsCalls().match(calls)
        self.assertIsNot(None, mismatch)
        self.assertEqual([calls[0].call], mismatch.vfs_calls)
        self.assertIn(
            mismatch.describe(),
            [
                "no VFS calls expected, got: b'append'(b'file')",
                "no VFS calls expected, got: append('file')",
            ],
        )
