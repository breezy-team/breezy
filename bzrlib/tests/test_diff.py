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

import os
from cStringIO import StringIO
import errno
import subprocess
from tempfile import TemporaryFile

from bzrlib.diff import internal_diff, external_diff, show_diff_trees
from bzrlib.errors import BinaryFile, NoDiff
import bzrlib.patiencediff
from bzrlib.tests import (TestCase, TestCaseWithTransport,
                          TestCaseInTempDir, TestSkipped)


def udiff_lines(old, new, allow_binary=False):
    output = StringIO()
    internal_diff('old', old, 'new', new, output, allow_binary)
    output.seek(0, 0)
    return output.readlines()


def external_udiff_lines(old, new, use_stringio=False):
    if use_stringio:
        # StringIO has no fileno, so it tests a different codepath
        output = StringIO()
    else:
        output = TemporaryFile()
    try:
        external_diff('old', old, 'new', new, output, diff_opts=['-u'])
    except NoDiff:
        raise TestSkipped('external "diff" not present to test')
    output.seek(0, 0)
    lines = output.readlines()
    output.close()
    return lines


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

    def test_external_diff(self):
        lines = external_udiff_lines(['boo\n'], ['goo\n'])
        self.check_patch(lines)
        self.assertEqual('\n', lines[-1])

    def test_external_diff_no_fileno(self):
        # Make sure that we can handle not having a fileno, even
        # if the diff is large
        lines = external_udiff_lines(['boo\n']*10000,
                                     ['goo\n']*10000,
                                     use_stringio=True)
        self.check_patch(lines)

    def test_external_diff_binary_lang_c(self):
        orig_lang = os.environ.get('LANG')
        try:
            os.environ['LANG'] = 'C'
            lines = external_udiff_lines(['\x00foobar\n'], ['foo\x00bar\n'])
            self.assertEqual(['Binary files old and new differ\n', '\n'], lines)
        finally:
            if orig_lang is None:
                del os.environ['LANG']
            else:
                os.environ['LANG'] = orig_lang

    def test_no_external_diff(self):
        """Check that NoDiff is raised when diff is not available"""
        # Use os.environ['PATH'] to make sure no 'diff' command is available
        orig_path = os.environ['PATH']
        try:
            os.environ['PATH'] = ''
            self.assertRaises(NoDiff, external_diff,
                              'old', ['boo\n'], 'new', ['goo\n'],
                              StringIO(), diff_opts=['-u'])
        finally:
            os.environ['PATH'] = orig_path
        
    def test_internal_diff_default(self):
        # Default internal diff encoding is utf8
        output = StringIO()
        internal_diff(u'old_\xb5', ['old_text\n'],
                    u'new_\xe5', ['new_text\n'], output)
        lines = output.getvalue().splitlines(True)
        self.check_patch(lines)
        self.assertEquals(['--- old_\xc2\xb5\n',
                           '+++ new_\xc3\xa5\n',
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
        self.assertEquals(['--- old_\xc2\xb5\n',
                           '+++ new_\xc3\xa5\n',
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
        self.assertEquals(['--- old_\xb5\n',
                           '+++ new_\xe5\n',
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


class TestDiffFiles(TestCaseInTempDir):

    def test_external_diff_binary(self):
        """The output when using external diff should use diff's i18n error"""
        # Make sure external_diff doesn't fail in the current LANG
        lines = external_udiff_lines(['\x00foobar\n'], ['foo\x00bar\n'])

        cmd = ['diff', '-u', 'old', 'new']
        open('old', 'wb').write('\x00foobar\n')
        open('new', 'wb').write('foo\x00bar\n')
        pipe = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                     stdin=subprocess.PIPE)
        out, err = pipe.communicate()
        # Diff returns '2' on Binary files.
        self.assertEqual(2, pipe.returncode)
        # We should output whatever diff tells us, plus a trailing newline
        self.assertEqual(out.splitlines(True) + ['\n'], lines)


class TestDiffDates(TestCaseWithTransport):

    def setUp(self):
        super(TestDiffDates, self).setUp()
        self.wt = self.make_branch_and_tree('.')
        self.b = self.wt.branch
        self.build_tree_contents([
            ('file1', 'file1 contents at rev 1\n'),
            ('file2', 'file2 contents at rev 1\n')
            ])
        self.wt.add(['file1', 'file2'])
        self.wt.commit(
            message='Revision 1',
            timestamp=1143849600, # 2006-04-01 00:00:00 UTC
            timezone=0,
            rev_id='rev-1')
        self.build_tree_contents([('file1', 'file1 contents at rev 2\n')])
        self.wt.commit(
            message='Revision 2',
            timestamp=1143936000, # 2006-04-02 00:00:00 UTC
            timezone=28800,
            rev_id='rev-2')
        self.build_tree_contents([('file2', 'file2 contents at rev 3\n')])
        self.wt.commit(
            message='Revision 3',
            timestamp=1144022400, # 2006-04-03 00:00:00 UTC
            timezone=-3600,
            rev_id='rev-3')
        self.wt.remove(['file2'])
        self.wt.commit(
            message='Revision 4',
            timestamp=1144108800, # 2006-04-04 00:00:00 UTC
            timezone=0,
            rev_id='rev-4')
        self.build_tree_contents([
            ('file1', 'file1 contents in working tree\n')
            ])
        # set the date stamps for files in the working tree to known values
        os.utime('file1', (1144195200, 1144195200)) # 2006-04-05 00:00:00 UTC

    def get_diff(self, tree1, tree2, specific_files=None, working_tree=None):
        output = StringIO()
        if working_tree is not None:
            extra_trees = (working_tree,)
        else:
            extra_trees = ()
        show_diff_trees(tree1, tree2, output, specific_files=specific_files,
                        extra_trees=extra_trees, old_label='old/', 
                        new_label='new/')
        return output.getvalue()

    def test_diff_rev_tree_working_tree(self):
        output = self.get_diff(self.wt.basis_tree(), self.wt)
        # note that the date for old/file1 is from rev 2 rather than from
        # the basis revision (rev 4)
        self.assertEqualDiff(output, '''\
=== modified file 'file1'
--- old/file1\t2006-04-02 00:00:00 +0000
+++ new/file1\t2006-04-05 00:00:00 +0000
@@ -1,1 +1,1 @@
-file1 contents at rev 2
+file1 contents in working tree

''')

    def test_diff_rev_tree_rev_tree(self):
        tree1 = self.b.repository.revision_tree('rev-2')
        tree2 = self.b.repository.revision_tree('rev-3')
        output = self.get_diff(tree1, tree2)
        self.assertEqualDiff(output, '''\
=== modified file 'file2'
--- old/file2\t2006-04-01 00:00:00 +0000
+++ new/file2\t2006-04-03 00:00:00 +0000
@@ -1,1 +1,1 @@
-file2 contents at rev 1
+file2 contents at rev 3

''')
        
    def test_diff_add_files(self):
        tree1 = self.b.repository.revision_tree(None)
        tree2 = self.b.repository.revision_tree('rev-1')
        output = self.get_diff(tree1, tree2)
        # the files have the epoch time stamp for the tree in which
        # they don't exist.
        self.assertEqualDiff(output, '''\
=== added file 'file1'
--- old/file1\t1970-01-01 00:00:00 +0000
+++ new/file1\t2006-04-01 00:00:00 +0000
@@ -0,0 +1,1 @@
+file1 contents at rev 1

=== added file 'file2'
--- old/file2\t1970-01-01 00:00:00 +0000
+++ new/file2\t2006-04-01 00:00:00 +0000
@@ -0,0 +1,1 @@
+file2 contents at rev 1

''')

    def test_diff_remove_files(self):
        tree1 = self.b.repository.revision_tree('rev-3')
        tree2 = self.b.repository.revision_tree('rev-4')
        output = self.get_diff(tree1, tree2)
        # the file has the epoch time stamp for the tree in which
        # it doesn't exist.
        self.assertEqualDiff(output, '''\
=== removed file 'file2'
--- old/file2\t2006-04-03 00:00:00 +0000
+++ new/file2\t1970-01-01 00:00:00 +0000
@@ -1,1 +0,0 @@
-file2 contents at rev 3

''')

    def test_show_diff_specified(self):
        """A working tree filename can be used to identify a file"""
        self.wt.rename_one('file1', 'file1b')
        old_tree = self.b.repository.revision_tree('rev-1')
        new_tree = self.b.repository.revision_tree('rev-4')
        out = self.get_diff(old_tree, new_tree, specific_files=['file1b'], 
                            working_tree=self.wt)
        self.assertContainsRe(out, 'file1\t')

    def test_recursive_diff(self):
        """Children of directories are matched"""
        os.mkdir('dir1')
        os.mkdir('dir2')
        self.wt.add(['dir1', 'dir2'])
        self.wt.rename_one('file1', 'dir1/file1')
        old_tree = self.b.repository.revision_tree('rev-1')
        new_tree = self.b.repository.revision_tree('rev-4')
        out = self.get_diff(old_tree, new_tree, specific_files=['dir1'], 
                            working_tree=self.wt)
        self.assertContainsRe(out, 'file1\t')
        out = self.get_diff(old_tree, new_tree, specific_files=['dir2'], 
                            working_tree=self.wt)
        self.assertNotContainsRe(out, 'file1\t')


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
