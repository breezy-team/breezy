# Copyright (C) 2005 Canonical Ltd
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

import os


from bzrlib.builtins import merge
from bzrlib.missing import find_unmerged, iter_log_data
from bzrlib.tests import TestCaseWithTransport
from bzrlib.workingtree import WorkingTree


class TestMissing(TestCaseWithTransport):

    def test_find_unmerged(self):
        original_tree = self.make_branch_and_tree('original')
        original = original_tree.branch
        puller_tree = self.make_branch_and_tree('puller')
        puller = puller_tree.branch
        merger_tree = self.make_branch_and_tree('merger')
        merger = merger_tree.branch
        self.assertEqual(find_unmerged(original, puller), ([], []))
        original_tree.commit('a', rev_id='a')
        self.assertEqual(find_unmerged(original, puller), ([(1, u'a')], []))
        puller_tree.pull(original)
        self.assertEqual(find_unmerged(original, puller), ([], []))
        merger_tree.pull(original)
        original_tree.commit('b', rev_id='b')
        original_tree.commit('c', rev_id='c')
        self.assertEqual(find_unmerged(original, puller), ([(2, u'b'), 
                                                            (3, u'c')], []))

        puller_tree.pull(original)
        self.assertEqual(find_unmerged(original, puller), ([], []))
        self.assertEqual(find_unmerged(original, merger), ([(2, u'b'), 
                                                            (3, u'c')], []))
        merge(['original', -1], [None, None], this_dir='merger')
        self.assertEqual(find_unmerged(original, merger), ([(2, u'b'), 
                                                            (3, u'c')], []))
        merger_tree.commit('d', rev_id='d')
        self.assertEqual(find_unmerged(original, merger), ([], [(2, 'd')]))

    def test_iter_log_data(self):
        base_tree = self.make_branch_and_tree('base')
        self.build_tree(['base/a'])
        base_tree.add(['a'], ['a-id'])
        base_tree.commit('add a', rev_id='b-1')

        child_tree = base_tree.bzrdir.sprout('child').open_workingtree()

        self.build_tree(['child/b'])
        child_tree.add(['b'], ['b-id'])
        child_tree.commit('adding b', rev_id='c-2')

        child_tree.remove(['a'])
        child_tree.commit('removing a', rev_id='c-3')

        self.build_tree_contents([('child/b', 'new contents for b\n')])
        child_tree.commit('modifying b', rev_id='c-4')

        child_tree.rename_one('b', 'c')
        child_tree.commit('rename b=>c', rev_id='c-5')

        base_extra, child_extra = find_unmerged(base_tree.branch,
                                                child_tree.branch)
        results = list(iter_log_data(base_extra, base_tree.branch.repository,
                                     verbose=True))
        self.assertEqual([], results)

        results = list(iter_log_data(child_extra, child_tree.branch.repository,
                                     verbose=True))
        self.assertEqual(4, len(results))

        r0,r1,r2,r3 = results

        self.assertEqual((2, 'c-2'), (r0[0], r0[1].revision_id))
        self.assertEqual((3, 'c-3'), (r1[0], r1[1].revision_id))
        self.assertEqual((4, 'c-4'), (r2[0], r2[1].revision_id))
        self.assertEqual((5, 'c-5'), (r3[0], r3[1].revision_id))

        delta0 = r0[2]
        self.assertNotEqual(None, delta0)
        self.assertEqual([('b', 'b-id', 'file')], delta0.added)
        self.assertEqual([], delta0.removed)
        self.assertEqual([], delta0.renamed)
        self.assertEqual([], delta0.modified)

        delta1 = r1[2]
        self.assertNotEqual(None, delta1)
        self.assertEqual([], delta1.added)
        self.assertEqual([('a', 'a-id', 'file')], delta1.removed)
        self.assertEqual([], delta1.renamed)
        self.assertEqual([], delta1.modified)

        delta2 = r2[2]
        self.assertNotEqual(None, delta2)
        self.assertEqual([], delta2.added)
        self.assertEqual([], delta2.removed)
        self.assertEqual([], delta2.renamed)
        self.assertEqual([('b', 'b-id', 'file', True, False)], delta2.modified)

        delta3 = r3[2]
        self.assertNotEqual(None, delta3)
        self.assertEqual([], delta3.added)
        self.assertEqual([], delta3.removed)
        self.assertEqual([('b', 'c', 'b-id', 'file', False, False)],
                         delta3.renamed)
        self.assertEqual([], delta3.modified)
