from bzrlib.tests import TestCase, TestCaseWithTransport
from bzrlib.revision import Revision
from bzrlib.plugins.stats import sort_by_committer, collapse_by_person


class TestCommitterStats(TestCaseWithTransport):

    def test_simple(self):
        wt = self.make_branch_and_tree('.')
        wt.commit(message='1', committer='Fero <fero@example.com>', rev_id='1')
        wt.commit(message='2', committer='Fero <fero@example.com>', rev_id='2')
        wt.commit(message='3', committer='Jano <jano@example.com>', rev_id='3')
        wt.commit(message='4', committer='Jano <jano@example.com>', author='Vinco <vinco@example.com>', rev_id='4')
        wt.commit(message='5', committer='Ferko <fero@example.com>', rev_id='5')
        committers = sort_by_committer(wt.branch.repository, ['1', '2', '3', '4', '5'])
        self.assertEquals(3, len(committers[('fero@example.com', None)]))
        self.assertEquals(1, len(committers[('jano@example.com', None)]))
        self.assertEquals(1, len(committers[('vinco@example.com', None)]))

    def test_empty_email(self):
        wt = self.make_branch_and_tree('.')
        wt.commit(message='1', committer='Fero', rev_id='1')
        wt.commit(message='2', committer='Fero', rev_id='2')
        wt.commit(message='3', committer='Jano', rev_id='3')
        committers = sort_by_committer(wt.branch.repository, ['1', '2', '3'])
        self.assertEquals(2, len(committers[('', 'Fero')]))
        self.assertEquals(1, len(committers[('', 'Jano')]))


class TestCollapseByPerson(TestCase):

    def test_no_conflicts(self):
        data = {
            ('foo@example.com', None): [Revision('1', {}, committer='Foo <foo@example.com>')],
            ('bar@example.com', None): [Revision('2', {}, committer='Bar <bar@example.com>'),
                                        Revision('3', {}, committer='Bar <bar@example.com>')],
        }
        info = collapse_by_person(data)
        self.assertEquals(2, info[0][0])
        self.assertEquals({('bar@example.com', None): 2}, info[0][2])
        self.assertEquals({'Bar': 2}, info[0][3])

    def test_different_email(self):
        data = {
            ('foo@example.com', None): [Revision('1', {}, committer='Foo <foo@example.com>')],
            ('bar@example.com', None): [Revision('2', {}, committer='Foo <bar@example.com>'),
                                        Revision('3', {}, committer='Foo <bar@example.com>')],
        }
        info = collapse_by_person(data)
        self.assertEquals(3, info[0][0])
        self.assertEquals({('foo@example.com', None): 1, ('bar@example.com', None): 2}, info[0][2])
        self.assertEquals({'Foo': 3}, info[0][3])

    def test_different_name(self):
        data = {
            ('foo@example.com', None): [Revision('1', {}, committer='Foo <foo@example.com>'),
                                        Revision('2', {}, committer='Bar <foo@example.com>'),
                                        Revision('3', {}, committer='Bar <foo@example.com>')],
        }
        info = collapse_by_person(data)
        self.assertEquals(3, info[0][0])
        self.assertEquals({('foo@example.com', None): 3}, info[0][2])
        self.assertEquals({'Foo': 1, 'Bar': 2}, info[0][3])
