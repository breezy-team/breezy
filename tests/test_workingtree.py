# Copyright (C) 2010-2018 Jelmer Vernooij <jelmer@jelmer.uk>
# Copyright (C) 2011 Canonical Ltd.
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

"""Tests for Git working trees."""

from __future__ import absolute_import

from .... import conflicts as _mod_conflicts
from ..workingtree import (
    FLAG_STAGEMASK,
    )
from ....tests import TestCaseWithTransport


class GitWorkingTreeTests(TestCaseWithTransport):

    def setUp(self):
        super(GitWorkingTreeTests, self).setUp()
        self.tree = self.make_branch_and_tree('.', format="git")

    def test_conflict_list(self):
        self.assertIsInstance(
                self.tree.conflicts(),
                _mod_conflicts.ConflictList)

    def test_add_conflict(self):
        self.build_tree(['conflicted'])
        self.tree.add(['conflicted'])
        with self.tree.lock_tree_write():
            self.tree.index['conflicted'] = self.tree.index['conflicted'][:9] + (FLAG_STAGEMASK, )
        conflicts = self.tree.conflicts()
        self.assertEqual(1, len(conflicts))

    def test_revert_empty(self):
        self.build_tree(['a'])
        self.tree.add(['a'])
        self.assertTrue(self.tree.is_versioned('a'))
        self.tree.revert(['a'])
        self.assertFalse(self.tree.is_versioned('a'))
