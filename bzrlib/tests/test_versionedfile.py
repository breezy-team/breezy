# Copyright (C) 2005 Canonical Ltd
#
# Authors:
#   Johan Rydberg <jrydberg@gnu.org>
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


# TODO: might be nice to create a versionedfile with some type of corruption
# considered typical and check that it can be detected/corrected.

from itertools import chain
from StringIO import StringIO

import bzrlib
from bzrlib import (
    errors,
    osutils,
    progress,
    )
from bzrlib.errors import (
                           RevisionNotPresent,
                           RevisionAlreadyPresent,
                           WeaveParentMismatch
                           )
from bzrlib import knit as _mod_knit
from bzrlib.knit import (
    cleanup_pack_knit,
    make_file_factory,
    make_pack_factory,
    KnitAnnotateFactory,
    KnitPlainFactory,
    )
from bzrlib.symbol_versioning import one_four, one_five
from bzrlib.tests import (
    TestCase,
    TestCaseWithMemoryTransport,
    TestScenarioApplier,
    TestSkipped,
    condition_isinstance,
    split_suite_by_condition,
    iter_suite_tests,
    )
from bzrlib.tests.http_utils import TestCaseWithWebserver
from bzrlib.trace import mutter
from bzrlib.transport import get_transport
from bzrlib.transport.memory import MemoryTransport
from bzrlib.tsort import topo_sort
from bzrlib.tuned_gzip import GzipFile
import bzrlib.versionedfile as versionedfile
from bzrlib.versionedfile import (
    ConstantMapper,
    HashEscapedPrefixMapper,
    PrefixMapper,
    VirtualVersionedFiles,
    make_versioned_files_factory,
    )
from bzrlib.weave import WeaveFile
from bzrlib.weavefile import read_weave, write_weave


def load_tests(standard_tests, module, loader):
    """Parameterize VersionedFiles tests for different implementations."""
    to_adapt, result = split_suite_by_condition(
        standard_tests, condition_isinstance(TestVersionedFiles))
    len_one_adapter = TestScenarioApplier()
    len_two_adapter = TestScenarioApplier()
    # We want to be sure of behaviour for:
    # weaves prefix layout (weave texts)
    # individually named weaves (weave inventories)
    # annotated knits - prefix|hash|hash-escape layout, we test the third only
    #                   as it is the most complex mapper.
    # individually named knits
    # individual no-graph knits in packs (signatures)
    # individual graph knits in packs (inventories)
    # individual graph nocompression knits in packs (revisions)
    # plain text knits in packs (texts)
    len_one_adapter.scenarios = [
        ('weave-named', {
            'cleanup':None,
            'factory':make_versioned_files_factory(WeaveFile,
                ConstantMapper('inventory')),
            'graph':True,
            'key_length':1,
            }),
        ('named-knit', {
            'cleanup':None,
            'factory':make_file_factory(False, ConstantMapper('revisions')),
            'graph':True,
            'key_length':1,
            }),
        ('named-nograph-knit-pack', {
            'cleanup':cleanup_pack_knit,
            'factory':make_pack_factory(False, False, 1),
            'graph':False,
            'key_length':1,
            }),
        ('named-graph-knit-pack', {
            'cleanup':cleanup_pack_knit,
            'factory':make_pack_factory(True, True, 1),
            'graph':True,
            'key_length':1,
            }),
        ('named-graph-nodelta-knit-pack', {
            'cleanup':cleanup_pack_knit,
            'factory':make_pack_factory(True, False, 1),
            'graph':True,
            'key_length':1,
            }),
        ]
    len_two_adapter.scenarios = [
        ('weave-prefix', {
            'cleanup':None,
            'factory':make_versioned_files_factory(WeaveFile,
                PrefixMapper()),
            'graph':True,
            'key_length':2,
            }),
        ('annotated-knit-escape', {
            'cleanup':None,
            'factory':make_file_factory(True, HashEscapedPrefixMapper()),
            'graph':True,
            'key_length':2,
            }),
        ('plain-knit-pack', {
            'cleanup':cleanup_pack_knit,
            'factory':make_pack_factory(True, True, 2),
            'graph':True,
            'key_length':2,
            }),
        ]
    for test in iter_suite_tests(to_adapt):
        result.addTests(len_one_adapter.adapt(test))
        result.addTests(len_two_adapter.adapt(test))
    return result


def get_diamond_vf(f, trailing_eol=True, left_only=False):
    """Get a diamond graph to exercise deltas and merges.
    
    :param trailing_eol: If True end the last line with \n.
    """
    parents = {
        'origin': (),
        'base': (('origin',),),
        'left': (('base',),),
        'right': (('base',),),
        'merged': (('left',), ('right',)),
        }
    # insert a diamond graph to exercise deltas and merges.
    if trailing_eol:
        last_char = '\n'
    else:
        last_char = ''
    f.add_lines('origin', [], ['origin' + last_char])
    f.add_lines('base', ['origin'], ['base' + last_char])
    f.add_lines('left', ['base'], ['base\n', 'left' + last_char])
    if not left_only:
        f.add_lines('right', ['base'],
            ['base\n', 'right' + last_char])
        f.add_lines('merged', ['left', 'right'],
            ['base\n', 'left\n', 'right\n', 'merged' + last_char])
    return f, parents


def get_diamond_files(files, key_length, trailing_eol=True, left_only=False,
    nograph=False):
    """Get a diamond graph to exercise deltas and merges.

    This creates a 5-node graph in files. If files supports 2-length keys two
    graphs are made to exercise the support for multiple ids.
    
    :param trailing_eol: If True end the last line with \n.
    :param key_length: The length of keys in files. Currently supports length 1
        and 2 keys.
    :param left_only: If True do not add the right and merged nodes.
    :param nograph: If True, do not provide parents to the add_lines calls;
        this is useful for tests that need inserted data but have graphless
        stores.
    :return: The results of the add_lines calls.
    """
    if key_length == 1:
        prefixes = [()]
    else:
        prefixes = [('FileA',), ('FileB',)]
    # insert a diamond graph to exercise deltas and merges.
    if trailing_eol:
        last_char = '\n'
    else:
        last_char = ''
    result = []
    def get_parents(suffix_list):
        if nograph:
            return ()
        else:
            result = [prefix + suffix for suffix in suffix_list]
            return result
    # we loop over each key because that spreads the inserts across prefixes,
    # which is how commit operates.
    for prefix in prefixes:
        result.append(files.add_lines(prefix + ('origin',), (),
            ['origin' + last_char]))
    for prefix in prefixes:
        result.append(files.add_lines(prefix + ('base',),
            get_parents([('origin',)]), ['base' + last_char]))
    for prefix in prefixes:
        result.append(files.add_lines(prefix + ('left',),
            get_parents([('base',)]),
            ['base\n', 'left' + last_char]))
    if not left_only:
        for prefix in prefixes:
            result.append(files.add_lines(prefix + ('right',),
                get_parents([('base',)]),
                ['base\n', 'right' + last_char]))
        for prefix in prefixes:
            result.append(files.add_lines(prefix + ('merged',),
                get_parents([('left',), ('right',)]),
                ['base\n', 'left\n', 'right\n', 'merged' + last_char]))
    return result


class VersionedFileTestMixIn(object):
    """A mixin test class for testing VersionedFiles.

    This is not an adaptor-style test at this point because
    theres no dynamic substitution of versioned file implementations,
    they are strictly controlled by their owning repositories.
    """

    def get_transaction(self):
        if not hasattr(self, '_transaction'):
            self._transaction = None
        return self._transaction

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
        _, _, parent_texts['r0'] = f.add_lines('r0', [], ['a\n', 'b\n'])
        try:
            _, _, parent_texts['r1'] = f.add_lines_with_ghosts('r1',
                ['r0', 'ghost'], ['b\n', 'c\n'], parent_texts=parent_texts)
        except NotImplementedError:
            # if the format doesn't support ghosts, just add normally.
            _, _, parent_texts['r1'] = f.add_lines('r1',
                ['r0'], ['b\n', 'c\n'], parent_texts=parent_texts)
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

    def test_add_follows_left_matching_blocks(self):
        """If we change left_matching_blocks, delta changes

        Note: There are multiple correct deltas in this case, because
        we start with 1 "a" and we get 3.
        """
        vf = self.get_file()
        if isinstance(vf, WeaveFile):
            raise TestSkipped("WeaveFile ignores left_matching_blocks")
        vf.add_lines('1', [], ['a\n'])
        vf.add_lines('2', ['1'], ['a\n', 'a\n', 'a\n'],
                     left_matching_blocks=[(0, 0, 1), (1, 3, 0)])
        self.assertEqual(['a\n', 'a\n', 'a\n'], vf.get_lines('2'))
        vf.add_lines('3', ['1'], ['a\n', 'a\n', 'a\n'],
                     left_matching_blocks=[(0, 2, 1), (1, 3, 0)])
        self.assertEqual(['a\n', 'a\n', 'a\n'], vf.get_lines('3'))

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

    def test_add_reserved(self):
        vf = self.get_file()
        self.assertRaises(errors.ReservedId,
            vf.add_lines, 'a:', [], ['a\n', 'b\n', 'c\n'])

    def test_add_lines_nostoresha(self):
        """When nostore_sha is supplied using old content raises."""
        vf = self.get_file()
        empty_text = ('a', [])
        sample_text_nl = ('b', ["foo\n", "bar\n"])
        sample_text_no_nl = ('c', ["foo\n", "bar"])
        shas = []
        for version, lines in (empty_text, sample_text_nl, sample_text_no_nl):
            sha, _, _ = vf.add_lines(version, [], lines)
            shas.append(sha)
        # we now have a copy of all the lines in the vf.
        for sha, (version, lines) in zip(
            shas, (empty_text, sample_text_nl, sample_text_no_nl)):
            self.assertRaises(errors.ExistingContent,
                vf.add_lines, version + "2", [], lines,
                nostore_sha=sha)
            # and no new version should have been added.
            self.assertRaises(errors.RevisionNotPresent, vf.get_lines,
                version + "2")

    def test_add_lines_with_ghosts_nostoresha(self):
        """When nostore_sha is supplied using old content raises."""
        vf = self.get_file()
        empty_text = ('a', [])
        sample_text_nl = ('b', ["foo\n", "bar\n"])
        sample_text_no_nl = ('c', ["foo\n", "bar"])
        shas = []
        for version, lines in (empty_text, sample_text_nl, sample_text_no_nl):
            sha, _, _ = vf.add_lines(version, [], lines)
            shas.append(sha)
        # we now have a copy of all the lines in the vf.
        # is the test applicable to this vf implementation?
        try:
            vf.add_lines_with_ghosts('d', [], [])
        except NotImplementedError:
            raise TestSkipped("add_lines_with_ghosts is optional")
        for sha, (version, lines) in zip(
            shas, (empty_text, sample_text_nl, sample_text_no_nl)):
            self.assertRaises(errors.ExistingContent,
                vf.add_lines_with_ghosts, version + "2", [], lines,
                nostore_sha=sha)
            # and no new version should have been added.
            self.assertRaises(errors.RevisionNotPresent, vf.get_lines,
                version + "2")

    def test_add_lines_return_value(self):
        # add_lines should return the sha1 and the text size.
        vf = self.get_file()
        empty_text = ('a', [])
        sample_text_nl = ('b', ["foo\n", "bar\n"])
        sample_text_no_nl = ('c', ["foo\n", "bar"])
        # check results for the three cases:
        for version, lines in (empty_text, sample_text_nl, sample_text_no_nl):
            # the first two elements are the same for all versioned files:
            # - the digest and the size of the text. For some versioned files
            #   additional data is returned in additional tuple elements.
            result = vf.add_lines(version, [], lines)
            self.assertEqual(3, len(result))
            self.assertEqual((osutils.sha_strings(lines), sum(map(len, lines))),
                result[0:2])
        # parents should not affect the result:
        lines = sample_text_nl[1]
        self.assertEqual((osutils.sha_strings(lines), sum(map(len, lines))),
            vf.add_lines('d', ['b', 'c'], lines)[0:2])

    def test_get_reserved(self):
        vf = self.get_file()
        self.assertRaises(errors.ReservedId, vf.get_texts, ['b:'])
        self.assertRaises(errors.ReservedId, vf.get_lines, 'b:')
        self.assertRaises(errors.ReservedId, vf.get_text, 'b:')

    def test_add_unchanged_last_line_noeol_snapshot(self):
        """Add a text with an unchanged last line with no eol should work."""
        # Test adding this in a number of chain lengths; because the interface
        # for VersionedFile does not allow forcing a specific chain length, we
        # just use a small base to get the first snapshot, then a much longer
        # first line for the next add (which will make the third add snapshot)
        # and so on. 20 has been chosen as an aribtrary figure - knits use 200
        # as a capped delta length, but ideally we would have some way of
        # tuning the test to the store (e.g. keep going until a snapshot
        # happens).
        for length in range(20):
            version_lines = {}
            vf = self.get_file('case-%d' % length)
            prefix = 'step-%d'
            parents = []
            for step in range(length):
                version = prefix % step
                lines = (['prelude \n'] * step) + ['line']
                vf.add_lines(version, parents, lines)
                version_lines[version] = lines
                parents = [version]
            vf.add_lines('no-eol', parents, ['line'])
            vf.get_texts(version_lines.keys())
            self.assertEqualDiff('line', vf.get_text('no-eol'))

    def test_get_texts_eol_variation(self):
        # similar to the failure in <http://bugs.launchpad.net/234748>
        vf = self.get_file()
        sample_text_nl = ["line\n"]
        sample_text_no_nl = ["line"]
        versions = []
        version_lines = {}
        parents = []
        for i in range(4):
            version = 'v%d' % i
            if i % 2:
                lines = sample_text_nl
            else:
                lines = sample_text_no_nl
            # left_matching blocks is an internal api; it operates on the
            # *internal* representation for a knit, which is with *all* lines
            # being normalised to end with \n - even the final line in a no_nl
            # file. Using it here ensures that a broken internal implementation
            # (which is what this test tests) will generate a correct line
            # delta (which is to say, an empty delta).
            vf.add_lines(version, parents, lines,
                left_matching_blocks=[(0, 0, 1)])
            parents = [version]
            versions.append(version)
            version_lines[version] = lines
        vf.check()
        vf.get_texts(versions)
        vf.get_texts(reversed(versions))

    def test_add_lines_with_matching_blocks_noeol_last_line(self):
        """Add a text with an unchanged last line with no eol should work."""
        from bzrlib import multiparent
        # Hand verified sha1 of the text we're adding.
        sha1 = '6a1d115ec7b60afb664dc14890b5af5ce3c827a4'
        # Create a mpdiff which adds a new line before the trailing line, and
        # reuse the last line unaltered (which can cause annotation reuse).
        # Test adding this in two situations:
        # On top of a new insertion
        vf = self.get_file('fulltext')
        vf.add_lines('noeol', [], ['line'])
        vf.add_lines('noeol2', ['noeol'], ['newline\n', 'line'],
            left_matching_blocks=[(0, 1, 1)])
        self.assertEqualDiff('newline\nline', vf.get_text('noeol2'))
        # On top of a delta
        vf = self.get_file('delta')
        vf.add_lines('base', [], ['line'])
        vf.add_lines('noeol', ['base'], ['prelude\n', 'line'])
        vf.add_lines('noeol2', ['noeol'], ['newline\n', 'line'],
            left_matching_blocks=[(1, 1, 1)])
        self.assertEqualDiff('newline\nline', vf.get_text('noeol2'))

    def test_make_mpdiffs(self):
        from bzrlib import multiparent
        vf = self.get_file('foo')
        sha1s = self._setup_for_deltas(vf)
        new_vf = self.get_file('bar')
        for version in multiparent.topo_iter(vf):
            mpdiff = vf.make_mpdiffs([version])[0]
            new_vf.add_mpdiffs([(version, vf.get_parent_map([version])[version],
                                 vf.get_sha1s([version])[version], mpdiff)])
            self.assertEqualDiff(vf.get_text(version),
                                 new_vf.get_text(version))

    def test_make_mpdiffs_with_ghosts(self):
        vf = self.get_file('foo')
        try:
            vf.add_lines_with_ghosts('text', ['ghost'], ['line\n'])
        except NotImplementedError:
            # old Weave formats do not allow ghosts
            return
        self.assertRaises(errors.RevisionNotPresent, vf.make_mpdiffs, ['ghost'])

    def _setup_for_deltas(self, f):
        self.assertFalse(f.has_version('base'))
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

        self.assertEqual(set(f.get_ancestry('rM')),
            set(f.get_ancestry('rM', topo_sorted=False)))

    def test_mutate_after_finish(self):
        self._transaction = 'before'
        f = self.get_file()
        self._transaction = 'after'
        self.assertRaises(errors.OutSideTransaction, f.add_lines, '', [], [])
        self.assertRaises(errors.OutSideTransaction, f.add_lines_with_ghosts, '', [], [])
        
    def test_copy_to(self):
        f = self.get_file()
        f.add_lines('0', [], ['a\n'])
        t = MemoryTransport()
        f.copy_to('foo', t)
        for suffix in self.get_factory().get_suffixes():
            self.assertTrue(t.has('foo' + suffix))

    def test_get_suffixes(self):
        f = self.get_file()
        # and should be a list
        self.assertTrue(isinstance(self.get_factory().get_suffixes(), list))

    def test_get_parent_map(self):
        f = self.get_file()
        f.add_lines('r0', [], ['a\n', 'b\n'])
        self.assertEqual(
            {'r0':()}, f.get_parent_map(['r0']))
        f.add_lines('r1', ['r0'], ['a\n', 'b\n'])
        self.assertEqual(
            {'r1':('r0',)}, f.get_parent_map(['r1']))
        self.assertEqual(
            {'r0':(),
             'r1':('r0',)},
            f.get_parent_map(['r0', 'r1']))
        f.add_lines('r2', [], ['a\n', 'b\n'])
        f.add_lines('r3', [], ['a\n', 'b\n'])
        f.add_lines('m', ['r0', 'r1', 'r2', 'r3'], ['a\n', 'b\n'])
        self.assertEqual(
            {'m':('r0', 'r1', 'r2', 'r3')}, f.get_parent_map(['m']))
        self.assertEqual({}, f.get_parent_map('y'))
        self.assertEqual(
            {'r0':(),
             'r1':('r0',)},
            f.get_parent_map(['r0', 'y', 'r1']))

    def test_annotate(self):
        f = self.get_file()
        f.add_lines('r0', [], ['a\n', 'b\n'])
        f.add_lines('r1', ['r0'], ['c\n', 'b\n'])
        origins = f.annotate('r1')
        self.assertEquals(origins[0][0], 'r1')
        self.assertEquals(origins[1][0], 'r0')

        self.assertRaises(RevisionNotPresent,
            f.annotate, 'foo')

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

        class InstrumentedProgress(progress.DummyProgress):

            def __init__(self):

                progress.DummyProgress.__init__(self)
                self.updates = []

            def update(self, msg=None, current=None, total=None):
                self.updates.append((msg, current, total))

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
        def iter_with_versions(versions, expected):
            # now we need to see what lines are returned, and how often.
            lines = {}
            progress = InstrumentedProgress()
            # iterate over the lines
            for line in vf.iter_lines_added_or_present_in_versions(versions,
                pb=progress):
                lines.setdefault(line, 0)
                lines[line] += 1
            if []!= progress.updates:
                self.assertEqual(expected, progress.updates)
            return lines
        lines = iter_with_versions(['child', 'otherchild'],
                                   [('Walking content.', 0, 2),
                                    ('Walking content.', 1, 2),
                                    ('Walking content.', 2, 2)])
        # we must see child and otherchild
        self.assertTrue(lines[('child\n', 'child')] > 0)
        self.assertTrue(lines[('otherchild\n', 'otherchild')] > 0)
        # we dont care if we got more than that.
        
        # test all lines
        lines = iter_with_versions(None, [('Walking content.', 0, 5),
                                          ('Walking content.', 1, 5),
                                          ('Walking content.', 2, 5),
                                          ('Walking content.', 3, 5),
                                          ('Walking content.', 4, 5),
                                          ('Walking content.', 5, 5)])
        # all lines must be seen at least once
        self.assertTrue(lines[('base\n', 'base')] > 0)
        self.assertTrue(lines[('lancestor\n', 'lancestor')] > 0)
        self.assertTrue(lines[('rancestor\n', 'rancestor')] > 0)
        self.assertTrue(lines[('child\n', 'child')] > 0)
        self.assertTrue(lines[('otherchild\n', 'otherchild')] > 0)

    def test_add_lines_with_ghosts(self):
        # some versioned file formats allow lines to be added with parent
        # information that is > than that in the format. Formats that do
        # not support this need to raise NotImplementedError on the
        # add_lines_with_ghosts api.
        vf = self.get_file()
        # add a revision with ghost parents
        # The preferred form is utf8, but we should translate when needed
        parent_id_unicode = u'b\xbfse'
        parent_id_utf8 = parent_id_unicode.encode('utf8')
        try:
            vf.add_lines_with_ghosts('notbxbfse', [parent_id_utf8], [])
        except NotImplementedError:
            # check the other ghost apis are also not implemented
            self.assertRaises(NotImplementedError, vf.get_ancestry_with_ghosts, ['foo'])
            self.assertRaises(NotImplementedError, vf.get_parents_with_ghosts, 'foo')
            return
        vf = self.reopen_file()
        # test key graph related apis: getncestry, _graph, get_parents
        # has_version
        # - these are ghost unaware and must not be reflect ghosts
        self.assertEqual(['notbxbfse'], vf.get_ancestry('notbxbfse'))
        self.assertFalse(vf.has_version(parent_id_utf8))
        # we have _with_ghost apis to give us ghost information.
        self.assertEqual([parent_id_utf8, 'notbxbfse'], vf.get_ancestry_with_ghosts(['notbxbfse']))
        self.assertEqual([parent_id_utf8], vf.get_parents_with_ghosts('notbxbfse'))
        # if we add something that is a ghost of another, it should correct the
        # results of the prior apis
        vf.add_lines(parent_id_utf8, [], [])
        self.assertEqual([parent_id_utf8, 'notbxbfse'], vf.get_ancestry(['notbxbfse']))
        self.assertEqual({'notbxbfse':(parent_id_utf8,)},
            vf.get_parent_map(['notbxbfse']))
        self.assertTrue(vf.has_version(parent_id_utf8))
        # we have _with_ghost apis to give us ghost information.
        self.assertEqual([parent_id_utf8, 'notbxbfse'],
            vf.get_ancestry_with_ghosts(['notbxbfse']))
        self.assertEqual([parent_id_utf8], vf.get_parents_with_ghosts('notbxbfse'))

    def test_add_lines_with_ghosts_after_normal_revs(self):
        # some versioned file formats allow lines to be added with parent
        # information that is > than that in the format. Formats that do
        # not support this need to raise NotImplementedError on the
        # add_lines_with_ghosts api.
        vf = self.get_file()
        # probe for ghost support
        try:
            vf.add_lines_with_ghosts('base', [], ['line\n', 'line_b\n'])
        except NotImplementedError:
            return
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
    
    def test_get_sha1s(self):
        # check the sha1 data is available
        vf = self.get_file()
        # a simple file
        vf.add_lines('a', [], ['a\n'])
        # the same file, different metadata
        vf.add_lines('b', ['a'], ['a\n'])
        # a file differing only in last newline.
        vf.add_lines('c', [], ['a'])
        self.assertEqual({
            'a': '3f786850e387550fdab836ed7e6dc881de23001b',
            'c': '86f7e437faa5a7fce15d1ddcb9eaeaea377667b8',
            'b': '3f786850e387550fdab836ed7e6dc881de23001b',
            },
            vf.get_sha1s(['a', 'c', 'b']))
        

class TestWeave(TestCaseWithMemoryTransport, VersionedFileTestMixIn):

    def get_file(self, name='foo'):
        return WeaveFile(name, get_transport(self.get_url('.')), create=True,
            get_scope=self.get_transaction)

    def get_file_corrupted_text(self):
        w = WeaveFile('foo', get_transport(self.get_url('.')), create=True,
            get_scope=self.get_transaction)
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
        return WeaveFile(name, get_transport(self.get_url('.')), create=create,
            get_scope=self.get_transaction)

    def test_no_implicit_create(self):
        self.assertRaises(errors.NoSuchFile,
                          WeaveFile,
                          'foo',
                          get_transport(self.get_url('.')),
                          get_scope=self.get_transaction)

    def get_factory(self):
        return WeaveFile


class TestPlanMergeVersionedFile(TestCaseWithMemoryTransport):

    def setUp(self):
        TestCaseWithMemoryTransport.setUp(self)
        mapper = PrefixMapper()
        factory = make_file_factory(True, mapper)
        self.vf1 = factory(self.get_transport('root-1'))
        self.vf2 = factory(self.get_transport('root-2'))
        self.plan_merge_vf = versionedfile._PlanMergeVersionedFile('root')
        self.plan_merge_vf.fallback_versionedfiles.extend([self.vf1, self.vf2])

    def test_add_lines(self):
        self.plan_merge_vf.add_lines(('root', 'a:'), [], [])
        self.assertRaises(ValueError, self.plan_merge_vf.add_lines,
            ('root', 'a'), [], [])
        self.assertRaises(ValueError, self.plan_merge_vf.add_lines,
            ('root', 'a:'), None, [])
        self.assertRaises(ValueError, self.plan_merge_vf.add_lines,
            ('root', 'a:'), [], None)

    def setup_abcde(self):
        self.vf1.add_lines(('root', 'A'), [], ['a'])
        self.vf1.add_lines(('root', 'B'), [('root', 'A')], ['b'])
        self.vf2.add_lines(('root', 'C'), [], ['c'])
        self.vf2.add_lines(('root', 'D'), [('root', 'C')], ['d'])
        self.plan_merge_vf.add_lines(('root', 'E:'),
            [('root', 'B'), ('root', 'D')], ['e'])

    def test_get_parents(self):
        self.setup_abcde()
        self.assertEqual({('root', 'B'):(('root', 'A'),)},
            self.plan_merge_vf.get_parent_map([('root', 'B')]))
        self.assertEqual({('root', 'D'):(('root', 'C'),)},
            self.plan_merge_vf.get_parent_map([('root', 'D')]))
        self.assertEqual({('root', 'E:'):(('root', 'B'),('root', 'D'))},
            self.plan_merge_vf.get_parent_map([('root', 'E:')]))
        self.assertEqual({},
            self.plan_merge_vf.get_parent_map([('root', 'F')]))
        self.assertEqual({
                ('root', 'B'):(('root', 'A'),),
                ('root', 'D'):(('root', 'C'),),
                ('root', 'E:'):(('root', 'B'),('root', 'D')),
                },
            self.plan_merge_vf.get_parent_map(
                [('root', 'B'), ('root', 'D'), ('root', 'E:'), ('root', 'F')]))

    def test_get_record_stream(self):
        self.setup_abcde()
        def get_record(suffix):
            return self.plan_merge_vf.get_record_stream(
                [('root', suffix)], 'unordered', True).next()
        self.assertEqual('a', get_record('A').get_bytes_as('fulltext'))
        self.assertEqual('c', get_record('C').get_bytes_as('fulltext'))
        self.assertEqual('e', get_record('E:').get_bytes_as('fulltext'))
        self.assertEqual('absent', get_record('F').storage_kind)


class TestReadonlyHttpMixin(object):

    def get_transaction(self):
        return 1

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
        return WeaveFile('foo', get_transport(self.get_url('.')), create=True,
            get_scope=self.get_transaction)

    def get_factory(self):
        return WeaveFile


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


class TestWeaveMerge(TestCaseWithMemoryTransport, MergeCasesMixin):

    def get_file(self, name='foo'):
        return WeaveFile(name, get_transport(self.get_url('.')), create=True)

    def log_contents(self, w):
        self.log('weave is:')
        tmpf = StringIO()
        write_weave(w, tmpf)
        self.log(tmpf.getvalue())

    overlappedInsertExpected = ['aaa', '<<<<<<< ', 'xxx', 'yyy', '=======', 
                                'xxx', '>>>>>>> ', 'bbb']


class TestContentFactoryAdaption(TestCaseWithMemoryTransport):

    def test_select_adaptor(self):
        """Test expected adapters exist."""
        # One scenario for each lookup combination we expect to use.
        # Each is source_kind, requested_kind, adapter class
        scenarios = [
            ('knit-delta-gz', 'fulltext', _mod_knit.DeltaPlainToFullText),
            ('knit-ft-gz', 'fulltext', _mod_knit.FTPlainToFullText),
            ('knit-annotated-delta-gz', 'knit-delta-gz',
                _mod_knit.DeltaAnnotatedToUnannotated),
            ('knit-annotated-delta-gz', 'fulltext',
                _mod_knit.DeltaAnnotatedToFullText),
            ('knit-annotated-ft-gz', 'knit-ft-gz',
                _mod_knit.FTAnnotatedToUnannotated),
            ('knit-annotated-ft-gz', 'fulltext',
                _mod_knit.FTAnnotatedToFullText),
            ]
        for source, requested, klass in scenarios:
            adapter_factory = versionedfile.adapter_registry.get(
                (source, requested))
            adapter = adapter_factory(None)
            self.assertIsInstance(adapter, klass)

    def get_knit(self, annotated=True):
        mapper = ConstantMapper('knit')
        transport = self.get_transport()
        return make_file_factory(annotated, mapper)(transport)

    def helpGetBytes(self, f, ft_adapter, delta_adapter):
        """Grab the interested adapted texts for tests."""
        # origin is a fulltext
        entries = f.get_record_stream([('origin',)], 'unordered', False)
        base = entries.next()
        ft_data = ft_adapter.get_bytes(base, base.get_bytes_as(base.storage_kind))
        # merged is both a delta and multiple parents.
        entries = f.get_record_stream([('merged',)], 'unordered', False)
        merged = entries.next()
        delta_data = delta_adapter.get_bytes(merged,
            merged.get_bytes_as(merged.storage_kind))
        return ft_data, delta_data

    def test_deannotation_noeol(self):
        """Test converting annotated knits to unannotated knits."""
        # we need a full text, and a delta
        f = self.get_knit()
        get_diamond_files(f, 1, trailing_eol=False)
        ft_data, delta_data = self.helpGetBytes(f,
            _mod_knit.FTAnnotatedToUnannotated(None),
            _mod_knit.DeltaAnnotatedToUnannotated(None))
        self.assertEqual(
            'version origin 1 b284f94827db1fa2970d9e2014f080413b547a7e\n'
            'origin\n'
            'end origin\n',
            GzipFile(mode='rb', fileobj=StringIO(ft_data)).read())
        self.assertEqual(
            'version merged 4 32c2e79763b3f90e8ccde37f9710b6629c25a796\n'
            '1,2,3\nleft\nright\nmerged\nend merged\n',
            GzipFile(mode='rb', fileobj=StringIO(delta_data)).read())

    def test_deannotation(self):
        """Test converting annotated knits to unannotated knits."""
        # we need a full text, and a delta
        f = self.get_knit()
        get_diamond_files(f, 1)
        ft_data, delta_data = self.helpGetBytes(f,
            _mod_knit.FTAnnotatedToUnannotated(None),
            _mod_knit.DeltaAnnotatedToUnannotated(None))
        self.assertEqual(
            'version origin 1 00e364d235126be43292ab09cb4686cf703ddc17\n'
            'origin\n'
            'end origin\n',
            GzipFile(mode='rb', fileobj=StringIO(ft_data)).read())
        self.assertEqual(
            'version merged 3 ed8bce375198ea62444dc71952b22cfc2b09226d\n'
            '2,2,2\nright\nmerged\nend merged\n',
            GzipFile(mode='rb', fileobj=StringIO(delta_data)).read())

    def test_annotated_to_fulltext_no_eol(self):
        """Test adapting annotated knits to full texts (for -> weaves)."""
        # we need a full text, and a delta
        f = self.get_knit()
        get_diamond_files(f, 1, trailing_eol=False)
        # Reconstructing a full text requires a backing versioned file, and it
        # must have the base lines requested from it.
        logged_vf = versionedfile.RecordingVersionedFilesDecorator(f)
        ft_data, delta_data = self.helpGetBytes(f,
            _mod_knit.FTAnnotatedToFullText(None),
            _mod_knit.DeltaAnnotatedToFullText(logged_vf))
        self.assertEqual('origin', ft_data)
        self.assertEqual('base\nleft\nright\nmerged', delta_data)
        self.assertEqual([('get_record_stream', [('left',)], 'unordered',
            True)], logged_vf.calls)

    def test_annotated_to_fulltext(self):
        """Test adapting annotated knits to full texts (for -> weaves)."""
        # we need a full text, and a delta
        f = self.get_knit()
        get_diamond_files(f, 1)
        # Reconstructing a full text requires a backing versioned file, and it
        # must have the base lines requested from it.
        logged_vf = versionedfile.RecordingVersionedFilesDecorator(f)
        ft_data, delta_data = self.helpGetBytes(f,
            _mod_knit.FTAnnotatedToFullText(None),
            _mod_knit.DeltaAnnotatedToFullText(logged_vf))
        self.assertEqual('origin\n', ft_data)
        self.assertEqual('base\nleft\nright\nmerged\n', delta_data)
        self.assertEqual([('get_record_stream', [('left',)], 'unordered',
            True)], logged_vf.calls)

    def test_unannotated_to_fulltext(self):
        """Test adapting unannotated knits to full texts.
        
        This is used for -> weaves, and for -> annotated knits.
        """
        # we need a full text, and a delta
        f = self.get_knit(annotated=False)
        get_diamond_files(f, 1)
        # Reconstructing a full text requires a backing versioned file, and it
        # must have the base lines requested from it.
        logged_vf = versionedfile.RecordingVersionedFilesDecorator(f)
        ft_data, delta_data = self.helpGetBytes(f,
            _mod_knit.FTPlainToFullText(None),
            _mod_knit.DeltaPlainToFullText(logged_vf))
        self.assertEqual('origin\n', ft_data)
        self.assertEqual('base\nleft\nright\nmerged\n', delta_data)
        self.assertEqual([('get_record_stream', [('left',)], 'unordered',
            True)], logged_vf.calls)

    def test_unannotated_to_fulltext_no_eol(self):
        """Test adapting unannotated knits to full texts.
        
        This is used for -> weaves, and for -> annotated knits.
        """
        # we need a full text, and a delta
        f = self.get_knit(annotated=False)
        get_diamond_files(f, 1, trailing_eol=False)
        # Reconstructing a full text requires a backing versioned file, and it
        # must have the base lines requested from it.
        logged_vf = versionedfile.RecordingVersionedFilesDecorator(f)
        ft_data, delta_data = self.helpGetBytes(f,
            _mod_knit.FTPlainToFullText(None),
            _mod_knit.DeltaPlainToFullText(logged_vf))
        self.assertEqual('origin', ft_data)
        self.assertEqual('base\nleft\nright\nmerged', delta_data)
        self.assertEqual([('get_record_stream', [('left',)], 'unordered',
            True)], logged_vf.calls)


class TestKeyMapper(TestCaseWithMemoryTransport):
    """Tests for various key mapping logic."""

    def test_identity_mapper(self):
        mapper = versionedfile.ConstantMapper("inventory")
        self.assertEqual("inventory", mapper.map(('foo@ar',)))
        self.assertEqual("inventory", mapper.map(('quux',)))

    def test_prefix_mapper(self):
        #format5: plain
        mapper = versionedfile.PrefixMapper()
        self.assertEqual("file-id", mapper.map(("file-id", "revision-id")))
        self.assertEqual("new-id", mapper.map(("new-id", "revision-id")))
        self.assertEqual(('file-id',), mapper.unmap("file-id"))
        self.assertEqual(('new-id',), mapper.unmap("new-id"))

    def test_hash_prefix_mapper(self):
        #format6: hash + plain
        mapper = versionedfile.HashPrefixMapper()
        self.assertEqual("9b/file-id", mapper.map(("file-id", "revision-id")))
        self.assertEqual("45/new-id", mapper.map(("new-id", "revision-id")))
        self.assertEqual(('file-id',), mapper.unmap("9b/file-id"))
        self.assertEqual(('new-id',), mapper.unmap("45/new-id"))

    def test_hash_escaped_mapper(self):
        #knit1: hash + escaped
        mapper = versionedfile.HashEscapedPrefixMapper()
        self.assertEqual("88/%2520", mapper.map((" ", "revision-id")))
        self.assertEqual("ed/fil%2545-%2549d", mapper.map(("filE-Id",
            "revision-id")))
        self.assertEqual("88/ne%2557-%2549d", mapper.map(("neW-Id",
            "revision-id")))
        self.assertEqual(('filE-Id',), mapper.unmap("ed/fil%2545-%2549d"))
        self.assertEqual(('neW-Id',), mapper.unmap("88/ne%2557-%2549d"))


class TestVersionedFiles(TestCaseWithMemoryTransport):
    """Tests for the multiple-file variant of VersionedFile."""

    def get_versionedfiles(self, relpath='files'):
        transport = self.get_transport(relpath)
        if relpath != '.':
            transport.mkdir('.')
        files = self.factory(transport)
        if self.cleanup is not None:
            self.addCleanup(lambda:self.cleanup(files))
        return files

    def test_annotate(self):
        files = self.get_versionedfiles()
        self.get_diamond_files(files)
        if self.key_length == 1:
            prefix = ()
        else:
            prefix = ('FileA',)
        # introduced full text
        origins = files.annotate(prefix + ('origin',))
        self.assertEqual([
            (prefix + ('origin',), 'origin\n')],
            origins)
        # a delta
        origins = files.annotate(prefix + ('base',))
        self.assertEqual([
            (prefix + ('base',), 'base\n')],
            origins)
        # a merge
        origins = files.annotate(prefix + ('merged',))
        if self.graph:
            self.assertEqual([
                (prefix + ('base',), 'base\n'),
                (prefix + ('left',), 'left\n'),
                (prefix + ('right',), 'right\n'),
                (prefix + ('merged',), 'merged\n')
                ],
                origins)
        else:
            # Without a graph everything is new.
            self.assertEqual([
                (prefix + ('merged',), 'base\n'),
                (prefix + ('merged',), 'left\n'),
                (prefix + ('merged',), 'right\n'),
                (prefix + ('merged',), 'merged\n')
                ],
                origins)
        self.assertRaises(RevisionNotPresent,
            files.annotate, prefix + ('missing-key',))

    def test_construct(self):
        """Each parameterised test can be constructed on a transport."""
        files = self.get_versionedfiles()

    def get_diamond_files(self, files, trailing_eol=True, left_only=False):
        return get_diamond_files(files, self.key_length,
            trailing_eol=trailing_eol, nograph=not self.graph,
            left_only=left_only)

    def test_add_lines_return(self):
        files = self.get_versionedfiles()
        # save code by using the stock data insertion helper.
        adds = self.get_diamond_files(files)
        results = []
        # We can only validate the first 2 elements returned from add_lines.
        for add in adds:
            self.assertEqual(3, len(add))
            results.append(add[:2])
        if self.key_length == 1:
            self.assertEqual([
                ('00e364d235126be43292ab09cb4686cf703ddc17', 7),
                ('51c64a6f4fc375daf0d24aafbabe4d91b6f4bb44', 5),
                ('a8478686da38e370e32e42e8a0c220e33ee9132f', 10),
                ('9ef09dfa9d86780bdec9219a22560c6ece8e0ef1', 11),
                ('ed8bce375198ea62444dc71952b22cfc2b09226d', 23)],
                results)
        elif self.key_length == 2:
            self.assertEqual([
                ('00e364d235126be43292ab09cb4686cf703ddc17', 7),
                ('00e364d235126be43292ab09cb4686cf703ddc17', 7),
                ('51c64a6f4fc375daf0d24aafbabe4d91b6f4bb44', 5),
                ('51c64a6f4fc375daf0d24aafbabe4d91b6f4bb44', 5),
                ('a8478686da38e370e32e42e8a0c220e33ee9132f', 10),
                ('a8478686da38e370e32e42e8a0c220e33ee9132f', 10),
                ('9ef09dfa9d86780bdec9219a22560c6ece8e0ef1', 11),
                ('9ef09dfa9d86780bdec9219a22560c6ece8e0ef1', 11),
                ('ed8bce375198ea62444dc71952b22cfc2b09226d', 23),
                ('ed8bce375198ea62444dc71952b22cfc2b09226d', 23)],
                results)

    def test_empty_lines(self):
        """Empty files can be stored."""
        f = self.get_versionedfiles()
        key_a = self.get_simple_key('a')
        f.add_lines(key_a, [], [])
        self.assertEqual('',
            f.get_record_stream([key_a], 'unordered', True
                ).next().get_bytes_as('fulltext'))
        key_b = self.get_simple_key('b')
        f.add_lines(key_b, self.get_parents([key_a]), [])
        self.assertEqual('',
            f.get_record_stream([key_b], 'unordered', True
                ).next().get_bytes_as('fulltext'))

    def test_newline_only(self):
        f = self.get_versionedfiles()
        key_a = self.get_simple_key('a')
        f.add_lines(key_a, [], ['\n'])
        self.assertEqual('\n',
            f.get_record_stream([key_a], 'unordered', True
                ).next().get_bytes_as('fulltext'))
        key_b = self.get_simple_key('b')
        f.add_lines(key_b, self.get_parents([key_a]), ['\n'])
        self.assertEqual('\n',
            f.get_record_stream([key_b], 'unordered', True
                ).next().get_bytes_as('fulltext'))

    def test_get_record_stream_empty(self):
        """An empty stream can be requested without error."""
        f = self.get_versionedfiles()
        entries = f.get_record_stream([], 'unordered', False)
        self.assertEqual([], list(entries))

    def assertValidStorageKind(self, storage_kind):
        """Assert that storage_kind is a valid storage_kind."""
        self.assertSubset([storage_kind],
            ['mpdiff', 'knit-annotated-ft', 'knit-annotated-delta',
             'knit-ft', 'knit-delta', 'fulltext', 'knit-annotated-ft-gz',
             'knit-annotated-delta-gz', 'knit-ft-gz', 'knit-delta-gz'])

    def capture_stream(self, f, entries, on_seen, parents):
        """Capture a stream for testing."""
        for factory in entries:
            on_seen(factory.key)
            self.assertValidStorageKind(factory.storage_kind)
            self.assertEqual(f.get_sha1s([factory.key])[factory.key],
                factory.sha1)
            self.assertEqual(parents[factory.key], factory.parents)
            self.assertIsInstance(factory.get_bytes_as(factory.storage_kind),
                str)

    def test_get_record_stream_interface(self):
        """each item in a stream has to provide a regular interface."""
        files = self.get_versionedfiles()
        self.get_diamond_files(files)
        keys, _ = self.get_keys_and_sort_order()
        parent_map = files.get_parent_map(keys)
        entries = files.get_record_stream(keys, 'unordered', False)
        seen = set()
        self.capture_stream(files, entries, seen.add, parent_map)
        self.assertEqual(set(keys), seen)

    def get_simple_key(self, suffix):
        """Return a key for the object under test."""
        if self.key_length == 1:
            return (suffix,)
        else:
            return ('FileA',) + (suffix,)

    def get_keys_and_sort_order(self):
        """Get diamond test keys list, and their sort ordering."""
        if self.key_length == 1:
            keys = [('merged',), ('left',), ('right',), ('base',)]
            sort_order = {('merged',):2, ('left',):1, ('right',):1, ('base',):0}
        else:
            keys = [
                ('FileA', 'merged'), ('FileA', 'left'), ('FileA', 'right'),
                ('FileA', 'base'),
                ('FileB', 'merged'), ('FileB', 'left'), ('FileB', 'right'),
                ('FileB', 'base'),
                ]
            sort_order = {
                ('FileA', 'merged'):2, ('FileA', 'left'):1, ('FileA', 'right'):1,
                ('FileA', 'base'):0,
                ('FileB', 'merged'):2, ('FileB', 'left'):1, ('FileB', 'right'):1,
                ('FileB', 'base'):0,
                }
        return keys, sort_order

    def test_get_record_stream_interface_ordered(self):
        """each item in a stream has to provide a regular interface."""
        files = self.get_versionedfiles()
        self.get_diamond_files(files)
        keys, sort_order = self.get_keys_and_sort_order()
        parent_map = files.get_parent_map(keys)
        entries = files.get_record_stream(keys, 'topological', False)
        seen = []
        self.capture_stream(files, entries, seen.append, parent_map)
        self.assertStreamOrder(sort_order, seen, keys)

    def test_get_record_stream_interface_ordered_with_delta_closure(self):
        """each item must be accessible as a fulltext."""
        files = self.get_versionedfiles()
        self.get_diamond_files(files)
        keys, sort_order = self.get_keys_and_sort_order()
        parent_map = files.get_parent_map(keys)
        entries = files.get_record_stream(keys, 'topological', True)
        seen = []
        for factory in entries:
            seen.append(factory.key)
            self.assertValidStorageKind(factory.storage_kind)
            self.assertSubset([factory.sha1],
                [None, files.get_sha1s([factory.key])[factory.key]])
            self.assertEqual(parent_map[factory.key], factory.parents)
            # self.assertEqual(files.get_text(factory.key),
            self.assertIsInstance(factory.get_bytes_as('fulltext'), str)
            self.assertIsInstance(factory.get_bytes_as(factory.storage_kind),
                str)
        self.assertStreamOrder(sort_order, seen, keys)

    def assertStreamOrder(self, sort_order, seen, keys):
        self.assertEqual(len(set(seen)), len(keys))
        if self.key_length == 1:
            lows = {():0}
        else:
            lows = {('FileA',):0, ('FileB',):0}
        if not self.graph:
            self.assertEqual(set(keys), set(seen))
        else:
            for key in seen:
                sort_pos = sort_order[key]
                self.assertTrue(sort_pos >= lows[key[:-1]],
                    "Out of order in sorted stream: %r, %r" % (key, seen))
                lows[key[:-1]] = sort_pos

    def test_get_record_stream_unknown_storage_kind_raises(self):
        """Asking for a storage kind that the stream cannot supply raises."""
        files = self.get_versionedfiles()
        self.get_diamond_files(files)
        if self.key_length == 1:
            keys = [('merged',), ('left',), ('right',), ('base',)]
        else:
            keys = [
                ('FileA', 'merged'), ('FileA', 'left'), ('FileA', 'right'),
                ('FileA', 'base'),
                ('FileB', 'merged'), ('FileB', 'left'), ('FileB', 'right'),
                ('FileB', 'base'),
                ]
        parent_map = files.get_parent_map(keys)
        entries = files.get_record_stream(keys, 'unordered', False)
        # We track the contents because we should be able to try, fail a
        # particular kind and then ask for one that works and continue.
        seen = set()
        for factory in entries:
            seen.add(factory.key)
            self.assertValidStorageKind(factory.storage_kind)
            self.assertEqual(files.get_sha1s([factory.key])[factory.key],
                factory.sha1)
            self.assertEqual(parent_map[factory.key], factory.parents)
            # currently no stream emits mpdiff
            self.assertRaises(errors.UnavailableRepresentation,
                factory.get_bytes_as, 'mpdiff')
            self.assertIsInstance(factory.get_bytes_as(factory.storage_kind),
                str)
        self.assertEqual(set(keys), seen)

    def test_get_record_stream_missing_records_are_absent(self):
        files = self.get_versionedfiles()
        self.get_diamond_files(files)
        if self.key_length == 1:
            keys = [('merged',), ('left',), ('right',), ('absent',), ('base',)]
        else:
            keys = [
                ('FileA', 'merged'), ('FileA', 'left'), ('FileA', 'right'),
                ('FileA', 'absent'), ('FileA', 'base'),
                ('FileB', 'merged'), ('FileB', 'left'), ('FileB', 'right'),
                ('FileB', 'absent'), ('FileB', 'base'),
                ('absent', 'absent'),
                ]
        parent_map = files.get_parent_map(keys)
        entries = files.get_record_stream(keys, 'unordered', False)
        self.assertAbsentRecord(files, keys, parent_map, entries)
        entries = files.get_record_stream(keys, 'topological', False)
        self.assertAbsentRecord(files, keys, parent_map, entries)

    def assertAbsentRecord(self, files, keys, parents, entries):
        """Helper for test_get_record_stream_missing_records_are_absent."""
        seen = set()
        for factory in entries:
            seen.add(factory.key)
            if factory.key[-1] == 'absent':
                self.assertEqual('absent', factory.storage_kind)
                self.assertEqual(None, factory.sha1)
                self.assertEqual(None, factory.parents)
            else:
                self.assertValidStorageKind(factory.storage_kind)
                self.assertEqual(files.get_sha1s([factory.key])[factory.key],
                    factory.sha1)
                self.assertEqual(parents[factory.key], factory.parents)
                self.assertIsInstance(factory.get_bytes_as(factory.storage_kind),
                    str)
        self.assertEqual(set(keys), seen)

    def test_filter_absent_records(self):
        """Requested missing records can be filter trivially."""
        files = self.get_versionedfiles()
        self.get_diamond_files(files)
        keys, _ = self.get_keys_and_sort_order()
        parent_map = files.get_parent_map(keys)
        # Add an absent record in the middle of the present keys. (We don't ask
        # for just absent keys to ensure that content before and after the
        # absent keys is still delivered).
        present_keys = list(keys)
        if self.key_length == 1:
            keys.insert(2, ('extra',))
        else:
            keys.insert(2, ('extra', 'extra'))
        entries = files.get_record_stream(keys, 'unordered', False)
        seen = set()
        self.capture_stream(files, versionedfile.filter_absent(entries), seen.add,
            parent_map)
        self.assertEqual(set(present_keys), seen)

    def get_mapper(self):
        """Get a mapper suitable for the key length of the test interface."""
        if self.key_length == 1:
            return ConstantMapper('source')
        else:
            return HashEscapedPrefixMapper()

    def get_parents(self, parents):
        """Get parents, taking self.graph into consideration."""
        if self.graph:
            return parents
        else:
            return None

    def test_get_parent_map(self):
        files = self.get_versionedfiles()
        if self.key_length == 1:
            parent_details = [
                (('r0',), self.get_parents(())),
                (('r1',), self.get_parents((('r0',),))),
                (('r2',), self.get_parents(())),
                (('r3',), self.get_parents(())),
                (('m',), self.get_parents((('r0',),('r1',),('r2',),('r3',)))),
                ]
        else:
            parent_details = [
                (('FileA', 'r0'), self.get_parents(())),
                (('FileA', 'r1'), self.get_parents((('FileA', 'r0'),))),
                (('FileA', 'r2'), self.get_parents(())),
                (('FileA', 'r3'), self.get_parents(())),
                (('FileA', 'm'), self.get_parents((('FileA', 'r0'),
                    ('FileA', 'r1'), ('FileA', 'r2'), ('FileA', 'r3')))),
                ]
        for key, parents in parent_details:
            files.add_lines(key, parents, [])
            # immediately after adding it should be queryable.
            self.assertEqual({key:parents}, files.get_parent_map([key]))
        # We can ask for an empty set
        self.assertEqual({}, files.get_parent_map([]))
        # We can ask for many keys
        all_parents = dict(parent_details)
        self.assertEqual(all_parents, files.get_parent_map(all_parents.keys()))
        # Absent keys are just not included in the result.
        keys = all_parents.keys()
        if self.key_length == 1:
            keys.insert(1, ('missing',))
        else:
            keys.insert(1, ('missing', 'missing'))
        # Absent keys are just ignored
        self.assertEqual(all_parents, files.get_parent_map(keys))

    def test_get_sha1s(self):
        files = self.get_versionedfiles()
        self.get_diamond_files(files)
        if self.key_length == 1:
            keys = [('base',), ('origin',), ('left',), ('merged',), ('right',)]
        else:
            # ask for shas from different prefixes.
            keys = [
                ('FileA', 'base'), ('FileB', 'origin'), ('FileA', 'left'),
                ('FileA', 'merged'), ('FileB', 'right'),
                ]
        self.assertEqual({
            keys[0]: '51c64a6f4fc375daf0d24aafbabe4d91b6f4bb44',
            keys[1]: '00e364d235126be43292ab09cb4686cf703ddc17',
            keys[2]: 'a8478686da38e370e32e42e8a0c220e33ee9132f',
            keys[3]: 'ed8bce375198ea62444dc71952b22cfc2b09226d',
            keys[4]: '9ef09dfa9d86780bdec9219a22560c6ece8e0ef1',
            },
            files.get_sha1s(keys))
        
    def test_insert_record_stream_empty(self):
        """Inserting an empty record stream should work."""
        files = self.get_versionedfiles()
        files.insert_record_stream([])

    def assertIdenticalVersionedFile(self, expected, actual):
        """Assert that left and right have the same contents."""
        self.assertEqual(set(actual.keys()), set(expected.keys()))
        actual_parents = actual.get_parent_map(actual.keys())
        if self.graph:
            self.assertEqual(actual_parents, expected.get_parent_map(expected.keys()))
        else:
            for key, parents in actual_parents.items():
                self.assertEqual(None, parents)
        for key in actual.keys():
            actual_text = actual.get_record_stream(
                [key], 'unordered', True).next().get_bytes_as('fulltext')
            expected_text = expected.get_record_stream(
                [key], 'unordered', True).next().get_bytes_as('fulltext')
            self.assertEqual(actual_text, expected_text)

    def test_insert_record_stream_fulltexts(self):
        """Any file should accept a stream of fulltexts."""
        files = self.get_versionedfiles()
        mapper = self.get_mapper()
        source_transport = self.get_transport('source')
        source_transport.mkdir('.')
        # weaves always output fulltexts.
        source = make_versioned_files_factory(WeaveFile, mapper)(
            source_transport)
        self.get_diamond_files(source, trailing_eol=False)
        stream = source.get_record_stream(source.keys(), 'topological',
            False)
        files.insert_record_stream(stream)
        self.assertIdenticalVersionedFile(source, files)

    def test_insert_record_stream_fulltexts_noeol(self):
        """Any file should accept a stream of fulltexts."""
        files = self.get_versionedfiles()
        mapper = self.get_mapper()
        source_transport = self.get_transport('source')
        source_transport.mkdir('.')
        # weaves always output fulltexts.
        source = make_versioned_files_factory(WeaveFile, mapper)(
            source_transport)
        self.get_diamond_files(source, trailing_eol=False)
        stream = source.get_record_stream(source.keys(), 'topological',
            False)
        files.insert_record_stream(stream)
        self.assertIdenticalVersionedFile(source, files)

    def test_insert_record_stream_annotated_knits(self):
        """Any file should accept a stream from plain knits."""
        files = self.get_versionedfiles()
        mapper = self.get_mapper()
        source_transport = self.get_transport('source')
        source_transport.mkdir('.')
        source = make_file_factory(True, mapper)(source_transport)
        self.get_diamond_files(source)
        stream = source.get_record_stream(source.keys(), 'topological',
            False)
        files.insert_record_stream(stream)
        self.assertIdenticalVersionedFile(source, files)

    def test_insert_record_stream_annotated_knits_noeol(self):
        """Any file should accept a stream from plain knits."""
        files = self.get_versionedfiles()
        mapper = self.get_mapper()
        source_transport = self.get_transport('source')
        source_transport.mkdir('.')
        source = make_file_factory(True, mapper)(source_transport)
        self.get_diamond_files(source, trailing_eol=False)
        stream = source.get_record_stream(source.keys(), 'topological',
            False)
        files.insert_record_stream(stream)
        self.assertIdenticalVersionedFile(source, files)

    def test_insert_record_stream_plain_knits(self):
        """Any file should accept a stream from plain knits."""
        files = self.get_versionedfiles()
        mapper = self.get_mapper()
        source_transport = self.get_transport('source')
        source_transport.mkdir('.')
        source = make_file_factory(False, mapper)(source_transport)
        self.get_diamond_files(source)
        stream = source.get_record_stream(source.keys(), 'topological',
            False)
        files.insert_record_stream(stream)
        self.assertIdenticalVersionedFile(source, files)

    def test_insert_record_stream_plain_knits_noeol(self):
        """Any file should accept a stream from plain knits."""
        files = self.get_versionedfiles()
        mapper = self.get_mapper()
        source_transport = self.get_transport('source')
        source_transport.mkdir('.')
        source = make_file_factory(False, mapper)(source_transport)
        self.get_diamond_files(source, trailing_eol=False)
        stream = source.get_record_stream(source.keys(), 'topological',
            False)
        files.insert_record_stream(stream)
        self.assertIdenticalVersionedFile(source, files)

    def test_insert_record_stream_existing_keys(self):
        """Inserting keys already in a file should not error."""
        files = self.get_versionedfiles()
        source = self.get_versionedfiles('source')
        self.get_diamond_files(source)
        # insert some keys into f.
        self.get_diamond_files(files, left_only=True)
        stream = source.get_record_stream(source.keys(), 'topological',
            False)
        files.insert_record_stream(stream)
        self.assertIdenticalVersionedFile(source, files)

    def test_insert_record_stream_missing_keys(self):
        """Inserting a stream with absent keys should raise an error."""
        files = self.get_versionedfiles()
        source = self.get_versionedfiles('source')
        stream = source.get_record_stream([('missing',) * self.key_length],
            'topological', False)
        self.assertRaises(errors.RevisionNotPresent, files.insert_record_stream,
            stream)

    def test_insert_record_stream_out_of_order(self):
        """An out of order stream can either error or work."""
        files = self.get_versionedfiles()
        source = self.get_versionedfiles('source')
        self.get_diamond_files(source)
        if self.key_length == 1:
            origin_keys = [('origin',)]
            end_keys = [('merged',), ('left',)]
            start_keys = [('right',), ('base',)]
        else:
            origin_keys = [('FileA', 'origin'), ('FileB', 'origin')]
            end_keys = [('FileA', 'merged',), ('FileA', 'left',),
                ('FileB', 'merged',), ('FileB', 'left',)]
            start_keys = [('FileA', 'right',), ('FileA', 'base',),
                ('FileB', 'right',), ('FileB', 'base',)]
        origin_entries = source.get_record_stream(origin_keys, 'unordered', False)
        end_entries = source.get_record_stream(end_keys, 'topological', False)
        start_entries = source.get_record_stream(start_keys, 'topological', False)
        entries = chain(origin_entries, end_entries, start_entries)
        try:
            files.insert_record_stream(entries)
        except RevisionNotPresent:
            # Must not have corrupted the file.
            files.check()
        else:
            self.assertIdenticalVersionedFile(source, files)

    def test_insert_record_stream_delta_missing_basis_no_corruption(self):
        """Insertion where a needed basis is not included aborts safely."""
        # We use a knit always here to be sure we are getting a binary delta.
        mapper = self.get_mapper()
        source_transport = self.get_transport('source')
        source_transport.mkdir('.')
        source = make_file_factory(False, mapper)(source_transport)
        self.get_diamond_files(source)
        entries = source.get_record_stream(['origin', 'merged'], 'unordered', False)
        files = self.get_versionedfiles()
        self.assertRaises(RevisionNotPresent, files.insert_record_stream,
            entries)
        files.check()
        self.assertEqual({}, files.get_parent_map([]))

    def test_iter_lines_added_or_present_in_keys(self):
        # test that we get at least an equalset of the lines added by
        # versions in the store.
        # the ordering here is to make a tree so that dumb searches have
        # more changes to muck up.

        class InstrumentedProgress(progress.DummyProgress):

            def __init__(self):

                progress.DummyProgress.__init__(self)
                self.updates = []

            def update(self, msg=None, current=None, total=None):
                self.updates.append((msg, current, total))

        files = self.get_versionedfiles()
        # add a base to get included
        files.add_lines(self.get_simple_key('base'), (), ['base\n'])
        # add a ancestor to be included on one side
        files.add_lines(self.get_simple_key('lancestor'), (), ['lancestor\n'])
        # add a ancestor to be included on the other side
        files.add_lines(self.get_simple_key('rancestor'),
            self.get_parents([self.get_simple_key('base')]), ['rancestor\n'])
        # add a child of rancestor with no eofile-nl
        files.add_lines(self.get_simple_key('child'),
            self.get_parents([self.get_simple_key('rancestor')]),
            ['base\n', 'child\n'])
        # add a child of lancestor and base to join the two roots
        files.add_lines(self.get_simple_key('otherchild'),
            self.get_parents([self.get_simple_key('lancestor'),
                self.get_simple_key('base')]),
            ['base\n', 'lancestor\n', 'otherchild\n'])
        def iter_with_keys(keys, expected):
            # now we need to see what lines are returned, and how often.
            lines = {}
            progress = InstrumentedProgress()
            # iterate over the lines
            for line in files.iter_lines_added_or_present_in_keys(keys,
                pb=progress):
                lines.setdefault(line, 0)
                lines[line] += 1
            if []!= progress.updates:
                self.assertEqual(expected, progress.updates)
            return lines
        lines = iter_with_keys(
            [self.get_simple_key('child'), self.get_simple_key('otherchild')],
            [('Walking content.', 0, 2),
             ('Walking content.', 1, 2),
             ('Walking content.', 2, 2)])
        # we must see child and otherchild
        self.assertTrue(lines[('child\n', self.get_simple_key('child'))] > 0)
        self.assertTrue(
            lines[('otherchild\n', self.get_simple_key('otherchild'))] > 0)
        # we dont care if we got more than that.
        
        # test all lines
        lines = iter_with_keys(files.keys(),
            [('Walking content.', 0, 5),
             ('Walking content.', 1, 5),
             ('Walking content.', 2, 5),
             ('Walking content.', 3, 5),
             ('Walking content.', 4, 5),
             ('Walking content.', 5, 5)])
        # all lines must be seen at least once
        self.assertTrue(lines[('base\n', self.get_simple_key('base'))] > 0)
        self.assertTrue(
            lines[('lancestor\n', self.get_simple_key('lancestor'))] > 0)
        self.assertTrue(
            lines[('rancestor\n', self.get_simple_key('rancestor'))] > 0)
        self.assertTrue(lines[('child\n', self.get_simple_key('child'))] > 0)
        self.assertTrue(
            lines[('otherchild\n', self.get_simple_key('otherchild'))] > 0)

    def test_make_mpdiffs(self):
        from bzrlib import multiparent
        files = self.get_versionedfiles('source')
        # add texts that should trip the knit maximum delta chain threshold
        # as well as doing parallel chains of data in knits.
        # this is done by two chains of 25 insertions
        files.add_lines(self.get_simple_key('base'), [], ['line\n'])
        files.add_lines(self.get_simple_key('noeol'),
            self.get_parents([self.get_simple_key('base')]), ['line'])
        # detailed eol tests:
        # shared last line with parent no-eol
        files.add_lines(self.get_simple_key('noeolsecond'),
            self.get_parents([self.get_simple_key('noeol')]),
                ['line\n', 'line'])
        # differing last line with parent, both no-eol
        files.add_lines(self.get_simple_key('noeolnotshared'),
            self.get_parents([self.get_simple_key('noeolsecond')]),
                ['line\n', 'phone'])
        # add eol following a noneol parent, change content
        files.add_lines(self.get_simple_key('eol'),
            self.get_parents([self.get_simple_key('noeol')]), ['phone\n'])
        # add eol following a noneol parent, no change content
        files.add_lines(self.get_simple_key('eolline'),
            self.get_parents([self.get_simple_key('noeol')]), ['line\n'])
        # noeol with no parents:
        files.add_lines(self.get_simple_key('noeolbase'), [], ['line'])
        # noeol preceeding its leftmost parent in the output:
        # this is done by making it a merge of two parents with no common
        # anestry: noeolbase and noeol with the 
        # later-inserted parent the leftmost.
        files.add_lines(self.get_simple_key('eolbeforefirstparent'),
            self.get_parents([self.get_simple_key('noeolbase'),
                self.get_simple_key('noeol')]),
            ['line'])
        # two identical eol texts
        files.add_lines(self.get_simple_key('noeoldup'),
            self.get_parents([self.get_simple_key('noeol')]), ['line'])
        next_parent = self.get_simple_key('base')
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
            new_version = self.get_simple_key(text_name + '%s' % depth)
            text = text + ['line\n']
            files.add_lines(new_version, self.get_parents([next_parent]), text)
            next_parent = new_version
        next_parent = self.get_simple_key('base')
        text_name = 'chain2-'
        text = ['line\n']
        for depth in range(26):
            new_version = self.get_simple_key(text_name + '%s' % depth)
            text = text + ['line\n']
            files.add_lines(new_version, self.get_parents([next_parent]), text)
            next_parent = new_version
        target = self.get_versionedfiles('target')
        for key in multiparent.topo_iter_keys(files, files.keys()):
            mpdiff = files.make_mpdiffs([key])[0]
            parents = files.get_parent_map([key])[key] or []
            target.add_mpdiffs(
                [(key, parents, files.get_sha1s([key])[key], mpdiff)])
            self.assertEqualDiff(
                files.get_record_stream([key], 'unordered',
                    True).next().get_bytes_as('fulltext'),
                target.get_record_stream([key], 'unordered',
                    True).next().get_bytes_as('fulltext')
                )

    def test_keys(self):
        # While use is discouraged, versions() is still needed by aspects of
        # bzr.
        files = self.get_versionedfiles()
        self.assertEqual(set(), set(files.keys()))
        if self.key_length == 1:
            key = ('foo',)
        else:
            key = ('foo', 'bar',)
        files.add_lines(key, (), [])
        self.assertEqual(set([key]), set(files.keys()))


class VirtualVersionedFilesTests(TestCase):
    """Basic tests for the VirtualVersionedFiles implementations."""

    def _get_parent_map(self, keys):
        ret = {}
        for k in keys:
            if k in self._parent_map:
                ret[k] = self._parent_map[k]
        return ret

    def setUp(self):
        TestCase.setUp(self)
        self._lines = {}
        self._parent_map = {}
        self.texts = VirtualVersionedFiles(self._get_parent_map, 
                                           self._lines.get)

    def test_add_lines(self):
        self.assertRaises(NotImplementedError, 
                self.texts.add_lines, "foo", [], [])

    def test_add_mpdiffs(self):
        self.assertRaises(NotImplementedError, 
                self.texts.add_mpdiffs, [])

    def test_check(self):
        self.assertTrue(self.texts.check())

    def test_insert_record_stream(self):
        self.assertRaises(NotImplementedError, self.texts.insert_record_stream,
                          [])

    def test_get_sha1s_nonexistent(self):
        self.assertEquals({}, self.texts.get_sha1s([("NONEXISTENT",)]))

    def test_get_sha1s(self):
        self._lines["key"] = ["dataline1", "dataline2"]
        self.assertEquals({("key",): osutils.sha_strings(self._lines["key"])},
                           self.texts.get_sha1s([("key",)]))

    def test_get_parent_map(self):
        self._parent_map = {"G": ("A", "B")}
        self.assertEquals({("G",): (("A",),("B",))}, 
                          self.texts.get_parent_map([("G",), ("L",)]))

    def test_get_record_stream(self):
        self._lines["A"] = ["FOO", "BAR"]
        it = self.texts.get_record_stream([("A",)], "unordered", True)
        record = it.next()
        self.assertEquals("fulltext", record.storage_kind)
        self.assertEquals("FOOBAR", record.get_bytes_as("fulltext"))

    def test_get_record_stream_absent(self):
        it = self.texts.get_record_stream([("A",)], "unordered", True)
        record = it.next()
        self.assertEquals("absent", record.storage_kind)

