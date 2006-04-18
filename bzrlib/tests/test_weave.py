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
# TODO: rbc 20050108 test that join does not leave an inconsistent weave 
#       if it fails.

"""test suite for weave algorithm"""

from pprint import pformat

import bzrlib.errors as errors
from bzrlib.weave import Weave, WeaveFormatError, WeaveError, reweave
from bzrlib.weavefile import write_weave, read_weave
from bzrlib.tests import TestCase
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


class WeaveContains(TestBase):
    """Weave __contains__ operator"""
    def runTest(self):
        k = Weave()
        self.assertFalse('foo' in k)
        k.add_lines('foo', [], TEXT_1)
        self.assertTrue('foo' in k)


class Easy(TestBase):
    def runTest(self):
        k = Weave()


class StoreText(TestBase):
    """Store and retrieve a simple text."""

    def test_storing_text(self):
        k = Weave()
        idx = k.add_lines('text0', [], TEXT_0)
        self.assertEqual(k.get_lines(idx), TEXT_0)
        self.assertEqual(idx, 0)


class AnnotateOne(TestBase):
    def runTest(self):
        k = Weave()
        k.add_lines('text0', [], TEXT_0)
        self.assertEqual(k.annotate('text0'),
                         [('text0', TEXT_0[0])])


class StoreTwo(TestBase):
    def runTest(self):
        k = Weave()

        idx = k.add_lines('text0', [], TEXT_0)
        self.assertEqual(idx, 0)

        idx = k.add_lines('text1', [], TEXT_1)
        self.assertEqual(idx, 1)

        self.assertEqual(k.get_lines(0), TEXT_0)
        self.assertEqual(k.get_lines(1), TEXT_1)


class GetSha1(TestBase):
    def test_get_sha1(self):
        k = Weave()
        k.add_lines('text0', [], 'text0')
        self.assertEqual('34dc0e430c642a26c3dd1c2beb7a8b4f4445eb79',
                         k.get_sha1('text0'))
        self.assertRaises(errors.RevisionNotPresent,
                          k.get_sha1, 0)
        self.assertRaises(errors.RevisionNotPresent,
                          k.get_sha1, 'text1')
                        

class InvalidAdd(TestBase):
    """Try to use invalid version number during add."""
    def runTest(self):
        k = Weave()

        self.assertRaises(errors.RevisionNotPresent,
                          k.add_lines,
                          'text0',
                          ['69'],
                          ['new text!'])


class RepeatedAdd(TestBase):
    """Add the same version twice; harmless."""
    def runTest(self):
        k = Weave()
        idx = k.add_lines('text0', [], TEXT_0)
        idx2 = k.add_lines('text0', [], TEXT_0)
        self.assertEqual(idx, idx2)


class InvalidRepeatedAdd(TestBase):
    def runTest(self):
        k = Weave()
        k.add_lines('basis', [], TEXT_0)
        idx = k.add_lines('text0', [], TEXT_0)
        self.assertRaises(errors.RevisionAlreadyPresent,
                          k.add_lines,
                          'text0',
                          [],
                          ['not the same text'])
        self.assertRaises(errors.RevisionAlreadyPresent,
                          k.add_lines,
                          'text0',
                          ['basis'],         # not the right parents
                          TEXT_0)
        

class InsertLines(TestBase):
    """Store a revision that adds one line to the original.

    Look at the annotations to make sure that the first line is matched
    and not stored repeatedly."""
    def runTest(self):
        k = Weave()

        k.add_lines('text0', [], ['line 1'])
        k.add_lines('text1', ['text0'], ['line 1', 'line 2'])

        self.assertEqual(k.annotate('text0'),
                         [('text0', 'line 1')])

        self.assertEqual(k.get_lines(1),
                         ['line 1',
                          'line 2'])

        self.assertEqual(k.annotate('text1'),
                         [('text0', 'line 1'),
                          ('text1', 'line 2')])

        k.add_lines('text2', ['text0'], ['line 1', 'diverged line'])

        self.assertEqual(k.annotate('text2'),
                         [('text0', 'line 1'),
                          ('text2', 'diverged line')])

        text3 = ['line 1', 'middle line', 'line 2']
        k.add_lines('text3',
              ['text0', 'text1'],
              text3)

        # self.log("changes to text3: " + pformat(list(k._delta(set([0, 1]), text3))))

        self.log("k._weave=" + pformat(k._weave))

        self.assertEqual(k.annotate('text3'),
                         [('text0', 'line 1'),
                          ('text3', 'middle line'),
                          ('text1', 'line 2')])

        # now multiple insertions at different places
        k.add_lines('text4',
              ['text0', 'text1', 'text3'],
              ['line 1', 'aaa', 'middle line', 'bbb', 'line 2', 'ccc'])

        self.assertEqual(k.annotate('text4'), 
                         [('text0', 'line 1'),
                          ('text4', 'aaa'),
                          ('text3', 'middle line'),
                          ('text4', 'bbb'),
                          ('text1', 'line 2'),
                          ('text4', 'ccc')])


class DeleteLines(TestBase):
    """Deletion of lines from existing text.

    Try various texts all based on a common ancestor."""
    def runTest(self):
        k = Weave()

        base_text = ['one', 'two', 'three', 'four']

        k.add_lines('text0', [], base_text)
        
        texts = [['one', 'two', 'three'],
                 ['two', 'three', 'four'],
                 ['one', 'four'],
                 ['one', 'two', 'three', 'four'],
                 ]

        i = 1
        for t in texts:
            ver = k.add_lines('text%d' % i,
                        ['text0'], t)
            i += 1

        self.log('final weave:')
        self.log('k._weave=' + pformat(k._weave))

        for i in range(len(texts)):
            self.assertEqual(k.get_lines(i+1),
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
                          k.get_lines,
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
        k._sha1s = [sha_string('first lineline to be deletedlast line')
                  , sha_string('first linelast line')]

        self.assertEqual(k.get_lines(0),
                         ['first line',
                          'line to be deleted',
                          'last line',
                          ])

        self.assertEqual(k.get_lines(1),
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
        k._sha1s = [sha_string('first lineline to be deletedlast line')
                  , sha_string('first linereplacement linelast line')]

        self.assertEqual(k.get_lines(0),
                         ['first line',
                          'line to be deleted',
                          'last line',
                          ])

        self.assertEqual(k.get_lines(1),
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

        k._sha1s = [sha_string('foo {}')
                  , sha_string('foo {  added in version 1  also from v1}')
                  , sha_string('foo {  added in v2}')
                  , sha_string('foo {  added in version 1  added in v2  also from v1}')
                  ]

        self.assertEqual(k.get_lines(0),
                         ['foo {',
                          '}'])

        self.assertEqual(k.get_lines(1),
                         ['foo {',
                          '  added in version 1',
                          '  also from v1',
                          '}'])
                       
        self.assertEqual(k.get_lines(2),
                         ['foo {',
                          '  added in v2',
                          '}'])

        self.assertEqual(k.get_lines(3),
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

        k.add_lines('text0', [], ["line the first",
                   "line 2",
                   "line 3",
                   "fine"])

        self.assertEqual(len(k.get_lines(0)), 4)

        k.add_lines('text1', ['text0'], ["line the first",
                   "fine"])

        self.assertEqual(k.get_lines(1),
                         ["line the first",
                          "fine"])

        self.assertEqual(k.annotate('text1'),
                         [('text0', "line the first"),
                          ('text0', "fine")])


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

        k._sha1s = [sha_string('first line')
                  , sha_string('first linesecond line')]

        self.assertEqual(k.get_lines(1),
                         ["first line",
                          "second line"])

        self.assertEqual(k.get_lines(0),
                         ["first line"])


class DivergedIncludes(TestBase):
    """Weave with two diverged texts based on version 0.
    """
    def runTest(self):
        # FIXME make the weave, dont poke at it.
        k = Weave()

        k._names = ['0', '1', '2']
        k._name_map = {'0':0, '1':1, '2':2}
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

        k._sha1s = [sha_string('first line')
                  , sha_string('first linesecond line')
                  , sha_string('first linealternative second line')]

        self.assertEqual(k.get_lines(0),
                         ["first line"])

        self.assertEqual(k.get_lines(1),
                         ["first line",
                          "second line"])

        self.assertEqual(k.get_lines('2'),
                         ["first line",
                          "alternative second line"])

        self.assertEqual(list(k.get_ancestry(['2'])),
                         ['0', '2'])


class ReplaceLine(TestBase):
    def runTest(self):
        k = Weave()

        text0 = ['cheddar', 'stilton', 'gruyere']
        text1 = ['cheddar', 'blue vein', 'neufchatel', 'chevre']
        
        k.add_lines('text0', [], text0)
        k.add_lines('text1', ['text0'], text1)

        self.log('k._weave=' + pformat(k._weave))

        self.assertEqual(k.get_lines(0), text0)
        self.assertEqual(k.get_lines(1), text1)


class Merge(TestBase):
    """Storage of versions that merge diverged parents"""
    def runTest(self):
        k = Weave()

        texts = [['header'],
                 ['header', '', 'line from 1'],
                 ['header', '', 'line from 2', 'more from 2'],
                 ['header', '', 'line from 1', 'fixup line', 'line from 2'],
                 ]

        k.add_lines('text0', [], texts[0])
        k.add_lines('text1', ['text0'], texts[1])
        k.add_lines('text2', ['text0'], texts[2])
        k.add_lines('merge', ['text0', 'text1', 'text2'], texts[3])

        for i, t in enumerate(texts):
            self.assertEqual(k.get_lines(i), t)

        self.assertEqual(k.annotate('merge'),
                         [('text0', 'header'),
                          ('text1', ''),
                          ('text1', 'line from 1'),
                          ('merge', 'fixup line'),
                          ('text2', 'line from 2'),
                          ])

        self.assertEqual(list(k.get_ancestry(['merge'])),
                         ['text0', 'text1', 'text2', 'merge'])

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

        k.add_lines([], ['aaa', 'bbb'])
        k.add_lines([0], ['aaa', '111', 'bbb'])
        k.add_lines([1], ['aaa', '222', 'bbb'])

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

        k.add_lines([], ['aaa', 'bbb'])
        k.add_lines([0], ['111', 'aaa', 'ccc', 'bbb'])
        k.add_lines([1], ['aaa', 'ccc', 'bbb', '222'])


class Khayyam(TestBase):
    """Test changes to multi-line texts, and read/write"""

    def test_multi_line_merge(self):
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
            ver = k.add_lines('text%d' % i,
                        list(parents), t)
            parents.add('text%d' % i)
            i += 1

        self.log("k._weave=" + pformat(k._weave))

        for i, t in enumerate(texts):
            self.assertEqual(k.get_lines(i), t)

        self.check_read_write(k)


class MergeCases(TestBase):
    def doMerge(self, base, a, b, mp):
        from cStringIO import StringIO
        from textwrap import dedent

        def addcrlf(x):
            return x + '\n'
        
        w = Weave()
        w.add_lines('text0', [], map(addcrlf, base))
        w.add_lines('text1', ['text0'], map(addcrlf, a))
        w.add_lines('text2', ['text0'], map(addcrlf, b))

        self.log('weave is:')
        tmpf = StringIO()
        write_weave(w, tmpf)
        self.log(tmpf.getvalue())

        self.log('merge plan:')
        p = list(w.plan_merge('text1', 'text2'))
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
                     ['aaa', '<<<<<<< ', 'xxx', 'yyy', '=======', 'xxx', 
                      '>>>>>>> ', 'bbb'])

        # really it ought to reduce this to 
        # ['aaa', 'xxx', 'yyy', 'bbb']


    def testClashReplace(self):
        self.doMerge(['aaa'],
                     ['xxx'],
                     ['yyy', 'zzz'],
                     ['<<<<<<< ', 'xxx', '=======', 'yyy', 'zzz', 
                      '>>>>>>> '])

    def testNonClashInsert(self):
        self.doMerge(['aaa'],
                     ['xxx', 'aaa'],
                     ['yyy', 'zzz'],
                     ['<<<<<<< ', 'xxx', 'aaa', '=======', 'yyy', 'zzz', 
                      '>>>>>>> '])

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
                     ['<<<<<<<< ', 'aaa', '=======', '>>>>>>> ', 'ccc'])

    def _test_merge_from_strings(self, base, a, b, expected):
        w = Weave()
        w.add_lines('text0', [], base.splitlines(True))
        w.add_lines('text1', ['text0'], a.splitlines(True))
        w.add_lines('text2', ['text0'], b.splitlines(True))
        self.log('merge plan:')
        p = list(w.plan_merge('text1', 'text2'))
        for state, line in p:
            if line:
                self.log('%12s | %s' % (state, line[:-1]))
        self.log('merge result:')
        result_text = ''.join(w.weave_merge(p))
        self.log(result_text)
        self.assertEqualDiff(result_text, expected)

    def test_weave_merge_conflicts(self):
        # does weave merge properly handle plans that end with unchanged?
        result = ''.join(Weave().weave_merge([('new-a', 'hello\n')]))
        self.assertEqual(result, 'hello\n')

    def test_deletion_extended(self):
        """One side deletes, the other deletes more.
        """
        base = """\
            line 1
            line 2
            line 3
            """
        a = """\
            line 1
            line 2
            """
        b = """\
            line 1
            """
        result = """\
            line 1
            """
        self._test_merge_from_strings(base, a, b, result)

    def test_deletion_overlap(self):
        """Delete overlapping regions with no other conflict.

        Arguably it'd be better to treat these as agreement, rather than 
        conflict, but for now conflict is safer.
        """
        base = """\
            start context
            int a() {}
            int b() {}
            int c() {}
            end context
            """
        a = """\
            start context
            int a() {}
            end context
            """
        b = """\
            start context
            int c() {}
            end context
            """
        result = """\
            start context
<<<<<<< 
            int a() {}
=======
            int c() {}
>>>>>>> 
            end context
            """
        self._test_merge_from_strings(base, a, b, result)

    def test_agreement_deletion(self):
        """Agree to delete some lines, without conflicts."""
        base = """\
            start context
            base line 1
            base line 2
            end context
            """
        a = """\
            start context
            base line 1
            end context
            """
        b = """\
            start context
            base line 1
            end context
            """
        result = """\
            start context
            base line 1
            end context
            """
        self._test_merge_from_strings(base, a, b, result)

    def test_sync_on_deletion(self):
        """Specific case of merge where we can synchronize incorrectly.
        
        A previous version of the weave merge concluded that the two versions
        agreed on deleting line 2, and this could be a synchronization point.
        Line 1 was then considered in isolation, and thought to be deleted on 
        both sides.

        It's better to consider the whole thing as a disagreement region.
        """
        base = """\
            start context
            base line 1
            base line 2
            end context
            """
        a = """\
            start context
            base line 1
            a's replacement line 2
            end context
            """
        b = """\
            start context
            b replaces
            both lines
            end context
            """
        result = """\
            start context
<<<<<<< 
            base line 1
            a's replacement line 2
=======
            b replaces
            both lines
>>>>>>> 
            end context
            """
        self._test_merge_from_strings(base, a, b, result)


class JoinWeavesTests(TestBase):
    def setUp(self):
        super(JoinWeavesTests, self).setUp()
        self.weave1 = Weave()
        self.lines1 = ['hello\n']
        self.lines3 = ['hello\n', 'cruel\n', 'world\n']
        self.weave1.add_lines('v1', [], self.lines1)
        self.weave1.add_lines('v2', ['v1'], ['hello\n', 'world\n'])
        self.weave1.add_lines('v3', ['v2'], self.lines3)
        
    def test_join_empty(self):
        """Join two empty weaves."""
        eq = self.assertEqual
        w1 = Weave()
        w2 = Weave()
        w1.join(w2)
        eq(len(w1), 0)
        
    def test_join_empty_to_nonempty(self):
        """Join empty weave onto nonempty."""
        self.weave1.join(Weave())
        self.assertEqual(len(self.weave1), 3)

    def test_join_unrelated(self):
        """Join two weaves with no history in common."""
        wb = Weave()
        wb.add_lines('b1', [], ['line from b\n'])
        w1 = self.weave1
        w1.join(wb)
        eq = self.assertEqual
        eq(len(w1), 4)
        eq(sorted(w1.versions()),
           ['b1', 'v1', 'v2', 'v3'])

    def test_join_related(self):
        wa = self.weave1.copy()
        wb = self.weave1.copy()
        wa.add_lines('a1', ['v3'], ['hello\n', 'sweet\n', 'world\n'])
        wb.add_lines('b1', ['v3'], ['hello\n', 'pale blue\n', 'world\n'])
        eq = self.assertEquals
        eq(len(wa), 4)
        eq(len(wb), 4)
        wa.join(wb)
        eq(len(wa), 5)
        eq(wa.get_lines('b1'),
           ['hello\n', 'pale blue\n', 'world\n'])

    def test_join_parent_disagreement(self):
        #join reconciles differening parents into a union.
        wa = Weave()
        wb = Weave()
        wa.add_lines('v1', [], ['hello\n'])
        wb.add_lines('v0', [], [])
        wb.add_lines('v1', ['v0'], ['hello\n'])
        wa.join(wb)
        self.assertEqual(['v0'], wa.get_parents('v1'))

    def test_join_text_disagreement(self):
        """Cannot join weaves with different texts for a version."""
        wa = Weave()
        wb = Weave()
        wa.add_lines('v1', [], ['hello\n'])
        wb.add_lines('v1', [], ['not\n', 'hello\n'])
        self.assertRaises(WeaveError,
                          wa.join, wb)

    def test_join_unordered(self):
        """Join weaves where indexes differ.
        
        The source weave contains a different version at index 0."""
        wa = self.weave1.copy()
        wb = Weave()
        wb.add_lines('x1', [], ['line from x1\n'])
        wb.add_lines('v1', [], ['hello\n'])
        wb.add_lines('v2', ['v1'], ['hello\n', 'world\n'])
        wa.join(wb)
        eq = self.assertEquals
        eq(sorted(wa.versions()), ['v1', 'v2', 'v3', 'x1',])
        eq(wa.get_text('x1'), 'line from x1\n')

    def test_written_detection(self):
        # Test detection of weave file corruption.
        #
        # Make sure that we can detect if a weave file has
        # been corrupted. This doesn't test all forms of corruption,
        # but it at least helps verify the data you get, is what you want.
        from cStringIO import StringIO

        w = Weave()
        w.add_lines('v1', [], ['hello\n'])
        w.add_lines('v2', ['v1'], ['hello\n', 'there\n'])

        tmpf = StringIO()
        write_weave(w, tmpf)

        # Because we are corrupting, we need to make sure we have the exact text
        self.assertEquals('# bzr weave file v5\n'
                          'i\n1 f572d396fae9206628714fb2ce00f72e94f2258f\nn v1\n\n'
                          'i 0\n1 90f265c6e75f1c8f9ab76dcf85528352c5f215ef\nn v2\n\n'
                          'w\n{ 0\n. hello\n}\n{ 1\n. there\n}\nW\n',
                          tmpf.getvalue())

        # Change a single letter
        tmpf = StringIO('# bzr weave file v5\n'
                        'i\n1 f572d396fae9206628714fb2ce00f72e94f2258f\nn v1\n\n'
                        'i 0\n1 90f265c6e75f1c8f9ab76dcf85528352c5f215ef\nn v2\n\n'
                        'w\n{ 0\n. hello\n}\n{ 1\n. There\n}\nW\n')

        w = read_weave(tmpf)

        self.assertEqual('hello\n', w.get_text('v1'))
        self.assertRaises(errors.WeaveInvalidChecksum, w.get_text, 'v2')
        self.assertRaises(errors.WeaveInvalidChecksum, w.get_lines, 'v2')
        self.assertRaises(errors.WeaveInvalidChecksum, w.check)

        # Change the sha checksum
        tmpf = StringIO('# bzr weave file v5\n'
                        'i\n1 f572d396fae9206628714fb2ce00f72e94f2258f\nn v1\n\n'
                        'i 0\n1 f0f265c6e75f1c8f9ab76dcf85528352c5f215ef\nn v2\n\n'
                        'w\n{ 0\n. hello\n}\n{ 1\n. there\n}\nW\n')

        w = read_weave(tmpf)

        self.assertEqual('hello\n', w.get_text('v1'))
        self.assertRaises(errors.WeaveInvalidChecksum, w.get_text, 'v2')
        self.assertRaises(errors.WeaveInvalidChecksum, w.get_lines, 'v2')
        self.assertRaises(errors.WeaveInvalidChecksum, w.check)


class InstrumentedWeave(Weave):
    """Keep track of how many times functions are called."""
    
    def __init__(self, weave_name=None):
        self._extract_count = 0
        Weave.__init__(self, weave_name=weave_name)

    def _extract(self, versions):
        self._extract_count += 1
        return Weave._extract(self, versions)


class JoinOptimization(TestCase):
    """Test that Weave.join() doesn't extract all texts, only what must be done."""

    def test_join(self):
        w1 = InstrumentedWeave()
        w2 = InstrumentedWeave()

        txt0 = ['a\n']
        txt1 = ['a\n', 'b\n']
        txt2 = ['a\n', 'c\n']
        txt3 = ['a\n', 'b\n', 'c\n']

        w1.add_lines('txt0', [], txt0) # extract 1a
        w2.add_lines('txt0', [], txt0) # extract 1b
        w1.add_lines('txt1', ['txt0'], txt1)# extract 2a
        w2.add_lines('txt2', ['txt0'], txt2)# extract 2b
        w1.join(w2) # extract 3a to add txt2 
        w2.join(w1) # extract 3b to add txt1 

        w1.add_lines('txt3', ['txt1', 'txt2'], txt3) # extract 4a 
        w2.add_lines('txt3', ['txt2', 'txt1'], txt3) # extract 4b
        # These secretly have inverted parents

        # This should not have to do any extractions
        w1.join(w2) # NO extract, texts already present with same parents
        w2.join(w1) # NO extract, texts already present with same parents

        self.assertEqual(4, w1._extract_count)
        self.assertEqual(4, w2._extract_count)

    def test_double_parent(self):
        # It should not be considered illegal to add
        # a revision with the same parent twice
        w1 = InstrumentedWeave()
        w2 = InstrumentedWeave()

        txt0 = ['a\n']
        txt1 = ['a\n', 'b\n']
        txt2 = ['a\n', 'c\n']
        txt3 = ['a\n', 'b\n', 'c\n']

        w1.add_lines('txt0', [], txt0)
        w2.add_lines('txt0', [], txt0)
        w1.add_lines('txt1', ['txt0'], txt1)
        w2.add_lines('txt1', ['txt0', 'txt0'], txt1)
        # Same text, effectively the same, because the
        # parent is only repeated
        w1.join(w2) # extract 3a to add txt2 
        w2.join(w1) # extract 3b to add txt1 


class TestNeedsReweave(TestCase):
    """Internal corner cases for when reweave is needed."""

    def test_compatible_parents(self):
        w1 = Weave('a')
        my_parents = set([1, 2, 3])
        # subsets are ok
        self.assertTrue(w1._compatible_parents(my_parents, set([3])))
        # same sets
        self.assertTrue(w1._compatible_parents(my_parents, set(my_parents)))
        # same empty corner case
        self.assertTrue(w1._compatible_parents(set(), set()))
        # other cannot contain stuff my_parents does not
        self.assertFalse(w1._compatible_parents(set(), set([1])))
        self.assertFalse(w1._compatible_parents(my_parents, set([1, 2, 3, 4])))
        self.assertFalse(w1._compatible_parents(my_parents, set([4])))
