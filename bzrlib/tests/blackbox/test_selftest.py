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

import sys

import bzrlib
from bzrlib.errors import ParamikoNotPresent
from bzrlib.tests import (
                          TestCase,
                          TestCaseInTempDir,
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

    def test_benchmark_runs_benchmark_tests(self):
        """bzr selftest --benchmark should not run the default test suite."""
        # We test this by passing a regression test name to --benchmark, which
        # should result in 0 rests run.
        out, err = self.run_bzr('selftest', '--benchmark', 'workingtree_implementations')
        self.assertContainsRe(out, 'Ran 0 tests.*\n\nOK')
        self.assertEqual(
            'running tests...\nRunning tests: .\nCleaning up: .\ntests passed\n',
            err)
        

class TestRunBzr(ExternalBase):

    def run_bzr_captured(self, argv, retcode=0, stdin=None):
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
