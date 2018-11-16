# Copyright (C) 2005-2011, 2016 Canonical Ltd
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA


import warnings

from breezy import (
    bugtracker,
    revision,
    )
from breezy.revision import NULL_REVISION
from breezy.tests import TestCase, TestCaseWithTransport
from breezy.tests.matchers import MatchesAncestry

# We're allowed to test deprecated interfaces
warnings.filterwarnings('ignore',
                        '.*get_intervening_revisions was deprecated',
                        DeprecationWarning,
                        r'breezy\.tests\.test_revision')

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

    tree1.commit("Commit one", rev_id=b"a@u-0-0")
    tree1.commit("Commit two", rev_id=b"a@u-0-1")
    tree1.commit("Commit three", rev_id=b"a@u-0-2")

    tree2 = tree1.controldir.sprout("branch2").open_workingtree()
    br2 = tree2.branch
    tree2.commit("Commit four", rev_id=b"b@u-0-3")
    tree2.commit("Commit five", rev_id=b"b@u-0-4")
    self.assertEqual(br2.last_revision(), b'b@u-0-4')

    tree1.merge_from_branch(br2)
    tree1.commit("Commit six", rev_id=b"a@u-0-3")
    tree1.commit("Commit seven", rev_id=b"a@u-0-4")
    tree2.commit("Commit eight", rev_id=b"b@u-0-5")
    self.assertEqual(br2.last_revision(), b'b@u-0-5')

    tree1.merge_from_branch(br2)
    tree1.commit("Commit nine", rev_id=b"a@u-0-5")
    # DO NOT MERGE HERE - we WANT a GHOST.
    br1.lock_read()
    try:
        graph = br1.repository.get_graph()
        revhistory = list(graph.iter_lefthand_ancestry(br1.last_revision(),
                                                       [revision.NULL_REVISION]))
        revhistory.reverse()
    finally:
        br1.unlock()
    tree2.add_parent_tree_id(revhistory[4])
    tree2.commit("Commit ten - ghost merge", rev_id=b"b@u-0-6")

    return br1, br2


class TestIsAncestor(TestCaseWithTransport):

    def test_recorded_ancestry(self):
        """Test that commit records all ancestors"""
        br1, br2 = make_branches(self)
        d = [(b'a@u-0-0', [b'a@u-0-0']),
             (b'a@u-0-1', [b'a@u-0-0', b'a@u-0-1']),
             (b'a@u-0-2', [b'a@u-0-0', b'a@u-0-1', b'a@u-0-2']),
             (b'b@u-0-3', [b'a@u-0-0', b'a@u-0-1', b'a@u-0-2', b'b@u-0-3']),
             (b'b@u-0-4', [b'a@u-0-0', b'a@u-0-1', b'a@u-0-2', b'b@u-0-3',
                           b'b@u-0-4']),
             (b'a@u-0-3', [b'a@u-0-0', b'a@u-0-1', b'a@u-0-2', b'b@u-0-3', b'b@u-0-4',
                           b'a@u-0-3']),
             (b'a@u-0-4', [b'a@u-0-0', b'a@u-0-1', b'a@u-0-2', b'b@u-0-3', b'b@u-0-4',
                           b'a@u-0-3', b'a@u-0-4']),
             (b'b@u-0-5', [b'a@u-0-0', b'a@u-0-1', b'a@u-0-2', b'b@u-0-3', b'b@u-0-4',
                           b'b@u-0-5']),
             (b'a@u-0-5', [b'a@u-0-0', b'a@u-0-1', b'a@u-0-2', b'a@u-0-3', b'a@u-0-4',
                           b'b@u-0-3', b'b@u-0-4',
                           b'b@u-0-5', b'a@u-0-5']),
             (b'b@u-0-6', [b'a@u-0-0', b'a@u-0-1', b'a@u-0-2', b'a@u-0-4',
                           b'b@u-0-3', b'b@u-0-4',
                           b'b@u-0-5', b'b@u-0-6']),
             ]
        br1_only = (b'a@u-0-3', b'a@u-0-4', b'a@u-0-5')
        br2_only = (b'b@u-0-6',)
        for branch in br1, br2:
            for rev_id, anc in d:
                if rev_id in br1_only and branch is not br1:
                    continue
                if rev_id in br2_only and branch is not br2:
                    continue
                self.assertThat(anc,
                                MatchesAncestry(branch.repository, rev_id))


class TestIntermediateRevisions(TestCaseWithTransport):

    def setUp(self):
        TestCaseWithTransport.setUp(self)
        self.br1, self.br2 = make_branches(self)
        wt1 = self.br1.controldir.open_workingtree()
        wt2 = self.br2.controldir.open_workingtree()
        wt2.commit("Commit eleven", rev_id=b"b@u-0-7")
        wt2.commit("Commit twelve", rev_id=b"b@u-0-8")
        wt2.commit("Commit thirtteen", rev_id=b"b@u-0-9")

        wt1.merge_from_branch(self.br2)
        wt1.commit("Commit fourtten", rev_id=b"a@u-0-6")

        wt2.merge_from_branch(self.br1)
        wt2.commit("Commit fifteen", rev_id=b"b@u-0-10")


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
        tree.commit('1', rev_id=b'1', allow_pointless=True)
        tree.commit('2', rev_id=b'2', allow_pointless=True)
        tree.commit('3', rev_id=b'3', allow_pointless=True)
        rev = tree.branch.repository.get_revision(b'1')
        history = rev.get_history(tree.branch.repository)
        self.assertEqual([None, b'1'], history)
        rev = tree.branch.repository.get_revision(b'2')
        history = rev.get_history(tree.branch.repository)
        self.assertEqual([None, b'1', b'2'], history)
        rev = tree.branch.repository.get_revision(b'3')
        history = rev.get_history(tree.branch.repository)
        self.assertEqual([None, b'1', b'2', b'3'], history)


class TestReservedId(TestCase):

    def test_is_reserved_id(self):
        self.assertEqual(True, revision.is_reserved_id(NULL_REVISION))
        self.assertEqual(True, revision.is_reserved_id(
            revision.CURRENT_REVISION))
        self.assertEqual(True, revision.is_reserved_id(b'arch:'))
        self.assertEqual(False, revision.is_reserved_id(b'null'))
        self.assertEqual(False, revision.is_reserved_id(
            b'arch:a@example.com/c--b--v--r'))
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
        r.message = None
        self.assertEqual('', r.get_summary())

    def test_get_apparent_authors(self):
        r = revision.Revision('1')
        r.committer = 'A'
        self.assertEqual(['A'], r.get_apparent_authors())
        r.properties[u'author'] = 'B'
        self.assertEqual(['B'], r.get_apparent_authors())
        r.properties[u'authors'] = 'C\nD'
        self.assertEqual(['C', 'D'], r.get_apparent_authors())

    def test_get_apparent_authors_no_committer(self):
        r = revision.Revision('1')
        self.assertEqual([], r.get_apparent_authors())


class TestRevisionBugs(TestCase):
    """Tests for getting the bugs that a revision is linked to."""

    def test_no_bugs(self):
        r = revision.Revision('1')
        self.assertEqual([], list(r.iter_bugs()))

    def test_some_bugs(self):
        r = revision.Revision(
            '1', properties={
                u'bugs': bugtracker.encode_fixes_bug_urls(
                    [('http://example.com/bugs/1', 'fixed'),
                     ('http://launchpad.net/bugs/1234', 'fixed')])})
        self.assertEqual(
            [('http://example.com/bugs/1', bugtracker.FIXED),
             ('http://launchpad.net/bugs/1234', bugtracker.FIXED)],
            list(r.iter_bugs()))

    def test_no_status(self):
        r = revision.Revision(
            '1', properties={u'bugs': 'http://example.com/bugs/1'})
        self.assertRaises(bugtracker.InvalidLineInBugsProperty, list,
                          r.iter_bugs())

    def test_too_much_information(self):
        r = revision.Revision(
            '1', properties={u'bugs': 'http://example.com/bugs/1 fixed bar'})
        self.assertRaises(bugtracker.InvalidLineInBugsProperty, list,
                          r.iter_bugs())

    def test_invalid_status(self):
        r = revision.Revision(
            '1', properties={u'bugs': 'http://example.com/bugs/1 faxed'})
        self.assertRaises(bugtracker.InvalidBugStatus, list, r.iter_bugs())
