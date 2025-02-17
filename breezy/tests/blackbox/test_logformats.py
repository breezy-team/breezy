# Copyright (C) 2006, 2007, 2009, 2011, 2016 Canonical Ltd
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


"""Black-box tests for default log_formats/log_formatters."""

import os

from breezy import bedding, tests


class TestLogFormats(tests.TestCaseWithTransport):
    def setUp(self):
        super().setUp()

        # Create a config file with some useful variables
        conf_path = bedding.config_path()
        if os.path.isfile(conf_path):
            # Something is wrong in environment,
            # we risk overwriting users config
            self.fail(f"{conf_path} exists")

        bedding.ensure_config_dir_exists()
        with open(conf_path, "wb") as f:
            f.write(
                b"""[DEFAULT]
email=Joe Foo <joe@foo.com>
log_format=line
"""
            )

    def _make_simple_branch(self, relpath="."):
        wt = self.make_branch_and_tree(relpath)
        wt.commit("first revision")
        wt.commit("second revision")
        return wt

    def test_log_default_format(self):
        self._make_simple_branch()
        # only the lines formatter is this short, one line by revision
        log = self.run_bzr("log")[0]
        self.assertEqual(2, len(log.splitlines()))

    def test_log_format_arg(self):
        self._make_simple_branch()
        self.run_bzr(["log", "--log-format", "short"])[0]

    def test_missing_default_format(self):
        wt = self._make_simple_branch("a")
        self.run_bzr(["branch", "a", "b"])
        wt.commit("third revision")
        wt.commit("fourth revision")

        missing = self.run_bzr("missing", retcode=1, working_dir="b")[0]
        # one line for 'Using save location'
        # one line for 'You are missing 2 revision(s)'
        # one line by missing revision (the line log format is used as
        # configured)
        self.assertEqual(4, len(missing.splitlines()))

    def test_missing_format_arg(self):
        wt = self._make_simple_branch("a")
        self.run_bzr(["branch", "a", "b"])
        wt.commit("third revision")
        wt.commit("fourth revision")

        missing = self.run_bzr(
            ["missing", "--log-format", "short"], retcode=1, working_dir="b"
        )[0]
        # one line for 'Using save location'
        # one line for 'You are missing 2 revision(s)'
        # three lines by missing revision
        self.assertEqual(8, len(missing.splitlines()))

    def test_logformat_gnu_changelog(self):
        # from http://launchpad.net/bugs/29582/
        wt = self.make_branch_and_tree(".")
        wt.commit("first revision", timestamp=1236045060, timezone=0)  # Aka UTC

        log, err = self.run_bzr(
            ["log", "--log-format", "gnu-changelog", "--timezone=utc"]
        )
        self.assertEqual("", err)
        expected = """2009-03-03  Joe Foo  <joe@foo.com>

\tfirst revision

"""
        self.assertEqualDiff(expected, log)

    def test_logformat_line_wide(self):
        """Author field should get larger for column widths over 80."""
        wt = self.make_branch_and_tree(".")
        wt.commit(
            "revision with a long author", committer="Person with long name SENTINEL"
        )
        log, err = self.run_bzr("log --line")
        self.assertNotContainsString(log, "SENTINEL")
        self.overrideEnv("BRZ_COLUMNS", "116")
        log, err = self.run_bzr("log --line")
        self.assertContainsString(log, "SENT...")
        self.overrideEnv("BRZ_COLUMNS", "0")
        log, err = self.run_bzr("log --line")
        self.assertContainsString(log, "SENTINEL")
