# Copyright (C) 2005-2011, 2016 Canonical Ltd
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


from .. import (
    merge3,
    tests,
    )
from ..errors import BinaryFile
from ..sixish import (
    BytesIO,
    int2byte,
    )


def split_lines(t):
    return BytesIO(t).readlines()


############################################################
# test case data from the gnu diffutils manual
# common base
TZU = split_lines(b"""     The Nameless is the origin of Heaven and Earth;
     The named is the mother of all things.

     Therefore let there always be non-being,
       so we may see their subtlety,
     And let there always be being,
       so we may see their outcome.
     The two are the same,
     But after they are produced,
       they have different names.
     They both may be called deep and profound.
     Deeper and more profound,
     The door of all subtleties!
""")

LAO = split_lines(b"""     The Way that can be told of is not the eternal Way;
     The name that can be named is not the eternal name.
     The Nameless is the origin of Heaven and Earth;
     The Named is the mother of all things.
     Therefore let there always be non-being,
       so we may see their subtlety,
     And let there always be being,
       so we may see their outcome.
     The two are the same,
     But after they are produced,
       they have different names.
""")


TAO = split_lines(b"""     The Way that can be told of is not the eternal Way;
     The name that can be named is not the eternal name.
     The Nameless is the origin of Heaven and Earth;
     The named is the mother of all things.

     Therefore let there always be non-being,
       so we may see their subtlety,
     And let there always be being,
       so we may see their result.
     The two are the same,
     But after they are produced,
       they have different names.

       -- The Way of Lao-Tzu, tr. Wing-tsit Chan

""")

MERGED_RESULT = split_lines(b"""     The Way that can be told of is not the eternal Way;
     The name that can be named is not the eternal name.
     The Nameless is the origin of Heaven and Earth;
     The Named is the mother of all things.
     Therefore let there always be non-being,
       so we may see their subtlety,
     And let there always be being,
       so we may see their result.
     The two are the same,
     But after they are produced,
       they have different names.
<<<<<<< LAO
=======

       -- The Way of Lao-Tzu, tr. Wing-tsit Chan

>>>>>>> TAO
""")


class TestMerge3(tests.TestCase):

    def test_no_changes(self):
        """No conflicts because nothing changed"""
        m3 = merge3.Merge3([b'aaa', b'bbb'],
                           [b'aaa', b'bbb'],
                           [b'aaa', b'bbb'])

        self.assertEqual(m3.find_unconflicted(),
                         [(0, 2)])

        self.assertEqual(list(m3.find_sync_regions()),
                         [(0, 2,
                           0, 2,
                           0, 2),
                          (2, 2, 2, 2, 2, 2)])

        self.assertEqual(list(m3.merge_regions()),
                         [('unchanged', 0, 2)])

        self.assertEqual(list(m3.merge_groups()),
                         [('unchanged', [b'aaa', b'bbb'])])

    def test_front_insert(self):
        m3 = merge3.Merge3([b'zz'],
                           [b'aaa', b'bbb', b'zz'],
                           [b'zz'])

        # todo: should use a sentinal at end as from get_matching_blocks
        # to match without zz
        self.assertEqual(list(m3.find_sync_regions()),
                         [(0, 1, 2, 3, 0, 1),
                          (1, 1, 3, 3, 1, 1), ])

        self.assertEqual(list(m3.merge_regions()),
                         [('a', 0, 2),
                          ('unchanged', 0, 1)])

        self.assertEqual(list(m3.merge_groups()),
                         [('a', [b'aaa', b'bbb']),
                          ('unchanged', [b'zz'])])

    def test_null_insert(self):
        m3 = merge3.Merge3([],
                           [b'aaa', b'bbb'],
                           [])
        # todo: should use a sentinal at end as from get_matching_blocks
        # to match without zz
        self.assertEqual(list(m3.find_sync_regions()),
                         [(0, 0, 2, 2, 0, 0)])

        self.assertEqual(list(m3.merge_regions()),
                         [('a', 0, 2)])

        self.assertEqual(list(m3.merge_lines()),
                         [b'aaa', b'bbb'])

    def test_no_conflicts(self):
        """No conflicts because only one side changed"""
        m3 = merge3.Merge3([b'aaa', b'bbb'],
                           [b'aaa', b'111', b'bbb'],
                           [b'aaa', b'bbb'])

        self.assertEqual(m3.find_unconflicted(),
                         [(0, 1), (1, 2)])

        self.assertEqual(list(m3.find_sync_regions()),
                         [(0, 1, 0, 1, 0, 1),
                          (1, 2, 2, 3, 1, 2),
                          (2, 2, 3, 3, 2, 2), ])

        self.assertEqual(list(m3.merge_regions()),
                         [('unchanged', 0, 1),
                          ('a', 1, 2),
                          ('unchanged', 1, 2), ])

    def test_append_a(self):
        m3 = merge3.Merge3([b'aaa\n', b'bbb\n'],
                           [b'aaa\n', b'bbb\n', b'222\n'],
                           [b'aaa\n', b'bbb\n'])

        self.assertEqual(b''.join(m3.merge_lines()),
                         b'aaa\nbbb\n222\n')

    def test_append_b(self):
        m3 = merge3.Merge3([b'aaa\n', b'bbb\n'],
                           [b'aaa\n', b'bbb\n'],
                           [b'aaa\n', b'bbb\n', b'222\n'])

        self.assertEqual(b''.join(m3.merge_lines()),
                         b'aaa\nbbb\n222\n')

    def test_append_agreement(self):
        m3 = merge3.Merge3([b'aaa\n', b'bbb\n'],
                           [b'aaa\n', b'bbb\n', b'222\n'],
                           [b'aaa\n', b'bbb\n', b'222\n'])

        self.assertEqual(b''.join(m3.merge_lines()),
                         b'aaa\nbbb\n222\n')

    def test_append_clash(self):
        m3 = merge3.Merge3([b'aaa\n', b'bbb\n'],
                           [b'aaa\n', b'bbb\n', b'222\n'],
                           [b'aaa\n', b'bbb\n', b'333\n'])

        ml = m3.merge_lines(name_a=b'a',
                            name_b=b'b',
                            start_marker=b'<<',
                            mid_marker=b'--',
                            end_marker=b'>>')
        self.assertEqual(b''.join(ml),
                         b'''\
aaa
bbb
<< a
222
--
333
>> b
''')

    def test_insert_agreement(self):
        m3 = merge3.Merge3([b'aaa\n', b'bbb\n'],
                           [b'aaa\n', b'222\n', b'bbb\n'],
                           [b'aaa\n', b'222\n', b'bbb\n'])

        ml = m3.merge_lines(name_a=b'a',
                            name_b=b'b',
                            start_marker=b'<<',
                            mid_marker=b'--',
                            end_marker=b'>>')
        self.assertEqual(b''.join(ml), b'aaa\n222\nbbb\n')

    def test_insert_clash(self):
        """Both try to insert lines in the same place."""
        m3 = merge3.Merge3([b'aaa\n', b'bbb\n'],
                           [b'aaa\n', b'111\n', b'bbb\n'],
                           [b'aaa\n', b'222\n', b'bbb\n'])

        self.assertEqual(m3.find_unconflicted(),
                         [(0, 1), (1, 2)])

        self.assertEqual(list(m3.find_sync_regions()),
                         [(0, 1, 0, 1, 0, 1),
                          (1, 2, 2, 3, 2, 3),
                          (2, 2, 3, 3, 3, 3), ])

        self.assertEqual(list(m3.merge_regions()),
                         [('unchanged', 0, 1),
                          ('conflict', 1, 1, 1, 2, 1, 2),
                          ('unchanged', 1, 2)])

        self.assertEqual(list(m3.merge_groups()),
                         [('unchanged', [b'aaa\n']),
                          ('conflict', [], [b'111\n'], [b'222\n']),
                          ('unchanged', [b'bbb\n']),
                          ])

        ml = m3.merge_lines(name_a=b'a',
                            name_b=b'b',
                            start_marker=b'<<',
                            mid_marker=b'--',
                            end_marker=b'>>')
        self.assertEqual(b''.join(ml),
                         b'''aaa
<< a
111
--
222
>> b
bbb
''')

    def test_replace_clash(self):
        """Both try to insert lines in the same place."""
        m3 = merge3.Merge3([b'aaa', b'000', b'bbb'],
                           [b'aaa', b'111', b'bbb'],
                           [b'aaa', b'222', b'bbb'])

        self.assertEqual(m3.find_unconflicted(),
                         [(0, 1), (2, 3)])

        self.assertEqual(list(m3.find_sync_regions()),
                         [(0, 1, 0, 1, 0, 1),
                          (2, 3, 2, 3, 2, 3),
                          (3, 3, 3, 3, 3, 3), ])

    def test_replace_multi(self):
        """Replacement with regions of different size."""
        m3 = merge3.Merge3([b'aaa', b'000', b'000', b'bbb'],
                           [b'aaa', b'111', b'111', b'111', b'bbb'],
                           [b'aaa', b'222', b'222', b'222', b'222', b'bbb'])

        self.assertEqual(m3.find_unconflicted(),
                         [(0, 1), (3, 4)])

        self.assertEqual(list(m3.find_sync_regions()),
                         [(0, 1, 0, 1, 0, 1),
                          (3, 4, 4, 5, 5, 6),
                          (4, 4, 5, 5, 6, 6), ])

    def test_merge_poem(self):
        """Test case from diff3 manual"""
        m3 = merge3.Merge3(TZU, LAO, TAO)
        ml = list(m3.merge_lines(b'LAO', b'TAO'))
        self.log('merge result:')
        self.log(b''.join(ml))
        self.assertEqual(ml, MERGED_RESULT)

    def test_minimal_conflicts_common(self):
        """Reprocessing"""
        base_text = (b"a\n" * 20).splitlines(True)
        this_text = (b"a\n" * 10 + b"b\n" * 10).splitlines(True)
        other_text = (b"a\n" * 10 + b"c\n" + b"b\n" *
                      8 + b"c\n").splitlines(True)
        m3 = merge3.Merge3(base_text, other_text, this_text)
        m_lines = m3.merge_lines(b'OTHER', b'THIS', reprocess=True)
        merged_text = b"".join(list(m_lines))
        optimal_text = (b"a\n" * 10 + b"<<<<<<< OTHER\nc\n"
                        + 8 * b"b\n" + b"c\n=======\n"
                        + 10 * b"b\n" + b">>>>>>> THIS\n")
        self.assertEqualDiff(optimal_text, merged_text)

    def test_minimal_conflicts_unique(self):
        def add_newline(s):
            """Add a newline to each entry in the string"""
            return [(int2byte(x) + b'\n') for x in bytearray(s)]

        base_text = add_newline(b"abcdefghijklm")
        this_text = add_newline(b"abcdefghijklmNOPQRSTUVWXYZ")
        other_text = add_newline(b"abcdefghijklm1OPQRSTUVWXY2")
        m3 = merge3.Merge3(base_text, other_text, this_text)
        m_lines = m3.merge_lines(b'OTHER', b'THIS', reprocess=True)
        merged_text = b"".join(list(m_lines))
        optimal_text = b''.join(add_newline(b"abcdefghijklm")
                                + [b"<<<<<<< OTHER\n1\n=======\nN\n>>>>>>> THIS\n"]
                                + add_newline(b'OPQRSTUVWXY')
                                + [b"<<<<<<< OTHER\n2\n=======\nZ\n>>>>>>> THIS\n"]
                                )
        self.assertEqualDiff(optimal_text, merged_text)

    def test_minimal_conflicts_nonunique(self):
        def add_newline(s):
            """Add a newline to each entry in the string"""
            return [(int2byte(x) + b'\n') for x in bytearray(s)]

        base_text = add_newline(b"abacddefgghij")
        this_text = add_newline(b"abacddefgghijkalmontfprz")
        other_text = add_newline(b"abacddefgghijknlmontfprd")
        m3 = merge3.Merge3(base_text, other_text, this_text)
        m_lines = m3.merge_lines(b'OTHER', b'THIS', reprocess=True)
        merged_text = b"".join(list(m_lines))
        optimal_text = b''.join(add_newline(b"abacddefgghijk")
                                + [b"<<<<<<< OTHER\nn\n=======\na\n>>>>>>> THIS\n"]
                                + add_newline(b'lmontfpr')
                                + [b"<<<<<<< OTHER\nd\n=======\nz\n>>>>>>> THIS\n"]
                                )
        self.assertEqualDiff(optimal_text, merged_text)

    def test_reprocess_and_base(self):
        """Reprocessing and showing base breaks correctly"""
        base_text = (b"a\n" * 20).splitlines(True)
        this_text = (b"a\n" * 10 + b"b\n" * 10).splitlines(True)
        other_text = (b"a\n" * 10 + b"c\n" + b"b\n" *
                      8 + b"c\n").splitlines(True)
        m3 = merge3.Merge3(base_text, other_text, this_text)
        m_lines = m3.merge_lines(b'OTHER', b'THIS', reprocess=True,
                                 base_marker=b'|||||||')
        self.assertRaises(merge3.CantReprocessAndShowBase, list, m_lines)

    def test_binary(self):
        self.assertRaises(BinaryFile, merge3.Merge3, [b'\x00'], [b'a'], [b'b'])

    def test_dos_text(self):
        base_text = b'a\r\n'
        this_text = b'b\r\n'
        other_text = b'c\r\n'
        m3 = merge3.Merge3(base_text.splitlines(True),
                           other_text.splitlines(True),
                           this_text.splitlines(True))
        m_lines = m3.merge_lines(b'OTHER', b'THIS')
        self.assertEqual(b'<<<<<<< OTHER\r\nc\r\n=======\r\nb\r\n'
                         b'>>>>>>> THIS\r\n'.splitlines(True), list(m_lines))

    def test_mac_text(self):
        base_text = b'a\r'
        this_text = b'b\r'
        other_text = b'c\r'
        m3 = merge3.Merge3(base_text.splitlines(True),
                           other_text.splitlines(True),
                           this_text.splitlines(True))
        m_lines = m3.merge_lines(b'OTHER', b'THIS')
        self.assertEqual(b'<<<<<<< OTHER\rc\r=======\rb\r'
                         b'>>>>>>> THIS\r'.splitlines(True), list(m_lines))

    def test_merge3_cherrypick(self):
        base_text = b"a\nb\n"
        this_text = b"a\n"
        other_text = b"a\nb\nc\n"
        # When cherrypicking, lines in base are not part of the conflict
        m3 = merge3.Merge3(base_text.splitlines(True),
                           this_text.splitlines(True),
                           other_text.splitlines(True), is_cherrypick=True)
        m_lines = m3.merge_lines()
        self.assertEqualDiff(b'a\n<<<<<<<\n=======\nc\n>>>>>>>\n',
                             b''.join(m_lines))

        # This is not symmetric
        m3 = merge3.Merge3(base_text.splitlines(True),
                           other_text.splitlines(True),
                           this_text.splitlines(True), is_cherrypick=True)
        m_lines = m3.merge_lines()
        self.assertEqualDiff(b'a\n<<<<<<<\nb\nc\n=======\n>>>>>>>\n',
                             b''.join(m_lines))

    def test_merge3_cherrypick_w_mixed(self):
        base_text = b'a\nb\nc\nd\ne\n'
        this_text = b'a\nb\nq\n'
        other_text = b'a\nb\nc\nd\nf\ne\ng\n'
        # When cherrypicking, lines in base are not part of the conflict
        m3 = merge3.Merge3(base_text.splitlines(True),
                           this_text.splitlines(True),
                           other_text.splitlines(True), is_cherrypick=True)
        m_lines = m3.merge_lines()
        self.assertEqualDiff(b'a\n'
                             b'b\n'
                             b'<<<<<<<\n'
                             b'q\n'
                             b'=======\n'
                             b'f\n'
                             b'>>>>>>>\n'
                             b'<<<<<<<\n'
                             b'=======\n'
                             b'g\n'
                             b'>>>>>>>\n',
                             b''.join(m_lines))

    def test_allow_objects(self):
        """Objects other than strs may be used with Merge3 when
        allow_objects=True.

        merge_groups and merge_regions work with non-str input.  Methods that
        return lines like merge_lines fail.
        """
        base = [(x, x) for x in 'abcde']
        a = [(x, x) for x in 'abcdef']
        b = [(x, x) for x in 'Zabcde']
        m3 = merge3.Merge3(base, a, b, allow_objects=True)
        self.assertEqual(
            [('b', 0, 1),
             ('unchanged', 0, 5),
             ('a', 5, 6)],
            list(m3.merge_regions()))
        self.assertEqual(
            [('b', [('Z', 'Z')]),
             ('unchanged', [(x, x) for x in 'abcde']),
             ('a', [('f', 'f')])],
            list(m3.merge_groups()))
