# Copyright (C) 2007-2012, 2016 Canonical Ltd
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

"""Black-box tests for bzr version."""

import os
import sys

import bzrlib
from bzrlib import osutils, trace
from bzrlib.tests import (
    probe_unicode_in_user_encoding,
    TestCase,
    TestCaseInTempDir,
    TestSkipped,
    )


class TestVersion(TestCase):

    def test_main_version(self):
        """Check output from version command and master option is reasonable"""
        # output is intentionally passed through to stdout so that we
        # can see the version being tested
        self.permit_source_tree_branch_repo()
        output = self.run_bzr('version')[0]
        self.log('bzr version output:')
        self.log(output)
        self.assertTrue(output.startswith('Bazaar (bzr) '))
        self.assertNotEqual(output.index('Canonical'), -1)
        # make sure --version is consistent
        tmp_output = self.run_bzr('--version')[0]
        self.assertEqual(output, tmp_output)

    def test_version(self):
        self.permit_source_tree_branch_repo()
        out = self.run_bzr("version")[0]
        self.assertTrue(len(out) > 0)
        self.assertEqualDiff(out.splitlines()[0],
            "Bazaar (bzr) %s" % bzrlib.__version__)
        self.assertContainsRe(out, r"(?m)^  Python interpreter:")
        self.assertContainsRe(out, r"(?m)^  Python standard library:")
        self.assertContainsRe(out, r"(?m)^  bzrlib:")
        self.assertContainsRe(out, r"(?m)^  Bazaar configuration:")
        self.assertContainsRe(out, r'(?m)^  Bazaar log file:.*\.bzr\.log')

    def test_version_short(self):
        self.permit_source_tree_branch_repo()
        out = self.run_bzr(["version", "--short"])[0]
        self.assertEqualDiff(out, bzrlib.version_string + '\n')


class TestVersionUnicodeOutput(TestCaseInTempDir):

    def _check(self, args):
        self.permit_source_tree_branch_repo()
        # Even though trace._bzr_log_filename variable
        # is used only to keep actual log filename
        # and changing this variable in selftest
        # don't change main .bzr.log location,
        # and therefore pretty safe,
        # but we run these tests in separate temp dir
        # with relative unicoded path
        old_trace_file = trace._bzr_log_filename
        trace._bzr_log_filename = u'\u1234/.bzr.log'
        try:
            out = self.run_bzr(args)[0]
        finally:
            trace._bzr_log_filename = old_trace_file
        self.assertTrue(len(out) > 0)
        self.assertContainsRe(out, r'(?m)^  Bazaar log file:.*bzr\.log')

    def test_command(self):
        self._check("version")

    def test_flag(self):
        self._check("--version")

    def test_unicode_bzr_home(self):
        uni_val, str_val = probe_unicode_in_user_encoding()
        if uni_val is None:
            raise TestSkipped('Cannot find a unicode character that works in'
                              ' encoding %s' % (osutils.get_user_encoding(),))

        self.overrideEnv('BZR_HOME', str_val)
        self.permit_source_tree_branch_repo()
        out = self.run_bzr("version")[0]
        self.assertTrue(len(out) > 0)
        self.assertContainsRe(out, r"(?m)^  Bazaar configuration: " + str_val)


class TestVersionBzrLogLocation(TestCaseInTempDir):

    def test_simple(self):
        bzr_log = 'my.bzr.log'
        self.overrideEnv('BZR_LOG', bzr_log)
        default_log = os.path.join(os.environ['BZR_HOME'], '.bzr.log')
        self.assertPathDoesNotExist([default_log, bzr_log])
        out = self.run_bzr_subprocess('version')[0]
        self.assertTrue(len(out) > 0)
        self.assertContainsRe(out, r"(?m)^  Bazaar log file: " + bzr_log)
        self.assertPathDoesNotExist(default_log)
        self.assertPathExists(bzr_log)

    def test_dev_null(self):
        # This test uses a subprocess to cause the log opening logic to
        # execute. It would be better to just execute that logic directly.
        if sys.platform == 'win32':
            bzr_log = 'NUL'
        else:
            bzr_log = '/dev/null'
        self.overrideEnv('BZR_LOG', bzr_log)
        default_log = os.path.join(os.environ['BZR_HOME'], '.bzr.log')
        self.assertPathDoesNotExist(default_log)
        out = self.run_bzr_subprocess('version')[0]
        self.assertTrue(len(out) > 0)
        self.assertContainsRe(out, r"(?m)^  Bazaar log file: " + bzr_log)
        self.assertPathDoesNotExist(default_log)

    def test_unicode_bzr_log(self):
        uni_val = u"\xa7"
        enc = osutils.get_user_encoding()
        try:
            str_val = uni_val.encode(enc)
        except UnicodeEncodeError:
            self.skip("Test string %r unrepresentable in user encoding %s" % (
                uni_val, enc))
        self.overrideEnv('BZR_HOME', self.test_base_dir)
        self.overrideEnv("BZR_LOG",
            os.path.join(self.test_base_dir, uni_val).encode(enc))
        out, err = self.run_bzr_subprocess("version")
        uni_out = out.decode(enc)
        self.assertContainsRe(uni_out, u"(?m)^  Bazaar log file: .*/\xa7$")


