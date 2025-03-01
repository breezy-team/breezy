# Copyright (C) 2009, 2010 Canonical Ltd
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

"""Tests for breezy.debug."""

from .. import config, debug, tests


class TestDebugFlags(tests.TestCaseInTempDir):
    def test_set_no_debug_flags_from_config(self):
        self.assertDebugFlags([], b"")

    def test_set_single_debug_flags_from_config(self):
        self.assertDebugFlags(["hpss"], b"debug_flags = hpss\n")

    def test_set_multiple_debug_flags_from_config(self):
        self.assertDebugFlags(["hpss", "error"], b"debug_flags = hpss, error\n")

    def assertDebugFlags(self, expected_flags, conf_bytes):
        conf = config.GlobalStack()
        conf.store._load_from_string(b"[DEFAULT]\n" + conf_bytes)
        conf.store.save()
        self.overrideAttr(debug, "debug_flags", set())
        debug.set_debug_flags_from_config()
        self.assertEqual(set(expected_flags), debug.debug_flags)
