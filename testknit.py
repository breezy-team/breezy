# Copyright (C) 2005 by Canonical Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA




"""test case for knit/weave algorithm"""


from testsweet import TestBase
from knit import Knit, VerInfo


# texts for use in testing
TEXT_0 = ["Hello world"]
TEXT_1 = ["Hello world",
          "A second line"]


class Easy(TestBase):
    def runTest(self):
        k = Knit()


class StoreText(TestBase):
    """Store and retrieve a simple text."""
    def runTest(self):
        k = Knit()
        idx = k.add([], TEXT_0)
        self.assertEqual(k.get(idx), TEXT_0)
        self.assertEqual(idx, 0)



class AnnotateOne(TestBase):
    def runTest(self):
        k = Knit()
        k.add([], TEXT_0)
        self.assertEqual(k.annotate(0),
                         [(0, TEXT_0[0])])


class StoreTwo(TestBase):
    def runTest(self):
        k = Knit()

        idx = k.add([], TEXT_0)
        self.assertEqual(idx, 0)

        idx = k.add([], TEXT_1)
        self.assertEqual(idx, 1)

        self.assertEqual(k.get(0), TEXT_0)
        self.assertEqual(k.get(1), TEXT_1)

        k.dump(self.TEST_LOG)



class Delta1(TestBase):
    """Detection of changes prior to inserting new revision."""
    def runTest(self):
        from pprint import pformat

        k = Knit()
        k.add([], ['line 1'])

        changes = list(k._delta(set([0]),
                                ['line 1',
                                 'new line']))

        self.log('raw changes: ' + pformat(changes))

        # should be one inserted line after line 0q
        self.assertEquals(changes,
                          [(1, 1, ['new line'])])

        changes = k._delta(set([0]),
                           ['top line',
                            'line 1'])
        
        self.assertEquals(list(changes),
                          [(0, 0, ['top line'])])



class InvalidAdd(TestBase):
    """Try to use invalid version number during add."""
    def runTest(self):
        k = Knit()

        self.assertRaises(IndexError,
                          k.add,
                          [69],
                          ['new text!'])


class InsertLines(TestBase):
    """Store a revision that adds one line to the original.

    Look at the annotations to make sure that the first line is matched
    and not stored repeatedly."""
    def runTest(self):
        k = Knit()

        k.add([], ['line 1'])
        k.add([0], ['line 1', 'line 2'])

        self.assertEqual(k.annotate(0),
                         [(0, 'line 1')])

        self.assertEqual(k.get(1),
                         ['line 1',
                          'line 2'])

        self.assertEqual(k.annotate(1),
                         [(0, 'line 1'),
                          (1, 'line 2')])



class IncludeVersions(TestBase):
    """Check texts that are stored across multiple revisions.

    Here we manually create a knit with particular encoding and make
    sure it unpacks properly.

    Text 0 includes nothing; text 1 includes text 0 and adds some
    lines.
    """

    def runTest(self):
        k = Knit()

        k._v = [VerInfo(), VerInfo(included=[0])]
        k._l = [(0, "first line"),
                (1, "second line")]

        self.assertEqual(k.get(1),
                         ["first line",
                          "second line"])

        self.assertEqual(k.get(0),
                         ["first line"])

        k.dump(self.TEST_LOG)


class DivergedIncludes(TestBase):
    """Knit with two diverged texts based on version 0.
    """
    def runTest(self):
        k = Knit()

        k._v = [VerInfo(),
                VerInfo(included=[0]),
                VerInfo(included=[0]),
                ]
        k._l = [(0, "first line"),
                (1, "second line"),
                (2, "alternative second line"),]

        self.assertEqual(k.get(0),
                         ["first line"])

        self.assertEqual(k.get(1),
                         ["first line",
                          "second line"])

        self.assertEqual(k.get(2),
                         ["first line",
                          "alternative second line"])

def testknit():
    import testsweet
    from unittest import TestSuite, TestLoader
    import testknit

    tl = TestLoader()
    suite = TestSuite()
    suite.addTest(tl.loadTestsFromModule(testknit))
    
    return int(not testsweet.run_suite(suite)) # for shell 0=true


if __name__ == '__main__':
    import sys
    sys.exit(testknit())
    
