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

from bzrlib import knit, plan_merge, tests

class TestPlanMerge(tests.TestCaseWithMemoryTransport):

    def setUp(self):
        tests.TestCaseWithMemoryTransport.setUp(self)
        self.vf = knit.KnitVersionedFile('root', self.get_transport(),
                                         create=True)
        self.plan_merge_vf = plan_merge._PlanMergeVersionedfile(self.vf)

    def add_version(self, version_id, parents, text):
        self.vf.add_lines(version_id, parents, [c+'\n' for c in text])

    def add_uncommitted_version(self, version_id, parents, text):
        self.plan_merge_vf.add_lines(version_id, parents,
                                     [c+'\n' for c in text])

    def setup_plan_merge(self):
        self.add_version('A', [], 'abc')
        self.add_version('B', ['A'], 'acehg')
        self.add_version('C', ['A'], 'fabg')
        return plan_merge.PlanMerge('B', 'C', self.plan_merge_vf)

    def setup_plan_merge_uncommitted(self):
        self.add_version('A', [], 'abc')
        self.add_uncommitted_version('B:', ['A'], 'acehg')
        self.add_uncommitted_version('C:', ['A'], 'fabg')
        return plan_merge.PlanMerge('B:', 'C:', self.plan_merge_vf)

    def test_unique_lines(self):
        plan = self.setup_plan_merge()
        self.assertEqual(plan._unique_lines(
            plan._get_matching_blocks('B', 'C')),
            ([1, 2, 3], [0, 2]))

    def test_find_new(self):
        plan = self.setup_plan_merge()
        self.assertEqual(set([2, 3, 4]), plan._find_new('B'))
        self.assertEqual(set([0, 3]), plan._find_new('C'))

    def test_find_new2(self):
        self.add_version('A', [], 'abc')
        self.add_version('B', ['A'], 'abcde')
        self.add_version('C', ['A'], 'abcefg')
        self.add_version('D', ['A', 'B', 'C'], 'abcdegh')
        my_plan = plan_merge.PlanMerge('B', 'D', self.plan_merge_vf)
        self.assertEqual(set([5, 6]), my_plan._find_new('D'))
        self.assertEqual(set(), my_plan._find_new('A'))

    def test_find_new_no_ancestors(self):
        self.add_version('A', [], 'abc')
        self.add_version('B', [], 'xyz')
        my_plan = plan_merge.PlanMerge('A', 'B', self.vf)
        self.assertEqual(set([0, 1, 2]), my_plan._find_new('A'))

    def test_plan_merge(self):
        my_plan = self.setup_plan_merge()
        plan = my_plan.plan_merge()
        self.assertEqual([
                          ('new-b', 'f\n'),
                          ('unchanged', 'a\n'),
                          ('killed-b', 'c\n'),
                          ('new-a', 'e\n'),
                          ('new-a', 'h\n'),
                          ('killed-a', 'b\n'),
                          ('unchanged', 'g\n')],
                         list(plan))

    def test_plan_merge_uncommitted_files(self):
        my_plan = self.setup_plan_merge_uncommitted()
        plan = my_plan.plan_merge()
        self.assertEqual([
                          ('new-b', 'f\n'),
                          ('unchanged', 'a\n'),
                          ('killed-b', 'c\n'),
                          ('new-a', 'e\n'),
                          ('new-a', 'h\n'),
                          ('killed-a', 'b\n'),
                          ('unchanged', 'g\n')],
                         list(plan))


class TestPlanMergeVersionedfile(tests.TestCaseWithMemoryTransport):

    def setUp(self):
        tests.TestCaseWithMemoryTransport.setUp(self)
        self.vf = knit.KnitVersionedFile('root', self.get_transport(),
                                         create=True)
        self.plan_merge_vf = plan_merge._PlanMergeVersionedfile(self.vf)

    def test_add_lines(self):
        self.plan_merge_vf.add_lines('a:', [], [])
        self.assertRaises(ValueError, self.plan_merge_vf.add_lines, 'a', [],
                          [])
        self.assertRaises(ValueError, self.plan_merge_vf.add_lines, 'a:', None,
                          [])
        self.assertRaises(ValueError, self.plan_merge_vf.add_lines, 'a:', [],
                          None)

    def test_ancestry(self):
        self.vf.add_lines('A', [], [])
        self.vf.add_lines('B', ['A'], [])
        self.plan_merge_vf.add_lines('C:', ['B'], [])
        self.plan_merge_vf.add_lines('D:', ['C:'], [])
        self.assertEqual(set(['A', 'B', 'C:', 'D:']),
            self.plan_merge_vf.get_ancestry('D:'))
