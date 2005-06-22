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


"""Tests of simple versioning operations"""


from bzrlib.selftest import InTempDir

class Mkdir(InTempDir):
    def runTest(self): 
        """Basic 'bzr mkdir' operation"""
        from bzrlib.commands import run_bzr
        import os

        run_bzr(['bzr', 'init'])
        run_bzr(['bzr', 'mkdir', 'foo'])
        self.assert_(os.path.isdir('foo'))

