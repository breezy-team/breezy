# Copyright (C) 2006-2010 Canonical Ltd
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

"""UI tests for the test framework."""

import os

from breezy import tests
from breezy.tests import features
from breezy.transport import memory


class SelfTestPatch:
    def get_params_passed_to_core(self, cmdline):
        params = []

        def selftest(*args, **kwargs):
            """Capture the arguments selftest was run with."""
            params.append((args, kwargs))
            return True

        # Yes this prevents using threads to run the test suite in parallel,
        # however we don't have a clean dependency injector for commands,
        # and even if we did - we'd still be testing that the glue is wired
        # up correctly. XXX: TODO: Solve this testing problem.
        original_selftest = tests.selftest
        tests.selftest = selftest
        try:
            self.run_bzr(cmdline)
            return params[0]
        finally:
            tests.selftest = original_selftest


class TestOptions(tests.TestCase, SelfTestPatch):
    def test_load_list(self):
        params = self.get_params_passed_to_core("selftest --load-list foo")
        self.assertEqual("foo", params[1]["load_list"])

    def test_transport_set_to_sftp(self):
        # Test that we can pass a transport to the selftest core - sftp
        # version.
        self.requireFeature(features.paramiko)
        from breezy.tests import stub_sftp

        params = self.get_params_passed_to_core("selftest --transport=sftp")
        self.assertEqual(stub_sftp.SFTPAbsoluteServer, params[1]["transport"])

    def test_transport_set_to_memory(self):
        # Test that we can pass a transport to the selftest core - memory
        # version.
        params = self.get_params_passed_to_core("selftest --transport=memory")
        self.assertEqual(memory.MemoryServer, params[1]["transport"])

    def test_parameters_passed_to_core(self):
        params = self.get_params_passed_to_core("selftest --list-only")
        self.assertIn("list_only", params[1])
        params = self.get_params_passed_to_core("selftest --list-only selftest")
        self.assertIn("list_only", params[1])
        params = self.get_params_passed_to_core(
            ["selftest", "--list-only", "--exclude", "selftest"]
        )
        self.assertIn("list_only", params[1])
        params = self.get_params_passed_to_core(
            ["selftest", "--list-only", "selftest", "--randomize", "now"]
        )
        self.assertSubset(["list_only", "random_seed"], params[1])

    def test_starting_with(self):
        params = self.get_params_passed_to_core("selftest --starting-with foo")
        self.assertEqual(["foo"], params[1]["starting_with"])

    def test_starting_with_multiple_argument(self):
        params = self.get_params_passed_to_core(
            "selftest --starting-with foo --starting-with bar"
        )
        self.assertEqual(["foo", "bar"], params[1]["starting_with"])

    def test_subunitv1(self):
        self.requireFeature(features.subunit)
        params = self.get_params_passed_to_core("selftest --subunit1")
        self.assertEqual(tests.SubUnitBzrRunnerv1, params[1]["runner_class"])

    def test_subunitv2(self):
        self.requireFeature(features.subunit)
        params = self.get_params_passed_to_core("selftest --subunit2")
        self.assertEqual(tests.SubUnitBzrRunnerv2, params[1]["runner_class"])

    def _parse_test_list(self, lines, newlines_in_header=0):
        """Parse a list of lines into a tuple of 3 lists (header,body,footer)."""
        in_header = newlines_in_header != 0
        in_footer = False
        header = []
        body = []
        footer = []
        header_newlines_found = 0
        for line in lines:
            if in_header:
                if line == "":
                    header_newlines_found += 1
                    if header_newlines_found >= newlines_in_header:
                        in_header = False
                        continue
                header.append(line)
            elif not in_footer:
                if line.startswith("-------"):
                    in_footer = True
                else:
                    body.append(line)
            else:
                footer.append(line)
        # If the last body line is blank, drop it off the list
        if len(body) > 0 and body[-1] == "":
            body.pop()
        return (header, body, footer)

    def test_list_only(self):
        # check that brz selftest --list-only outputs no ui noise
        def selftest(*args, **kwargs):
            """Capture the arguments selftest was run with."""
            return True

        def outputs_nothing(cmdline):
            out, err = self.run_bzr(cmdline)
            (header, body, footer) = self._parse_test_list(out.splitlines())
            len(body)
            self.assertLength(0, header)
            self.assertLength(0, footer)
            self.assertEqual("", err)

        # Yes this prevents using threads to run the test suite in parallel,
        # however we don't have a clean dependency injector for commands,
        # and even if we did - we'd still be testing that the glue is wired
        # up correctly. XXX: TODO: Solve this testing problem.
        original_selftest = tests.selftest
        tests.selftest = selftest
        try:
            outputs_nothing("selftest --list-only")
            outputs_nothing("selftest --list-only selftest")
            outputs_nothing(["selftest", "--list-only", "--exclude", "selftest"])
        finally:
            tests.selftest = original_selftest

    def test_lsprof_tests(self):
        params = self.get_params_passed_to_core("selftest --lsprof-tests")
        self.assertEqual(True, params[1]["lsprof_tests"])

    def test_parallel_fork_unsupported(self):
        if getattr(os, "fork", None) is not None:
            self.addCleanup(setattr, os, "fork", os.fork)
            del os.fork
        out, err = self.run_bzr(
            ["selftest", "--parallel=fork", "-s", "bt.x"], retcode=3
        )
        self.assertIn("platform does not support fork", err)
        self.assertFalse(out)
