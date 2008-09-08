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


import os
import warnings

from bzrlib import (
    revision,
    symbol_versioning,
    )
from bzrlib.branch import Branch
from bzrlib.errors import NoSuchRevision
from bzrlib.deprecated_graph import Graph
from bzrlib.revision import (find_present_ancestors,
                             NULL_REVISION)
from bzrlib.symbol_versioning import one_three
from bzrlib.tests import TestCase, TestCaseWithTransport
from bzrlib.trace import mutter
from bzrlib.workingtree import WorkingTree

# We're allowed to test deprecated interfaces
warnings.filterwarnings('ignore',
        '.*get_intervening_revisions was deprecated',
        DeprecationWarning,
        r'bzrlib\.tests\.test_revision')

# XXX: Make this a method of a merge base case
def make_branches(self, format=None):
    """Create two branches

    branch 1 has 6 commits, branch 2 has 3 commits
    commit 10 is a ghosted merge merge from branch 1

    the object graph is
    B:     A:
    a..0   a..0 
    a..1   a..1
    a..2   a..2
    b..3   a..3 merges b..4
    b..4   a..4
    b..5   a..5 merges b..5
    b..6 merges a4

    so A is missing b6 at the start
    and B is missing a3, a4, a5
    """
    tree1 = self.make_branch_and_tree("branch1", format=format)
    br1 = tree1.branch
    
    tree1.commit("Commit one", rev_id="a@u-0-0")
    tree1.commit("Commit two", rev_id="a@u-0-1")
    tree1.commit("Commit three", rev_id="a@u-0-2")

    tree2 = tree1.bzrdir.clone("branch2").open_workingtree()
    br2 = tree2.branch
    tree2.commit("Commit four", rev_id="b@u-0-3")
    tree2.commit("Commit five", rev_id="b@u-0-4")
    revisions_2 = br2.revision_history()
    self.assertEquals(revisions_2[-1], 'b@u-0-4')
    
    tree1.merge_from_branch(br2)
    tree1.commit("Commit six", rev_id="a@u-0-3")
    tree1.commit("Commit seven", rev_id="a@u-0-4")
    tree2.commit("Commit eight", rev_id="b@u-0-5")
    self.assertEquals(br2.revision_history()[-1], 'b@u-0-5')
    
    tree1.merge_from_branch(br2)
    tree1.commit("Commit nine", rev_id="a@u-0-5")
    # DO NOT MERGE HERE - we WANT a GHOST.
    tree2.add_parent_tree_id(br1.revision_history()[4])
    tree2.commit("Commit ten - ghost merge", rev_id="b@u-0-6")
    
    return br1, br2


class TestIsAncestor(TestCaseWithTransport):

    def test_recorded_ancestry(self):
        """Test that commit records all ancestors"""
        br1, br2 = make_branches(self)
        d = [('a@u-0-0', ['a@u-0-0']),
             ('a@u-0-1', ['a@u-0-0', 'a@u-0-1']),
             ('a@u-0-2', ['a@u-0-0', 'a@u-0-1', 'a@u-0-2']),
             ('b@u-0-3', ['a@u-0-0', 'a@u-0-1', 'a@u-0-2', 'b@u-0-3']),
             ('b@u-0-4', ['a@u-0-0', 'a@u-0-1', 'a@u-0-2', 'b@u-0-3',
                          'b@u-0-4']),
             ('a@u-0-3', ['a@u-0-0', 'a@u-0-1', 'a@u-0-2', 'b@u-0-3', 'b@u-0-4',
                          'a@u-0-3']),
             ('a@u-0-4', ['a@u-0-0', 'a@u-0-1', 'a@u-0-2', 'b@u-0-3', 'b@u-0-4',
                          'a@u-0-3', 'a@u-0-4']),
             ('b@u-0-5', ['a@u-0-0', 'a@u-0-1', 'a@u-0-2', 'b@u-0-3', 'b@u-0-4',
                          'b@u-0-5']),
             ('a@u-0-5', ['a@u-0-0', 'a@u-0-1', 'a@u-0-2', 'a@u-0-3', 'a@u-0-4',
                          'b@u-0-3', 'b@u-0-4',
                          'b@u-0-5', 'a@u-0-5']),
             ('b@u-0-6', ['a@u-0-0', 'a@u-0-1', 'a@u-0-2',
                          'b@u-0-3', 'b@u-0-4',
                          'b@u-0-5', 'b@u-0-6']),
             ]
        br1_only = ('a@u-0-3', 'a@u-0-4', 'a@u-0-5')
        br2_only = ('b@u-0-6',)
        for branch in br1, br2:
            for rev_id, anc in d:
                if rev_id in br1_only and not branch is br1:
                    continue
                if rev_id in br2_only and not branch is br2:
                    continue
                mutter('ancestry of {%s}: %r',
                       rev_id, branch.repository.get_ancestry(rev_id))
                result = sorted(branch.repository.get_ancestry(rev_id))
                self.assertEquals(result, [None] + sorted(anc))
    

class TestIntermediateRevisions(TestCaseWithTransport):

    def setUp(self):
        TestCaseWithTransport.setUp(self)
        self.br1, self.br2 = make_branches(self)
        wt1 = self.br1.bzrdir.open_workingtree()
        wt2 = self.br2.bzrdir.open_workingtree()
        wt2.commit("Commit eleven", rev_id="b@u-0-7")
        wt2.commit("Commit twelve", rev_id="b@u-0-8")
        wt2.commit("Commit thirtteen", rev_id="b@u-0-9")

        wt1.merge_from_branch(self.br2)
        wt1.commit("Commit fourtten", rev_id="a@u-0-6")

        wt2.merge_from_branch(self.br1)
        wt2.commit("Commit fifteen", rev_id="b@u-0-10")


class MockRevisionSource(object):
    """A RevisionSource that takes a pregenerated graph.

    This is useful for testing revision graph algorithms where
    the actual branch existing is irrelevant.
    """

    def __init__(self, full_graph):
        self._full_graph = full_graph

    def get_revision_graph_with_ghosts(self, revision_ids):
        # This is mocked out to just return a constant graph.
        return self._full_graph


class TestCommonAncestor(TestCaseWithTransport):
    """Test checking whether a revision is an ancestor of another revision"""

    def test_get_history(self):
        # TODO: test ghosts on the left hand branch's impact
        # TODO: test ghosts on all parents, we should get some
        # indicator. i.e. NULL_REVISION
        # RBC 20060608
        tree = self.make_branch_and_tree('.')
        tree.commit('1', rev_id = '1', allow_pointless=True)
        tree.commit('2', rev_id = '2', allow_pointless=True)
        tree.commit('3', rev_id = '3', allow_pointless=True)
        rev = tree.branch.repository.get_revision('1')
        history = rev.get_history(tree.branch.repository)
        self.assertEqual([None, '1'], history)
        rev = tree.branch.repository.get_revision('2')
        history = rev.get_history(tree.branch.repository)
        self.assertEqual([None, '1', '2'], history)
        rev = tree.branch.repository.get_revision('3')
        history = rev.get_history(tree.branch.repository)
        self.assertEqual([None, '1', '2' ,'3'], history)


class TestReservedId(TestCase):

    def test_is_reserved_id(self):
        self.assertEqual(True, revision.is_reserved_id(NULL_REVISION))
        self.assertEqual(True, revision.is_reserved_id(
            revision.CURRENT_REVISION))
        self.assertEqual(True, revision.is_reserved_id('arch:'))
        self.assertEqual(False, revision.is_reserved_id('null'))
        self.assertEqual(False, revision.is_reserved_id(
            'arch:a@example.com/c--b--v--r'))
        self.assertEqual(False, revision.is_reserved_id(None))


class TestRevisionMethods(TestCase):

    def test_get_summary(self):
        r = revision.Revision('1')
        r.message = 'a'
        self.assertEqual('a', r.get_summary())
        r.message = 'a\nb'
        self.assertEqual('a', r.get_summary())
        r.message = '\na\nb'
        self.assertEqual('a', r.get_summary())

    def test_get_apparent_author(self):
        r = revision.Revision('1')
        r.committer = 'A'
        self.assertEqual('A', r.get_apparent_author())
        r.properties['author'] = 'B'
        self.assertEqual('B', r.get_apparent_author())
