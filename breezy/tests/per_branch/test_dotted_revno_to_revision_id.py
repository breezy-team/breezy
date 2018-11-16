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

"""Tests for Branch.dotted_revno_to_revision_id()"""

from breezy import errors

from breezy.tests.per_branch import TestCaseWithBranch


class TestDottedRevnoToRevisionId(TestCaseWithBranch):

    def test_lookup_revision_id_by_dotted(self):
        tree, revmap = self.create_tree_with_merge()
        the_branch = tree.branch
        the_branch.lock_read()
        self.addCleanup(the_branch.unlock)
        self.assertEqual(
            b'null:', the_branch.dotted_revno_to_revision_id((0,)))
        self.assertEqual(revmap['1'],
                         the_branch.dotted_revno_to_revision_id((1, )))
        self.assertEqual(revmap['2'],
                         the_branch.dotted_revno_to_revision_id((2, )))
        self.assertEqual(revmap['3'],
                         the_branch.dotted_revno_to_revision_id((3, )))
        self.assertEqual(revmap['1.1.1'],
                         the_branch.dotted_revno_to_revision_id(
            (1, 1, 1)))
        self.assertRaises(
            errors.NoSuchRevision,
            the_branch.dotted_revno_to_revision_id, (1, 0, 2))
        # Test reverse caching
        self.assertEqual(
            None,
            the_branch._partial_revision_id_to_revno_cache.get(revmap['1']))
        self.assertEqual(
            revmap['1'], the_branch.dotted_revno_to_revision_id(
                (1, ), _cache_reverse=True))
        self.assertEqual(
            (1,),
            the_branch._partial_revision_id_to_revno_cache.get(revmap['1']))
