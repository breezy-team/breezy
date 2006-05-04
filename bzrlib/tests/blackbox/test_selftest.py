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


class TestRunBzr(ExternalBase):

    def run_bzr_captured(self, argv, retcode=0, stdin=None):
        self.stdin = stdin

    def test_stdin(self):
        # test that the stdin keyword to run_bzr is passed through to
        # run_bzr_captured as-is.
        self.run_bzr('foo', 'bar', stdin='gam')
        self.assertEqual('gam', self.stdin)
        self.run_bzr('foo', 'bar', stdin='zippy')
        self.assertEqual('zippy', self.stdin)


class TestRunBzrCaptured(ExternalBase):

    def apply_redirected(self, stdin=None, stdout=None, stderr=None,
                         a_callable=None, *args, **kwargs):
        self.stdin = stdin
        return 0

    def test_stdin(self):
        # test that the stdin keyword to run_bzr_captured is passed through to
        # apply_redirected as a StringIO
        self.run_bzr_captured(['foo', 'bar'], stdin='gam')
        self.assertEqual('gam', self.stdin.read())
        self.run_bzr_captured(['foo', 'bar'], stdin='zippy')
        self.assertEqual('zippy', self.stdin.read())
