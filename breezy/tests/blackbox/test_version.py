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

"""Black-box tests for brz version."""

import os
import sys

import breezy
from breezy import osutils, trace
from breezy.tests import (
    TestCase,
    TestCaseInTempDir,
    TestSkipped,
    probe_unicode_in_user_encoding,
)


class TestVersion(TestCase):
    def test_main_version(self):
        """Check output from version command and master option is reasonable."""
        # output is intentionally passed through to stdout so that we
        # can see the version being tested
        self.permit_source_tree_branch_repo()
        output = self.run_bzr("version")[0]
        self.log("brz version output:")
        self.log(output)
        self.assertTrue(output.startswith("Breezy (brz) "))
        self.assertNotEqual(output.index("Canonical"), -1)
        # make sure --version is consistent
        tmp_output = self.run_bzr("--version")[0]
        self.assertEqual(output, tmp_output)

    def test_version(self):
        self.permit_source_tree_branch_repo()
        out = self.run_bzr("version")[0]
        self.assertTrue(len(out) > 0)
        self.assertEqualDiff(
            out.splitlines()[0], "Breezy (brz) {}".format(breezy.__version__)
        )
        self.assertContainsRe(out, r"(?m)^  Python interpreter:")
        self.assertContainsRe(out, r"(?m)^  Python standard library:")
        self.assertContainsRe(out, r"(?m)^  breezy:")
        self.assertContainsRe(out, r"(?m)^  Breezy configuration:")
        self.assertContainsRe(out, r"(?m)^  Breezy log file:.*[\\/]breezy[\\/]brz\.log")

    def test_version_short(self):
        self.permit_source_tree_branch_repo()
        out = self.run_bzr(["version", "--short"])[0]
        self.assertEqualDiff(out, breezy.version_string + "\n")


class TestVersionUnicodeOutput(TestCaseInTempDir):
    def _check(self, args):
        self.permit_source_tree_branch_repo()
        # Even though trace._brz_log_filename variable
        # is used only to keep actual log filename
        # and changing this variable in selftest
        # don't change main brz.log location,
        # and therefore pretty safe,
        # but we run these tests in separate temp dir
        # with relative unicoded path
        old_trace_file = trace._brz_log_filename
        trace._brz_log_filename = "\u1234/.brz.log"
        try:
            out = self.run_bzr(args)[0]
        finally:
            trace._brz_log_filename = old_trace_file
        self.assertTrue(len(out) > 0)
        self.assertContainsRe(out, r"(?m)^  Breezy log file:.*brz\.log")

    def test_command(self):
        self._check("version")

    def test_flag(self):
        self._check("--version")

    def test_unicode_bzr_home(self):
        uni_val, str_val = probe_unicode_in_user_encoding()
        if uni_val is None:
            raise TestSkipped(
                "Cannot find a unicode character that works in"
                " encoding {}".format(osutils.get_user_encoding())
            )

        self.overrideEnv("BRZ_HOME", uni_val)
        self.permit_source_tree_branch_repo()
        out = self.run_bzr_raw("version")[0]
        self.assertTrue(len(out) > 0)
        self.assertContainsRe(out, rb"(?m)^  Breezy configuration: " + str_val)


class TestVersionBzrLogLocation(TestCaseInTempDir):
    def default_log(self):
        return os.path.join(os.environ["BRZ_HOME"], "breezy", "brz.log")

    def test_simple(self):
        brz_log = "my.brz.log"
        self.overrideEnv("BRZ_LOG", brz_log)
        self.assertPathDoesNotExist([self.default_log(), brz_log])
        out = self.run_brz_subprocess("version")[0]
        self.assertTrue(len(out) > 0)
        self.assertContainsRe(
            out, rb"(?m)^  Breezy log file: " + brz_log.encode("ascii")
        )
        self.assertPathExists(brz_log)
        self.assertPathDoesNotExist(self.default_log())

    def test_dev_null(self):
        # This test uses a subprocess to cause the log opening logic to
        # execute. It would be better to just execute that logic directly.
        if sys.platform == "win32":
            brz_log = "NUL"
        else:
            brz_log = "/dev/null"
        self.overrideEnv("BRZ_LOG", brz_log)
        self.assertPathDoesNotExist(self.default_log())
        out = self.run_brz_subprocess("version")[0]
        self.assertTrue(len(out) > 0)
        self.assertContainsRe(
            out, rb"(?m)^  Breezy log file: " + brz_log.encode("ascii")
        )
        self.assertPathDoesNotExist(self.default_log())

    def test_unicode_brz_log(self):
        uni_val = "\xa7"
        enc = osutils.get_user_encoding()
        try:
            uni_val.encode(enc)
        except UnicodeEncodeError:
            self.skipTest(
                "Test string {!r} unrepresentable in user encoding {}".format(
                    uni_val, enc
                )
            )
        brz_log = os.path.join(self.test_base_dir, uni_val)
        self.overrideEnv("BRZ_LOG", brz_log)
        out, err = self.run_brz_subprocess("version")
        uni_out = out.decode(enc)
        self.assertContainsRe(uni_out, "(?m)^  Breezy log file: .*/\xa7$")
