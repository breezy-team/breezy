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

"""Test that all Tree's implement .annotate_iter()"""

from bzrlib.tests.per_tree import TestCaseWithTree


class TestAnnotate(TestCaseWithTree):

    def get_simple_tree(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree_contents([('tree/one', 'first\ncontent\n')])
        tree.add(['one'], ['one-id'])
        tree.commit('one', rev_id='one')
        self.build_tree_contents([('tree/one', 'second\ncontent\n')])
        tree.commit('two', rev_id='two')
        return self._convert_tree(tree)

    def get_tree_with_ghost(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree_contents([('tree/one', 'first\ncontent\n')])
        tree.add(['one'], ['one-id'])
        tree.commit('one', rev_id='one')
        tree.set_parent_ids(['one', 'ghost-one'])
        self.build_tree_contents([('tree/one', 'second\ncontent\n')])
        tree.commit('two', rev_id='two')
        return self._convert_tree(tree)

    def test_annotate_simple(self):
        tree = self.get_simple_tree()
        tree.lock_read()
        self.addCleanup(tree.unlock)
        self.assertEqual([('two', 'second\n'), ('one', 'content\n')],
                         list(tree.annotate_iter('one-id')))

    def test_annotate_with_ghost(self):
        tree = self.get_tree_with_ghost()
        tree.lock_read()
        self.addCleanup(tree.unlock)
        self.assertEqual([('two', 'second\n'), ('one', 'content\n')],
                         list(tree.annotate_iter('one-id')))
