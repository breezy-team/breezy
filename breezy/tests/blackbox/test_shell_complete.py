# Copyright (C) 2011 Canonical Ltd
# -*- coding: utf-8 -*-
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


"""Black-box tests for 'brz shell-complete'."""

from breezy.tests import TestCaseWithTransport


class ShellCompleteTests(TestCaseWithTransport):

    def test_list(self):
        out, err = self.run_bzr('shell-complete')
        self.assertEqual('', err)
        self.assertIn("version:show version of brz\n", out)

    def test_specific_command_missing(self):
        out, err = self.run_bzr('shell-complete missing-command', retcode=3)
        self.assertEqual(
            'brz: ERROR: unknown command "missing-command"\n', err)
        self.assertEqual('', out)

    def test_specific_command(self):
        out, err = self.run_bzr('shell-complete shell-complete')
        self.assertEqual('', err)
        self.assertEqual("""\
"(--help -h)"{--help,-h}
"(--quiet -q)"{--quiet,-q}
"(--verbose -v)"{--verbose,-v}
--usage
context?
""".splitlines(), sorted(out.splitlines()))
