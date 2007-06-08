# Copyright (C) 2007 Canonical Ltd
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

from bzrlib.revision import NULL_REVISION
from bzrlib.tests import TestCaseWithMemoryTransport

ancestry_1 = {'rev1': [NULL_REVISION], 'rev2a': ['rev1'], 'rev2b': ['rev1'],
              'rev3': ['rev2a'], 'rev4': ['rev3', 'rev2b']}
ancestry_2 = {'rev1a': [NULL_REVISION], 'rev2a': ['rev1a'],
              'rev1b': [NULL_REVISION], 'rev3a': ['rev2a'], 'rev4a': ['rev3a']}

criss_cross = {'rev1': [NULL_REVISION], 'rev2a': ['rev1'], 'rev2b': ['rev1'],
               'rev3a': ['rev2a', 'rev2b'], 'rev3b': ['rev2b', 'rev2a']}

criss_cross2 = {'rev1a': [NULL_REVISION], 'rev1b': [NULL_REVISION],
                'rev2a': ['rev1a', 'rev1b'], 'rev2b': ['rev1b', 'rev1a']}

mainline = {'rev1': [NULL_REVISION], 'rev2a': ['rev1', 'rev2b'],
            'rev2b': ['rev1']}

feature_branch = {'rev1': [NULL_REVISION],
                  'rev2b': ['rev1'], 'rev3b': ['rev2b']}

history_shortcut = {'rev1': [NULL_REVISION], 'rev2a': ['rev1'],
                    'rev2b': ['rev1'], 'rev2c': ['rev1'],
                    'rev3a': ['rev2a', 'rev2b'], 'rev3b': ['rev2b', 'rev2c']}

class TestGraphWalker(TestCaseWithMemoryTransport):

    def make_walker(self, ancestors):
        tree = self.prepare_memory_tree('.')
        self.build_ancestry(tree, ancestors)
        tree.unlock()
        return tree.branch.repository.get_graph_walker()

    def prepare_memory_tree(self, location):
        tree = self.make_branch_and_memory_tree(location)
        tree.lock_write()
        tree.add('.')
        return tree

    def build_ancestry(self, tree, ancestors):
        pending = [NULL_REVISION]
        descendants = {}
        for descendant, parents in ancestors.iteritems():
            for parent in parents:
                descendants.setdefault(parent, []).append(descendant)
        while len(pending) > 0:
            cur_node = pending.pop()
            for descendant in descendants.get(cur_node, []):
                if tree.branch.repository.has_revision(descendant):
                    continue
                parents = [p for p in ancestors[descendant] if p is not
                           NULL_REVISION]
                if len([p for p in parents if not
                    tree.branch.repository.has_revision(p)]) > 0:
                    continue
                tree.set_parent_ids(parents)
                if len(parents) > 0:
                    left_parent = parents[0]
                else:
                    left_parent = NULL_REVISION
                tree.branch.set_last_revision_info(
                    len(tree.branch._lefthand_history(left_parent)),
                    left_parent)
                tree.commit(descendant, rev_id=descendant)
                pending.append(descendant)

    def test_lca(self):
        """Test finding distinct common ancestor.

        ancestry_1 should always have a single common ancestor
        """
        graph_walker = self.make_walker(ancestry_1)
        self.assertEqual(set([NULL_REVISION]),
                         graph_walker.find_lca(NULL_REVISION,
                                                     NULL_REVISION))
        self.assertEqual(set([NULL_REVISION]),
                         graph_walker.find_lca(NULL_REVISION,
                                                     'rev1'))
        self.assertEqual(set(['rev1']),
                         graph_walker.find_lca('rev1', 'rev1'))
        self.assertEqual(set(['rev1']),
                         graph_walker.find_lca('rev2a', 'rev2b'))

    def test_lca_criss_cross(self):
        graph_walker = self.make_walker(criss_cross)
        self.assertEqual(set(['rev2a', 'rev2b']),
                         graph_walker.find_lca('rev3a', 'rev3b'))
        self.assertEqual(set(['rev2b']),
                         graph_walker.find_lca('rev3a', 'rev3b',
                                                     'rev2b'))

    def test_lca_shortcut(self):
        graph_walker = self.make_walker(history_shortcut)
        self.assertEqual(set(['rev2b']),
                         graph_walker.find_lca('rev3a', 'rev3b'))

    def test_recursive_unique_lca(self):
        """Test finding a unique distinct common ancestor.

        ancestry_1 should always have a single common ancestor
        """
        graph_walker = self.make_walker(ancestry_1)
        self.assertEqual(NULL_REVISION,
                         graph_walker.find_unique_lca(NULL_REVISION,
                                                      NULL_REVISION))
        self.assertEqual(NULL_REVISION,
                         graph_walker.find_unique_lca(NULL_REVISION,
                                                      'rev1'))
        self.assertEqual('rev1', graph_walker.find_unique_lca('rev1',
                                                              'rev1'))
        self.assertEqual('rev1', graph_walker.find_unique_lca('rev2a',
                                                              'rev2b'))

    def test_lca_criss_cross(self):
        graph_walker = self.make_walker(criss_cross)
        self.assertEqual(set(['rev2a', 'rev2b']),
                         graph_walker.find_lca('rev3a', 'rev3b'))
        self.assertEqual(set(['rev2b']),
                         graph_walker.find_lca('rev3a', 'rev3b',
                                                      'rev2b'))

    def test_unique_lca_criss_cross(self):
        """Ensure we don't pick non-unique lcas in a criss-cross"""
        graph_walker = self.make_walker(criss_cross)
        self.assertEqual('rev1',
                         graph_walker.find_unique_lca('rev3a', 'rev3b'))

    def test_unique_lca_null_revision(self):
        """Ensure we pick NULL_REVISION when necessary"""
        graph_walker = self.make_walker(criss_cross2)
        self.assertEqual('rev1b',
                         graph_walker.find_unique_lca('rev2a', 'rev1b'))
        self.assertEqual(NULL_REVISION,
                         graph_walker.find_unique_lca('rev2a', 'rev2b'))

    def test_unique_lca_null_revision2(self):
        """Ensure we pick NULL_REVISION when necessary"""
        graph_walker = self.make_walker(ancestry_2)
        self.assertEqual(NULL_REVISION,
                         graph_walker.find_unique_lca('rev4a', 'rev1b'))

    def test_common_ancestor_two_repos(self):
        """Ensure we do unique_lca using data from two repos"""
        mainline_tree = self.prepare_memory_tree('mainline')
        self.build_ancestry(mainline_tree, mainline)
        mainline_tree.unlock()

        # This is cheating, because the revisions in the graph are actually
        # different revisions, despite having the same revision-id.
        feature_tree = self.prepare_memory_tree('feature')
        self.build_ancestry(feature_tree, feature_branch)
        feature_tree.unlock()
        graph_walker = mainline_tree.branch.repository.get_graph_walker(
            feature_tree.branch.repository)
        self.assertEqual('rev2b', graph_walker.find_unique_lca('rev2a',
                         'rev3b'))
