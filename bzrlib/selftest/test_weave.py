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


# TODO: tests regarding version names



"""test suite for weave algorithm"""

from pprint import pformat

from bzrlib.weave import Weave, WeaveFormatError, WeaveError
from bzrlib.weavefile import write_weave, read_weave
from bzrlib.selftest import TestCase
from bzrlib.osutils import sha_string


# texts for use in testing
TEXT_0 = ["Hello world"]
TEXT_1 = ["Hello world",
          "A second line"]



class TestBase(TestCase):
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

            self.log('')
            self.log('parents: %s' % (k._parents == k2._parents))
            self.log('         %r' % k._parents)
            self.log('         %r' % k2._parents)
            self.log('')

            
            self.fail('read/write check failed')
        
        


class Easy(TestBase):
    def runTest(self):
        k = Weave()


class StoreText(TestBase):
    """Store and retrieve a simple text."""
    def runTest(self):
        k = Weave()
        idx = k.add('text0', [], TEXT_0)
        self.assertEqual(k.get(idx), TEXT_0)
        self.assertEqual(idx, 0)



class AnnotateOne(TestBase):
    def runTest(self):
        k = Weave()
        k.add('text0', [], TEXT_0)
        self.assertEqual(k.annotate(0),
                         [(0, TEXT_0[0])])


class StoreTwo(TestBase):
    def runTest(self):
        k = Weave()

        idx = k.add('text0', [], TEXT_0)
        self.assertEqual(idx, 0)

        idx = k.add('text1', [], TEXT_1)
        self.assertEqual(idx, 1)

        self.assertEqual(k.get(0), TEXT_0)
        self.assertEqual(k.get(1), TEXT_1)



class AddWithGivenSha(TestBase):
    def runTest(self):
        """Add with caller-supplied SHA-1"""
        k = Weave()

        t = 'text0'
        k.add('text0', [], [t], sha1=sha_string(t))



class InvalidAdd(TestBase):
    """Try to use invalid version number during add."""
    def runTest(self):
        k = Weave()

        self.assertRaises(IndexError,
                          k.add,
                          'text0',
                          [69],
                          ['new text!'])


class RepeatedAdd(TestBase):
    """Add the same version twice; harmless."""
    def runTest(self):
        k = Weave()
        idx = k.add('text0', [], TEXT_0)
        idx2 = k.add('text0', [], TEXT_0)
        self.assertEqual(idx, idx2)



class InvalidRepeatedAdd(TestBase):
    def runTest(self):
        k = Weave()
        idx = k.add('text0', [], TEXT_0)
        self.assertRaises(WeaveError,
                          k.add,
                          'text0',
                          [],
                          ['not the same text'])
        self.assertRaises(WeaveError,
                          k.add,
                          'text0',
                          [12],         # not the right parents
                          TEXT_0)
        


class InsertLines(TestBase):
    """Store a revision that adds one line to the original.

    Look at the annotations to make sure that the first line is matched
    and not stored repeatedly."""
    def runTest(self):
        k = Weave()

        k.add('text0', [], ['line 1'])
        k.add('text1', [0], ['line 1', 'line 2'])

        self.assertEqual(k.annotate(0),
                         [(0, 'line 1')])

        self.assertEqual(k.get(1),
                         ['line 1',
                          'line 2'])

        self.assertEqual(k.annotate(1),
                         [(0, 'line 1'),
                          (1, 'line 2')])

        k.add('text2', [0], ['line 1', 'diverged line'])

        self.assertEqual(k.annotate(2),
                         [(0, 'line 1'),
                          (2, 'diverged line')])

        text3 = ['line 1', 'middle line', 'line 2']
        k.add('text3',
              [0, 1],
              text3)

        # self.log("changes to text3: " + pformat(list(k._delta(set([0, 1]), text3))))

        self.log("k._weave=" + pformat(k._weave))

        self.assertEqual(k.annotate(3),
                         [(0, 'line 1'),
                          (3, 'middle line'),
                          (1, 'line 2')])

        # now multiple insertions at different places
        k.add('text4',
              [0, 1, 3],
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

        k.add('text0', [], base_text)
        
        texts = [['one', 'two', 'three'],
                 ['two', 'three', 'four'],
                 ['one', 'four'],
                 ['one', 'two', 'three', 'four'],
                 ]

        i = 1
        for t in texts:
            ver = k.add('text%d' % i,
                        [0], t)
            i += 1

        self.log('final weave:')
        self.log('k._weave=' + pformat(k._weave))

        for i in range(len(texts)):
            self.assertEqual(k.get(i+1),
                             texts[i])
            



class SuicideDelete(TestBase):
    """Invalid weave which tries to add and delete simultaneously."""
    def runTest(self):
        k = Weave()

        k._parents = [(),
                ]
        k._weave = [('{', 0),
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

        k._parents = [(),
                frozenset([0]),
                ]
        k._weave = [('{', 0),
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

        k._parents = [frozenset(),
                frozenset([0]),
                ]
        k._weave = [('{', 0),
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

        k._parents = [frozenset(),
                ]
        k._weave = ['bad line',
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

        k._parents = [frozenset(),
                frozenset([0]),
                frozenset([0]),
                frozenset([0,1,2]),
                ]
        k._weave = [('{', 0),
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

        k._parents = [frozenset(),
                frozenset([0]),
                frozenset([0]),
                frozenset([0,1,2]),
                ]
        k._weave = [('{', 0),
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

        k.add('text0', [], ["line the first",
                   "line 2",
                   "line 3",
                   "fine"])

        self.assertEqual(len(k.get(0)), 4)

        k.add('text1', [0], ["line the first",
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

        k._parents = [frozenset(), frozenset([0])]
        k._weave = [('{', 0),
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


class DivergedIncludes(TestBase):
    """Weave with two diverged texts based on version 0.
    """
    def runTest(self):
        k = Weave()

        k._parents = [frozenset(),
                frozenset([0]),
                frozenset([0]),
                ]
        k._weave = [('{', 0),
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

        self.assertEqual(list(k.inclusions([2])),
                         [0, 2])



class ReplaceLine(TestBase):
    def runTest(self):
        k = Weave()

        text0 = ['cheddar', 'stilton', 'gruyere']
        text1 = ['cheddar', 'blue vein', 'neufchatel', 'chevre']
        
        k.add('text0', [], text0)
        k.add('text1', [0], text1)

        self.log('k._weave=' + pformat(k._weave))

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

        k.add('text0', [], texts[0])
        k.add('text1', [0], texts[1])
        k.add('text2', [0], texts[2])
        k.add('merge', [0, 1, 2], texts[3])

        for i, t in enumerate(texts):
            self.assertEqual(k.get(i), t)

        self.assertEqual(k.annotate(3),
                         [(0, 'header'),
                          (1, ''),
                          (1, 'line from 1'),
                          (3, 'fixup line'),
                          (2, 'line from 2'),
                          ])

        self.assertEqual(list(k.inclusions([3])),
                         [0, 1, 2, 3])

        self.log('k._weave=' + pformat(k._weave))

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

        k.add('text0', [], texts[0])
        k.add('text1', [0], texts[1])
        k.add('text2', [0], texts[2])

        self.log('k._weave=' + pformat(k._weave))

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
        i = 0
        for t in texts:
            ver = k.add('text%d' % i,
                        list(parents), t)
            parents.add(ver)
            i += 1

        self.log("k._weave=" + pformat(k._weave))

        for i, t in enumerate(texts):
            self.assertEqual(k.get(i), t)

        self.check_read_write(k)



class MergeCases(TestBase):
    def doMerge(self, base, a, b, mp):
        from cStringIO import StringIO
        from textwrap import dedent

        def addcrlf(x):
            return x + '\n'
        
        w = Weave()
        w.add('text0', [], map(addcrlf, base))
        w.add('text1', [0], map(addcrlf, a))
        w.add('text2', [0], map(addcrlf, b))

        self.log('weave is:')
        tmpf = StringIO()
        write_weave(w, tmpf)
        self.log(tmpf.getvalue())

        self.log('merge plan:')
        p = list(w.plan_merge(1, 2))
        for state, line in p:
            if line:
                self.log('%12s | %s' % (state, line[:-1]))

        self.log('merge:')
        mt = StringIO()
        mt.writelines(w.weave_merge(p))
        mt.seek(0)
        self.log(mt.getvalue())

        mp = map(addcrlf, mp)
        self.assertEqual(mt.readlines(), mp)
        
        
    def testOneInsert(self):
        self.doMerge([],
                     ['aa'],
                     [],
                     ['aa'])

    def testSeparateInserts(self):
        self.doMerge(['aaa', 'bbb', 'ccc'],
                     ['aaa', 'xxx', 'bbb', 'ccc'],
                     ['aaa', 'bbb', 'yyy', 'ccc'],
                     ['aaa', 'xxx', 'bbb', 'yyy', 'ccc'])

    def testSameInsert(self):
        self.doMerge(['aaa', 'bbb', 'ccc'],
                     ['aaa', 'xxx', 'bbb', 'ccc'],
                     ['aaa', 'xxx', 'bbb', 'yyy', 'ccc'],
                     ['aaa', 'xxx', 'bbb', 'yyy', 'ccc'])

    def testOverlappedInsert(self):
        self.doMerge(['aaa', 'bbb'],
                     ['aaa', 'xxx', 'yyy', 'bbb'],
                     ['aaa', 'xxx', 'bbb'],
                     ['aaa', '<<<<', 'xxx', 'yyy', '====', 'xxx', '>>>>', 'bbb'])

        # really it ought to reduce this to 
        # ['aaa', 'xxx', 'yyy', 'bbb']


    def testClashReplace(self):
        self.doMerge(['aaa'],
                     ['xxx'],
                     ['yyy', 'zzz'],
                     ['<<<<', 'xxx', '====', 'yyy', 'zzz', '>>>>'])

    def testNonClashInsert(self):
        self.doMerge(['aaa'],
                     ['xxx', 'aaa'],
                     ['yyy', 'zzz'],
                     ['<<<<', 'xxx', 'aaa', '====', 'yyy', 'zzz', '>>>>'])

        self.doMerge(['aaa'],
                     ['aaa'],
                     ['yyy', 'zzz'],
                     ['yyy', 'zzz'])


    def testDeleteAndModify(self):
        """Clashing delete and modification.

        If one side modifies a region and the other deletes it then
        there should be a conflict with one side blank.
        """

        #######################################
        # skippd, not working yet
        return
        
        self.doMerge(['aaa', 'bbb', 'ccc'],
                     ['aaa', 'ddd', 'ccc'],
                     ['aaa', 'ccc'],
                     ['<<<<', 'aaa', '====', '>>>>', 'ccc'])


class JoinWeavesTests(TestBase):
    def setUp(self):
        super(JoinWeavesTests, self).setUp()
        self.weave1 = Weave()
        self.lines1 = ['hello\n']
        self.lines3 = ['hello\n', 'cruel\n', 'world\n']
        self.weave1.add('v1', [], self.lines1)
        self.weave1.add('v2', [0], ['hello\n', 'world\n'])
        self.weave1.add('v3', [1], self.lines3)
        
    def test_join_empty(self):
        """Join two empty weaves."""
        eq = self.assertEqual
        w1 = Weave()
        w2 = Weave()
        w1.join(w2)
        eq(w1.numversions(), 0)
        
    def test_join_empty_to_nonempty(self):
        """Join empty weave onto nonempty."""
        self.weave1.join(Weave())
        self.assertEqual(len(self.weave1), 3)

    def test_join_unrelated(self):
        """Join two weaves with no history in common."""
        wb = Weave()
        wb.add('b1', [], ['line from b\n'])
        w1 = self.weave1
        w1.join(wb)
        eq = self.assertEqual
        eq(len(w1), 4)
        eq(sorted(list(w1.iter_names())),
           ['b1', 'v1', 'v2', 'v3'])

    def test_join_related(self):
        wa = self.weave1.copy()
        wb = self.weave1.copy()
        wa.add('a1', ['v3'], ['hello\n', 'sweet\n', 'world\n'])
        wb.add('b1', ['v3'], ['hello\n', 'pale blue\n', 'world\n'])
        eq = self.assertEquals
        eq(len(wa), 4)
        eq(len(wb), 4)
        wa.join(wb)
        eq(len(wa), 5)
        eq(wa.get_lines('b1'),
           ['hello\n', 'pale blue\n', 'world\n'])

    def test_join_parent_disagreement(self):
        """Cannot join weaves with different parents for a version."""
        wa = Weave()
        wb = Weave()
        wa.add('v1', [], ['hello\n'])
        wb.add('v0', [], [])
        wb.add('v1', ['v0'], ['hello\n'])
        self.assertRaises(WeaveError,
                          wa.join, wb)

    def test_join_text_disagreement(self):
        """Cannot join weaves with different texts for a version."""
        wa = Weave()
        wb = Weave()
        wa.add('v1', [], ['hello\n'])
        wb.add('v1', [], ['not\n', 'hello\n'])
        self.assertRaises(WeaveError,
                          wa.join, wb)

    def test_join_unordered(self):
        """Join weaves where indexes differ.
        
        The source weave contains a different version at index 0."""
        wa = self.weave1.copy()
        wb = Weave()
        wb.add('x1', [], ['line from x1\n'])
        wb.add('v1', [], ['hello\n'])
        wb.add('v2', ['v1'], ['hello\n', 'world\n'])
        wa.join(wb)
        eq = self.assertEquals
        eq(sorted(wa.iter_names()), ['v1', 'v2', 'v3', 'x1',])
        eq(wa.get_text('x1'), 'line from x1\n')

    def test_join_with_ghosts(self):
        """Join that inserts parents of an existing revision.

        This can happen when merging from another branch who
        knows about revisions the destination does not.  In 
        this test the second weave knows of an additional parent of 
        v2.  Any revisions which are in common still have to have the 
        same text."""
        return ###############################
        wa = self.weave1.copy()
        wb = Weave()
        wb.add('x1', [], ['line from x1\n'])
        wb.add('v1', [], ['hello\n'])
        wb.add('v2', ['v1', 'x1'], ['hello\n', 'world\n'])
        wa.join(wb)
        eq = self.assertEquals
        eq(sorted(wa.iter_names()), ['v1', 'v2', 'v3', 'x1',])
        eq(wa.get_text('x1'), 'line from x1\n')


if __name__ == '__main__':
    import sys
    import unittest
    sys.exit(unittest.main())
    
