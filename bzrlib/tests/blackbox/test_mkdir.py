# Copyright (C) 2011 Canonical Ltd
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


"""Black-box tests for bzr mkdir.
"""

from bzrlib import tests


class TestMkdir(tests.TestCaseWithTransport):

    def test_mkdir(self):
        tree = self.make_branch_and_tree('.')
        self.run_bzr(['mkdir', 'somedir'])

        self.assertEquals(tree.kind(tree.path2id('somedir')), "directory")

    def test_mkdir_recursive(self):
        tree = self.make_branch_and_tree('.')
        self.run_bzr(['mkdir', '-p', 'somedir/foo'])

        self.assertEquals(tree.kind(tree.path2id('somedir/foo')), "directory")
