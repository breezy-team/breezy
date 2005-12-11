"""Black-box tests for bzr missing.
"""

import os

from bzrlib.branch import Branch
from bzrlib.tests import TestCaseInTempDir

class TestMissing(TestCaseInTempDir):
    def test_missing(self):
        missing = "You are missing the following revisions:"

        # create a source branch
        os.mkdir('a')
        os.chdir('a')
        self.capture('init')
        open('a', 'wb').write('initial\n')
        self.capture('add a')
        self.capture('commit -m inital')

        # clone and add a differing revision
        self.capture('branch . ../b')
        os.chdir('../b')
        open('a', 'ab').write('more\n')
        self.capture('commit -m more')

        # compare a against b
        os.chdir('../a')
        lines = self.capture('missing ../b').splitlines()
        # we're missing the extra revision here
        self.assertEqual(missing, lines[0])
        self.assertEqual(8, len(lines))

        # get extra revision from b
        self.capture('merge ../b')
        self.capture('commit -m merge')

        # compare again, but now we have the 'merge' commit extra
        lines = self.capture('missing ../b').splitlines()
        self.assertEqual("You have the following extra revisions:", lines[0])
        self.assertEqual(8, len(lines))

        # relative to a, missing the 'merge' commit 
        os.chdir('../b')
        lines = self.capture('missing ../a').splitlines()
        self.assertEqual(missing, lines[0])
        self.assertEqual(8, len(lines))
        
        # after a pull we're back on track
        self.capture('pull')
        self.assertEqual("Branches are up to date.\n", self.capture('missing ../a'))

