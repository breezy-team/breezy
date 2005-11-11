# (C) 2005 Canonical

"""Tests for revision properties."""

from bzrlib.branch import Branch
from bzrlib.selftest import TestCaseInTempDir

class TestRevProps(TestCaseInTempDir):
    def test_simple_revprops(self):
        """Simple revision properties"""
        b = Branch.initialize('.')
        b.nick = 'Nicholas'
        props = dict(flavor='choc-mint', 
                     condiment='orange\n  mint\n\tcandy')
        b.commit(message='initial null commit', 
                 revprops=props,
                 allow_pointless=True,
                 rev_id='test@user-1')
        rev = b.storage.get_revision('test@user-1')
        self.assertTrue('flavor' in rev.properties)
        self.assertEquals(rev.properties['flavor'], 'choc-mint')
        self.assertEquals(sorted(rev.properties.items()),
                          [('branch-nick', 'Nicholas'), 
                           ('condiment', 'orange\n  mint\n\tcandy'),
                           ('flavor', 'choc-mint')])

    def test_invalid_revprops(self):
        """Invalid revision properties"""
        b = Branch.initialize('.')
        self.assertRaises(ValueError,
                          b.commit, 
                          message='invalid',
                          revprops={'what a silly property': 'fine'})
        self.assertRaises(ValueError,
                          b.commit, 
                          message='invalid',
                          revprops=dict(number=13))
