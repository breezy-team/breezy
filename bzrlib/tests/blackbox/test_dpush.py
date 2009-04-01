# Copyright (C) 2005, 2007, 2008 Canonical Ltd
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

"""Black-box tests for bzr dpush."""

from bzrlib.branch import Branch
from bzrlib.bzrdir import BzrDirFormat
from bzrlib.foreign import ForeignBranch, ForeignRepository
from bzrlib.repository import Repository
from bzrlib.tests.blackbox import ExternalBase
from bzrlib.tests.test_foreign import DummyForeignVcsDirFormat

import os

class TestDpush(ExternalBase):

    def setUp(self):
        BzrDirFormat.register_control_format(DummyForeignVcsDirFormat)
        super(TestDpush, self).setUp()

    def tearDown(self):
        try:
            BzrDirFormat.unregister_control_format(DummyForeignVcsDirFormat)
        except ValueError:
            pass
        super(TestDpush, self).tearDown()

    def test_dpush_native(self):
        tree = self.make_branch_and_tree("dp")
        self.run_bzr("init dc")
        error = self.run_bzr("dpush -d dc dp", retcode=3)[1]
        self.assertContainsRe(error, 'not a foreign branch, use regular push')

    def test_dpush(self):
        tree = self.make_branch_and_tree("d", format=DummyForeignVcsDirFormat())

        self.build_tree(("d/foo", "bar"))
        tree.add("foo")
        tree.commit("msg")

        self.run_bzr("branch d dc")
        self.build_tree(("dc/foo", "blaaaa"))
        self.run_bzr("commit -m msg dc")
        self.run_bzr("dpush -d dc d")
        self.check_output("", "status dc")

    def test_dpush_new(self):
        tree = self.make_branch_and_tree("d", format=DummyForeignVcsDirFormat())

        self.build_tree(("d/foo", "bar"))
        tree.add("foo")
        tree.commit("msg") # rev 1

        self.run_bzr("branch d dc")
        self.build_tree(("dc/foofile", "blaaaa"))
        self.run_bzr("add dc/foofile")
        self.run_bzr("commit -m msg dc") # rev 2
        self.run_bzr("dpush -d dc d")
        self.check_output("2\n", "revno dc")
        self.check_output("", "status dc")

    def test_dpush_wt_diff(self):
        tree = self.make_branch_and_tree("d", format=DummyForeignVcsDirFormat())
        
        self.build_tree_contents([("d/foo", "bar")])
        tree.add("foo")
        tree.commit("msg")

        self.run_bzr("branch d dc")
        self.build_tree_contents([("dc/foofile", "blaaaa")])
        self.run_bzr("add dc/foofile")
        self.run_bzr("commit -m msg dc")
        self.build_tree_contents([("dc/foofile", "blaaaal")])
        self.run_bzr("dpush -d dc d")
        self.assertFileEqual("blaaaal", "dc/foofile")
        self.check_output('modified:\n  foofile\n', "status dc")

    def test_diverged(self):
        tree = self.make_branch_and_tree("d", format=DummyForeignVcsDirFormat())
        
        self.build_tree(["d/foo"])
        tree.add("foo")
        tree.commit("msg")

        self.run_bzr("branch d dc")

        self.build_tree_contents([("dc/foo", "bar")])
        self.run_bzr("commit -m msg1 dc")

        self.build_tree_contents([("d/foo", "blie")])
        self.run_bzr("commit -m msg2 d")

        error = self.run_bzr("dpush -d dc d", retcode=3)[1]
        self.assertContainsRe(error, "have diverged")


