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

"""Tests for Branch.get_revision_id_to_revno_map()."""

from breezy.tests.per_branch import TestCaseWithBranch


class TestRevisionIdToDottedRevno(TestCaseWithBranch):
    def test_simple_revno(self):
        tree, revmap = self.create_tree_with_merge()
        # Re-open the branch so we make sure we start fresh.
        # see bug #162486
        the_branch = tree.controldir.open_branch()

        self.assertEqual(
            {
                revmap["1"]: (1,),
                revmap["2"]: (2,),
                revmap["3"]: (3,),
                revmap["1.1.1"]: (1, 1, 1),
            },
            the_branch.get_revision_id_to_revno_map(),
        )


class TestCaching(TestCaseWithBranch):
    """Tests for the caching of branches' dotted revno generation.

    When locked, branches should avoid regenerating revision_id=>dotted revno
    mapping.

    When not locked, obviously the revision_id => dotted revno will need to be
    regenerated or reread each time.

    We test if revision_history is using the cache by instrumenting the branch's
    _gen_revno_map method, which is called by get_revision_id_to_revno_map.
    """

    def get_instrumented_branch(self):
        """Get a branch and monkey patch it to log calls to _gen_revno_map.

        :returns: a tuple of (the branch, list that calls will be logged to)
        """
        tree, revmap = self.create_tree_with_merge()
        calls = []
        real_func = tree.branch._gen_revno_map

        def wrapper():
            calls.append("_gen_revno_map")
            return real_func()

        tree.branch._gen_revno_map = wrapper
        return tree.branch, revmap, calls

    def test_unlocked(self):
        """Repeated calls will call _gen_revno_map each time."""
        branch, revmap, calls = self.get_instrumented_branch()
        # Repeatedly call revision_history.
        branch.get_revision_id_to_revno_map()
        branch.get_revision_id_to_revno_map()
        branch.get_revision_id_to_revno_map()
        self.assertEqual(["_gen_revno_map"] * 3, calls)

    def test_locked(self):
        """Repeated calls will only call _gen_revno_map once."""
        branch, revmap, calls = self.get_instrumented_branch()
        # Lock the branch, then repeatedly call revision_history.
        with branch.lock_read():
            branch.get_revision_id_to_revno_map()
            self.assertEqual(["_gen_revno_map"], calls)

    def test_set_last_revision_info_when_locked(self):
        """Calling set_last_revision_info should reset the cache."""
        branch, revmap, calls = self.get_instrumented_branch()
        with branch.lock_write():
            self.assertEqual(
                {
                    revmap["1"]: (1,),
                    revmap["2"]: (2,),
                    revmap["3"]: (3,),
                    revmap["1.1.1"]: (1, 1, 1),
                },
                branch.get_revision_id_to_revno_map(),
            )
            branch.set_last_revision_info(2, revmap["2"])
            self.assertEqual(
                {revmap["1"]: (1,), revmap["2"]: (2,)},
                branch.get_revision_id_to_revno_map(),
            )
            self.assertEqual(
                {revmap["1"]: (1,), revmap["2"]: (2,)},
                branch.get_revision_id_to_revno_map(),
            )
            self.assertEqual(["_gen_revno_map"] * 2, calls)
