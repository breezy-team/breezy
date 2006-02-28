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


from bzrlib.tests import TestCaseInTempDir
from bzrlib.weave import Weave
from bzrlib.transactions import PassThroughTransaction
from bzrlib.trace import mutter
from bzrlib.knit import KnitVersionedFile, \
     KnitAnnotateFactory
from bzrlib.transport.local import LocalTransport
from bzrlib.errors import RevisionNotPresent, \
     RevisionAlreadyPresent


class VersionedFileTestMixIn(object):
    """A mixin test class for testing VersionedFiles.

    This is not an adaptor-style test at this point because
    theres no dynamic substitution of versioned file implementations,
    they are strictly controlled by their owning repositories.
    """

    def test_add(self):
        t = PassThroughTransaction()
        f = self.get_file()
        f.add_lines('r0', [], ['a\n', 'b\n'])
        f.add_lines('r1', ['r0'], ['b\n', 'c\n'])
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

    def test_ancestry(self):
        t = PassThroughTransaction()
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

    def test_clone_text(self):
        t = PassThroughTransaction()
        f = self.get_file()
        f.add_lines('r0', [], ['a\n', 'b\n'])
        f.clone_text('r1', 'r0', ['r0'], t)
        self.assertEquals(f.get_lines('r1'), f.get_lines('r0'))
        self.assertEquals(f.get_lines('r1'), ['a\n', 'b\n'])
        self.assertEquals(f.get_parents('r1'), ['r0'])

        self.assertRaises(RevisionNotPresent,
            f.clone_text, 'r2', 'rX', [], t)
        self.assertRaises(RevisionAlreadyPresent,
            f.clone_text, 'r1', 'r0', [], t)

    def test_get_parents(self):
        t = PassThroughTransaction()
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
        t = PassThroughTransaction()
        f = self.get_file()
        f.add_lines('r0', [], ['a\n', 'b\n'])
        f.add_lines('r1', ['r0'], ['c\n', 'b\n'])
        origins = f.annotate('r1')
        self.assertEquals(origins[0][0], 'r1')
        self.assertEquals(origins[1][0], 'r0')

        self.assertRaises(RevisionNotPresent,
            f.annotate, 'foo')

    def test_join(self):
        t = PassThroughTransaction()
        f1 = self.get_file('1')
        f1.add_lines('r0', [], ['a\n', 'b\n'])
        f1.add_lines('r1', ['r0'], ['c\n', 'b\n'])
        f2 = self.get_file('2')
        f2.join(f1, None, t)
        self.assertTrue(f2.has_version('r0'))
        self.assertTrue(f2.has_version('r1'))

        self.assertRaises(RevisionNotPresent,
            f2.join, f1, version_ids=['r3'])


        #f3 = self.get_file('1')
        #f3.add_lines('r0', ['a\n', 'b\n'], [], t)
        #f3.add_lines('r1', ['c\n', 'b\n'], ['r0'], t)
        #f4 = self.get_file('2')
        #f4.join(f3, ['r0'], t)
        #self.assertTrue(f4.has_version('r0'))
        #self.assertFalse(f4.has_version('r1'))

    def test_walk(self):
        t = PassThroughTransaction()
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


class TestWeave(TestCaseInTempDir, VersionedFileTestMixIn):

    def get_file(self, name='foo'):
        return Weave(name)


class TestKnit(TestCaseInTempDir, VersionedFileTestMixIn):

    def get_file(self, name='foo'):
        t = PassThroughTransaction()
        return KnitVersionedFile(LocalTransport('.'),
            name, 'w', KnitAnnotateFactory(), t, delta=True)
