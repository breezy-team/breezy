# Copyright (C) 2007, 2009-2012, 2016 Canonical Ltd
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

"""Tests for branch.last_revision_info."""

from breezy.revision import NULL_REVISION
from breezy.tests import TestCaseWithTransport


class TestLastRevisionInfo(TestCaseWithTransport):

    def test_empty_branch(self):
        # on an empty branch we want (0, NULL_REVISION)
        branch = self.make_branch('branch')
        self.assertEqual((0, NULL_REVISION), branch.last_revision_info())

    def test_non_empty_branch(self):
        # after the second commit we want (2, 'second-revid')
        tree = self.make_branch_and_tree('branch')
        tree.commit('1st post')
        revid = tree.commit('2st post', allow_pointless=True)
        self.assertEqual((2, revid), tree.branch.last_revision_info())

    def test_import(self):
        # importing and setting last revision
        tree1 = self.make_branch_and_tree('branch1')
        tree1.commit('1st post')
        revid = tree1.commit('2st post', allow_pointless=True)
        branch2 = self.make_branch('branch2')
        self.assertEqual((2, revid),
                         branch2.import_last_revision_info_and_tags(tree1.branch, 2, revid))
        self.assertEqual((2, revid), branch2.last_revision_info())
        self.assertTrue(branch2.repository.has_revision(revid))

    def test_import_lossy(self):
        # importing with lossy=True works
        tree1 = self.make_branch_and_tree('branch1')
        tree1.commit('1st post')
        revid = tree1.commit('2st post', allow_pointless=True)
        branch2 = self.make_branch('branch2')
        ret = branch2.import_last_revision_info_and_tags(tree1.branch, 2,
                                                         revid, lossy=True)
        self.assertIsInstance(ret, tuple)
        self.assertIsInstance(ret[0], int)
        self.assertIsInstance(ret[1], bytes)

    def test_same_repo(self):
        # importing and setting last revision within the same repo
        tree = self.make_branch_and_tree('branch1')
        tree.commit('1st post')
        revid = tree.commit('2st post', allow_pointless=True)
        tree.branch.set_last_revision_info(0, NULL_REVISION)
        tree.branch.import_last_revision_info_and_tags(tree.branch, 2, revid)
        self.assertEqual((2, revid), tree.branch.last_revision_info())
