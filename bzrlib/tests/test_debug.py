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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Tests for bzrlib.debug"""


import os


from bzrlib import debug
from bzrlib.config import config_filename, ensure_config_dir_exists
from bzrlib.transport import get_transport
from bzrlib.tests import TestCaseInTempDir


class TestDebugFlags(TestCaseInTempDir):

    def test_set_debug_flags_from_config(self):
        # test both combinations because configobject automatically splits up
        # comma-separated lists
        if os.path.isfile(config_filename()):
            # Something is wrong in environment,
            # we risk overwriting users config
            self.assert_(config_filename() + "exists, abort")

        self.try_debug_flags(
            """debug_flags = hpss, error\n""",
            set(['hpss', 'error']))

        self.try_debug_flags(
            """debug_flags = hpss\n""",
            set(['hpss']))

    def try_debug_flags(self, conf_bytes, expected_flags):
        ensure_config_dir_exists()
        f = open(config_filename(), 'wb')
        try:
            f.write(conf_bytes)
        finally:
            f.close()
        saved_debug = set(debug.debug_flags)
        debug.debug_flags.clear()
        try:
            debug.set_debug_flags_from_config()
            self.assertEqual(expected_flags,
                debug.debug_flags)
        finally:
            # restore without rebinding the variable
            debug.debug_flags.clear()
            debug.debug_flags.update(saved_debug)
