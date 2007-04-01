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

"""Tests for Branch.revision_history."""

from bzrlib import branch
from bzrlib.tests.branch_implementations.test_branch import TestCaseWithBranch


class TestRevisionHistoryCaching(TestCaseWithBranch):
    """Tests for the caching of branches' revision_history.

    When locked, branches should avoid regenerating or rereading
    revision_history by caching the last value of it.  This is safe because
    the branch is locked, so nothing can change the revision_history
    unexpectedly.

    When not locked, obviously the revision_history will need to be regenerated
    or reread each time.

    We test if revision_history is using the cache by instrumenting the branch's
    _gen_revision_history method, which is called by Branch.revision_history if
    the branch does not have a cache of the revision history.
    """

    def get_instrumented_branch(self):
        """Get a branch and monkey patch it to log calls to
        _gen_revision_history.

        :returns: a tuple of (the branch, list that calls will be logged to)
        """
        branch = self.get_branch()
        calls = []
        real_gen_revision_history = branch._gen_revision_history
        def fake_gen_revision_history():
            calls.append('_gen_revision_history')
            return real_gen_revision_history()
        branch._gen_revision_history = fake_gen_revision_history
        return branch, calls

    def test_revision_history_when_unlocked(self):
        """Repeated calls to revision history will call _gen_revision_history
        each time when the branch is not locked.
        """
        branch, calls = self.get_instrumented_branch()
        # Repeatedly call revision_history.
        branch.revision_history()
        branch.revision_history()
        self.assertEqual(
            ['_gen_revision_history', '_gen_revision_history'], calls)

    def test_revision_history_when_locked(self):
        """Repeated calls to revision history will only call
        _gen_revision_history once while the branch is locked.
        """
        branch, calls = self.get_instrumented_branch()
        # Lock the branch, then repeatedly call revision_history.
        branch.lock_read()
        try:
            branch.revision_history()
            branch.revision_history()
            self.assertEqual(['_gen_revision_history'], calls)
        finally:
            branch.unlock()

    def test_set_revision_history_when_locked(self):
        """When the branch is locked, calling set_revision_history should cache
        the revision history so that a later call to revision_history will not
        need to call _gen_revision_history.
        """
        branch, calls = self.get_instrumented_branch()
        # Lock the branch, set the revision history, then repeatedly call
        # revision_history.
        branch.lock_write()
        branch.set_revision_history([])
        try:
            branch.revision_history()
            self.assertEqual([], calls)
        finally:
            branch.unlock()

    def test_set_revision_history_when_unlocked(self):
        """When the branch is not locked, calling set_revision_history will not
        cause the revision history to be cached.
        """
        branch, calls = self.get_instrumented_branch()
        # Lock the branch, set the revision history, then repeatedly call
        # revision_history.
        branch.set_revision_history([])
        branch.revision_history()
        self.assertEqual(['_gen_revision_history'], calls)

    def test_set_last_revision_info_when_locked(self):
        """When the branch is locked, calling set_last_revision_info should
        cache the last revision info so that a later call to last_revision_info
        will not need the revision_history.  Thus the branch will not to call
        _gen_revision_history in this situation.
        """
        a_branch, calls = self.get_instrumented_branch()
        # Lock the branch, set the last revision info, then call
        # last_revision_info.
        a_branch.lock_write()
        a_branch.set_last_revision_info(0, None)
        del calls[:]
        try:
            a_branch.last_revision_info()
            self.assertEqual([], calls)
        finally:
            a_branch.unlock()

    def test_set_last_revision_info_uncaches_revision_history_for_format6(self):
        """On format 6 branches, set_last_revision_info invalidates the revision
        history cache.
        """
        if not isinstance(self.branch_format, branch.BzrBranchFormat6):
            return
        a_branch, calls = self.get_instrumented_branch()
        # Lock the branch, cache the revision history.
        a_branch.lock_write()
        a_branch.revision_history()
        # Set the last revision info, clearing the cache.
        a_branch.set_last_revision_info(0, None)
        del calls[:]
        try:
            a_branch.revision_history()
            self.assertEqual(['_gen_revision_history'], calls)
        finally:
            a_branch.unlock()

    def test_cached_revision_history_not_accidentally_mutable(self):
        """When there's a cached version of the history, revision_history
        returns a copy of the cached data so that callers cannot accidentally
        corrupt the cache.
        """
        branch = self.get_branch()
        # Lock the branch, then repeatedly call revision_history, mutating the
        # results.
        branch.lock_read()
        try:
            # The first time the data returned will not be in the cache.
            history = branch.revision_history()
            history.append('one')
            # The second time the data comes from the cache.
            history = branch.revision_history()
            history.append('two')
            # The revision_history() should still be unchanged, even though
            # we've mutated the return values from earlier calls.
            self.assertEqual([], branch.revision_history())
        finally:
            branch.unlock()



