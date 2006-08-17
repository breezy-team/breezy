# Copyright (C) 2006 by Canonical Ltd
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

"""Blackbox tests for the 'bzr testament' command"""


from bzrlib.tests.test_testament import (
    REV_1_SHORT,
    REV_1_SHORT_STRICT,
    REV_2_TESTAMENT,
    TestamentSetup,
    )


class TestTestament(TestamentSetup):
    """Run blackbox tests on 'bzr testament'"""

    def test_testament_command(self):
        """Testament containing a file and a directory."""
        out, err = self.run_bzr('testament', '--long')
        self.assertEqualDiff(err, '')
        self.assertEqualDiff(out, REV_2_TESTAMENT)

    def test_testament_command_2(self):
        """Command getting short testament of previous version."""
        out, err = self.run_bzr('testament', '-r1')
        self.assertEqualDiff(err, '')
        self.assertEqualDiff(out, REV_1_SHORT)

    def test_testament_command_3(self):
        """Command getting short testament of previous version."""
        out, err = self.run_bzr('testament', '-r1', '--strict')
        self.assertEqualDiff(err, '')
        self.assertEqualDiff(out, REV_1_SHORT_STRICT)

