from ...tests import TestCase, TestCaseWithTransport
from ...revision import Revision
from .cmds import get_revisions_and_committers, collapse_by_person


class TestGetRevisionsAndCommitters(TestCaseWithTransport):

    def test_simple(self):
        wt = self.make_branch_and_tree('.')
        wt.commit(message='1', committer='Fero <fero@example.com>', rev_id=b'1')
        wt.commit(message='2', committer='Fero <fero@example.com>', rev_id=b'2')
        wt.commit(message='3', committer='Jano <jano@example.com>', rev_id=b'3')
        wt.commit(message='4', committer='Jano <jano@example.com>',
                  authors=['Vinco <vinco@example.com>'], rev_id=b'4')
        wt.commit(message='5', committer='Ferko <fero@example.com>', rev_id=b'5')
        revs, committers = get_revisions_and_committers(wt.branch.repository,
                                                        [b'1', b'2', b'3', b'4', b'5'])
        fero = ('Fero', 'fero@example.com')
        jano = ('Jano', 'jano@example.com')
        vinco = ('Vinco', 'vinco@example.com')
        ferok = ('Ferko', 'fero@example.com')
        self.assertEqual({fero: fero, jano: jano, vinco: vinco, ferok: fero},
                         committers)

    def test_empty_email(self):
        wt = self.make_branch_and_tree('.')
        wt.commit(message='1', committer='Fero', rev_id=b'1')
        wt.commit(message='2', committer='Fero', rev_id=b'2')
        wt.commit(message='3', committer='Jano', rev_id=b'3')
        revs, committers = get_revisions_and_committers(wt.branch.repository,
                                                        [b'1', b'2', b'3'])
        self.assertEqual({('Fero', ''): ('Fero', ''),
                          ('Jano', ''): ('Jano', ''),
                          }, committers)

    def test_different_case(self):
        wt = self.make_branch_and_tree('.')
        wt.commit(message='1', committer='Fero', rev_id=b'1')
        wt.commit(message='2', committer='Fero', rev_id=b'2')
        wt.commit(message='3', committer='FERO', rev_id=b'3')
        revs, committers = get_revisions_and_committers(wt.branch.repository,
                                                        [b'1', b'2', b'3'])
        self.assertEqual({('Fero', ''): ('Fero', ''),
                          ('FERO', ''): ('Fero', ''),
                          }, committers)
        self.assertEquals([b'1', b'2', b'3'], sorted(
            [r.revision_id for r in revs]))


class TestCollapseByPerson(TestCase):

    def test_no_conflicts(self):
        revisions = [
            Revision('1', {}, committer='Foo <foo@example.com>'),
            Revision('2', {}, committer='Bar <bar@example.com>'),
            Revision('3', {}, committer='Bar <bar@example.com>'),
        ]
        foo = ('Foo', 'foo@example.com')
        bar = ('Bar', 'bar@example.com')
        committers = {foo: foo, bar: bar}
        info = collapse_by_person(revisions, committers)
        self.assertEquals(2, info[0][0])
        self.assertEquals({'bar@example.com': 2}, info[0][2])
        self.assertEquals({'Bar': 2}, info[0][3])

    def test_different_email(self):
        revisions = [
            Revision('1', {}, committer='Foo <foo@example.com>'),
            Revision('2', {}, committer='Foo <bar@example.com>'),
            Revision('3', {}, committer='Foo <bar@example.com>'),
        ]
        foo = ('Foo', 'foo@example.com')
        bar = ('Foo', 'bar@example.com')
        committers = {foo: foo, bar: foo}
        info = collapse_by_person(revisions, committers)
        self.assertEquals(3, info[0][0])
        self.assertEquals(
            {'foo@example.com': 1, 'bar@example.com': 2}, info[0][2])
        self.assertEquals({'Foo': 3}, info[0][3])

    def test_different_name(self):
        revisions = [
            Revision('1', {}, committer='Foo <foo@example.com>'),
            Revision('2', {}, committer='Bar <foo@example.com>'),
            Revision('3', {}, committer='Bar <foo@example.com>'),
        ]
        foo = ('Foo', 'foo@example.com')
        bar = ('Bar', 'foo@example.com')
        committers = {foo: foo, bar: foo}
        info = collapse_by_person(revisions, committers)
        self.assertEquals(3, info[0][0])
        self.assertEquals({'foo@example.com': 3}, info[0][2])
        self.assertEquals({'Foo': 1, 'Bar': 2}, info[0][3])

    def test_different_name_case(self):
        revisions = [
            Revision('1', {}, committer='Foo <foo@example.com>'),
            Revision('2', {}, committer='Foo <foo@example.com>'),
            Revision('3', {}, committer='FOO <bar@example.com>'),
        ]
        foo = ('Foo', 'foo@example.com')
        FOO = ('FOO', 'bar@example.com')
        committers = {foo: foo, FOO: foo}
        info = collapse_by_person(revisions, committers)
        self.assertEquals(3, info[0][0])
        self.assertEquals(
            {'foo@example.com': 2, 'bar@example.com': 1}, info[0][2])
        self.assertEquals({'Foo': 2, 'FOO': 1}, info[0][3])
