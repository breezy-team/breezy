# Copyright (C) 2004, 2005 by Canonical Ltd

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


from bzrlib.selftest import InTempDir, TestBase
from bzrlib.merge3 import Merge3

class NoConflicts(TestBase):
    """No conflicts because only one side changed"""
    def runTest(self):
        m3 = Merge3(['aaa', 'bbb'],
                    ['aaa', '111', 'bbb'],
                    ['aaa', 'bbb'])

        self.assertEquals(m3.find_unconflicted(),
                          [(0, 1), (1, 2)])

    
class NoChanges(TestBase):
    """No conflicts because nothing changed"""
    def runTest(self):
        m3 = Merge3(['aaa', 'bbb'],
                    ['aaa', 'bbb'],
                    ['aaa', 'bbb'])

        self.assertEquals(m3.find_unconflicted(),
                          [(0, 2)])

    

class InsertClash(TestBase):
    """Both try to insert lines in the same place."""
    def runTest(self):
        m3 = Merge3(['aaa', 'bbb'],
                    ['aaa', '111', 'bbb'],
                    ['aaa', '222', 'bbb'])

        self.assertEquals(m3.find_unconflicted(),
                          [(0, 1), (1, 2)])

        



class ReplaceClash(TestBase):
    """Both try to insert lines in the same place."""
    def runTest(self):
        m3 = Merge3(['aaa', '000', 'bbb'],
                    ['aaa', '111', 'bbb'],
                    ['aaa', '222', 'bbb'])

        self.assertEquals(m3.find_unconflicted(),
                          [(0, 1), (2, 3)])

        
