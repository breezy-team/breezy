# Copyright (C) 2005 Robey Pointer <robey@lag.net>, Canonical Ltd

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

"""Tests for branches bound to an sftp branch."""


import os


from bzrlib.branch import Branch
from bzrlib.bzrdir import (BzrDir,
                           BzrDirFormat,
                           BzrDirFormat6,
                           BzrDirMetaFormat1,
                           )
import bzrlib.errors as errors
from bzrlib.tests.test_sftp_transport import TestCaseWithSFTPServer, paramiko_loaded


class BoundSFTPBranch(TestCaseWithSFTPServer):

    def create_branches(self):
        self.build_tree(['base/', 'base/a', 'base/b'])
        old_format = BzrDirFormat.get_default_format()
        BzrDirFormat.set_default_format(BzrDirMetaFormat1())
        try:
            wt_base = BzrDir.create_standalone_workingtree('base')
        finally:
            BzrDirFormat.set_default_format(old_format)
    
        b_base = wt_base.branch

        wt_base.add('a')
        wt_base.add('b')
        wt_base.commit('first', rev_id='r@b-1')

        wt_child = b_base.bzrdir.sprout('child').open_workingtree()
        self.sftp_base = Branch.open(self.get_url('base'))
        wt_child.branch.bind(self.sftp_base)

        self.assertEqual(['r@b-1'], b_base.revision_history())
        self.assertEqual(['r@b-1'], wt_child.branch.revision_history())

        return b_base, wt_child

    def test_simple_binding(self):
        self.build_tree(['base/', 'base/a', 'base/b', 'child/'])
        wt_base = BzrDir.create_standalone_workingtree('base')

        wt_base.add('a')
        wt_base.add('b')
        wt_base.commit('first', rev_id='r@b-1')

        b_base = wt_base.branch
        old_format = BzrDirFormat.get_default_format()
        BzrDirFormat.set_default_format(BzrDirMetaFormat1())
        try:
            b_child = BzrDir.create_branch_convenience('child')
        finally:
            BzrDirFormat.set_default_format(old_format)
        self.assertEqual(None, b_child.get_bound_location())
        self.assertEqual(None, b_child.get_master_branch())

        sftp_b_base = Branch.open(self.get_url('base'))
        b_child.bind(sftp_b_base)
        self.assertEqual(sftp_b_base.base, b_child.get_bound_location())
        # this line is more of a working tree test line, but - what the hey.
        b_child.bzrdir.open_workingtree().update()
        self.failUnlessExists('child/a')
        self.failUnlessExists('child/b')

        b_child.unbind()
        self.assertEqual(None, b_child.get_bound_location())

    def test_bound_commit(self):
        b_base, wt_child = self.create_branches()

        open('child/a', 'wb').write('new contents\n')
        wt_child.commit('modified a', rev_id='r@c-2')

        self.assertEqual(['r@b-1', 'r@c-2'], wt_child.branch.revision_history())
        self.assertEqual(['r@b-1', 'r@c-2'], b_base.revision_history())

    def test_bound_fail(self):
        # Make sure commit fails if out of date.
        b_base, wt_child = self.create_branches()

        open('base/a', 'wb').write('new base contents\n')
        b_base.bzrdir.open_workingtree().commit('base', rev_id='r@b-2')

        open('child/b', 'wb').write('new b child contents\n')
        self.assertRaises(errors.BoundBranchOutOfDate,
                wt_child.commit, 'child', rev_id='r@c-2')

        sftp_b_base = Branch.open(self.get_url('base'))

        # This is all that cmd_update does
        wt_child.pull(sftp_b_base, overwrite=False)

        wt_child.commit('child', rev_id='r@c-3')

        self.assertEqual(['r@b-1', 'r@b-2', 'r@c-3'],
                wt_child.branch.revision_history())
        self.assertEqual(['r@b-1', 'r@b-2', 'r@c-3'],
                b_base.revision_history())
        self.assertEqual(['r@b-1', 'r@b-2', 'r@c-3'],
                sftp_b_base.revision_history())

    def test_double_binding(self):
        b_base, wt_child = self.create_branches()

        wt_child2 = wt_child.bzrdir.sprout('child2').open_workingtree()

        wt_child2.branch.bind(wt_child.branch)

        open('child2/a', 'wb').write('new contents\n')
        self.assertRaises(errors.CommitToDoubleBoundBranch,
                wt_child2.commit, 'child2', rev_id='r@d-2')

    def test_unbinding(self):
        from bzrlib.transport import get_transport
        b_base, wt_child = self.create_branches()

        # TestCaseWithSFTPServer only allows you to connect one time
        # to the SFTP server. So we have to create a connection and
        # keep it around, so that it can be reused
        __unused_t = get_transport(self.get_url('.'))

        wt_base = b_base.bzrdir.open_workingtree()
        open('base/a', 'wb').write('new base contents\n')
        wt_base.commit('base', rev_id='r@b-2')

        open('child/b', 'wb').write('new b child contents\n')
        self.assertRaises(errors.BoundBranchOutOfDate,
                wt_child.commit, 'child', rev_id='r@c-2')
        self.assertEqual(['r@b-1'], wt_child.branch.revision_history())
        wt_child.branch.unbind()
        wt_child.commit('child', rev_id='r@c-2')
        self.assertEqual(['r@b-1', 'r@c-2'], wt_child.branch.revision_history())
        self.assertEqual(['r@b-1', 'r@b-2'], b_base.revision_history())

        sftp_b_base = Branch.open(self.get_url('base'))
        self.assertRaises(errors.DivergedBranches,
                wt_child.branch.bind, sftp_b_base)

    def test_commit_remote_bound(self):
        # Make sure it is detected if the current base
        # suddenly is bound when child goes to commit
        b_base, wt_child = self.create_branches()

        b_base.bzrdir.sprout('newbase')

        sftp_b_base = Branch.open(self.get_url('base'))
        sftp_b_newbase = Branch.open(self.get_url('newbase'))

        sftp_b_base.bind(sftp_b_newbase)

        open('child/a', 'wb').write('new contents\n')
        self.assertRaises(errors.CommitToDoubleBoundBranch,
                wt_child.commit, 'failure', rev_id='r@c-2')

        self.assertEqual(['r@b-1'], b_base.revision_history())
        self.assertEqual(['r@b-1'], wt_child.branch.revision_history())
        self.assertEqual(['r@b-1'], sftp_b_newbase.revision_history())

    def test_pull_updates_both(self):
        b_base, wt_child = self.create_branches()

        wt_newchild = b_base.bzrdir.sprout('newchild').open_workingtree()
        open('newchild/b', 'wb').write('newchild b contents\n')
        wt_newchild.commit('newchild', rev_id='r@d-2')
        self.assertEqual(['r@b-1', 'r@d-2'], wt_newchild.branch.revision_history())

        wt_child.pull(wt_newchild.branch)
        self.assertEqual(['r@b-1', 'r@d-2'], wt_child.branch.revision_history())
        self.assertEqual(['r@b-1', 'r@d-2'], b_base.revision_history())

    def test_bind_diverged(self):
        from bzrlib.builtins import merge

        b_base, wt_child = self.create_branches()

        wt_child.branch.unbind()
        open('child/a', 'ab').write('child contents\n')
        wt_child.commit('child', rev_id='r@c-2')

        self.assertEqual(['r@b-1', 'r@c-2'], wt_child.branch.revision_history())
        self.assertEqual(['r@b-1'], b_base.revision_history())

        open('base/b', 'ab').write('base contents\n')
        b_base.bzrdir.open_workingtree().commit('base', rev_id='r@b-2')
        self.assertEqual(['r@b-1', 'r@b-2'], b_base.revision_history())

        sftp_b_base = Branch.open(self.get_url('base'))

        self.assertRaises(errors.DivergedBranches,
                wt_child.branch.bind, sftp_b_base)

        # TODO: jam 20051230 merge_inner doesn't set pending merges
        #       Is this on purpose?
        #       merge_inner also doesn't fetch any missing revisions
        #merge_inner(wt_child.branch, sftp_b_base.revision_tree('r@b-2'), 
        #        wt_child.branch.revision_tree('r@b-1'))
        # TODO: jam 20051230 merge(..., (None, None), ...) seems to
        #       cause an infinite loop of some sort. It definitely doesn't
        #       work, you have to use list notation
        merge((sftp_b_base.base, 2), [None, None], this_dir=wt_child.branch.base)

        self.assertEqual(['r@b-2'], wt_child.pending_merges())
        wt_child.commit('merged', rev_id='r@c-3')

        # After a merge, trying to bind again should succeed
        # by pushing the new change to base
        wt_child.branch.bind(sftp_b_base)

        self.assertEqual(['r@b-1', 'r@b-2', 'r@c-3'],
                b_base.revision_history())
        self.assertEqual(['r@b-1', 'r@b-2', 'r@c-3'],
                wt_child.branch.revision_history())

    def test_bind_parent_ahead(self):
        b_base, wt_child = self.create_branches()

        wt_child.branch.unbind()

        open('a', 'ab').write('base changes\n')
        wt_base = b_base.bzrdir.open_workingtree()
        wt_base.commit('base', rev_id='r@b-2')
        self.assertEqual(['r@b-1', 'r@b-2'], b_base.revision_history())
        self.assertEqual(['r@b-1'], wt_child.branch.revision_history())

        sftp_b_base = Branch.open(self.get_url('base'))
        wt_child.branch.bind(sftp_b_base)

        self.assertEqual(['r@b-1', 'r@b-2'], wt_child.branch.revision_history())

        wt_child.branch.unbind()

        # Check and make sure it also works if parent is ahead multiple
        wt_base.commit('base 3', rev_id='r@b-3', allow_pointless=True)
        wt_base.commit('base 4', rev_id='r@b-4', allow_pointless=True)
        wt_base.commit('base 5', rev_id='r@b-5', allow_pointless=True)

        self.assertEqual(['r@b-1', 'r@b-2', 'r@b-3', 'r@b-4', 'r@b-5'],
                b_base.revision_history())

        self.assertEqual(['r@b-1', 'r@b-2'], wt_child.branch.revision_history())

        wt_child.branch.bind(sftp_b_base)
        self.assertEqual(['r@b-1', 'r@b-2', 'r@b-3', 'r@b-4', 'r@b-5'],
                wt_child.branch.revision_history())

    def test_bind_child_ahead(self):
        b_base, wt_child = self.create_branches()

        wt_child.branch.unbind()

        wt_child.commit('child', rev_id='r@c-2', allow_pointless=True)
        self.assertEqual(['r@b-1', 'r@c-2'], wt_child.branch.revision_history())
        self.assertEqual(['r@b-1'], b_base.revision_history())

        sftp_b_base = Branch.open(self.get_url('base'))
        wt_child.branch.bind(sftp_b_base)

        self.assertEqual(['r@b-1', 'r@c-2'], b_base.revision_history())

        # Check and make sure it also works if child is ahead multiple
        wt_child.branch.unbind()
        wt_child.commit('child 3', rev_id='r@c-3', allow_pointless=True)
        wt_child.commit('child 4', rev_id='r@c-4', allow_pointless=True)
        wt_child.commit('child 5', rev_id='r@c-5', allow_pointless=True)

        self.assertEqual(['r@b-1', 'r@c-2', 'r@c-3', 'r@c-4', 'r@c-5'],
                wt_child.branch.revision_history())
        self.assertEqual(['r@b-1', 'r@c-2'], b_base.revision_history())

        wt_child.branch.bind(sftp_b_base)
        self.assertEqual(['r@b-1', 'r@c-2', 'r@c-3', 'r@c-4', 'r@c-5'],
                b_base.revision_history())

    def test_commit_after_merge(self):
        from bzrlib.builtins import merge

        b_base, wt_child = self.create_branches()

        # We want merge to be able to be a local only
        # operation, because it does not alter the branch data.

        # But we can't fail afterwards

        wt_other = wt_child.bzrdir.sprout('other').open_workingtree()

        open('other/c', 'wb').write('file c\n')
        wt_other.add('c')
        wt_other.commit('adding c', rev_id='r@d-2')

        self.failIf(wt_child.branch.repository.has_revision('r@d-2'))
        self.failIf(b_base.repository.has_revision('r@d-2'))

        # TODO: jam 20051230 merge_inner doesn't set pending merges
        #       Is this on purpose?
        #       merge_inner also doesn't fetch any missing revisions
        #merge_inner(wt_child.branch, b_other.revision_tree('r@d-2'),
        #        wt_child.branch.revision_tree('r@b-1'))
        merge((wt_other.branch.base, 2), [None, None], this_dir=wt_child.branch.base)

        self.failUnlessExists('child/c')
        self.assertEqual(['r@d-2'], wt_child.pending_merges())
        self.failUnless(wt_child.branch.repository.has_revision('r@d-2'))
        self.failIf(b_base.repository.has_revision('r@d-2'))

        # Commit should succeed, and cause merged revisions to
        # be pulled into base
        wt_child.commit('merge other', rev_id='r@c-2')
        self.assertEqual(['r@b-1', 'r@c-2'], wt_child.branch.revision_history())
        self.assertEqual(['r@b-1', 'r@c-2'], b_base.revision_history())
        self.failUnless(b_base.repository.has_revision('r@d-2'))

    def test_commit_fails(self):
        b_base, wt_child = self.create_branches()

        open('a', 'ab').write('child adds some text\n')

        del b_base
        os.rename('base', 'hidden_base')

        self.assertRaises(errors.BoundBranchConnectionFailure,
                wt_child.commit, 'added text', rev_id='r@c-2')

    def test_pull_fails(self):
        b_base, wt_child = self.create_branches()

        wt_other = wt_child.bzrdir.sprout('other').open_workingtree()
        open('other/a', 'wb').write('new contents\n')
        wt_other.commit('changed a', rev_id='r@d-2')

        self.assertEqual(['r@b-1'], b_base.revision_history())
        self.assertEqual(['r@b-1'], wt_child.branch.revision_history())
        self.assertEqual(['r@b-1', 'r@d-2'], wt_other.branch.revision_history())

        del b_base
        os.rename('base', 'hidden_base')

        self.assertRaises(errors.BoundBranchConnectionFailure,
                wt_child.pull, wt_other.branch)

    # TODO: jam 20051231 We need invasive failure tests, so that we can show
    #       performance even when something fails.


if not paramiko_loaded:
    del BoundSFTPBranch

