# Copyright (C) 2005, 2006 Canonical Ltd
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

"""Tests for Knit data structure"""


import difflib


from bzrlib.errors import KnitError, RevisionAlreadyPresent, NoSuchFile
from bzrlib.knit import (
    KnitContent,
    KnitVersionedFile,
    KnitPlainFactory,
    KnitAnnotateFactory,
    WeaveToKnit)
from bzrlib.osutils import split_lines
from bzrlib.tests import TestCase, TestCaseWithTransport
from bzrlib.transport import TransportLogger, get_transport
from bzrlib.transport.memory import MemoryTransport
from bzrlib.weave import Weave


class KnitContentTests(TestCase):

    def test_constructor(self):
        content = KnitContent([])

    def test_text(self):
        content = KnitContent([])
        self.assertEqual(content.text(), [])

        content = KnitContent([("origin1", "text1"), ("origin2", "text2")])
        self.assertEqual(content.text(), ["text1", "text2"])

    def test_annotate(self):
        content = KnitContent([])
        self.assertEqual(content.annotate(), [])

        content = KnitContent([("origin1", "text1"), ("origin2", "text2")])
        self.assertEqual(content.annotate(),
            [("origin1", "text1"), ("origin2", "text2")])

    def test_annotate_iter(self):
        content = KnitContent([])
        it = content.annotate_iter()
        self.assertRaises(StopIteration, it.next)

        content = KnitContent([("origin1", "text1"), ("origin2", "text2")])
        it = content.annotate_iter()
        self.assertEqual(it.next(), ("origin1", "text1"))
        self.assertEqual(it.next(), ("origin2", "text2"))
        self.assertRaises(StopIteration, it.next)

    def test_copy(self):
        content = KnitContent([("origin1", "text1"), ("origin2", "text2")])
        copy = content.copy()
        self.assertIsInstance(copy, KnitContent)
        self.assertEqual(copy.annotate(),
            [("origin1", "text1"), ("origin2", "text2")])

    def test_line_delta(self):
        content1 = KnitContent([("", "a"), ("", "b")])
        content2 = KnitContent([("", "a"), ("", "a"), ("", "c")])
        self.assertEqual(content1.line_delta(content2),
            [(1, 2, 2, [("", "a"), ("", "c")])])

    def test_line_delta_iter(self):
        content1 = KnitContent([("", "a"), ("", "b")])
        content2 = KnitContent([("", "a"), ("", "a"), ("", "c")])
        it = content1.line_delta_iter(content2)
        self.assertEqual(it.next(), (1, 2, 2, [("", "a"), ("", "c")]))
        self.assertRaises(StopIteration, it.next)

class KnitTests(TestCaseWithTransport):
    """Class containing knit test helper routines."""

    def make_test_knit(self, annotate=False, delay_create=False):
        if not annotate:
            factory = KnitPlainFactory()
        else:
            factory = None
        return KnitVersionedFile('test', get_transport('.'), access_mode='w',
                                 factory=factory, create=True,
                                 delay_create=delay_create)


class BasicKnitTests(KnitTests):

    def add_stock_one_and_one_a(self, k):
        k.add_lines('text-1', [], split_lines(TEXT_1))
        k.add_lines('text-1a', ['text-1'], split_lines(TEXT_1A))

    def test_knit_constructor(self):
        """Construct empty k"""
        self.make_test_knit()

    def test_knit_add(self):
        """Store one text in knit and retrieve"""
        k = self.make_test_knit()
        k.add_lines('text-1', [], split_lines(TEXT_1))
        self.assertTrue(k.has_version('text-1'))
        self.assertEqualDiff(''.join(k.get_lines('text-1')), TEXT_1)

    def test_knit_reload(self):
        # test that the content in a reloaded knit is correct
        k = self.make_test_knit()
        k.add_lines('text-1', [], split_lines(TEXT_1))
        del k
        k2 = KnitVersionedFile('test', get_transport('.'), access_mode='r', factory=KnitPlainFactory(), create=True)
        self.assertTrue(k2.has_version('text-1'))
        self.assertEqualDiff(''.join(k2.get_lines('text-1')), TEXT_1)

    def test_knit_several(self):
        """Store several texts in a knit"""
        k = self.make_test_knit()
        k.add_lines('text-1', [], split_lines(TEXT_1))
        k.add_lines('text-2', [], split_lines(TEXT_2))
        self.assertEqualDiff(''.join(k.get_lines('text-1')), TEXT_1)
        self.assertEqualDiff(''.join(k.get_lines('text-2')), TEXT_2)
        
    def test_repeated_add(self):
        """Knit traps attempt to replace existing version"""
        k = self.make_test_knit()
        k.add_lines('text-1', [], split_lines(TEXT_1))
        self.assertRaises(RevisionAlreadyPresent, 
                k.add_lines,
                'text-1', [], split_lines(TEXT_1))

    def test_empty(self):
        k = self.make_test_knit(True)
        k.add_lines('text-1', [], [])
        self.assertEquals(k.get_lines('text-1'), [])

    def test_incomplete(self):
        """Test if texts without a ending line-end can be inserted and
        extracted."""
        k = KnitVersionedFile('test', get_transport('.'), delta=False, create=True)
        k.add_lines('text-1', [], ['a\n',    'b'  ])
        k.add_lines('text-2', ['text-1'], ['a\rb\n', 'b\n'])
        # reopening ensures maximum room for confusion
        k = KnitVersionedFile('test', get_transport('.'), delta=False, create=True)
        self.assertEquals(k.get_lines('text-1'), ['a\n',    'b'  ])
        self.assertEquals(k.get_lines('text-2'), ['a\rb\n', 'b\n'])

    def test_delta(self):
        """Expression of knit delta as lines"""
        k = self.make_test_knit()
        td = list(line_delta(TEXT_1.splitlines(True),
                             TEXT_1A.splitlines(True)))
        self.assertEqualDiff(''.join(td), delta_1_1a)
        out = apply_line_delta(TEXT_1.splitlines(True), td)
        self.assertEqualDiff(''.join(out), TEXT_1A)

    def test_add_with_parents(self):
        """Store in knit with parents"""
        k = self.make_test_knit()
        self.add_stock_one_and_one_a(k)
        self.assertEquals(k.get_parents('text-1'), [])
        self.assertEquals(k.get_parents('text-1a'), ['text-1'])

    def test_ancestry(self):
        """Store in knit with parents"""
        k = self.make_test_knit()
        self.add_stock_one_and_one_a(k)
        self.assertEquals(set(k.get_ancestry(['text-1a'])), set(['text-1a', 'text-1']))

    def test_add_delta(self):
        """Store in knit with parents"""
        k = KnitVersionedFile('test', get_transport('.'), factory=KnitPlainFactory(),
            delta=True, create=True)
        self.add_stock_one_and_one_a(k)
        k.clear_cache()
        self.assertEqualDiff(''.join(k.get_lines('text-1a')), TEXT_1A)

    def test_annotate(self):
        """Annotations"""
        k = KnitVersionedFile('knit', get_transport('.'), factory=KnitAnnotateFactory(),
            delta=True, create=True)
        self.insert_and_test_small_annotate(k)

    def insert_and_test_small_annotate(self, k):
        """test annotation with k works correctly."""
        k.add_lines('text-1', [], ['a\n', 'b\n'])
        k.add_lines('text-2', ['text-1'], ['a\n', 'c\n'])

        origins = k.annotate('text-2')
        self.assertEquals(origins[0], ('text-1', 'a\n'))
        self.assertEquals(origins[1], ('text-2', 'c\n'))

    def test_annotate_fulltext(self):
        """Annotations"""
        k = KnitVersionedFile('knit', get_transport('.'), factory=KnitAnnotateFactory(),
            delta=False, create=True)
        self.insert_and_test_small_annotate(k)

    def test_annotate_merge_1(self):
        k = self.make_test_knit(True)
        k.add_lines('text-a1', [], ['a\n', 'b\n'])
        k.add_lines('text-a2', [], ['d\n', 'c\n'])
        k.add_lines('text-am', ['text-a1', 'text-a2'], ['d\n', 'b\n'])
        origins = k.annotate('text-am')
        self.assertEquals(origins[0], ('text-a2', 'd\n'))
        self.assertEquals(origins[1], ('text-a1', 'b\n'))

    def test_annotate_merge_2(self):
        k = self.make_test_knit(True)
        k.add_lines('text-a1', [], ['a\n', 'b\n', 'c\n'])
        k.add_lines('text-a2', [], ['x\n', 'y\n', 'z\n'])
        k.add_lines('text-am', ['text-a1', 'text-a2'], ['a\n', 'y\n', 'c\n'])
        origins = k.annotate('text-am')
        self.assertEquals(origins[0], ('text-a1', 'a\n'))
        self.assertEquals(origins[1], ('text-a2', 'y\n'))
        self.assertEquals(origins[2], ('text-a1', 'c\n'))

    def test_annotate_merge_9(self):
        k = self.make_test_knit(True)
        k.add_lines('text-a1', [], ['a\n', 'b\n', 'c\n'])
        k.add_lines('text-a2', [], ['x\n', 'y\n', 'z\n'])
        k.add_lines('text-am', ['text-a1', 'text-a2'], ['k\n', 'y\n', 'c\n'])
        origins = k.annotate('text-am')
        self.assertEquals(origins[0], ('text-am', 'k\n'))
        self.assertEquals(origins[1], ('text-a2', 'y\n'))
        self.assertEquals(origins[2], ('text-a1', 'c\n'))

    def test_annotate_merge_3(self):
        k = self.make_test_knit(True)
        k.add_lines('text-a1', [], ['a\n', 'b\n', 'c\n'])
        k.add_lines('text-a2', [] ,['x\n', 'y\n', 'z\n'])
        k.add_lines('text-am', ['text-a1', 'text-a2'], ['k\n', 'y\n', 'z\n'])
        origins = k.annotate('text-am')
        self.assertEquals(origins[0], ('text-am', 'k\n'))
        self.assertEquals(origins[1], ('text-a2', 'y\n'))
        self.assertEquals(origins[2], ('text-a2', 'z\n'))

    def test_annotate_merge_4(self):
        k = self.make_test_knit(True)
        k.add_lines('text-a1', [], ['a\n', 'b\n', 'c\n'])
        k.add_lines('text-a2', [], ['x\n', 'y\n', 'z\n'])
        k.add_lines('text-a3', ['text-a1'], ['a\n', 'b\n', 'p\n'])
        k.add_lines('text-am', ['text-a2', 'text-a3'], ['a\n', 'b\n', 'z\n'])
        origins = k.annotate('text-am')
        self.assertEquals(origins[0], ('text-a1', 'a\n'))
        self.assertEquals(origins[1], ('text-a1', 'b\n'))
        self.assertEquals(origins[2], ('text-a2', 'z\n'))

    def test_annotate_merge_5(self):
        k = self.make_test_knit(True)
        k.add_lines('text-a1', [], ['a\n', 'b\n', 'c\n'])
        k.add_lines('text-a2', [], ['d\n', 'e\n', 'f\n'])
        k.add_lines('text-a3', [], ['x\n', 'y\n', 'z\n'])
        k.add_lines('text-am',
                    ['text-a1', 'text-a2', 'text-a3'],
                    ['a\n', 'e\n', 'z\n'])
        origins = k.annotate('text-am')
        self.assertEquals(origins[0], ('text-a1', 'a\n'))
        self.assertEquals(origins[1], ('text-a2', 'e\n'))
        self.assertEquals(origins[2], ('text-a3', 'z\n'))

    def test_annotate_file_cherry_pick(self):
        k = self.make_test_knit(True)
        k.add_lines('text-1', [], ['a\n', 'b\n', 'c\n'])
        k.add_lines('text-2', ['text-1'], ['d\n', 'e\n', 'f\n'])
        k.add_lines('text-3', ['text-2', 'text-1'], ['a\n', 'b\n', 'c\n'])
        origins = k.annotate('text-3')
        self.assertEquals(origins[0], ('text-1', 'a\n'))
        self.assertEquals(origins[1], ('text-1', 'b\n'))
        self.assertEquals(origins[2], ('text-1', 'c\n'))

    def test_knit_join(self):
        """Store in knit with parents"""
        k1 = KnitVersionedFile('test1', get_transport('.'), factory=KnitPlainFactory(), create=True)
        k1.add_lines('text-a', [], split_lines(TEXT_1))
        k1.add_lines('text-b', ['text-a'], split_lines(TEXT_1))

        k1.add_lines('text-c', [], split_lines(TEXT_1))
        k1.add_lines('text-d', ['text-c'], split_lines(TEXT_1))

        k1.add_lines('text-m', ['text-b', 'text-d'], split_lines(TEXT_1))

        k2 = KnitVersionedFile('test2', get_transport('.'), factory=KnitPlainFactory(), create=True)
        count = k2.join(k1, version_ids=['text-m'])
        self.assertEquals(count, 5)
        self.assertTrue(k2.has_version('text-a'))
        self.assertTrue(k2.has_version('text-c'))

    def test_reannotate(self):
        k1 = KnitVersionedFile('knit1', get_transport('.'),
                               factory=KnitAnnotateFactory(), create=True)
        # 0
        k1.add_lines('text-a', [], ['a\n', 'b\n'])
        # 1
        k1.add_lines('text-b', ['text-a'], ['a\n', 'c\n'])

        k2 = KnitVersionedFile('test2', get_transport('.'),
                               factory=KnitAnnotateFactory(), create=True)
        k2.join(k1, version_ids=['text-b'])

        # 2
        k1.add_lines('text-X', ['text-b'], ['a\n', 'b\n'])
        # 2
        k2.add_lines('text-c', ['text-b'], ['z\n', 'c\n'])
        # 3
        k2.add_lines('text-Y', ['text-b'], ['b\n', 'c\n'])

        # test-c will have index 3
        k1.join(k2, version_ids=['text-c'])

        lines = k1.get_lines('text-c')
        self.assertEquals(lines, ['z\n', 'c\n'])

        origins = k1.annotate('text-c')
        self.assertEquals(origins[0], ('text-c', 'z\n'))
        self.assertEquals(origins[1], ('text-b', 'c\n'))

    def test_get_line_delta_texts(self):
        """Make sure we can call get_texts on text with reused line deltas"""
        k1 = KnitVersionedFile('test1', get_transport('.'), 
                               factory=KnitPlainFactory(), create=True)
        for t in range(3):
            if t == 0:
                parents = []
            else:
                parents = ['%d' % (t-1)]
            k1.add_lines('%d' % t, parents, ['hello\n'] * t)
        k1.get_texts(('%d' % t) for t in range(3))
        
    def test_iter_lines_reads_in_order(self):
        t = MemoryTransport()
        instrumented_t = TransportLogger(t)
        k1 = KnitVersionedFile('id', instrumented_t, create=True, delta=True)
        self.assertEqual([('id.kndx',)], instrumented_t._calls)
        # add texts with no required ordering
        k1.add_lines('base', [], ['text\n'])
        k1.add_lines('base2', [], ['text2\n'])
        k1.clear_cache()
        instrumented_t._calls = []
        # request a last-first iteration
        results = list(k1.iter_lines_added_or_present_in_versions(['base2', 'base']))
        self.assertEqual([('id.knit', [(0, 87), (87, 89)])], instrumented_t._calls)
        self.assertEqual(['text\n', 'text2\n'], results)

    def test_create_empty_annotated(self):
        k1 = self.make_test_knit(True)
        # 0
        k1.add_lines('text-a', [], ['a\n', 'b\n'])
        k2 = k1.create_empty('t', MemoryTransport())
        self.assertTrue(isinstance(k2.factory, KnitAnnotateFactory))
        self.assertEqual(k1.delta, k2.delta)
        # the generic test checks for empty content and file class

    def test_knit_format(self):
        # this tests that a new knit index file has the expected content
        # and that is writes the data we expect as records are added.
        knit = self.make_test_knit(True)
        # Now knit files are not created until we first add data to them
        self.assertFileEqual("# bzr knit index 8\n", 'test.kndx')
        knit.add_lines_with_ghosts('revid', ['a_ghost'], ['a\n'])
        self.assertFileEqual(
            "# bzr knit index 8\n"
            "\n"
            "revid fulltext 0 84 .a_ghost :",
            'test.kndx')
        knit.add_lines_with_ghosts('revid2', ['revid'], ['a\n'])
        self.assertFileEqual(
            "# bzr knit index 8\n"
            "\nrevid fulltext 0 84 .a_ghost :"
            "\nrevid2 line-delta 84 82 0 :",
            'test.kndx')
        # we should be able to load this file again
        knit = KnitVersionedFile('test', get_transport('.'), access_mode='r')
        self.assertEqual(['revid', 'revid2'], knit.versions())
        # write a short write to the file and ensure that its ignored
        indexfile = file('test.kndx', 'at')
        indexfile.write('\nrevid3 line-delta 166 82 1 2 3 4 5 .phwoar:demo ')
        indexfile.close()
        # we should be able to load this file again
        knit = KnitVersionedFile('test', get_transport('.'), access_mode='w')
        self.assertEqual(['revid', 'revid2'], knit.versions())
        # and add a revision with the same id the failed write had
        knit.add_lines('revid3', ['revid2'], ['a\n'])
        # and when reading it revid3 should now appear.
        knit = KnitVersionedFile('test', get_transport('.'), access_mode='r')
        self.assertEqual(['revid', 'revid2', 'revid3'], knit.versions())
        self.assertEqual(['revid2'], knit.get_parents('revid3'))

    def test_delay_create(self):
        """Test that passing delay_create=True creates files late"""
        knit = self.make_test_knit(annotate=True, delay_create=True)
        self.failIfExists('test.knit')
        self.failIfExists('test.kndx')
        knit.add_lines_with_ghosts('revid', ['a_ghost'], ['a\n'])
        self.failUnlessExists('test.knit')
        self.assertFileEqual(
            "# bzr knit index 8\n"
            "\n"
            "revid fulltext 0 84 .a_ghost :",
            'test.kndx')

    def test_create_parent_dir(self):
        """create_parent_dir can create knits in nonexistant dirs"""
        # Has no effect if we don't set 'delay_create'
        trans = get_transport('.')
        self.assertRaises(NoSuchFile, KnitVersionedFile, 'dir/test',
                          trans, access_mode='w', factory=None,
                          create=True, create_parent_dir=True)
        # Nothing should have changed yet
        knit = KnitVersionedFile('dir/test', trans, access_mode='w',
                                 factory=None, create=True,
                                 create_parent_dir=True,
                                 delay_create=True)
        self.failIfExists('dir/test.knit')
        self.failIfExists('dir/test.kndx')
        self.failIfExists('dir')
        knit.add_lines('revid', [], ['a\n'])
        self.failUnlessExists('dir')
        self.failUnlessExists('dir/test.knit')
        self.assertFileEqual(
            "# bzr knit index 8\n"
            "\n"
            "revid fulltext 0 84  :",
            'dir/test.kndx')

    def test_create_mode_700(self):
        trans = get_transport('.')
        if not trans._can_roundtrip_unix_modebits():
            # Can't roundtrip, so no need to run this test
            return
        knit = KnitVersionedFile('dir/test', trans, access_mode='w',
                                 factory=None, create=True,
                                 create_parent_dir=True,
                                 delay_create=True,
                                 file_mode=0600,
                                 dir_mode=0700)
        knit.add_lines('revid', [], ['a\n'])
        self.assertTransportMode(trans, 'dir', 0700)
        self.assertTransportMode(trans, 'dir/test.knit', 0600)
        self.assertTransportMode(trans, 'dir/test.kndx', 0600)

    def test_create_mode_770(self):
        trans = get_transport('.')
        if not trans._can_roundtrip_unix_modebits():
            # Can't roundtrip, so no need to run this test
            return
        knit = KnitVersionedFile('dir/test', trans, access_mode='w',
                                 factory=None, create=True,
                                 create_parent_dir=True,
                                 delay_create=True,
                                 file_mode=0660,
                                 dir_mode=0770)
        knit.add_lines('revid', [], ['a\n'])
        self.assertTransportMode(trans, 'dir', 0770)
        self.assertTransportMode(trans, 'dir/test.knit', 0660)
        self.assertTransportMode(trans, 'dir/test.kndx', 0660)

    def test_create_mode_777(self):
        trans = get_transport('.')
        if not trans._can_roundtrip_unix_modebits():
            # Can't roundtrip, so no need to run this test
            return
        knit = KnitVersionedFile('dir/test', trans, access_mode='w',
                                 factory=None, create=True,
                                 create_parent_dir=True,
                                 delay_create=True,
                                 file_mode=0666,
                                 dir_mode=0777)
        knit.add_lines('revid', [], ['a\n'])
        self.assertTransportMode(trans, 'dir', 0777)
        self.assertTransportMode(trans, 'dir/test.knit', 0666)
        self.assertTransportMode(trans, 'dir/test.kndx', 0666)

    def test_plan_merge(self):
        my_knit = self.make_test_knit(annotate=True)
        my_knit.add_lines('text1', [], split_lines(TEXT_1))
        my_knit.add_lines('text1a', ['text1'], split_lines(TEXT_1A))
        my_knit.add_lines('text1b', ['text1'], split_lines(TEXT_1B))
        plan = list(my_knit.plan_merge('text1a', 'text1b'))
        for plan_line, expected_line in zip(plan, AB_MERGE):
            self.assertEqual(plan_line, expected_line)


TEXT_1 = """\
Banana cup cakes:

- bananas
- eggs
- broken tea cups
"""

TEXT_1A = """\
Banana cup cake recipe
(serves 6)

- bananas
- eggs
- broken tea cups
- self-raising flour
"""

TEXT_1B = """\
Banana cup cake recipe

- bananas (do not use plantains!!!)
- broken tea cups
- flour
"""

delta_1_1a = """\
0,1,2
Banana cup cake recipe
(serves 6)
5,5,1
- self-raising flour
"""

TEXT_2 = """\
Boeuf bourguignon

- beef
- red wine
- small onions
- carrot
- mushrooms
"""

AB_MERGE_TEXT="""unchanged|Banana cup cake recipe
new-a|(serves 6)
unchanged|
killed-b|- bananas
killed-b|- eggs
new-b|- bananas (do not use plantains!!!)
unchanged|- broken tea cups
new-a|- self-raising flour
new-b|- flour
"""
AB_MERGE=[tuple(l.split('|')) for l in AB_MERGE_TEXT.splitlines(True)]


def line_delta(from_lines, to_lines):
    """Generate line-based delta from one text to another"""
    s = difflib.SequenceMatcher(None, from_lines, to_lines)
    for op in s.get_opcodes():
        if op[0] == 'equal':
            continue
        yield '%d,%d,%d\n' % (op[1], op[2], op[4]-op[3])
        for i in range(op[3], op[4]):
            yield to_lines[i]


def apply_line_delta(basis_lines, delta_lines):
    """Apply a line-based perfect diff
    
    basis_lines -- text to apply the patch to
    delta_lines -- diff instructions and content
    """
    out = basis_lines[:]
    i = 0
    offset = 0
    while i < len(delta_lines):
        l = delta_lines[i]
        a, b, c = map(long, l.split(','))
        i = i + 1
        out[offset+a:offset+b] = delta_lines[i:i+c]
        i = i + c
        offset = offset + (b - a) + c
    return out


class TestWeaveToKnit(KnitTests):

    def test_weave_to_knit_matches(self):
        # check that the WeaveToKnit is_compatible function
        # registers True for a Weave to a Knit.
        w = Weave()
        k = self.make_test_knit()
        self.failUnless(WeaveToKnit.is_compatible(w, k))
        self.failIf(WeaveToKnit.is_compatible(k, w))
        self.failIf(WeaveToKnit.is_compatible(w, w))
        self.failIf(WeaveToKnit.is_compatible(k, k))


class TestKnitCaching(KnitTests):
    
    def create_knit(self, cache_add=False):
        k = self.make_test_knit(True)
        if cache_add:
            k.enable_cache()

        k.add_lines('text-1', [], split_lines(TEXT_1))
        k.add_lines('text-2', [], split_lines(TEXT_2))
        return k

    def test_no_caching(self):
        k = self.create_knit()
        # Nothing should be cached without setting 'enable_cache'
        self.assertEqual({}, k._data._cache)

    def test_cache_add_and_clear(self):
        k = self.create_knit(True)

        self.assertEqual(['text-1', 'text-2'], sorted(k._data._cache.keys()))

        k.clear_cache()
        self.assertEqual({}, k._data._cache)

    def test_cache_data_read_raw(self):
        k = self.create_knit()

        # Now cache and read
        k.enable_cache()

        def read_one_raw(version):
            pos_map = k._get_components_positions([version])
            method, pos, size, next = pos_map[version]
            lst = list(k._data.read_records_iter_raw([(version, pos, size)]))
            self.assertEqual(1, len(lst))
            return lst[0]

        val = read_one_raw('text-1')
        self.assertEqual({'text-1':val[1]}, k._data._cache)

        k.clear_cache()
        # After clear, new reads are not cached
        self.assertEqual({}, k._data._cache)

        val2 = read_one_raw('text-1')
        self.assertEqual(val, val2)
        self.assertEqual({}, k._data._cache)

    def test_cache_data_read(self):
        k = self.create_knit()

        def read_one(version):
            pos_map = k._get_components_positions([version])
            method, pos, size, next = pos_map[version]
            lst = list(k._data.read_records_iter([(version, pos, size)]))
            self.assertEqual(1, len(lst))
            return lst[0]

        # Now cache and read
        k.enable_cache()

        val = read_one('text-2')
        self.assertEqual(['text-2'], k._data._cache.keys())
        self.assertEqual('text-2', val[0])
        content, digest = k._data._parse_record('text-2',
                                                k._data._cache['text-2'])
        self.assertEqual(content, val[1])
        self.assertEqual(digest, val[2])

        k.clear_cache()
        self.assertEqual({}, k._data._cache)

        val2 = read_one('text-2')
        self.assertEqual(val, val2)
        self.assertEqual({}, k._data._cache)

    def test_cache_read(self):
        k = self.create_knit()
        k.enable_cache()

        text = k.get_text('text-1')
        self.assertEqual(TEXT_1, text)
        self.assertEqual(['text-1'], k._data._cache.keys())

        k.clear_cache()
        self.assertEqual({}, k._data._cache)

        text = k.get_text('text-1')
        self.assertEqual(TEXT_1, text)
        self.assertEqual({}, k._data._cache)


class TestKnitIndex(KnitTests):

    def test_add_versions_dictionary_compresses(self):
        """Adding versions to the index should update the lookup dict"""
        knit = self.make_test_knit()
        idx = knit._index
        idx.add_version('a-1', ['fulltext'], 0, 0, [])
        self.check_file_contents('test.kndx',
            '# bzr knit index 8\n'
            '\n'
            'a-1 fulltext 0 0  :'
            )
        idx.add_versions([('a-2', ['fulltext'], 0, 0, ['a-1']),
                          ('a-3', ['fulltext'], 0, 0, ['a-2']),
                         ])
        self.check_file_contents('test.kndx',
            '# bzr knit index 8\n'
            '\n'
            'a-1 fulltext 0 0  :\n'
            'a-2 fulltext 0 0 0 :\n'
            'a-3 fulltext 0 0 1 :'
            )
        self.assertEqual(['a-1', 'a-2', 'a-3'], idx._history)
        self.assertEqual({'a-1':('a-1', ['fulltext'], 0, 0, [], 0),
                          'a-2':('a-2', ['fulltext'], 0, 0, ['a-1'], 1),
                          'a-3':('a-3', ['fulltext'], 0, 0, ['a-2'], 2),
                         }, idx._cache)

    def test_add_versions_fails_clean(self):
        """If add_versions fails in the middle, it restores a pristine state.

        Any modifications that are made to the index are reset if all versions
        cannot be added.
        """
        # This cheats a little bit by passing in a generator which will
        # raise an exception before the processing finishes
        # Other possibilities would be to have an version with the wrong number
        # of entries, or to make the backing transport unable to write any
        # files.

        knit = self.make_test_knit()
        idx = knit._index
        idx.add_version('a-1', ['fulltext'], 0, 0, [])

        class StopEarly(Exception):
            pass

        def generate_failure():
            """Add some entries and then raise an exception"""
            yield ('a-2', ['fulltext'], 0, 0, ['a-1'])
            yield ('a-3', ['fulltext'], 0, 0, ['a-2'])
            raise StopEarly()

        # Assert the pre-condition
        self.assertEqual(['a-1'], idx._history)
        self.assertEqual({'a-1':('a-1', ['fulltext'], 0, 0, [], 0)}, idx._cache)

        self.assertRaises(StopEarly, idx.add_versions, generate_failure())

        # And it shouldn't be modified
        self.assertEqual(['a-1'], idx._history)
        self.assertEqual({'a-1':('a-1', ['fulltext'], 0, 0, [], 0)}, idx._cache)
