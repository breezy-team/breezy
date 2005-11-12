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


"""Tests of bound branches (binding, unbinding, commit, etc) command.

"""

import os
from cStringIO import StringIO

from bzrlib.selftest import TestCaseInTempDir
from bzrlib.branch import Branch

class TestBoundBranches(TestCaseInTempDir):
    
    def create_branches(self):
        self.build_tree(['base/', 'base/a', 'base/b'])

        os.chdir('base')
        self.run_bzr('init')
        self.run_bzr('add')
        self.run_bzr('commit', '-m', 'init')

        os.chdir('..')

        bzr('get', '--bound', 'base', 'child')

        self.failUnlessExists('child')

        os.chdir('child')
        self.check_revno('1')
        self.failUnlessExists('.bzr/bound')
        os.chdir('..')

    def check_revno(self, val):
        self.assertEquals(self.capture('bzr revno').strip(), val)

    def test_bound_commit(self):
        bzr = self.run_bzr
        self.create_branches()

        os.chdir('child')
        open('a', 'wb').write('new contents\n')
        bzr('commit', '-m', 'child')

        self.check_revno('2')

        # Make sure it committed on the parent
        os.chdir('../base')
        self.check_revno('2')

    def test_bound_fail(self)
        """Make sure commit fails if out of date."""
        bzr = self.run_bzr
        self.create_branches()

        os.chdir('base')
        open('a', 'wb').write('new base contents\n')
        bzr('commit', '-m', 'base')

        os.chdir('../child')
        open('b', 'wb').write('new b child contents\n')
        bzr('commit', '-m', 'child', retcode=1)

        bzr('pull')
        self.check_revno('2')

        bzr('commit', '-m', 'child')
        self.check_revno('3')
        os.chdir('../base')
        self.check_revno('3')

    def test_double_binding(self):
        bzr = self.run_bzr
        self.create_branches()

        bzr('branch', 'child', 'child2')
        os.chdir('child2')

        bzr('bind', '../child', retcode=1)

        # The binding should fail, because child2 is bound
        self.failIf(os.path.lexists('.bzr/bound'))

    def test_unbinding(self):
        bzr = self.run_bzr
        self.create_branches()

        os.chdir('base')
        open('a', 'wb').write('new base contents\n')
        bzr('commit', '-m', 'base')
        self.check_revno('2')

        os.chdir('../child')
        open('b', 'wb').write('new b child contents\n')
        self.check_revno('1')
        bzr('commit', '-m', 'child', retcode=1)
        self.check_revno('1')
        bzr('unbind')
        bzr('commit', '-m', 'child')
        self.check_revno('2')

        bzr('bind', retcode=1)
    

