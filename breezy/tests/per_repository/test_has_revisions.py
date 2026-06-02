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

"""Tests for implementations of Repository.has_revisions."""

from breezy.tests.per_repository import TestCaseWithRepository

from ...revision import NULL_REVISION


class TestHasRevisions(TestCaseWithRepository):
    def test_empty_list(self):
        repo = self.make_repository(".")
        self.assertEqual(set(), repo.has_revisions([]))

    def test_superset(self):
        tree = self.make_branch_and_tree(".")
        repo = tree.branch.repository
        rev1 = tree.commit("1")
        tree.commit("2")
        rev3 = tree.commit("3")
        self.assertEqual({rev1, rev3}, repo.has_revisions([rev1, rev3, b"foobar:"]))

    def test_NULL(self):
        # NULL_REVISION is always present. So for
        # compatibility with 'has_revision' we make this work.
        repo = self.make_repository(".")
        self.assertEqual({NULL_REVISION}, repo.has_revisions([NULL_REVISION]))
