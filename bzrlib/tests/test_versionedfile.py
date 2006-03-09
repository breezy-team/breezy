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


import bzrlib
import bzrlib.errors as errors
from bzrlib.errors import (
                           RevisionNotPresent, 
                           RevisionAlreadyPresent,
                           WeaveParentMismatch
                           )
from bzrlib.knit import KnitVersionedFile, \
     KnitAnnotateFactory
from bzrlib.tests import TestCaseWithTransport
from bzrlib.trace import mutter
from bzrlib.transport import get_transport
from bzrlib.transport.memory import MemoryTransport
import bzrlib.versionedfile as versionedfile
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
            self.assertEqual(2, len(f))
            self.assertEqual(2, f.num_versions())
    
            self.assertRaises(RevisionNotPresent,
                f.add_lines, 'r2', ['foo'], [])
            self.assertRaises(RevisionAlreadyPresent,
                f.add_lines, 'r1', [], [])
        verify_file(f)
        f = self.reopen_file()
        verify_file(f)

    def test_ancestry(self):
        f = self.get_file()
        self.assertEqual([], f.get_ancestry([]))
        f.add_lines('r0', [], ['a\n', 'b\n'])
        f.add_lines('r1', ['r0'], ['b\n', 'c\n'])
        f.add_lines('r2', ['r0'], ['b\n', 'c\n'])
        f.add_lines('r3', ['r2'], ['b\n', 'c\n'])
        f.add_lines('rM', ['r1', 'r2'], ['b\n', 'c\n'])
        self.assertEqual([], f.get_ancestry([]))
        versions = f.get_ancestry(['rM'])
        # there are some possibilities:
        # r0 r1 r2 rM r3
        # r0 r1 r2 r3 rM
        # etc
        # so we check indexes
        r0 = versions.index('r0')
        r1 = versions.index('r1')
        r2 = versions.index('r2')
        self.assertFalse('r3' in versions)
        rM = versions.index('rM')
        self.assertTrue(r0 < r1)
        self.assertTrue(r0 < r2)
        self.assertTrue(r1 < rM)
        self.assertTrue(r2 < rM)

        self.assertRaises(RevisionNotPresent,
            f.get_ancestry, ['rM', 'rX'])

    def test_mutate_after_finish(self):
        f = self.get_file()
        f.transaction_finished()
        self.assertRaises(errors.OutSideTransaction, f.add_lines, '', [], [])
        self.assertRaises(errors.OutSideTransaction, f.add_lines_with_ghosts, '', [], [])
        self.assertRaises(errors.OutSideTransaction, f.fix_parents, '', [])
        self.assertRaises(errors.OutSideTransaction, f.join, '')
        self.assertRaises(errors.OutSideTransaction, f.clone_text, 'base', 'bar', ['foo'])
        
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

    def test_create_empty(self):
        f = self.get_file()
        f.add_lines('0', [], ['a\n'])
        new_f = f.create_empty('t', MemoryTransport())
        # smoke test, specific types should check it is honoured correctly for
        # non type attributes
        self.assertEqual([], new_f.versions())
        self.assertTrue(isinstance(new_f, f.__class__))

    def test_copy_to(self):
        f = self.get_file()
        f.add_lines('0', [], ['a\n'])
        t = MemoryTransport()
        f.copy_to('foo', t)
        for suffix in f.__class__.get_suffixes():
            self.assertTrue(t.has('foo' + suffix))

    def test_get_suffixes(self):
        f = self.get_file()
        # should be the same
        self.assertEqual(f.__class__.get_suffixes(), f.__class__.get_suffixes())
        # and should be a list
        self.assertTrue(isinstance(f.__class__.get_suffixes(), list))

    def test_get_graph(self):
        f = self.get_file()
        f.add_lines('v1', [], ['hello\n'])
        f.add_lines('v2', ['v1'], ['hello\n', 'world\n'])
        f.add_lines('v3', ['v2'], ['hello\n', 'cruel\n', 'world\n'])
        self.assertEqual({'v1': [],
                          'v2': ['v1'],
                          'v3': ['v2']},
                         f.get_graph())

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

    def test_walk(self):
        # tests that walk returns all the inclusions for the requested
        # revisions as well as the revisions changes themselves.
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
        self.assertRaises(errors.WeaveInvalidChecksum, w.check)

        w = self.get_file_corrupted_checksum()

        self.assertEqual('hello\n', w.get_text('v1'))
        self.assertRaises(errors.WeaveInvalidChecksum, w.get_text, 'v2')
        self.assertRaises(errors.WeaveInvalidChecksum, w.get_lines, 'v2')
        self.assertRaises(errors.WeaveInvalidChecksum, w.check)

    def get_file_corrupted_text(self):
        """Return a versioned file with corrupt text but valid metadata."""
        raise NotImplementedError(self.get_file_corrupted_text)

    def reopen_file(self, name='foo'):
        """Open the versioned file from disk again."""
        raise NotImplementedError(self.reopen_file)

    def test_iter_lines_added_or_present_in_versions(self):
        # test that we get at least an equalset of the lines added by
        # versions in the weave 
        # the ordering here is to make a tree so that dumb searches have
        # more changes to muck up.
        vf = self.get_file()
        # add a base to get included
        vf.add_lines('base', [], ['base\n'])
        # add a ancestor to be included on one side
        vf.add_lines('lancestor', [], ['lancestor\n'])
        # add a ancestor to be included on the other side
        vf.add_lines('rancestor', ['base'], ['rancestor\n'])
        # add a child of rancestor with no eofile-nl
        vf.add_lines('child', ['rancestor'], ['base\n', 'child\n'])
        # add a child of lancestor and base to join the two roots
        vf.add_lines('otherchild',
                     ['lancestor', 'base'],
                     ['base\n', 'lancestor\n', 'otherchild\n'])
        def iter_with_versions(versions):
            # now we need to see what lines are returned, and how often.
            lines = {'base\n':0,
                     'lancestor\n':0,
                     'rancestor\n':0,
                     'child\n':0,
                     'otherchild\n':0,
                     }
            # iterate over the lines
            for line in vf.iter_lines_added_or_present_in_versions(versions):
                lines[line] += 1
            return lines
        lines = iter_with_versions(['child', 'otherchild'])
        # we must see child and otherchild
        self.assertTrue(lines['child\n'] > 0)
        self.assertTrue(lines['otherchild\n'] > 0)
        # we dont care if we got more than that.
        
        # test all lines
        lines = iter_with_versions(None)
        # all lines must be seen at least once
        self.assertTrue(lines['base\n'] > 0)
        self.assertTrue(lines['lancestor\n'] > 0)
        self.assertTrue(lines['rancestor\n'] > 0)
        self.assertTrue(lines['child\n'] > 0)
        self.assertTrue(lines['otherchild\n'] > 0)

    def test_fix_parents(self):
        # some versioned files allow incorrect parents to be corrected after
        # insertion - this may not fix ancestry..
        # if they do not supported, they just do not implement it.
        # we test this as an interface test to ensure that those that *do*
        # implementent it get it right.
        vf = self.get_file()
        vf.add_lines('notbase', [], [])
        vf.add_lines('base', [], [])
        try:
            vf.fix_parents('notbase', ['base'])
        except NotImplementedError:
            return
        self.assertEqual(['base'], vf.get_parents('notbase'))
        # open again, check it stuck.
        vf = self.get_file()
        self.assertEqual(['base'], vf.get_parents('notbase'))

    def test_fix_parents_with_ghosts(self):
        # when fixing parents, ghosts that are listed should not be ghosts
        # anymore.
        vf = self.get_file()

        try:
            vf.add_lines_with_ghosts('notbase', ['base', 'stillghost'], [])
        except NotImplementedError:
            return
        vf.add_lines('base', [], [])
        vf.fix_parents('notbase', ['base', 'stillghost'])
        self.assertEqual(['base'], vf.get_parents('notbase'))
        # open again, check it stuck.
        vf = self.get_file()
        self.assertEqual(['base'], vf.get_parents('notbase'))
        # and check the ghosts
        self.assertEqual(['base', 'stillghost'],
                         vf.get_parents_with_ghosts('notbase'))

    def test_add_lines_with_ghosts(self):
        # some versioned file formats allow lines to be added with parent
        # information that is > than that in the format. Formats that do
        # not support this need to raise NotImplementedError on the
        # add_lines_with_ghosts api.
        vf = self.get_file()
        # add a revision with ghost parents
        try:
            vf.add_lines_with_ghosts('notbase', ['base'], [])
        except NotImplementedError:
            # check the other ghost apis are also not implemented
            self.assertRaises(NotImplementedError, vf.has_ghost, 'foo')
            self.assertRaises(NotImplementedError, vf.get_ancestry_with_ghosts, ['foo'])
            self.assertRaises(NotImplementedError, vf.get_parents_with_ghosts, 'foo')
            self.assertRaises(NotImplementedError, vf.get_graph_with_ghosts)
            return
        # test key graph related apis: getncestry, _graph, get_parents
        # has_version
        # - these are ghost unaware and must not be reflect ghosts
        self.assertEqual(['notbase'], vf.get_ancestry('notbase'))
        self.assertEqual([], vf.get_parents('notbase'))
        self.assertEqual({'notbase':[]}, vf.get_graph())
        self.assertFalse(vf.has_version('base'))
        # we have _with_ghost apis to give us ghost information.
        self.assertEqual(['base', 'notbase'], vf.get_ancestry_with_ghosts(['notbase']))
        self.assertEqual(['base'], vf.get_parents_with_ghosts('notbase'))
        self.assertEqual({'notbase':['base']}, vf.get_graph_with_ghosts())
        self.assertTrue(vf.has_ghost('base'))
        # if we add something that is a ghost of another, it should correct the
        # results of the prior apis
        vf.add_lines('base', [], [])
        self.assertEqual(['base', 'notbase'], vf.get_ancestry(['notbase']))
        self.assertEqual(['base'], vf.get_parents('notbase'))
        self.assertEqual({'base':[],
                          'notbase':['base'],
                          },
                         vf.get_graph())
        self.assertTrue(vf.has_version('base'))
        # we have _with_ghost apis to give us ghost information.
        self.assertEqual(['base', 'notbase'], vf.get_ancestry_with_ghosts(['notbase']))
        self.assertEqual(['base'], vf.get_parents_with_ghosts('notbase'))
        self.assertEqual({'base':[],
                          'notbase':['base'],
                          },
                         vf.get_graph_with_ghosts())
        self.assertFalse(vf.has_ghost('base'))

    def test_add_lines_with_ghosts_after_normal_revs(self):
        # some versioned file formats allow lines to be added with parent
        # information that is > than that in the format. Formats that do
        # not support this need to raise NotImplementedError on the
        # add_lines_with_ghosts api.
        vf = self.get_file()
        # probe for ghost support
        try:
            vf.has_ghost('hoo')
        except NotImplementedError:
            return
        vf.add_lines_with_ghosts('base', [], ['line\n', 'line_b\n'])
        vf.add_lines_with_ghosts('references_ghost',
                                 ['base', 'a_ghost'],
                                 ['line\n', 'line_b\n', 'line_c\n'])
        origins = vf.annotate('references_ghost')
        self.assertEquals(('base', 'line\n'), origins[0])
        self.assertEquals(('base', 'line_b\n'), origins[1])
        self.assertEquals(('references_ghost', 'line_c\n'), origins[2])

    def test_readonly_mode(self):
        transport = get_transport(self.get_url('.'))
        factory = self.get_factory()
        vf = factory('id', transport, 0777, create=True, access_mode='w')
        vf = factory('id', transport, access_mode='r')
        self.assertRaises(errors.ReadOnlyError, vf.add_lines, 'base', [], [])
        self.assertRaises(errors.ReadOnlyError,
                          vf.add_lines_with_ghosts,
                          'base',
                          [],
                          [])
        self.assertRaises(errors.ReadOnlyError, vf.fix_parents, 'base', [])
        self.assertRaises(errors.ReadOnlyError, vf.join, 'base')
        self.assertRaises(errors.ReadOnlyError, vf.clone_text, 'base', 'bar', ['foo'])
        

class TestWeave(TestCaseWithTransport, VersionedFileTestMixIn):

    def get_file(self, name='foo'):
        return WeaveFile(name, get_transport(self.get_url('.')), create=True)

    def get_file_corrupted_text(self):
        w = WeaveFile('foo', get_transport(self.get_url('.')), create=True)
        w.add_lines('v1', [], ['hello\n'])
        w.add_lines('v2', ['v1'], ['hello\n', 'there\n'])
        
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
        return WeaveFile(name, get_transport(self.get_url('.')))

    def test_no_implicit_create(self):
        self.assertRaises(errors.NoSuchFile,
                          WeaveFile,
                          'foo',
                          get_transport(self.get_url('.')))

    def get_factory(self):
        return WeaveFile


class TestKnit(TestCaseWithTransport, VersionedFileTestMixIn):

    def get_file(self, name='foo'):
        return KnitVersionedFile(name, get_transport(self.get_url('.')),
                                 delta=True, create=True)

    def get_factory(self):
        return KnitVersionedFile

    def get_file_corrupted_text(self):
        knit = self.get_file()
        knit.add_lines('v1', [], ['hello\n'])
        knit.add_lines('v2', ['v1'], ['hello\n', 'there\n'])
        return knit

    def reopen_file(self, name='foo'):
        return KnitVersionedFile(name, get_transport(self.get_url('.')), delta=True)

    def test_detection(self):
        print "TODO for merging: create a corrupted knit."
        knit = self.get_file()
        knit.check()

    def test_no_implicit_create(self):
        self.assertRaises(errors.NoSuchFile,
                          KnitVersionedFile,
                          'foo',
                          get_transport(self.get_url('.')))


class InterString(versionedfile.InterVersionedFile):
    """An inter-versionedfile optimised code path for strings.

    This is for use during testing where we use strings as versionedfiles
    so that none of the default regsitered interversionedfile classes will
    match - which lets us test the match logic.
    """

    @staticmethod
    def is_compatible(source, target):
        """InterString is compatible with strings-as-versionedfiles."""
        return isinstance(source, str) and isinstance(target, str)


# TODO this and the InterRepository core logic should be consolidatable
# if we make the registry a separate class though we still need to 
# test the behaviour in the active registry to catch failure-to-handle-
# stange-objects
class TestInterVersionedFile(TestCaseWithTransport):

    def test_get_default_inter_versionedfile(self):
        # test that the InterVersionedFile.get(a, b) probes
        # for a class where is_compatible(a, b) returns
        # true and returns a default interversionedfile otherwise.
        # This also tests that the default registered optimised interversionedfile
        # classes do not barf inappropriately when a surprising versionedfile type
        # is handed to them.
        dummy_a = "VersionedFile 1."
        dummy_b = "VersionedFile 2."
        self.assertGetsDefaultInterVersionedFile(dummy_a, dummy_b)

    def assertGetsDefaultInterVersionedFile(self, a, b):
        """Asserts that InterVersionedFile.get(a, b) -> the default."""
        inter = versionedfile.InterVersionedFile.get(a, b)
        self.assertEqual(versionedfile.InterVersionedFile,
                         inter.__class__)
        self.assertEqual(a, inter.source)
        self.assertEqual(b, inter.target)

    def test_register_inter_versionedfile_class(self):
        # test that a optimised code path provider - a
        # InterVersionedFile subclass can be registered and unregistered
        # and that it is correctly selected when given a versionedfile
        # pair that it returns true on for the is_compatible static method
        # check
        dummy_a = "VersionedFile 1."
        dummy_b = "VersionedFile 2."
        versionedfile.InterVersionedFile.register_optimiser(InterString)
        try:
            # we should get the default for something InterString returns False
            # to
            self.assertFalse(InterString.is_compatible(dummy_a, None))
            self.assertGetsDefaultInterVersionedFile(dummy_a, None)
            # and we should get an InterString for a pair it 'likes'
            self.assertTrue(InterString.is_compatible(dummy_a, dummy_b))
            inter = versionedfile.InterVersionedFile.get(dummy_a, dummy_b)
            self.assertEqual(InterString, inter.__class__)
            self.assertEqual(dummy_a, inter.source)
            self.assertEqual(dummy_b, inter.target)
        finally:
            versionedfile.InterVersionedFile.unregister_optimiser(InterString)
        # now we should get the default InterVersionedFile object again.
        self.assertGetsDefaultInterVersionedFile(dummy_a, dummy_b)
