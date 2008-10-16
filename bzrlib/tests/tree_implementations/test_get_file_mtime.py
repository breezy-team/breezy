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

"""Test that all Tree's implement get_file_mtime"""

import time

from bzrlib.tests.tree_implementations import TestCaseWithTree


class TestGetFileMTime(TestCaseWithTree):

    def get_basic_tree(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/one'])
        tree.add(['one'], ['one-id'])
        return self._convert_tree(tree)

    def test_get_file_mtime(self):
        now = time.time()
        tree = self.get_basic_tree()
        tree.lock_read()
        self.addCleanup(tree.unlock)
        # Committed trees return the time of the commit that last changed the
        # file, working trees return the on-disk time.
        mtime_file_id = tree.get_file_mtime(file_id='one-id')
        self.assertIsInstance(mtime_file_id, (float, int))
        self.failUnless(now - 5 < mtime_file_id < now + 5)
        mtime_path = tree.get_file_mtime(file_id='one-id', path='one')
        self.assertEqual(mtime_file_id, mtime_path)
