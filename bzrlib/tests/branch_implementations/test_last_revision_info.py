# Copyright (C) 2004, 2005, 2007 Canonical Ltd
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

"""Tests for branch.last_revision_info."""

from bzrlib.revision import NULL_REVISION
from bzrlib.tests import TestCaseWithTransport


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
