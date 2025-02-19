# Copyright (C) 2006 Canonical Ltd
# Authors:  Robert Collins <robert.collins@canonical.com>
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

from breezy.osutils import basename
from breezy.tests.per_workingtree import TestCaseWithWorkingTree


class TestIsControlFilename(TestCaseWithWorkingTree):
    def validate_tree_is_controlfilename(self, tree):
        """Check that 'tree' obeys the contract for is_control_filename."""
        bzrdirname = basename(tree.controldir.transport.base[:-1])
        self.assertTrue(tree.is_control_filename(bzrdirname))
        self.assertTrue(tree.is_control_filename(bzrdirname + "/subdir"))
        self.assertFalse(tree.is_control_filename("dir/" + bzrdirname))
        self.assertFalse(tree.is_control_filename("dir/" + bzrdirname + "/sub"))

    def test_dotbzr_is_control_in_cwd(self):
        tree = self.make_branch_and_tree(".")
        self.validate_tree_is_controlfilename(tree)

    def test_dotbzr_is_control_in_subdir(self):
        tree = self.make_branch_and_tree("subdir")
        self.validate_tree_is_controlfilename(tree)
