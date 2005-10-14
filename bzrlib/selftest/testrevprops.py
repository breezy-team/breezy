# (C) 2005 Canonical

"""Tests for revision properties."""

from bzrlib.branch import Branch
from bzrlib.selftest import TestCaseInTempDir

class TestRevProps(TestCaseInTempDir):
    def test_simple_revprops(self):
        """Simple revision properties"""
        b = Branch.initialize('.')
        props = dict(flavor='choc-mint', 
                     condiment='chilli')
        b.commit(message='initial null commit', 
                 revprops=props,
                 allow_pointless=True,
                 rev_id='test@user-1')
        rev = b.get_revision('test@user-1')
        self.assertTrue('flavor' in rev.properties)
        self.assertEquals(rev.properties['flavor'], 'choc-mint')
        self.assertEquals(rev.properties['condiment'], 'chilli')
        self.assertEquals(sorted(rev.properties.items()),
                          [('condiment', 'chilli'),
                           ('flavor', 'choc-mint')])

        # TODO: try properties with newlines and indenting

        # TODO: property names with newlines are disallowed

        # TODO: Can't add non-string properties

        # TODO: Properties are retrieved correctly

