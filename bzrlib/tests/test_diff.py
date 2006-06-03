# Copyright (C) 2005, 2006 Canonical Development Ltd
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

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

from cStringIO import StringIO

from bzrlib.diff import internal_diff
from bzrlib.errors import BinaryFile
import bzrlib.patiencediff
from bzrlib.tests import TestCase, TestCaseInTempDir


def udiff_lines(old, new, allow_binary=False):
    output = StringIO()
    internal_diff('old', old, 'new', new, output, allow_binary)
    output.seek(0, 0)
    return output.readlines()


class TestDiff(TestCase):

    def test_add_nl(self):
        """diff generates a valid diff for patches that add a newline"""
        lines = udiff_lines(['boo'], ['boo\n'])
        self.check_patch(lines)
        self.assertEquals(lines[4], '\\ No newline at end of file\n')
            ## "expected no-nl, got %r" % lines[4]

    def test_add_nl_2(self):
        """diff generates a valid diff for patches that change last line and
        add a newline.
        """
        lines = udiff_lines(['boo'], ['goo\n'])
        self.check_patch(lines)
        self.assertEquals(lines[4], '\\ No newline at end of file\n')
            ## "expected no-nl, got %r" % lines[4]

    def test_remove_nl(self):
        """diff generates a valid diff for patches that change last line and
        add a newline.
        """
        lines = udiff_lines(['boo\n'], ['boo'])
        self.check_patch(lines)
        self.assertEquals(lines[5], '\\ No newline at end of file\n')
            ## "expected no-nl, got %r" % lines[5]

    def check_patch(self, lines):
        self.assert_(len(lines) > 1)
            ## "Not enough lines for a file header for patch:\n%s" % "".join(lines)
        self.assert_(lines[0].startswith ('---'))
            ## 'No orig line for patch:\n%s' % "".join(lines)
        self.assert_(lines[1].startswith ('+++'))
            ## 'No mod line for patch:\n%s' % "".join(lines)
        self.assert_(len(lines) > 2)
            ## "No hunks for patch:\n%s" % "".join(lines)
        self.assert_(lines[2].startswith('@@'))
            ## "No hunk header for patch:\n%s" % "".join(lines)
        self.assert_('@@' in lines[2][2:])
            ## "Unterminated hunk header for patch:\n%s" % "".join(lines)

    def test_binary_lines(self):
        self.assertRaises(BinaryFile, udiff_lines, [1023 * 'a' + '\x00'], [])
        self.assertRaises(BinaryFile, udiff_lines, [], [1023 * 'a' + '\x00'])
        udiff_lines([1023 * 'a' + '\x00'], [], allow_binary=True)
        udiff_lines([], [1023 * 'a' + '\x00'], allow_binary=True)

    def test_internal_diff_default(self):
        # Default internal diff encoding is utf8
        output = StringIO()
        internal_diff(u'old_\xb5', ['old_text\n'],
                    u'new_\xe5', ['new_text\n'], output)
        lines = output.getvalue().splitlines(True)
        self.check_patch(lines)
        self.assertEquals(['--- old_\xc2\xb5\t\n',
                           '+++ new_\xc3\xa5\t\n',
                           '@@ -1,1 +1,1 @@\n',
                           '-old_text\n',
                           '+new_text\n',
                           '\n',
                          ]
                          , lines)

    def test_internal_diff_utf8(self):
        output = StringIO()
        internal_diff(u'old_\xb5', ['old_text\n'],
                    u'new_\xe5', ['new_text\n'], output,
                    path_encoding='utf8')
        lines = output.getvalue().splitlines(True)
        self.check_patch(lines)
        self.assertEquals(['--- old_\xc2\xb5\t\n',
                           '+++ new_\xc3\xa5\t\n',
                           '@@ -1,1 +1,1 @@\n',
                           '-old_text\n',
                           '+new_text\n',
                           '\n',
                          ]
                          , lines)

    def test_internal_diff_iso_8859_1(self):
        output = StringIO()
        internal_diff(u'old_\xb5', ['old_text\n'],
                    u'new_\xe5', ['new_text\n'], output,
                    path_encoding='iso-8859-1')
        lines = output.getvalue().splitlines(True)
        self.check_patch(lines)
        self.assertEquals(['--- old_\xb5\t\n',
                           '+++ new_\xe5\t\n',
                           '@@ -1,1 +1,1 @@\n',
                           '-old_text\n',
                           '+new_text\n',
                           '\n',
                          ]
                          , lines)

    def test_internal_diff_returns_bytes(self):
        import StringIO
        output = StringIO.StringIO()
        internal_diff(u'old_\xb5', ['old_text\n'],
                    u'new_\xe5', ['new_text\n'], output)
        self.failUnless(isinstance(output.getvalue(), str),
            'internal_diff should return bytestrings')


class TestPatienceDiffLib(TestCase):

    def test_unique_lcs(self):
        unique_lcs = bzrlib.patiencediff.unique_lcs
        self.assertEquals(unique_lcs('', ''), [])
        self.assertEquals(unique_lcs('a', 'a'), [(0,0)])
        self.assertEquals(unique_lcs('a', 'b'), [])
        self.assertEquals(unique_lcs('ab', 'ab'), [(0,0), (1,1)])
        self.assertEquals(unique_lcs('abcde', 'cdeab'), [(2,0), (3,1), (4,2)])
        self.assertEquals(unique_lcs('cdeab', 'abcde'), [(0,2), (1,3), (2,4)])
        self.assertEquals(unique_lcs('abXde', 'abYde'), [(0,0), (1,1), 
                                                         (3,3), (4,4)])
        self.assertEquals(unique_lcs('acbac', 'abc'), [(2,1)])

    def test_recurse_matches(self):
        def test_one(a, b, matches):
            test_matches = []
            bzrlib.patiencediff.recurse_matches(a, b, 0, 0, len(a), len(b),
                test_matches, 10)
            self.assertEquals(test_matches, matches)

        test_one(['a', '', 'b', '', 'c'], ['a', 'a', 'b', 'c', 'c'],
                 [(0, 0), (2, 2), (4, 4)])
        test_one(['a', 'c', 'b', 'a', 'c'], ['a', 'b', 'c'],
                 [(0, 0), (2, 1), (4, 2)])

        # recurse_matches doesn't match non-unique 
        # lines surrounded by bogus text.
        # The update has been done in patiencediff.SequenceMatcher instead

        # This is what it could be
        #test_one('aBccDe', 'abccde', [(0,0), (2,2), (3,3), (5,5)])

        # This is what it currently gives:
        test_one('aBccDe', 'abccde', [(0,0), (5,5)])

    def test_matching_blocks(self):
        def chk_blocks(a, b, expected_blocks):
            # difflib always adds a signature of the total
            # length, with no matching entries at the end
            s = bzrlib.patiencediff.PatienceSequenceMatcher(None, a, b)
            blocks = s.get_matching_blocks()
            self.assertEquals((len(a), len(b), 0), blocks[-1])
            self.assertEquals(expected_blocks, blocks[:-1])

        # Some basic matching tests
        chk_blocks('', '', [])
        chk_blocks([], [], [])
        chk_blocks('abcd', 'abcd', [(0, 0, 4)])
        chk_blocks('abcd', 'abce', [(0, 0, 3)])
        chk_blocks('eabc', 'abce', [(1, 0, 3)])
        chk_blocks('eabce', 'abce', [(1, 0, 4)])
        chk_blocks('abcde', 'abXde', [(0, 0, 2), (3, 3, 2)])
        chk_blocks('abcde', 'abXYZde', [(0, 0, 2), (3, 5, 2)])
        chk_blocks('abde', 'abXYZde', [(0, 0, 2), (2, 5, 2)])
        # This may check too much, but it checks to see that 
        # a copied block stays attached to the previous section,
        # not the later one.
        # difflib would tend to grab the trailing longest match
        # which would make the diff not look right
        chk_blocks('abcdefghijklmnop', 'abcdefxydefghijklmnop',
                   [(0, 0, 6), (6, 11, 10)])

        # make sure it supports passing in lists
        chk_blocks(
                   ['hello there\n',
                    'world\n',
                    'how are you today?\n'],
                   ['hello there\n',
                    'how are you today?\n'],
                [(0, 0, 1), (2, 1, 1)])

        # non unique lines surrounded by non-matching lines
        # won't be found
        chk_blocks('aBccDe', 'abccde', [(0,0,1), (5,5,1)])

        # But they only need to be locally unique
        chk_blocks('aBcDec', 'abcdec', [(0,0,1), (2,2,1), (4,4,2)])

        # non unique blocks won't be matched
        chk_blocks('aBcdEcdFg', 'abcdecdfg', [(0,0,1), (8,8,1)])

        # but locally unique ones will
        chk_blocks('aBcdEeXcdFg', 'abcdecdfg', [(0,0,1), (2,2,2),
                                              (5,4,1), (7,5,2), (10,8,1)])

        chk_blocks('abbabbXd', 'cabbabxd', [(7,7,1)])
        chk_blocks('abbabbbb', 'cabbabbc', [])
        chk_blocks('bbbbbbbb', 'cbbbbbbc', [])

    def test_opcodes(self):
        def chk_ops(a, b, expected_codes):
            s = bzrlib.patiencediff.PatienceSequenceMatcher(None, a, b)
            self.assertEquals(expected_codes, s.get_opcodes())

        chk_ops('', '', [])
        chk_ops([], [], [])
        chk_ops('abcd', 'abcd', [('equal',    0,4, 0,4)])
        chk_ops('abcd', 'abce', [('equal',   0,3, 0,3),
                                 ('replace', 3,4, 3,4)
                                ])
        chk_ops('eabc', 'abce', [('delete', 0,1, 0,0),
                                 ('equal',  1,4, 0,3),
                                 ('insert', 4,4, 3,4)
                                ])
        chk_ops('eabce', 'abce', [('delete', 0,1, 0,0),
                                  ('equal',  1,5, 0,4)
                                 ])
        chk_ops('abcde', 'abXde', [('equal',   0,2, 0,2),
                                   ('replace', 2,3, 2,3),
                                   ('equal',   3,5, 3,5)
                                  ])
        chk_ops('abcde', 'abXYZde', [('equal',   0,2, 0,2),
                                     ('replace', 2,3, 2,5),
                                     ('equal',   3,5, 5,7)
                                    ])
        chk_ops('abde', 'abXYZde', [('equal',  0,2, 0,2),
                                    ('insert', 2,2, 2,5),
                                    ('equal',  2,4, 5,7)
                                   ])
        chk_ops('abcdefghijklmnop', 'abcdefxydefghijklmnop',
                [('equal',  0,6,  0,6),
                 ('insert', 6,6,  6,11),
                 ('equal',  6,16, 11,21)
                ])
        chk_ops(
                [ 'hello there\n'
                , 'world\n'
                , 'how are you today?\n'],
                [ 'hello there\n'
                , 'how are you today?\n'],
                [('equal',  0,1, 0,1),
                 ('delete', 1,2, 1,1),
                 ('equal',  2,3, 1,2),
                ])
        chk_ops('aBccDe', 'abccde', 
                [('equal',   0,1, 0,1),
                 ('replace', 1,5, 1,5),
                 ('equal',   5,6, 5,6),
                ])
        chk_ops('aBcDec', 'abcdec', 
                [('equal',   0,1, 0,1),
                 ('replace', 1,2, 1,2),
                 ('equal',   2,3, 2,3),
                 ('replace', 3,4, 3,4),
                 ('equal',   4,6, 4,6),
                ])
        chk_ops('aBcdEcdFg', 'abcdecdfg', 
                [('equal',   0,1, 0,1),
                 ('replace', 1,8, 1,8),
                 ('equal',   8,9, 8,9)
                ])
        chk_ops('aBcdEeXcdFg', 'abcdecdfg', 
                [('equal',   0,1, 0,1),
                 ('replace', 1,2, 1,2),
                 ('equal',   2,4, 2,4),
                 ('delete', 4,5, 4,4),
                 ('equal',   5,6, 4,5),
                 ('delete', 6,7, 5,5),
                 ('equal',   7,9, 5,7),
                 ('replace', 9,10, 7,8),
                 ('equal',   10,11, 8,9)
                ])

    def test_multiple_ranges(self):
        # There was an earlier bug where we used a bad set of ranges,
        # this triggers that specific bug, to make sure it doesn't regress
        def chk_blocks(a, b, expected_blocks):
            # difflib always adds a signature of the total
            # length, with no matching entries at the end
            s = bzrlib.patiencediff.PatienceSequenceMatcher(None, a, b)
            blocks = s.get_matching_blocks()
            x = blocks.pop()
            self.assertEquals(x, (len(a), len(b), 0))
            self.assertEquals(expected_blocks, blocks)

        chk_blocks('abcdefghijklmnop'
                 , 'abcXghiYZQRSTUVWXYZijklmnop'
                 , [(0, 0, 3), (6, 4, 3), (9, 20, 7)])

        chk_blocks('ABCd efghIjk  L'
                 , 'AxyzBCn mo pqrstuvwI1 2  L'
                 , [(0,0,1), (1, 4, 2), (9, 19, 1), (12, 23, 3)])

        # These are rot13 code snippets.
        chk_blocks('''\
    trg nqqrq jura lbh nqq n svyr va gur qverpgbel.
    """
    gnxrf_netf = ['svyr*']
    gnxrf_bcgvbaf = ['ab-erphefr']
  
    qrs eha(frys, svyr_yvfg, ab_erphefr=Snyfr):
        sebz omeyvo.nqq vzcbeg fzneg_nqq, nqq_ercbegre_cevag, nqq_ercbegre_ahyy
        vs vf_dhvrg():
            ercbegre = nqq_ercbegre_ahyy
        ryfr:
            ercbegre = nqq_ercbegre_cevag
        fzneg_nqq(svyr_yvfg, abg ab_erphefr, ercbegre)


pynff pzq_zxqve(Pbzznaq):
'''.splitlines(True), '''\
    trg nqqrq jura lbh nqq n svyr va gur qverpgbel.

    --qel-eha jvyy fubj juvpu svyrf jbhyq or nqqrq, ohg abg npghnyyl 
    nqq gurz.
    """
    gnxrf_netf = ['svyr*']
    gnxrf_bcgvbaf = ['ab-erphefr', 'qel-eha']

    qrs eha(frys, svyr_yvfg, ab_erphefr=Snyfr, qel_eha=Snyfr):
        vzcbeg omeyvo.nqq

        vs qel_eha:
            vs vf_dhvrg():
                # Guvf vf cbvagyrff, ohg V'q engure abg envfr na reebe
                npgvba = omeyvo.nqq.nqq_npgvba_ahyy
            ryfr:
  npgvba = omeyvo.nqq.nqq_npgvba_cevag
        ryvs vf_dhvrg():
            npgvba = omeyvo.nqq.nqq_npgvba_nqq
        ryfr:
       npgvba = omeyvo.nqq.nqq_npgvba_nqq_naq_cevag

        omeyvo.nqq.fzneg_nqq(svyr_yvfg, abg ab_erphefr, npgvba)


pynff pzq_zxqve(Pbzznaq):
'''.splitlines(True)
, [(0,0,1), (1, 4, 2), (9, 19, 1), (12, 23, 3)])

    def test_patience_unified_diff(self):
        txt_a = ['hello there\n',
                 'world\n',
                 'how are you today?\n']
        txt_b = ['hello there\n',
                 'how are you today?\n']
        unified_diff = bzrlib.patiencediff.unified_diff
        psm = bzrlib.patiencediff.PatienceSequenceMatcher
        self.assertEquals([ '---  \n',
                           '+++  \n',
                           '@@ -1,3 +1,2 @@\n',
                           ' hello there\n',
                           '-world\n',
                           ' how are you today?\n'
                          ]
                          , list(unified_diff(txt_a, txt_b,
                                 sequencematcher=psm)))
        txt_a = map(lambda x: x+'\n', 'abcdefghijklmnop')
        txt_b = map(lambda x: x+'\n', 'abcdefxydefghijklmnop')
        # This is the result with LongestCommonSubstring matching
        self.assertEquals(['---  \n',
                           '+++  \n',
                           '@@ -1,6 +1,11 @@\n',
                           ' a\n',
                           ' b\n',
                           ' c\n',
                           '+d\n',
                           '+e\n',
                           '+f\n',
                           '+x\n',
                           '+y\n',
                           ' d\n',
                           ' e\n',
                           ' f\n']
                          , list(unified_diff(txt_a, txt_b)))
        # And the patience diff
        self.assertEquals(['---  \n',
                           '+++  \n',
                           '@@ -4,6 +4,11 @@\n',
                           ' d\n',
                           ' e\n',
                           ' f\n',
                           '+x\n',
                           '+y\n',
                           '+d\n',
                           '+e\n',
                           '+f\n',
                           ' g\n',
                           ' h\n',
                           ' i\n',
                          ]
                          , list(unified_diff(txt_a, txt_b,
                                 sequencematcher=psm)))


class TestPatienceDiffLibFiles(TestCaseInTempDir):

    def test_patience_unified_diff_files(self):
        txt_a = ['hello there\n',
                 'world\n',
                 'how are you today?\n']
        txt_b = ['hello there\n',
                 'how are you today?\n']
        open('a1', 'wb').writelines(txt_a)
        open('b1', 'wb').writelines(txt_b)

        unified_diff_files = bzrlib.patiencediff.unified_diff_files
        psm = bzrlib.patiencediff.PatienceSequenceMatcher
        self.assertEquals(['--- a1 \n',
                           '+++ b1 \n',
                           '@@ -1,3 +1,2 @@\n',
                           ' hello there\n',
                           '-world\n',
                           ' how are you today?\n',
                          ]
                          , list(unified_diff_files('a1', 'b1',
                                 sequencematcher=psm)))

        txt_a = map(lambda x: x+'\n', 'abcdefghijklmnop')
        txt_b = map(lambda x: x+'\n', 'abcdefxydefghijklmnop')
        open('a2', 'wb').writelines(txt_a)
        open('b2', 'wb').writelines(txt_b)

        # This is the result with LongestCommonSubstring matching
        self.assertEquals(['--- a2 \n',
                           '+++ b2 \n',
                           '@@ -1,6 +1,11 @@\n',
                           ' a\n',
                           ' b\n',
                           ' c\n',
                           '+d\n',
                           '+e\n',
                           '+f\n',
                           '+x\n',
                           '+y\n',
                           ' d\n',
                           ' e\n',
                           ' f\n']
                          , list(unified_diff_files('a2', 'b2')))

        # And the patience diff
        self.assertEquals(['--- a2 \n',
                           '+++ b2 \n',
                           '@@ -4,6 +4,11 @@\n',
                           ' d\n',
                           ' e\n',
                           ' f\n',
                           '+x\n',
                           '+y\n',
                           '+d\n',
                           '+e\n',
                           '+f\n',
                           ' g\n',
                           ' h\n',
                           ' i\n',
                          ]
                          , list(unified_diff_files('a2', 'b2',
                                 sequencematcher=psm)))
