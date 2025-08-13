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
    """Tests for debug flag configuration functionality."""

    def test_set_no_debug_flags_from_config(self):
        """Test that no debug flags are set when config is empty."""
        self.assertDebugFlags([], b"")

    def test_set_single_debug_flags_from_config(self):
        """Test setting a single debug flag from config."""
        self.assertDebugFlags(["hpss"], b"debug_flags = hpss\n")

    def test_set_multiple_debug_flags_from_config(self):
        """Test setting multiple debug flags from config."""
        self.assertDebugFlags(["hpss", "error"], b"debug_flags = hpss, error\n")

    def assertDebugFlags(self, expected_flags, conf_bytes):
        """Assert that the given config bytes result in the expected debug flags.

        Args:
            expected_flags: List of expected debug flag names.
            conf_bytes: Configuration content as bytes.
        """
        conf = config.GlobalStack()
        conf.store._load_from_string(b"[DEFAULT]\n" + conf_bytes)
        conf.store.save()
        old_debug_flags = debug.get_debug_flags()
        self.addCleanup(debug.set_debug_flags, old_debug_flags)
        debug.clear_debug_flags()
        debug.set_debug_flags_from_config()
        self.assertEqual(set(expected_flags), debug.get_debug_flags())
