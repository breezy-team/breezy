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

from bzrlib.tests import TestCaseWithTransport
from bzrlib.branch import Branch
from bzrlib.bzrdir import (BzrDir,
                           BzrDirFormat,
                           BzrDirFormat6,
                           BzrDirMetaFormat1,
                           )
from bzrlib.workingtree import WorkingTree


class TestLegacyFormats(TestCaseWithTransport):
    
    def setUp(self):
        super(TestLegacyFormats, self).setUp()
        self.build_tree(['master/', 'child/'])
        self.run_bzr('init', 'master')
        old_format = BzrDirFormat.get_default_format()
        BzrDirFormat.set_default_format(BzrDirFormat6())
        try:
            self.run_bzr('init', 'child')
        finally:
            BzrDirFormat.set_default_format(old_format)
        os.chdir('child')
    
    def test_bind_format_6_bzrdir(self):
        # bind on a format 6 bzrdir should error
        out,err = self.run_bzr('bind', '../master', retcode=3)
        self.assertEqual('', out)
        self.assertEqual('bzr: ERROR: To use this feature you must '
                         'upgrade your branch at %s/.\n' % os.getcwdu(), err)
    
    def test_unbind_format_6_bzrdir(self):
        # bind on a format 6 bzrdir should error
        out,err = self.run_bzr('unbind', retcode=3)
        self.assertEqual('', out)
        self.assertEqual('bzr: ERROR: To use this feature you must '
                         'upgrade your branch at %s/.\n' % os.getcwdu(), err)


class TestBoundBranches(TestCaseWithTransport):

    def create_branches(self):
        bzr = self.run_bzr
        self.build_tree(['base/', 'base/a', 'base/b'])

        self.init_meta_branch('base')
        os.chdir('base')
        bzr('add')
        bzr('commit', '-m', 'init')

        os.chdir('..')

        bzr('checkout', 'base', 'child')

        self.failUnlessExists('child')

        self.check_revno(1, 'child')
        d = BzrDir.open('child')
        self.assertNotEqual(None, d.open_branch().get_master_branch())

    def check_revno(self, val, loc=None):
        if loc is not None:
            cwd = os.getcwd()
            os.chdir(loc)
        self.assertEquals(str(val), self.run_bzr('revno')[0].strip())
        if loc is not None:
            os.chdir(cwd)

    def test_simple_binding(self):
        self.build_tree(['base/', 'base/a', 'base/b'])

        self.init_meta_branch('base')
        self.run_bzr('add', 'base')
        self.run_bzr('commit', '-m', 'init', 'base')

        self.run_bzr('branch', 'base', 'child')

        os.chdir('child')
        self.run_bzr('bind', '../base')

        d = BzrDir.open('')
        self.assertNotEqual(None, d.open_branch().get_master_branch())

        self.run_bzr('unbind')
        self.assertEqual(None, d.open_branch().get_master_branch())

        self.run_bzr('unbind', retcode=3)

    def init_meta_branch(self, path):
        old_format = BzrDirFormat.get_default_format()
        BzrDirFormat.set_default_format(BzrDirMetaFormat1())
        try:
            self.run_bzr('init', path)
        finally:
            BzrDirFormat.set_default_format(old_format)

    def test_bound_commit(self):
        bzr = self.run_bzr
        self.create_branches()

        os.chdir('child')
        open('a', 'wb').write('new contents\n')
        bzr('commit', '-m', 'child')

        self.check_revno(2)

        # Make sure it committed on the parent
        self.check_revno(2, '../base')

    def test_bound_fail(self):
        # Make sure commit fails if out of date.
        bzr = self.run_bzr
        self.create_branches()

        os.chdir('base')
        open('a', 'wb').write('new base contents\n')
        bzr('commit', '-m', 'base')
        self.check_revno(2)

        os.chdir('../child')
        self.check_revno(1)
        open('b', 'wb').write('new b child contents\n')
        bzr('commit', '-m', 'child', retcode=3)
        self.check_revno(1)

        bzr('update')
        self.check_revno(2)

        bzr('commit', '-m', 'child')
        self.check_revno(3)
        self.check_revno(3, '../base')

    def test_double_binding(self):
        bzr = self.run_bzr
        self.create_branches()

        bzr('branch', 'child', 'child2')
        os.chdir('child2')

        # Double binding succeeds, but committing to child2 should fail
        bzr('bind', '../child')

        bzr('commit', '-m', 'child2', '--unchanged', retcode=3)

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
        bzr('commit', '-m', 'child', retcode=3)
        self.check_revno(1)
        bzr('unbind')
        bzr('commit', '-m', 'child')
        self.check_revno(2)

        bzr('bind', retcode=3)

    def test_commit_remote_bound(self):
        # It is not possible to commit to a branch
        # which is bound to a branch which is bound
        bzr = self.run_bzr
        self.create_branches()
        bzr('branch', 'base', 'newbase')
        os.chdir('base')
        
        # There is no way to know that B has already
        # been bound by someone else, otherwise it
        # might be nice if this would fail
        bzr('bind', '../newbase')

        os.chdir('../child')
        bzr('commit', '-m', 'failure', '--unchanged', retcode=3)

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

        self.check_revno(2, '../base')

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
        bzr('bind', '../base', retcode=3)

        # TODO: In the future, this might require actual changes
        # to have occurred, rather than just a new revision entry
        bzr('merge', '../base')
        bzr('commit', '-m', 'merged')
        self.check_revno(3)

        # After a merge, trying to bind again should succeed
        # by pushing the new change to base
        bzr('bind', '../base')
        self.check_revno(3)
        self.check_revno(3, '../base')

        # After binding, the revision history should be identical
        child_rh = bzr('revision-history')[0]
        os.chdir('../base')
        base_rh = bzr('revision-history')[0]
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
        bzr('unbind')

        # Check and make sure it also works if parent is ahead multiple
        os.chdir('../base')
        bzr('commit', '-m', 'base 3', '--unchanged')
        bzr('commit', '-m', 'base 4', '--unchanged')
        bzr('commit', '-m', 'base 5', '--unchanged')
        self.check_revno(5)

        os.chdir('../child')
        self.check_revno(2)
        bzr('bind', '../base')
        self.check_revno(5)

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

        # Check and make sure it also works if child is ahead multiple
        bzr('unbind')
        bzr('commit', '-m', 'child 3', '--unchanged')
        bzr('commit', '-m', 'child 4', '--unchanged')
        bzr('commit', '-m', 'child 5', '--unchanged')
        self.check_revno(5)

        self.check_revno(2, '../base')
        bzr('bind', '../base')
        self.check_revno(5, '../base')

    def test_commit_after_merge(self):
        bzr = self.run_bzr
        self.create_branches()

        # We want merge to be able to be a local only
        # operation, because it can be without violating
        # the binding invariants.
        # But we can't fail afterwards

        bzr('branch', 'child', 'other')

        os.chdir('other')
        open('c', 'wb').write('file c\n')
        bzr('add', 'c')
        bzr('commit', '-m', 'adding c')
        new_rev_id = bzr('revision-history')[0].strip().split('\n')[-1]

        os.chdir('../child')
        bzr('merge', '../other')

        self.failUnlessExists('c')
        tree = WorkingTree.open('.')
        self.assertEqual([new_rev_id], tree.pending_merges())

        # Make sure the local branch has the installed revision
        bzr('cat-revision', new_rev_id)
        
        # And make sure that the base tree does not
        os.chdir('../base')
        bzr('cat-revision', new_rev_id, retcode=3)

        # Commit should succeed, and cause merged revisions to
        # be pulled into base
        os.chdir('../child')
        bzr('commit', '-m', 'merge other')

        self.check_revno(2)

        os.chdir('../base')
        self.check_revno(2)

        bzr('cat-revision', new_rev_id)

    def test_pull_overwrite_fails(self):
        bzr = self.run_bzr
        self.create_branches()

        bzr('branch', 'child', 'other')
        
        os.chdir('other')
        open('a', 'wb').write('new contents\n')
        bzr('commit', '-m', 'changed a')
        self.check_revno(2)
        open('a', 'ab').write('and then some\n')
        bzr('commit', '-m', 'another a')
        self.check_revno(3)
        open('a', 'ab').write('and some more\n')
        bzr('commit', '-m', 'yet another a')
        self.check_revno(4)

        os.chdir('../child')
        open('a', 'wb').write('also changed a\n')
        bzr('commit', '-m', 'child modified a')

        self.check_revno(2)
        self.check_revno(2, '../base')

        # It might be possible that we want pull --overwrite to
        # actually succeed.
        # If we want it, just change this test to make sure that 
        # both base and child are updated properly
        bzr('pull', '--overwrite', '../other', retcode=3)

        # It should fail without changing the local revision
        self.check_revno(2)
        self.check_revno(2, '../base')

    # TODO: jam 20051230 Test that commit & pull fail when the branch we 
    #       are bound to is not available


