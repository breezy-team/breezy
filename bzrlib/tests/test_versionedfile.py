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


from StringIO import StringIO

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
from bzrlib.tests.HTTPTestUtil import TestCaseWithWebserver
from bzrlib.trace import mutter
from bzrlib.transport import get_transport
from bzrlib.transport.memory import MemoryTransport
from bzrlib.tsort import topo_sort
import bzrlib.versionedfile as versionedfile
from bzrlib.weave import WeaveFile
from bzrlib.weavefile import read_weave, write_weave


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
        # this checks that reopen with create=True does not break anything.
        f = self.reopen_file(create=True)
        verify_file(f)

    def test_adds_with_parent_texts(self):
        f = self.get_file()
        parent_texts = {}
        parent_texts['r0'] = f.add_lines('r0', [], ['a\n', 'b\n'])
        try:
            parent_texts['r1'] = f.add_lines_with_ghosts('r1',
                                                         ['r0', 'ghost'], 
                                                         ['b\n', 'c\n'],
                                                         parent_texts=parent_texts)
        except NotImplementedError:
            # if the format doesn't support ghosts, just add normally.
            parent_texts['r1'] = f.add_lines('r1',
                                             ['r0'], 
                                             ['b\n', 'c\n'],
                                             parent_texts=parent_texts)
        f.add_lines('r2', ['r1'], ['c\n', 'd\n'], parent_texts=parent_texts)
        self.assertNotEqual(None, parent_texts['r0'])
        self.assertNotEqual(None, parent_texts['r1'])
        def verify_file(f):
            versions = f.versions()
            self.assertTrue('r0' in versions)
            self.assertTrue('r1' in versions)
            self.assertTrue('r2' in versions)
            self.assertEquals(f.get_lines('r0'), ['a\n', 'b\n'])
            self.assertEquals(f.get_lines('r1'), ['b\n', 'c\n'])
            self.assertEquals(f.get_lines('r2'), ['c\n', 'd\n'])
            self.assertEqual(3, f.num_versions())
            origins = f.annotate('r1')
            self.assertEquals(origins[0][0], 'r0')
            self.assertEquals(origins[1][0], 'r1')
            origins = f.annotate('r2')
            self.assertEquals(origins[0][0], 'r1')
            self.assertEquals(origins[1][0], 'r2')

        verify_file(f)
        f = self.reopen_file()
        verify_file(f)

    def test_add_unicode_content(self):
        # unicode content is not permitted in versioned files. 
        # versioned files version sequences of bytes only.
        vf = self.get_file()
        self.assertRaises(errors.BzrBadParameterUnicode,
            vf.add_lines, 'a', [], ['a\n', u'b\n', 'c\n'])
        self.assertRaises(
            (errors.BzrBadParameterUnicode, NotImplementedError),
            vf.add_lines_with_ghosts, 'a', [], ['a\n', u'b\n', 'c\n'])

    def test_inline_newline_throws(self):
        # \r characters are not permitted in lines being added
        vf = self.get_file()
        self.assertRaises(errors.BzrBadParameterContainsNewline, 
            vf.add_lines, 'a', [], ['a\n\n'])
        self.assertRaises(
            (errors.BzrBadParameterContainsNewline, NotImplementedError),
            vf.add_lines_with_ghosts, 'a', [], ['a\n\n'])
        # but inline CR's are allowed
        vf.add_lines('a', [], ['a\r\n'])
        try:
            vf.add_lines_with_ghosts('b', [], ['a\r\n'])
        except NotImplementedError:
            pass

    def test_get_delta(self):
        f = self.get_file()
        sha1s = self._setup_for_deltas(f)
        expected_delta = (None, '6bfa09d82ce3e898ad4641ae13dd4fdb9cf0d76b', False, 
                          [(0, 0, 1, [('base', 'line\n')])])
        self.assertEqual(expected_delta, f.get_delta('base'))
        next_parent = 'base'
        text_name = 'chain1-'
        for depth in range(26):
            new_version = text_name + '%s' % depth
            expected_delta = (next_parent, sha1s[depth], 
                              False,
                              [(depth + 1, depth + 1, 1, [(new_version, 'line\n')])])
            self.assertEqual(expected_delta, f.get_delta(new_version))
            next_parent = new_version
        next_parent = 'base'
        text_name = 'chain2-'
        for depth in range(26):
            new_version = text_name + '%s' % depth
            expected_delta = (next_parent, sha1s[depth], False,
                              [(depth + 1, depth + 1, 1, [(new_version, 'line\n')])])
            self.assertEqual(expected_delta, f.get_delta(new_version))
            next_parent = new_version
        # smoke test for eol support
        expected_delta = ('base', '264f39cab871e4cfd65b3a002f7255888bb5ed97', True, [])
        self.assertEqual(['line'], f.get_lines('noeol'))
        self.assertEqual(expected_delta, f.get_delta('noeol'))

    def test_get_deltas(self):
        f = self.get_file()
        sha1s = self._setup_for_deltas(f)
        deltas = f.get_deltas(f.versions())
        expected_delta = (None, '6bfa09d82ce3e898ad4641ae13dd4fdb9cf0d76b', False, 
                          [(0, 0, 1, [('base', 'line\n')])])
        self.assertEqual(expected_delta, deltas['base'])
        next_parent = 'base'
        text_name = 'chain1-'
        for depth in range(26):
            new_version = text_name + '%s' % depth
            expected_delta = (next_parent, sha1s[depth], 
                              False,
                              [(depth + 1, depth + 1, 1, [(new_version, 'line\n')])])
            self.assertEqual(expected_delta, deltas[new_version])
            next_parent = new_version
        next_parent = 'base'
        text_name = 'chain2-'
        for depth in range(26):
            new_version = text_name + '%s' % depth
            expected_delta = (next_parent, sha1s[depth], False,
                              [(depth + 1, depth + 1, 1, [(new_version, 'line\n')])])
            self.assertEqual(expected_delta, deltas[new_version])
            next_parent = new_version
        # smoke tests for eol support
        expected_delta = ('base', '264f39cab871e4cfd65b3a002f7255888bb5ed97', True, [])
        self.assertEqual(['line'], f.get_lines('noeol'))
        self.assertEqual(expected_delta, deltas['noeol'])
        # smoke tests for eol support - two noeol in a row same content
        expected_deltas = (('noeol', '3ad7ee82dbd8f29ecba073f96e43e414b3f70a4d', True, 
                          [(0, 1, 2, [(u'noeolsecond', 'line\n'), (u'noeolsecond', 'line\n')])]),
                          ('noeol', '3ad7ee82dbd8f29ecba073f96e43e414b3f70a4d', True, 
                           [(0, 0, 1, [('noeolsecond', 'line\n')]), (1, 1, 0, [])]))
        self.assertEqual(['line\n', 'line'], f.get_lines('noeolsecond'))
        self.assertTrue(deltas['noeolsecond'] in expected_deltas)
        # two no-eol in a row, different content
        expected_delta = ('noeolsecond', '8bb553a84e019ef1149db082d65f3133b195223b', True, 
                          [(1, 2, 1, [(u'noeolnotshared', 'phone\n')])])
        self.assertEqual(['line\n', 'phone'], f.get_lines('noeolnotshared'))
        self.assertEqual(expected_delta, deltas['noeolnotshared'])
        # eol folling a no-eol with content change
        expected_delta = ('noeol', 'a61f6fb6cfc4596e8d88c34a308d1e724caf8977', False, 
                          [(0, 1, 1, [(u'eol', 'phone\n')])])
        self.assertEqual(['phone\n'], f.get_lines('eol'))
        self.assertEqual(expected_delta, deltas['eol'])
        # eol folling a no-eol with content change
        expected_delta = ('noeol', '6bfa09d82ce3e898ad4641ae13dd4fdb9cf0d76b', False, 
                          [(0, 1, 1, [(u'eolline', 'line\n')])])
        self.assertEqual(['line\n'], f.get_lines('eolline'))
        self.assertEqual(expected_delta, deltas['eolline'])
        # eol with no parents
        expected_delta = (None, '264f39cab871e4cfd65b3a002f7255888bb5ed97', True, 
                          [(0, 0, 1, [(u'noeolbase', 'line\n')])])
        self.assertEqual(['line'], f.get_lines('noeolbase'))
        self.assertEqual(expected_delta, deltas['noeolbase'])
        # eol with two parents, in inverse insertion order
        expected_deltas = (('noeolbase', '264f39cab871e4cfd65b3a002f7255888bb5ed97', True,
                            [(0, 1, 1, [(u'eolbeforefirstparent', 'line\n')])]),
                           ('noeolbase', '264f39cab871e4cfd65b3a002f7255888bb5ed97', True,
                            [(0, 1, 1, [(u'eolbeforefirstparent', 'line\n')])]))
        self.assertEqual(['line'], f.get_lines('eolbeforefirstparent'))
        #self.assertTrue(deltas['eolbeforefirstparent'] in expected_deltas)

    def _setup_for_deltas(self, f):
        self.assertRaises(errors.RevisionNotPresent, f.get_delta, 'base')
        # add texts that should trip the knit maximum delta chain threshold
        # as well as doing parallel chains of data in knits.
        # this is done by two chains of 25 insertions
        f.add_lines('base', [], ['line\n'])
        f.add_lines('noeol', ['base'], ['line'])
        # detailed eol tests:
        # shared last line with parent no-eol
        f.add_lines('noeolsecond', ['noeol'], ['line\n', 'line'])
        # differing last line with parent, both no-eol
        f.add_lines('noeolnotshared', ['noeolsecond'], ['line\n', 'phone'])
        # add eol following a noneol parent, change content
        f.add_lines('eol', ['noeol'], ['phone\n'])
        # add eol following a noneol parent, no change content
        f.add_lines('eolline', ['noeol'], ['line\n'])
        # noeol with no parents:
        f.add_lines('noeolbase', [], ['line'])
        # noeol preceeding its leftmost parent in the output:
        # this is done by making it a merge of two parents with no common
        # anestry: noeolbase and noeol with the 
        # later-inserted parent the leftmost.
        f.add_lines('eolbeforefirstparent', ['noeolbase', 'noeol'], ['line'])
        # two identical eol texts
        f.add_lines('noeoldup', ['noeol'], ['line'])
        next_parent = 'base'
        text_name = 'chain1-'
        text = ['line\n']
        sha1s = {0 :'da6d3141cb4a5e6f464bf6e0518042ddc7bfd079',
                 1 :'45e21ea146a81ea44a821737acdb4f9791c8abe7',
                 2 :'e1f11570edf3e2a070052366c582837a4fe4e9fa',
                 3 :'26b4b8626da827088c514b8f9bbe4ebf181edda1',
                 4 :'e28a5510be25ba84d31121cff00956f9970ae6f6',
                 5 :'d63ec0ce22e11dcf65a931b69255d3ac747a318d',
                 6 :'2c2888d288cb5e1d98009d822fedfe6019c6a4ea',
                 7 :'95c14da9cafbf828e3e74a6f016d87926ba234ab',
                 8 :'779e9a0b28f9f832528d4b21e17e168c67697272',
                 9 :'1f8ff4e5c6ff78ac106fcfe6b1e8cb8740ff9a8f',
                 10:'131a2ae712cf51ed62f143e3fbac3d4206c25a05',
                 11:'c5a9d6f520d2515e1ec401a8f8a67e6c3c89f199',
                 12:'31a2286267f24d8bedaa43355f8ad7129509ea85',
                 13:'dc2a7fe80e8ec5cae920973973a8ee28b2da5e0a',
                 14:'2c4b1736566b8ca6051e668de68650686a3922f2',
                 15:'5912e4ecd9b0c07be4d013e7e2bdcf9323276cde',
                 16:'b0d2e18d3559a00580f6b49804c23fea500feab3',
                 17:'8e1d43ad72f7562d7cb8f57ee584e20eb1a69fc7',
                 18:'5cf64a3459ae28efa60239e44b20312d25b253f3',
                 19:'1ebed371807ba5935958ad0884595126e8c4e823',
                 20:'2aa62a8b06fb3b3b892a3292a068ade69d5ee0d3',
                 21:'01edc447978004f6e4e962b417a4ae1955b6fe5d',
                 22:'d8d8dc49c4bf0bab401e0298bb5ad827768618bb',
                 23:'c21f62b1c482862983a8ffb2b0c64b3451876e3f',
                 24:'c0593fe795e00dff6b3c0fe857a074364d5f04fc',
                 25:'dd1a1cf2ba9cc225c3aff729953e6364bf1d1855',
                 }
        for depth in range(26):
            new_version = text_name + '%s' % depth
            text = text + ['line\n']
            f.add_lines(new_version, [next_parent], text)
            next_parent = new_version
        next_parent = 'base'
        text_name = 'chain2-'
        text = ['line\n']
        for depth in range(26):
            new_version = text_name + '%s' % depth
            text = text + ['line\n']
            f.add_lines(new_version, [next_parent], text)
            next_parent = new_version
        return sha1s

    def test_add_delta(self):
        # tests for the add-delta facility.
        # at this point, optimising for speed, we assume no checks when deltas are inserted.
        # this may need to be revisited.
        source = self.get_file('source')
        source.add_lines('base', [], ['line\n'])
        next_parent = 'base'
        text_name = 'chain1-'
        text = ['line\n']
        for depth in range(26):
            new_version = text_name + '%s' % depth
            text = text + ['line\n']
            source.add_lines(new_version, [next_parent], text)
            next_parent = new_version
        next_parent = 'base'
        text_name = 'chain2-'
        text = ['line\n']
        for depth in range(26):
            new_version = text_name + '%s' % depth
            text = text + ['line\n']
            source.add_lines(new_version, [next_parent], text)
            next_parent = new_version
        source.add_lines('noeol', ['base'], ['line'])
        
        target = self.get_file('target')
        for version in source.versions():
            parent, sha1, noeol, delta = source.get_delta(version)
            target.add_delta(version,
                             source.get_parents(version),
                             parent,
                             sha1,
                             noeol,
                             delta)
        self.assertRaises(RevisionAlreadyPresent,
                          target.add_delta, 'base', [], None, '', False, [])
        for version in source.versions():
            self.assertEqual(source.get_lines(version),
                             target.get_lines(version))

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
        self.assertRaises(errors.OutSideTransaction, f.add_delta, '', [], '', '', False, [])
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

    def build_graph(self, file, graph):
        for node in topo_sort(graph.items()):
            file.add_lines(node, graph[node], [])

    def test_get_graph(self):
        f = self.get_file()
        graph = {
            'v1': [],
            'v2': ['v1'],
            'v3': ['v2']}
        self.build_graph(f, graph)
        self.assertEqual(graph, f.get_graph())
    
    def test_get_graph_partial(self):
        f = self.get_file()
        complex_graph = {}
        simple_a = {
            'c': [],
            'b': ['c'],
            'a': ['b'],
            }
        complex_graph.update(simple_a)
        simple_b = {
            'c': [],
            'b': ['c'],
            }
        complex_graph.update(simple_b)
        simple_gam = {
            'c': [],
            'oo': [],
            'bar': ['oo', 'c'],
            'gam': ['bar'],
            }
        complex_graph.update(simple_gam)
        simple_b_gam = {}
        simple_b_gam.update(simple_gam)
        simple_b_gam.update(simple_b)
        self.build_graph(f, complex_graph)
        self.assertEqual(simple_a, f.get_graph(['a']))
        self.assertEqual(simple_b, f.get_graph(['b']))
        self.assertEqual(simple_gam, f.get_graph(['gam']))
        self.assertEqual(simple_b_gam, f.get_graph(['b', 'gam']))

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
            vf.add_lines_with_ghosts(u'notbxbfse', [u'b\xbfse'], [])
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
        self.assertEqual([u'notbxbfse'], vf.get_ancestry(u'notbxbfse'))
        self.assertEqual([], vf.get_parents(u'notbxbfse'))
        self.assertEqual({u'notbxbfse':[]}, vf.get_graph())
        self.assertFalse(vf.has_version(u'b\xbfse'))
        # we have _with_ghost apis to give us ghost information.
        self.assertEqual([u'b\xbfse', u'notbxbfse'], vf.get_ancestry_with_ghosts([u'notbxbfse']))
        self.assertEqual([u'b\xbfse'], vf.get_parents_with_ghosts(u'notbxbfse'))
        self.assertEqual({u'notbxbfse':[u'b\xbfse']}, vf.get_graph_with_ghosts())
        self.assertTrue(vf.has_ghost(u'b\xbfse'))
        # if we add something that is a ghost of another, it should correct the
        # results of the prior apis
        vf.add_lines(u'b\xbfse', [], [])
        self.assertEqual([u'b\xbfse', u'notbxbfse'], vf.get_ancestry([u'notbxbfse']))
        self.assertEqual([u'b\xbfse'], vf.get_parents(u'notbxbfse'))
        self.assertEqual({u'b\xbfse':[],
                          u'notbxbfse':[u'b\xbfse'],
                          },
                         vf.get_graph())
        self.assertTrue(vf.has_version(u'b\xbfse'))
        # we have _with_ghost apis to give us ghost information.
        self.assertEqual([u'b\xbfse', u'notbxbfse'], vf.get_ancestry_with_ghosts([u'notbxbfse']))
        self.assertEqual([u'b\xbfse'], vf.get_parents_with_ghosts(u'notbxbfse'))
        self.assertEqual({u'b\xbfse':[],
                          u'notbxbfse':[u'b\xbfse'],
                          },
                         vf.get_graph_with_ghosts())
        self.assertFalse(vf.has_ghost(u'b\xbfse'))

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
        self.assertRaises(errors.ReadOnlyError, vf.add_delta, '', [], '', '', False, [])
        self.assertRaises(errors.ReadOnlyError, vf.add_lines, 'base', [], [])
        self.assertRaises(errors.ReadOnlyError,
                          vf.add_lines_with_ghosts,
                          'base',
                          [],
                          [])
        self.assertRaises(errors.ReadOnlyError, vf.fix_parents, 'base', [])
        self.assertRaises(errors.ReadOnlyError, vf.join, 'base')
        self.assertRaises(errors.ReadOnlyError, vf.clone_text, 'base', 'bar', ['foo'])
    
    def test_get_sha1(self):
        # check the sha1 data is available
        vf = self.get_file()
        # a simple file
        vf.add_lines('a', [], ['a\n'])
        # the same file, different metadata
        vf.add_lines('b', ['a'], ['a\n'])
        # a file differing only in last newline.
        vf.add_lines('c', [], ['a'])
        self.assertEqual(
            '3f786850e387550fdab836ed7e6dc881de23001b', vf.get_sha1('a'))
        self.assertEqual(
            '3f786850e387550fdab836ed7e6dc881de23001b', vf.get_sha1('b'))
        self.assertEqual(
            '86f7e437faa5a7fce15d1ddcb9eaeaea377667b8', vf.get_sha1('c'))
        

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

    def reopen_file(self, name='foo', create=False):
        return WeaveFile(name, get_transport(self.get_url('.')), create=create)

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

    def reopen_file(self, name='foo', create=False):
        return KnitVersionedFile(name, get_transport(self.get_url('.')),
            delta=True,
            create=create)

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


class TestReadonlyHttpMixin(object):

    def test_readonly_http_works(self):
        # we should be able to read from http with a versioned file.
        vf = self.get_file()
        # try an empty file access
        readonly_vf = self.get_factory()('foo', get_transport(self.get_readonly_url('.')))
        self.assertEqual([], readonly_vf.versions())
        # now with feeling.
        vf.add_lines('1', [], ['a\n'])
        vf.add_lines('2', ['1'], ['b\n', 'a\n'])
        readonly_vf = self.get_factory()('foo', get_transport(self.get_readonly_url('.')))
        self.assertEqual(['1', '2'], vf.versions())
        for version in readonly_vf.versions():
            readonly_vf.get_lines(version)


class TestWeaveHTTP(TestCaseWithWebserver, TestReadonlyHttpMixin):

    def get_file(self):
        return WeaveFile('foo', get_transport(self.get_url('.')), create=True)

    def get_factory(self):
        return WeaveFile


class TestKnitHTTP(TestCaseWithWebserver, TestReadonlyHttpMixin):

    def get_file(self):
        return KnitVersionedFile('foo', get_transport(self.get_url('.')),
                                 delta=True, create=True)

    def get_factory(self):
        return KnitVersionedFile


class MergeCasesMixin(object):

    def doMerge(self, base, a, b, mp):
        from cStringIO import StringIO
        from textwrap import dedent

        def addcrlf(x):
            return x + '\n'
        
        w = self.get_file()
        w.add_lines('text0', [], map(addcrlf, base))
        w.add_lines('text1', ['text0'], map(addcrlf, a))
        w.add_lines('text2', ['text0'], map(addcrlf, b))

        self.log_contents(w)

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
    overlappedInsertExpected = ['aaa', 'xxx', 'yyy', 'bbb']
    def testOverlappedInsert(self):
        self.doMerge(['aaa', 'bbb'],
                     ['aaa', 'xxx', 'yyy', 'bbb'],
                     ['aaa', 'xxx', 'bbb'], self.overlappedInsertExpected)

        # really it ought to reduce this to 
        # ['aaa', 'xxx', 'yyy', 'bbb']


    def testClashReplace(self):
        self.doMerge(['aaa'],
                     ['xxx'],
                     ['yyy', 'zzz'],
                     ['<<<<<<< ', 'xxx', '=======', 'yyy', 'zzz', 
                      '>>>>>>> '])

    def testNonClashInsert1(self):
        self.doMerge(['aaa'],
                     ['xxx', 'aaa'],
                     ['yyy', 'zzz'],
                     ['<<<<<<< ', 'xxx', 'aaa', '=======', 'yyy', 'zzz', 
                      '>>>>>>> '])

    def testNonClashInsert2(self):
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
        w = self.get_file()
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
        result = ''.join(self.get_file().weave_merge([('new-a', 'hello\n')]))
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


class TestKnitMerge(TestCaseWithTransport, MergeCasesMixin):

    def get_file(self, name='foo'):
        return KnitVersionedFile(name, get_transport(self.get_url('.')),
                                 delta=True, create=True)

    def log_contents(self, w):
        pass


class TestWeaveMerge(TestCaseWithTransport, MergeCasesMixin):

    def get_file(self, name='foo'):
        return WeaveFile(name, get_transport(self.get_url('.')), create=True)

    def log_contents(self, w):
        self.log('weave is:')
        tmpf = StringIO()
        write_weave(w, tmpf)
        self.log(tmpf.getvalue())

    overlappedInsertExpected = ['aaa', '<<<<<<< ', 'xxx', 'yyy', '=======', 
                                'xxx', '>>>>>>> ', 'bbb']
