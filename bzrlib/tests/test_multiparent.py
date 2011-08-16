# Copyright (C) 2007, 2009, 2011 Canonical Ltd
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

from unittest import TestCase

from bzrlib import (
    multiparent,
    patiencediff,
    tests,
    )


LINES_1 = "a\nb\nc\nd\ne\n".splitlines(True)
LINES_2 = "a\nc\nd\ne\n".splitlines(True)
LINES_3 = "a\nb\nc\nd\n".splitlines(True)
LF_SPLIT_LINES = ['\x00\n', '\x00\r\x01\n', '\x02\r\xff']


class Mock(object):

    def __init__(self, **kwargs):
        self.__dict__ = kwargs


class TestMulti(TestCase):

    def test_compare_no_parent(self):
        diff = multiparent.MultiParent.from_lines(LINES_1)
        self.assertEqual([multiparent.NewText(LINES_1)], diff.hunks)

    def test_compare_one_parent(self):
        diff = multiparent.MultiParent.from_lines(LINES_1, [LINES_2])
        self.assertEqual([multiparent.ParentText(0, 0, 0, 1),
                          multiparent.NewText(['b\n']),
                          multiparent.ParentText(0, 1, 2, 3)],
                         diff.hunks)

        diff = multiparent.MultiParent.from_lines(LINES_2, [LINES_1])
        self.assertEqual([multiparent.ParentText(0, 0, 0, 1),
                          multiparent.ParentText(0, 2, 1, 3)],
                         diff.hunks)

    def test_compare_two_parents(self):
        diff = multiparent.MultiParent.from_lines(LINES_1, [LINES_2, LINES_3])
        self.assertEqual([multiparent.ParentText(1, 0, 0, 4),
                          multiparent.ParentText(0, 3, 4, 1)],
                         diff.hunks)

    def test_compare_two_parents_blocks(self):
        matcher = patiencediff.PatienceSequenceMatcher(None, LINES_2, LINES_1)
        blocks = matcher.get_matching_blocks()
        diff = multiparent.MultiParent.from_lines(LINES_1, [LINES_2, LINES_3],
                                                  left_blocks=blocks)
        self.assertEqual([multiparent.ParentText(1, 0, 0, 4),
                          multiparent.ParentText(0, 3, 4, 1)],
                         diff.hunks)

    def test_get_matching_blocks(self):
        diff = multiparent.MultiParent.from_lines(LINES_1, [LINES_2])
        self.assertEqual([(0, 0, 1), (1, 2, 3), (4, 5, 0)],
                         list(diff.get_matching_blocks(0, len(LINES_2))))

        diff = multiparent.MultiParent.from_lines(LINES_2, [LINES_1])
        self.assertEqual([(0, 0, 1), (2, 1, 3), (5, 4, 0)],
                         list(diff.get_matching_blocks(0, len(LINES_1))))

    def test_range_iterator(self):
        diff = multiparent.MultiParent.from_lines(LINES_1, [LINES_2, LINES_3])
        diff.hunks.append(multiparent.NewText(['q\n']))
        self.assertEqual([(0, 4, 'parent', (1, 0, 4)),
                          (4, 5, 'parent', (0, 3, 4)),
                          (5, 6, 'new', ['q\n'])],
                         list(diff.range_iterator()))

    def test_eq(self):
        diff = multiparent.MultiParent.from_lines(LINES_1)
        diff2 = multiparent.MultiParent.from_lines(LINES_1)
        self.assertEqual(diff, diff2)
        diff3 = multiparent.MultiParent.from_lines(LINES_2)
        self.assertFalse(diff == diff3)
        self.assertFalse(diff == Mock(hunks=[multiparent.NewText(LINES_1)]))
        self.assertEqual(multiparent.MultiParent(
                         [multiparent.NewText(LINES_1),
                          multiparent.ParentText(0, 1, 2, 3)]),
                         multiparent.MultiParent(
                         [multiparent.NewText(LINES_1),
                          multiparent.ParentText(0, 1, 2, 3)]))

    def test_to_patch(self):
        self.assertEqual(['i 1\n', 'a\n', '\n', 'c 0 1 2 3\n'],
            list(multiparent.MultiParent([multiparent.NewText(['a\n']),
            multiparent.ParentText(0, 1, 2, 3)]).to_patch()))

    def test_from_patch(self):
        self.assertEqual(multiparent.MultiParent(
            [multiparent.NewText(['a\n']),
             multiparent.ParentText(0, 1, 2, 3)]),
             multiparent.MultiParent.from_patch('i 1\na\n\nc 0 1 2 3'))
        self.assertEqual(multiparent.MultiParent(
            [multiparent.NewText(['a']),
             multiparent.ParentText(0, 1, 2, 3)]),
             multiparent.MultiParent.from_patch('i 1\na\nc 0 1 2 3\n'))

    def test_binary_content(self):
        patch = list(
            multiparent.MultiParent.from_lines(LF_SPLIT_LINES).to_patch())
        multiparent.MultiParent.from_patch(''.join(patch))

    def test_make_patch_from_binary(self):
        patch = multiparent.MultiParent.from_texts(''.join(LF_SPLIT_LINES))
        expected = multiparent.MultiParent([
            multiparent.NewText(LF_SPLIT_LINES)])
        self.assertEqual(expected, patch)

    def test_num_lines(self):
        mp = multiparent.MultiParent([multiparent.NewText(['a\n'])])
        self.assertEqual(1, mp.num_lines())
        mp.hunks.append(multiparent.NewText(['b\n', 'c\n']))
        self.assertEqual(3, mp.num_lines())
        mp.hunks.append(multiparent.ParentText(0, 0, 3, 2))
        self.assertEqual(5, mp.num_lines())
        mp.hunks.append(multiparent.NewText(['f\n', 'g\n']))
        self.assertEqual(7, mp.num_lines())

    def test_to_lines(self):
        mpdiff = multiparent.MultiParent.from_texts('a\nb\nc\n', ('b\nc\n',))
        lines = mpdiff.to_lines(('b\ne\n',))
        self.assertEqual(['a\n', 'b\n', 'e\n'], lines)


class TestNewText(TestCase):

    def test_eq(self):
        self.assertEqual(multiparent.NewText([]), multiparent.NewText([]))
        self.assertFalse(multiparent.NewText(['a']) ==
                         multiparent.NewText(['b']))
        self.assertFalse(multiparent.NewText(['a']) == Mock(lines=['a']))

    def test_to_patch(self):
        self.assertEqual(['i 0\n', '\n'],
                         list(multiparent.NewText([]).to_patch()))
        self.assertEqual(['i 1\n', 'a', '\n'],
                         list(multiparent.NewText(['a']).to_patch()))
        self.assertEqual(['i 1\n', 'a\n', '\n'],
                         list(multiparent.NewText(['a\n']).to_patch()))


class TestParentText(TestCase):

    def test_eq(self):
        self.assertEqual(multiparent.ParentText(1, 2, 3, 4),
                         multiparent.ParentText(1, 2, 3, 4))
        self.assertFalse(multiparent.ParentText(1, 2, 3, 4) ==
                         multiparent.ParentText(2, 2, 3, 4))
        self.assertFalse(multiparent.ParentText(1, 2, 3, 4) ==
                         Mock(parent=1, parent_pos=2, child_pos=3,
                              num_lines=4))

    def test_to_patch(self):
        self.assertEqual(['c 0 1 2 3\n'],
                         list(multiparent.ParentText(0, 1, 2, 3).to_patch()))


REV_A = ['a\n', 'b\n', 'c\n', 'd\n']
REV_B = ['a\n', 'c\n', 'd\n', 'e\n']
REV_C = ['a\n', 'b\n', 'e\n', 'f\n']


class TestVersionedFile(TestCase):

    def add_version(self, vf, text, version_id, parent_ids):
        vf.add_version([(t+'\n') for t in text], version_id, parent_ids)

    def make_vf(self):
        vf = multiparent.MultiMemoryVersionedFile()
        self.add_version(vf, 'abcd', 'rev-a', [])
        self.add_version(vf, 'acde', 'rev-b', [])
        self.add_version(vf, 'abef', 'rev-c', ['rev-a', 'rev-b'])
        return vf

    def test_add_version(self):
        vf = self.make_vf()
        self.assertEqual(REV_A, vf._lines['rev-a'])
        vf.clear_cache()
        self.assertEqual(vf._lines, {})

    def test_get_line_list(self):
        vf = self.make_vf()
        vf.clear_cache()
        self.assertEqual(REV_A, vf.get_line_list(['rev-a'])[0])
        self.assertEqual([REV_B, REV_C], vf.get_line_list(['rev-b', 'rev-c']))

    def test_reconstruct_empty(self):
        vf = multiparent.MultiMemoryVersionedFile()
        vf.add_version([], 'a', [])
        self.assertEqual([], self.reconstruct_version(vf, 'a'))

    @staticmethod
    def reconstruct(vf, revision_id, start, end):
        reconstructor = multiparent._Reconstructor(vf, vf._lines,
                                                   vf._parents)
        lines = []
        reconstructor._reconstruct(lines, revision_id, start, end)
        return lines

    @staticmethod
    def reconstruct_version(vf, revision_id):
        reconstructor = multiparent._Reconstructor(vf, vf._lines,
                                                   vf._parents)
        lines = []
        reconstructor.reconstruct_version(lines, revision_id)
        return lines

    def test_reconstructor(self):
        vf = self.make_vf()
        self.assertEqual(['a\n', 'b\n'], self.reconstruct(vf, 'rev-a',  0, 2))
        self.assertEqual(['c\n', 'd\n'], self.reconstruct(vf, 'rev-a',  2, 4))
        self.assertEqual(['e\n', 'f\n'], self.reconstruct(vf, 'rev-c',  2, 4))
        self.assertEqual(['a\n', 'b\n', 'e\n', 'f\n'],
                          self.reconstruct(vf, 'rev-c',  0, 4))
        self.assertEqual(['a\n', 'b\n', 'e\n', 'f\n'],
                          self.reconstruct_version(vf, 'rev-c'))

    def test_reordered(self):
        """Check for a corner case that requires re-starting the cursor"""
        vf = multiparent.MultiMemoryVersionedFile()
        # rev-b must have at least two hunks, so split a and b with c.
        self.add_version(vf, 'c', 'rev-a', [])
        self.add_version(vf, 'acb', 'rev-b', ['rev-a'])
        # rev-c and rev-d must each have a line from a different rev-b hunk
        self.add_version(vf, 'b', 'rev-c', ['rev-b'])
        self.add_version(vf, 'a', 'rev-d', ['rev-b'])
        # The lines from rev-c and rev-d must appear in the opposite order
        self.add_version(vf, 'ba', 'rev-e', ['rev-c', 'rev-d'])
        vf.clear_cache()
        lines = vf.get_line_list(['rev-e'])[0]
        self.assertEqual(['b\n', 'a\n'], lines)


class TestMultiVersionedFile(tests.TestCaseInTempDir):

    def test_save_load(self):
        vf = multiparent.MultiVersionedFile('foop')
        vf.add_version('a\nb\nc\nd'.splitlines(True), 'a', [])
        vf.add_version('a\ne\nd\n'.splitlines(True), 'b', ['a'])
        vf.save()
        newvf = multiparent.MultiVersionedFile('foop')
        newvf.load()
        self.assertEqual('a\nb\nc\nd', ''.join(newvf.get_line_list(['a'])[0]))
        self.assertEqual('a\ne\nd\n', ''.join(newvf.get_line_list(['b'])[0]))

    def test_filenames(self):
        vf = multiparent.MultiVersionedFile('foop')
        vf.add_version('a\nb\nc\nd'.splitlines(True), 'a', [])
        self.assertPathExists('foop.mpknit')
        self.assertPathDoesNotExist('foop.mpidx')
        vf.save()
        self.assertPathExists('foop.mpidx')
        vf.destroy()
        self.assertPathDoesNotExist('foop.mpknit')
        self.assertPathDoesNotExist('foop.mpidx')
