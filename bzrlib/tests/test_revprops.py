# (C) 2005 Canonical

"""Tests for revision properties."""

from bzrlib.tests import TestCaseWithTransport

class TestRevProps(TestCaseWithTransport):

    def test_simple_revprops(self):
        """Simple revision properties"""
        wt = self.make_branch_and_tree('.')
        b = wt.branch
        b.nick = 'Nicholas'
        props = dict(flavor='choc-mint',
                     condiment='orange\n  mint\n\tcandy',
                     empty='',
                     non_ascii=u'\xb5')
        wt.commit(message='initial null commit', 
                 revprops=props,
                 allow_pointless=True,
                 rev_id='test@user-1')
        rev = b.repository.get_revision('test@user-1')
        self.assertTrue('flavor' in rev.properties)
        self.assertEquals(rev.properties['flavor'], 'choc-mint')
        self.assertEquals([('branch-nick', 'Nicholas'), 
                           ('condiment', 'orange\n  mint\n\tcandy'),
                           ('empty', ''),
                           ('flavor', 'choc-mint'),
                           ('non_ascii', u'\xb5'),
                          ], sorted(rev.properties.items()))

    def test_invalid_revprops(self):
        """Invalid revision properties"""
        wt = self.make_branch_and_tree('.')
        b = wt.branch
        self.assertRaises(ValueError,
                          wt.commit, 
                          message='invalid',
                          revprops={'what a silly property': 'fine'})
        self.assertRaises(ValueError,
                          wt.commit, 
                          message='invalid',
                          revprops=dict(number=13))
