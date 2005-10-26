# Copyright (C) 2005 by Canonical Ltd
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Test reweave code.

Reweave takes two weaves containing a partial view of history and combines
them into a single weave containing all the information.  This can include 

 - versions recorded in only one file

 - versions with different (but not contradictory) lists of parent 
   revisions

It is an error if either of these conditions occur:

 - contradictory ancestry graphs, e.g.
   - v1 is an ancestor of v2 in one weave, and vice versa in the other
   - different text for any version 
"""

import os
import sys

from bzrlib.selftest import TestCaseInTempDir
from bzrlib.weave import Weave, reweave
from bzrlib.weavefile import read_weave
from bzrlib.errors import WeaveParentMismatch

class TestReweave(TestCaseInTempDir):

    def test_reweave_add_parents(self):
        """Reweave inserting new parents
        
        The new version must have the right parent list and must identify
        lines originating in another parent.
        """
        w1 = Weave('w1')
        w2 = Weave('w2')
        w1.add('v-1', [], ['line 1\n'])
        w2.add('v-2', [], ['line 2\n'])
        w1.add('v-3', ['v-1'], ['line 1\n'])
        w2.add('v-3', ['v-2'], ['line 1\n'])
        w3 = reweave(w1, w2)
        self.assertEqual(sorted(w3.names()),
                         'v-1 v-2 v-3'.split())
        self.assertEqualDiff(w3.get_text('v-3'),
                'line 1\n')
        self.assertEqual(sorted(w3.parent_names('v-3')),
                ['v-1', 'v-2'])
        ann = list(w3.annotate('v-3'))
        self.assertEqual(len(ann), 1)
        self.assertEqual(w3.idx_to_name(ann[0][0]), 'v-1')
        self.assertEqual(ann[0][1], 'line 1\n')
        
    def build_weave1(self):
        weave1 = Weave()
        self.lines1 = ['hello\n']
        self.lines3 = ['hello\n', 'cruel\n', 'world\n']
        weave1.add('v1', [], self.lines1)
        weave1.add('v2', [0], ['hello\n', 'world\n'])
        weave1.add('v3', [1], self.lines3)
        return weave1
        
    def test_reweave_with_empty(self):
        """Reweave adding empty weave"""
        wb = Weave()
        w1 = self.build_weave1()
        wr = reweave(w1, wb)
        eq = self.assertEquals
        eq(sorted(wr.iter_names()), ['v1', 'v2', 'v3'])
        eq(wr.get_lines('v3'), ['hello\n', 'cruel\n', 'world\n'])
        self.assertEquals(wr, w1)

    def test_join_with_ghosts_raises_parent_mismatch(self):
        """Join weave traps parent mismatch"""
        wa = self.build_weave1()
        wb = Weave()
        wb.add('x1', [], ['line from x1\n'])
        wb.add('v1', [], ['hello\n'])
        wb.add('v2', ['v1', 'x1'], ['hello\n', 'world\n'])
        self.assertRaises(WeaveParentMismatch, wa.join, wb)

    def test_reweave_with_ghosts(self):
        """Join that inserts parents of an existing revision.

        This can happen when merging from another branch who
        knows about revisions the destination does not.  In 
        this test the second weave knows of an additional parent of 
        v2.  Any revisions which are in common still have to have the 
        same text.
        """
        w1 = self.build_weave1()
        wa = w1.copy()
        wb = Weave()
        wb.add('x1', [], ['line from x1\n'])
        wb.add('v1', [], ['hello\n'])
        wb.add('v2', ['v1', 'x1'], ['hello\n', 'world\n'])
        wc = reweave(wa, wb)
        eq = self.assertEquals
        eq(sorted(wc.iter_names()), ['v1', 'v2', 'v3', 'x1',])
        eq(wc.get_text('x1'), 'line from x1\n')
        eq(wc.get_lines('v2'), ['hello\n', 'world\n'])
        eq(wc.parent_names('v2'), ['v1', 'x1'])
        w1.reweave(wb)
        self.assertEquals(wc, w1)
