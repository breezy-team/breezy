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

"""Tests for bzrlib.debug"""


from bzrlib import (
    config,
    debug,
    tests,
    )


class TestDebugFlags(tests.TestCaseInTempDir):

    def test_set_debug_flags_from_config(self):
        # test both combinations because configobject automatically splits up
        # comma-separated lists
        self.try_debug_flags(['hpss', 'error'], 'debug_flags = hpss, error\n')
        self.try_debug_flags(['hpss'], 'debug_flags = hpss\n')

    def try_debug_flags(self, expected_flags, conf_bytes):
        conf = config.GlobalConfig.from_bytes(conf_bytes, save=True)
        self.overrideAttr(debug, 'debug_flags', set())
        debug.set_debug_flags_from_config()
        self.assertEqual(set(expected_flags), debug.debug_flags)
