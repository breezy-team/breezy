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

"""Tests for bzrlib.debug"""


import os


from bzrlib import debug
from bzrlib.transport import get_transport
from bzrlib.tests import TestCaseInTempDir


class TestDebugFlags(TestCaseInTempDir):

    def test_set_debug_flags_from_config(self):
        # TestCase already makes a dummy HOME so we don't have to
        t = get_transport(os.environ['HOME'])

        # guard against being run from the wrong directory
        self.assertFalse(t.has(".bazaar"))

        t.mkdir(".bazaar")
        t.put_bytes(".bazaar/bazaar.conf",
            """debug_flags = hpss, error\n""")
        saved_debug = set(debug.debug_flags)
        try:
            debug.set_debug_flags_from_config()
            self.assertEqual(set(['hpss', 'error']),
                debug.debug_flags)
        finally:
            # restore without rebinding the variable
            debug.debug_flags.clear()
            debug.debug_flags.update(saved_debug)
