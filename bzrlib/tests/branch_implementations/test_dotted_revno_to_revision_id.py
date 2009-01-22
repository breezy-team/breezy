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

"""Tests for Branch.dotted_revno_to_revision_id()"""

from bzrlib import errors

from bzrlib.tests.branch_implementations import TestCaseWithBranch


class TestDottedRevnoToRevisionId(TestCaseWithBranch):

    def test_lookup_revision_id_by_dotted(self):
        tree = self.create_tree_with_merge()
        the_branch = tree.branch
        self.assertEqual('null:', the_branch.dotted_revno_to_revision_id((0,)))
        self.assertEqual('rev-1', the_branch.dotted_revno_to_revision_id((1,)))
        self.assertEqual('rev-2', the_branch.dotted_revno_to_revision_id((2,)))
        self.assertEqual('rev-3', the_branch.dotted_revno_to_revision_id((3,)))
        self.assertEqual('rev-1.1.1', the_branch.dotted_revno_to_revision_id(
            (1,1,1)))
        self.assertRaises(errors.NoSuchRevision,
                          the_branch.dotted_revno_to_revision_id, (1,0,2))
        # Test reverse caching
        self.assertEqual(None,
            the_branch._revision_id_to_revno_top_cache.get('rev-1'))
        self.assertEqual('rev-1', the_branch.dotted_revno_to_revision_id((1,),
            _reverse_cache=True))
        self.assertEqual((1,),
            the_branch._revision_id_to_revno_top_cache.get('rev-1'))
