# Copyright (C) 2010 Canonical Ltd
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

"""Front-end command for shell-like test scripts.

See doc/developers/testing.txt for more explanations.
"""

import os

from . import commands, option


class cmd_test_script(commands.Command):
    """Run a shell-like test from a file."""

    hidden = True
    takes_args = ["infile"]
    takes_options = [
        option.Option("null-output", help="Null command outputs match any output."),
    ]

    @commands.display_command
    def run(self, infile, null_output=False):
        from breezy import tests

        from .tests.script import TestCaseWithTransportAndScript

        with open(infile) as f:
            script = f.read()

        class Test(TestCaseWithTransportAndScript):
            script = None  # Set before running

            def test_it(self):
                self.run_script(script, null_output_matches_anything=null_output)

        runner = tests.TextTestRunner(stream=self.outf)
        test = Test("test_it")
        test.path = os.path.realpath(infile)
        res = runner.run(test)
        return len(res.errors) + len(res.failures)
