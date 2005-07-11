#! /usr/bin/python2.4

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




"""test suite for weave algorithm"""


import testsweet
from bzrlib.weave import Weave, WeaveFormatError
from bzrlib.weavefile import write_weave, read_weave
from pprint import pformat



try:
    set
    frozenset
except NameError:
    from sets import Set, ImmutableSet
    set = Set
    frozenset = ImmutableSet
    del Set, ImmutableSet



# texts for use in testing
TEXT_0 = ["Hello world"]
TEXT_1 = ["Hello world",
          "A second line"]



class TestBase(testsweet.TestBase):
    def check_read_write(self, k):
        """Check the weave k can be written & re-read."""
        from tempfile import TemporaryFile
        tf = TemporaryFile()

        write_weave(k, tf)
        tf.seek(0)
        k2 = read_weave(tf)

        if k != k2:
            tf.seek(0)
            self.log('serialized weave:')
            self.log(tf.read())
            self.fail('read/write check failed')
        
        


class Easy(TestBase):
    def runTest(self):
        k = Weave()


class StoreText(TestBase):
    """Store and retrieve a simple text."""
    def runTest(self):
        k = Weave()
        idx = k.add([], TEXT_0)
        self.assertEqual(k.get(idx), TEXT_0)
        self.assertEqual(idx, 0)



class AnnotateOne(TestBase):
    def runTest(self):
        k = Weave()
        k.add([], TEXT_0)
        self.assertEqual(k.annotate(0),
                         [(0, TEXT_0[0])])


class StoreTwo(TestBase):
    def runTest(self):
        k = Weave()

        idx = k.add([], TEXT_0)
        self.assertEqual(idx, 0)

        idx = k.add([], TEXT_1)
        self.assertEqual(idx, 1)

        self.assertEqual(k.get(0), TEXT_0)
        self.assertEqual(k.get(1), TEXT_1)

        k.dump(self.TEST_LOG)



class DeltaAdd(TestBase):
    """Detection of changes prior to inserting new revision."""
    def runTest(self):
        k = Weave()
        k.add([], ['line 1'])

        self.assertEqual(k._l,
                         [('{', 0),
                          'line 1',
                          ('}', 0),
                          ])

        changes = list(k._delta(set([0]),
                                ['line 1',
                                 'new line']))

        self.log('raw changes: ' + pformat(changes))

        # currently there are 3 lines in the weave, and we insert after them
        self.assertEquals(changes,
                          [(3, 3, ['new line'])])

        changes = k._delta(set([0]),
                           ['top line',
                            'line 1'])
        
        self.assertEquals(list(changes),
                          [(1, 1, ['top line'])])

        self.check_read_write(k)


class InvalidAdd(TestBase):
    """Try to use invalid version number during add."""
    def runTest(self):
        k = Weave()

        self.assertRaises(ValueError,
                          k.add,
                          [69],
                          ['new text!'])


class InsertLines(TestBase):
    """Store a revision that adds one line to the original.

    Look at the annotations to make sure that the first line is matched
    and not stored repeatedly."""
    def runTest(self):
        k = Weave()

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

        k.add([0], ['line 1', 'diverged line'])

        self.assertEqual(k.annotate(2),
                         [(0, 'line 1'),
                          (2, 'diverged line')])

        text3 = ['line 1', 'middle line', 'line 2']
        k.add([0, 1],
              text3)

        self.log("changes to text3: " + pformat(list(k._delta(set([0, 1]), text3))))

        self.log("k._l=" + pformat(k._l))

        self.assertEqual(k.annotate(3),
                         [(0, 'line 1'),
                          (3, 'middle line'),
                          (1, 'line 2')])

        # now multiple insertions at different places
        k.add([0, 1, 3],
              ['line 1', 'aaa', 'middle line', 'bbb', 'line 2', 'ccc'])

        self.assertEqual(k.annotate(4), 
                         [(0, 'line 1'),
                          (4, 'aaa'),
                          (3, 'middle line'),
                          (4, 'bbb'),
                          (1, 'line 2'),
                          (4, 'ccc')])



class DeleteLines(TestBase):
    """Deletion of lines from existing text.

    Try various texts all based on a common ancestor."""
    def runTest(self):
        k = Weave()

        base_text = ['one', 'two', 'three', 'four']

        k.add([], base_text)
        
        texts = [['one', 'two', 'three'],
                 ['two', 'three', 'four'],
                 ['one', 'four'],
                 ['one', 'two', 'three', 'four'],
                 ]

        for t in texts:
            ver = k.add([0], t)

        self.log('final weave:')
        self.log('k._l=' + pformat(k._l))

        for i in range(len(texts)):
            self.assertEqual(k.get(i+1),
                             texts[i])
            



class SuicideDelete(TestBase):
    """Invalid weave which tries to add and delete simultaneously."""
    def runTest(self):
        k = Weave()

        k._v = [(),
                ]
        k._l = [('{', 0),
                'first line',
                ('[', 0),
                'deleted in 0',
                (']', 0),
                ('}', 0),
                ]
        ################################### SKIPPED
        # Weave.get doesn't trap this anymore
        return 

        self.assertRaises(WeaveFormatError,
                          k.get,
                          0)        



class CannedDelete(TestBase):
    """Unpack canned weave with deleted lines."""
    def runTest(self):
        k = Weave()

        k._v = [(),
                frozenset([0]),
                ]
        k._l = [('{', 0),
                'first line',
                ('[', 1),
                'line to be deleted',
                (']', 1),
                'last line',
                ('}', 0),
                ]

        self.assertEqual(k.get(0),
                         ['first line',
                          'line to be deleted',
                          'last line',
                          ])

        self.assertEqual(k.get(1),
                         ['first line',
                          'last line',
                          ])



class CannedReplacement(TestBase):
    """Unpack canned weave with deleted lines."""
    def runTest(self):
        k = Weave()

        k._v = [frozenset(),
                frozenset([0]),
                ]
        k._l = [('{', 0),
                'first line',
                ('[', 1),
                'line to be deleted',
                (']', 1),
                ('{', 1),
                'replacement line',                
                ('}', 1),
                'last line',
                ('}', 0),
                ]

        self.assertEqual(k.get(0),
                         ['first line',
                          'line to be deleted',
                          'last line',
                          ])

        self.assertEqual(k.get(1),
                         ['first line',
                          'replacement line',
                          'last line',
                          ])



class BadWeave(TestBase):
    """Test that we trap an insert which should not occur."""
    def runTest(self):
        k = Weave()

        k._v = [frozenset(),
                ]
        k._l = ['bad line',
                ('{', 0),
                'foo {',
                ('{', 1),
                '  added in version 1',
                ('{', 2),
                '  added in v2',
                ('}', 2),
                '  also from v1',
                ('}', 1),
                '}',
                ('}', 0)]

        ################################### SKIPPED
        # Weave.get doesn't trap this anymore
        return 


        self.assertRaises(WeaveFormatError,
                          k.get,
                          0)


class BadInsert(TestBase):
    """Test that we trap an insert which should not occur."""
    def runTest(self):
        k = Weave()

        k._v = [frozenset(),
                frozenset([0]),
                frozenset([0]),
                frozenset([0,1,2]),
                ]
        k._l = [('{', 0),
                'foo {',
                ('{', 1),
                '  added in version 1',
                ('{', 1),
                '  more in 1',
                ('}', 1),
                ('}', 1),
                ('}', 0)]


        # this is not currently enforced by get
        return  ##########################################

        self.assertRaises(WeaveFormatError,
                          k.get,
                          0)

        self.assertRaises(WeaveFormatError,
                          k.get,
                          1)


class InsertNested(TestBase):
    """Insertion with nested instructions."""
    def runTest(self):
        k = Weave()

        k._v = [frozenset(),
                frozenset([0]),
                frozenset([0]),
                frozenset([0,1,2]),
                ]
        k._l = [('{', 0),
                'foo {',
                ('{', 1),
                '  added in version 1',
                ('{', 2),
                '  added in v2',
                ('}', 2),
                '  also from v1',
                ('}', 1),
                '}',
                ('}', 0)]

        self.assertEqual(k.get(0),
                         ['foo {',
                          '}'])

        self.assertEqual(k.get(1),
                         ['foo {',
                          '  added in version 1',
                          '  also from v1',
                          '}'])
                       
        self.assertEqual(k.get(2),
                         ['foo {',
                          '  added in v2',
                          '}'])

        self.assertEqual(k.get(3),
                         ['foo {',
                          '  added in version 1',
                          '  added in v2',
                          '  also from v1',
                          '}'])
                         


class DeleteLines2(TestBase):
    """Test recording revisions that delete lines.

    This relies on the weave having a way to represent lines knocked
    out by a later revision."""
    def runTest(self):
        k = Weave()

        k.add([], ["line the first",
                   "line 2",
                   "line 3",
                   "fine"])

        self.assertEqual(len(k.get(0)), 4)

        k.add([0], ["line the first",
                   "fine"])

        self.assertEqual(k.get(1),
                         ["line the first",
                          "fine"])

        self.assertEqual(k.annotate(1),
                         [(0, "line the first"),
                          (0, "fine")])



class IncludeVersions(TestBase):
    """Check texts that are stored across multiple revisions.

    Here we manually create a weave with particular encoding and make
    sure it unpacks properly.

    Text 0 includes nothing; text 1 includes text 0 and adds some
    lines.
    """

    def runTest(self):
        k = Weave()

        k._v = [frozenset(), frozenset([0])]
        k._l = [('{', 0),
                "first line",
                ('}', 0),
                ('{', 1),
                "second line",
                ('}', 1)]

        self.assertEqual(k.get(1),
                         ["first line",
                          "second line"])

        self.assertEqual(k.get(0),
                         ["first line"])

        k.dump(self.TEST_LOG)


class DivergedIncludes(TestBase):
    """Weave with two diverged texts based on version 0.
    """
    def runTest(self):
        k = Weave()

        k._v = [frozenset(),
                frozenset([0]),
                frozenset([0]),
                ]
        k._l = [('{', 0),
                "first line",
                ('}', 0),
                ('{', 1),
                "second line",
                ('}', 1),
                ('{', 2),
                "alternative second line",
                ('}', 2),                
                ]

        self.assertEqual(k.get(0),
                         ["first line"])

        self.assertEqual(k.get(1),
                         ["first line",
                          "second line"])

        self.assertEqual(k.get(2),
                         ["first line",
                          "alternative second line"])

        self.assertEqual(k.inclusions([2]),
                         set([0, 2]))



class ReplaceLine(TestBase):
    def runTest(self):
        k = Weave()

        text0 = ['cheddar', 'stilton', 'gruyere']
        text1 = ['cheddar', 'blue vein', 'neufchatel', 'chevre']
        
        k.add([], text0)
        k.add([0], text1)

        self.log('k._l=' + pformat(k._l))

        self.assertEqual(k.get(0), text0)
        self.assertEqual(k.get(1), text1)



class Merge(TestBase):
    """Storage of versions that merge diverged parents"""
    def runTest(self):
        k = Weave()

        texts = [['header'],
                 ['header', '', 'line from 1'],
                 ['header', '', 'line from 2', 'more from 2'],
                 ['header', '', 'line from 1', 'fixup line', 'line from 2'],
                 ]

        k.add([], texts[0])
        k.add([0], texts[1])
        k.add([0], texts[2])
        k.add([0, 1, 2], texts[3])

        for i, t in enumerate(texts):
            self.assertEqual(k.get(i), t)

        self.assertEqual(k.annotate(3),
                         [(0, 'header'),
                          (1, ''),
                          (1, 'line from 1'),
                          (3, 'fixup line'),
                          (2, 'line from 2'),
                          ])

        self.assertEqual(k.inclusions([3]),
                         set([0, 1, 2, 3]))

        self.log('k._l=' + pformat(k._l))

        self.check_read_write(k)


class Conflicts(TestBase):
    """Test detection of conflicting regions during a merge.

    A base version is inserted, then two descendents try to
    insert different lines in the same place.  These should be
    reported as a possible conflict and forwarded to the user."""
    def runTest(self):
        return  # NOT RUN
        k = Weave()

        k.add([], ['aaa', 'bbb'])
        k.add([0], ['aaa', '111', 'bbb'])
        k.add([1], ['aaa', '222', 'bbb'])

        merged = k.merge([1, 2])

        self.assertEquals([[['aaa']],
                           [['111'], ['222']],
                           [['bbb']]])



class NonConflict(TestBase):
    """Two descendants insert compatible changes.

    No conflict should be reported."""
    def runTest(self):
        return  # NOT RUN
        k = Weave()

        k.add([], ['aaa', 'bbb'])
        k.add([0], ['111', 'aaa', 'ccc', 'bbb'])
        k.add([1], ['aaa', 'ccc', 'bbb', '222'])

    
    


class AutoMerge(TestBase):
    def runTest(self):
        k = Weave()

        texts = [['header', 'aaa', 'bbb'],
                 ['header', 'aaa', 'line from 1', 'bbb'],
                 ['header', 'aaa', 'bbb', 'line from 2', 'more from 2'],
                 ]

        k.add([], texts[0])
        k.add([0], texts[1])
        k.add([0], texts[2])

        self.log('k._l=' + pformat(k._l))

        m = list(k.mash_iter([0, 1, 2]))

        self.assertEqual(m,
                         ['header', 'aaa',
                          'line from 1',
                          'bbb',
                          'line from 2', 'more from 2'])
        


class Khayyam(TestBase):
    """Test changes to multi-line texts, and read/write"""
    def runTest(self):
        rawtexts = [
            """A Book of Verses underneath the Bough,
            A Jug of Wine, a Loaf of Bread, -- and Thou
            Beside me singing in the Wilderness --
            Oh, Wilderness were Paradise enow!""",
            
            """A Book of Verses underneath the Bough,
            A Jug of Wine, a Loaf of Bread, -- and Thou
            Beside me singing in the Wilderness --
            Oh, Wilderness were Paradise now!""",

            """A Book of poems underneath the tree,
            A Jug of Wine, a Loaf of Bread,
            and Thou
            Beside me singing in the Wilderness --
            Oh, Wilderness were Paradise now!

            -- O. Khayyam""",

            """A Book of Verses underneath the Bough,
            A Jug of Wine, a Loaf of Bread,
            and Thou
            Beside me singing in the Wilderness --
            Oh, Wilderness were Paradise now!""",
            ]
        texts = [[l.strip() for l in t.split('\n')] for t in rawtexts]

        k = Weave()
        parents = set()
        for t in texts:
            ver = k.add(list(parents), t)
            parents.add(ver)

        self.log("k._l=" + pformat(k._l))

        for i, t in enumerate(texts):
            self.assertEqual(k.get(i), t)

        self.check_read_write(k)


def testweave():
    import testsweet
    from unittest import TestSuite, TestLoader
    import testweave
 
    tl = TestLoader()
    suite = TestSuite()
    suite.addTest(tl.loadTestsFromModule(testweave))
    
    return int(not testsweet.run_suite(suite)) # for shell 0=true


if __name__ == '__main__':
    import sys
    sys.exit(testweave())
    
