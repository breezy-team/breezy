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

"""Tests for the test framework
"""

import os
import sys
import unittest

from bzrlib.tests import (
                          _load_module_by_name,
                          TestCase,
                          TestCaseInTempDir,
                          TestSkipped,
                          TextTestRunner,
                          )


class SelftestTests(TestCase):

    def test_import_tests(self):
        mod = _load_module_by_name('bzrlib.tests.test_selftest')
        self.assertEqual(mod.SelftestTests, SelftestTests)

    def test_import_test_failure(self):
        self.assertRaises(ImportError,
                          _load_module_by_name,
                          'bzrlib.no-name-yet')


class MetaTestLog(TestCase):

    def test_logging(self):
        """Test logs are captured when a test fails."""
        self.log('a test message')
        self._log_file.flush()
        self.assertContainsRe(self._get_log(), 'a test message\n')


class TestTreeShape(TestCaseInTempDir):

    def test_unicode_paths(self):
        filename = u'hell\u00d8'
        try:
            self.build_tree_contents([(filename, 'contents of hello')])
        except UnicodeEncodeError:
            raise TestSkipped("can't build unicode working tree in "
                "filesystem encoding %s" % sys.getfilesystemencoding())
        self.failUnlessExists(filename)


class TestSkippedTest(TestCase):
    """Try running a test which is skipped, make sure it's reported properly."""

    def test_skipped_test(self):
        # must be hidden in here so it's not run as a real test
        def skipping_test():
            raise TestSkipped('test intentionally skipped')
        runner = TextTestRunner(stream=self._log_file)
        test = unittest.FunctionTestCase(skipping_test)
        result = runner.run(test)
        self.assertTrue(result.wasSuccessful())


class TestTransportProviderAdapter(TestCase):

    def test_adapter_sets_transport_class(self):
        from bzrlib.transport.local import (LocalTransport,
                                            LocalRelpathServer,
                                            LocalAbspathServer,
                                            LocalURLServer
                                            )
        from bzrlib.transport.sftp import (SFTPTransport,
                                           SFTPAbsoluteServer,
                                           SFTPHomeDirServer,
                                           SFTPSiblingAbsoluteServer,
                                           )
        from bzrlib.transport.http import (HttpTransport,
                                           HttpServer
                                           )
        from bzrlib.transport.ftp import FtpTransport
        from bzrlib.transport.memory import (MemoryTransport,
                                             MemoryServer
                                             )
        from bzrlib.transport import TransportTestProviderAdapter
        # FIXME. What we want is a factory for the things
        # needed to test the implementation. I.e. for transport we want:
        # the class that connections should get; a local server factory
        # so we would want the following permutations:
        # LocalTransport relpath-factory
        # LocalTransport abspath-factory
        # LocalTransport file://-factory
        # SFTPTransport homedir-factory
        # SFTPTransport abssolute-factory
        # HTTPTransport http-factory
        # HTTPTransport https-factory
        # etc, but we are currently lacking in this, so print out that
        # this should be fixed.
        print "TODO: test servers for all local permutations."
        print "Currently missing: FTP, HTTPS."
        input_test = TestTransportProviderAdapter(
            "test_adapter_sets_transport_class")
        suite = TransportTestProviderAdapter().adapt(input_test)
        test_iter = iter(suite)
        local_relpath_test = test_iter.next()
        local_abspath_test = test_iter.next()
        local_urlpath_test = test_iter.next()
        sftp_abs_test = test_iter.next()
        sftp_homedir_test = test_iter.next()
        sftp_sibling_abs_test = test_iter.next()
        http_test = test_iter.next()
        memory_test = test_iter.next()
        # ftp_test = test_iter.next()
        self.assertRaises(StopIteration, test_iter.next)
        self.assertEqual(LocalTransport, local_relpath_test.transport_class)
        self.assertEqual(LocalRelpathServer, local_relpath_test.transport_server)
        
        self.assertEqual(LocalTransport, local_abspath_test.transport_class)
        self.assertEqual(LocalAbspathServer, local_abspath_test.transport_server)

        self.assertEqual(LocalTransport, local_urlpath_test.transport_class)
        self.assertEqual(LocalURLServer, local_urlpath_test.transport_server)

        self.assertEqual(SFTPTransport, sftp_abs_test.transport_class)
        self.assertEqual(SFTPAbsoluteServer, sftp_abs_test.transport_server)
        self.assertEqual(SFTPTransport, sftp_homedir_test.transport_class)
        self.assertEqual(SFTPHomeDirServer, sftp_homedir_test.transport_server)
        self.assertEqual(SFTPTransport, sftp_sibling_abs_test.transport_class)
        self.assertEqual(SFTPSiblingAbsoluteServer,
                         sftp_sibling_abs_test.transport_server)

        self.assertEqual(HttpTransport, http_test.transport_class)
        self.assertEqual(HttpServer, http_test.transport_server)
        # self.assertEqual(FtpTransport, ftp_test.transport_class)

        self.assertEqual(MemoryTransport, memory_test.transport_class)
        self.assertEqual(MemoryServer, memory_test.transport_server)
        
        # we could test all of them for .id, but two is probably sufficient.
        self.assertEqual("bzrlib.tests.test_selftest."
                         "TestTransportProviderAdapter."
                         "test_adapter_sets_transport_class(MemoryServer)",
                         memory_test.id())
        self.assertEqual("bzrlib.tests.test_selftest."
                         "TestTransportProviderAdapter."
                         "test_adapter_sets_transport_class(LocalRelpathServer)",
                         local_relpath_test.id())
