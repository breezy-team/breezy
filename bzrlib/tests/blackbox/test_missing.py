"""Black-box tests for bzr missing.
"""

import os

from bzrlib.branch import Branch
from bzrlib.tests import TestCaseInTempDir

class TestMissing(TestCaseInTempDir):
    def test_missing(self):
        missing = "You are missing 1 revision(s):"

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
        lines = self.capture('missing ../b', retcode=1).splitlines()
        # we're missing the extra revision here
        self.assertEqual(missing, lines[0])
        self.assertEqual(8, len(lines))

        # get extra revision from b
        self.capture('merge ../b')
        self.capture('commit -m merge')

        # compare again, but now we have the 'merge' commit extra
        lines = self.capture('missing ../b', retcode=1).splitlines()
        self.assertEqual("You have 1 extra revision(s):", lines[0])
        self.assertEqual(8, len(lines))
        lines2 = self.capture('missing ../b --mine-only', retcode=1)
        lines2 = lines2.splitlines()
        self.assertEqual(lines, lines2)
        lines3 = self.capture('missing ../b --theirs-only', retcode=1)
        lines3 = lines3.splitlines()
        self.assertEqual(0, len(lines3))

        # relative to a, missing the 'merge' commit 
        os.chdir('../b')
        lines = self.capture('missing ../a', retcode=1).splitlines()
        self.assertEqual(missing, lines[0])
        self.assertEqual(8, len(lines))
        lines2 = self.capture('missing ../a --theirs-only', retcode=1)
        lines2 = lines2.splitlines()
        self.assertEqual(lines, lines2)
        lines3 = self.capture('missing ../a --mine-only', retcode=1)
        lines3 = lines3.splitlines()
        self.assertEqual(0, len(lines3))
        lines4 = self.capture('missing ../a --short', retcode=1)
        lines4 = lines4.splitlines()
        self.assertEqual(4, len(lines4))
        lines5 = self.capture('missing ../a --line', retcode=1)
        lines5 = lines5.splitlines()
        self.assertEqual(2, len(lines5))
        lines6 = self.capture('missing ../a --reverse', retcode=1)
        lines6 = lines6.splitlines()
        self.assertEqual(lines6, lines)
        lines7 = self.capture('missing ../a --show-ids', retcode=1)
        lines7 = lines7.splitlines()
        self.assertEqual(11, len(lines7))
        lines8 = self.capture('missing ../a --verbose', retcode=1)
        lines8 = lines8.splitlines()
        self.assertEqual("modified:", lines8[-2])
        self.assertEqual("  a", lines8[-1])

        
        # after a pull we're back on track
        self.capture('pull')
        self.assertEqual("Branches are up to date.\n", 
                         self.capture('missing ../a'))

