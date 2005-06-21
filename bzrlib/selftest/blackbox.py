# Copyright (C) 2005 by Canonical Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


"""Black-box tests for bzr.

These check that it behaves properly when it's invoked through the regular
command-line interface.
"""

# this code was previously in testbzr

from unittest import TestCase
from bzrlib.selftest import TestBase

class TestVersion(TestBase):
    def runTest(self):
        # output is intentionally passed through to stdout so that we
        # can see the version being tested
        self.runcmd(['bzr', 'version'])


# class InTempBranch(TestBase):
#     """Base class for tests run in a temporary branch."""
#     def setUp():
#     def tearDown()


# class InitBranch(TestBase):
#     def runTest(self):
        
