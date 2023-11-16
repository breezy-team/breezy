# Copyright (C) 2008 Aaron Bentley
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
#

"""Tests for the 'brz link-tree' command."""

import os

from ... import tests
from ..features import HardlinkFeature


class TestLinkTreeCommand(tests.TestCaseWithTransport):
    def setUp(self):
        tests.TestCaseWithTransport.setUp(self)
        self.requireFeature(HardlinkFeature(self.test_dir))
        self.parent_tree = self.make_branch_and_tree("parent")
        self.parent_tree.lock_write()
        self.addCleanup(self.parent_tree.unlock)
        self.build_tree_contents([("parent/foo", b"bar")])
        self.parent_tree.add("foo", ids=b"foo-id")
        self.parent_tree.commit("added foo")
        child_controldir = self.parent_tree.controldir.sprout("child")
        self.child_tree = child_controldir.open_workingtree()

    def hardlinked(self):
        parent_stat = os.lstat(self.parent_tree.abspath("foo"))
        child_stat = os.lstat(self.child_tree.abspath("foo"))
        return parent_stat.st_ino == child_stat.st_ino

    def test_link_tree(self):
        """Ensure the command works as intended."""
        os.chdir("child")
        self.parent_tree.unlock()
        self.run_bzr("link-tree ../parent")
        self.assertTrue(self.hardlinked())
        # want teh addCleanup to work properly
        self.parent_tree.lock_write()
