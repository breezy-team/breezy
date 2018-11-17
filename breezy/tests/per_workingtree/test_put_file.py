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

"""Tests for interface conformance of 'workingtree.put_file*'"""

from breezy.tests.per_workingtree import TestCaseWithWorkingTree


class TestPutFileBytesNonAtomic(TestCaseWithWorkingTree):

    def test_put_new_file(self):
        t = self.make_branch_and_tree('t1')
        t.add(['foo'], kinds=['file'])
        t.put_file_bytes_non_atomic('foo', b'barshoom')
        with t.get_file('foo') as f:
            self.assertEqual(b'barshoom', f.read())

    def test_put_existing_file(self):
        t = self.make_branch_and_tree('t1')
        t.add(['foo'], kinds=['file'])
        t.put_file_bytes_non_atomic('foo', b'first-content')
        t.put_file_bytes_non_atomic('foo', b'barshoom')
        with t.get_file('foo') as f:
            self.assertEqual(b'barshoom', f.read())
