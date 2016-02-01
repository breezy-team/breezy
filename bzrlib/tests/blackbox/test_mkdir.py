# Copyright (C) 2011, 2016 Canonical Ltd
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

import os
from bzrlib import tests


class TestMkdir(tests.TestCaseWithTransport):

    def test_mkdir(self):
        tree = self.make_branch_and_tree('.')
        self.run_bzr(['mkdir', 'somedir'])
        self.assertEqual(tree.kind(tree.path2id('somedir')), "directory")

    def test_mkdir_multi(self):
        tree = self.make_branch_and_tree('.')
        self.run_bzr(['mkdir', 'somedir', 'anotherdir'])
        self.assertEqual(tree.kind(tree.path2id('somedir')), "directory")
        self.assertEqual(tree.kind(tree.path2id('anotherdir')), "directory")

    def test_mkdir_parents(self):
        tree = self.make_branch_and_tree('.')
        self.run_bzr(['mkdir', '-p', 'somedir/foo'])
        self.assertEqual(tree.kind(tree.path2id('somedir/foo')), "directory")

    def test_mkdir_parents_existing_versioned_dir(self):
        tree = self.make_branch_and_tree('.')
        tree.mkdir('somedir')
        self.assertEqual(tree.kind(tree.path2id('somedir')), "directory")
        self.run_bzr(['mkdir', '-p', 'somedir'])

    def test_mkdir_parents_existing_unversioned_dir(self):
        tree = self.make_branch_and_tree('.')
        os.mkdir('somedir')
        self.run_bzr(['mkdir', '-p', 'somedir'])
        self.assertEqual(tree.kind(tree.path2id('somedir')), "directory")

    def test_mkdir_parents_with_unversioned_parent(self):
        tree = self.make_branch_and_tree('.')
        os.mkdir('somedir')
        self.run_bzr(['mkdir', '-p', 'somedir/foo'])
        self.assertEqual(tree.kind(tree.path2id('somedir/foo')), "directory")
