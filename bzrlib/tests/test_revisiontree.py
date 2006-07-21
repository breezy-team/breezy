# Copyright (C) 2006 Canonical Ltd
# Authors:  Robert Collins <robert.collins@canonical.com>
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

"""Tests for the RevisionTree class."""

import bzrlib
from bzrlib.tests import TestCaseWithTransport
from bzrlib.tree import RevisionTree


class TestTreeWithCommits(TestCaseWithTransport):

    def setUp(self):
        super(TestTreeWithCommits, self).setUp()
        self.t = self.make_branch_and_tree('.')
        self.rev_id = self.t.commit('foo', allow_pointless=True)
        self.rev_tree = self.t.branch.repository.revision_tree(self.rev_id)

    def test_empty_no_unknowns(self):
        self.assertEqual([], list(self.rev_tree.unknowns()))

    def test_no_conflicts(self):
        self.assertEqual([], list(self.rev_tree.conflicts()))

    def test_parents(self):
        """RevisionTree.parent_ids should match the revision graph."""
        # XXX: TODO: Should this be a repository_implementation test ?
        # at the end of the graph, we get []
        self.assertEqual([], self.rev_tree.get_parent_ids())
        # do a commit to look further up
        revid_2 = self.t.commit('bar', allow_pointless=True)
        self.assertEqual(
            [self.rev_id],
            self.t.branch.repository.revision_tree(revid_2).get_parent_ids())
        # TODO commit a merge and check it is reported correctly.
