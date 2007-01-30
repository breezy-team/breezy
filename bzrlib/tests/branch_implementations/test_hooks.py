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

"""Tests that branch classes implement hook callouts correctly."""

from bzrlib.branch import Branch
from bzrlib.tests import TestCaseWithMemoryTransport


class TestPushHook(TestCaseWithMemoryTransport):

    def setUp(self):
        self.hook_calls = []
        TestCaseWithMemoryTransport.setUp(self)

    def capture_set_rh_hook(self, branch, rev_history):
        """Capture post push hook calls to self.hook_calls.
        
        The call is logged, as is some state of the two branches.
        """
        self.hook_calls.append(
            ('set_rh', branch, rev_history, branch.is_locked()))

    def test_set_rh_empty_history(self):
        branch = self.make_branch('source')
        Branch.hooks['set_rh'].append(self.capture_set_rh_hook)
        branch.set_revision_history([])
        self.assertEqual(self.hook_calls,
            [('set_rh', branch, [], True)])

    def test_set_rh_nonempty_history(self):
        branch = self.make_branch('source')
        Branch.hooks['set_rh'].append(self.capture_set_rh_hook)
        branch.set_revision_history([u'foo'])
        self.assertEqual(self.hook_calls,
            [('set_rh', branch, [u'foo'], True)])

    def test_set_rh_branch_is_locked(self):
        branch = self.make_branch('source')
        Branch.hooks['set_rh'].append(self.capture_set_rh_hook)
        branch.set_revision_history([])
        self.assertEqual(self.hook_calls,
            [('set_rh', branch, [], True)])

    def test_set_rh_calls_all_hooks_no_errors(self):
        branch = self.make_branch('source')
        Branch.hooks['set_rh'].append(self.capture_set_rh_hook)
        Branch.hooks['set_rh'].append(self.capture_set_rh_hook)
        branch.set_revision_history([])
        self.assertEqual(self.hook_calls,
            [('set_rh', branch, [], True),
             ('set_rh', branch, [], True),
            ])

