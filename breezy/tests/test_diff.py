# Copyright (C) 2005-2012, 2014, 2016, 2017 Canonical Ltd
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

import os
import re
import subprocess
import sys
import tempfile

from .. import (
    diff,
    errors,
    osutils,
    patiencediff,
    _patiencediff_py,
    revision as _mod_revision,
    revisionspec,
    revisiontree,
    tests,
    transform,
    )
from ..sixish import (
    BytesIO,
    unichr,
    )
from ..tests import (
    features,
    EncodingAdapter,
    )
from ..tests.scenarios import load_tests_apply_scenarios


load_tests = load_tests_apply_scenarios


def subst_dates(string):
    """Replace date strings with constant values."""
    return re.sub(br'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} [-\+]\d{4}',
                  b'YYYY-MM-DD HH:MM:SS +ZZZZ', string)


def udiff_lines(old, new, allow_binary=False):
    output = BytesIO()
    diff.internal_diff('old', old, 'new', new, output, allow_binary)
    output.seek(0, 0)
    return output.readlines()


def external_udiff_lines(old, new, use_stringio=False):
    if use_stringio:
        # BytesIO has no fileno, so it tests a different codepath
        output = BytesIO()
    else:
        output = tempfile.TemporaryFile()
    try:
        diff.external_diff('old', old, 'new', new, output, diff_opts=['-u'])
    except errors.NoDiff:
        raise tests.TestSkipped('external "diff" not present to test')
    output.seek(0, 0)
    lines = output.readlines()
    output.close()
    return lines


class StubO(object):
    """Simple file-like object that allows writes with any type and records."""

    def __init__(self):
        self.write_record = []

    def write(self, data):
        self.write_record.append(data)

    def check_types(self, testcase, expected_type):
        testcase.assertFalse(
            any(not isinstance(o, expected_type) for o in self.write_record),
            "Not all writes of type %s: %r" % (
                expected_type.__name__, self.write_record))


class TestDiffOptions(tests.TestCase):

    def test_unified_added(self):
        """Check for default style '-u' only if no other style specified
        in 'diff-options'.
        """
        # Verify that style defaults to unified, id est '-u' appended
        # to option list, in the absence of an alternative style.
        self.assertEqual(['-a', '-u'], diff.default_style_unified(['-a']))


class TestDiffOptionsScenarios(tests.TestCase):

    scenarios = [(s, dict(style=s)) for s in diff.style_option_list]
    style = None  # Set by load_tests_apply_scenarios from scenarios

    def test_unified_not_added(self):
        # Verify that for all valid style options, '-u' is not
        # appended to option list.
        ret_opts = diff.default_style_unified(diff_opts=["%s" % (self.style,)])
        self.assertEqual(["%s" % (self.style,)], ret_opts)


class TestDiff(tests.TestCase):

    def test_add_nl(self):
        """diff generates a valid diff for patches that add a newline"""
        lines = udiff_lines([b'boo'], [b'boo\n'])
        self.check_patch(lines)
        self.assertEqual(lines[4], b'\\ No newline at end of file\n')
        ## "expected no-nl, got %r" % lines[4]

    def test_add_nl_2(self):
        """diff generates a valid diff for patches that change last line and
        add a newline.
        """
        lines = udiff_lines([b'boo'], [b'goo\n'])
        self.check_patch(lines)
        self.assertEqual(lines[4], b'\\ No newline at end of file\n')
        ## "expected no-nl, got %r" % lines[4]

    def test_remove_nl(self):
        """diff generates a valid diff for patches that change last line and
        add a newline.
        """
        lines = udiff_lines([b'boo\n'], [b'boo'])
        self.check_patch(lines)
        self.assertEqual(lines[5], b'\\ No newline at end of file\n')
        ## "expected no-nl, got %r" % lines[5]

    def check_patch(self, lines):
        self.assertTrue(len(lines) > 1)
        ## "Not enough lines for a file header for patch:\n%s" % "".join(lines)
        self.assertTrue(lines[0].startswith(b'---'))
        ## 'No orig line for patch:\n%s' % "".join(lines)
        self.assertTrue(lines[1].startswith(b'+++'))
        ## 'No mod line for patch:\n%s' % "".join(lines)
        self.assertTrue(len(lines) > 2)
        ## "No hunks for patch:\n%s" % "".join(lines)
        self.assertTrue(lines[2].startswith(b'@@'))
        ## "No hunk header for patch:\n%s" % "".join(lines)
        self.assertTrue(b'@@' in lines[2][2:])
        ## "Unterminated hunk header for patch:\n%s" % "".join(lines)

    def test_binary_lines(self):
        empty = []
        uni_lines = [1023 * b'a' + b'\x00']
        self.assertRaises(errors.BinaryFile, udiff_lines, uni_lines, empty)
        self.assertRaises(errors.BinaryFile, udiff_lines, empty, uni_lines)
        udiff_lines(uni_lines, empty, allow_binary=True)
        udiff_lines(empty, uni_lines, allow_binary=True)

    def test_external_diff(self):
        lines = external_udiff_lines([b'boo\n'], [b'goo\n'])
        self.check_patch(lines)
        self.assertEqual(b'\n', lines[-1])

    def test_external_diff_no_fileno(self):
        # Make sure that we can handle not having a fileno, even
        # if the diff is large
        lines = external_udiff_lines([b'boo\n'] * 10000,
                                     [b'goo\n'] * 10000,
                                     use_stringio=True)
        self.check_patch(lines)

    def test_external_diff_binary_lang_c(self):
        for lang in ('LANG', 'LC_ALL', 'LANGUAGE'):
            self.overrideEnv(lang, 'C')
        lines = external_udiff_lines([b'\x00foobar\n'], [b'foo\x00bar\n'])
        # Older versions of diffutils say "Binary files", newer
        # versions just say "Files".
        self.assertContainsRe(
            lines[0], b'(Binary f|F)iles old and new differ\n')
        self.assertEqual(lines[1:], [b'\n'])

    def test_no_external_diff(self):
        """Check that NoDiff is raised when diff is not available"""
        # Make sure no 'diff' command is available
        # XXX: Weird, using None instead of '' breaks the test -- vila 20101216
        self.overrideEnv('PATH', '')
        self.assertRaises(errors.NoDiff, diff.external_diff,
                          b'old', [b'boo\n'], b'new', [b'goo\n'],
                          BytesIO(), diff_opts=['-u'])

    def test_internal_diff_default(self):
        # Default internal diff encoding is utf8
        output = BytesIO()
        diff.internal_diff(u'old_\xb5', [b'old_text\n'],
                           u'new_\xe5', [b'new_text\n'], output)
        lines = output.getvalue().splitlines(True)
        self.check_patch(lines)
        self.assertEqual([b'--- old_\xc2\xb5\n',
                          b'+++ new_\xc3\xa5\n',
                          b'@@ -1,1 +1,1 @@\n',
                          b'-old_text\n',
                          b'+new_text\n',
                          b'\n',
                          ], lines)

    def test_internal_diff_utf8(self):
        output = BytesIO()
        diff.internal_diff(u'old_\xb5', [b'old_text\n'],
                           u'new_\xe5', [b'new_text\n'], output,
                           path_encoding='utf8')
        lines = output.getvalue().splitlines(True)
        self.check_patch(lines)
        self.assertEqual([b'--- old_\xc2\xb5\n',
                          b'+++ new_\xc3\xa5\n',
                          b'@@ -1,1 +1,1 @@\n',
                          b'-old_text\n',
                          b'+new_text\n',
                          b'\n',
                          ], lines)

    def test_internal_diff_iso_8859_1(self):
        output = BytesIO()
        diff.internal_diff(u'old_\xb5', [b'old_text\n'],
                           u'new_\xe5', [b'new_text\n'], output,
                           path_encoding='iso-8859-1')
        lines = output.getvalue().splitlines(True)
        self.check_patch(lines)
        self.assertEqual([b'--- old_\xb5\n',
                          b'+++ new_\xe5\n',
                          b'@@ -1,1 +1,1 @@\n',
                          b'-old_text\n',
                          b'+new_text\n',
                          b'\n',
                          ], lines)

    def test_internal_diff_no_content(self):
        output = BytesIO()
        diff.internal_diff(u'old', [], u'new', [], output)
        self.assertEqual(b'', output.getvalue())

    def test_internal_diff_no_changes(self):
        output = BytesIO()
        diff.internal_diff(u'old', [b'text\n', b'contents\n'],
                           u'new', [b'text\n', b'contents\n'],
                           output)
        self.assertEqual(b'', output.getvalue())

    def test_internal_diff_returns_bytes(self):
        output = StubO()
        diff.internal_diff(u'old_\xb5', [b'old_text\n'],
                           u'new_\xe5', [b'new_text\n'], output)
        output.check_types(self, bytes)

    def test_internal_diff_default_context(self):
        output = BytesIO()
        diff.internal_diff('old', [b'same_text\n', b'same_text\n', b'same_text\n',
                                   b'same_text\n', b'same_text\n', b'old_text\n'],
                           'new', [b'same_text\n', b'same_text\n', b'same_text\n',
                                   b'same_text\n', b'same_text\n', b'new_text\n'], output)
        lines = output.getvalue().splitlines(True)
        self.check_patch(lines)
        self.assertEqual([b'--- old\n',
                          b'+++ new\n',
                          b'@@ -3,4 +3,4 @@\n',
                          b' same_text\n',
                          b' same_text\n',
                          b' same_text\n',
                          b'-old_text\n',
                          b'+new_text\n',
                          b'\n',
                          ], lines)

    def test_internal_diff_no_context(self):
        output = BytesIO()
        diff.internal_diff('old', [b'same_text\n', b'same_text\n', b'same_text\n',
                                   b'same_text\n', b'same_text\n', b'old_text\n'],
                           'new', [b'same_text\n', b'same_text\n', b'same_text\n',
                                   b'same_text\n', b'same_text\n', b'new_text\n'], output,
                           context_lines=0)
        lines = output.getvalue().splitlines(True)
        self.check_patch(lines)
        self.assertEqual([b'--- old\n',
                          b'+++ new\n',
                          b'@@ -6,1 +6,1 @@\n',
                          b'-old_text\n',
                          b'+new_text\n',
                          b'\n',
                          ], lines)

    def test_internal_diff_more_context(self):
        output = BytesIO()
        diff.internal_diff('old', [b'same_text\n', b'same_text\n', b'same_text\n',
                                   b'same_text\n', b'same_text\n', b'old_text\n'],
                           'new', [b'same_text\n', b'same_text\n', b'same_text\n',
                                   b'same_text\n', b'same_text\n', b'new_text\n'], output,
                           context_lines=4)
        lines = output.getvalue().splitlines(True)
        self.check_patch(lines)
        self.assertEqual([b'--- old\n',
                          b'+++ new\n',
                          b'@@ -2,5 +2,5 @@\n',
                          b' same_text\n',
                          b' same_text\n',
                          b' same_text\n',
                          b' same_text\n',
                          b'-old_text\n',
                          b'+new_text\n',
                          b'\n',
                          ], lines)


class TestDiffFiles(tests.TestCaseInTempDir):

    def test_external_diff_binary(self):
        """The output when using external diff should use diff's i18n error"""
        for lang in ('LANG', 'LC_ALL', 'LANGUAGE'):
            self.overrideEnv(lang, 'C')
        # Make sure external_diff doesn't fail in the current LANG
        lines = external_udiff_lines([b'\x00foobar\n'], [b'foo\x00bar\n'])

        cmd = ['diff', '-u', '--binary', 'old', 'new']
        with open('old', 'wb') as f:
            f.write(b'\x00foobar\n')
        with open('new', 'wb') as f:
            f.write(b'foo\x00bar\n')
        pipe = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                stdin=subprocess.PIPE)
        out, err = pipe.communicate()
        # We should output whatever diff tells us, plus a trailing newline
        self.assertEqual(out.splitlines(True) + [b'\n'], lines)


def get_diff_as_string(tree1, tree2, specific_files=None, working_tree=None):
    output = BytesIO()
    if working_tree is not None:
        extra_trees = (working_tree,)
    else:
        extra_trees = ()
    diff.show_diff_trees(tree1, tree2, output,
                         specific_files=specific_files,
                         extra_trees=extra_trees, old_label='old/',
                         new_label='new/')
    return output.getvalue()


class TestDiffDates(tests.TestCaseWithTransport):

    def setUp(self):
        super(TestDiffDates, self).setUp()
        self.wt = self.make_branch_and_tree('.')
        self.b = self.wt.branch
        self.build_tree_contents([
            ('file1', b'file1 contents at rev 1\n'),
            ('file2', b'file2 contents at rev 1\n')
            ])
        self.wt.add(['file1', 'file2'])
        self.wt.commit(
            message='Revision 1',
            timestamp=1143849600,  # 2006-04-01 00:00:00 UTC
            timezone=0,
            rev_id=b'rev-1')
        self.build_tree_contents([('file1', b'file1 contents at rev 2\n')])
        self.wt.commit(
            message='Revision 2',
            timestamp=1143936000,  # 2006-04-02 00:00:00 UTC
            timezone=28800,
            rev_id=b'rev-2')
        self.build_tree_contents([('file2', b'file2 contents at rev 3\n')])
        self.wt.commit(
            message='Revision 3',
            timestamp=1144022400,  # 2006-04-03 00:00:00 UTC
            timezone=-3600,
            rev_id=b'rev-3')
        self.wt.remove(['file2'])
        self.wt.commit(
            message='Revision 4',
            timestamp=1144108800,  # 2006-04-04 00:00:00 UTC
            timezone=0,
            rev_id=b'rev-4')
        self.build_tree_contents([
            ('file1', b'file1 contents in working tree\n')
            ])
        # set the date stamps for files in the working tree to known values
        os.utime('file1', (1144195200, 1144195200))  # 2006-04-05 00:00:00 UTC

    def test_diff_rev_tree_working_tree(self):
        output = get_diff_as_string(self.wt.basis_tree(), self.wt)
        # note that the date for old/file1 is from rev 2 rather than from
        # the basis revision (rev 4)
        self.assertEqualDiff(output, b'''\
=== modified file 'file1'
--- old/file1\t2006-04-02 00:00:00 +0000
+++ new/file1\t2006-04-05 00:00:00 +0000
@@ -1,1 +1,1 @@
-file1 contents at rev 2
+file1 contents in working tree

''')

    def test_diff_rev_tree_rev_tree(self):
        tree1 = self.b.repository.revision_tree(b'rev-2')
        tree2 = self.b.repository.revision_tree(b'rev-3')
        output = get_diff_as_string(tree1, tree2)
        self.assertEqualDiff(output, b'''\
=== modified file 'file2'
--- old/file2\t2006-04-01 00:00:00 +0000
+++ new/file2\t2006-04-03 00:00:00 +0000
@@ -1,1 +1,1 @@
-file2 contents at rev 1
+file2 contents at rev 3

''')

    def test_diff_add_files(self):
        tree1 = self.b.repository.revision_tree(_mod_revision.NULL_REVISION)
        tree2 = self.b.repository.revision_tree(b'rev-1')
        output = get_diff_as_string(tree1, tree2)
        # the files have the epoch time stamp for the tree in which
        # they don't exist.
        self.assertEqualDiff(output, b'''\
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
        tree1 = self.b.repository.revision_tree(b'rev-3')
        tree2 = self.b.repository.revision_tree(b'rev-4')
        output = get_diff_as_string(tree1, tree2)
        # the file has the epoch time stamp for the tree in which
        # it doesn't exist.
        self.assertEqualDiff(output, b'''\
=== removed file 'file2'
--- old/file2\t2006-04-03 00:00:00 +0000
+++ new/file2\t1970-01-01 00:00:00 +0000
@@ -1,1 +0,0 @@
-file2 contents at rev 3

''')

    def test_show_diff_specified(self):
        """A working tree filename can be used to identify a file"""
        self.wt.rename_one('file1', 'file1b')
        old_tree = self.b.repository.revision_tree(b'rev-1')
        new_tree = self.b.repository.revision_tree(b'rev-4')
        out = get_diff_as_string(old_tree, new_tree, specific_files=['file1b'],
                                 working_tree=self.wt)
        self.assertContainsRe(out, b'file1\t')

    def test_recursive_diff(self):
        """Children of directories are matched"""
        os.mkdir('dir1')
        os.mkdir('dir2')
        self.wt.add(['dir1', 'dir2'])
        self.wt.rename_one('file1', 'dir1/file1')
        old_tree = self.b.repository.revision_tree(b'rev-1')
        new_tree = self.b.repository.revision_tree(b'rev-4')
        out = get_diff_as_string(old_tree, new_tree, specific_files=['dir1'],
                                 working_tree=self.wt)
        self.assertContainsRe(out, b'file1\t')
        out = get_diff_as_string(old_tree, new_tree, specific_files=['dir2'],
                                 working_tree=self.wt)
        self.assertNotContainsRe(out, b'file1\t')


class TestShowDiffTrees(tests.TestCaseWithTransport):
    """Direct tests for show_diff_trees"""

    def test_modified_file(self):
        """Test when a file is modified."""
        tree = self.make_branch_and_tree('tree')
        self.build_tree_contents([('tree/file', b'contents\n')])
        tree.add(['file'], [b'file-id'])
        tree.commit('one', rev_id=b'rev-1')

        self.build_tree_contents([('tree/file', b'new contents\n')])
        d = get_diff_as_string(tree.basis_tree(), tree)
        self.assertContainsRe(d, b"=== modified file 'file'\n")
        self.assertContainsRe(d, b'--- old/file\t')
        self.assertContainsRe(d, b'\\+\\+\\+ new/file\t')
        self.assertContainsRe(d, b'-contents\n'
                                 b'\\+new contents\n')

    def test_modified_file_in_renamed_dir(self):
        """Test when a file is modified in a renamed directory."""
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/dir/'])
        self.build_tree_contents([('tree/dir/file', b'contents\n')])
        tree.add(['dir', 'dir/file'], [b'dir-id', b'file-id'])
        tree.commit('one', rev_id=b'rev-1')

        tree.rename_one('dir', 'other')
        self.build_tree_contents([('tree/other/file', b'new contents\n')])
        d = get_diff_as_string(tree.basis_tree(), tree)
        self.assertContainsRe(d, b"=== renamed directory 'dir' => 'other'\n")
        self.assertContainsRe(d, b"=== modified file 'other/file'\n")
        # XXX: This is technically incorrect, because it used to be at another
        # location. What to do?
        self.assertContainsRe(d, b'--- old/dir/file\t')
        self.assertContainsRe(d, b'\\+\\+\\+ new/other/file\t')
        self.assertContainsRe(d, b'-contents\n'
                                 b'\\+new contents\n')

    def test_renamed_directory(self):
        """Test when only a directory is only renamed."""
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/dir/'])
        self.build_tree_contents([('tree/dir/file', b'contents\n')])
        tree.add(['dir', 'dir/file'], [b'dir-id', b'file-id'])
        tree.commit('one', rev_id=b'rev-1')

        tree.rename_one('dir', 'newdir')
        d = get_diff_as_string(tree.basis_tree(), tree)
        # Renaming a directory should be a single "you renamed this dir" even
        # when there are files inside.
        self.assertEqual(d, b"=== renamed directory 'dir' => 'newdir'\n")

    def test_renamed_file(self):
        """Test when a file is only renamed."""
        tree = self.make_branch_and_tree('tree')
        self.build_tree_contents([('tree/file', b'contents\n')])
        tree.add(['file'], [b'file-id'])
        tree.commit('one', rev_id=b'rev-1')

        tree.rename_one('file', 'newname')
        d = get_diff_as_string(tree.basis_tree(), tree)
        self.assertContainsRe(d, b"=== renamed file 'file' => 'newname'\n")
        # We shouldn't have a --- or +++ line, because there is no content
        # change
        self.assertNotContainsRe(d, b'---')

    def test_renamed_and_modified_file(self):
        """Test when a file is only renamed."""
        tree = self.make_branch_and_tree('tree')
        self.build_tree_contents([('tree/file', b'contents\n')])
        tree.add(['file'], [b'file-id'])
        tree.commit('one', rev_id=b'rev-1')

        tree.rename_one('file', 'newname')
        self.build_tree_contents([('tree/newname', b'new contents\n')])
        d = get_diff_as_string(tree.basis_tree(), tree)
        self.assertContainsRe(d, b"=== renamed file 'file' => 'newname'\n")
        self.assertContainsRe(d, b'--- old/file\t')
        self.assertContainsRe(d, b'\\+\\+\\+ new/newname\t')
        self.assertContainsRe(d, b'-contents\n'
                                 b'\\+new contents\n')

    def test_internal_diff_exec_property(self):
        tree = self.make_branch_and_tree('tree')

        tt = transform.TreeTransform(tree)
        tt.new_file('a', tt.root, [b'contents\n'], b'a-id', True)
        tt.new_file('b', tt.root, [b'contents\n'], b'b-id', False)
        tt.new_file('c', tt.root, [b'contents\n'], b'c-id', True)
        tt.new_file('d', tt.root, [b'contents\n'], b'd-id', False)
        tt.new_file('e', tt.root, [b'contents\n'], b'control-e-id', True)
        tt.new_file('f', tt.root, [b'contents\n'], b'control-f-id', False)
        tt.apply()
        tree.commit('one', rev_id=b'rev-1')

        tt = transform.TreeTransform(tree)
        tt.set_executability(False, tt.trans_id_file_id(b'a-id'))
        tt.set_executability(True, tt.trans_id_file_id(b'b-id'))
        tt.set_executability(False, tt.trans_id_file_id(b'c-id'))
        tt.set_executability(True, tt.trans_id_file_id(b'd-id'))
        tt.apply()
        tree.rename_one('c', 'new-c')
        tree.rename_one('d', 'new-d')

        d = get_diff_as_string(tree.basis_tree(), tree)

        self.assertContainsRe(d, br"file 'a'.*\(properties changed:"
                                 br".*\+x to -x.*\)")
        self.assertContainsRe(d, br"file 'b'.*\(properties changed:"
                                 br".*-x to \+x.*\)")
        self.assertContainsRe(d, br"file 'c'.*\(properties changed:"
                                 br".*\+x to -x.*\)")
        self.assertContainsRe(d, br"file 'd'.*\(properties changed:"
                                 br".*-x to \+x.*\)")
        self.assertNotContainsRe(d, br"file 'e'")
        self.assertNotContainsRe(d, br"file 'f'")

    def test_binary_unicode_filenames(self):
        """Test that contents of files are *not* encoded in UTF-8 when there
        is a binary file in the diff.
        """
        # See https://bugs.launchpad.net/bugs/110092.
        self.requireFeature(features.UnicodeFilenameFeature)

        tree = self.make_branch_and_tree('tree')
        alpha, omega = u'\u03b1', u'\u03c9'
        alpha_utf8, omega_utf8 = alpha.encode('utf8'), omega.encode('utf8')
        self.build_tree_contents(
            [('tree/' + alpha, b'\0'),
             ('tree/' + omega,
              (b'The %s and the %s\n' % (alpha_utf8, omega_utf8)))])
        tree.add([alpha], [b'file-id'])
        tree.add([omega], [b'file-id-2'])
        diff_content = StubO()
        diff.show_diff_trees(tree.basis_tree(), tree, diff_content)
        diff_content.check_types(self, bytes)
        d = b''.join(diff_content.write_record)
        self.assertContainsRe(d, br"=== added file '%s'" % alpha_utf8)
        self.assertContainsRe(d, b"Binary files a/%s.*and b/%s.* differ\n"
                              % (alpha_utf8, alpha_utf8))
        self.assertContainsRe(d, br"=== added file '%s'" % omega_utf8)
        self.assertContainsRe(d, br"--- a/%s" % (omega_utf8,))
        self.assertContainsRe(d, br"\+\+\+ b/%s" % (omega_utf8,))

    def test_unicode_filename(self):
        """Test when the filename are unicode."""
        self.requireFeature(features.UnicodeFilenameFeature)

        alpha, omega = u'\u03b1', u'\u03c9'
        autf8, outf8 = alpha.encode('utf8'), omega.encode('utf8')

        tree = self.make_branch_and_tree('tree')
        self.build_tree_contents([('tree/ren_' + alpha, b'contents\n')])
        tree.add(['ren_' + alpha], [b'file-id-2'])
        self.build_tree_contents([('tree/del_' + alpha, b'contents\n')])
        tree.add(['del_' + alpha], [b'file-id-3'])
        self.build_tree_contents([('tree/mod_' + alpha, b'contents\n')])
        tree.add(['mod_' + alpha], [b'file-id-4'])

        tree.commit('one', rev_id=b'rev-1')

        tree.rename_one('ren_' + alpha, 'ren_' + omega)
        tree.remove('del_' + alpha)
        self.build_tree_contents([('tree/add_' + alpha, b'contents\n')])
        tree.add(['add_' + alpha], [b'file-id'])
        self.build_tree_contents([('tree/mod_' + alpha, b'contents_mod\n')])

        d = get_diff_as_string(tree.basis_tree(), tree)
        self.assertContainsRe(d,
                              b"=== renamed file 'ren_%s' => 'ren_%s'\n" % (autf8, outf8))
        self.assertContainsRe(d, b"=== added file 'add_%s'" % autf8)
        self.assertContainsRe(d, b"=== modified file 'mod_%s'" % autf8)
        self.assertContainsRe(d, b"=== removed file 'del_%s'" % autf8)

    def test_unicode_filename_path_encoding(self):
        """Test for bug #382699: unicode filenames on Windows should be shown
        in user encoding.
        """
        self.requireFeature(features.UnicodeFilenameFeature)
        # The word 'test' in Russian
        _russian_test = u'\u0422\u0435\u0441\u0442'
        directory = _russian_test + u'/'
        test_txt = _russian_test + u'.txt'
        u1234 = u'\u1234.txt'

        tree = self.make_branch_and_tree('.')
        self.build_tree_contents([
            (test_txt, b'foo\n'),
            (u1234, b'foo\n'),
            (directory, None),
            ])
        tree.add([test_txt, u1234, directory])

        sio = BytesIO()
        diff.show_diff_trees(tree.basis_tree(), tree, sio,
                             path_encoding='cp1251')

        output = subst_dates(sio.getvalue())
        shouldbe = (b'''\
=== added directory '%(directory)s'
=== added file '%(test_txt)s'
--- a/%(test_txt)s\tYYYY-MM-DD HH:MM:SS +ZZZZ
+++ b/%(test_txt)s\tYYYY-MM-DD HH:MM:SS +ZZZZ
@@ -0,0 +1,1 @@
+foo

=== added file '?.txt'
--- a/?.txt\tYYYY-MM-DD HH:MM:SS +ZZZZ
+++ b/?.txt\tYYYY-MM-DD HH:MM:SS +ZZZZ
@@ -0,0 +1,1 @@
+foo

''' % {b'directory': _russian_test.encode('cp1251'),
            b'test_txt': test_txt.encode('cp1251'),
       })
        self.assertEqualDiff(output, shouldbe)


class DiffWasIs(diff.DiffPath):

    def diff(self, file_id, old_path, new_path, old_kind, new_kind):
        self.to_file.write(b'was: ')
        self.to_file.write(self.old_tree.get_file(old_path).read())
        self.to_file.write(b'is: ')
        self.to_file.write(self.new_tree.get_file(new_path).read())


class TestDiffTree(tests.TestCaseWithTransport):

    def setUp(self):
        super(TestDiffTree, self).setUp()
        self.old_tree = self.make_branch_and_tree('old-tree')
        self.old_tree.lock_write()
        self.addCleanup(self.old_tree.unlock)
        self.new_tree = self.make_branch_and_tree('new-tree')
        self.new_tree.lock_write()
        self.addCleanup(self.new_tree.unlock)
        self.differ = diff.DiffTree(self.old_tree, self.new_tree, BytesIO())

    def test_diff_text(self):
        self.build_tree_contents([('old-tree/olddir/',),
                                  ('old-tree/olddir/oldfile', b'old\n')])
        self.old_tree.add('olddir')
        self.old_tree.add('olddir/oldfile', b'file-id')
        self.build_tree_contents([('new-tree/newdir/',),
                                  ('new-tree/newdir/newfile', b'new\n')])
        self.new_tree.add('newdir')
        self.new_tree.add('newdir/newfile', b'file-id')
        differ = diff.DiffText(self.old_tree, self.new_tree, BytesIO())
        differ.diff_text('olddir/oldfile', None, 'old label',
                         'new label', b'file-id', None)
        self.assertEqual(
            b'--- old label\n+++ new label\n@@ -1,1 +0,0 @@\n-old\n\n',
            differ.to_file.getvalue())
        differ.to_file.seek(0)
        differ.diff_text(None, 'newdir/newfile',
                         'old label', 'new label', None, b'file-id')
        self.assertEqual(
            b'--- old label\n+++ new label\n@@ -0,0 +1,1 @@\n+new\n\n',
            differ.to_file.getvalue())
        differ.to_file.seek(0)
        differ.diff_text('olddir/oldfile', 'newdir/newfile',
                         'old label', 'new label', b'file-id', b'file-id')
        self.assertEqual(
            b'--- old label\n+++ new label\n@@ -1,1 +1,1 @@\n-old\n+new\n\n',
            differ.to_file.getvalue())

    def test_diff_deletion(self):
        self.build_tree_contents([('old-tree/file', b'contents'),
                                  ('new-tree/file', b'contents')])
        self.old_tree.add('file', b'file-id')
        self.new_tree.add('file', b'file-id')
        os.unlink('new-tree/file')
        self.differ.show_diff(None)
        self.assertContainsRe(self.differ.to_file.getvalue(), b'-contents')

    def test_diff_creation(self):
        self.build_tree_contents([('old-tree/file', b'contents'),
                                  ('new-tree/file', b'contents')])
        self.old_tree.add('file', b'file-id')
        self.new_tree.add('file', b'file-id')
        os.unlink('old-tree/file')
        self.differ.show_diff(None)
        self.assertContainsRe(self.differ.to_file.getvalue(), br'\+contents')

    def test_diff_symlink(self):
        differ = diff.DiffSymlink(self.old_tree, self.new_tree, BytesIO())
        differ.diff_symlink('old target', None)
        self.assertEqual(b"=== target was 'old target'\n",
                         differ.to_file.getvalue())

        differ = diff.DiffSymlink(self.old_tree, self.new_tree, BytesIO())
        differ.diff_symlink(None, 'new target')
        self.assertEqual(b"=== target is 'new target'\n",
                         differ.to_file.getvalue())

        differ = diff.DiffSymlink(self.old_tree, self.new_tree, BytesIO())
        differ.diff_symlink('old target', 'new target')
        self.assertEqual(b"=== target changed 'old target' => 'new target'\n",
                         differ.to_file.getvalue())

    def test_diff(self):
        self.build_tree_contents([('old-tree/olddir/',),
                                  ('old-tree/olddir/oldfile', b'old\n')])
        self.old_tree.add('olddir')
        self.old_tree.add('olddir/oldfile', b'file-id')
        self.build_tree_contents([('new-tree/newdir/',),
                                  ('new-tree/newdir/newfile', b'new\n')])
        self.new_tree.add('newdir')
        self.new_tree.add('newdir/newfile', b'file-id')
        self.differ.diff(b'file-id', 'olddir/oldfile', 'newdir/newfile')
        self.assertContainsRe(
            self.differ.to_file.getvalue(),
            br'--- olddir/oldfile.*\n\+\+\+ newdir/newfile.*\n\@\@ -1,1 \+1,1'
            br' \@\@\n-old\n\+new\n\n')

    def test_diff_kind_change(self):
        self.requireFeature(features.SymlinkFeature)
        self.build_tree_contents([('old-tree/olddir/',),
                                  ('old-tree/olddir/oldfile', b'old\n')])
        self.old_tree.add('olddir')
        self.old_tree.add('olddir/oldfile', b'file-id')
        self.build_tree(['new-tree/newdir/'])
        os.symlink('new', 'new-tree/newdir/newfile')
        self.new_tree.add('newdir')
        self.new_tree.add('newdir/newfile', b'file-id')
        self.differ.diff(b'file-id', 'olddir/oldfile', 'newdir/newfile')
        self.assertContainsRe(
            self.differ.to_file.getvalue(),
            br'--- olddir/oldfile.*\n\+\+\+ newdir/newfile.*\n\@\@ -1,1 \+0,0'
            br' \@\@\n-old\n\n')
        self.assertContainsRe(self.differ.to_file.getvalue(),
                              b"=== target is 'new'\n")

    def test_diff_directory(self):
        self.build_tree(['new-tree/new-dir/'])
        self.new_tree.add('new-dir', b'new-dir-id')
        self.differ.diff(b'new-dir-id', None, 'new-dir')
        self.assertEqual(self.differ.to_file.getvalue(), b'')

    def create_old_new(self):
        self.build_tree_contents([('old-tree/olddir/',),
                                  ('old-tree/olddir/oldfile', b'old\n')])
        self.old_tree.add('olddir')
        self.old_tree.add('olddir/oldfile', b'file-id')
        self.build_tree_contents([('new-tree/newdir/',),
                                  ('new-tree/newdir/newfile', b'new\n')])
        self.new_tree.add('newdir')
        self.new_tree.add('newdir/newfile', b'file-id')

    def test_register_diff(self):
        self.create_old_new()
        old_diff_factories = diff.DiffTree.diff_factories
        diff.DiffTree.diff_factories = old_diff_factories[:]
        diff.DiffTree.diff_factories.insert(0, DiffWasIs.from_diff_tree)
        try:
            differ = diff.DiffTree(self.old_tree, self.new_tree, BytesIO())
        finally:
            diff.DiffTree.diff_factories = old_diff_factories
        differ.diff(b'file-id', 'olddir/oldfile', 'newdir/newfile')
        self.assertNotContainsRe(
            differ.to_file.getvalue(),
            br'--- olddir/oldfile.*\n\+\+\+ newdir/newfile.*\n\@\@ -1,1 \+1,1'
            br' \@\@\n-old\n\+new\n\n')
        self.assertContainsRe(differ.to_file.getvalue(),
                              b'was: old\nis: new\n')

    def test_extra_factories(self):
        self.create_old_new()
        differ = diff.DiffTree(self.old_tree, self.new_tree, BytesIO(),
                               extra_factories=[DiffWasIs.from_diff_tree])
        differ.diff(b'file-id', 'olddir/oldfile', 'newdir/newfile')
        self.assertNotContainsRe(
            differ.to_file.getvalue(),
            br'--- olddir/oldfile.*\n\+\+\+ newdir/newfile.*\n\@\@ -1,1 \+1,1'
            br' \@\@\n-old\n\+new\n\n')
        self.assertContainsRe(differ.to_file.getvalue(),
                              b'was: old\nis: new\n')

    def test_alphabetical_order(self):
        self.build_tree(['new-tree/a-file'])
        self.new_tree.add('a-file')
        self.build_tree(['old-tree/b-file'])
        self.old_tree.add('b-file')
        self.differ.show_diff(None)
        self.assertContainsRe(self.differ.to_file.getvalue(),
                              b'.*a-file(.|\n)*b-file')


class TestPatienceDiffLib(tests.TestCase):

    def setUp(self):
        super(TestPatienceDiffLib, self).setUp()
        self._unique_lcs = _patiencediff_py.unique_lcs_py
        self._recurse_matches = _patiencediff_py.recurse_matches_py
        self._PatienceSequenceMatcher = \
            _patiencediff_py.PatienceSequenceMatcher_py

    def test_diff_unicode_string(self):
        a = ''.join([unichr(i) for i in range(4000, 4500, 3)])
        b = ''.join([unichr(i) for i in range(4300, 4800, 2)])
        sm = self._PatienceSequenceMatcher(None, a, b)
        mb = sm.get_matching_blocks()
        self.assertEqual(35, len(mb))

    def test_unique_lcs(self):
        unique_lcs = self._unique_lcs
        self.assertEqual(unique_lcs('', ''), [])
        self.assertEqual(unique_lcs('', 'a'), [])
        self.assertEqual(unique_lcs('a', ''), [])
        self.assertEqual(unique_lcs('a', 'a'), [(0, 0)])
        self.assertEqual(unique_lcs('a', 'b'), [])
        self.assertEqual(unique_lcs('ab', 'ab'), [(0, 0), (1, 1)])
        self.assertEqual(unique_lcs('abcde', 'cdeab'),
                         [(2, 0), (3, 1), (4, 2)])
        self.assertEqual(unique_lcs('cdeab', 'abcde'),
                         [(0, 2), (1, 3), (2, 4)])
        self.assertEqual(unique_lcs('abXde', 'abYde'), [(0, 0), (1, 1),
                                                        (3, 3), (4, 4)])
        self.assertEqual(unique_lcs('acbac', 'abc'), [(2, 1)])

    def test_recurse_matches(self):
        def test_one(a, b, matches):
            test_matches = []
            self._recurse_matches(
                a, b, 0, 0, len(a), len(b), test_matches, 10)
            self.assertEqual(test_matches, matches)

        test_one(['a', '', 'b', '', 'c'], ['a', 'a', 'b', 'c', 'c'],
                 [(0, 0), (2, 2), (4, 4)])
        test_one(['a', 'c', 'b', 'a', 'c'], ['a', 'b', 'c'],
                 [(0, 0), (2, 1), (4, 2)])
        # Even though 'bc' is not unique globally, and is surrounded by
        # non-matching lines, we should still match, because they are locally
        # unique
        test_one('abcdbce', 'afbcgdbce', [(0, 0), (1, 2), (2, 3), (3, 5),
                                          (4, 6), (5, 7), (6, 8)])

        # recurse_matches doesn't match non-unique
        # lines surrounded by bogus text.
        # The update has been done in patiencediff.SequenceMatcher instead

        # This is what it could be
        #test_one('aBccDe', 'abccde', [(0,0), (2,2), (3,3), (5,5)])

        # This is what it currently gives:
        test_one('aBccDe', 'abccde', [(0, 0), (5, 5)])

    def assertDiffBlocks(self, a, b, expected_blocks):
        """Check that the sequence matcher returns the correct blocks.

        :param a: A sequence to match
        :param b: Another sequence to match
        :param expected_blocks: The expected output, not including the final
            matching block (len(a), len(b), 0)
        """
        matcher = self._PatienceSequenceMatcher(None, a, b)
        blocks = matcher.get_matching_blocks()
        last = blocks.pop()
        self.assertEqual((len(a), len(b), 0), last)
        self.assertEqual(expected_blocks, blocks)

    def test_matching_blocks(self):
        # Some basic matching tests
        self.assertDiffBlocks('', '', [])
        self.assertDiffBlocks([], [], [])
        self.assertDiffBlocks('abc', '', [])
        self.assertDiffBlocks('', 'abc', [])
        self.assertDiffBlocks('abcd', 'abcd', [(0, 0, 4)])
        self.assertDiffBlocks('abcd', 'abce', [(0, 0, 3)])
        self.assertDiffBlocks('eabc', 'abce', [(1, 0, 3)])
        self.assertDiffBlocks('eabce', 'abce', [(1, 0, 4)])
        self.assertDiffBlocks('abcde', 'abXde', [(0, 0, 2), (3, 3, 2)])
        self.assertDiffBlocks('abcde', 'abXYZde', [(0, 0, 2), (3, 5, 2)])
        self.assertDiffBlocks('abde', 'abXYZde', [(0, 0, 2), (2, 5, 2)])
        # This may check too much, but it checks to see that
        # a copied block stays attached to the previous section,
        # not the later one.
        # difflib would tend to grab the trailing longest match
        # which would make the diff not look right
        self.assertDiffBlocks('abcdefghijklmnop', 'abcdefxydefghijklmnop',
                              [(0, 0, 6), (6, 11, 10)])

        # make sure it supports passing in lists
        self.assertDiffBlocks(
            ['hello there\n',
             'world\n',
             'how are you today?\n'],
            ['hello there\n',
             'how are you today?\n'],
            [(0, 0, 1), (2, 1, 1)])

        # non unique lines surrounded by non-matching lines
        # won't be found
        self.assertDiffBlocks('aBccDe', 'abccde', [(0, 0, 1), (5, 5, 1)])

        # But they only need to be locally unique
        self.assertDiffBlocks('aBcDec', 'abcdec', [
                              (0, 0, 1), (2, 2, 1), (4, 4, 2)])

        # non unique blocks won't be matched
        self.assertDiffBlocks('aBcdEcdFg', 'abcdecdfg', [(0, 0, 1), (8, 8, 1)])

        # but locally unique ones will
        self.assertDiffBlocks('aBcdEeXcdFg', 'abcdecdfg', [(0, 0, 1), (2, 2, 2),
                                                           (5, 4, 1), (7, 5, 2), (10, 8, 1)])

        self.assertDiffBlocks('abbabbXd', 'cabbabxd', [(7, 7, 1)])
        self.assertDiffBlocks('abbabbbb', 'cabbabbc', [])
        self.assertDiffBlocks('bbbbbbbb', 'cbbbbbbc', [])

    def test_matching_blocks_tuples(self):
        # Some basic matching tests
        self.assertDiffBlocks([], [], [])
        self.assertDiffBlocks([('a',), ('b',), ('c,')], [], [])
        self.assertDiffBlocks([], [('a',), ('b',), ('c,')], [])
        self.assertDiffBlocks([('a',), ('b',), ('c,')],
                              [('a',), ('b',), ('c,')],
                              [(0, 0, 3)])
        self.assertDiffBlocks([('a',), ('b',), ('c,')],
                              [('a',), ('b',), ('d,')],
                              [(0, 0, 2)])
        self.assertDiffBlocks([('d',), ('b',), ('c,')],
                              [('a',), ('b',), ('c,')],
                              [(1, 1, 2)])
        self.assertDiffBlocks([('d',), ('a',), ('b',), ('c,')],
                              [('a',), ('b',), ('c,')],
                              [(1, 0, 3)])
        self.assertDiffBlocks([('a', 'b'), ('c', 'd'), ('e', 'f')],
                              [('a', 'b'), ('c', 'X'), ('e', 'f')],
                              [(0, 0, 1), (2, 2, 1)])
        self.assertDiffBlocks([('a', 'b'), ('c', 'd'), ('e', 'f')],
                              [('a', 'b'), ('c', 'dX'), ('e', 'f')],
                              [(0, 0, 1), (2, 2, 1)])

    def test_opcodes(self):
        def chk_ops(a, b, expected_codes):
            s = self._PatienceSequenceMatcher(None, a, b)
            self.assertEqual(expected_codes, s.get_opcodes())

        chk_ops('', '', [])
        chk_ops([], [], [])
        chk_ops('abc', '', [('delete', 0, 3, 0, 0)])
        chk_ops('', 'abc', [('insert', 0, 0, 0, 3)])
        chk_ops('abcd', 'abcd', [('equal', 0, 4, 0, 4)])
        chk_ops('abcd', 'abce', [('equal', 0, 3, 0, 3),
                                 ('replace', 3, 4, 3, 4)
                                 ])
        chk_ops('eabc', 'abce', [('delete', 0, 1, 0, 0),
                                 ('equal', 1, 4, 0, 3),
                                 ('insert', 4, 4, 3, 4)
                                 ])
        chk_ops('eabce', 'abce', [('delete', 0, 1, 0, 0),
                                  ('equal', 1, 5, 0, 4)
                                  ])
        chk_ops('abcde', 'abXde', [('equal', 0, 2, 0, 2),
                                   ('replace', 2, 3, 2, 3),
                                   ('equal', 3, 5, 3, 5)
                                   ])
        chk_ops('abcde', 'abXYZde', [('equal', 0, 2, 0, 2),
                                     ('replace', 2, 3, 2, 5),
                                     ('equal', 3, 5, 5, 7)
                                     ])
        chk_ops('abde', 'abXYZde', [('equal', 0, 2, 0, 2),
                                    ('insert', 2, 2, 2, 5),
                                    ('equal', 2, 4, 5, 7)
                                    ])
        chk_ops('abcdefghijklmnop', 'abcdefxydefghijklmnop',
                [('equal', 0, 6, 0, 6),
                 ('insert', 6, 6, 6, 11),
                 ('equal', 6, 16, 11, 21)
                 ])
        chk_ops(
            ['hello there\n', 'world\n', 'how are you today?\n'],
            ['hello there\n', 'how are you today?\n'],
            [('equal', 0, 1, 0, 1),
             ('delete', 1, 2, 1, 1),
             ('equal', 2, 3, 1, 2),
             ])
        chk_ops('aBccDe', 'abccde',
                [('equal', 0, 1, 0, 1),
                 ('replace', 1, 5, 1, 5),
                 ('equal', 5, 6, 5, 6),
                 ])
        chk_ops('aBcDec', 'abcdec',
                [('equal', 0, 1, 0, 1),
                 ('replace', 1, 2, 1, 2),
                 ('equal', 2, 3, 2, 3),
                 ('replace', 3, 4, 3, 4),
                 ('equal', 4, 6, 4, 6),
                 ])
        chk_ops('aBcdEcdFg', 'abcdecdfg',
                [('equal', 0, 1, 0, 1),
                 ('replace', 1, 8, 1, 8),
                 ('equal', 8, 9, 8, 9)
                 ])
        chk_ops('aBcdEeXcdFg', 'abcdecdfg',
                [('equal', 0, 1, 0, 1),
                 ('replace', 1, 2, 1, 2),
                 ('equal', 2, 4, 2, 4),
                 ('delete', 4, 5, 4, 4),
                 ('equal', 5, 6, 4, 5),
                 ('delete', 6, 7, 5, 5),
                 ('equal', 7, 9, 5, 7),
                 ('replace', 9, 10, 7, 8),
                 ('equal', 10, 11, 8, 9)
                 ])

    def test_grouped_opcodes(self):
        def chk_ops(a, b, expected_codes, n=3):
            s = self._PatienceSequenceMatcher(None, a, b)
            self.assertEqual(expected_codes, list(s.get_grouped_opcodes(n)))

        chk_ops('', '', [])
        chk_ops([], [], [])
        chk_ops('abc', '', [[('delete', 0, 3, 0, 0)]])
        chk_ops('', 'abc', [[('insert', 0, 0, 0, 3)]])
        chk_ops('abcd', 'abcd', [])
        chk_ops('abcd', 'abce', [[('equal', 0, 3, 0, 3),
                                  ('replace', 3, 4, 3, 4)
                                  ]])
        chk_ops('eabc', 'abce', [[('delete', 0, 1, 0, 0),
                                  ('equal', 1, 4, 0, 3),
                                  ('insert', 4, 4, 3, 4)
                                  ]])
        chk_ops('abcdefghijklmnop', 'abcdefxydefghijklmnop',
                [[('equal', 3, 6, 3, 6),
                  ('insert', 6, 6, 6, 11),
                  ('equal', 6, 9, 11, 14)
                  ]])
        chk_ops('abcdefghijklmnop', 'abcdefxydefghijklmnop',
                [[('equal', 2, 6, 2, 6),
                  ('insert', 6, 6, 6, 11),
                  ('equal', 6, 10, 11, 15)
                  ]], 4)
        chk_ops('Xabcdef', 'abcdef',
                [[('delete', 0, 1, 0, 0),
                  ('equal', 1, 4, 0, 3)
                  ]])
        chk_ops('abcdef', 'abcdefX',
                [[('equal', 3, 6, 3, 6),
                  ('insert', 6, 6, 6, 7)
                  ]])

    def test_multiple_ranges(self):
        # There was an earlier bug where we used a bad set of ranges,
        # this triggers that specific bug, to make sure it doesn't regress
        self.assertDiffBlocks('abcdefghijklmnop',
                              'abcXghiYZQRSTUVWXYZijklmnop',
                              [(0, 0, 3), (6, 4, 3), (9, 20, 7)])

        self.assertDiffBlocks('ABCd efghIjk  L',
                              'AxyzBCn mo pqrstuvwI1 2  L',
                              [(0, 0, 1), (1, 4, 2), (9, 19, 1), (12, 23, 3)])

        # These are rot13 code snippets.
        self.assertDiffBlocks('''\
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
'''.splitlines(True), [(0, 0, 1), (1, 4, 2), (9, 19, 1), (12, 23, 3)])

    def test_patience_unified_diff(self):
        txt_a = ['hello there\n',
                 'world\n',
                 'how are you today?\n']
        txt_b = ['hello there\n',
                 'how are you today?\n']
        unified_diff = patiencediff.unified_diff
        psm = self._PatienceSequenceMatcher
        self.assertEqual(['--- \n',
                          '+++ \n',
                          '@@ -1,3 +1,2 @@\n',
                          ' hello there\n',
                          '-world\n',
                          ' how are you today?\n'
                          ], list(unified_diff(txt_a, txt_b,
                                               sequencematcher=psm)))
        txt_a = [x + '\n' for x in 'abcdefghijklmnop']
        txt_b = [x + '\n' for x in 'abcdefxydefghijklmnop']
        # This is the result with LongestCommonSubstring matching
        self.assertEqual(['--- \n',
                          '+++ \n',
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
                          ' f\n'], list(unified_diff(txt_a, txt_b)))
        # And the patience diff
        self.assertEqual(['--- \n',
                          '+++ \n',
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
                          ], list(unified_diff(txt_a, txt_b,
                                               sequencematcher=psm)))

    def test_patience_unified_diff_with_dates(self):
        txt_a = ['hello there\n',
                 'world\n',
                 'how are you today?\n']
        txt_b = ['hello there\n',
                 'how are you today?\n']
        unified_diff = patiencediff.unified_diff
        psm = self._PatienceSequenceMatcher
        self.assertEqual(['--- a\t2008-08-08\n',
                          '+++ b\t2008-09-09\n',
                          '@@ -1,3 +1,2 @@\n',
                          ' hello there\n',
                          '-world\n',
                          ' how are you today?\n'
                          ], list(unified_diff(txt_a, txt_b,
                                               fromfile='a', tofile='b',
                                               fromfiledate='2008-08-08',
                                               tofiledate='2008-09-09',
                                               sequencematcher=psm)))


class TestPatienceDiffLib_c(TestPatienceDiffLib):

    _test_needs_features = [features.compiled_patiencediff_feature]

    def setUp(self):
        super(TestPatienceDiffLib_c, self).setUp()
        from breezy import _patiencediff_c
        self._unique_lcs = _patiencediff_c.unique_lcs_c
        self._recurse_matches = _patiencediff_c.recurse_matches_c
        self._PatienceSequenceMatcher = \
            _patiencediff_c.PatienceSequenceMatcher_c

    def test_unhashable(self):
        """We should get a proper exception here."""
        # We need to be able to hash items in the sequence, lists are
        # unhashable, and thus cannot be diffed
        e = self.assertRaises(TypeError, self._PatienceSequenceMatcher,
                              None, [[]], [])
        e = self.assertRaises(TypeError, self._PatienceSequenceMatcher,
                              None, ['valid', []], [])
        e = self.assertRaises(TypeError, self._PatienceSequenceMatcher,
                              None, ['valid'], [[]])
        e = self.assertRaises(TypeError, self._PatienceSequenceMatcher,
                              None, ['valid'], ['valid', []])


class TestPatienceDiffLibFiles(tests.TestCaseInTempDir):

    def setUp(self):
        super(TestPatienceDiffLibFiles, self).setUp()
        self._PatienceSequenceMatcher = \
            _patiencediff_py.PatienceSequenceMatcher_py

    def test_patience_unified_diff_files(self):
        txt_a = [b'hello there\n',
                 b'world\n',
                 b'how are you today?\n']
        txt_b = [b'hello there\n',
                 b'how are you today?\n']
        with open('a1', 'wb') as f:
            f.writelines(txt_a)
        with open('b1', 'wb') as f:
            f.writelines(txt_b)

        unified_diff_files = patiencediff.unified_diff_files
        psm = self._PatienceSequenceMatcher
        self.assertEqual([b'--- a1\n',
                          b'+++ b1\n',
                          b'@@ -1,3 +1,2 @@\n',
                          b' hello there\n',
                          b'-world\n',
                          b' how are you today?\n',
                          ], list(unified_diff_files(b'a1', b'b1',
                                                     sequencematcher=psm)))

        txt_a = [x + '\n' for x in 'abcdefghijklmnop']
        txt_b = [x + '\n' for x in 'abcdefxydefghijklmnop']
        with open('a2', 'wt') as f:
            f.writelines(txt_a)
        with open('b2', 'wt') as f:
            f.writelines(txt_b)

        # This is the result with LongestCommonSubstring matching
        self.assertEqual([b'--- a2\n',
                          b'+++ b2\n',
                          b'@@ -1,6 +1,11 @@\n',
                          b' a\n',
                          b' b\n',
                          b' c\n',
                          b'+d\n',
                          b'+e\n',
                          b'+f\n',
                          b'+x\n',
                          b'+y\n',
                          b' d\n',
                          b' e\n',
                          b' f\n'], list(unified_diff_files(b'a2', b'b2')))

        # And the patience diff
        self.assertEqual([b'--- a2\n',
                          b'+++ b2\n',
                          b'@@ -4,6 +4,11 @@\n',
                          b' d\n',
                          b' e\n',
                          b' f\n',
                          b'+x\n',
                          b'+y\n',
                          b'+d\n',
                          b'+e\n',
                          b'+f\n',
                          b' g\n',
                          b' h\n',
                          b' i\n'],
                         list(unified_diff_files(b'a2', b'b2',
                                                 sequencematcher=psm)))


class TestPatienceDiffLibFiles_c(TestPatienceDiffLibFiles):

    _test_needs_features = [features.compiled_patiencediff_feature]

    def setUp(self):
        super(TestPatienceDiffLibFiles_c, self).setUp()
        from breezy import _patiencediff_c
        self._PatienceSequenceMatcher = \
            _patiencediff_c.PatienceSequenceMatcher_c


class TestUsingCompiledIfAvailable(tests.TestCase):

    def test_PatienceSequenceMatcher(self):
        if features.compiled_patiencediff_feature.available():
            from breezy._patiencediff_c import PatienceSequenceMatcher_c
            self.assertIs(PatienceSequenceMatcher_c,
                          patiencediff.PatienceSequenceMatcher)
        else:
            from breezy._patiencediff_py import PatienceSequenceMatcher_py
            self.assertIs(PatienceSequenceMatcher_py,
                          patiencediff.PatienceSequenceMatcher)

    def test_unique_lcs(self):
        if features.compiled_patiencediff_feature.available():
            from breezy._patiencediff_c import unique_lcs_c
            self.assertIs(unique_lcs_c,
                          patiencediff.unique_lcs)
        else:
            from breezy._patiencediff_py import unique_lcs_py
            self.assertIs(unique_lcs_py,
                          patiencediff.unique_lcs)

    def test_recurse_matches(self):
        if features.compiled_patiencediff_feature.available():
            from breezy._patiencediff_c import recurse_matches_c
            self.assertIs(recurse_matches_c,
                          patiencediff.recurse_matches)
        else:
            from breezy._patiencediff_py import recurse_matches_py
            self.assertIs(recurse_matches_py,
                          patiencediff.recurse_matches)


class TestDiffFromTool(tests.TestCaseWithTransport):

    def test_from_string(self):
        diff_obj = diff.DiffFromTool.from_string('diff', None, None, None)
        self.addCleanup(diff_obj.finish)
        self.assertEqual(['diff', '@old_path', '@new_path'],
                         diff_obj.command_template)

    def test_from_string_u5(self):
        diff_obj = diff.DiffFromTool.from_string('diff "-u 5"',
                                                 None, None, None)
        self.addCleanup(diff_obj.finish)
        self.assertEqual(['diff', '-u 5', '@old_path', '@new_path'],
                         diff_obj.command_template)
        self.assertEqual(['diff', '-u 5', 'old-path', 'new-path'],
                         diff_obj._get_command('old-path', 'new-path'))

    def test_from_string_path_with_backslashes(self):
        self.requireFeature(features.backslashdir_feature)
        tool = 'C:\\Tools\\Diff.exe'
        diff_obj = diff.DiffFromTool.from_string(tool, None, None, None)
        self.addCleanup(diff_obj.finish)
        self.assertEqual(['C:\\Tools\\Diff.exe', '@old_path', '@new_path'],
                         diff_obj.command_template)
        self.assertEqual(['C:\\Tools\\Diff.exe', 'old-path', 'new-path'],
                         diff_obj._get_command('old-path', 'new-path'))

    def test_execute(self):
        output = BytesIO()
        diff_obj = diff.DiffFromTool([sys.executable, '-c',
                                      'print("@old_path @new_path")'],
                                     None, None, output)
        self.addCleanup(diff_obj.finish)
        diff_obj._execute('old', 'new')
        self.assertEqual(output.getvalue().rstrip(), b'old new')

    def test_execute_missing(self):
        diff_obj = diff.DiffFromTool(['a-tool-which-is-unlikely-to-exist'],
                                     None, None, None)
        self.addCleanup(diff_obj.finish)
        e = self.assertRaises(errors.ExecutableMissing, diff_obj._execute,
                              'old', 'new')
        self.assertEqual('a-tool-which-is-unlikely-to-exist could not be found'
                         ' on this machine', str(e))

    def test_prepare_files_creates_paths_readable_by_windows_tool(self):
        self.requireFeature(features.AttribFeature)
        output = BytesIO()
        tree = self.make_branch_and_tree('tree')
        self.build_tree_contents([('tree/file', b'content')])
        tree.add('file', b'file-id')
        tree.commit('old tree')
        tree.lock_read()
        self.addCleanup(tree.unlock)
        basis_tree = tree.basis_tree()
        basis_tree.lock_read()
        self.addCleanup(basis_tree.unlock)
        diff_obj = diff.DiffFromTool([sys.executable, '-c',
                                      'print "@old_path @new_path"'],
                                     basis_tree, tree, output)
        diff_obj._prepare_files('file', 'file', file_id=b'file-id')
        # The old content should be readonly
        self.assertReadableByAttrib(diff_obj._root, 'old\\file',
                                    r'R.*old\\file$')
        # The new content should use the tree object, not a 'new' file anymore
        self.assertEndsWith(tree.basedir, 'work/tree')
        self.assertReadableByAttrib(tree.basedir, 'file', r'work\\tree\\file$')

    def assertReadableByAttrib(self, cwd, relpath, regex):
        proc = subprocess.Popen(['attrib', relpath],
                                stdout=subprocess.PIPE,
                                cwd=cwd)
        (result, err) = proc.communicate()
        self.assertContainsRe(result.replace('\r\n', '\n'), regex)

    def test_prepare_files(self):
        output = BytesIO()
        tree = self.make_branch_and_tree('tree')
        self.build_tree_contents([('tree/oldname', b'oldcontent')])
        self.build_tree_contents([('tree/oldname2', b'oldcontent2')])
        tree.add('oldname', b'file-id')
        tree.add('oldname2', b'file2-id')
        # Earliest allowable date on FAT32 filesystems is 1980-01-01
        tree.commit('old tree', timestamp=315532800)
        tree.rename_one('oldname', 'newname')
        tree.rename_one('oldname2', 'newname2')
        self.build_tree_contents([('tree/newname', b'newcontent')])
        self.build_tree_contents([('tree/newname2', b'newcontent2')])
        old_tree = tree.basis_tree()
        old_tree.lock_read()
        self.addCleanup(old_tree.unlock)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        diff_obj = diff.DiffFromTool([sys.executable, '-c',
                                      'print "@old_path @new_path"'],
                                     old_tree, tree, output)
        self.addCleanup(diff_obj.finish)
        self.assertContainsRe(diff_obj._root, 'brz-diff-[^/]*')
        old_path, new_path = diff_obj._prepare_files(
            'oldname', 'newname', file_id=b'file-id')
        self.assertContainsRe(old_path, 'old/oldname$')
        self.assertEqual(315532800, os.stat(old_path).st_mtime)
        self.assertContainsRe(new_path, 'tree/newname$')
        self.assertFileEqual(b'oldcontent', old_path)
        self.assertFileEqual(b'newcontent', new_path)
        if osutils.host_os_dereferences_symlinks():
            self.assertTrue(os.path.samefile('tree/newname', new_path))
        # make sure we can create files with the same parent directories
        diff_obj._prepare_files('oldname2', 'newname2', file_id=b'file2-id')


class TestDiffFromToolEncodedFilename(tests.TestCaseWithTransport):

    def test_encodable_filename(self):
        # Just checks file path for external diff tool.
        # We cannot change CPython's internal encoding used by os.exec*.
        diffobj = diff.DiffFromTool(['dummy', '@old_path', '@new_path'],
                                    None, None, None)
        for _, scenario in EncodingAdapter.encoding_scenarios:
            encoding = scenario['encoding']
            dirname = scenario['info']['directory']
            filename = scenario['info']['filename']

            self.overrideAttr(diffobj, '_fenc', lambda: encoding)
            relpath = dirname + u'/' + filename
            fullpath = diffobj._safe_filename('safe', relpath)
            self.assertEqual(fullpath,
                             fullpath.encode(encoding).decode(encoding))
            self.assertTrue(fullpath.startswith(diffobj._root + '/safe'))

    def test_unencodable_filename(self):
        diffobj = diff.DiffFromTool(['dummy', '@old_path', '@new_path'],
                                    None, None, None)
        for _, scenario in EncodingAdapter.encoding_scenarios:
            encoding = scenario['encoding']
            dirname = scenario['info']['directory']
            filename = scenario['info']['filename']

            if encoding == 'iso-8859-1':
                encoding = 'iso-8859-2'
            else:
                encoding = 'iso-8859-1'

            self.overrideAttr(diffobj, '_fenc', lambda: encoding)
            relpath = dirname + u'/' + filename
            fullpath = diffobj._safe_filename('safe', relpath)
            self.assertEqual(fullpath,
                             fullpath.encode(encoding).decode(encoding))
            self.assertTrue(fullpath.startswith(diffobj._root + '/safe'))


class TestGetTreesAndBranchesToDiffLocked(tests.TestCaseWithTransport):

    def call_gtabtd(self, path_list, revision_specs, old_url, new_url):
        """Call get_trees_and_branches_to_diff_locked."""
        return diff.get_trees_and_branches_to_diff_locked(
            path_list, revision_specs, old_url, new_url, self.addCleanup)

    def test_basic(self):
        tree = self.make_branch_and_tree('tree')
        (old_tree, new_tree,
         old_branch, new_branch,
         specific_files, extra_trees) = self.call_gtabtd(
             ['tree'], None, None, None)

        self.assertIsInstance(old_tree, revisiontree.RevisionTree)
        self.assertEqual(_mod_revision.NULL_REVISION,
                         old_tree.get_revision_id())
        self.assertEqual(tree.basedir, new_tree.basedir)
        self.assertEqual(tree.branch.base, old_branch.base)
        self.assertEqual(tree.branch.base, new_branch.base)
        self.assertIs(None, specific_files)
        self.assertIs(None, extra_trees)

    def test_with_rev_specs(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree_contents([('tree/file', b'oldcontent')])
        tree.add('file', b'file-id')
        tree.commit('old tree', timestamp=0, rev_id=b"old-id")
        self.build_tree_contents([('tree/file', b'newcontent')])
        tree.commit('new tree', timestamp=0, rev_id=b"new-id")

        revisions = [revisionspec.RevisionSpec.from_string('1'),
                     revisionspec.RevisionSpec.from_string('2')]
        (old_tree, new_tree,
         old_branch, new_branch,
         specific_files, extra_trees) = self.call_gtabtd(
            ['tree'], revisions, None, None)

        self.assertIsInstance(old_tree, revisiontree.RevisionTree)
        self.assertEqual(b"old-id", old_tree.get_revision_id())
        self.assertIsInstance(new_tree, revisiontree.RevisionTree)
        self.assertEqual(b"new-id", new_tree.get_revision_id())
        self.assertEqual(tree.branch.base, old_branch.base)
        self.assertEqual(tree.branch.base, new_branch.base)
        self.assertIs(None, specific_files)
        self.assertEqual(tree.basedir, extra_trees[0].basedir)
