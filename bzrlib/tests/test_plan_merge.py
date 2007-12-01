from bzrlib import knit, plan_merge, tests

class TestPlanMerge(tests.TestCaseWithMemoryTransport):

    def setUp(self):
        tests.TestCaseWithMemoryTransport.setUp(self)
        self.vf = knit.KnitVersionedFile('root', self.get_transport(),
                                         create=True)

    def add_version(self, version_id, parents, text):
        self.vf.add_lines(version_id, parents, [c+'\n' for c in text])

    def setup_plan_merge(self):
        self.add_version('A', [], 'abc')
        self.add_version('B', ['A'], 'acehg')
        self.add_version('C', ['A'], 'fabg')
        return plan_merge.PlanMerge('B', 'C', self.vf)

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
        my_plan = plan_merge.PlanMerge('B', 'D', self.vf)
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
