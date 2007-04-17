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


class TestDottedRevnoCaching(TestCaseWithBranch):
    """Tests for the caching of branches' dotted revno generation.

    When locked, branches should avoid regenerating revision_id=>dotted revno
    mapping.

    When not locked, obviously the revision_id => dotted revno will need to be
    regenerated or reread each time.

    We test if revision_history is using the cache by instrumenting the branch's
    _gen_revno_map method, which is called by
    Branch.revision_id_to_dotted_revno if the branch does not have a cache of
    the dotted revnos.
    """

    def get_instrumented_branch(self):
        """Get a branch and monkey patch it to log calls to _gen_revno_map.

        :returns: a tuple of (the branch, list that calls will be logged to)
        """
        tree = self.create_tree_with_merge()
        calls = []
        real_func = tree.branch._gen_revno_map
        def wrapper():
            calls.append('_gen_revno_map')
            return real_func()
        tree.branch._gen_revno_map = wrapper
        return tree.branch, calls

    def test_unlocked(self):
        """Repeated calls will call _gen_revno_map each time."""
        branch, calls = self.get_instrumented_branch()
        # Repeatedly call revision_history.
        self.assertEqual((1,), branch.revision_id_to_dotted_revno('rev-1'))
        self.assertEqual((2,), branch.revision_id_to_dotted_revno('rev-2'))
        self.assertEqual((3,), branch.revision_id_to_dotted_revno('rev-3'))
        self.assertEqual(['_gen_revno_map']*3, calls)

    def test_locked(self):
        """Repeated calls will only call _gen_revno_map once.
        """
        branch, calls = self.get_instrumented_branch()
        # Lock the branch, then repeatedly call revision_history.
        branch.lock_read()
        try:
            self.assertEqual((1,), branch.revision_id_to_dotted_revno('rev-1'))
            self.assertEqual((2,), branch.revision_id_to_dotted_revno('rev-2'))
            self.assertEqual((3,), branch.revision_id_to_dotted_revno('rev-3'))
            self.assertEqual(['_gen_revno_map'], calls)
        finally:
            branch.unlock()

    def test_set_revision_history_when_locked(self):
        """Calling set_revision_history should reset the cache."""
        branch, calls = self.get_instrumented_branch()
        branch.lock_write()
        try:
            self.assertEqual((1,), branch.revision_id_to_dotted_revno('rev-1'))
            branch.set_revision_history(['rev-1', 'rev-2'])
            self.assertEqual((2,), branch.revision_id_to_dotted_revno('rev-2'))
            self.assertRaises(errors.NoSuchRevision,
                              branch.revision_id_to_dotted_revno, 'rev-3')
            self.assertEqual(['_gen_revno_map']*2, calls)
        finally:
            branch.unlock()

    def test_set_last_revision_info_when_locked(self):
        """Calling set_last_revision_info should reset the cache."""
        branch, calls = self.get_instrumented_branch()
        branch.lock_write()
        try:
            self.assertEqual((1,), branch.revision_id_to_dotted_revno('rev-1'))
            branch.set_last_revision_info(2, 'rev-2')
            self.assertEqual((2,), branch.revision_id_to_dotted_revno('rev-2'))
            self.assertRaises(errors.NoSuchRevision,
                              branch.revision_id_to_dotted_revno, 'rev-3')
            self.assertEqual(['_gen_revno_map']*2, calls)
        finally:
            branch.unlock()
