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

from bzrlib.selftest import TestCaseInTempDir
from bzrlib.branch import Branch
from bzrlib.commit import commit
from bzrlib.errors import PointlessCommit, BzrError, PointlessCommit
from bzrlib.selftest.revision import make_branches
from bzrlib.fetch import fetch
from bzrlib.check import check


class TestCommitMerge(TestCaseInTempDir):
    """Tests for committing the results of a merge.

    These don't currently test the merge code, which is intentional to
    reduce the scope of testing.  We just mark the revision as merged
    without bothering about the contents much."""

    def test_merge_commit_empty(self):
        """Simple commit of two-way merge of empty trees."""
        os.mkdir('x')
        os.mkdir('y')
        bx = Branch.initialize('x')
        by = Branch.initialize('y')

        commit(bx, 'commit one', rev_id='x@u-0-1', allow_pointless=True)
        commit(by, 'commit two', rev_id='y@u-0-1', allow_pointless=True)

        fetcher = fetch(from_branch=bx, to_branch=by)
        self.assertEqual(1, fetcher.count_copied)
        self.assertEqual([], fetcher.failed_revisions)
        # just having the history there does nothing
        self.assertRaises(PointlessCommit,
                          commit,
                          by, 'no changes yet', rev_id='y@u-0-2',
                          allow_pointless=False)
        by.working_tree().add_pending_merge('x@u-0-1')
        commit(by, 'merge from x', rev_id='y@u-0-2', allow_pointless=False)

        self.assertEquals(by.revno(), 2)
        self.assertEquals(list(by.revision_history()),
                          ['y@u-0-1', 'y@u-0-2'])
        rev = by.get_revision('y@u-0-2')
        self.assertEquals(rev.parent_ids,
                          ['y@u-0-1', 'x@u-0-1'])



    def test_merge_new_file(self):
        """Commit merge of two trees with no overlapping files."""
        self.build_tree(['x/', 'x/ecks', 'y/', 'y/why'])

        bx = Branch.initialize('x')
        by = Branch.initialize('y')
        bx.add(['ecks'], ['ecks-id'])
        by.add(['why'], ['why-id'])

        commit(bx, 'commit one', rev_id='x@u-0-1', allow_pointless=True)
        commit(by, 'commit two', rev_id='y@u-0-1', allow_pointless=True)

        fetch(from_branch=bx, to_branch=by)
        # we haven't merged the texts, but let's fake it
        shutil.copyfile('x/ecks', 'y/ecks')
        by.add(['ecks'], ['ecks-id'])
        by.working_tree().add_pending_merge('x@u-0-1')

        # partial commit of merges is currently not allowed, because
        # it would give different merge graphs for each file which
        # might be complex.  it can be allowed in the future.
        self.assertRaises(Exception,
                          commit,
                          by, 'partial commit', allow_pointless=False,
                          specific_files=['ecks'])
        
        commit(by, 'merge from x', rev_id='y@u-0-2', allow_pointless=False)
        tree = by.revision_tree('y@u-0-2')
        inv = tree.inventory
        self.assertEquals(inv['ecks-id'].revision, 'x@u-0-1')
        self.assertEquals(inv['why-id'].revision, 'y@u-0-1')

        check(bx, False)
        check(by, False)
