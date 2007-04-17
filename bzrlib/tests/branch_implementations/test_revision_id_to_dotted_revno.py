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

"""Tests for Branch.revision_id_to_dotted_revno()"""

from bzrlib import (
    errors,
    revision,
    )

from bzrlib.tests.branch_implementations import TestCaseWithBranch


class TestRevisionIdToDottedRevno(TestCaseWithBranch):

    def test_simple_revno(self):
        tree = self.create_tree_with_merge()
        the_branch = tree.branch

        id_to_revno = the_branch.revision_id_to_dotted_revno

        self.assertEqual((0,), id_to_revno(None))
        self.assertEqual((0,), id_to_revno(revision.NULL_REVISION))
        self.assertEqual((1,), id_to_revno('rev-1'))
        self.assertEqual((2,), id_to_revno('rev-2'))
        self.assertEqual((3,), id_to_revno('rev-3'))
        self.assertEqual((1,1,1), id_to_revno('rev-1.1.1'))

        self.assertRaises(errors.NoSuchRevision, id_to_revno, 'rev-none')
