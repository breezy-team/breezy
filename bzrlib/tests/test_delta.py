# Copyright (C) 2006 by Canonical Development Ltd
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

"""test the functions in bzrlib/delta.py"""

from bzrlib import delta, revision, transform
from bzrlib.tests import TestCaseWithTransport


class TestCompareTrees(TestCaseWithTransport):
    
    def setUp(self):
        TestCaseWithTransport.setUp(self)
        self.tree = self.make_branch_and_tree('tree')
        files = ['a', 'b/', 'b/c']
        self.build_tree(['tree/' + f for f in files])
        self.tree.add(files, ['a-id', 'b-id', 'c-id'])
        self.tree.commit('initial tree')

    def test_subset_file(self):
        empty_tree = self.tree.branch.repository.revision_tree(
                        revision.NULL_REVISION)

        d = delta.compare_trees(empty_tree, self.tree.basis_tree(),
                                specific_files=['a'])
        self.assertEqual([('a', 'a-id', 'file')], d.added)
        self.assertEqual([], d.removed)
        self.assertEqual([], d.renamed)
        self.assertEqual([], d.modified)

    def test_subset_multiple(self):
        empty_tree = self.tree.branch.repository.revision_tree(
                        revision.NULL_REVISION)

        d = delta.compare_trees(empty_tree, self.tree,
                                specific_files=['a', 'b/c'])
        self.assertEqual([('a', 'a-id', 'file'),
                          ('b/c', 'c-id', 'file'),
                         ], d.added)
        self.assertEqual([], d.removed)
        self.assertEqual([], d.renamed)
        self.assertEqual([], d.modified)

    def test_subset_dir(self):
        """Restricting to a directory checks the dir, and all children."""
        empty_tree = self.tree.branch.repository.revision_tree(
                        revision.NULL_REVISION)

        d = delta.compare_trees(empty_tree, self.tree,
                                specific_files=['b'])
        self.assertEqual([('b', 'b-id', 'directory'),
                          ('b/c', 'c-id', 'file'),
                         ], d.added)
        self.assertEqual([], d.removed)
        self.assertEqual([], d.renamed)
        self.assertEqual([], d.modified)

    def test_unknown(self):
        self.build_tree(['tree/unknown'])
        # Unknowns are not reported by compare_trees
        d = delta.compare_trees(self.tree.basis_tree(), self.tree)
        self.assertEqual([], d.added)
        self.assertEqual([], d.removed)
        self.assertEqual([], d.renamed)
        self.assertEqual([], d.modified)

    def test_unknown_specific_file(self):
        self.build_tree(['tree/unknown'])
        empty_tree = self.tree.branch.repository.revision_tree(
                        revision.NULL_REVISION)
                        
        # If a specific_files list is present, even if none of the
        # files are versioned, only paths that are present in the list
        # should be compared
        d = delta.compare_trees(empty_tree, self.tree,
                                specific_files=['unknown'])
        self.assertEqual([], d.added)
        self.assertEqual([], d.removed)
        self.assertEqual([], d.renamed)
        self.assertEqual([], d.modified)
