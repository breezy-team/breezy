# Copyright (C) 2005 by Canonical Ltd
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as published by
# the Free Software Foundation.
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
                          TestCaseInTempDir,
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
        old_root = TestCaseInTempDir.TEST_ROOT
        TestCaseInTempDir.TEST_ROOT = None
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
            TestCaseInTempDir.TEST_ROOT = old_root


class TestRunBzr(ExternalBase):

    def run_bzr_captured(self, argv, retcode=0, encoding=None, stdin=None):
        self.stdin = stdin

    def test_stdin(self):
        # test that the stdin keyword to run_bzr is passed through to
        # run_bzr_captured as-is. We do this by overriding
        # run_bzr_captured in this class, and then calling run_bzr,
        # which is a convenience function for run_bzr_captured, so 
        # should invoke it.
        self.run_bzr('foo', 'bar', stdin='gam')
        self.assertEqual('gam', self.stdin)
        self.run_bzr('foo', 'bar', stdin='zippy')
        self.assertEqual('zippy', self.stdin)


class TestBenchmarkTests(TestCaseWithTransport):

    def test_benchmark_runs_benchmark_tests(self):
        """bzr selftest --benchmark should not run the default test suite."""
        # We test this by passing a regression test name to --benchmark, which
        # should result in 0 rests run.
        old_root = TestCaseInTempDir.TEST_ROOT
        try:
            TestCaseInTempDir.TEST_ROOT = None
            out, err = self.run_bzr('selftest', '--benchmark', 'workingtree_implementations')
        finally:
            TestCaseInTempDir.TEST_ROOT = old_root
        self.assertContainsRe(out, 'Ran 0 tests.*\n\nOK')
        self.assertEqual(
            'running tests...\ntests passed\n',
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
        process = self.start_bzr_subprocess(['wait-until-signalled'])
        self.assertEqual('running\n', process.stdout.readline())
        result = self.finish_bzr_subprocess(process, send_signal=signal.SIGINT,
                                            retcode=3)
        self.assertEqual('', result[0])
        self.assertEqual('bzr: interrupted\n', result[1])
        

class TestRunBzrError(ExternalBase):

    def test_run_bzr_error(self):
        out, err = self.run_bzr_error(['^$'], 'rocks', retcode=0)
        self.assertEqual(out, 'it sure does!\n')

        out, err = self.run_bzr_error(["'foobarbaz' is not a versioned file"],
                                      'file-id', 'foobarbaz')
