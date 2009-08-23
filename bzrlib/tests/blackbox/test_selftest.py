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

from cStringIO import StringIO
import os
import re
import signal
import sys
import unittest

import bzrlib
from bzrlib import (
    osutils,
    tests,
    )
from bzrlib.errors import ParamikoNotPresent
from bzrlib.tests import (
                          SubUnitFeature,
                          TestCase,
                          TestCaseInTempDir,
                          TestCaseWithMemoryTransport,
                          TestCaseWithTransport,
                          TestUIFactory,
                          TestSkipped,
                          )
from bzrlib.tests.blackbox import ExternalBase


class TestOptions(TestCase):

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

    def test_subunit(self):
        self.requireFeature(SubUnitFeature)
        params = self.get_params_passed_to_core('selftest --subunit')
        self.assertEqual(tests.SubUnitBzrRunner, params[1]['runner_class'])


class TestRunBzr(ExternalBase):

    def _run_bzr_core(self, argv, retcode=0, encoding=None, stdin=None,
                         working_dir=None):
        """Override _run_bzr_core to test how it is invoked by run_bzr.

        Attempts to run bzr from inside this class don't actually run it.

        We test how run_bzr actually invokes bzr in another location.
        Here we only need to test that it is run_bzr passes the right
        parameters to run_bzr.
        """
        self.argv = list(argv)
        self.retcode = retcode
        self.encoding = encoding
        self.stdin = stdin
        self.working_dir = working_dir
        return '', ''

    def test_encoding(self):
        """Test that run_bzr passes encoding to _run_bzr_core"""
        self.run_bzr('foo bar')
        self.assertEqual(None, self.encoding)
        self.assertEqual(['foo', 'bar'], self.argv)

        self.run_bzr('foo bar', encoding='baz')
        self.assertEqual('baz', self.encoding)
        self.assertEqual(['foo', 'bar'], self.argv)

    def test_retcode(self):
        """Test that run_bzr passes retcode to _run_bzr_core"""
        # Default is retcode == 0
        self.run_bzr('foo bar')
        self.assertEqual(0, self.retcode)
        self.assertEqual(['foo', 'bar'], self.argv)

        self.run_bzr('foo bar', retcode=1)
        self.assertEqual(1, self.retcode)
        self.assertEqual(['foo', 'bar'], self.argv)

        self.run_bzr('foo bar', retcode=None)
        self.assertEqual(None, self.retcode)
        self.assertEqual(['foo', 'bar'], self.argv)

        self.run_bzr(['foo', 'bar'], retcode=3)
        self.assertEqual(3, self.retcode)
        self.assertEqual(['foo', 'bar'], self.argv)

    def test_stdin(self):
        # test that the stdin keyword to run_bzr is passed through to
        # _run_bzr_core as-is. We do this by overriding
        # _run_bzr_core in this class, and then calling run_bzr,
        # which is a convenience function for _run_bzr_core, so
        # should invoke it.
        self.run_bzr('foo bar', stdin='gam')
        self.assertEqual('gam', self.stdin)
        self.assertEqual(['foo', 'bar'], self.argv)

        self.run_bzr('foo bar', stdin='zippy')
        self.assertEqual('zippy', self.stdin)
        self.assertEqual(['foo', 'bar'], self.argv)

    def test_working_dir(self):
        """Test that run_bzr passes working_dir to _run_bzr_core"""
        self.run_bzr('foo bar')
        self.assertEqual(None, self.working_dir)
        self.assertEqual(['foo', 'bar'], self.argv)

        self.run_bzr('foo bar', working_dir='baz')
        self.assertEqual('baz', self.working_dir)
        self.assertEqual(['foo', 'bar'], self.argv)

    def test_reject_extra_keyword_arguments(self):
        self.assertRaises(TypeError, self.run_bzr, "foo bar",
                          error_regex=['error message'])


class TestBenchmarkTests(TestCaseWithTransport):

    def test_benchmark_runs_benchmark_tests(self):
        """bzr selftest --benchmark should not run the default test suite."""
        # We test this by passing a regression test name to --benchmark, which
        # should result in 0 tests run.
        old_root = TestCaseWithMemoryTransport.TEST_ROOT
        try:
            TestCaseWithMemoryTransport.TEST_ROOT = None
            out, err = self.run_bzr('selftest --benchmark'
                                    ' per_workingtree')
        finally:
            TestCaseWithMemoryTransport.TEST_ROOT = old_root
        self.assertContainsRe(out, 'Ran 0 tests.*\n\nOK')
        self.assertContainsRe(out, 'tests passed\n')
        benchfile = open(".perf_history", "rt")
        try:
            lines = benchfile.readlines()
        finally:
            benchfile.close()
        self.assertEqual(1, len(lines))
        self.assertContainsRe(lines[0], "--date [0-9.]+")


class TestRunBzrCaptured(ExternalBase):

    def apply_redirected(self, stdin=None, stdout=None, stderr=None,
                         a_callable=None, *args, **kwargs):
        self.stdin = stdin
        self.factory_stdin = getattr(bzrlib.ui.ui_factory, "stdin", None)
        self.factory = bzrlib.ui.ui_factory
        self.working_dir = osutils.getcwd()
        stdout.write('foo\n')
        stderr.write('bar\n')
        return 0

    def test_stdin(self):
        # test that the stdin keyword to _run_bzr_core is passed through to
        # apply_redirected as a StringIO. We do this by overriding
        # apply_redirected in this class, and then calling _run_bzr_core,
        # which calls apply_redirected.
        self.run_bzr(['foo', 'bar'], stdin='gam')
        self.assertEqual('gam', self.stdin.read())
        self.assertTrue(self.stdin is self.factory_stdin)
        self.run_bzr(['foo', 'bar'], stdin='zippy')
        self.assertEqual('zippy', self.stdin.read())
        self.assertTrue(self.stdin is self.factory_stdin)

    def test_ui_factory(self):
        # each invocation of self.run_bzr should get its
        # own UI factory, which is an instance of TestUIFactory,
        # with stdin, stdout and stderr attached to the stdin,
        # stdout and stderr of the invoked run_bzr
        current_factory = bzrlib.ui.ui_factory
        self.run_bzr(['foo'])
        self.failIf(current_factory is self.factory)
        self.assertNotEqual(sys.stdout, self.factory.stdout)
        self.assertNotEqual(sys.stderr, self.factory.stderr)
        self.assertEqual('foo\n', self.factory.stdout.getvalue())
        self.assertEqual('bar\n', self.factory.stderr.getvalue())
        self.assertIsInstance(self.factory, TestUIFactory)

    def test_working_dir(self):
        self.build_tree(['one/', 'two/'])
        cwd = osutils.getcwd()

        # Default is to work in the current directory
        self.run_bzr(['foo', 'bar'])
        self.assertEqual(cwd, self.working_dir)

        self.run_bzr(['foo', 'bar'], working_dir=None)
        self.assertEqual(cwd, self.working_dir)

        # The function should be run in the alternative directory
        # but afterwards the current working dir shouldn't be changed
        self.run_bzr(['foo', 'bar'], working_dir='one')
        self.assertNotEqual(cwd, self.working_dir)
        self.assertEndsWith(self.working_dir, 'one')
        self.assertEqual(cwd, osutils.getcwd())

        self.run_bzr(['foo', 'bar'], working_dir='two')
        self.assertNotEqual(cwd, self.working_dir)
        self.assertEndsWith(self.working_dir, 'two')
        self.assertEqual(cwd, osutils.getcwd())


class TestRunBzrSubprocess(TestCaseWithTransport):

    def test_run_bzr_subprocess(self):
        """The run_bzr_helper_external command behaves nicely."""
        result = self.run_bzr_subprocess('--version')
        result = self.run_bzr_subprocess(['--version'])
        result = self.run_bzr_subprocess('--version', retcode=None)
        self.assertContainsRe(result[0], 'is free software')
        self.assertRaises(AssertionError, self.run_bzr_subprocess,
                          '--versionn')
        result = self.run_bzr_subprocess('--versionn', retcode=3)
        result = self.run_bzr_subprocess('--versionn', retcode=None)
        self.assertContainsRe(result[1], 'unknown command')
        err = self.run_bzr_subprocess(['merge', '--merge-type',
                                      'magic merge'], retcode=3)[1]
        self.assertContainsRe(err, 'Bad value "magic merge" for option'
                              ' "merge-type"')

    def test_run_bzr_subprocess_env(self):
        """run_bzr_subprocess can set environment variables in the child only.

        These changes should not change the running process, only the child.
        """
        # The test suite should unset this variable
        self.assertEqual(None, os.environ.get('BZR_EMAIL'))
        out, err = self.run_bzr_subprocess('whoami', env_changes={
                                            'BZR_EMAIL':'Joe Foo <joe@foo.com>'
                                          }, universal_newlines=True)
        self.assertEqual('', err)
        self.assertEqual('Joe Foo <joe@foo.com>\n', out)
        # And it should not be modified
        self.assertEqual(None, os.environ.get('BZR_EMAIL'))

        # Do it again with a different address, just to make sure
        # it is actually changing
        out, err = self.run_bzr_subprocess('whoami', env_changes={
                                            'BZR_EMAIL':'Barry <bar@foo.com>'
                                          }, universal_newlines=True)
        self.assertEqual('', err)
        self.assertEqual('Barry <bar@foo.com>\n', out)
        self.assertEqual(None, os.environ.get('BZR_EMAIL'))

    def test_run_bzr_subprocess_env_del(self):
        """run_bzr_subprocess can remove environment variables too."""
        # Create a random email, so we are sure this won't collide
        rand_bzr_email = 'John Doe <jdoe@%s.com>' % (osutils.rand_chars(20),)
        rand_email = 'Jane Doe <jdoe@%s.com>' % (osutils.rand_chars(20),)
        os.environ['BZR_EMAIL'] = rand_bzr_email
        os.environ['EMAIL'] = rand_email
        try:
            # By default, the child will inherit the current env setting
            out, err = self.run_bzr_subprocess('whoami', universal_newlines=True)
            self.assertEqual('', err)
            self.assertEqual(rand_bzr_email + '\n', out)

            # Now that BZR_EMAIL is not set, it should fall back to EMAIL
            out, err = self.run_bzr_subprocess('whoami',
                                               env_changes={'BZR_EMAIL':None},
                                               universal_newlines=True)
            self.assertEqual('', err)
            self.assertEqual(rand_email + '\n', out)

            # This switches back to the default email guessing logic
            # Which shouldn't match either of the above addresses
            out, err = self.run_bzr_subprocess('whoami',
                           env_changes={'BZR_EMAIL':None, 'EMAIL':None},
                           universal_newlines=True)

            self.assertEqual('', err)
            self.assertNotEqual(rand_bzr_email + '\n', out)
            self.assertNotEqual(rand_email + '\n', out)
        finally:
            # TestCase cleans up BZR_EMAIL, and EMAIL at startup
            del os.environ['BZR_EMAIL']
            del os.environ['EMAIL']

    def test_run_bzr_subprocess_env_del_missing(self):
        """run_bzr_subprocess won't fail if deleting a nonexistant env var"""
        self.failIf('NON_EXISTANT_ENV_VAR' in os.environ)
        out, err = self.run_bzr_subprocess('rocks',
                        env_changes={'NON_EXISTANT_ENV_VAR':None},
                        universal_newlines=True)
        self.assertEqual('It sure does!\n', out)
        self.assertEqual('', err)

    def test_run_bzr_subprocess_working_dir(self):
        """Test that we can specify the working dir for the child"""
        cwd = osutils.getcwd()

        self.make_branch_and_tree('.')
        self.make_branch_and_tree('one')
        self.make_branch_and_tree('two')

        def get_root(**kwargs):
            """Spawn a process to get the 'root' of the tree.

            You can pass in arbitrary new arguments. This just makes
            sure that the returned path doesn't have trailing whitespace.
            """
            return self.run_bzr_subprocess('root', **kwargs)[0].rstrip()

        self.assertEqual(cwd, get_root())
        self.assertEqual(cwd, get_root(working_dir=None))
        # Has our path changed?
        self.assertEqual(cwd, osutils.getcwd())

        dir1 = get_root(working_dir='one')
        self.assertEndsWith(dir1, 'one')
        self.assertEqual(cwd, osutils.getcwd())

        dir2 = get_root(working_dir='two')
        self.assertEndsWith(dir2, 'two')
        self.assertEqual(cwd, osutils.getcwd())


class _DontSpawnProcess(Exception):
    """A simple exception which just allows us to skip unnecessary steps"""


class TestRunBzrSubprocessCommands(TestCaseWithTransport):

    def _popen(self, *args, **kwargs):
        """Record the command that is run, so that we can ensure it is correct"""
        self._popen_args = args
        self._popen_kwargs = kwargs
        raise _DontSpawnProcess()

    def test_run_bzr_subprocess_no_plugins(self):
        self.assertRaises(_DontSpawnProcess, self.run_bzr_subprocess, '')
        command = self._popen_args[0]
        self.assertEqual(sys.executable, command[0])
        self.assertEqual(self.get_bzr_path(), command[1])
        self.assertEqual(['--no-plugins'], command[2:])

    def test_allow_plugins(self):
        self.assertRaises(_DontSpawnProcess,
                          self.run_bzr_subprocess, '', allow_plugins=True)
        command = self._popen_args[0]
        self.assertEqual([], command[2:])


class TestBzrSubprocess(TestCaseWithTransport):

    def test_start_and_stop_bzr_subprocess(self):
        """We can start and perform other test actions while that process is
        still alive.
        """
        process = self.start_bzr_subprocess(['--version'])
        result = self.finish_bzr_subprocess(process)
        self.assertContainsRe(result[0], 'is free software')
        self.assertEqual('', result[1])

    def test_start_and_stop_bzr_subprocess_with_error(self):
        """finish_bzr_subprocess allows specification of the desired exit code.
        """
        process = self.start_bzr_subprocess(['--versionn'])
        result = self.finish_bzr_subprocess(process, retcode=3)
        self.assertEqual('', result[0])
        self.assertContainsRe(result[1], 'unknown command')

    def test_start_and_stop_bzr_subprocess_ignoring_retcode(self):
        """finish_bzr_subprocess allows the exit code to be ignored."""
        process = self.start_bzr_subprocess(['--versionn'])
        result = self.finish_bzr_subprocess(process, retcode=None)
        self.assertEqual('', result[0])
        self.assertContainsRe(result[1], 'unknown command')

    def test_start_and_stop_bzr_subprocess_with_unexpected_retcode(self):
        """finish_bzr_subprocess raises self.failureException if the retcode is
        not the expected one.
        """
        process = self.start_bzr_subprocess(['--versionn'])
        self.assertRaises(self.failureException, self.finish_bzr_subprocess,
                          process)

    def test_start_and_stop_bzr_subprocess_send_signal(self):
        """finish_bzr_subprocess raises self.failureException if the retcode is
        not the expected one.
        """
        process = self.start_bzr_subprocess(['wait-until-signalled'],
                                            skip_if_plan_to_signal=True)
        self.assertEqual('running\n', process.stdout.readline())
        result = self.finish_bzr_subprocess(process, send_signal=signal.SIGINT,
                                            retcode=3)
        self.assertEqual('', result[0])
        self.assertEqual('bzr: interrupted\n', result[1])

    def test_start_and_stop_working_dir(self):
        cwd = osutils.getcwd()

        self.make_branch_and_tree('one')

        process = self.start_bzr_subprocess(['root'], working_dir='one')
        result = self.finish_bzr_subprocess(process, universal_newlines=True)
        self.assertEndsWith(result[0], 'one\n')
        self.assertEqual('', result[1])


class TestRunBzrError(ExternalBase):

    def test_run_bzr_error(self):
        # retcode=0 is specially needed here because run_bzr_error expects
        # an error (oddly enough) but we want to test the case of not
        # actually getting one
        out, err = self.run_bzr_error(['^$'], ['rocks'], retcode=0)
        self.assertEqual(out, 'It sure does!\n')
        # now test actually getting an error
        out, err = self.run_bzr_error(
                ["bzr: ERROR: foobarbaz is not versioned"],
                ['file-id', 'foobarbaz'])


class TestSelftestListOnly(TestCase):

    @staticmethod
    def _parse_test_list(lines, newlines_in_header=0):
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


class TestSelftestWithIdList(TestCaseInTempDir):

    def test_load_list(self):
        # We don't want to call selftest for the whole suite, so we start with
        # a reduced list.
        test_list_fname = 'test.list'
        fl = open(test_list_fname, 'wt')
        fl.write('%s\n' % self.id())
        fl.close()
        out, err = self.run_bzr(
            ['selftest', '--load-list', test_list_fname, '--list'])
        self.assertContainsRe(out, "TestSelftestWithIdList")
        self.assertLength(1, out.splitlines())

    def test_load_unknown(self):
        out, err = self.run_bzr('selftest --load-list I_do_not_exist ',
                                retcode=3)


class TestSelftestStartingWith(TestCase):

    def test_starting_with_single_argument(self):
        out, err = self.run_bzr(
            ['selftest', '--starting-with', self.id(), '--list'])
        self.assertContainsRe(out, self.id())

    def test_starting_with_multiple_argument(self):
        out, err = self.run_bzr(
            ['selftest',
             '--starting-with', self.id(),
             '--starting-with', 'bzrlib.tests.test_sampler',
             '--list'])
        self.assertContainsRe(out, self.id())
        self.assertContainsRe(out, 'bzrlib.tests.test_sampler')
