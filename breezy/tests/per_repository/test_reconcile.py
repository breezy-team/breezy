# Copyright (C) 2006-2010 Canonical Ltd
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

"""Tests for reconciliation of repositories."""


from breezy.tests.per_repository import (
    TestCaseWithRepository,
    )


class TestRepeatedReconcile(TestCaseWithRepository):

    def test_trivial_two_reconciles_no_error(self):
        tree = self.make_branch_and_tree('.')
        tree.commit('first post')
        tree.branch.repository.reconcile(thorough=True)
        tree.branch.repository.reconcile(thorough=True)
