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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Tests for Branch.revision_id_to_revno()"""

from bzrlib import errors

from bzrlib.tests.branch_implementations.test_branch import TestCaseWithBranch


class TestRevisionIdToRevno(TestCaseWithBranch):

    def test_simple_revno(self):
        tree = self.create_tree_with_merge()
        the_branch = tree.branch

        self.assertEqual(1, the_branch.revision_id_to_revno('rev-1'))
        self.assertEqual(2, the_branch.revision_id_to_revno('rev-2'))
        self.assertEqual(3, the_branch.revision_id_to_revno('rev-3'))

        self.assertRaises(errors.NoSuchRevision,
                          the_branch.revision_id_to_revno, 'rev-none')
        # revision_id_to_revno is defined as returning only integer revision
        # numbers, so non-mainline revisions get NoSuchRevision raised
        self.assertRaises(errors.NoSuchRevision,
                          the_branch.revision_id_to_revno, 'rev-1.1.1')

