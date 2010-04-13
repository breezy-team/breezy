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

"""Tests for Branch.revision_id_to_dotted_revno()"""

from bzrlib import errors

from bzrlib.tests.per_branch import TestCaseWithBranch


class TestRevisionIdToDottedRevno(TestCaseWithBranch):

    def test_lookup_dotted_revno(self):
        tree = self.create_tree_with_merge()
        the_branch = tree.branch
        self.assertEqual((0,), the_branch.revision_id_to_dotted_revno('null:'))
        self.assertEqual((1,), the_branch.revision_id_to_dotted_revno('rev-1'))
        self.assertEqual((2,), the_branch.revision_id_to_dotted_revno('rev-2'))
        self.assertEqual((3,), the_branch.revision_id_to_dotted_revno('rev-3'))
        self.assertEqual((1,1,1), the_branch.revision_id_to_dotted_revno(
            'rev-1.1.1'))
        self.assertRaises(errors.NoSuchRevision,
                          the_branch.revision_id_to_dotted_revno, 'rev-1.0.2')
