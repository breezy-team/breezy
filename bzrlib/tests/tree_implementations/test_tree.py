# Copyright (C) 2006, 2007 Canonical Ltd
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

from bzrlib import tests
from bzrlib.tests.tree_implementations import TestCaseWithTree

class TestAnnotate(TestCaseWithTree):

    def test_annotate(self):
        work_tree = self.make_branch_and_tree('wt')
        tree = self.get_tree_no_parents_abc_content(work_tree)
        tree_revision = getattr(tree, 'get_revision_id', lambda: 'current:')()
        tree.lock_read()
        try:
            for revision, line in tree.annotate_iter('a-id'):
                self.assertEqual('contents of a\n', line)
                self.assertEqual(tree_revision, revision)
        finally:
            tree.unlock()


class TestReference(TestCaseWithTree):

    def skip_if_no_reference(self, tree):
        if not getattr(tree, 'supports_tree_reference', lambda: False)():
            raise tests.TestSkipped('Tree references not supported')

    def create_nested(self):
        work_tree = self.make_branch_and_tree('wt')
        work_tree.lock_write()
        try:
            self.skip_if_no_reference(work_tree)
            subtree = self.make_branch_and_tree('wt/subtree')
            subtree.set_root_id('sub-root')
            subtree.commit('foo', rev_id='sub-1')
            work_tree.add_reference(subtree)
        finally:
            work_tree.unlock()
        tree = self._convert_tree(work_tree)
        self.skip_if_no_reference(tree)
        return tree

    def test_get_reference_revision(self):
        tree = self.create_nested()
        tree.lock_read()
        try:
            entry = tree.inventory['sub-root']
        finally:
            tree.unlock()
        path = tree.id2path('sub-root')
        self.assertEqual('sub-1', tree.get_reference_revision(entry, path))

    def test_iter_reference_entries(self):
        tree = self.create_nested()
        tree.lock_read()
        try:
            entry = tree.inventory['sub-root']
        finally:
            tree.unlock()
        self.assertEqual([entry], [e for p, e in
                                   tree.iter_reference_entries()])

    def test_get_root_id(self):
        # trees should return some kind of root id; it can be none
        tree = self.make_branch_and_tree('tree')
        root_id = tree.get_root_id()
        if root_id is not None:
            self.assertIsInstance(root_id, str)
