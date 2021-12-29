# Copyright (C) 2010 Canonical Ltd
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

from breezy.tests import (
    per_tree,
    )
from breezy.tests.features import (
    SymlinkFeature,
    )


class TestIsExecutable(per_tree.TestCaseWithTree):

    def test_is_executable_dir(self):
        tree = self.get_tree_with_subdirs_and_all_supported_content_types(
            False)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        self.assertEqual(False, tree.is_executable('1top-dir'))

    def test_is_executable_symlink(self):
        self.requireFeature(SymlinkFeature(self.test_dir))
        tree = self.get_tree_with_subdirs_and_all_content_types()
        tree.lock_read()
        self.addCleanup(tree.unlock)
        self.assertEqual(False, tree.is_executable('symlink'))
