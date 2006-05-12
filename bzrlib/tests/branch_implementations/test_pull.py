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

"""Tests for branch.pull behaviour."""

import os

from bzrlib.branch import Branch
from bzrlib.osutils import abspath, realpath
from bzrlib.tests import TestCaseWithTransport


class TestPull(TestCaseWithTransport):

    def test_pull_convergence_simple(self):
        # when revisions are pulled, the left-most accessible parents must 
        # become the revision-history.
        parent = self.make_branch_and_tree('parent')
        parent.commit('1st post', rev_id='P1', allow_pointless=True)
        mine = parent.bzrdir.sprout('mine').open_workingtree()
        mine.commit('my change', rev_id='M1', allow_pointless=True)
        self.merge(mine.branch, parent)
        parent.commit('merge my change', rev_id='P2')
        mine.pull(parent.branch)
        self.assertEqual(['P1', 'P2'], mine.branch.revision_history())

    def test_pull_merged_indirect(self):
        # it should be possible to do a pull from one branch into another
        # when the tip of the target was merged into the source branch
        # via a third branch - so its buried in the ancestry and is not
        # directly accessible.
        parent = self.make_branch_and_tree('parent')
        parent.commit('1st post', rev_id='P1', allow_pointless=True)
        mine = parent.bzrdir.sprout('mine').open_workingtree()
        mine.commit('my change', rev_id='M1', allow_pointless=True)
        other = parent.bzrdir.sprout('other').open_workingtree()
        self.merge(mine.branch, other)
        other.commit('merge my change', rev_id='O2')
        self.merge(other.branch, parent)
        parent.commit('merge other', rev_id='P2')
        mine.pull(parent.branch)
        self.assertEqual(['P1', 'P2'], mine.branch.revision_history())
