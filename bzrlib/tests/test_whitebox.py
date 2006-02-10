import os
import unittest

from bzrlib.tests import TestCaseWithTransport, TestCase
from bzrlib.branch import ScratchBranch, Branch
from bzrlib.errors import PathNotChild
from bzrlib.osutils import relpath, pathjoin, abspath, realpath


class MoreTests(TestCaseWithTransport):

    def test_relpath(self):
        """test for branch path lookups
    
        bzrlib.osutils._relpath do a simple but subtle
        job: given a path (either relative to cwd or absolute), work out
        if it is inside a branch and return the path relative to the base.
        """
        import tempfile, shutil
        
        savedir = os.getcwdu()
        dtmp = tempfile.mkdtemp()
        # On Mac OSX, /tmp actually expands to /private/tmp
        dtmp = realpath(dtmp)

        def rp(p):
            return relpath(dtmp, p)
        
        try:
            # check paths inside dtmp while standing outside it
            self.assertEqual(rp(pathjoin(dtmp, 'foo')), 'foo')

            # root = nothing
            self.assertEqual(rp(dtmp), '')

            self.assertRaises(PathNotChild,
                              rp,
                              '/etc')

            # now some near-miss operations -- note that
            # os.path.commonprefix gets these wrong!
            self.assertRaises(PathNotChild,
                              rp,
                              dtmp.rstrip('\\/') + '2')

            self.assertRaises(PathNotChild,
                              rp,
                              dtmp.rstrip('\\/') + '2/foo')

            # now operations based on relpath of files in current
            # directory, or nearby
            os.chdir(dtmp)

            self.assertEqual(rp('foo/bar/quux'), 'foo/bar/quux')

            self.assertEqual(rp('foo'), 'foo')

            self.assertEqual(rp('./foo'), 'foo')

            self.assertEqual(rp(abspath('foo')), 'foo')

            self.assertRaises(PathNotChild,
                              rp, '../foo')

        finally:
            os.chdir(savedir)
            shutil.rmtree(dtmp)
