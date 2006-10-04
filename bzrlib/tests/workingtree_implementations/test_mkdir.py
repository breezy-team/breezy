# (C) 2006 Canonical Ltd
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Tests for interface conformance of 'workingtree.put_mkdir'"""

from bzrlib.tests.workingtree_implementations import TestCaseWithWorkingTree


class TestMkdir(TestCaseWithWorkingTree):

    def test_mkdir_no_id(self):
        t = self.make_branch_and_tree('t1')
        file_id = t.mkdir('path')
        self.assertEqual('directory', t.kind(file_id))

    def test_mkdir_with_id(self):
        t = self.make_branch_and_tree('t1')
        file_id = t.mkdir('path', 'my-id')
        self.assertEqual('my-id', file_id)
        self.assertEqual('directory', t.kind(file_id))
