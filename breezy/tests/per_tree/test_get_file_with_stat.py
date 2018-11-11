# Copyright (C) 2008, 2009, 2010 Canonical Ltd
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

"""Test that all WorkingTree's implement get_file_with_stat."""

import os

from breezy.tests.per_tree import TestCaseWithTree


class TestGetFileWithStat(TestCaseWithTree):

    def test_get_file_with_stat_id_only(self):
        work_tree = self.make_branch_and_tree('.')
        self.build_tree(['foo'])
        work_tree.add(['foo'])
        tree = self._convert_tree(work_tree)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        file_obj, statvalue = tree.get_file_with_stat('foo')
        self.addCleanup(file_obj.close)
        if statvalue is not None:
            expected = os.lstat('foo')
            self.assertEqualStat(expected, statvalue)
        self.assertEqual([b"contents of foo\n"], file_obj.readlines())

    def test_get_file_with_stat_id_and_path(self):
        work_tree = self.make_branch_and_tree('.')
        self.build_tree(['foo'])
        work_tree.add(['foo'])
        tree = self._convert_tree(work_tree)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        file_obj, statvalue = tree.get_file_with_stat('foo')
        self.addCleanup(file_obj.close)
        if statvalue is not None:
            expected = os.lstat('foo')
            self.assertEqualStat(expected, statvalue)
        self.assertEqual([b"contents of foo\n"], file_obj.readlines())
