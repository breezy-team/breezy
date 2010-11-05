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

See developers/testing.html for more explanations.
This module should be importable even if testtools aren't available.
"""

import os

from bzrlib import commands


class cmd_test_script(commands.Command):
    """Run a shell-like test from a file."""

    hidden = True
    takes_args = ['infile']

    @commands.display_command
    def run(self, infile):
        # local imports to defer testtools dependency
        from bzrlib import tests
        from bzrlib.tests.script import TestCaseWithTransportAndScript

        f = open(infile)
        try:
            script = f.read()
        finally:
            f.close()

        class Test(TestCaseWithTransportAndScript):

            script = None # Set before running

            def test_it(self):
                self.run_script(script)

        runner = tests.TextTestRunner(stream=self.outf)
        test = Test('test_it')
        test.path = os.path.realpath(infile)
        res = runner.run(test)
        return len(res.errors) + len(res.failures)
