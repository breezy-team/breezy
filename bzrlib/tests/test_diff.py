import os
from cStringIO import StringIO

from bzrlib.diff import internal_diff, show_diff_trees
from bzrlib.errors import BinaryFile
from bzrlib.tests import TestCase, TestCaseWithTransport


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

    def get_diff(self, tree1, tree2):
        output = StringIO()
        show_diff_trees(tree1, tree2, output,
                        old_label='old/', new_label='new/')
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
