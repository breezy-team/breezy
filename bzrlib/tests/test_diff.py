from bzrlib.tests import TestCase, TestCaseInTempDir
from bzrlib.diff import internal_diff
from cStringIO import StringIO
def udiff_lines(old, new):
    output = StringIO()
    internal_diff('old', old, 'new', new, output)
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


class TestCDVDiffLib(TestCase):

    def test_unique_lcs(self):
        from bzrlib.cdv.nofrillsprecisemerge import unique_lcs

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
        from bzrlib.cdv.nofrillsprecisemerge import recurse_matches

        def test_one(a, b, matches):
            test_matches = []
            recurse_matches(a, b, len(a), len(b), test_matches, 10)
            self.assertEquals(test_matches, matches)

        test_one(['a', None, 'b', None, 'c'], ['a', 'a', 'b', 'c', 'c'],
                 [(0, 0), (2, 2), (4, 4)])
        test_one(['a', 'c', 'b', 'a', 'c'], ['a', 'b', 'c'],
                 [(0, 0), (2, 1), (4, 2)])

        # recurse_matches doesn't match non-unique 
        # lines surrounded by bogus text.
        # The update has been done in cdvdifflib.SequenceMatcher instead

        # This is what it could be
        #test_one('aBccDe', 'abccde', [(0,0), (2,2), (3,3), (5,5)])

        # This is what it currently gives:
        test_one('aBccDe', 'abccde', [(0,0), (5,5)])

    def test_matching_blocks(self):
        from bzrlib.cdv.cdvdifflib import SequenceMatcher

        def chk_blocks(a, b, matching):
            # difflib always adds a signature of the total
            # length, with no matching entries at the end
            s = SequenceMatcher(None, a, b)
            blocks = s.get_matching_blocks()
            x = blocks.pop()
            self.assertEquals(x, (len(a), len(b), 0))
            self.assertEquals(matching, blocks)

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
                [ 'hello there\n'
                , 'world\n'
                , 'how are you today?\n'],
                [ 'hello there\n'
                , 'how are you today?\n'],
                [(0, 0, 1), (2, 1, 1)])

        chk_blocks('aBccDe', 'abccde', [(0,0,1), (2,2,2), (5,5,1)])

        chk_blocks('aBcdEcdFg', 'abcdecdfg', [(0,0,1), (2,2,2),
                                              (5,5,2), (8,8,1)])

        chk_blocks('abbabbXd', 'cabbabxd', [(0,1,5), (7,7,1)])
        chk_blocks('abbabbbb', 'cabbabbc', [(0,1,6)])
        chk_blocks('bbbbbbbb', 'cbbbbbbc', [(0,1,6)])

    def test_opcodes(self):
        from bzrlib.cdv.cdvdifflib import SequenceMatcher

        def chk_ops(a, b, codes):
            s = SequenceMatcher(None, a, b)
            self.assertEquals(codes, s.get_opcodes())

        chk_ops('', '', [])
        chk_ops([], [], [])
        chk_ops('abcd', 'abcd', [('equal',    0,4, 0,4)])
        chk_ops('abcd', 'abce', [ ('equal',   0,3, 0,3)
                                , ('replace', 3,4, 3,4)
                                ])
        chk_ops('eabc', 'abce', [ ('delete', 0,1, 0,0)
                                , ('equal',  1,4, 0,3)
                                , ('insert', 4,4, 3,4)
                                ])
        chk_ops('eabce', 'abce', [ ('delete', 0,1, 0,0)
                                 , ('equal',  1,5, 0,4)
                                 ])
        chk_ops('abcde', 'abXde', [ ('equal',   0,2, 0,2)
                                  , ('replace', 2,3, 2,3)
                                  , ('equal',   3,5, 3,5)
                                  ])
        chk_ops('abcde', 'abXYZde', [ ('equal',   0,2, 0,2)
                                    , ('replace', 2,3, 2,5)
                                    , ('equal',   3,5, 5,7)
                                    ])
        chk_ops('abde', 'abXYZde', [ ('equal',  0,2, 0,2)
                                   , ('insert', 2,2, 2,5)
                                   , ('equal',  2,4, 5,7)
                                   ])
        chk_ops('abcdefghijklmnop', 'abcdefxydefghijklmnop',
                [ ('equal',  0,6,  0,6)
                , ('insert', 6,6,  6,11)
                , ('equal',  6,16, 11,21)
                ])

        chk_ops(
                [ 'hello there\n'
                , 'world\n'
                , 'how are you today?\n'],
                [ 'hello there\n'
                , 'how are you today?\n'],
                [ ('equal',  0,1, 0,1)
                , ('delete', 1,2, 1,1)
                , ('equal',  2,3, 1,2)
                ])

        chk_ops('aBccDe', 'abccde', 
                [ ('equal',   0,1, 0,1)
                , ('replace', 1,2, 1,2)
                , ('equal',   2,4, 2,4)
                , ('replace', 4,5, 4,5)
                , ('equal',   5,6, 5,6)
                ])

        chk_ops('aBcdEcdFg', 'abcdecdfg', 
                [ ('equal',   0,1, 0,1)
                , ('replace', 1,2, 1,2)
                , ('equal',   2,4, 2,4)
                , ('replace', 4,5, 4,5)
                , ('equal',   5,7, 5,7)
                , ('replace', 7,8, 7,8)
                , ('equal',   8,9, 8,9)
                ])

    def test_cdv_unified_diff(self):
        from bzrlib.cdv.cdvdifflib import unified_diff
        from bzrlib.cdv.cdvdifflib import SequenceMatcher

        txt_a = [ 'hello there\n'
                , 'world\n'
                , 'how are you today?\n']
        txt_b = [ 'hello there\n'
                , 'how are you today?\n']

        self.assertEquals([ '---  \n'
                          , '+++  \n'
                          , '@@ -1,3 +1,2 @@\n'
                          , ' hello there\n'
                          , '-world\n'
                          , ' how are you today?\n'
                          ]
                          , list(unified_diff(txt_a, txt_b
                                        , sequencematcher=SequenceMatcher)))

        txt_a = map(lambda x: x+'\n', 'abcdefghijklmnop')
        txt_b = map(lambda x: x+'\n', 'abcdefxydefghijklmnop')

        # This is the result with LongestCommonSubstring matching
        self.assertEquals([ '---  \n'
                          , '+++  \n'
                          , '@@ -1,6 +1,11 @@\n'
                          , ' a\n'
                          , ' b\n'
                          , ' c\n'
                          , '+d\n'
                          , '+e\n'
                          , '+f\n'
                          , '+x\n'
                          , '+y\n'
                          , ' d\n'
                          , ' e\n'
                          , ' f\n']
                          , list(unified_diff(txt_a, txt_b)))

        # And the cdv diff
        self.assertEquals([ '---  \n'
                          , '+++  \n'
                          , '@@ -4,6 +4,11 @@\n'
                          , ' d\n'
                          , ' e\n'
                          , ' f\n'
                          , '+x\n'
                          , '+y\n'
                          , '+d\n'
                          , '+e\n'
                          , '+f\n'
                          , ' g\n'
                          , ' h\n'
                          , ' i\n'
                          ]
                          , list(unified_diff(txt_a, txt_b
                                        , sequencematcher=SequenceMatcher)))

class TestCDVDiffLibFiles(TestCaseInTempDir):

    def test_cdv_unified_diff_files(self):
        from bzrlib.cdv.cdvdifflib import unified_diff_files
        from bzrlib.cdv.cdvdifflib import SequenceMatcher

        txt_a = [ 'hello there\n'
                , 'world\n'
                , 'how are you today?\n']
        txt_b = [ 'hello there\n'
                , 'how are you today?\n']
        open('a1', 'wb').writelines(txt_a)
        open('b1', 'wb').writelines(txt_b)

        self.assertEquals([ '--- a1 \n'
                          , '+++ b1 \n'
                          , '@@ -1,3 +1,2 @@\n'
                          , ' hello there\n'
                          , '-world\n'
                          , ' how are you today?\n'
                          ]
                          , list(unified_diff_files('a1', 'b1'
                                        , sequencematcher=SequenceMatcher)))

        txt_a = map(lambda x: x+'\n', 'abcdefghijklmnop')
        txt_b = map(lambda x: x+'\n', 'abcdefxydefghijklmnop')
        open('a2', 'wb').writelines(txt_a)
        open('b2', 'wb').writelines(txt_b)

        # This is the result with LongestCommonSubstring matching
        self.assertEquals([ '--- a2 \n'
                          , '+++ b2 \n'
                          , '@@ -1,6 +1,11 @@\n'
                          , ' a\n'
                          , ' b\n'
                          , ' c\n'
                          , '+d\n'
                          , '+e\n'
                          , '+f\n'
                          , '+x\n'
                          , '+y\n'
                          , ' d\n'
                          , ' e\n'
                          , ' f\n']
                          , list(unified_diff_files('a2', 'b2')))

        # And the cdv diff
        self.assertEquals([ '--- a2 \n'
                          , '+++ b2 \n'
                          , '@@ -4,6 +4,11 @@\n'
                          , ' d\n'
                          , ' e\n'
                          , ' f\n'
                          , '+x\n'
                          , '+y\n'
                          , '+d\n'
                          , '+e\n'
                          , '+f\n'
                          , ' g\n'
                          , ' h\n'
                          , ' i\n'
                          ]
                          , list(unified_diff_files('a2', 'b2'
                                        , sequencematcher=SequenceMatcher)))

