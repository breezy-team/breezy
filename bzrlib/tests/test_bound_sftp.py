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

"""\
Tests for branches bound to an sftp branch.
"""

import os

from bzrlib.tests.test_sftp import TestCaseWithSFTPServer, paramiko_loaded
import bzrlib.errors as errors
from bzrlib.branch import Branch
from bzrlib.clone import copy_branch


class BoundSFTPBranch(TestCaseWithSFTPServer):

    def create_branches(self):
        self.delayed_setup()

        self.build_tree(['base/', 'base/a', 'base/b'])
        b_base = Branch.initialize('base')

        wt_base = b_base.working_tree()
        wt_base.add('a')
        wt_base.add('b')
        wt_base.commit('first', rev_id='r@b-1')

        b_child = copy_branch(b_base, 'child')
        b_child.set_bound_location(self._sftp_url + 'base')

        self.assertEqual(['r@b-1'], b_base.revision_history())
        self.assertEqual(['r@b-1'], b_child.revision_history())

        return b_base, b_child

    def test_simple_binding(self):
        self.delayed_setup()
        self.build_tree(['base/', 'base/a', 'base/b', 'child/'])
        b_base = Branch.initialize('base')

        wt_base = b_base.working_tree()
        wt_base.add('a')
        wt_base.add('b')
        wt_base.commit('first', rev_id='r@b-1')

        b_child = Branch.initialize('child')
        self.assertEqual(None, b_child.get_bound_location())
        self.assertEqual(None, b_child.get_master_branch())

        sftp_b_base = Branch.open(self._sftp_url + 'base')
        b_child.bind(sftp_b_base)
        self.failUnlessExists('child/.bzr/bound')
        self.failUnlessExists('child/a')
        self.failUnlessExists('child/b')

        b_child.unbind()
        self.failIf(os.path.lexists('child/.bzr/bound'))

    def test_bound_commit(self):
        b_base, b_child = self.create_branches()

        open('child/a', 'wb').write('new contents\n')
        wt_child = b_child.working_tree()
        wt_child.commit('modified a', rev_id='r@c-2')

        self.assertEqual(['r@b-1', 'r@c-2'], b_child.revision_history())
        self.assertEqual(['r@b-1', 'r@c-2'], b_base.revision_history())

    def test_bound_fail(self):
        # Make sure commit fails if out of date.
        b_base, b_child = self.create_branches()

        open('base/a', 'wb').write('new base contents\n')
        b_base.working_tree().commit('base', rev_id='r@b-2')

        wt_child = b_child.working_tree()
        open('child/b', 'wb').write('new b child contents\n')
        self.assertRaises(errors.BoundBranchOutOfDate,
                wt_child.commit, 'child', rev_id='r@c-2')

        sftp_b_base = Branch.open(self._sftp_url + 'base')

        # This is all that cmd_update does
        wt_child.pull(sftp_b_base, overwrite=False)

        wt_child.commit('child', rev_id='r@c-3')

        self.assertEqual(['r@b-1', 'r@b-2', 'r@c-3'],
                b_child.revision_history())
        self.assertEqual(['r@b-1', 'r@b-2', 'r@c-3'],
                b_base.revision_history())
        self.assertEqual(['r@b-1', 'r@b-2', 'r@c-3'],
                sftp_b_base.revision_history())

    def test_double_binding(self):
        b_base, b_child = self.create_branches()

        b_child2 = copy_branch(b_child, 'child2')

        b_child2.bind(b_child)

        open('child2/a', 'wb').write('new contents\n')
        self.assertRaises(errors.CommitToDoubleBoundBranch,
                b_child2.working_tree().commit, 'child2', rev_id='r@d-2')

    def test_unbinding(self):
        from bzrlib.transport import get_transport
        b_base, b_child = self.create_branches()

        # TestCaseWithSFTPServer only allows you to connect one time
        # to the SFTP server. So we have to create a connection and
        # keep it around, so that it can be reused
        __unused_t = get_transport(self._sftp_url)

        wt_base = b_base.working_tree()
        open('base/a', 'wb').write('new base contents\n')
        wt_base.commit('base', rev_id='r@b-2')

        wt_child = b_child.working_tree()
        open('child/b', 'wb').write('new b child contents\n')
        self.assertRaises(errors.BoundBranchOutOfDate,
                wt_child.commit, 'child', rev_id='r@c-2')
        self.assertEqual(['r@b-1'], b_child.revision_history())
        b_child.unbind()
        wt_child.commit('child', rev_id='r@c-2')
        self.assertEqual(['r@b-1', 'r@c-2'], b_child.revision_history())
        self.assertEqual(['r@b-1', 'r@b-2'], b_base.revision_history())

        sftp_b_base = Branch.open(self._sftp_url + 'base')
        self.assertRaises(errors.DivergedBranches,
                b_child.bind, sftp_b_base)

    def test_commit_remote_bound(self):
        # Make sure it is detected if the current base
        # suddenly is bound when child goes to commit
        b_base, b_child = self.create_branches()

        copy_branch(b_base, 'newbase')

        sftp_b_base = Branch.open(self._sftp_url + 'base')
        sftp_b_newbase = Branch.open(self._sftp_url + 'newbase')

        sftp_b_base.bind(sftp_b_newbase)

        open('child/a', 'wb').write('new contents\n')
        self.assertRaises(errors.CommitToDoubleBoundBranch,
                b_child.working_tree().commit, 'failure', rev_id='r@c-2')

        self.assertEqual(['r@b-1'], b_base.revision_history())
        self.assertEqual(['r@b-1'], b_child.revision_history())
        self.assertEqual(['r@b-1'], sftp_b_newbase.revision_history())

    def test_pull_updates_both(self):
        b_base, b_child = self.create_branches()

        b_newchild = copy_branch(b_base, 'newchild')
        open('newchild/b', 'wb').write('newchild b contents\n')
        b_newchild.working_tree().commit('newchild', rev_id='r@d-2')
        self.assertEqual(['r@b-1', 'r@d-2'], b_newchild.revision_history())

        b_child.pull(b_newchild)
        self.assertEqual(['r@b-1', 'r@d-2'], b_child.revision_history())
        self.assertEqual(['r@b-1', 'r@d-2'], b_base.revision_history())

    def test_bind_diverged(self):
        from bzrlib.merge import merge, merge_inner

        b_base, b_child = self.create_branches()

        b_child.unbind()
        open('child/a', 'ab').write('child contents\n')
        wt_child = b_child.working_tree()
        wt_child.commit('child', rev_id='r@c-2')

        self.assertEqual(['r@b-1', 'r@c-2'], b_child.revision_history())
        self.assertEqual(['r@b-1'], b_base.revision_history())

        open('base/b', 'ab').write('base contents\n')
        b_base.working_tree().commit('base', rev_id='r@b-2')
        self.assertEqual(['r@b-1', 'r@b-2'], b_base.revision_history())

        sftp_b_base = Branch.open(self._sftp_url + 'base')

        self.assertRaises(errors.DivergedBranches,
                b_child.bind, sftp_b_base)

        # TODO: jam 20051230 merge_inner doesn't set pending merges
        #       Is this on purpose?
        #       merge_inner also doesn't fetch any missing revisions
        #merge_inner(b_child, sftp_b_base.revision_tree('r@b-2'), 
        #        b_child.revision_tree('r@b-1'))
        # TODO: jam 20051230 merge(..., (None, None), ...) seems to
        #       cause an infinite loop of some sort. It definitely doesn't
        #       work, you have to use list notation
        merge((sftp_b_base.base, 2), [None, None], this_dir=b_child.base)

        self.assertEqual(['r@b-2'], wt_child.pending_merges())
        wt_child.commit('merged', rev_id='r@c-3')

        # After a merge, trying to bind again should succeed
        # by pushing the new change to base
        b_child.bind(sftp_b_base)

        self.assertEqual(['r@b-1', 'r@b-2', 'r@c-3'],
                b_base.revision_history())
        self.assertEqual(['r@b-1', 'r@b-2', 'r@c-3'],
                b_child.revision_history())

    def test_bind_parent_ahead(self):
        b_base, b_child = self.create_branches()

        b_child.unbind()

        open('a', 'ab').write('base changes\n')
        wt_base = b_base.working_tree()
        wt_base.commit('base', rev_id='r@b-2')
        self.assertEqual(['r@b-1', 'r@b-2'], b_base.revision_history())
        self.assertEqual(['r@b-1'], b_child.revision_history())

        sftp_b_base = Branch.open(self._sftp_url + 'base')
        b_child.bind(sftp_b_base)

        self.assertEqual(['r@b-1', 'r@b-2'], b_child.revision_history())

        b_child.unbind()

        # Check and make sure it also works if parent is ahead multiple
        wt_base.commit('base 3', rev_id='r@b-3', allow_pointless=True)
        wt_base.commit('base 4', rev_id='r@b-4', allow_pointless=True)
        wt_base.commit('base 5', rev_id='r@b-5', allow_pointless=True)

        self.assertEqual(['r@b-1', 'r@b-2', 'r@b-3', 'r@b-4', 'r@b-5'],
                b_base.revision_history())

        self.assertEqual(['r@b-1', 'r@b-2'], b_child.revision_history())

        b_child.bind(sftp_b_base)
        self.assertEqual(['r@b-1', 'r@b-2', 'r@b-3', 'r@b-4', 'r@b-5'],
                b_child.revision_history())

    def test_bind_child_ahead(self):
        b_base, b_child = self.create_branches()

        b_child.unbind()

        wt_child = b_child.working_tree()
        wt_child.commit('child', rev_id='r@c-2', allow_pointless=True)
        self.assertEqual(['r@b-1', 'r@c-2'], b_child.revision_history())
        self.assertEqual(['r@b-1'], b_base.revision_history())

        sftp_b_base = Branch.open(self._sftp_url + 'base')
        b_child.bind(sftp_b_base)

        self.assertEqual(['r@b-1', 'r@c-2'], b_base.revision_history())

        # Check and make sure it also works if child is ahead multiple
        b_child.unbind()
        wt_child.commit('child 3', rev_id='r@c-3', allow_pointless=True)
        wt_child.commit('child 4', rev_id='r@c-4', allow_pointless=True)
        wt_child.commit('child 5', rev_id='r@c-5', allow_pointless=True)

        self.assertEqual(['r@b-1', 'r@c-2', 'r@c-3', 'r@c-4', 'r@c-5'],
                b_child.revision_history())
        self.assertEqual(['r@b-1', 'r@c-2'], b_base.revision_history())

        b_child.bind(sftp_b_base)
        self.assertEqual(['r@b-1', 'r@c-2', 'r@c-3', 'r@c-4', 'r@c-5'],
                b_base.revision_history())

    def test_commit_after_merge(self):
        from bzrlib.merge import merge, merge_inner

        b_base, b_child = self.create_branches()

        # We want merge to be able to be a local only
        # operation, because it can be without violating
        # the binding invariants.
        # But we can't fail afterwards

        b_other = copy_branch(b_child, 'other')

        open('other/c', 'wb').write('file c\n')
        wt_other = b_other.working_tree()
        wt_other.add('c')
        wt_other.commit('adding c', rev_id='r@d-2')

        self.failIf(b_child.has_revision('r@d-2'))
        self.failIf(b_base.has_revision('r@d-2'))

        wt_child = b_child.working_tree()
        # TODO: jam 20051230 merge_inner doesn't set pending merges
        #       Is this on purpose?
        #       merge_inner also doesn't fetch any missing revisions
        #merge_inner(b_child, b_other.revision_tree('r@d-2'),
        #        b_child.revision_tree('r@b-1'))
        merge((b_other.base, 2), [None, None], this_dir=b_child.base)

        self.failUnlessExists('child/c')
        self.assertEqual(['r@d-2'], wt_child.pending_merges())
        self.failUnless(b_child.has_revision('r@d-2'))
        self.failIf(b_base.has_revision('r@d-2'))

        # Commit should succeed, and cause merged revisions to
        # be pulled into base
        wt_child.commit('merge other', rev_id='r@c-2')
        self.assertEqual(['r@b-1', 'r@c-2'], b_child.revision_history())
        self.assertEqual(['r@b-1', 'r@c-2'], b_base.revision_history())
        self.failUnless(b_base.has_revision('r@d-2'))

    def test_pull_overwrite_fails(self):
        b_base, b_child = self.create_branches()

        b_other = copy_branch(b_child, 'other')
        wt_other = b_other.working_tree()
        
        open('other/a', 'wb').write('new contents\n')
        wt_other.commit('changed a', rev_id='r@d-2')

        open('child/a', 'wb').write('also changed a\n')
        wt_child = b_child.working_tree()
        wt_child.commit('child modified a', rev_id='r@c-2')

        self.assertEqual(['r@b-1', 'r@c-2'], b_base.revision_history())
        self.assertEqual(['r@b-1', 'r@c-2'], b_child.revision_history())
        self.assertEqual(['r@b-1', 'r@d-2'], b_other.revision_history())

        # It might be possible that we want pull --overwrite to
        # actually succeed.
        # If we want it, just change this test to make sure that 
        # both base and child are updated properly
        self.assertRaises(errors.OverwriteBoundBranch,
                wt_child.pull, b_other, overwrite=True)

        # It should fail without changing the local revision
        self.assertEqual(['r@b-1', 'r@c-2'], b_base.revision_history())
        self.assertEqual(['r@b-1', 'r@c-2'], b_child.revision_history())

    # TODO: jam 20051230 Test that commit & pull fail when the branch we 
    #       are bound to is not available


if not paramiko_loaded:
    del BoundSFTPBranch

