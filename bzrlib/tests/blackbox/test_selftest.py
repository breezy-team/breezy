# Copyright (C) 2005, 2007 Canonical Ltd
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

import bzrlib.transport
from bzrlib import (
    benchmarks,
    tests,
    )
from bzrlib.errors import ParamikoNotPresent
from bzrlib.tests import (
                          SubUnitFeature,
                          TestCase,
                          TestCaseInTempDir,
                          TestSkipped,
                          )


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


class TestOptionsWritingToDisk(TestCaseInTempDir, SelfTestPatch):

    def test_benchmark_runs_benchmark_tests(self):
        """selftest --benchmark should change the suite factory."""
        params = self.get_params_passed_to_core('selftest --benchmark')
        self.assertEqual(benchmarks.test_suite,
            params[1]['test_suite_factory'])
        self.assertNotEqual(None, params[1]['bench_history'])
        benchfile = open(".perf_history", "rt")
        try:
            lines = benchfile.readlines()
        finally:
            benchfile.close()
        # Because we don't run the actual test code no output is made to the
        # file.
        self.assertEqual(0, len(lines))


class TestOptions(TestCase, SelfTestPatch):

    def test_load_list(self):
        params = self.get_params_passed_to_core('selftest --load-list foo')
        self.assertEqual('foo', params[1]['load_list'])

    def test_transport_set_to_sftp(self):
        # Test that we can pass a transport to the selftest core - sftp
        # version.
        try:
            import bzrlib.transport.sftp
        except ParamikoNotPresent:
            raise TestSkipped("Paramiko not present")
        params = self.get_params_passed_to_core('selftest --transport=sftp')
        self.assertEqual(bzrlib.transport.sftp.SFTPAbsoluteServer,
            params[1]["transport"])

    def test_transport_set_to_memory(self):
        # Test that we can pass a transport to the selftest core - memory
        # version.
        import bzrlib.transport.memory
        params = self.get_params_passed_to_core('selftest --transport=memory')
        self.assertEqual(bzrlib.transport.memory.MemoryServer,
            params[1]["transport"])

    def test_parameters_passed_to_core(self):
        params = self.get_params_passed_to_core('selftest --list-only')
        self.assertTrue("list_only" in params[1])
        params = self.get_params_passed_to_core('selftest --list-only selftest')
        self.assertTrue("list_only" in params[1])
        params = self.get_params_passed_to_core(['selftest', '--list-only',
            '--exclude', 'selftest'])
        self.assertTrue("list_only" in params[1])
        params = self.get_params_passed_to_core(['selftest', '--list-only',
            'selftest', '--randomize', 'now'])
        self.assertSubset(["list_only", "random_seed"], params[1])

    def test_starting_with(self):
        params = self.get_params_passed_to_core('selftest --starting-with foo')
        self.assertEqual(['foo'], params[1]['starting_with'])

    def test_starting_with_multiple_argument(self):
        params = self.get_params_passed_to_core(
            'selftest --starting-with foo --starting-with bar')
        self.assertEqual(['foo', 'bar'], params[1]['starting_with'])

    def test_subunit(self):
        self.requireFeature(SubUnitFeature)
        params = self.get_params_passed_to_core('selftest --subunit')
        self.assertEqual(tests.SubUnitBzrRunner, params[1]['runner_class'])

    def _parse_test_list(self, lines, newlines_in_header=0):
        "Parse a list of lines into a tuple of 3 lists (header,body,footer)."
        in_header = newlines_in_header != 0
        in_footer = False
        header = []
        body = []
        footer = []
        header_newlines_found = 0
        for line in lines:
            if in_header:
                if line == '':
                    header_newlines_found += 1
                    if header_newlines_found >= newlines_in_header:
                        in_header = False
                        continue
                header.append(line)
            elif not in_footer:
                if line.startswith('-------'):
                    in_footer = True
                else:
                    body.append(line)
            else:
                footer.append(line)
        # If the last body line is blank, drop it off the list
        if len(body) > 0 and body[-1] == '':
            body.pop()
        return (header,body,footer)

    def test_list_only(self):
        # check that bzr selftest --list-only outputs no ui noise
        def selftest(*args, **kwargs):
            """Capture the arguments selftest was run with."""
            return True
        def outputs_nothing(cmdline):
            out,err = self.run_bzr(cmdline)
            (header,body,footer) = self._parse_test_list(out.splitlines())
            num_tests = len(body)
            self.assertLength(0, header)
            self.assertLength(0, footer)
            self.assertEqual('', err)
        # Yes this prevents using threads to run the test suite in parallel,
        # however we don't have a clean dependency injector for commands, 
        # and even if we did - we'd still be testing that the glue is wired
        # up correctly. XXX: TODO: Solve this testing problem.
        original_selftest = tests.selftest
        tests.selftest = selftest
        try:
            outputs_nothing('selftest --list-only')
            outputs_nothing('selftest --list-only selftest')
            outputs_nothing(['selftest', '--list-only', '--exclude', 'selftest'])
        finally:
            tests.selftest = original_selftest
