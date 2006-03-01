# Copyright (C) 2005 by Canonical Ltd
#
# Authors:
#   Johan Rydberg <jrydberg@gnu.org>
#
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

# Remaing to do is to figure out if get_graph should return a simple
# map, or a graph object of some kind.


import bzrlib
import bzrlib.errors as errors
from bzrlib.errors import (
                           RevisionNotPresent, 
                           RevisionAlreadyPresent,
                           WeaveParentMismatch
                           )
from bzrlib.knit import KnitVersionedFile, \
     KnitAnnotateFactory
from bzrlib.tests import TestCaseInTempDir
from bzrlib.trace import mutter
from bzrlib.transport.local import LocalTransport
from bzrlib.weave import WeaveFile
from bzrlib.weavefile import read_weave


class VersionedFileTestMixIn(object):
    """A mixin test class for testing VersionedFiles.

    This is not an adaptor-style test at this point because
    theres no dynamic substitution of versioned file implementations,
    they are strictly controlled by their owning repositories.
    """

    def test_add(self):
        f = self.get_file()
        f.add_lines('r0', [], ['a\n', 'b\n'])
        f.add_lines('r1', ['r0'], ['b\n', 'c\n'])
        def verify_file(f):
            versions = f.versions()
            self.assertTrue('r0' in versions)
            self.assertTrue('r1' in versions)
            self.assertEquals(f.get_lines('r0'), ['a\n', 'b\n'])
            self.assertEquals(f.get_text('r0'), 'a\nb\n')
            self.assertEquals(f.get_lines('r1'), ['b\n', 'c\n'])
    
            self.assertRaises(RevisionNotPresent,
                f.add_lines, 'r2', ['foo'], [])
            self.assertRaises(RevisionAlreadyPresent,
                f.add_lines, 'r1', [], [])
        verify_file(f)
        f = self.reopen_file()
        verify_file(f)

    def test_ancestry(self):
        f = self.get_file()
        f.add_lines('r0', [], ['a\n', 'b\n'])
        f.add_lines('r1', ['r0'], ['b\n', 'c\n'])
        f.add_lines('r2', ['r0'], ['b\n', 'c\n'])
        f.add_lines('r3', ['r2'], ['b\n', 'c\n'])
        f.add_lines('rM', ['r1', 'r2'], ['b\n', 'c\n'])
        versions = set(f.get_ancestry(['rM']))
        self.assertEquals(versions, set(['rM', 'r2', 'r1', 'r0']))

        self.assertRaises(RevisionNotPresent,
            f.get_ancestry, ['rM', 'rX'])
        
    def test_clear_cache(self):
        f = self.get_file()
        # on a new file it should not error
        f.clear_cache()
        # and after adding content, doing a clear_cache and a get should work.
        f.add_lines('0', [], ['a'])
        f.clear_cache()
        self.assertEqual(['a'], f.get_lines('0'))

    def test_clone_text(self):
        f = self.get_file()
        f.add_lines('r0', [], ['a\n', 'b\n'])
        f.clone_text('r1', 'r0', ['r0'])
        def verify_file(f):
            self.assertEquals(f.get_lines('r1'), f.get_lines('r0'))
            self.assertEquals(f.get_lines('r1'), ['a\n', 'b\n'])
            self.assertEquals(f.get_parents('r1'), ['r0'])
    
            self.assertRaises(RevisionNotPresent,
                f.clone_text, 'r2', 'rX', [])
            self.assertRaises(RevisionAlreadyPresent,
                f.clone_text, 'r1', 'r0', [])
        verify_file(f)
        verify_file(self.reopen_file())

    def test_get_parents(self):
        f = self.get_file()
        f.add_lines('r0', [], ['a\n', 'b\n'])
        f.add_lines('r1', [], ['a\n', 'b\n'])
        f.add_lines('r2', [], ['a\n', 'b\n'])
        f.add_lines('r3', [], ['a\n', 'b\n'])
        f.add_lines('m', ['r0', 'r1', 'r2', 'r3'], ['a\n', 'b\n'])
        self.assertEquals(f.get_parents('m'), ['r0', 'r1', 'r2', 'r3'])

        self.assertRaises(RevisionNotPresent,
            f.get_parents, 'y')

    def test_annotate(self):
        f = self.get_file()
        f.add_lines('r0', [], ['a\n', 'b\n'])
        f.add_lines('r1', ['r0'], ['c\n', 'b\n'])
        origins = f.annotate('r1')
        self.assertEquals(origins[0][0], 'r1')
        self.assertEquals(origins[1][0], 'r0')

        self.assertRaises(RevisionNotPresent,
            f.annotate, 'foo')

    def test_join(self):
        f1 = self.get_file('1')
        f1.add_lines('r0', [], ['a\n', 'b\n'])
        f1.add_lines('r1', ['r0'], ['c\n', 'b\n'])
        f2 = self.get_file('2')
        f2.join(f1, None)
        def verify_file(f):
            self.assertTrue(f.has_version('r0'))
            self.assertTrue(f.has_version('r1'))
        verify_file(f2)
        verify_file(self.reopen_file('2'))

        self.assertRaises(RevisionNotPresent,
            f2.join, f1, version_ids=['r3'])

        #f3 = self.get_file('1')
        #f3.add_lines('r0', ['a\n', 'b\n'], [])
        #f3.add_lines('r1', ['c\n', 'b\n'], ['r0'])
        #f4 = self.get_file('2')
        #f4.join(f3, ['r0'])
        #self.assertTrue(f4.has_version('r0'))
        #self.assertFalse(f4.has_version('r1'))

    def test_walk(self):
        f = self.get_file('1')
        f.add_lines('r0', [], ['a\n', 'b\n'])
        f.add_lines('r1', ['r0'], ['c\n', 'b\n'])
        f.add_lines('rX', ['r1'], ['d\n', 'b\n'])
        f.add_lines('rY', ['r1'], ['c\n', 'e\n'])

        lines = {}
        for lineno, insert, dset, text in f.walk(['rX', 'rY']):
            lines[text] = (insert, dset)

        self.assertTrue(lines['a\n'], ('r0', set(['r1'])))
        self.assertTrue(lines['b\n'], ('r0', set(['rY'])))
        self.assertTrue(lines['c\n'], ('r1', set(['rX'])))
        self.assertTrue(lines['d\n'], ('rX', set([])))
        self.assertTrue(lines['e\n'], ('rY', set([])))

    def test_detection(self):
        # Test weaves detect corruption.
        #
        # Weaves contain a checksum of their texts.
        # When a text is extracted, this checksum should be
        # verified.

        w = self.get_file_corrupted_text()

        self.assertEqual('hello\n', w.get_text('v1'))
        self.assertRaises(errors.WeaveInvalidChecksum, w.get_text, 'v2')
        self.assertRaises(errors.WeaveInvalidChecksum, w.get_lines, 'v2')
        self.assertRaises(errors.WeaveInvalidChecksum, list, w.get_iter('v2'))
        self.assertRaises(errors.WeaveInvalidChecksum, w.check)

        w = self.get_file_corrupted_checksum()

        self.assertEqual('hello\n', w.get_text('v1'))
        self.assertRaises(errors.WeaveInvalidChecksum, w.get_text, 'v2')
        self.assertRaises(errors.WeaveInvalidChecksum, w.get_lines, 'v2')
        self.assertRaises(errors.WeaveInvalidChecksum, list, w.get_iter('v2'))
        self.assertRaises(errors.WeaveInvalidChecksum, w.check)

    def get_file_corrupted_text(self):
        """Return a versioned file with corrupt text but valid metadata."""
        raise NotImplementedError(self.get_file_corrupted_text)

    def reopen_file(self, name='foo'):
        """Open the versioned file from disk again."""
        raise NotImplementedError(self.reopen_file)

    def test_join_add_parents(self):
        """Reweave inserting new parents
        
        The new version must have the right parent list and must identify
        lines originating in another parent.
        """
        w1 = self.get_file('w1')
        w2 = self.get_file('w2')
        w1.add_lines('v-1', [], ['line 1\n'])
        w2.add_lines('v-2', [], ['line 2\n'])
        w1.add_lines('v-3', ['v-1'], ['line 1\n'])
        w2.add_lines('v-3', ['v-2'], ['line 1\n'])
        w1.join(w2)
        self.assertEqual(sorted(w1.names()),
                         'v-1 v-2 v-3'.split())
        self.assertEqualDiff(w1.get_text('v-3'),
                'line 1\n')
        self.assertEqual(sorted(w1.parent_names('v-3')),
                ['v-1', 'v-2'])
        ann = list(w1.annotate('v-3'))
        self.assertEqual(len(ann), 1)
        self.assertEqual(ann[0][0], 'v-1')
        self.assertEqual(ann[0][1], 'line 1\n')
        
    def build_weave1(self):
        weave1 = self.get_file()
        self.lines1 = ['hello\n']
        self.lines3 = ['hello\n', 'cruel\n', 'world\n']
        weave1.add_lines('v1', [], self.lines1)
        weave1.add_lines('v2', ['v1'], ['hello\n', 'world\n'])
        weave1.add_lines('v3', ['v2'], self.lines3)
        return weave1
        
    def test_join_with_empty(self):
        """Reweave adding empty weave"""
        wb = self.get_file('b')
        w1 = self.build_weave1()
        w1.join(wb)
        self.assertEqual(sorted(w1.iter_names()), ['v1', 'v2', 'v3'])
        self.assertEqual(w1.get_lines('v1'), ['hello\n'])
        self.assertEqual([], w1.get_parents('v1'))
        self.assertEqual(w1.get_lines('v2'), ['hello\n', 'world\n'])
        self.assertEqual(['v1'], w1.get_parents('v2'))
        self.assertEqual(w1.get_lines('v3'), ['hello\n', 'cruel\n', 'world\n'])
        self.assertEqual(['v2'], w1.get_parents('v3'))

    def test_join_with_ghosts_raises_parent_mismatch(self):
        """Join combined parent lists"""
        wa = self.build_weave1()
        wb = self.get_file('b')
        wb.add_lines('x1', [], ['line from x1\n'])
        wb.add_lines('v1', [], ['hello\n'])
        wb.add_lines('v2', ['v1', 'x1'], ['hello\n', 'world\n'])
        wa.join(wb)
        self.assertEqual(['v1','x1'], wa.get_parents('v2'))

    def test_join_with_ghosts(self):
        """Join that inserts parents of an existing revision.

        This can happen when merging from another branch who
        knows about revisions the destination does not.  In 
        this test the second weave knows of an additional parent of 
        v2.  Any revisions which are in common still have to have the 
        same text.
        """
        w1 = self.build_weave1()
        wb = self.get_file('b')
        wb.add_lines('x1', [], ['line from x1\n'])
        wb.add_lines('v1', [], ['hello\n'])
        wb.add_lines('v2', ['v1', 'x1'], ['hello\n', 'world\n'])
        w1.join(wb)
        eq = self.assertEquals
        eq(sorted(w1.iter_names()), ['v1', 'v2', 'v3', 'x1',])
        eq(w1.get_text('x1'), 'line from x1\n')
        eq(w1.get_lines('v2'), ['hello\n', 'world\n'])
        eq(w1.parent_names('v2'), ['v1', 'x1'])

    def build_empty_weave(self, name, *pattern):
        w = self.get_file(name)
        for version, parents in pattern:
            w.add_lines(version, parents, [])
        return w

    def test_join_reorder(self):
        """Reweave requiring reordering of versions.

        Weaves must be stored such that parents come before children.  When
        reweaving, we may add new parents to some children, but it is required
        that there must be *some* valid order that can be found, otherwise the
        ancestries are contradictory.  (For the specific case of inserting
        ghost revisions there will be no disagreement, only partial knowledge
        of the history.)

        Note that the weaves are only partially ordered: when there are two
        versions where neither is an ancestor of the other the order in which
        they occur is unconstrained.  When we join those versions into
        another weave, they may become more constrained and it may be
        necessary to change their order.

        One simple case of this is 

        w1: (c[], a[], b[a])
        w2: (b[], c[b], a[])
        
        We need to recognize that the final weave must show the ordering
        a[], b[a], c[b].  The version that must be first in the result is 
        not first in either of the input weaves.
        """
        w1 = self.build_empty_weave('1', ('c', []), ('a', []), ('b', ['a']))
        w2 = self.build_empty_weave('2', ('b', []), ('c', ['b']), ('a', []))
        w1.join(w2)
        self.assertEqual([], w1.get_parents('a'))
        self.assertEqual(['a'], w1.get_parents('b'))
        self.assertEqual(['b'], w1.get_parents('c'))

class TestWeave(TestCaseInTempDir, VersionedFileTestMixIn):

    def get_file(self, name='foo'):
        return WeaveFile(name, LocalTransport('.'))

    def get_file_corrupted_text(self):
        w = WeaveFile('foo', LocalTransport('.'))
        w.add('v1', [], ['hello\n'])
        w.add('v2', ['v1'], ['hello\n', 'there\n'])
        
        # We are going to invasively corrupt the text
        # Make sure the internals of weave are the same
        self.assertEqual([('{', 0)
                        , 'hello\n'
                        , ('}', None)
                        , ('{', 1)
                        , 'there\n'
                        , ('}', None)
                        ], w._weave)
        
        self.assertEqual(['f572d396fae9206628714fb2ce00f72e94f2258f'
                        , '90f265c6e75f1c8f9ab76dcf85528352c5f215ef'
                        ], w._sha1s)
        w.check()
        
        # Corrupted
        w._weave[4] = 'There\n'
        return w

    def get_file_corrupted_checksum(self):
        w = self.get_file_corrupted_text()
        # Corrected
        w._weave[4] = 'there\n'
        self.assertEqual('hello\nthere\n', w.get_text('v2'))
        
        #Invalid checksum, first digit changed
        w._sha1s[1] =  'f0f265c6e75f1c8f9ab76dcf85528352c5f215ef'
        return w

    def reopen_file(self, name='foo'):
        return WeaveFile(name, LocalTransport('.'))


class TestKnit(TestCaseInTempDir, VersionedFileTestMixIn):

    def get_file(self, name='foo'):
        return KnitVersionedFile(LocalTransport('.'),
            name, 'w', KnitAnnotateFactory(), delta=True)

    def get_file_corrupted_text(self):
        knit = self.get_file()
        knit.add_lines('v1', [], ['hello\n'])
        knit.add_lines('v2', ['v1'], ['hello\n', 'there\n'])
        return knit

    def reopen_file(self, name='foo'):
        return KnitVersionedFile(LocalTransport('.'),
            name, 'w', KnitAnnotateFactory(), delta=True)

    def test_detection(self):
        print "TODO for merging: create a corrupted knit."
