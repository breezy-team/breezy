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


import os
import shutil

from bzrlib.tests import TestCaseWithTransport
from bzrlib.branch import Branch
from bzrlib.errors import PointlessCommit, BzrError, PointlessCommit
from bzrlib.tests.test_revision import make_branches
from bzrlib.check import check


class TestCommitMerge(TestCaseWithTransport):
    """Tests for committing the results of a merge.

    These don't currently test the merge code, which is intentional to
    reduce the scope of testing.  We just mark the revision as merged
    without bothering about the contents much."""

    def test_merge_commit_empty(self):
        """Simple commit of two-way merge of empty trees."""
        wtx = self.make_branch_and_tree('x')
        bx = wtx.branch
        wty = self.make_branch_and_tree('y')
        by = wty.branch

        wtx.commit('commit one', rev_id='x@u-0-1', allow_pointless=True)
        wty.commit('commit two', rev_id='y@u-0-1', allow_pointless=True)

        self.assertEqual((1, []), by.fetch(bx))
        # just having the history there does nothing
        self.assertRaises(PointlessCommit,
                          wty.commit,
                          'no changes yet', rev_id='y@u-0-2',
                          allow_pointless=False)
        wty.add_pending_merge('x@u-0-1')
        wty.commit('merge from x', rev_id='y@u-0-2', allow_pointless=False)

        self.assertEquals(by.revno(), 2)
        self.assertEquals(list(by.revision_history()),
                          ['y@u-0-1', 'y@u-0-2'])
        rev = by.repository.get_revision('y@u-0-2')
        self.assertEquals(rev.parent_ids,
                          ['y@u-0-1', 'x@u-0-1'])

    def test_merge_new_file(self):
        """Commit merge of two trees with no overlapping files."""
        wtx = self.make_branch_and_tree('x')
        bx = wtx.branch
        wty = self.make_branch_and_tree('y')
        by = wty.branch

        self.build_tree(['x/ecks', 'y/why'])

        wtx.add(['ecks'], ['ecks-id'])
        wty.add(['why'], ['why-id'])

        wtx.commit('commit one', rev_id='x@u-0-1', allow_pointless=True)
        wty.commit('commit two', rev_id='y@u-0-1', allow_pointless=True)

        by.fetch(bx)
        # we haven't merged the texts, but let's fake it
        shutil.copyfile('x/ecks', 'y/ecks')
        wty.add(['ecks'], ['ecks-id'])
        wty.add_pending_merge('x@u-0-1')

        # partial commit of merges is currently not allowed, because
        # it would give different merge graphs for each file which
        # might be complex.  it can be allowed in the future.
        self.assertRaises(Exception,
                          wty.commit,
                          'partial commit', allow_pointless=False,
                          specific_files=['ecks'])
        
        wty.commit('merge from x', rev_id='y@u-0-2', allow_pointless=False)
        tree = by.repository.revision_tree('y@u-0-2')
        inv = tree.inventory
        self.assertEquals(inv['ecks-id'].revision, 'x@u-0-1')
        self.assertEquals(inv['why-id'].revision, 'y@u-0-1')

        check(bx, False)
        check(by, False)
