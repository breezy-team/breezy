from bzrlib.selftest import TestCase
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

