# Copyright (C) 2008, 2009 Canonical Ltd
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

from bzrlib import (
    tests,
    )

from bzrlib.plugins import (
    upload,
    )
from bzrlib.plugins.upload import (
    cmds,
    )


class AutoPushHookTests(tests.TestCaseWithTransport):

    def setUp(self):
        super(AutoPushHookTests, self).setUp()
        upload.install_auto_upload_hook()

    def make_start_branch(self):
        self.wt = self.make_branch_and_tree('.')
        self.build_tree(['a'])
        self.wt.add(['a'])
        self.wt.commit("one")


class AutoPushWithLocation(AutoPushHookTests):

    def setUp(self):
        super(AutoPushWithLocation, self).setUp()
        self.make_start_branch()
        cmds.set_upload_auto(self.wt.branch, True)
        cmds.set_upload_location(self.wt.branch, self.get_url('target'))
        cmds.set_upload_auto_quiet(self.wt.branch, 'True')

    def test_auto_push_on_commit(self):
        self.failIfExists('target')
        self.build_tree(['b'])
        self.wt.add(['b'])
        self.wt.commit("two")
        self.failUnlessExists('target')
        self.failUnlessExists(os.path.join('target', 'a'))
        self.failUnlessExists(os.path.join('target', 'b'))

    def test_disable_auto_push(self):
        self.failIfExists('target')
        self.build_tree(['b'])
        self.wt.add(['b'])
        self.wt.commit("two")
        cmds.set_upload_auto(self.wt.branch, False)
        self.build_tree(['c'])
        self.wt.add(['c'])
        self.wt.commit("three")
        self.failIfExists(os.path.join('target', 'c'))


class AutoPushWithoutLocation(AutoPushHookTests):

    def setUp(self):
        super(AutoPushWithoutLocation, self).setUp()
        self.make_start_branch()
        cmds.set_upload_auto(self.wt.branch, True)

    def test_dont_push_if_no_location(self):
        self.failIfExists('target')
        self.build_tree(['b'])
        self.wt.add(['b'])
        self.wt.commit("two")
        self.failIfExists('target')
