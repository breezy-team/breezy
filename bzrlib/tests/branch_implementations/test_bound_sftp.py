# Copyright (C) 2005 Robey Pointer <robey@lag.net>, Canonical Ltd
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

"""Tests for branches bound to an sftp branch."""


import os

import bzrlib
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
        # check the branch histories are ready for using in tests.
        self.assertEqual(['r@b-1'], b_base.revision_history())
        self.assertEqual(['r@b-1'], wt_child.branch.revision_history())
        return b_base, wt_child

    def tearDown(self):
        self.sftp_base = None
        bzrlib.transport.sftp.clear_connection_cache()
        super(BoundSFTPBranch, self).tearDown()

    def test_simple_binding(self):
        self.build_tree(['base/', 'base/a', 'base/b', 'child/'])
        wt_base = BzrDir.create_standalone_workingtree('base')

        wt_base.add('a')
        wt_base.add('b')
        wt_base.commit('first', rev_id='r@b-1')

        b_base = wt_base.branch
        # manually make a branch we can bind, because the default format
        # may not be bindable-from, and we want to test the side effects etc
        # of bondage.
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
        # the bind must not have given b_child history:
        self.assertEqual([], b_child.revision_history())
        # we should be able to update the branch at this point:
        self.assertEqual(None, b_child.update())
        # and now there must be history.
        self.assertEqual(['r@b-1'], b_child.revision_history())
        # this line is more of a working tree test line, but - what the hey,
        # it has work to do.
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

    def test_bound_commit_fails_when_out_of_date(self):
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

        wt_child2 = wt_child.branch.create_checkout('child2')

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
        # Make sure it is detected if the current base is bound during the
        # objects lifetime, when the child goes to commit.
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
        wt_child_rev = wt_child.commit('child', rev_id='r@c-2')

        self.assertEqual(['r@b-1', 'r@c-2'], wt_child.branch.revision_history())
        self.assertEqual(['r@b-1'], b_base.revision_history())

        open('base/b', 'ab').write('base contents\n')
        b_base.bzrdir.open_workingtree().commit('base', rev_id='r@b-2')
        self.assertEqual(['r@b-1', 'r@b-2'], b_base.revision_history())

        sftp_b_base = Branch.open(self.get_url('base'))

        self.assertRaises(errors.DivergedBranches,
                wt_child.branch.bind, sftp_b_base)

        wt_child.merge_from_branch(sftp_b_base)
        self.assertEqual([wt_child_rev, 'r@b-2'], wt_child.get_parent_ids())
        wt_child.commit('merged', rev_id='r@c-3')

        # After a merge, trying to bind again should succeed but not push the
        # new change.
        wt_child.branch.bind(sftp_b_base)

        self.assertEqual(['r@b-1', 'r@b-2'], b_base.revision_history())
        self.assertEqual(['r@b-1', 'r@c-2', 'r@c-3'],
            wt_child.branch.revision_history())

    def test_bind_parent_ahead_preserves_parent(self):
        b_base, wt_child = self.create_branches()

        wt_child.branch.unbind()

        open('a', 'ab').write('base changes\n')
        wt_base = b_base.bzrdir.open_workingtree()
        wt_base.commit('base', rev_id='r@b-2')
        self.assertEqual(['r@b-1', 'r@b-2'], b_base.revision_history())
        self.assertEqual(['r@b-1'], wt_child.branch.revision_history())

        sftp_b_base = Branch.open(self.get_url('base'))
        wt_child.branch.bind(sftp_b_base)

        self.assertEqual(['r@b-1'], wt_child.branch.revision_history())

        wt_child.branch.unbind()

        # Check and make sure it also works if parent is ahead multiple
        wt_base.commit('base 3', rev_id='r@b-3', allow_pointless=True)
        wt_base.commit('base 4', rev_id='r@b-4', allow_pointless=True)
        wt_base.commit('base 5', rev_id='r@b-5', allow_pointless=True)

        self.assertEqual(['r@b-1', 'r@b-2', 'r@b-3', 'r@b-4', 'r@b-5'],
                b_base.revision_history())

        self.assertEqual(['r@b-1'], wt_child.branch.revision_history())

        wt_child.branch.bind(sftp_b_base)
        self.assertEqual(['r@b-1'], wt_child.branch.revision_history())

    def test_bind_child_ahead_preserves_child(self):
        b_base, wt_child = self.create_branches()

        wt_child.branch.unbind()

        wt_child.commit('child', rev_id='r@c-2', allow_pointless=True)
        self.assertEqual(['r@b-1', 'r@c-2'], wt_child.branch.revision_history())
        self.assertEqual(['r@b-1'], b_base.revision_history())

        sftp_b_base = Branch.open(self.get_url('base'))
        wt_child.branch.bind(sftp_b_base)

        self.assertEqual(['r@b-1'], b_base.revision_history())

        # Check and make sure it also works if child is ahead multiple
        wt_child.branch.unbind()
        wt_child.commit('child 3', rev_id='r@c-3', allow_pointless=True)
        wt_child.commit('child 4', rev_id='r@c-4', allow_pointless=True)
        wt_child.commit('child 5', rev_id='r@c-5', allow_pointless=True)

        self.assertEqual(['r@b-1', 'r@c-2', 'r@c-3', 'r@c-4', 'r@c-5'],
                wt_child.branch.revision_history())
        self.assertEqual(['r@b-1'], b_base.revision_history())

        wt_child.branch.bind(sftp_b_base)
        self.assertEqual(['r@b-1'], b_base.revision_history())

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

        wt_child.merge_from_branch(wt_other.branch)

        self.failUnlessExists('child/c')
        self.assertEqual(['r@d-2'], wt_child.get_parent_ids()[1:])
        self.failUnless(wt_child.branch.repository.has_revision('r@d-2'))
        self.failIf(b_base.repository.has_revision('r@d-2'))

        # Commit should succeed, and cause merged revisions to
        # be pushed into base
        wt_child.commit('merge other', rev_id='r@c-2')
        self.assertEqual(['r@b-1', 'r@c-2'], wt_child.branch.revision_history())
        self.assertEqual(['r@b-1', 'r@c-2'], b_base.revision_history())
        self.failUnless(b_base.repository.has_revision('r@d-2'))

    def test_commit_fails(self):
        b_base, wt_child = self.create_branches()

        open('a', 'ab').write('child adds some text\n')

        # this deletes the branch from memory
        del b_base
        # and this moves it out of the way on disk
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

        # this deletes the branch from memory
        del b_base
        # and this moves it out of the way on disk
        os.rename('base', 'hidden_base')

        self.assertRaises(errors.BoundBranchConnectionFailure,
                wt_child.pull, wt_other.branch)

    # TODO: jam 20051231 We need invasive failure tests, so that we can show
    #       performance even when something fails.


if not paramiko_loaded:
    del BoundSFTPBranch

