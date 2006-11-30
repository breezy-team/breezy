# Copyright (C) 2005 Canonical Ltd
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

"""UI tests for the test framework."""

import os
import signal
import sys

import bzrlib
from bzrlib import (
    osutils,
    )
from bzrlib.errors import ParamikoNotPresent
from bzrlib.tests import (
                          TestCase,
                          TestCaseWithMemoryTransport,
                          TestCaseWithTransport,
                          TestSkipped,
                          )
from bzrlib.tests.blackbox import ExternalBase


class TestOptions(TestCase):

    current_test = None

    def test_transport_set_to_sftp(self):
        # test the --transport option has taken effect from within the
        # test_transport test
        try:
            import bzrlib.transport.sftp
        except ParamikoNotPresent:
            raise TestSkipped("Paramiko not present")
        if TestOptions.current_test != "test_transport_set_to_sftp":
            return
        self.assertEqual(bzrlib.transport.sftp.SFTPAbsoluteServer,
                         bzrlib.tests.default_transport)

    def test_transport_set_to_memory(self):
        # test the --transport option has taken effect from within the
        # test_transport test
        import bzrlib.transport.memory
        if TestOptions.current_test != "test_transport_set_to_memory":
            return
        self.assertEqual(bzrlib.transport.memory.MemoryServer,
                         bzrlib.tests.default_transport)

    def test_transport(self):
        # test that --transport=sftp works
        try:
            import bzrlib.transport.sftp
        except ParamikoNotPresent:
            raise TestSkipped("Paramiko not present")
        old_transport = bzrlib.tests.default_transport
        old_root = TestCaseWithMemoryTransport.TEST_ROOT
        TestCaseWithMemoryTransport.TEST_ROOT = None
        try:
            TestOptions.current_test = "test_transport_set_to_sftp"
            stdout = self.capture('selftest --transport=sftp test_transport_set_to_sftp')
            
            self.assertContainsRe(stdout, 'Ran 1 test')
            self.assertEqual(old_transport, bzrlib.tests.default_transport)

            TestOptions.current_test = "test_transport_set_to_memory"
            stdout = self.capture('selftest --transport=memory test_transport_set_to_memory')
            self.assertContainsRe(stdout, 'Ran 1 test')
            self.assertEqual(old_transport, bzrlib.tests.default_transport)
        finally:
            bzrlib.tests.default_transport = old_transport
            TestOptions.current_test = None
            TestCaseWithMemoryTransport.TEST_ROOT = old_root


class TestRunBzr(ExternalBase):

    def run_bzr_captured(self, argv, retcode=0, encoding=None, stdin=None,
                         working_dir=None):
        """Override run_bzr_captured to test how it is invoked by run_bzr.

        We test how run_bzr_captured actually invokes bzr in another location.
        Here we only need to test that it is run_bzr passes the right
        parameters to run_bzr_captured.
        """
        self.argv = argv
        self.retcode = retcode
        self.encoding = encoding
        self.stdin = stdin
        self.working_dir = working_dir

    def test_args(self):
        """Test that run_bzr passes args correctly to run_bzr_captured"""
        self.run_bzr('arg1', 'arg2', 'arg3', retcode=1)
        self.assertEqual(('arg1', 'arg2', 'arg3'), self.argv)

    def test_encoding(self):
        """Test that run_bzr passes encoding to run_bzr_captured"""
        self.run_bzr('foo', 'bar')
        self.assertEqual(None, self.encoding)
        self.assertEqual(('foo', 'bar'), self.argv)

        self.run_bzr('foo', 'bar', encoding='baz')
        self.assertEqual('baz', self.encoding)
        self.assertEqual(('foo', 'bar'), self.argv)

    def test_retcode(self):
        """Test that run_bzr passes retcode to run_bzr_captured"""
        # Default is retcode == 0
        self.run_bzr('foo', 'bar')
        self.assertEqual(0, self.retcode)
        self.assertEqual(('foo', 'bar'), self.argv)

        self.run_bzr('foo', 'bar', retcode=1)
        self.assertEqual(1, self.retcode)
        self.assertEqual(('foo', 'bar'), self.argv)

        self.run_bzr('foo', 'bar', retcode=None)
        self.assertEqual(None, self.retcode)
        self.assertEqual(('foo', 'bar'), self.argv)

        self.run_bzr('foo', 'bar', retcode=3)
        self.assertEqual(3, self.retcode)
        self.assertEqual(('foo', 'bar'), self.argv)

    def test_stdin(self):
        # test that the stdin keyword to run_bzr is passed through to
        # run_bzr_captured as-is. We do this by overriding
        # run_bzr_captured in this class, and then calling run_bzr,
        # which is a convenience function for run_bzr_captured, so 
        # should invoke it.
        self.run_bzr('foo', 'bar', stdin='gam')
        self.assertEqual('gam', self.stdin)
        self.assertEqual(('foo', 'bar'), self.argv)

        self.run_bzr('foo', 'bar', stdin='zippy')
        self.assertEqual('zippy', self.stdin)
        self.assertEqual(('foo', 'bar'), self.argv)

    def test_working_dir(self):
        """Test that run_bzr passes working_dir to run_bzr_captured"""
        self.run_bzr('foo', 'bar')
        self.assertEqual(None, self.working_dir)
        self.assertEqual(('foo', 'bar'), self.argv)

        self.run_bzr('foo', 'bar', working_dir='baz')
        self.assertEqual('baz', self.working_dir)
        self.assertEqual(('foo', 'bar'), self.argv)


class TestBenchmarkTests(TestCaseWithTransport):

    def test_benchmark_runs_benchmark_tests(self):
        """bzr selftest --benchmark should not run the default test suite."""
        # We test this by passing a regression test name to --benchmark, which
        # should result in 0 rests run.
        old_root = TestCaseWithMemoryTransport.TEST_ROOT
        try:
            TestCaseWithMemoryTransport.TEST_ROOT = None
            out, err = self.run_bzr('selftest', '--benchmark', 'workingtree_implementations')
        finally:
            TestCaseWithMemoryTransport.TEST_ROOT = old_root
        self.assertContainsRe(out, 'Ran 0 tests.*\n\nOK')
        self.assertEqual(
            'tests passed\n',
            err)
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
        # test that the stdin keyword to run_bzr_captured is passed through to
        # apply_redirected as a StringIO. We do this by overriding
        # apply_redirected in this class, and then calling run_bzr_captured,
        # which calls apply_redirected. 
        self.run_bzr_captured(['foo', 'bar'], stdin='gam')
        self.assertEqual('gam', self.stdin.read())
        self.assertTrue(self.stdin is self.factory_stdin)
        self.run_bzr_captured(['foo', 'bar'], stdin='zippy')
        self.assertEqual('zippy', self.stdin.read())
        self.assertTrue(self.stdin is self.factory_stdin)

    def test_ui_factory(self):
        # each invocation of self.run_bzr_captured should get its own UI
        # factory, which is an instance of TestUIFactory, with stdout and
        # stderr attached to the stdout and stderr of the invoked
        # run_bzr_captured
        current_factory = bzrlib.ui.ui_factory
        self.run_bzr_captured(['foo'])
        self.failIf(current_factory is self.factory)
        self.assertNotEqual(sys.stdout, self.factory.stdout)
        self.assertNotEqual(sys.stderr, self.factory.stderr)
        self.assertEqual('foo\n', self.factory.stdout.getvalue())
        self.assertEqual('bar\n', self.factory.stderr.getvalue())
        self.assertIsInstance(self.factory, bzrlib.tests.blackbox.TestUIFactory)

    def test_working_dir(self):
        self.build_tree(['one/', 'two/'])
        cwd = osutils.getcwd()

        # Default is to work in the current directory
        self.run_bzr_captured(['foo', 'bar'])
        self.assertEqual(cwd, self.working_dir)

        self.run_bzr_captured(['foo', 'bar'], working_dir=None)
        self.assertEqual(cwd, self.working_dir)

        # The function should be run in the alternative directory
        # but afterwards the current working dir shouldn't be changed
        self.run_bzr_captured(['foo', 'bar'], working_dir='one')
        self.assertNotEqual(cwd, self.working_dir)
        self.assertEndsWith(self.working_dir, 'one')
        self.assertEqual(cwd, osutils.getcwd())

        self.run_bzr_captured(['foo', 'bar'], working_dir='two')
        self.assertNotEqual(cwd, self.working_dir)
        self.assertEndsWith(self.working_dir, 'two')
        self.assertEqual(cwd, osutils.getcwd())


class TestRunBzrSubprocess(TestCaseWithTransport):

    def test_run_bzr_subprocess(self):
        """The run_bzr_helper_external comand behaves nicely."""
        result = self.run_bzr_subprocess('--version')
        result = self.run_bzr_subprocess('--version', retcode=None)
        self.assertContainsRe(result[0], 'is free software')
        self.assertRaises(AssertionError, self.run_bzr_subprocess, 
                          '--versionn')
        result = self.run_bzr_subprocess('--versionn', retcode=3)
        result = self.run_bzr_subprocess('--versionn', retcode=None)
        self.assertContainsRe(result[1], 'unknown command')
        err = self.run_bzr_subprocess('merge', '--merge-type', 'magic merge', 
                                      retcode=3)[1]
        self.assertContainsRe(err, 'No known merge type magic merge')

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
        self.assertEqual('it sure does!\n', out)
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
        self.assertRaises(_DontSpawnProcess, self.run_bzr_subprocess)
        command = self._popen_args[0]
        self.assertEqual(sys.executable, command[0])
        self.assertEqual(self.get_bzr_path(), command[1])
        self.assertEqual(['--no-plugins'], command[2:])

    def test_allow_plugins(self):
        self.assertRaises(_DontSpawnProcess,
                          self.run_bzr_subprocess, allow_plugins=True)
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
                          process, retcode=0)
        
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
        out, err = self.run_bzr_error(['^$'], 'rocks', retcode=0)
        self.assertEqual(out, 'it sure does!\n')

        out, err = self.run_bzr_error(["bzr: ERROR: foobarbaz is not versioned"],
                                      'file-id', 'foobarbaz')
