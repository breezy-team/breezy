#! /usr/bin/python

from bzrlib.branch import ScratchBranch
from bzrlib.errors import NotBranchError
from unittest import TestCase
import os, unittest

def Reporter(TestResult):
    def startTest(self, test):
        super(Reporter, self).startTest(test)
        print test.id(),

    def stopTest(self, test):
        print

class BranchPathTestCase(TestCase):
    """test for branch path lookups

    Branch.relpath and bzrlib.branch._relpath do a simple but subtle
    job: given a path (either relative to cwd or absolute), work out
    if it is inside a branch and return the path relative to the base.
    """
    
    def runTest(self):
        from bzrlib.branch import _relpath
        import tempfile, shutil
        
        savedir = os.getcwdu()
        dtmp = tempfile.mkdtemp()

        def rp(p):
            return _relpath(dtmp, p)
        
        try:
            # check paths inside dtmp while standing outside it
            self.assertEqual(rp(os.path.join(dtmp, 'foo')), 'foo')

            # root = nothing
            self.assertEqual(rp(dtmp), '')

            self.assertRaises(NotBranchError,
                              rp,
                              '/etc')

            # now some near-miss operations -- note that
            # os.path.commonprefix gets these wrong!
            self.assertRaises(NotBranchError,
                              rp,
                              dtmp.rstrip('\\/') + '2')

            self.assertRaises(NotBranchError,
                              rp,
                              dtmp.rstrip('\\/') + '2/foo')

            # now operations based on relpath of files in current
            # directory, or nearby
            os.chdir(dtmp)

            self.assertEqual(rp('foo/bar/quux'), 'foo/bar/quux')

            self.assertEqual(rp('foo'), 'foo')

            self.assertEqual(rp('./foo'), 'foo')

            self.assertEqual(rp(os.path.abspath('foo')), 'foo')

            self.assertRaises(NotBranchError,
                              rp, '../foo')

        finally:
            os.chdir(savedir)
            shutil.rmtree(dtmp)

                              
if __name__ == '__main__':
    unittest.main()
    
