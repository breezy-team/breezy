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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Tests for interface conformance of 'workingtree.get_parent_ids'"""

from breezy.tests import TestNotApplicable
from breezy.tests.per_workingtree import TestCaseWithWorkingTree


class TestGetParentIds(TestCaseWithWorkingTree):

    def test_get_parent_ids(self):
        t = self.make_branch_and_tree('t1')
        self.assertEqual([], t.get_parent_ids())
        rev1_id = t.commit('foo', allow_pointless=True)
        self.assertEqual([rev1_id], t.get_parent_ids())
        t2 = t.controldir.sprout('t2').open_workingtree()
        rev2_id = t2.commit('foo', allow_pointless=True)
        self.assertEqual([rev2_id], t2.get_parent_ids())
        t.merge_from_branch(t2.branch)
        self.assertEqual([rev1_id, rev2_id], t.get_parent_ids())
        for parent_id in t.get_parent_ids():
            self.assertIsInstance(parent_id, bytes)

    def test_pending_merges(self):
        """Test the correspondence between set pending merges and get_parent_ids."""
        wt = self.make_branch_and_tree('.')
        self.assertEqual([], wt.get_parent_ids())
        if not wt._format. supports_righthand_parent_id_as_ghost:
            raise TestNotApplicable(
                'format does not support right hand side parents '
                'that are ghosts')
        # the first pending merge replaces the 'last revision' because
        # 'last revision' is shorthand for 'left most parent'
        wt.add_pending_merge(b'foo@azkhazan-123123-abcabc')
        self.assertEqual([b'foo@azkhazan-123123-abcabc'], wt.get_parent_ids())
        # adding a merge which is already in the parents list gets ignored.
        wt.add_pending_merge(b'foo@azkhazan-123123-abcabc')
        self.assertEqual([b'foo@azkhazan-123123-abcabc'], wt.get_parent_ids())
        # adding a different merge results in it being appended to the list -
        # order is preserved.
        wt.add_pending_merge(b'wibble@fofof--20050401--1928390812')
        self.assertEqual([b'foo@azkhazan-123123-abcabc',
                          b'wibble@fofof--20050401--1928390812'],
                         wt.get_parent_ids())
