# Copyright (C) 2005 Canonical Ltd
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


"""Tests of bound branches (binding, unbinding, commit, etc) command."""

import os
from cStringIO import StringIO

from bzrlib import (
    bzrdir,
    errors
    )
from bzrlib.branch import Branch
from bzrlib.bzrdir import (BzrDir, BzrDirFormat, BzrDirMetaFormat1)
from bzrlib.osutils import getcwd
from bzrlib.tests import TestCaseWithTransport
import bzrlib.urlutils as urlutils
from bzrlib.workingtree import WorkingTree


class TestLegacyFormats(TestCaseWithTransport):
    
    def setUp(self):
        super(TestLegacyFormats, self).setUp()
        self.build_tree(['master/', 'child/'])
        self.make_branch_and_tree('master')
        self.make_branch_and_tree('child',
                        format=bzrdir.format_registry.make_bzrdir('weave'))
        os.chdir('child')
    
    def test_bind_format_6_bzrdir(self):
        # bind on a format 6 bzrdir should error
        out,err = self.run_bzr('bind ../master', retcode=3)
        self.assertEqual('', out)
        # TODO: jam 20060427 Probably something like this really should
        #       print out the actual path, rather than the URL
        cwd = urlutils.local_path_to_url(getcwd())
        self.assertEqual('bzr: ERROR: To use this feature you must '
                         'upgrade your branch at %s/.\n' % cwd, err)
    
    def test_unbind_format_6_bzrdir(self):
        # bind on a format 6 bzrdir should error
        out,err = self.run_bzr('unbind', retcode=3)
        self.assertEqual('', out)
        cwd = urlutils.local_path_to_url(getcwd())
        self.assertEqual('bzr: ERROR: To use this feature you must '
                         'upgrade your branch at %s/.\n' % cwd, err)


class TestBoundBranches(TestCaseWithTransport):

    def create_branches(self):
        self.build_tree(['base/', 'base/a', 'base/b'])

        branch = self.init_meta_branch('base')
        base_tree = branch.bzrdir.open_workingtree()
        base_tree.lock_write()
        base_tree.add(['a', 'b'])
        base_tree.commit('init')
        base_tree.unlock()

        child_tree = branch.create_checkout('child')

        self.check_revno(1, 'child')
        d = BzrDir.open('child')
        self.assertNotEqual(None, d.open_branch().get_master_branch())

        return base_tree, child_tree

    def check_revno(self, val, loc='.'):
        self.assertEqual(
            val, len(BzrDir.open(loc).open_branch().revision_history()))

    def test_simple_binding(self):
        self.build_tree(['base/', 'base/a', 'base/b'])

        branch = self.init_meta_branch('base')
        tree = branch.bzrdir.open_workingtree()
        tree.add('a', 'b')
        tree.commit(message='init')

        tree.bzrdir.sprout('child')

        os.chdir('child')
        self.run_bzr('bind ../base')

        d = BzrDir.open('')
        self.assertNotEqual(None, d.open_branch().get_master_branch())

        self.run_bzr('unbind')
        self.assertEqual(None, d.open_branch().get_master_branch())

        self.run_bzr('unbind', retcode=3)

    def test_bind_branch6(self):
        branch1 = self.make_branch('branch1', format='dirstate-tags')
        os.chdir('branch1')
        error = self.run_bzr('bind', retcode=3)[1]
        self.assertContainsRe(error, 'no previous location known')

    def setup_rebind(self, format):
        branch1 = self.make_branch('branch1')
        branch2 = self.make_branch('branch2', format=format)
        branch2.bind(branch1)
        branch2.unbind()

    def test_rebind_branch6(self):
        self.setup_rebind('dirstate-tags')
        os.chdir('branch2')
        self.run_bzr('bind')
        b = Branch.open('.')
        self.assertContainsRe(b.get_bound_location(), '\/branch1\/$')

    def test_rebind_branch5(self):
        self.setup_rebind('knit')
        os.chdir('branch2')
        error = self.run_bzr('bind', retcode=3)[1]
        self.assertContainsRe(error, 'old locations')

    def init_meta_branch(self, path):
        format = bzrdir.format_registry.make_bzrdir('default')
        return BzrDir.create_branch_convenience(path, format=format)

    def test_bound_commit(self):
        child_tree = self.create_branches()[1]

        self.build_tree_contents([('child/a', 'new contents')])
        child_tree.commit(message='child')

        self.check_revno(2, 'child')

        # Make sure it committed on the parent
        self.check_revno(2, 'base')

    def test_bound_fail(self):
        # Make sure commit fails if out of date.
        base_tree, child_tree = self.create_branches()

        self.build_tree_contents([
            ('base/a',  'new base contents\n'   ),
            ('child/b', 'new b child contents\n')])
        base_tree.commit(message='base')
        self.check_revno(2, 'base')

        self.check_revno(1, 'child')
        self.assertRaises(errors.BoundBranchOutOfDate, child_tree.commit,
                                                            message='child')
        self.check_revno(1, 'child')

        child_tree.update()
        self.check_revno(2, 'child')

        child_tree.commit(message='child')
        self.check_revno(3, 'child')
        self.check_revno(3, 'base')

    def test_double_binding(self):
        child_tree = self.create_branches()[1]

        child2_tree = child_tree.bzrdir.sprout('child2').open_workingtree()

        os.chdir('child2')
        # Double binding succeeds, but committing to child2 should fail
        self.run_bzr('bind ../child')

        self.assertRaises(errors.CommitToDoubleBoundBranch,
                child2_tree.commit, message='child2', allow_pointless=True)

    def test_unbinding(self):
        base_tree, child_tree = self.create_branches()

        self.build_tree_contents([
            ('base/a',  'new base contents\n'   ),
            ('child/b', 'new b child contents\n')])

        base_tree.commit(message='base')
        self.check_revno(2, 'base')

        self.check_revno(1, 'child')
        os.chdir('child')
        self.run_bzr("commit -m child", retcode=3)
        self.check_revno(1)
        self.run_bzr('unbind')
        child_tree.commit(message='child')
        self.check_revno(2)

        self.run_bzr('bind', retcode=3)

    def test_commit_remote_bound(self):
        # It is not possible to commit to a branch
        # which is bound to a branch which is bound
        base_tree, child_tree = self.create_branches()
        base_tree.bzrdir.sprout('newbase')

        os.chdir('base')
        # There is no way to know that B has already
        # been bound by someone else, otherwise it
        # might be nice if this would fail
        self.run_bzr('bind ../newbase')

        os.chdir('../child')
        self.run_bzr('commit -m failure --unchanged', retcode=3)

    def test_pull_updates_both(self):
        base_tree = self.create_branches()[0]
        newchild_tree = base_tree.bzrdir.sprout('newchild').open_workingtree()
        self.build_tree_contents([('newchild/b', 'newchild b contents\n')])
        newchild_tree.commit(message='newchild')
        self.check_revno(2, 'newchild')

        os.chdir('child')
        # The pull should succeed, and update
        # the bound parent branch
        self.run_bzr('pull ../newchild')
        self.check_revno(2)

        self.check_revno(2, '../base')

    def test_bind_diverged(self):
        base_tree, child_tree = self.create_branches()
        base_branch = base_tree.branch
        child_branch = child_tree.branch

        os.chdir('child')
        self.run_bzr('unbind')

        child_tree.commit(message='child', allow_pointless=True)
        self.check_revno(2)

        os.chdir('..')
        self.check_revno(1, 'base')
        base_tree.commit(message='base', allow_pointless=True)
        self.check_revno(2, 'base')

        os.chdir('child')
        # These branches have diverged
        self.run_bzr('bind ../base', retcode=3)

        # TODO: In the future, this might require actual changes
        # to have occurred, rather than just a new revision entry
        child_tree.merge_from_branch(base_branch)
        child_tree.commit(message='merged')
        self.check_revno(3)

        # After binding, the revision history should be unaltered
        # take a copy before
        base_history = base_branch.revision_history()
        child_history = child_branch.revision_history()

        # After a merge, trying to bind again should succeed
        # keeping the new change as a local commit.
        self.run_bzr('bind ../base')
        self.check_revno(3)
        self.check_revno(2, '../base')

        # and compare the revision history now
        self.assertEqual(base_history, base_branch.revision_history())
        self.assertEqual(child_history, child_branch.revision_history())

    def test_bind_parent_ahead(self):
        base_tree = self.create_branches()[0]

        os.chdir('child')
        self.run_bzr('unbind')

        base_tree.commit(message='base', allow_pointless=True)

        self.check_revno(1)
        self.run_bzr('bind ../base')

        # binding does not pull data:
        self.check_revno(1)
        self.run_bzr('unbind')

        # Check and make sure it also works if parent is ahead multiple
        base_tree.commit(message='base 3', allow_pointless=True)
        base_tree.commit(message='base 4', allow_pointless=True)
        base_tree.commit(message='base 5', allow_pointless=True)
        self.check_revno(5, '../base')

        self.check_revno(1)
        self.run_bzr('bind ../base')
        self.check_revno(1)

    def test_bind_child_ahead(self):
        # test binding when the master branches history is a prefix of the 
        # childs - it should bind ok but the revision histories should not
        # be altered
        child_tree = self.create_branches()[1]

        os.chdir('child')
        self.run_bzr('unbind')
        child_tree.commit(message='child', allow_pointless=True)
        self.check_revno(2)
        self.check_revno(1, '../base')

        self.run_bzr('bind ../base')
        self.check_revno(1, '../base')

        # Check and make sure it also works if child is ahead multiple
        self.run_bzr('unbind')
        child_tree.commit(message='child 3', allow_pointless=True)
        child_tree.commit(message='child 4', allow_pointless=True)
        child_tree.commit(message='child 5', allow_pointless=True)
        self.check_revno(5)

        self.check_revno(1, '../base')
        self.run_bzr('bind ../base')
        self.check_revno(1, '../base')

    def test_commit_after_merge(self):
        base_tree, child_tree = self.create_branches()

        # We want merge to be able to be a local only
        # operation, because it can be without violating
        # the binding invariants.
        # But we can't fail afterwards
        other_tree = child_tree.bzrdir.sprout('other').open_workingtree()
        other_branch = other_tree.branch

        self.build_tree_contents([('other/c', 'file c\n')])
        other_tree.add('c')
        other_tree.commit(message='adding c')
        new_rev_id = other_branch.revision_history()[-1]

        child_tree.merge_from_branch(other_branch)

        self.failUnlessExists('child/c')
        self.assertEqual([new_rev_id], child_tree.get_parent_ids()[1:])

        # Make sure the local branch has the installed revision
        self.assertTrue(child_tree.branch.repository.has_revision(new_rev_id))

        # And make sure that the base tree does not
        self.assertFalse(base_tree.branch.repository.has_revision(new_rev_id))

        # Commit should succeed, and cause merged revisions to
        # be pulled into base
        os.chdir('child')
        self.run_bzr(['commit', '-m', 'merge other'])

        self.check_revno(2)

        self.check_revno(2, '../base')

        self.assertTrue(base_tree.branch.repository.has_revision(new_rev_id))

    def test_pull_overwrite(self):
        # XXX: This test should be moved to branch-implemenations/test_pull
        child_tree = self.create_branches()[1]

        other_tree = child_tree.bzrdir.sprout('other').open_workingtree()

        self.build_tree_contents([('other/a', 'new contents\n')])
        other_tree.commit(message='changed a')
        self.check_revno(2, 'other')
        self.build_tree_contents([
            ('other/a', 'new contents\nand then some\n')])
        other_tree.commit(message='another a')
        self.check_revno(3, 'other')
        self.build_tree_contents([
            ('other/a', 'new contents\nand then some\nand some more\n')])
        other_tree.commit('yet another a')
        self.check_revno(4, 'other')

        self.build_tree_contents([('child/a', 'also changed a\n')])
        child_tree.commit(message='child modified a')

        self.check_revno(2, 'child')
        self.check_revno(2, 'base')

        os.chdir('child')
        self.run_bzr('pull --overwrite ../other')

        # both the local and master should have been updated.
        self.check_revno(4)
        self.check_revno(4, '../base')
