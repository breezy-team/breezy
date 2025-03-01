# Copyright (C) 2008, 2009, 2011, 2012 Canonical Ltd
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

from .... import tests
from ... import upload


class AutoPushHookTests(tests.TestCaseWithTransport):
    def setUp(self):
        super().setUp()
        upload.install_auto_upload_hook()

    def make_start_branch(self):
        self.wt = self.make_branch_and_tree(".")
        self.build_tree(["a"])
        self.wt.add(["a"])
        self.wt.commit("one")


class AutoPushWithLocation(AutoPushHookTests):
    def setUp(self):
        super().setUp()
        self.make_start_branch()
        conf = self.wt.branch.get_config_stack()
        conf.set("upload_auto", True)
        conf.set("upload_location", self.get_url("target"))
        conf.set("upload_auto_quiet", True)

    def test_auto_push_on_commit(self):
        self.assertPathDoesNotExist("target")
        self.build_tree(["b"])
        self.wt.add(["b"])
        self.wt.commit("two")
        self.assertPathExists("target")
        self.assertPathExists(os.path.join("target", "a"))
        self.assertPathExists(os.path.join("target", "b"))

    def test_disable_auto_push(self):
        self.assertPathDoesNotExist("target")
        self.build_tree(["b"])
        self.wt.add(["b"])
        self.wt.commit("two")
        self.wt.branch.get_config_stack().set("upload_auto", False)
        self.build_tree(["c"])
        self.wt.add(["c"])
        self.wt.commit("three")
        self.assertPathDoesNotExist(os.path.join("target", "c"))


class AutoPushWithoutLocation(AutoPushHookTests):
    def setUp(self):
        super().setUp()
        self.make_start_branch()
        self.wt.branch.get_config_stack().set("upload_auto", True)

    def test_dont_push_if_no_location(self):
        self.assertPathDoesNotExist("target")
        self.build_tree(["b"])
        self.wt.add(["b"])
        self.wt.commit("two")
        self.assertPathDoesNotExist("target")
