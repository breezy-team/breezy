# Copyright (C) 2005, 2006, 2007, 2009 Canonical Ltd
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


"""Black-box tests for bzr log."""

import os
import re

from bzrlib import (
    osutils,
    tests,
    )
from bzrlib.tests import test_log


class TestLog(tests.TestCaseWithTransport):

    def setUp(self):
        super(TestLog, self).setUp()
        self.timezone = 0 # UTC
        self.timestamp = 1132617600 # Mon 2005-11-22 00:00:00 +0000

    def make_minimal_branch(self, path='.', format=None):
        tree = self.make_branch_and_tree(path, format=format)
        self.build_tree([path + '/hello.txt'])
        tree.add('hello.txt')
        tree.commit(message='message1')
        return tree

    def make_linear_branch(self, path='.', format=None):
        tree = self.make_branch_and_tree(path, format=format)
        self.build_tree(
            [path + '/hello.txt', path + '/goodbye.txt', path + '/meep.txt'])
        tree.add('hello.txt')
        tree.commit(message='message1')
        tree.add('goodbye.txt')
        tree.commit(message='message2')
        tree.add('meep.txt')
        tree.commit(message='message3')
        return tree

    def make_merged_branch(self, path='.', format=None):
        tree = self.make_linear_branch(path, format)
        tree2 = tree.bzrdir.sprout('tree2',
            revision_id=tree.branch.get_rev_id(1)).open_workingtree()
        tree2.commit(message='tree2 message2')
        tree2.commit(message='tree2 message3')
        tree.merge_from_branch(tree2.branch)
        tree.commit(message='merge')
        return tree

    def assertRevnos(self, log, must_have=(), must_not_have=()):
        """Check if revnos are in or not in the log output"""
        for revno in must_have:
            self.assertTrue(('revno: %s\n' % revno) in log,
                'Does not contain expected revno %s' % revno)
        for revno in must_not_have:
            self.assertFalse(('revno: %s\n' % revno) in log,
                'Contains unexpected revno %s' % revno)

    def commit_options(self):
        """Use some mostly fixed values for commits to simplify tests.

        Tests can use this function to get some commit attributes. The time
        stamp is incremented at each commit.
        """
        self.timestamp += 1 # 1 second between each commit
        return dict(committer='Lorem Ipsum <joe@foo.com>',
                 timezone=self.timezone,
                 timestamp=self.timestamp,
                 )

    def check_log(self, expected, args, working_dir='level0'):
        out, err = self.run_bzr(['log', '--timezone', 'utc'] + args,
                                working_dir=working_dir)
        self.assertEqual('', err)
        self.assertEqualDiff(expected, test_log.normalize_log(out))


class TestLogRevSpecs(TestLog):

    def test_log_null_end_revspec(self):
        self.make_linear_branch()
        log = self.run_bzr(['log'])[0]
        self.assertTrue('revno: 1\n' in log)
        self.assertTrue('revno: 2\n' in log)
        self.assertTrue('revno: 3\n' in log)
        self.assertTrue('message:\n  message1\n' in log)
        self.assertTrue('message:\n  message2\n' in log)
        self.assertTrue('message:\n  message3\n' in log)

        full_log = self.run_bzr(['log'])[0]
        log = self.run_bzr("log -r 1..")[0]
        self.assertEqualDiff(log, full_log)

    def test_log_null_begin_revspec(self):
        self.make_linear_branch()
        full_log = self.run_bzr(['log'])[0]
        log = self.run_bzr("log -r ..3")[0]
        self.assertEqualDiff(full_log, log)

    def test_log_null_both_revspecs(self):
        self.make_linear_branch()
        full_log = self.run_bzr(['log'])[0]
        log = self.run_bzr("log -r ..")[0]
        self.assertEqualDiff(full_log, log)

    def test_log_zero_revspec(self):
        self.make_minimal_branch()
        self.run_bzr_error(['bzr: ERROR: Logging revision 0 is invalid.'],
                           ['log', '-r0'])

    def test_log_zero_begin_revspec(self):
        self.make_linear_branch()
        self.run_bzr_error(['bzr: ERROR: Logging revision 0 is invalid.'],
                           ['log', '-r0..2'])

    def test_log_zero_end_revspec(self):
        self.make_linear_branch()
        self.run_bzr_error(['bzr: ERROR: Logging revision 0 is invalid.'],
                           ['log', '-r-2..0'])

    def test_log_negative_begin_revspec_full_log(self):
        self.make_linear_branch()
        full_log = self.run_bzr(['log'])[0]
        log = self.run_bzr("log -r -3..")[0]
        self.assertEqualDiff(full_log, log)

    def test_log_negative_both_revspec_full_log(self):
        self.make_linear_branch()
        full_log = self.run_bzr(['log'])[0]
        log = self.run_bzr("log -r -3..-1")[0]
        self.assertEqualDiff(full_log, log)

    def test_log_negative_both_revspec_partial(self):
        self.make_linear_branch()
        log = self.run_bzr("log -r -3..-2")[0]
        self.assertTrue('revno: 1\n' in log)
        self.assertTrue('revno: 2\n' in log)
        self.assertTrue('revno: 3\n' not in log)

    def test_log_negative_begin_revspec(self):
        self.make_linear_branch()
        log = self.run_bzr("log -r -2..")[0]
        self.assertTrue('revno: 1\n' not in log)
        self.assertTrue('revno: 2\n' in log)
        self.assertTrue('revno: 3\n' in log)

    def test_log_positive_revspecs(self):
        self.make_linear_branch()
        full_log = self.run_bzr(['log'])[0]
        log = self.run_bzr("log -r 1..3")[0]
        self.assertEqualDiff(full_log, log)

    def test_log_dotted_revspecs(self):
        self.make_merged_branch()
        log = self.run_bzr("log -n0 -r 1..1.1.1")[0]
        self.assertRevnos(log, (1, '1.1.1'), (2, 3, '1.1.2', 4))

    def test_log_reversed_revspecs(self):
        self.make_linear_branch()
        self.run_bzr_error(('bzr: ERROR: Start revision must be older than '
                            'the end revision.\n',),
                           ['log', '-r3..1'])

    def test_log_reversed_dotted_revspecs(self):
        self.make_merged_branch()
        self.run_bzr_error(('bzr: ERROR: Start revision not found in '
                            'left-hand history of end revision.\n',),
                           "log -r 1.1.1..1")

    def test_log_revno_n_path(self):
        self.make_linear_branch('branch1')
        self.make_linear_branch('branch2')
        # Swapped revisions
        self.run_bzr("log -r revno:2:branch1..revno:3:branch2", retcode=3)[0]
        # Correct order
        log = self.run_bzr("log -r revno:1:branch2..revno:3:branch2")[0]
        full_log = self.run_bzr(['log'], working_dir='branch2')[0]
        self.assertEqualDiff(full_log, log)
        log = self.run_bzr("log -r revno:1:branch2")[0]
        self.assertTrue('revno: 1\n' in log)
        self.assertTrue('revno: 2\n' not in log)
        self.assertTrue('branch nick: branch2\n' in log)
        self.assertTrue('branch nick: branch1\n' not in log)

    def test_log_nonexistent_revno(self):
        self.make_minimal_branch()
        (out, err) = self.run_bzr_error(
            ["bzr: ERROR: Requested revision: '1234' "
             "does not exist in branch:"],
            ['log', '-r1234'])

    def test_log_nonexistent_dotted_revno(self):
        self.make_minimal_branch()
        (out, err) = self.run_bzr_error(
            ["bzr: ERROR: Requested revision: '123.123' "
             "does not exist in branch:"],
            ['log',  '-r123.123'])

    def test_log_change_revno(self):
        self.make_linear_branch()
        expected_log = self.run_bzr("log -r 1")[0]
        log = self.run_bzr("log -c 1")[0]
        self.assertEqualDiff(expected_log, log)

    def test_log_change_nonexistent_revno(self):
        self.make_minimal_branch()
        (out, err) = self.run_bzr_error(
            ["bzr: ERROR: Requested revision: '1234' "
             "does not exist in branch:"],
            ['log',  '-c1234'])

    def test_log_change_nonexistent_dotted_revno(self):
        self.make_minimal_branch()
        (out, err) = self.run_bzr_error(
            ["bzr: ERROR: Requested revision: '123.123' "
             "does not exist in branch:"],
            ['log', '-c123.123'])

    def test_log_change_single_revno_only(self):
        self.make_minimal_branch()
        self.run_bzr_error(['bzr: ERROR: Option --change does not'
                           ' accept revision ranges'],
                           ['log', '--change', '2..3'])

    def test_log_change_incompatible_with_revision(self):
        self.run_bzr_error(['bzr: ERROR: --revision and --change'
                           ' are mutually exclusive'],
                           ['log', '--change', '2', '--revision', '3'])

    def test_log_nonexistent_file(self):
        self.make_minimal_branch()
        # files that don't exist in either the basis tree or working tree
        # should give an error
        out, err = self.run_bzr('log does-not-exist', retcode=3)
        self.assertContainsRe(err,
                              'Path unknown at end or start of revision range: '
                              'does-not-exist')

    def test_log_with_tags(self):
        tree = self.make_linear_branch(format='dirstate-tags')
        branch = tree.branch
        branch.tags.set_tag('tag1', branch.get_rev_id(1))
        branch.tags.set_tag('tag1.1', branch.get_rev_id(1))
        branch.tags.set_tag('tag3', branch.last_revision())

        log = self.run_bzr("log -r-1")[0]
        self.assertTrue('tags: tag3' in log)

        log = self.run_bzr("log -r1")[0]
        # I guess that we can't know the order of tags in the output
        # since dicts are unordered, need to check both possibilities
        self.assertContainsRe(log, r'tags: (tag1, tag1\.1|tag1\.1, tag1)')

    def test_merged_log_with_tags(self):
        branch1_tree = self.make_linear_branch('branch1',
                                               format='dirstate-tags')
        branch1 = branch1_tree.branch
        branch2_tree = branch1_tree.bzrdir.sprout('branch2').open_workingtree()
        branch1_tree.commit(message='foobar', allow_pointless=True)
        branch1.tags.set_tag('tag1', branch1.last_revision())
        # tags don't propagate if we don't merge
        self.run_bzr('merge ../branch1', working_dir='branch2')
        branch2_tree.commit(message='merge branch 1')
        log = self.run_bzr("log -n0 -r-1", working_dir='branch2')[0]
        self.assertContainsRe(log, r'    tags: tag1')
        log = self.run_bzr("log -n0 -r3.1.1", working_dir='branch2')[0]
        self.assertContainsRe(log, r'tags: tag1')

    def test_log_limit(self):
        tree = self.make_branch_and_tree('.')
        # We want more commits than our batch size starts at
        for pos in range(10):
            tree.commit("%s" % pos)
        log = self.run_bzr("log --limit 2")[0]
        self.assertNotContainsRe(log, r'revno: 1\n')
        self.assertNotContainsRe(log, r'revno: 2\n')
        self.assertNotContainsRe(log, r'revno: 3\n')
        self.assertNotContainsRe(log, r'revno: 4\n')
        self.assertNotContainsRe(log, r'revno: 5\n')
        self.assertNotContainsRe(log, r'revno: 6\n')
        self.assertNotContainsRe(log, r'revno: 7\n')
        self.assertNotContainsRe(log, r'revno: 8\n')
        self.assertContainsRe(log, r'revno: 9\n')
        self.assertContainsRe(log, r'revno: 10\n')

    def test_log_limit_short(self):
        self.make_linear_branch()
        log = self.run_bzr("log -l 2")[0]
        self.assertNotContainsRe(log, r'revno: 1\n')
        self.assertContainsRe(log, r'revno: 2\n')
        self.assertContainsRe(log, r'revno: 3\n')

    def test_log_bad_message_re(self):
        """Bad --message argument gives a sensible message
        
        See https://bugs.launchpad.net/bzr/+bug/251352
        """
        self.make_minimal_branch()
        out, err = self.run_bzr(['log', '-m', '*'], retcode=3)
        self.assertEqual("bzr: ERROR: Invalid regular expression"
            " in log message filter"
            ": '*'"
            ": nothing to repeat\n", err)
        self.assertEqual('', out)


class TestLogTimeZone(TestLog):

    def test_log_unsupported_timezone(self):
        self.make_linear_branch()
        self.run_bzr_error(['bzr: ERROR: Unsupported timezone format "foo", '
                            'options are "utc", "original", "local".'],
                           ['log', '--timezone', 'foo'])


class TestLogVerbose(TestLog):

    def setUp(self):
        super(TestLogVerbose, self).setUp()
        self.make_minimal_branch()

    def assertUseShortDeltaFormat(self, cmd):
        log = self.run_bzr(cmd)[0]
        # Check that we use the short status format
        self.assertContainsRe(log, '(?m)^\s*A  hello.txt$')
        self.assertNotContainsRe(log, '(?m)^\s*added:$')

    def assertUseLongDeltaFormat(self, cmd):
        log = self.run_bzr(cmd)[0]
        # Check that we use the long status format
        self.assertNotContainsRe(log, '(?m)^\s*A  hello.txt$')
        self.assertContainsRe(log, '(?m)^\s*added:$')

    def test_log_short_verbose(self):
        self.assertUseShortDeltaFormat(['log', '--short', '-v'])

    def test_log_short_verbose_verbose(self):
        self.assertUseLongDeltaFormat(['log', '--short', '-vv'])

    def test_log_long_verbose(self):
        # Check that we use the long status format, ignoring the verbosity
        # level
        self.assertUseLongDeltaFormat(['log', '--long', '-v'])

    def test_log_long_verbose_verbose(self):
        # Check that we use the long status format, ignoring the verbosity
        # level
        self.assertUseLongDeltaFormat(['log', '--long', '-vv'])


class TestLogMerges(TestLog):

    def setUp(self):
        super(TestLogMerges, self).setUp()
        self.make_branches_with_merges()

    def make_branches_with_merges(self):
        level0 = self.make_branch_and_tree('level0')
        level0.commit(message='in branch level0', **self.commit_options())

        level1 = level0.bzrdir.sprout('level1').open_workingtree()
        level1.commit(message='in branch level1', **self.commit_options())

        level2 = level1.bzrdir.sprout('level2').open_workingtree()
        level2.commit(message='in branch level2', **self.commit_options())

        level1.merge_from_branch(level2.branch)
        level1.commit(message='merge branch level2', **self.commit_options())

        level0.merge_from_branch(level1.branch)
        level0.commit(message='merge branch level1', **self.commit_options())

    def test_merges_are_indented_by_level(self):
        expected = """\
------------------------------------------------------------
revno: 2 [merge]
committer: Lorem Ipsum <test@example.com>
branch nick: level0
timestamp: Just now
message:
  merge branch level1
    ------------------------------------------------------------
    revno: 1.1.2 [merge]
    committer: Lorem Ipsum <test@example.com>
    branch nick: level1
    timestamp: Just now
    message:
      merge branch level2
        ------------------------------------------------------------
        revno: 1.2.1
        committer: Lorem Ipsum <test@example.com>
        branch nick: level2
        timestamp: Just now
        message:
          in branch level2
    ------------------------------------------------------------
    revno: 1.1.1
    committer: Lorem Ipsum <test@example.com>
    branch nick: level1
    timestamp: Just now
    message:
      in branch level1
------------------------------------------------------------
revno: 1
committer: Lorem Ipsum <test@example.com>
branch nick: level0
timestamp: Just now
message:
  in branch level0
"""
        self.check_log(expected, ['-n0'])

    def test_force_merge_revisions_off(self):
        expected = """\
------------------------------------------------------------
revno: 2 [merge]
committer: Lorem Ipsum <test@example.com>
branch nick: level0
timestamp: Just now
message:
  merge branch level1
------------------------------------------------------------
revno: 1
committer: Lorem Ipsum <test@example.com>
branch nick: level0
timestamp: Just now
message:
  in branch level0
"""
        self.check_log(expected, ['--long', '-n1'])

    def test_force_merge_revisions_on(self):
        expected = """\
    2 Lorem Ipsum\t2005-11-22 [merge]
      merge branch level1

          1.1.2 Lorem Ipsum\t2005-11-22 [merge]
                merge branch level2

              1.2.1 Lorem Ipsum\t2005-11-22
                    in branch level2

          1.1.1 Lorem Ipsum\t2005-11-22
                in branch level1

    1 Lorem Ipsum\t2005-11-22
      in branch level0

"""
        self.check_log(expected, ['--short', '-n0'])

    def test_include_merges(self):
        # Confirm --include-merges gives the same output as -n0
        out_im, err_im = self.run_bzr('log --include-merges',
                                      working_dir='level0')
        out_n0, err_n0 = self.run_bzr('log -n0', working_dir='level0')
        self.assertEqual('', err_im)
        self.assertEqual('', err_n0)
        self.assertEqual(out_im, out_n0)

    def test_force_merge_revisions_N(self):
        expected = """\
    2 Lorem Ipsum\t2005-11-22 [merge]
      merge branch level1

          1.1.2 Lorem Ipsum\t2005-11-22 [merge]
                merge branch level2

          1.1.1 Lorem Ipsum\t2005-11-22
                in branch level1

    1 Lorem Ipsum\t2005-11-22
      in branch level0

"""
        self.check_log(expected, ['--short', '-n2'])

    def test_merges_single_merge_rev(self):
        expected = """\
------------------------------------------------------------
revno: 1.1.2 [merge]
committer: Lorem Ipsum <test@example.com>
branch nick: level1
timestamp: Just now
message:
  merge branch level2
    ------------------------------------------------------------
    revno: 1.2.1
    committer: Lorem Ipsum <test@example.com>
    branch nick: level2
    timestamp: Just now
    message:
      in branch level2
"""
        self.check_log(expected, ['-n0', '-r1.1.2'])

    def test_merges_partial_range(self):
        expected = """\
------------------------------------------------------------
revno: 1.1.2 [merge]
committer: Lorem Ipsum <test@example.com>
branch nick: level1
timestamp: Just now
message:
  merge branch level2
    ------------------------------------------------------------
    revno: 1.2.1
    committer: Lorem Ipsum <test@example.com>
    branch nick: level2
    timestamp: Just now
    message:
      in branch level2
------------------------------------------------------------
revno: 1.1.1
committer: Lorem Ipsum <test@example.com>
branch nick: level1
timestamp: Just now
message:
  in branch level1
"""
        self.check_log(expected, ['-n0', '-r1.1.1..1.1.2'])


class TestLogDiff(TestLog):

    def setUp(self):
        super(TestLogDiff, self).setUp()
        self.make_branch_with_diffs()

    def make_branch_with_diffs(self):
        level0 = self.make_branch_and_tree('level0')
        self.build_tree(['level0/file1', 'level0/file2'])
        level0.add('file1')
        level0.add('file2')
        level0.commit(message='in branch level0', **self.commit_options())

        level1 = level0.bzrdir.sprout('level1').open_workingtree()
        self.build_tree_contents([('level1/file2', 'hello\n')])
        level1.commit(message='in branch level1', **self.commit_options())
        level0.merge_from_branch(level1.branch)
        level0.commit(message='merge branch level1', **self.commit_options())

    def test_log_show_diff_long_with_merges(self):
        out,err = self.run_bzr('log -p -n0')
        self.assertEqual('', err)
        log = test_log.normalize_log(out)
        expected = """\
------------------------------------------------------------
revno: 2 [merge]
committer: Lorem Ipsum <test@example.com>
branch nick: level0
timestamp: Just now
message:
  merge branch level1
diff:
=== modified file 'file2'
--- file2\t2005-11-22 00:00:01 +0000
+++ file2\t2005-11-22 00:00:02 +0000
@@ -1,1 +1,1 @@
-contents of level0/file2
+hello
    ------------------------------------------------------------
    revno: 1.1.1
    committer: Lorem Ipsum <test@example.com>
    branch nick: level1
    timestamp: Just now
    message:
      in branch level1
    diff:
    === modified file 'file2'
    --- file2\t2005-11-22 00:00:01 +0000
    +++ file2\t2005-11-22 00:00:02 +0000
    @@ -1,1 +1,1 @@
    -contents of level0/file2
    +hello
------------------------------------------------------------
revno: 1
committer: Lorem Ipsum <test@example.com>
branch nick: level0
timestamp: Just now
message:
  in branch level0
diff:
=== added file 'file1'
--- file1\t1970-01-01 00:00:00 +0000
+++ file1\t2005-11-22 00:00:01 +0000
@@ -0,0 +1,1 @@
+contents of level0/file1

=== added file 'file2'
--- file2\t1970-01-01 00:00:00 +0000
+++ file2\t2005-11-22 00:00:01 +0000
@@ -0,0 +1,1 @@
+contents of level0/file2
"""
        self.check_log(expected, ['-p', '-n0'])

    def test_log_show_diff_short(self):
        expected = """\
    2 Lorem Ipsum\t2005-11-22 [merge]
      merge branch level1
      === modified file 'file2'
      --- file2\t2005-11-22 00:00:01 +0000
      +++ file2\t2005-11-22 00:00:02 +0000
      @@ -1,1 +1,1 @@
      -contents of level0/file2
      +hello

    1 Lorem Ipsum\t2005-11-22
      in branch level0
      === added file 'file1'
      --- file1\t1970-01-01 00:00:00 +0000
      +++ file1\t2005-11-22 00:00:01 +0000
      @@ -0,0 +1,1 @@
      +contents of level0/file1
\x20\x20\x20\x20\x20\x20
      === added file 'file2'
      --- file2\t1970-01-01 00:00:00 +0000
      +++ file2\t2005-11-22 00:00:01 +0000
      @@ -0,0 +1,1 @@
      +contents of level0/file2

Use --include-merges or -n0 to see merged revisions.
"""
        self.check_log(expected, ['-p', '--short'])

    def test_log_show_diff_line(self):
        # Not supported by this formatter so expect plain output
        expected = """\
2: Lorem Ipsum 2005-11-22 [merge] merge branch level1
1: Lorem Ipsum 2005-11-22 in branch level0
"""
        self.check_log(expected, ['-p', '--line'])

    def test_log_show_diff_file1(self):
        """Only the diffs for the given file are to be shown"""
        expected = """\
    1 Lorem Ipsum\t2005-11-22
      in branch level0
      === added file 'file1'
      --- file1\t1970-01-01 00:00:00 +0000
      +++ file1\t2005-11-22 00:00:01 +0000
      @@ -0,0 +1,1 @@
      +contents of level0/file1

"""
        self.check_log(expected, ['-p', '--short', 'file1'])

    def test_log_show_diff_file2(self):
        """Only the diffs for the given file are to be shown"""
        expected = """\
    2 Lorem Ipsum\t2005-11-22 [merge]
      merge branch level1
      === modified file 'file2'
      --- file2\t2005-11-22 00:00:01 +0000
      +++ file2\t2005-11-22 00:00:02 +0000
      @@ -1,1 +1,1 @@
      -contents of level0/file2
      +hello

    1 Lorem Ipsum\t2005-11-22
      in branch level0
      === added file 'file2'
      --- file2\t1970-01-01 00:00:00 +0000
      +++ file2\t2005-11-22 00:00:01 +0000
      @@ -0,0 +1,1 @@
      +contents of level0/file2

Use --include-merges or -n0 to see merged revisions.
"""
        self.check_log(expected, ['-p', '--short', 'file2'])


class TestLogUnicodeDiff(TestLog):

    def test_log_show_diff_non_ascii(self):
        # Smoke test for bug #328007 UnicodeDecodeError on 'log -p'
        message = u'Message with \xb5'
        body = 'Body with \xb5\n'
        wt = self.make_branch_and_tree('.')
        self.build_tree_contents([('foo', body)])
        wt.add('foo')
        wt.commit(message=message)
        # check that command won't fail with unicode error
        # don't care about exact output because we have other tests for this
        out,err = self.run_bzr('log -p --long')
        self.assertNotEqual('', out)
        self.assertEqual('', err)
        out,err = self.run_bzr('log -p --short')
        self.assertNotEqual('', out)
        self.assertEqual('', err)
        out,err = self.run_bzr('log -p --line')
        self.assertNotEqual('', out)
        self.assertEqual('', err)


class TestLogEncodings(tests.TestCaseInTempDir):

    _mu = u'\xb5'
    _message = u'Message with \xb5'

    # Encodings which can encode mu
    good_encodings = [
        'utf-8',
        'latin-1',
        'iso-8859-1',
        'cp437', # Common windows encoding
        'cp1251', # Russian windows encoding
        'cp1258', # Common windows encoding
    ]
    # Encodings which cannot encode mu
    bad_encodings = [
        'ascii',
        'iso-8859-2',
        'koi8_r',
    ]

    def setUp(self):
        super(TestLogEncodings, self).setUp()
        self.user_encoding = osutils._cached_user_encoding
        def restore():
            osutils._cached_user_encoding = self.user_encoding
        self.addCleanup(restore)

    def create_branch(self):
        bzr = self.run_bzr
        bzr('init')
        open('a', 'wb').write('some stuff\n')
        bzr('add a')
        bzr(['commit', '-m', self._message])

    def try_encoding(self, encoding, fail=False):
        bzr = self.run_bzr
        if fail:
            self.assertRaises(UnicodeEncodeError,
                self._mu.encode, encoding)
            encoded_msg = self._message.encode(encoding, 'replace')
        else:
            encoded_msg = self._message.encode(encoding)

        old_encoding = osutils._cached_user_encoding
        # This test requires that 'run_bzr' uses the current
        # bzrlib, because we override user_encoding, and expect
        # it to be used
        try:
            osutils._cached_user_encoding = 'ascii'
            # We should be able to handle any encoding
            out, err = bzr('log', encoding=encoding)
            if not fail:
                # Make sure we wrote mu as we expected it to exist
                self.assertNotEqual(-1, out.find(encoded_msg))
                out_unicode = out.decode(encoding)
                self.assertNotEqual(-1, out_unicode.find(self._message))
            else:
                self.assertNotEqual(-1, out.find('Message with ?'))
        finally:
            osutils._cached_user_encoding = old_encoding

    def test_log_handles_encoding(self):
        self.create_branch()

        for encoding in self.good_encodings:
            self.try_encoding(encoding)

    def test_log_handles_bad_encoding(self):
        self.create_branch()

        for encoding in self.bad_encodings:
            self.try_encoding(encoding, fail=True)

    def test_stdout_encoding(self):
        bzr = self.run_bzr
        osutils._cached_user_encoding = "cp1251"

        bzr('init')
        self.build_tree(['a'])
        bzr('add a')
        bzr(['commit', '-m', u'\u0422\u0435\u0441\u0442'])
        stdout, stderr = self.run_bzr('log', encoding='cp866')

        message = stdout.splitlines()[-1]

        # explanation of the check:
        # u'\u0422\u0435\u0441\u0442' is word 'Test' in russian
        # in cp866  encoding this is string '\x92\xa5\xe1\xe2'
        # in cp1251 encoding this is string '\xd2\xe5\xf1\xf2'
        # This test should check that output of log command
        # encoded to sys.stdout.encoding
        test_in_cp866 = '\x92\xa5\xe1\xe2'
        test_in_cp1251 = '\xd2\xe5\xf1\xf2'
        # Make sure the log string is encoded in cp866
        self.assertEquals(test_in_cp866, message[2:])
        # Make sure the cp1251 string is not found anywhere
        self.assertEquals(-1, stdout.find(test_in_cp1251))


class TestLogFile(tests.TestCaseWithTransport):

    def test_log_local_branch_file(self):
        """We should be able to log files in local treeless branches"""
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/file'])
        tree.add('file')
        tree.commit('revision 1')
        tree.bzrdir.destroy_workingtree()
        self.run_bzr('log tree/file')

    def prepare_tree(self, complex=False):
        # The complex configuration includes deletes and renames
        tree = self.make_branch_and_tree('parent')
        self.build_tree(['parent/file1', 'parent/file2', 'parent/file3'])
        tree.add('file1')
        tree.commit('add file1')
        tree.add('file2')
        tree.commit('add file2')
        tree.add('file3')
        tree.commit('add file3')
        child_tree = tree.bzrdir.sprout('child').open_workingtree()
        self.build_tree_contents([('child/file2', 'hello')])
        child_tree.commit(message='branch 1')
        tree.merge_from_branch(child_tree.branch)
        tree.commit(message='merge child branch')
        if complex:
            tree.remove('file2')
            tree.commit('remove file2')
            tree.rename_one('file3', 'file4')
            tree.commit('file3 is now called file4')
            tree.remove('file1')
            tree.commit('remove file1')
        os.chdir('parent')

    def test_log_file(self):
        """The log for a particular file should only list revs for that file"""
        self.prepare_tree()
        log = self.run_bzr('log -n0 file1')[0]
        self.assertContainsRe(log, 'revno: 1\n')
        self.assertNotContainsRe(log, 'revno: 2\n')
        self.assertNotContainsRe(log, 'revno: 3\n')
        self.assertNotContainsRe(log, 'revno: 3.1.1\n')
        self.assertNotContainsRe(log, 'revno: 4 ')
        log = self.run_bzr('log -n0 file2')[0]
        self.assertNotContainsRe(log, 'revno: 1\n')
        self.assertContainsRe(log, 'revno: 2\n')
        self.assertNotContainsRe(log, 'revno: 3\n')
        self.assertContainsRe(log, 'revno: 3.1.1\n')
        self.assertContainsRe(log, 'revno: 4 ')
        log = self.run_bzr('log -n0 file3')[0]
        self.assertNotContainsRe(log, 'revno: 1\n')
        self.assertNotContainsRe(log, 'revno: 2\n')
        self.assertContainsRe(log, 'revno: 3\n')
        self.assertNotContainsRe(log, 'revno: 3.1.1\n')
        self.assertNotContainsRe(log, 'revno: 4 ')
        log = self.run_bzr('log -n0 -r3.1.1 file2')[0]
        self.assertNotContainsRe(log, 'revno: 1\n')
        self.assertNotContainsRe(log, 'revno: 2\n')
        self.assertNotContainsRe(log, 'revno: 3\n')
        self.assertContainsRe(log, 'revno: 3.1.1\n')
        self.assertNotContainsRe(log, 'revno: 4 ')
        log = self.run_bzr('log -n0 -r4 file2')[0]
        self.assertNotContainsRe(log, 'revno: 1\n')
        self.assertNotContainsRe(log, 'revno: 2\n')
        self.assertNotContainsRe(log, 'revno: 3\n')
        self.assertContainsRe(log, 'revno: 3.1.1\n')
        self.assertContainsRe(log, 'revno: 4 ')
        log = self.run_bzr('log -n0 -r3.. file2')[0]
        self.assertNotContainsRe(log, 'revno: 1\n')
        self.assertNotContainsRe(log, 'revno: 2\n')
        self.assertNotContainsRe(log, 'revno: 3\n')
        self.assertContainsRe(log, 'revno: 3.1.1\n')
        self.assertContainsRe(log, 'revno: 4 ')
        log = self.run_bzr('log -n0 -r..3 file2')[0]
        self.assertNotContainsRe(log, 'revno: 1\n')
        self.assertContainsRe(log, 'revno: 2\n')
        self.assertNotContainsRe(log, 'revno: 3\n')
        self.assertNotContainsRe(log, 'revno: 3.1.1\n')
        self.assertNotContainsRe(log, 'revno: 4 ')

    def test_log_file_historical_missing(self):
        # Check logging a deleted file gives an error if the
        # file isn't found at the end or start of the revision range
        self.prepare_tree(complex=True)
        err_msg = "Path unknown at end or start of revision range: file2"
        err = self.run_bzr('log file2', retcode=3)[1]
        self.assertContainsRe(err, err_msg)

    def test_log_file_historical_end(self):
        # Check logging a deleted file is ok if the file existed
        # at the end the revision range
        self.prepare_tree(complex=True)
        log, err = self.run_bzr('log -n0 -r..4 file2')
        self.assertEquals('', err)
        self.assertNotContainsRe(log, 'revno: 1\n')
        self.assertContainsRe(log, 'revno: 2\n')
        self.assertNotContainsRe(log, 'revno: 3\n')
        self.assertContainsRe(log, 'revno: 3.1.1\n')
        self.assertContainsRe(log, 'revno: 4 ')

    def test_log_file_historical_start(self):
        # Check logging a deleted file is ok if the file existed
        # at the start of the revision range
        self.prepare_tree(complex=True)
        log, err = self.run_bzr('log file1')
        self.assertEquals('', err)
        self.assertContainsRe(log, 'revno: 1\n')
        self.assertNotContainsRe(log, 'revno: 2\n')
        self.assertNotContainsRe(log, 'revno: 3\n')
        self.assertNotContainsRe(log, 'revno: 3.1.1\n')
        self.assertNotContainsRe(log, 'revno: 4 ')

    def test_log_file_renamed(self):
        """File matched against revision range, not current tree."""
        self.prepare_tree(complex=True)

        # Check logging a renamed file gives an error by default
        err_msg = "Path unknown at end or start of revision range: file3"
        err = self.run_bzr('log file3', retcode=3)[1]
        self.assertContainsRe(err, err_msg)

        # Check we can see a renamed file if we give the right end revision
        log, err = self.run_bzr('log -r..4 file3')
        self.assertEquals('', err)
        self.assertNotContainsRe(log, 'revno: 1\n')
        self.assertNotContainsRe(log, 'revno: 2\n')
        self.assertContainsRe(log, 'revno: 3\n')
        self.assertNotContainsRe(log, 'revno: 3.1.1\n')
        self.assertNotContainsRe(log, 'revno: 4 ')

    def test_line_log_file(self):
        """The line log for a file should only list relevant mainline revs"""
        # Note: this also implicitly  covers the short logging case.
        # We test using --line in preference to --short because matching
        # revnos in the output of --line is more reliable.
        self.prepare_tree()

        # full history of file1
        log = self.run_bzr('log --line file1')[0]
        self.assertContainsRe(log, '^1:', re.MULTILINE)
        self.assertNotContainsRe(log, '^2:', re.MULTILINE)
        self.assertNotContainsRe(log, '^3:', re.MULTILINE)
        self.assertNotContainsRe(log, '^3.1.1:', re.MULTILINE)
        self.assertNotContainsRe(log, '^4:', re.MULTILINE)

        # full history of file2
        log = self.run_bzr('log --line file2')[0]
        self.assertNotContainsRe(log, '^1:', re.MULTILINE)
        self.assertContainsRe(log, '^2:', re.MULTILINE)
        self.assertNotContainsRe(log, '^3:', re.MULTILINE)
        self.assertNotContainsRe(log, '^3.1.1:', re.MULTILINE)
        self.assertContainsRe(log, '^4:', re.MULTILINE)

        # full history of file3
        log = self.run_bzr('log --line file3')[0]
        self.assertNotContainsRe(log, '^1:', re.MULTILINE)
        self.assertNotContainsRe(log, '^2:', re.MULTILINE)
        self.assertContainsRe(log, '^3:', re.MULTILINE)
        self.assertNotContainsRe(log, '^3.1.1:', re.MULTILINE)
        self.assertNotContainsRe(log, '^4:', re.MULTILINE)

        # file in a merge revision
        log = self.run_bzr('log --line -r3.1.1 file2')[0]
        self.assertNotContainsRe(log, '^1:', re.MULTILINE)
        self.assertNotContainsRe(log, '^2:', re.MULTILINE)
        self.assertNotContainsRe(log, '^3:', re.MULTILINE)
        self.assertContainsRe(log, '^3.1.1:', re.MULTILINE)
        self.assertNotContainsRe(log, '^4:', re.MULTILINE)

        # file in a mainline revision
        log = self.run_bzr('log --line -r4 file2')[0]
        self.assertNotContainsRe(log, '^1:', re.MULTILINE)
        self.assertNotContainsRe(log, '^2:', re.MULTILINE)
        self.assertNotContainsRe(log, '^3:', re.MULTILINE)
        self.assertNotContainsRe(log, '^3.1.1:', re.MULTILINE)
        self.assertContainsRe(log, '^4:', re.MULTILINE)

        # file since a revision
        log = self.run_bzr('log --line -r3.. file2')[0]
        self.assertNotContainsRe(log, '^1:', re.MULTILINE)
        self.assertNotContainsRe(log, '^2:', re.MULTILINE)
        self.assertNotContainsRe(log, '^3:', re.MULTILINE)
        self.assertNotContainsRe(log, '^3.1.1:', re.MULTILINE)
        self.assertContainsRe(log, '^4:', re.MULTILINE)

        # file up to a revision
        log = self.run_bzr('log --line -r..3 file2')[0]
        self.assertNotContainsRe(log, '^1:', re.MULTILINE)
        self.assertContainsRe(log, '^2:', re.MULTILINE)
        self.assertNotContainsRe(log, '^3:', re.MULTILINE)
        self.assertNotContainsRe(log, '^3.1.1:', re.MULTILINE)
        self.assertNotContainsRe(log, '^4:', re.MULTILINE)


class TestLogMultiple(tests.TestCaseWithTransport):

    def prepare_tree(self):
        tree = self.make_branch_and_tree('parent')
        self.build_tree([
            'parent/file1',
            'parent/file2',
            'parent/dir1/',
            'parent/dir1/file5',
            'parent/dir1/dir2/',
            'parent/dir1/dir2/file3',
            'parent/file4'])
        tree.add('file1')
        tree.commit('add file1')
        tree.add('file2')
        tree.commit('add file2')
        tree.add(['dir1', 'dir1/dir2', 'dir1/dir2/file3'])
        tree.commit('add file3')
        tree.add('file4')
        tree.commit('add file4')
        tree.add('dir1/file5')
        tree.commit('add file5')
        child_tree = tree.bzrdir.sprout('child').open_workingtree()
        self.build_tree_contents([('child/file2', 'hello')])
        child_tree.commit(message='branch 1')
        tree.merge_from_branch(child_tree.branch)
        tree.commit(message='merge child branch')
        os.chdir('parent')

    def assertRevnos(self, paths_str, expected_revnos):
        # confirm the revision numbers in log --line output are those expected
        out, err = self.run_bzr('log --line -n0 %s' % (paths_str,))
        self.assertEqual('', err)
        revnos = [s.split(':', 1)[0].lstrip() for s in out.splitlines()]
        self.assertEqual(expected_revnos, revnos)

    def test_log_files(self):
        """The log for multiple file should only list revs for those files"""
        self.prepare_tree()
        self.assertRevnos('file1 file2 dir1/dir2/file3',
            ['6', '5.1.1', '3', '2', '1'])

    def test_log_directory(self):
        """The log for a directory should show all nested files."""
        self.prepare_tree()
        self.assertRevnos('dir1', ['5', '3'])

    def test_log_nested_directory(self):
        """The log for a directory should show all nested files."""
        self.prepare_tree()
        self.assertRevnos('dir1/dir2', ['3'])

    def test_log_in_nested_directory(self):
        """The log for a directory should show all nested files."""
        self.prepare_tree()
        os.chdir("dir1")
        self.assertRevnos('.', ['5', '3'])

    def test_log_files_and_directories(self):
        """Logging files and directories together should be fine."""
        self.prepare_tree()
        self.assertRevnos('file4 dir1/dir2', ['4', '3'])

    def test_log_files_and_dirs_in_nested_directory(self):
        """The log for a directory should show all nested files."""
        self.prepare_tree()
        os.chdir("dir1")
        self.assertRevnos('dir2 file5', ['5', '3'])
