# Copyright (C) 2012, 2013, 2016 Canonical Ltd
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

"""External tests of 'brz ping'."""

import breezy
from breezy import tests


class TestSmartServerPing(tests.TestCaseWithTransport):
    def test_simple_ping(self):
        self.setup_smart_server_with_call_log()
        t = self.make_branch_and_tree("branch")
        self.build_tree_contents([("branch/foo", b"thecontents")])
        t.add("foo")
        t.commit("message")
        self.reset_smart_call_log()
        out, err = self.run_bzr(["ping", self.get_url("branch")])
        self.assertLength(1, self.hpss_calls)
        self.assertLength(1, self.hpss_connections)
        self.assertEqual(
            out,
            "Response: (b'ok', b'2')\n"
            f"Headers: {{'Software version': '{breezy.version_string}'}}\n",
        )
        self.assertEqual(err, "")
