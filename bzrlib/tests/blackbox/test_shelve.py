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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

import os

from bzrlib import shelf
from bzrlib.tests import TestCaseWithTransport

class TestShelveList(TestCaseWithTransport):

    def test_no_shelved_changes(self):
        tree = self.make_branch_and_tree('.')
        err = self.run_bzr('shelve --list')[1]
        self.assertEqual('No shelved changes.\n', err)

    def make_creator(self, tree):
        creator = shelf.ShelfCreator(tree, tree.basis_tree(), [])
        self.addCleanup(creator.finalize)
        return creator

    def test_shelve_one(self):
        tree = self.make_branch_and_tree('.')
        creator = self.make_creator(tree)
        shelf_id = tree.get_shelf_manager().shelve_changes(creator, 'Foo')
        out, err = self.run_bzr('shelve --list', retcode=1)
        self.assertEqual('', err)
        self.assertEqual('  1: Foo\n', out)

    def test_shelve_no_message(self):
        tree = self.make_branch_and_tree('.')
        creator = self.make_creator(tree)
        shelf_id = tree.get_shelf_manager().shelve_changes(creator)
        out, err = self.run_bzr('shelve --list', retcode=1)
        self.assertEqual('', err)
        self.assertEqual('  1: <no message>\n', out)

    def test_shelf_order(self):
        tree = self.make_branch_and_tree('.')
        creator = self.make_creator(tree)
        tree.get_shelf_manager().shelve_changes(creator, 'Foo')
        creator = self.make_creator(tree)
        tree.get_shelf_manager().shelve_changes(creator, 'Bar')
        out, err = self.run_bzr('shelve --list', retcode=1)
        self.assertEqual('', err)
        self.assertEqual('  2: Bar\n  1: Foo\n', out)

    def test_shelve_destroy(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['file'])
        tree.add('file')
        self.run_bzr('shelve --all --destroy')
        self.failIfExists('file')
        self.assertIs(None, tree.get_shelf_manager().last_shelf())


class TestShelveRelpath(TestCaseWithTransport):

    def test_shelve_in_subdir(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/file', 'tree/dir/'])
        tree.add('file')
        os.chdir('tree/dir')
        self.run_bzr('shelve --all ../file')
