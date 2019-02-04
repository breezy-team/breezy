# Copyright (C) 2008 Canonical Ltd
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

"""Tests for all_revision_ids on a repository with external references."""

from breezy.tests.per_repository_reference import (
    TestCaseWithExternalReferenceRepository,
    )


class TestAllRevisionIds(TestCaseWithExternalReferenceRepository):

    def test_all_revision_ids_empty(self):
        base = self.make_repository('base')
        repo = self.make_referring('referring', base)
        self.assertEqual(set([]), set(repo.all_revision_ids()))

    def test_all_revision_ids_from_base(self):
        tree = self.make_branch_and_tree('base')
        revid = tree.commit('one')
        repo = self.make_referring('referring', tree.branch.repository)
        self.assertEqual({revid}, set(repo.all_revision_ids()))

    def test_all_revision_ids_from_repo(self):
        tree = self.make_branch_and_tree('spare')
        revid = tree.commit('one')
        base = self.make_repository('base')
        repo = self.make_referring('referring', base)
        repo.fetch(tree.branch.repository, revid)
        self.assertEqual({revid}, set(repo.all_revision_ids()))

    def test_all_revision_ids_from_both(self):
        tree = self.make_branch_and_tree('spare')
        revid = tree.commit('one')
        base_tree = self.make_branch_and_tree('base')
        revid2 = base_tree.commit('two')
        repo = self.make_referring('referring', base_tree.branch.repository)
        repo.fetch(tree.branch.repository, revid)
        self.assertEqual({revid, revid2}, set(repo.all_revision_ids()))

    def test_duplicate_ids_do_not_affect_length(self):
        tree = self.make_branch_and_tree('spare')
        revid = tree.commit('one')
        base = self.make_repository('base')
        repo = self.make_referring('referring', base)
        repo.fetch(tree.branch.repository, revid)
        base.fetch(tree.branch.repository, revid)
        self.assertEqual({revid}, set(repo.all_revision_ids()))
        self.assertEqual(1, len(repo.all_revision_ids()))
