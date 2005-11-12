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
        self.check_revno(1)
        self.failUnlessExists('.bzr/bound')
        os.chdir('..')

    def check_revno(self, val, loc=None):
        if loc is not None:
            cwd = os.getcwd()
            os.chdir(loc)
        self.assertEquals(self.capture('bzr revno').strip(), str(val))
        if loc is not None:
            os.chdir(cwd)

    def test_bound_commit(self):
        bzr = self.run_bzr
        self.create_branches()

        os.chdir('child')
        open('a', 'wb').write('new contents\n')
        bzr('commit', '-m', 'child')

        self.check_revno(2)

        # Make sure it committed on the parent
        os.chdir('../base')
        self.check_revno(2)

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
        self.check_revno(2)

        bzr('commit', '-m', 'child')
        self.check_revno(3)
        os.chdir('../base')
        self.check_revno(3)

    def test_double_binding(self):
        # The behavior of this test is under debate
        bzr = self.run_bzr
        self.create_branches()

        bzr('branch', 'child', 'child2')
        os.chdir('child2')

        bzr('bind', '../child', retcode=1)

        # The binding should fail, because child is bound
        self.failIf(os.path.lexists('.bzr/bound'))

    def test_unbinding(self):
        bzr = self.run_bzr
        self.create_branches()

        os.chdir('base')
        open('a', 'wb').write('new base contents\n')
        bzr('commit', '-m', 'base')
        self.check_revno(2)

        os.chdir('../child')
        open('b', 'wb').write('new b child contents\n')
        self.check_revno(1)
        bzr('commit', '-m', 'child', retcode=1)
        self.check_revno(1)
        bzr('unbind')
        bzr('commit', '-m', 'child')
        self.check_revno(2)

        bzr('bind', retcode=1)

    def test_commit_remote_bound(self):
        # It is not possible to commit to a branch
        # which is bound to a branch which is bound
        bzr = self.run_bzr
        bzr('branch', 'base', 'newbase')
        os.chdir('base')
        
        # There is no way to know that B has already
        # been bound by someone else, otherwise it
        # might be nice if this would fail
        bzr('bind', '../newbase')

        os.chdir('../child')
        bzr('commit', '-m', 'failure', '--unchanged', retcode=1)
        

    def test_pull_updates_both(self):
        bzr = self.run_bzr
        self.create_branches()
        bzr('branch', 'base', 'newchild')
        os.chdir('newchild')
        open('b', 'wb').write('newchild b contents\n')
        bzr('commit', '-m', 'newchild')
        self.check_revno(2)

        os.chdir('../child')
        # The pull should succeed, and update
        # the bound parent branch
        bzr('pull', '../newchild')
        self.check_revno(2)

        os.chdir('../base')
        self.check_revno(2)

    def test_bind_diverged(self):
        bzr = self.run_bzr
        self.create_branches()

        os.chdir('child')
        bzr('unbind')

        bzr('commit', '-m', 'child', '--unchanged')
        self.check_revno(2)

        os.chdir('../base')
        self.check_revno(1)
        bzr('commit', '-m', 'base', '--unchanged')
        self.check_revno(2)

        os.chdir('../child')
        # These branches have diverged
        bzr('bind', '../base', retcode=1)

        # TODO: In the future, this might require actual changes
        # to have occurred, rather than just a new revision entry
        bzr('merge', '../base')
        bzr('commit', '-m', 'merged')
        self.check_revno(3)

        # This should also be possible by doing a 'bzr push' to the
        # base, rather than doing 'bzr pull' from it
        os.chdir('../base')
        bzr('pull', '../child')
        self.check_revno(3)

        os.chdir('../child')
        bzr('bind', '../base')

        # After binding, the revision history should be identical
        child_rh = self.capture('bzr revision-history')
        os.chdir('../base')
        base_rh = self.capture('bzr revision-history')
        self.assertEquals(child_rh, base_rh)

    def test_bind_parent_ahead(self):
        bzr = self.run_bzr
        self.create_branches()

        os.chdir('child')
        bzr('unbind')

        os.chdir('../base')
        bzr('commit', '-m', 'base', '--unchanged')

        os.chdir('../child')
        self.check_revno(1)
        bzr('bind', '../base')

        self.check_revno(2)

    def test_bind_child_ahead(self):
        bzr = self.run_bzr
        self.create_branches()

        os.chdir('child')
        bzr('unbind')
        bzr('commit', '-m', 'child', '--unchanged')
        self.check_revno(2)
        self.check_revno(1, '../base')

        bzr('bind', '../base')
        self.check_revno(2, '../base')

