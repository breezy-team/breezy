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

This always reinvokes bzr through a new Python interpreter, which is a
bit inefficient but arguably tests in a way more representative of how
it's normally invoked.
"""

# this code was previously in testbzr

from unittest import TestCase
from bzrlib.selftest import TestBase, InTempDir

class TestVersion(TestBase):
    def runTest(self):
        # output is intentionally passed through to stdout so that we
        # can see the version being tested
        print
        self.runcmd(['bzr', 'version'])
        print



class HelpCommands(TestBase):
    def runTest(self):
        self.runcmd('bzr --help')
        self.runcmd('bzr help')
        self.runcmd('bzr help commands')
        self.runcmd('bzr help help')
        self.runcmd('bzr commit -h')


class InitBranch(InTempDir):
    def runTest(self):
        import os
        print "%s running in %s" % (self, os.getcwdu())
        self.runcmd(['bzr', 'init'])



class UserIdentity(InTempDir):
    def runTest(self):
        # this should always identify something, if only "john@localhost"
        self.runcmd("bzr whoami")
        self.runcmd("bzr whoami --email")
        self.assertEquals(self.backtick("bzr whoami --email").count('@'),
                          1)    
        


# lists all tests from this module in the best order to run them.  we
# do it this way rather than just discovering them all because it
# allows us to test more basic functions first where failures will be
# easiest to understand.

def suite():
    from unittest import TestSuite
    s = TestSuite()
    s.addTests([TestVersion(),
                InitBranch(),
                HelpCommands(),
                UserIdentity()])
    return s
