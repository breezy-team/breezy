# Copyright (C) 2004, 2005, 2007 Canonical Ltd
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

"""Tests for branch.push behaviour."""

import os

from bzrlib.branch import Branch
from bzrlib import errors
from bzrlib.tests import TestCaseWithTransport


class TestPush(TestCaseWithTransport):

    def test_push_convergence_simple(self):
        # when revisions are pushed, the left-most accessible parents must 
        # become the revision-history.
        mine = self.make_branch_and_tree('mine')
        mine.commit('1st post', rev_id='P1', allow_pointless=True)
        other = mine.bzrdir.sprout('other').open_workingtree()
        other.commit('my change', rev_id='M1', allow_pointless=True)
        mine.merge_from_branch(other.branch)
        mine.commit('merge my change', rev_id='P2')
        mine.branch.push(other.branch)
        self.assertEqual(['P1', 'P2'], other.branch.revision_history())

    def test_push_merged_indirect(self):
        # it should be possible to do a push from one branch into another
        # when the tip of the target was merged into the source branch
        # via a third branch - so its buried in the ancestry and is not
        # directly accessible.
        mine = self.make_branch_and_tree('mine')
        mine.commit('1st post', rev_id='P1', allow_pointless=True)
        target = mine.bzrdir.sprout('target').open_workingtree()
        target.commit('my change', rev_id='M1', allow_pointless=True)
        other = mine.bzrdir.sprout('other').open_workingtree()
        other.merge_from_branch(target.branch)
        other.commit('merge my change', rev_id='O2')
        mine.merge_from_branch(other.branch)
        mine.commit('merge other', rev_id='P2')
        mine.branch.push(target.branch)
        self.assertEqual(['P1', 'P2'], target.branch.revision_history())

    def test_push_to_checkout_updates_master(self):
        """Pushing into a checkout updates the checkout and the master branch"""
        master_tree = self.make_branch_and_tree('master')
        rev1 = master_tree.commit('master')
        checkout = master_tree.branch.create_checkout('checkout')

        other = master_tree.branch.bzrdir.sprout('other').open_workingtree()
        rev2 = other.commit('other commit')
        # now push, which should update both checkout and master.
        other.branch.push(checkout.branch)
        self.assertEqual([rev1, rev2], checkout.branch.revision_history())
        self.assertEqual([rev1, rev2], master_tree.branch.revision_history())

    def test_push_raises_specific_error_on_master_connection_error(self):
        master_tree = self.make_branch_and_tree('master')
        checkout = master_tree.branch.create_checkout('checkout')
        other = master_tree.branch.bzrdir.sprout('other').open_workingtree()
        # move the branch out of the way on disk to cause a connection
        # error.
        os.rename('master', 'master_gone')
        # try to push, which should raise a BoundBranchConnectionFailure.
        self.assertRaises(errors.BoundBranchConnectionFailure,
                other.branch.push, checkout.branch)
