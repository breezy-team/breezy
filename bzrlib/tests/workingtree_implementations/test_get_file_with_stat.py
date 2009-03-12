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

"""Test that all WorkingTree's implement get_file_with_stat."""

import os

from bzrlib.tests.workingtree_implementations import TestCaseWithWorkingTree


class TestGetFileWithStat(TestCaseWithWorkingTree):

    def test_get_file_with_stat_id_only(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['foo'])
        tree.add(['foo'], ['foo-id'])
        tree.lock_read()
        self.addCleanup(tree.unlock)
        file_obj, statvalue = tree.get_file_with_stat('foo-id')
        if statvalue is not None:
            expected = os.lstat('foo')
            self.assertEqualStat(expected, statvalue)
        self.assertEqual(["contents of foo\n"], file_obj.readlines())

    def test_get_file_with_stat_id_and_path(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['foo'])
        tree.add(['foo'], ['foo-id'])
        tree.lock_read()
        self.addCleanup(tree.unlock)
        file_obj, statvalue = tree.get_file_with_stat('foo-id', 'foo')
        expected = os.lstat('foo')
        if statvalue is not None:
            expected = os.lstat('foo')
            self.assertEqualStat(expected, statvalue)
        self.assertEqual(["contents of foo\n"], file_obj.readlines())
