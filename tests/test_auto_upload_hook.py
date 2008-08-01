# Copyright (C) 2008 Canonical Ltd
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

import os

from bzrlib.branch import Branch
from bzrlib.tests import TestCaseWithTransport

from bzrlib.plugins.upload import set_upload_location, set_upload_auto
from bzrlib.plugins.upload.auto_upload_hook import auto_upload_hook

# Hooks are disabled during tests, so that they don't cause havoc
# with a users system. What we will test is that the hook was
# correctly registered, and then set up the scenarios and trigger
# it manually

class AutoPushHookTests(TestCaseWithTransport):

    def make_start_branch(self, location=True, auto=True):
        self.wt = self.make_branch_and_tree('.')
        self.build_tree(['a'])
        self.wt.add(['a'])
        self.wt.commit("one")
        if location:
            set_upload_location(self.wt.branch, self.target_location())
        if auto:
            set_upload_auto(self.wt.branch, True)

    def target_location(self):
        return self.get_url('target')

    def get_params(self):
        class FakeParams(object):
            def __init__(self, branch):
                self.branch = branch
        return FakeParams(self.wt.branch)

    def test_hook_is_registered(self):
        # Hooks are stored in self._preserved_hooks
        self.assertTrue(auto_upload_hook in 
                self._preserved_hooks[Branch]['post_change_branch_tip'])

    def test_auto_push_on_commit(self):
        self.make_start_branch()
        self.failIfExists('target')
        self.build_tree(['b'])
        self.wt.add(['b'])
        self.wt.commit("two")
        auto_upload_hook(self.get_params(), quiet=True)
        self.failUnlessExists('target')
        self.failUnlessExists(os.path.join('target', 'a'))
        self.failUnlessExists(os.path.join('target', 'b'))

    def test_disable_auto_push(self):
        self.make_start_branch()
        self.failIfExists('target')
        self.build_tree(['b'])
        self.wt.add(['b'])
        self.wt.commit("two")
        auto_upload_hook(self.get_params(), quiet=True)
        set_upload_auto(self.wt.branch, False)
        self.build_tree(['c'])
        self.wt.add(['c'])
        self.wt.commit("three")
        auto_upload_hook(self.get_params(), quiet=True)
        self.failIfExists(os.path.join('target', 'c'))

    def test_dont_push_if_no_location(self):
        self.make_start_branch(location=False)
        self.failIfExists('target')
        self.build_tree(['b'])
        self.wt.add(['b'])
        self.wt.commit("two")
        auto_upload_hook(self.get_params(), quiet=True)
        self.failIfExists('target')

