# Copyright (C) 2007 Canonical Ltd
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

"""Tests for repository packing."""

from breezy.tests.per_repository import TestCaseWithRepository


class TestPack(TestCaseWithRepository):

    def test_pack_empty_does_not_error(self):
        repo = self.make_repository('.')
        repo.pack()

    def test_pack_accepts_opaque_hint(self):
        # For requesting packs of a repository where some data is known to be
        # unoptimal we permit packing just some data via a hint. If the hint is
        # illegible it is ignored.
        tree = self.make_branch_and_tree('tree')
        rev1 = tree.commit('1')
        rev2 = tree.commit('2')
        rev3 = tree.commit('3')
        rev4 = tree.commit('4')
        tree.branch.repository.pack(
            hint=[rev3.decode('utf-8'), rev4.decode('utf-8')])
