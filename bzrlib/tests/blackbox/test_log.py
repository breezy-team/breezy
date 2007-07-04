# Copyright (C) 2005, 2006, 2007 Canonical Ltd
# -*- coding: utf-8 -*-
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


"""Black-box tests for bzr log."""

import os

import bzrlib
from bzrlib.tests.blackbox import ExternalBase
from bzrlib.tests import TestCaseInTempDir, TestCaseWithTransport


class TestLog(ExternalBase):

    def _prepare(self, format=None):
        if format:
            self.run_bzr(["init", "--format="+format])
        else:
            self.run_bzr("init")
        self.build_tree(['hello.txt', 'goodbye.txt', 'meep.txt'])
        self.run_bzr("add hello.txt")
        self.run_bzr("commit -m message1 hello.txt")
        self.run_bzr("add goodbye.txt")
        self.run_bzr("commit -m message2 goodbye.txt")
        self.run_bzr("add meep.txt")
        self.run_bzr("commit -m message3 meep.txt")
        self.full_log = self.run_bzr("log")[0]

    def test_log_null_end_revspec(self):
        self._prepare()
        self.assertTrue('revno: 1\n' in self.full_log)
        self.assertTrue('revno: 2\n' in self.full_log)
        self.assertTrue('revno: 3\n' in self.full_log)
        self.assertTrue('message:\n  message1\n' in self.full_log)
        self.assertTrue('message:\n  message2\n' in self.full_log)
        self.assertTrue('message:\n  message3\n' in self.full_log)

        log = self.run_bzr("log -r 1..")[0]
        self.assertEqualDiff(log, self.full_log)

    def test_log_null_begin_revspec(self):
        self._prepare()
        log = self.run_bzr("log -r ..3")[0]
        self.assertEqualDiff(self.full_log, log)

    def test_log_null_both_revspecs(self):
        self._prepare()
        log = self.run_bzr("log -r ..")[0]
        self.assertEquals(self.full_log, log)
        self.assertEqualDiff(self.full_log, log)

    def test_log_negative_begin_revspec_full_log(self):
        self._prepare()
        log = self.run_bzr("log -r -3..")[0]
        self.assertEqualDiff(self.full_log, log)

    def test_log_negative_both_revspec_full_log(self):
        self._prepare()
        log = self.run_bzr("log -r -3..-1")[0]
        self.assertEqualDiff(self.full_log, log)

    def test_log_negative_both_revspec_partial(self):
        self._prepare()
        log = self.run_bzr("log -r -3..-2")[0]
        self.assertTrue('revno: 1\n' in log)
        self.assertTrue('revno: 2\n' in log)
        self.assertTrue('revno: 3\n' not in log)

    def test_log_negative_begin_revspec(self):
        self._prepare()
        log = self.run_bzr("log -r -2..")[0]
        self.assertTrue('revno: 1\n' not in log)
        self.assertTrue('revno: 2\n' in log)
        self.assertTrue('revno: 3\n' in log)

    def test_log_postive_revspecs(self):
        self._prepare()
        log = self.run_bzr("log -r 1..3")[0]
        self.assertEqualDiff(self.full_log, log)

    def test_log_reversed_revspecs(self):
        self._prepare()
        self.run_bzr_error(('bzr: ERROR: Start revision must be older than '
                            'the end revision.\n',),
                           'log', '-r3..1')

    def test_log_revno_n_path(self):
        os.mkdir('branch1')
        os.chdir('branch1')
        self._prepare()
        os.chdir('..')
        os.mkdir('branch2')
        os.chdir('branch2')
        self._prepare()
        os.chdir('..')
        log = self.run_bzr("log -r revno:2:branch1..revno:3:branch2",
                          retcode=3)[0]
        log = self.run_bzr("log -r revno:1:branch2..revno:3:branch2")[0]
        self.assertEqualDiff(self.full_log, log)
        log = self.run_bzr("log -r revno:1:branch2")[0]
        self.assertTrue('revno: 1\n' in log)
        self.assertTrue('revno: 2\n' not in log)
        self.assertTrue('branch nick: branch2\n' in log)
        self.assertTrue('branch nick: branch1\n' not in log)
        
    def test_log_nonexistent_file(self):
        # files that don't exist in either the basis tree or working tree
        # should give an error
        wt = self.make_branch_and_tree('.')
        out, err = self.run_bzr('log', 'does-not-exist', retcode=3)
        self.assertContainsRe(
            err, 'Path does not have any revision history: does-not-exist')

    def test_log_with_tags(self):
        self._prepare(format='dirstate-tags')
        self.run_bzr('tag -r1 tag1')
        self.run_bzr('tag -r1 tag1.1')
        self.run_bzr('tag tag3')
        
        log = self.run_bzr("log -r-1")[0]
        self.assertTrue('tags: tag3' in log)

        log = self.run_bzr("log -r1")[0]
        # I guess that we can't know the order of tags in the output
        # since dicts are unordered, need to check both possibilities
        self.assertContainsRe(log, r'tags: (tag1, tag1\.1|tag1\.1, tag1)')

    def test_merged_log_with_tags(self):
        os.mkdir('branch1')
        os.chdir('branch1')
        self._prepare(format='dirstate-tags')
        os.chdir('..')
        self.run_bzr('branch branch1 branch2')
        os.chdir('branch1')
        self.run_bzr('commit -m foobar --unchanged')
        self.run_bzr('tag tag1')
        os.chdir('../branch2')
        self.run_bzr('merge ../branch1')
        self.run_bzr('commit -m merge_branch_1')
        log = self.run_bzr("log -r-1")[0]
        self.assertContainsRe(log, r'    tags: tag1')
        log = self.run_bzr("log -r3.1.1")[0]
        self.assertContainsRe(log, r'    tags: tag1')

    def test_log_limit(self):
        self._prepare()
        log = self.run_bzr("log --limit 2")[0]
        self.assertTrue('revno: 1\n' not in log)
        self.assertTrue('revno: 2\n' in log)
        self.assertTrue('revno: 3\n' in log)

class TestLogMerges(ExternalBase):

    def _prepare(self):
        self.build_tree(['parent/'])
        self.run_bzr('init', 'parent')
        self.run_bzr('commit', '-m', 'first post', '--unchanged', 'parent')
        self.run_bzr('branch', 'parent', 'child')
        self.run_bzr('commit', '-m', 'branch 1', '--unchanged', 'child')
        self.run_bzr('branch', 'child', 'smallerchild')
        self.run_bzr('commit', '-m', 'branch 2', '--unchanged', 'smallerchild')
        os.chdir('child')
        self.run_bzr('merge', '../smallerchild')
        self.run_bzr('commit', '-m', 'merge branch 2')
        os.chdir('../parent')
        self.run_bzr('merge', '../child')
        self.run_bzr('commit', '-m', 'merge branch 1')

    def test_merges_are_indented_by_level(self):
        self._prepare()
        out,err = self.run_bzr('log')
        # the log will look something like:
#        self.assertEqual("""\
#------------------------------------------------------------
#revno: 2
#committer: Robert Collins <foo@example.com>
#branch nick: parent
#timestamp: Tue 2006-03-28 22:31:40 +1100
#message:
#  merge branch 1
#    ------------------------------------------------------------
#    revno: 1.1.2  
#    committer: Robert Collins <foo@example.com>
#    branch nick: child
#    timestamp: Tue 2006-03-28 22:31:40 +1100
#    message:
#      merge branch 2
#        ------------------------------------------------------------
#        revno: 1.1.1.1
#        committer: Robert Collins <foo@example.com>
#        branch nick: smallerchild
#        timestamp: Tue 2006-03-28 22:31:40 +1100
#        message:
#          branch 2
#    ------------------------------------------------------------
#    revno: 1.1.1
#    committer: Robert Collins <foo@example.com>
#    branch nick: child
#    timestamp: Tue 2006-03-28 22:31:40 +1100
#    message:
#      branch 1
#------------------------------------------------------------
#revno: 1
#committer: Robert Collins <foo@example.com>
#branch nick: parent
#timestamp: Tue 2006-03-28 22:31:39 +1100
#message:
#  first post
#""", out)
        # but we dont have a nice pattern matcher hooked up yet, so:
        # we check for the indenting of the commit message and the 
        # revision numbers 
        self.assertTrue('revno: 2' in out)
        self.assertTrue('  merge branch 1' in out)
        self.assertTrue('    revno: 1.1.2' in out)
        self.assertTrue('      merge branch 2' in out)
        self.assertTrue('        revno: 1.1.1.1' in out)
        self.assertTrue('          branch 2' in out)
        self.assertTrue('    revno: 1.1.1' in out)
        self.assertTrue('      branch 1' in out)
        self.assertTrue('revno: 1\n' in out)
        self.assertTrue('  first post' in out)
        self.assertEqual('', err)

    def test_merges_single_merge_rev(self):
        self._prepare()
        out,err = self.run_bzr('log', '-r1.1.2')
        # the log will look something like:
#        self.assertEqual("""\
#    ------------------------------------------------------------
#    revno: 1.1.2  
#    committer: Robert Collins <foo@example.com>
#    branch nick: child
#    timestamp: Tue 2006-03-28 22:31:40 +1100
#    message:
#      merge branch 2
#        ------------------------------------------------------------
#        revno: 1.1.1.1
#        committer: Robert Collins <foo@example.com>
#        branch nick: smallerchild
#        timestamp: Tue 2006-03-28 22:31:40 +1100
#        message:
#          branch 2
#""", out)
        # but we dont have a nice pattern matcher hooked up yet, so:
        # we check for the indenting of the commit message and the 
        # revision numbers 
        self.assertTrue('revno: 2' not in out)
        self.assertTrue('  merge branch 1' not in out)
        self.assertTrue('    revno: 1.1.2' in out)
        self.assertTrue('      merge branch 2' in out)
        self.assertTrue('        revno: 1.1.1.1' in out)
        self.assertTrue('          branch 2' in out)
        self.assertTrue('    revno: 1.1.1\n' not in out)
        self.assertTrue('      branch 1' not in out)
        self.assertTrue('revno: 1\n' not in out)
        self.assertTrue('  first post' not in out)
        self.assertEqual('', err)

    def test_merges_partial_range(self):
        self._prepare()
        out,err = self.run_bzr('log', '-r1.1.1..1.1.2')
        # the log will look something like:
#        self.assertEqual("""\
#    ------------------------------------------------------------
#    revno: 1.1.2  
#    committer: Robert Collins <foo@example.com>
#    branch nick: child
#    timestamp: Tue 2006-03-28 22:31:40 +1100
#    message:
#      merge branch 2
#        ------------------------------------------------------------
#        revno: 1.1.1.1
#        committer: Robert Collins <foo@example.com>
#        branch nick: smallerchild
#        timestamp: Tue 2006-03-28 22:31:40 +1100
#        message:
#          branch 2
#    ------------------------------------------------------------
#    revno: 1.1.1
#    committer: Robert Collins <foo@example.com>
#    branch nick: child
#    timestamp: Tue 2006-03-28 22:31:40 +1100
#    message:
#      branch 1
#""", out)
        # but we dont have a nice pattern matcher hooked up yet, so:
        # we check for the indenting of the commit message and the 
        # revision numbers 
        self.assertTrue('revno: 2' not in out)
        self.assertTrue('  merge branch 1' not in out)
        self.assertTrue('    revno: 1.1.2' in out)
        self.assertTrue('      merge branch 2' in out)
        self.assertTrue('        revno: 1.1.1.1' in out)
        self.assertTrue('          branch 2' in out)
        self.assertTrue('    revno: 1.1.1' in out)
        self.assertTrue('      branch 1' in out)
        self.assertTrue('revno: 1\n' not in out)
        self.assertTrue('  first post' not in out)
        self.assertEqual('', err)

 
class TestLogEncodings(TestCaseInTempDir):

    _mu = u'\xb5'
    _message = u'Message with \xb5'

    # Encodings which can encode mu
    good_encodings = [
        'utf-8',
        'latin-1',
        'iso-8859-1',
        'cp437', # Common windows encoding
        'cp1251', # Alexander Belchenko's windows encoding
        'cp1258', # Common windows encoding
    ]
    # Encodings which cannot encode mu
    bad_encodings = [
        'ascii',
        'iso-8859-2',
        'koi8_r',
    ]

    def setUp(self):
        TestCaseInTempDir.setUp(self)
        self.user_encoding = bzrlib.user_encoding

    def tearDown(self):
        bzrlib.user_encoding = self.user_encoding
        TestCaseInTempDir.tearDown(self)

    def create_branch(self):
        bzr = self.run_bzr
        bzr('init')
        open('a', 'wb').write('some stuff\n')
        bzr('add', 'a')
        bzr('commit', '-m', self._message)

    def try_encoding(self, encoding, fail=False):
        bzr = self.run_bzr
        if fail:
            self.assertRaises(UnicodeEncodeError,
                self._mu.encode, encoding)
            encoded_msg = self._message.encode(encoding, 'replace')
        else:
            encoded_msg = self._message.encode(encoding)

        old_encoding = bzrlib.user_encoding
        # This test requires that 'run_bzr' uses the current
        # bzrlib, because we override user_encoding, and expect
        # it to be used
        try:
            bzrlib.user_encoding = 'ascii'
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
            bzrlib.user_encoding = old_encoding

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
        bzrlib.user_encoding = "cp1251"

        bzr('init')
        self.build_tree(['a'])
        bzr('add', 'a')
        bzr('commit', '-m', u'\u0422\u0435\u0441\u0442')
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


class TestLogFile(TestCaseWithTransport):

    def test_log_local_branch_file(self):
        """We should be able to log files in local treeless branches"""
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/file'])
        tree.add('file')
        tree.commit('revision 1')
        tree.bzrdir.destroy_workingtree()
        self.run_bzr('log', 'tree/file')

    def test_log_file(self):
        """The log for a particular file should only list revs for that file"""
        tree = self.make_branch_and_tree('parent')
        self.build_tree(['parent/file1', 'parent/file2', 'parent/file3'])
        tree.add('file1')
        tree.commit('add file1')
        tree.add('file2')
        tree.commit('add file2')
        tree.add('file3')
        tree.commit('add file3')
        self.run_bzr('branch', 'parent', 'child')
        print >> file('child/file2', 'wb'), 'hello'
        self.run_bzr('commit', '-m', 'branch 1', 'child')
        os.chdir('parent')
        self.run_bzr('merge', '../child')
        self.run_bzr('commit', '-m', 'merge child branch')
       
        log = self.run_bzr('log', 'file1')[0]
        self.assertContainsRe(log, 'revno: 1\n')
        self.assertNotContainsRe(log, 'revno: 2\n')
        self.assertNotContainsRe(log, 'revno: 3\n')
        self.assertNotContainsRe(log, 'revno: 3.1.1\n')
        self.assertNotContainsRe(log, 'revno: 4\n')
        log = self.run_bzr('log', 'file2')[0]
        self.assertNotContainsRe(log, 'revno: 1\n')
        self.assertContainsRe(log, 'revno: 2\n')
        self.assertNotContainsRe(log, 'revno: 3\n')
        self.assertContainsRe(log, 'revno: 3.1.1\n')
        self.assertContainsRe(log, 'revno: 4\n')
        log = self.run_bzr('log', 'file3')[0]
        self.assertNotContainsRe(log, 'revno: 1\n')
        self.assertNotContainsRe(log, 'revno: 2\n')
        self.assertContainsRe(log, 'revno: 3\n')
        self.assertNotContainsRe(log, 'revno: 3.1.1\n')
        self.assertNotContainsRe(log, 'revno: 4\n')
        log = self.run_bzr('log', '-r3.1.1', 'file2')[0]
        self.assertNotContainsRe(log, 'revno: 1\n')
        self.assertNotContainsRe(log, 'revno: 2\n')
        self.assertNotContainsRe(log, 'revno: 3\n')
        self.assertContainsRe(log, 'revno: 3.1.1\n')
        self.assertNotContainsRe(log, 'revno: 4\n')
        log = self.run_bzr('log', '-r4', 'file2')[0]
        self.assertNotContainsRe(log, 'revno: 1\n')
        self.assertNotContainsRe(log, 'revno: 2\n')
        self.assertNotContainsRe(log, 'revno: 3\n')
        self.assertContainsRe(log, 'revno: 3.1.1\n')
        self.assertContainsRe(log, 'revno: 4\n')
        log = self.run_bzr('log', '-r3..', 'file2')[0]
        self.assertNotContainsRe(log, 'revno: 1\n')
        self.assertNotContainsRe(log, 'revno: 2\n')
        self.assertNotContainsRe(log, 'revno: 3\n')
        self.assertContainsRe(log, 'revno: 3.1.1\n')
        self.assertContainsRe(log, 'revno: 4\n')
        log = self.run_bzr('log', '-r..3', 'file2')[0]
        self.assertNotContainsRe(log, 'revno: 1\n')
        self.assertContainsRe(log, 'revno: 2\n')
        self.assertNotContainsRe(log, 'revno: 3\n')
        self.assertNotContainsRe(log, 'revno: 3.1.1\n')
        self.assertNotContainsRe(log, 'revno: 4\n')
