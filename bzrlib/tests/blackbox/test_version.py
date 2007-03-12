"""Black-box tests for bzr version."""

import bzrlib
from bzrlib.tests.blackbox import ExternalBase

class TestVersion(ExternalBase):
    
    def test_version(self):
        out = self.run_bzr("version")[0]
        self.assertTrue(len(out) > 0)
        self.assertEquals(1,out.count(bzrlib.__version__))
        self.assertEquals(1,out.count("Using python interpreter:"))
        self.assertEquals(1,out.count("Using python standard library:"))
        self.assertEquals(1,out.count("Using bzrlib:"))
        self.assertEquals(1,out.count("Using bazaar configuration:"))
