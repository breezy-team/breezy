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

"""Tests for interface conformance of 'workingtree.put_mkdir'"""

from breezy.tests.per_workingtree import TestCaseWithWorkingTree

from breezy.workingtree import SettingFileIdUnsupported


class TestMkdir(TestCaseWithWorkingTree):

    def test_mkdir_no_id(self):
        t = self.make_branch_and_tree('t1')
        t.lock_write()
        self.addCleanup(t.unlock)
        file_id = t.mkdir('path')
        self.assertEqual('directory', t.kind('path'))

    def test_mkdir_with_id(self):
        t = self.make_branch_and_tree('t1')
        t.lock_write()
        self.addCleanup(t.unlock)
        if not t.supports_setting_file_ids():
            self.assertRaises(
                (SettingFileIdUnsupported, TypeError),
                t.mkdir, 'path', b'my-id')
        else:
            file_id = t.mkdir('path', b'my-id')
            self.assertEqual(b'my-id', file_id)
            self.assertEqual('directory', t.kind('path'))
