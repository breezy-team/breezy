# Copyright (C) 2005, 2006, 2007 Canonical Ltd
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

"""Tests for the test framework."""

import cStringIO
import os
from StringIO import StringIO
import sys
import time
import unittest
import warnings

import bzrlib
from bzrlib import (
    bzrdir,
    errors,
    memorytree,
    osutils,
    repository,
    symbol_versioning,
    )
from bzrlib.progress import _BaseProgressBar
from bzrlib.repofmt import weaverepo
from bzrlib.symbol_versioning import zero_ten, zero_eleven
from bzrlib.tests import (
                          ChrootedTestCase,
                          ExtendedTestResult,
                          Feature,
                          KnownFailure,
                          TestCase,
                          TestCaseInTempDir,
                          TestCaseWithMemoryTransport,
                          TestCaseWithTransport,
                          TestSkipped,
                          TestSuite,
                          TextTestRunner,
                          UnavailableFeature,
                          clean_selftest_output,
                          )
from bzrlib.tests.test_sftp_transport import TestCaseWithSFTPServer
from bzrlib.tests.TestUtil import _load_module_by_name
from bzrlib.trace import note
from bzrlib.transport.memory import MemoryServer, MemoryTransport
from bzrlib.version import _get_bzr_source_tree


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
        self.assertContainsRe(self._get_log(keep_log_file=True),
                              'a test message\n')


class TestTreeShape(TestCaseInTempDir):

    def test_unicode_paths(self):
        filename = u'hell\u00d8'
        try:
            self.build_tree_contents([(filename, 'contents of hello')])
        except UnicodeEncodeError:
            raise TestSkipped("can't build unicode working tree in "
                "filesystem encoding %s" % sys.getfilesystemencoding())
        self.failUnlessExists(filename)


class TestTransportProviderAdapter(TestCase):
    """A group of tests that test the transport implementation adaption core.

    This is a meta test that the tests are applied to all available 
    transports.

    This will be generalised in the future which is why it is in this 
    test file even though it is specific to transport tests at the moment.
    """

    def test_get_transport_permutations(self):
        # this checks that we the module get_test_permutations call
        # is made by the adapter get_transport_test_permitations method.
        class MockModule(object):
            def get_test_permutations(self):
                return sample_permutation
        sample_permutation = [(1,2), (3,4)]
        from bzrlib.transport import TransportTestProviderAdapter
        adapter = TransportTestProviderAdapter()
        self.assertEqual(sample_permutation,
                         adapter.get_transport_test_permutations(MockModule()))

    def test_adapter_checks_all_modules(self):
        # this checks that the adapter returns as many permurtations as
        # there are in all the registered# transport modules for there
        # - we assume if this matches its probably doing the right thing
        # especially in combination with the tests for setting the right
        # classes below.
        from bzrlib.transport import (TransportTestProviderAdapter,
                                      _get_transport_modules
                                      )
        modules = _get_transport_modules()
        permutation_count = 0
        for module in modules:
            try:
                permutation_count += len(reduce(getattr, 
                    (module + ".get_test_permutations").split('.')[1:],
                     __import__(module))())
            except errors.DependencyNotPresent:
                pass
        input_test = TestTransportProviderAdapter(
            "test_adapter_sets_transport_class")
        adapter = TransportTestProviderAdapter()
        self.assertEqual(permutation_count,
                         len(list(iter(adapter.adapt(input_test)))))

    def test_adapter_sets_transport_class(self):
        # Check that the test adapter inserts a transport and server into the
        # generated test.
        #
        # This test used to know about all the possible transports and the
        # order they were returned but that seems overly brittle (mbp
        # 20060307)
        input_test = TestTransportProviderAdapter(
            "test_adapter_sets_transport_class")
        from bzrlib.transport import TransportTestProviderAdapter
        suite = TransportTestProviderAdapter().adapt(input_test)
        tests = list(iter(suite))
        self.assertTrue(len(tests) > 6)
        # there are at least that many builtin transports
        one_test = tests[0]
        self.assertTrue(issubclass(one_test.transport_class, 
                                   bzrlib.transport.Transport))
        self.assertTrue(issubclass(one_test.transport_server, 
                                   bzrlib.transport.Server))


class TestBranchProviderAdapter(TestCase):
    """A group of tests that test the branch implementation test adapter."""

    def test_adapted_tests(self):
        # check that constructor parameters are passed through to the adapted
        # test.
        from bzrlib.branch import BranchTestProviderAdapter
        input_test = TestBranchProviderAdapter(
            "test_adapted_tests")
        server1 = "a"
        server2 = "b"
        formats = [("c", "C"), ("d", "D")]
        adapter = BranchTestProviderAdapter(server1, server2, formats)
        suite = adapter.adapt(input_test)
        tests = list(iter(suite))
        self.assertEqual(2, len(tests))
        self.assertEqual(tests[0].branch_format, formats[0][0])
        self.assertEqual(tests[0].bzrdir_format, formats[0][1])
        self.assertEqual(tests[0].transport_server, server1)
        self.assertEqual(tests[0].transport_readonly_server, server2)
        self.assertEqual(tests[1].branch_format, formats[1][0])
        self.assertEqual(tests[1].bzrdir_format, formats[1][1])
        self.assertEqual(tests[1].transport_server, server1)
        self.assertEqual(tests[1].transport_readonly_server, server2)


class TestBzrDirProviderAdapter(TestCase):
    """A group of tests that test the bzr dir implementation test adapter."""

    def test_adapted_tests(self):
        # check that constructor parameters are passed through to the adapted
        # test.
        from bzrlib.bzrdir import BzrDirTestProviderAdapter
        input_test = TestBzrDirProviderAdapter(
            "test_adapted_tests")
        vfs_factory = "v"
        server1 = "a"
        server2 = "b"
        formats = ["c", "d"]
        adapter = BzrDirTestProviderAdapter(vfs_factory,
            server1, server2, formats)
        suite = adapter.adapt(input_test)
        tests = list(iter(suite))
        self.assertEqual(2, len(tests))
        self.assertEqual(tests[0].bzrdir_format, formats[0])
        self.assertEqual(tests[0].vfs_transport_factory, vfs_factory)
        self.assertEqual(tests[0].transport_server, server1)
        self.assertEqual(tests[0].transport_readonly_server, server2)
        self.assertEqual(tests[1].bzrdir_format, formats[1])
        self.assertEqual(tests[1].vfs_transport_factory, vfs_factory)
        self.assertEqual(tests[1].transport_server, server1)
        self.assertEqual(tests[1].transport_readonly_server, server2)


class TestRepositoryProviderAdapter(TestCase):
    """A group of tests that test the repository implementation test adapter."""

    def test_adapted_tests(self):
        # check that constructor parameters are passed through to the adapted
        # test.
        from bzrlib.repository import RepositoryTestProviderAdapter
        input_test = TestRepositoryProviderAdapter(
            "test_adapted_tests")
        server1 = "a"
        server2 = "b"
        formats = [("c", "C"), ("d", "D")]
        adapter = RepositoryTestProviderAdapter(server1, server2, formats)
        suite = adapter.adapt(input_test)
        tests = list(iter(suite))
        self.assertEqual(2, len(tests))
        self.assertEqual(tests[0].bzrdir_format, formats[0][1])
        self.assertEqual(tests[0].repository_format, formats[0][0])
        self.assertEqual(tests[0].transport_server, server1)
        self.assertEqual(tests[0].transport_readonly_server, server2)
        self.assertEqual(tests[1].bzrdir_format, formats[1][1])
        self.assertEqual(tests[1].repository_format, formats[1][0])
        self.assertEqual(tests[1].transport_server, server1)
        self.assertEqual(tests[1].transport_readonly_server, server2)

    def test_setting_vfs_transport(self):
        """The vfs_transport_factory can be set optionally."""
        from bzrlib.repository import RepositoryTestProviderAdapter
        input_test = TestRepositoryProviderAdapter(
            "test_adapted_tests")
        formats = [("c", "C")]
        adapter = RepositoryTestProviderAdapter(None, None, formats,
            vfs_transport_factory="vfs")
        suite = adapter.adapt(input_test)
        tests = list(iter(suite))
        self.assertEqual(1, len(tests))
        self.assertEqual(tests[0].vfs_transport_factory, "vfs")


class TestInterRepositoryProviderAdapter(TestCase):
    """A group of tests that test the InterRepository test adapter."""

    def test_adapted_tests(self):
        # check that constructor parameters are passed through to the adapted
        # test.
        from bzrlib.repository import InterRepositoryTestProviderAdapter
        input_test = TestInterRepositoryProviderAdapter(
            "test_adapted_tests")
        server1 = "a"
        server2 = "b"
        formats = [(str, "C1", "C2"), (int, "D1", "D2")]
        adapter = InterRepositoryTestProviderAdapter(server1, server2, formats)
        suite = adapter.adapt(input_test)
        tests = list(iter(suite))
        self.assertEqual(2, len(tests))
        self.assertEqual(tests[0].interrepo_class, formats[0][0])
        self.assertEqual(tests[0].repository_format, formats[0][1])
        self.assertEqual(tests[0].repository_format_to, formats[0][2])
        self.assertEqual(tests[0].transport_server, server1)
        self.assertEqual(tests[0].transport_readonly_server, server2)
        self.assertEqual(tests[1].interrepo_class, formats[1][0])
        self.assertEqual(tests[1].repository_format, formats[1][1])
        self.assertEqual(tests[1].repository_format_to, formats[1][2])
        self.assertEqual(tests[1].transport_server, server1)
        self.assertEqual(tests[1].transport_readonly_server, server2)


class TestInterVersionedFileProviderAdapter(TestCase):
    """A group of tests that test the InterVersionedFile test adapter."""

    def test_adapted_tests(self):
        # check that constructor parameters are passed through to the adapted
        # test.
        from bzrlib.versionedfile import InterVersionedFileTestProviderAdapter
        input_test = TestInterRepositoryProviderAdapter(
            "test_adapted_tests")
        server1 = "a"
        server2 = "b"
        formats = [(str, "C1", "C2"), (int, "D1", "D2")]
        adapter = InterVersionedFileTestProviderAdapter(server1, server2, formats)
        suite = adapter.adapt(input_test)
        tests = list(iter(suite))
        self.assertEqual(2, len(tests))
        self.assertEqual(tests[0].interversionedfile_class, formats[0][0])
        self.assertEqual(tests[0].versionedfile_factory, formats[0][1])
        self.assertEqual(tests[0].versionedfile_factory_to, formats[0][2])
        self.assertEqual(tests[0].transport_server, server1)
        self.assertEqual(tests[0].transport_readonly_server, server2)
        self.assertEqual(tests[1].interversionedfile_class, formats[1][0])
        self.assertEqual(tests[1].versionedfile_factory, formats[1][1])
        self.assertEqual(tests[1].versionedfile_factory_to, formats[1][2])
        self.assertEqual(tests[1].transport_server, server1)
        self.assertEqual(tests[1].transport_readonly_server, server2)


class TestRevisionStoreProviderAdapter(TestCase):
    """A group of tests that test the RevisionStore test adapter."""

    def test_adapted_tests(self):
        # check that constructor parameters are passed through to the adapted
        # test.
        from bzrlib.store.revision import RevisionStoreTestProviderAdapter
        input_test = TestRevisionStoreProviderAdapter(
            "test_adapted_tests")
        # revision stores need a store factory - i.e. RevisionKnit
        #, a readonly and rw transport 
        # transport servers:
        server1 = "a"
        server2 = "b"
        store_factories = ["c", "d"]
        adapter = RevisionStoreTestProviderAdapter(server1, server2, store_factories)
        suite = adapter.adapt(input_test)
        tests = list(iter(suite))
        self.assertEqual(2, len(tests))
        self.assertEqual(tests[0].store_factory, store_factories[0][0])
        self.assertEqual(tests[0].transport_server, server1)
        self.assertEqual(tests[0].transport_readonly_server, server2)
        self.assertEqual(tests[1].store_factory, store_factories[1][0])
        self.assertEqual(tests[1].transport_server, server1)
        self.assertEqual(tests[1].transport_readonly_server, server2)


class TestWorkingTreeProviderAdapter(TestCase):
    """A group of tests that test the workingtree implementation test adapter."""

    def test_adapted_tests(self):
        # check that constructor parameters are passed through to the adapted
        # test.
        from bzrlib.workingtree import WorkingTreeTestProviderAdapter
        input_test = TestWorkingTreeProviderAdapter(
            "test_adapted_tests")
        server1 = "a"
        server2 = "b"
        formats = [("c", "C"), ("d", "D")]
        adapter = WorkingTreeTestProviderAdapter(server1, server2, formats)
        suite = adapter.adapt(input_test)
        tests = list(iter(suite))
        self.assertEqual(2, len(tests))
        self.assertEqual(tests[0].workingtree_format, formats[0][0])
        self.assertEqual(tests[0].bzrdir_format, formats[0][1])
        self.assertEqual(tests[0].transport_server, server1)
        self.assertEqual(tests[0].transport_readonly_server, server2)
        self.assertEqual(tests[1].workingtree_format, formats[1][0])
        self.assertEqual(tests[1].bzrdir_format, formats[1][1])
        self.assertEqual(tests[1].transport_server, server1)
        self.assertEqual(tests[1].transport_readonly_server, server2)


class TestTreeProviderAdapter(TestCase):
    """Test the setup of tree_implementation tests."""

    def test_adapted_tests(self):
        # the tree implementation adapter is meant to setup one instance for
        # each working tree format, and one additional instance that will
        # use the default wt format, but create a revision tree for the tests.
        # this means that the wt ones should have the workingtree_to_test_tree
        # attribute set to 'return_parameter' and the revision one set to
        # revision_tree_from_workingtree.

        from bzrlib.tests.tree_implementations import (
            TreeTestProviderAdapter,
            return_parameter,
            revision_tree_from_workingtree
            )
        from bzrlib.workingtree import WorkingTreeFormat, WorkingTreeFormat3
        input_test = TestTreeProviderAdapter(
            "test_adapted_tests")
        server1 = "a"
        server2 = "b"
        formats = [("c", "C"), ("d", "D")]
        adapter = TreeTestProviderAdapter(server1, server2, formats)
        suite = adapter.adapt(input_test)
        tests = list(iter(suite))
        self.assertEqual(4, len(tests))
        # this must match the default format setp up in
        # TreeTestProviderAdapter.adapt
        default_format = WorkingTreeFormat3
        self.assertEqual(tests[0].workingtree_format, formats[0][0])
        self.assertEqual(tests[0].bzrdir_format, formats[0][1])
        self.assertEqual(tests[0].transport_server, server1)
        self.assertEqual(tests[0].transport_readonly_server, server2)
        self.assertEqual(tests[0].workingtree_to_test_tree, return_parameter)
        self.assertEqual(tests[1].workingtree_format, formats[1][0])
        self.assertEqual(tests[1].bzrdir_format, formats[1][1])
        self.assertEqual(tests[1].transport_server, server1)
        self.assertEqual(tests[1].transport_readonly_server, server2)
        self.assertEqual(tests[1].workingtree_to_test_tree, return_parameter)
        self.assertIsInstance(tests[2].workingtree_format, default_format)
        #self.assertEqual(tests[2].bzrdir_format,
        #                 default_format._matchingbzrdir)
        self.assertEqual(tests[2].transport_server, server1)
        self.assertEqual(tests[2].transport_readonly_server, server2)
        self.assertEqual(tests[2].workingtree_to_test_tree,
            revision_tree_from_workingtree)


class TestInterTreeProviderAdapter(TestCase):
    """A group of tests that test the InterTreeTestAdapter."""

    def test_adapted_tests(self):
        # check that constructor parameters are passed through to the adapted
        # test.
        # for InterTree tests we want the machinery to bring up two trees in
        # each instance: the base one, and the one we are interacting with.
        # because each optimiser can be direction specific, we need to test
        # each optimiser in its chosen direction.
        # unlike the TestProviderAdapter we dont want to automatically add a
        # parameterised one for WorkingTree - the optimisers will tell us what
        # ones to add.
        from bzrlib.tests.tree_implementations import (
            return_parameter,
            revision_tree_from_workingtree
            )
        from bzrlib.tests.intertree_implementations import (
            InterTreeTestProviderAdapter,
            )
        from bzrlib.workingtree import WorkingTreeFormat2, WorkingTreeFormat3
        input_test = TestInterTreeProviderAdapter(
            "test_adapted_tests")
        server1 = "a"
        server2 = "b"
        format1 = WorkingTreeFormat2()
        format2 = WorkingTreeFormat3()
        formats = [(str, format1, format2, "converter1"),
            (int, format2, format1, "converter2")]
        adapter = InterTreeTestProviderAdapter(server1, server2, formats)
        suite = adapter.adapt(input_test)
        tests = list(iter(suite))
        self.assertEqual(2, len(tests))
        self.assertEqual(tests[0].intertree_class, formats[0][0])
        self.assertEqual(tests[0].workingtree_format, formats[0][1])
        self.assertEqual(tests[0].workingtree_format_to, formats[0][2])
        self.assertEqual(tests[0].mutable_trees_to_test_trees, formats[0][3])
        self.assertEqual(tests[0].workingtree_to_test_tree, return_parameter)
        self.assertEqual(tests[0].transport_server, server1)
        self.assertEqual(tests[0].transport_readonly_server, server2)
        self.assertEqual(tests[1].intertree_class, formats[1][0])
        self.assertEqual(tests[1].workingtree_format, formats[1][1])
        self.assertEqual(tests[1].workingtree_format_to, formats[1][2])
        self.assertEqual(tests[1].mutable_trees_to_test_trees, formats[1][3])
        self.assertEqual(tests[1].workingtree_to_test_tree, return_parameter)
        self.assertEqual(tests[1].transport_server, server1)
        self.assertEqual(tests[1].transport_readonly_server, server2)


class TestTestCaseInTempDir(TestCaseInTempDir):

    def test_home_is_not_working(self):
        self.assertNotEqual(self.test_dir, self.test_home_dir)
        cwd = osutils.getcwd()
        self.assertEqual(self.test_dir, cwd)
        self.assertEqual(self.test_home_dir, os.environ['HOME'])


class TestTestCaseWithMemoryTransport(TestCaseWithMemoryTransport):

    def test_home_is_non_existant_dir_under_root(self):
        """The test_home_dir for TestCaseWithMemoryTransport is missing.

        This is because TestCaseWithMemoryTransport is for tests that do not
        need any disk resources: they should be hooked into bzrlib in such a 
        way that no global settings are being changed by the test (only a 
        few tests should need to do that), and having a missing dir as home is
        an effective way to ensure that this is the case.
        """
        self.assertEqual(self.TEST_ROOT + "/MemoryTransportMissingHomeDir",
            self.test_home_dir)
        self.assertEqual(self.test_home_dir, os.environ['HOME'])
        
    def test_cwd_is_TEST_ROOT(self):
        self.assertEqual(self.test_dir, self.TEST_ROOT)
        cwd = osutils.getcwd()
        self.assertEqual(self.test_dir, cwd)

    def test_make_branch_and_memory_tree(self):
        """In TestCaseWithMemoryTransport we should not make the branch on disk.

        This is hard to comprehensively robustly test, so we settle for making
        a branch and checking no directory was created at its relpath.
        """
        tree = self.make_branch_and_memory_tree('dir')
        # Guard against regression into MemoryTransport leaking
        # files to disk instead of keeping them in memory.
        self.failIf(osutils.lexists('dir'))
        self.assertIsInstance(tree, memorytree.MemoryTree)

    def test_make_branch_and_memory_tree_with_format(self):
        """make_branch_and_memory_tree should accept a format option."""
        format = bzrdir.BzrDirMetaFormat1()
        format.repository_format = weaverepo.RepositoryFormat7()
        tree = self.make_branch_and_memory_tree('dir', format=format)
        # Guard against regression into MemoryTransport leaking
        # files to disk instead of keeping them in memory.
        self.failIf(osutils.lexists('dir'))
        self.assertIsInstance(tree, memorytree.MemoryTree)
        self.assertEqual(format.repository_format.__class__,
            tree.branch.repository._format.__class__)


class TestTestCaseWithTransport(TestCaseWithTransport):
    """Tests for the convenience functions TestCaseWithTransport introduces."""

    def test_get_readonly_url_none(self):
        from bzrlib.transport import get_transport
        from bzrlib.transport.memory import MemoryServer
        from bzrlib.transport.readonly import ReadonlyTransportDecorator
        self.vfs_transport_factory = MemoryServer
        self.transport_readonly_server = None
        # calling get_readonly_transport() constructs a decorator on the url
        # for the server
        url = self.get_readonly_url()
        url2 = self.get_readonly_url('foo/bar')
        t = get_transport(url)
        t2 = get_transport(url2)
        self.failUnless(isinstance(t, ReadonlyTransportDecorator))
        self.failUnless(isinstance(t2, ReadonlyTransportDecorator))
        self.assertEqual(t2.base[:-1], t.abspath('foo/bar'))

    def test_get_readonly_url_http(self):
        from bzrlib.tests.HttpServer import HttpServer
        from bzrlib.transport import get_transport
        from bzrlib.transport.local import LocalURLServer
        from bzrlib.transport.http import HttpTransportBase
        self.transport_server = LocalURLServer
        self.transport_readonly_server = HttpServer
        # calling get_readonly_transport() gives us a HTTP server instance.
        url = self.get_readonly_url()
        url2 = self.get_readonly_url('foo/bar')
        # the transport returned may be any HttpTransportBase subclass
        t = get_transport(url)
        t2 = get_transport(url2)
        self.failUnless(isinstance(t, HttpTransportBase))
        self.failUnless(isinstance(t2, HttpTransportBase))
        self.assertEqual(t2.base[:-1], t.abspath('foo/bar'))

    def test_is_directory(self):
        """Test assertIsDirectory assertion"""
        t = self.get_transport()
        self.build_tree(['a_dir/', 'a_file'], transport=t)
        self.assertIsDirectory('a_dir', t)
        self.assertRaises(AssertionError, self.assertIsDirectory, 'a_file', t)
        self.assertRaises(AssertionError, self.assertIsDirectory, 'not_here', t)


class TestTestCaseTransports(TestCaseWithTransport):

    def setUp(self):
        super(TestTestCaseTransports, self).setUp()
        self.vfs_transport_factory = MemoryServer

    def test_make_bzrdir_preserves_transport(self):
        t = self.get_transport()
        result_bzrdir = self.make_bzrdir('subdir')
        self.assertIsInstance(result_bzrdir.transport, 
                              MemoryTransport)
        # should not be on disk, should only be in memory
        self.failIfExists('subdir')


class TestChrootedTest(ChrootedTestCase):

    def test_root_is_root(self):
        from bzrlib.transport import get_transport
        t = get_transport(self.get_readonly_url())
        url = t.base
        self.assertEqual(url, t.clone('..').base)


class MockProgress(_BaseProgressBar):
    """Progress-bar standin that records calls.

    Useful for testing pb using code.
    """

    def __init__(self):
        _BaseProgressBar.__init__(self)
        self.calls = []

    def tick(self):
        self.calls.append(('tick',))

    def update(self, msg=None, current=None, total=None):
        self.calls.append(('update', msg, current, total))

    def clear(self):
        self.calls.append(('clear',))

    def note(self, msg, *args):
        self.calls.append(('note', msg, args))


class TestTestResult(TestCase):

    def test_elapsed_time_with_benchmarking(self):
        result = bzrlib.tests.TextTestResult(self._log_file,
                                        descriptions=0,
                                        verbosity=1,
                                        )
        result._recordTestStartTime()
        time.sleep(0.003)
        result.extractBenchmarkTime(self)
        timed_string = result._testTimeString()
        # without explicit benchmarking, we should get a simple time.
        self.assertContainsRe(timed_string, "^ *[ 1-9][0-9]ms$")
        # if a benchmark time is given, we want a x of y style result.
        self.time(time.sleep, 0.001)
        result.extractBenchmarkTime(self)
        timed_string = result._testTimeString()
        self.assertContainsRe(timed_string, "^ *[ 1-9][0-9]ms/ *[ 1-9][0-9]ms$")
        # extracting the time from a non-bzrlib testcase sets to None
        result._recordTestStartTime()
        result.extractBenchmarkTime(
            unittest.FunctionTestCase(self.test_elapsed_time_with_benchmarking))
        timed_string = result._testTimeString()
        self.assertContainsRe(timed_string, "^ *[ 1-9][0-9]ms$")
        # cheat. Yes, wash thy mouth out with soap.
        self._benchtime = None

    def test_assigned_benchmark_file_stores_date(self):
        output = StringIO()
        result = bzrlib.tests.TextTestResult(self._log_file,
                                        descriptions=0,
                                        verbosity=1,
                                        bench_history=output
                                        )
        output_string = output.getvalue()
        
        # if you are wondering about the regexp please read the comment in
        # test_bench_history (bzrlib.tests.test_selftest.TestRunner)
        # XXX: what comment?  -- Andrew Bennetts
        self.assertContainsRe(output_string, "--date [0-9.]+")

    def test_benchhistory_records_test_times(self):
        result_stream = StringIO()
        result = bzrlib.tests.TextTestResult(
            self._log_file,
            descriptions=0,
            verbosity=1,
            bench_history=result_stream
            )

        # we want profile a call and check that its test duration is recorded
        # make a new test instance that when run will generate a benchmark
        example_test_case = TestTestResult("_time_hello_world_encoding")
        # execute the test, which should succeed and record times
        example_test_case.run(result)
        lines = result_stream.getvalue().splitlines()
        self.assertEqual(2, len(lines))
        self.assertContainsRe(lines[1],
            " *[0-9]+ms bzrlib.tests.test_selftest.TestTestResult"
            "._time_hello_world_encoding")
 
    def _time_hello_world_encoding(self):
        """Profile two sleep calls
        
        This is used to exercise the test framework.
        """
        self.time(unicode, 'hello', errors='replace')
        self.time(unicode, 'world', errors='replace')

    def test_lsprofiling(self):
        """Verbose test result prints lsprof statistics from test cases."""
        try:
            import bzrlib.lsprof
        except ImportError:
            raise TestSkipped("lsprof not installed.")
        result_stream = StringIO()
        result = bzrlib.tests.VerboseTestResult(
            unittest._WritelnDecorator(result_stream),
            descriptions=0,
            verbosity=2,
            )
        # we want profile a call of some sort and check it is output by
        # addSuccess. We dont care about addError or addFailure as they
        # are not that interesting for performance tuning.
        # make a new test instance that when run will generate a profile
        example_test_case = TestTestResult("_time_hello_world_encoding")
        example_test_case._gather_lsprof_in_benchmarks = True
        # execute the test, which should succeed and record profiles
        example_test_case.run(result)
        # lsprofile_something()
        # if this worked we want 
        # LSProf output for <built in function unicode> (['hello'], {'errors': 'replace'})
        #    CallCount    Recursive    Total(ms)   Inline(ms) module:lineno(function)
        # (the lsprof header)
        # ... an arbitrary number of lines
        # and the function call which is time.sleep.
        #           1        0            ???         ???       ???(sleep) 
        # and then repeated but with 'world', rather than 'hello'.
        # this should appear in the output stream of our test result.
        output = result_stream.getvalue()
        self.assertContainsRe(output,
            r"LSProf output for <type 'unicode'>\(\('hello',\), {'errors': 'replace'}\)")
        self.assertContainsRe(output,
            r" *CallCount *Recursive *Total\(ms\) *Inline\(ms\) *module:lineno\(function\)\n")
        self.assertContainsRe(output,
            r"( +1 +0 +0\.\d+ +0\.\d+ +<method 'disable' of '_lsprof\.Profiler' objects>\n)?")
        self.assertContainsRe(output,
            r"LSProf output for <type 'unicode'>\(\('world',\), {'errors': 'replace'}\)\n")

    def test_known_failure(self):
        """A KnownFailure being raised should trigger several result actions."""
        class InstrumentedTestResult(ExtendedTestResult):

            def report_test_start(self, test): pass
            def report_known_failure(self, test, err):
                self._call = test, err
        result = InstrumentedTestResult(None, None, None, None)
        def test_function():
            raise KnownFailure('failed!')
        test = unittest.FunctionTestCase(test_function)
        test.run(result)
        # it should invoke 'report_known_failure'.
        self.assertEqual(2, len(result._call))
        self.assertEqual(test, result._call[0])
        self.assertEqual(KnownFailure, result._call[1][0])
        self.assertIsInstance(result._call[1][1], KnownFailure)
        # we dont introspec the traceback, if the rest is ok, it would be
        # exceptional for it not to be.
        # it should update the known_failure_count on the object.
        self.assertEqual(1, result.known_failure_count)
        # the result should be successful.
        self.assertTrue(result.wasSuccessful())

    def test_verbose_report_known_failure(self):
        # verbose test output formatting
        result_stream = StringIO()
        result = bzrlib.tests.VerboseTestResult(
            unittest._WritelnDecorator(result_stream),
            descriptions=0,
            verbosity=2,
            )
        test = self.get_passing_test()
        result.startTest(test)
        result.extractBenchmarkTime(test)
        prefix = len(result_stream.getvalue())
        # the err parameter has the shape:
        # (class, exception object, traceback)
        # KnownFailures dont get their tracebacks shown though, so we
        # can skip that.
        err = (KnownFailure, KnownFailure('foo'), None)
        result.report_known_failure(test, err)
        output = result_stream.getvalue()[prefix:]
        lines = output.splitlines()
        self.assertEqual(lines, ['XFAIL                   0ms', '    foo'])
    
    def test_text_report_known_failure(self):
        # text test output formatting
        pb = MockProgress()
        result = bzrlib.tests.TextTestResult(
            None,
            descriptions=0,
            verbosity=1,
            pb=pb,
            )
        test = self.get_passing_test()
        # this seeds the state to handle reporting the test.
        result.startTest(test)
        result.extractBenchmarkTime(test)
        # the err parameter has the shape:
        # (class, exception object, traceback)
        # KnownFailures dont get their tracebacks shown though, so we
        # can skip that.
        err = (KnownFailure, KnownFailure('foo'), None)
        result.report_known_failure(test, err)
        self.assertEqual(
            [
            ('update', '[1 in 0s] passing_test', None, None),
            ('note', 'XFAIL: %s\n%s\n', ('passing_test', err[1]))
            ],
            pb.calls)
        # known_failures should be printed in the summary, so if we run a test
        # after there are some known failures, the update prefix should match
        # this.
        result.known_failure_count = 3
        test.run(result)
        self.assertEqual(
            [
            ('update', '[2 in 0s, 3 known failures] passing_test', None, None),
            ],
            pb.calls[2:])

    def get_passing_test(self):
        """Return a test object that can't be run usefully."""
        def passing_test():
            pass
        return unittest.FunctionTestCase(passing_test)

    def test_add_not_supported(self):
        """Test the behaviour of invoking addNotSupported."""
        class InstrumentedTestResult(ExtendedTestResult):
            def report_test_start(self, test): pass
            def report_unsupported(self, test, feature):
                self._call = test, feature
        result = InstrumentedTestResult(None, None, None, None)
        test = SampleTestCase('_test_pass')
        feature = Feature()
        result.startTest(test)
        result.addNotSupported(test, feature)
        # it should invoke 'report_unsupported'.
        self.assertEqual(2, len(result._call))
        self.assertEqual(test, result._call[0])
        self.assertEqual(feature, result._call[1])
        # the result should be successful.
        self.assertTrue(result.wasSuccessful())
        # it should record the test against a count of tests not run due to
        # this feature.
        self.assertEqual(1, result.unsupported['Feature'])
        # and invoking it again should increment that counter
        result.addNotSupported(test, feature)
        self.assertEqual(2, result.unsupported['Feature'])

    def test_verbose_report_unsupported(self):
        # verbose test output formatting
        result_stream = StringIO()
        result = bzrlib.tests.VerboseTestResult(
            unittest._WritelnDecorator(result_stream),
            descriptions=0,
            verbosity=2,
            )
        test = self.get_passing_test()
        feature = Feature()
        result.startTest(test)
        result.extractBenchmarkTime(test)
        prefix = len(result_stream.getvalue())
        result.report_unsupported(test, feature)
        output = result_stream.getvalue()[prefix:]
        lines = output.splitlines()
        self.assertEqual(lines, ['NODEP                   0ms', "    The feature 'Feature' is not available."])
    
    def test_text_report_unsupported(self):
        # text test output formatting
        pb = MockProgress()
        result = bzrlib.tests.TextTestResult(
            None,
            descriptions=0,
            verbosity=1,
            pb=pb,
            )
        test = self.get_passing_test()
        feature = Feature()
        # this seeds the state to handle reporting the test.
        result.startTest(test)
        result.extractBenchmarkTime(test)
        result.report_unsupported(test, feature)
        # no output on unsupported features
        self.assertEqual(
            [('update', '[1 in 0s] passing_test', None, None)
            ],
            pb.calls)
        # the number of missing features should be printed in the progress
        # summary, so check for that.
        result.unsupported = {'foo':0, 'bar':0}
        test.run(result)
        self.assertEqual(
            [
            ('update', '[2 in 0s, 2 missing features] passing_test', None, None),
            ],
            pb.calls[1:])
    
    def test_unavailable_exception(self):
        """An UnavailableFeature being raised should invoke addNotSupported."""
        class InstrumentedTestResult(ExtendedTestResult):

            def report_test_start(self, test): pass
            def addNotSupported(self, test, feature):
                self._call = test, feature
        result = InstrumentedTestResult(None, None, None, None)
        feature = Feature()
        def test_function():
            raise UnavailableFeature(feature)
        test = unittest.FunctionTestCase(test_function)
        test.run(result)
        # it should invoke 'addNotSupported'.
        self.assertEqual(2, len(result._call))
        self.assertEqual(test, result._call[0])
        self.assertEqual(feature, result._call[1])
        # and not count as an error
        self.assertEqual(0, result.error_count)


class TestRunner(TestCase):

    def dummy_test(self):
        pass

    def run_test_runner(self, testrunner, test):
        """Run suite in testrunner, saving global state and restoring it.

        This current saves and restores:
        TestCaseInTempDir.TEST_ROOT
        
        There should be no tests in this file that use bzrlib.tests.TextTestRunner
        without using this convenience method, because of our use of global state.
        """
        old_root = TestCaseInTempDir.TEST_ROOT
        try:
            TestCaseInTempDir.TEST_ROOT = None
            return testrunner.run(test)
        finally:
            TestCaseInTempDir.TEST_ROOT = old_root

    def test_known_failure_failed_run(self):
        # run a test that generates a known failure which should be printed in
        # the final output when real failures occur.
        def known_failure_test():
            raise KnownFailure('failed')
        test = unittest.TestSuite()
        test.addTest(unittest.FunctionTestCase(known_failure_test))
        def failing_test():
            raise AssertionError('foo')
        test.addTest(unittest.FunctionTestCase(failing_test))
        stream = StringIO()
        runner = TextTestRunner(stream=stream)
        result = self.run_test_runner(runner, test)
        lines = stream.getvalue().splitlines()
        self.assertEqual([
            '',
            '======================================================================',
            'FAIL: unittest.FunctionTestCase (failing_test)',
            '----------------------------------------------------------------------',
            'Traceback (most recent call last):',
            '    raise AssertionError(\'foo\')',
            'AssertionError: foo',
            '',
            '----------------------------------------------------------------------',
            '',
            'FAILED (failures=1, known_failure_count=1)'],
            lines[0:5] + lines[6:10] + lines[11:])

    def test_known_failure_ok_run(self):
        # run a test that generates a known failure which should be printed in the final output.
        def known_failure_test():
            raise KnownFailure('failed')
        test = unittest.FunctionTestCase(known_failure_test)
        stream = StringIO()
        runner = TextTestRunner(stream=stream)
        result = self.run_test_runner(runner, test)
        self.assertEqual(
            '\n'
            '----------------------------------------------------------------------\n'
            'Ran 1 test in 0.000s\n'
            '\n'
            'OK (known_failures=1)\n',
            stream.getvalue())

    def test_skipped_test(self):
        # run a test that is skipped, and check the suite as a whole still
        # succeeds.
        # skipping_test must be hidden in here so it's not run as a real test
        def skipping_test():
            raise TestSkipped('test intentionally skipped')

        runner = TextTestRunner(stream=self._log_file, keep_output=True)
        test = unittest.FunctionTestCase(skipping_test)
        result = self.run_test_runner(runner, test)
        self.assertTrue(result.wasSuccessful())

    def test_skipped_from_setup(self):
        class SkippedSetupTest(TestCase):

            def setUp(self):
                self.counter = 1
                self.addCleanup(self.cleanup)
                raise TestSkipped('skipped setup')

            def test_skip(self):
                self.fail('test reached')

            def cleanup(self):
                self.counter -= 1

        runner = TextTestRunner(stream=self._log_file, keep_output=True)
        test = SkippedSetupTest('test_skip')
        result = self.run_test_runner(runner, test)
        self.assertTrue(result.wasSuccessful())
        # Check if cleanup was called the right number of times.
        self.assertEqual(0, test.counter)

    def test_skipped_from_test(self):
        class SkippedTest(TestCase):

            def setUp(self):
                self.counter = 1
                self.addCleanup(self.cleanup)

            def test_skip(self):
                raise TestSkipped('skipped test')

            def cleanup(self):
                self.counter -= 1

        runner = TextTestRunner(stream=self._log_file, keep_output=True)
        test = SkippedTest('test_skip')
        result = self.run_test_runner(runner, test)
        self.assertTrue(result.wasSuccessful())
        # Check if cleanup was called the right number of times.
        self.assertEqual(0, test.counter)

    def test_unsupported_features_listed(self):
        """When unsupported features are encountered they are detailed."""
        class Feature1(Feature):
            def _probe(self): return False
        class Feature2(Feature):
            def _probe(self): return False
        # create sample tests
        test1 = SampleTestCase('_test_pass')
        test1._test_needs_features = [Feature1()]
        test2 = SampleTestCase('_test_pass')
        test2._test_needs_features = [Feature2()]
        test = unittest.TestSuite()
        test.addTest(test1)
        test.addTest(test2)
        stream = StringIO()
        runner = TextTestRunner(stream=stream)
        result = self.run_test_runner(runner, test)
        lines = stream.getvalue().splitlines()
        self.assertEqual([
            'OK',
            "Missing feature 'Feature1' skipped 1 tests.",
            "Missing feature 'Feature2' skipped 1 tests.",
            ],
            lines[-3:])

    def test_bench_history(self):
        # tests that the running the benchmark produces a history file
        # containing a timestamp and the revision id of the bzrlib source which
        # was tested.
        workingtree = _get_bzr_source_tree()
        test = TestRunner('dummy_test')
        output = StringIO()
        runner = TextTestRunner(stream=self._log_file, bench_history=output)
        result = self.run_test_runner(runner, test)
        output_string = output.getvalue()
        self.assertContainsRe(output_string, "--date [0-9.]+")
        if workingtree is not None:
            revision_id = workingtree.get_parent_ids()[0]
            self.assertEndsWith(output_string.rstrip(), revision_id)

    def test_success_log_deleted(self):
        """Successful tests have their log deleted"""

        class LogTester(TestCase):

            def test_success(self):
                self.log('this will be removed\n')

        sio = cStringIO.StringIO()
        runner = TextTestRunner(stream=sio)
        test = LogTester('test_success')
        result = self.run_test_runner(runner, test)

        log = test._get_log()
        self.assertEqual("DELETED log file to reduce memory footprint", log)
        self.assertEqual('', test._log_contents)
        self.assertIs(None, test._log_file_name)

    def test_fail_log_kept(self):
        """Failed tests have their log kept"""

        class LogTester(TestCase):

            def test_fail(self):
                self.log('this will be kept\n')
                self.fail('this test fails')

        sio = cStringIO.StringIO()
        runner = TextTestRunner(stream=sio)
        test = LogTester('test_fail')
        result = self.run_test_runner(runner, test)

        text = sio.getvalue()
        self.assertContainsRe(text, 'this will be kept')
        self.assertContainsRe(text, 'this test fails')

        log = test._get_log()
        self.assertContainsRe(log, 'this will be kept')
        self.assertEqual(log, test._log_contents)

    def test_error_log_kept(self):
        """Tests with errors have their log kept"""

        class LogTester(TestCase):

            def test_error(self):
                self.log('this will be kept\n')
                raise ValueError('random exception raised')

        sio = cStringIO.StringIO()
        runner = TextTestRunner(stream=sio)
        test = LogTester('test_error')
        result = self.run_test_runner(runner, test)

        text = sio.getvalue()
        self.assertContainsRe(text, 'this will be kept')
        self.assertContainsRe(text, 'random exception raised')

        log = test._get_log()
        self.assertContainsRe(log, 'this will be kept')
        self.assertEqual(log, test._log_contents)


class SampleTestCase(TestCase):

    def _test_pass(self):
        pass


class TestTestCase(TestCase):
    """Tests that test the core bzrlib TestCase."""

    def inner_test(self):
        # the inner child test
        note("inner_test")

    def outer_child(self):
        # the outer child test
        note("outer_start")
        self.inner_test = TestTestCase("inner_child")
        result = bzrlib.tests.TextTestResult(self._log_file,
                                        descriptions=0,
                                        verbosity=1)
        self.inner_test.run(result)
        note("outer finish")

    def test_trace_nesting(self):
        # this tests that each test case nests its trace facility correctly.
        # we do this by running a test case manually. That test case (A)
        # should setup a new log, log content to it, setup a child case (B),
        # which should log independently, then case (A) should log a trailer
        # and return.
        # we do two nested children so that we can verify the state of the 
        # logs after the outer child finishes is correct, which a bad clean
        # up routine in tearDown might trigger a fault in our test with only
        # one child, we should instead see the bad result inside our test with
        # the two children.
        # the outer child test
        original_trace = bzrlib.trace._trace_file
        outer_test = TestTestCase("outer_child")
        result = bzrlib.tests.TextTestResult(self._log_file,
                                        descriptions=0,
                                        verbosity=1)
        outer_test.run(result)
        self.assertEqual(original_trace, bzrlib.trace._trace_file)

    def method_that_times_a_bit_twice(self):
        # call self.time twice to ensure it aggregates
        self.time(time.sleep, 0.007)
        self.time(time.sleep, 0.007)

    def test_time_creates_benchmark_in_result(self):
        """Test that the TestCase.time() method accumulates a benchmark time."""
        sample_test = TestTestCase("method_that_times_a_bit_twice")
        output_stream = StringIO()
        result = bzrlib.tests.VerboseTestResult(
            unittest._WritelnDecorator(output_stream),
            descriptions=0,
            verbosity=2,
            num_tests=sample_test.countTestCases())
        sample_test.run(result)
        self.assertContainsRe(
            output_stream.getvalue(),
            r"\d+ms/ +\d+ms\n$")

    def test_hooks_sanitised(self):
        """The bzrlib hooks should be sanitised by setUp."""
        self.assertEqual(bzrlib.branch.BranchHooks(),
            bzrlib.branch.Branch.hooks)
        self.assertEqual(bzrlib.smart.server.SmartServerHooks(),
            bzrlib.smart.server.SmartTCPServer.hooks)

    def test__gather_lsprof_in_benchmarks(self):
        """When _gather_lsprof_in_benchmarks is on, accumulate profile data.
        
        Each self.time() call is individually and separately profiled.
        """
        try:
            import bzrlib.lsprof
        except ImportError:
            raise TestSkipped("lsprof not installed.")
        # overrides the class member with an instance member so no cleanup 
        # needed.
        self._gather_lsprof_in_benchmarks = True
        self.time(time.sleep, 0.000)
        self.time(time.sleep, 0.003)
        self.assertEqual(2, len(self._benchcalls))
        self.assertEqual((time.sleep, (0.000,), {}), self._benchcalls[0][0])
        self.assertEqual((time.sleep, (0.003,), {}), self._benchcalls[1][0])
        self.assertIsInstance(self._benchcalls[0][1], bzrlib.lsprof.Stats)
        self.assertIsInstance(self._benchcalls[1][1], bzrlib.lsprof.Stats)

    def test_knownFailure(self):
        """Self.knownFailure() should raise a KnownFailure exception."""
        self.assertRaises(KnownFailure, self.knownFailure, "A Failure")

    def test_requireFeature_available(self):
        """self.requireFeature(available) is a no-op."""
        class Available(Feature):
            def _probe(self):return True
        feature = Available()
        self.requireFeature(feature)

    def test_requireFeature_unavailable(self):
        """self.requireFeature(unavailable) raises UnavailableFeature."""
        class Unavailable(Feature):
            def _probe(self):return False
        feature = Unavailable()
        self.assertRaises(UnavailableFeature, self.requireFeature, feature)

    def test_run_no_parameters(self):
        test = SampleTestCase('_test_pass')
        test.run()
    
    def test_run_enabled_unittest_result(self):
        """Test we revert to regular behaviour when the test is enabled."""
        test = SampleTestCase('_test_pass')
        class EnabledFeature(object):
            def available(self):
                return True
        test._test_needs_features = [EnabledFeature()]
        result = unittest.TestResult()
        test.run(result)
        self.assertEqual(1, result.testsRun)
        self.assertEqual([], result.errors)
        self.assertEqual([], result.failures)

    def test_run_disabled_unittest_result(self):
        """Test our compatability for disabled tests with unittest results."""
        test = SampleTestCase('_test_pass')
        class DisabledFeature(object):
            def available(self):
                return False
        test._test_needs_features = [DisabledFeature()]
        result = unittest.TestResult()
        test.run(result)
        self.assertEqual(1, result.testsRun)
        self.assertEqual([], result.errors)
        self.assertEqual([], result.failures)

    def test_run_disabled_supporting_result(self):
        """Test disabled tests behaviour with support aware results."""
        test = SampleTestCase('_test_pass')
        class DisabledFeature(object):
            def available(self):
                return False
        the_feature = DisabledFeature()
        test._test_needs_features = [the_feature]
        class InstrumentedTestResult(unittest.TestResult):
            def __init__(self):
                unittest.TestResult.__init__(self)
                self.calls = []
            def startTest(self, test):
                self.calls.append(('startTest', test))
            def stopTest(self, test):
                self.calls.append(('stopTest', test))
            def addNotSupported(self, test, feature):
                self.calls.append(('addNotSupported', test, feature))
        result = InstrumentedTestResult()
        test.run(result)
        self.assertEqual([
            ('startTest', test),
            ('addNotSupported', test, the_feature),
            ('stopTest', test),
            ],
            result.calls)


@symbol_versioning.deprecated_function(zero_eleven)
def sample_deprecated_function():
    """A deprecated function to test applyDeprecated with."""
    return 2


def sample_undeprecated_function(a_param):
    """A undeprecated function to test applyDeprecated with."""


class ApplyDeprecatedHelper(object):
    """A helper class for ApplyDeprecated tests."""

    @symbol_versioning.deprecated_method(zero_eleven)
    def sample_deprecated_method(self, param_one):
        """A deprecated method for testing with."""
        return param_one

    def sample_normal_method(self):
        """A undeprecated method."""

    @symbol_versioning.deprecated_method(zero_ten)
    def sample_nested_deprecation(self):
        return sample_deprecated_function()


class TestExtraAssertions(TestCase):
    """Tests for new test assertions in bzrlib test suite"""

    def test_assert_isinstance(self):
        self.assertIsInstance(2, int)
        self.assertIsInstance(u'', basestring)
        self.assertRaises(AssertionError, self.assertIsInstance, None, int)
        self.assertRaises(AssertionError, self.assertIsInstance, 23.3, int)

    def test_assertEndsWith(self):
        self.assertEndsWith('foo', 'oo')
        self.assertRaises(AssertionError, self.assertEndsWith, 'o', 'oo')

    def test_applyDeprecated_not_deprecated(self):
        sample_object = ApplyDeprecatedHelper()
        # calling an undeprecated callable raises an assertion
        self.assertRaises(AssertionError, self.applyDeprecated, zero_eleven,
            sample_object.sample_normal_method)
        self.assertRaises(AssertionError, self.applyDeprecated, zero_eleven,
            sample_undeprecated_function, "a param value")
        # calling a deprecated callable (function or method) with the wrong
        # expected deprecation fails.
        self.assertRaises(AssertionError, self.applyDeprecated, zero_ten,
            sample_object.sample_deprecated_method, "a param value")
        self.assertRaises(AssertionError, self.applyDeprecated, zero_ten,
            sample_deprecated_function)
        # calling a deprecated callable (function or method) with the right
        # expected deprecation returns the functions result.
        self.assertEqual("a param value", self.applyDeprecated(zero_eleven,
            sample_object.sample_deprecated_method, "a param value"))
        self.assertEqual(2, self.applyDeprecated(zero_eleven,
            sample_deprecated_function))
        # calling a nested deprecation with the wrong deprecation version
        # fails even if a deeper nested function was deprecated with the 
        # supplied version.
        self.assertRaises(AssertionError, self.applyDeprecated,
            zero_eleven, sample_object.sample_nested_deprecation)
        # calling a nested deprecation with the right deprecation value
        # returns the calls result.
        self.assertEqual(2, self.applyDeprecated(zero_ten,
            sample_object.sample_nested_deprecation))

    def test_callDeprecated(self):
        def testfunc(be_deprecated, result=None):
            if be_deprecated is True:
                symbol_versioning.warn('i am deprecated', DeprecationWarning, 
                                       stacklevel=1)
            return result
        result = self.callDeprecated(['i am deprecated'], testfunc, True)
        self.assertIs(None, result)
        result = self.callDeprecated([], testfunc, False, 'result')
        self.assertEqual('result', result)
        self.callDeprecated(['i am deprecated'], testfunc, be_deprecated=True)
        self.callDeprecated([], testfunc, be_deprecated=False)


class TestConvenienceMakers(TestCaseWithTransport):
    """Test for the make_* convenience functions."""

    def test_make_branch_and_tree_with_format(self):
        # we should be able to supply a format to make_branch_and_tree
        self.make_branch_and_tree('a', format=bzrlib.bzrdir.BzrDirMetaFormat1())
        self.make_branch_and_tree('b', format=bzrlib.bzrdir.BzrDirFormat6())
        self.assertIsInstance(bzrlib.bzrdir.BzrDir.open('a')._format,
                              bzrlib.bzrdir.BzrDirMetaFormat1)
        self.assertIsInstance(bzrlib.bzrdir.BzrDir.open('b')._format,
                              bzrlib.bzrdir.BzrDirFormat6)

    def test_make_branch_and_memory_tree(self):
        # we should be able to get a new branch and a mutable tree from
        # TestCaseWithTransport
        tree = self.make_branch_and_memory_tree('a')
        self.assertIsInstance(tree, bzrlib.memorytree.MemoryTree)


class TestSFTPMakeBranchAndTree(TestCaseWithSFTPServer):

    def test_make_tree_for_sftp_branch(self):
        """Transports backed by local directories create local trees."""

        tree = self.make_branch_and_tree('t1')
        base = tree.bzrdir.root_transport.base
        self.failIf(base.startswith('sftp'),
                'base %r is on sftp but should be local' % base)
        self.assertEquals(tree.bzrdir.root_transport,
                tree.branch.bzrdir.root_transport)
        self.assertEquals(tree.bzrdir.root_transport,
                tree.branch.repository.bzrdir.root_transport)


class TestSelftest(TestCase):
    """Tests of bzrlib.tests.selftest."""

    def test_selftest_benchmark_parameter_invokes_test_suite__benchmark__(self):
        factory_called = []
        def factory():
            factory_called.append(True)
            return TestSuite()
        out = StringIO()
        err = StringIO()
        self.apply_redirected(out, err, None, bzrlib.tests.selftest, 
            test_suite_factory=factory)
        self.assertEqual([True], factory_called)


class TestSelftestCleanOutput(TestCaseInTempDir):

    def test_clean_output(self):
        # test functionality of clean_selftest_output()
        self.build_tree(['test0000.tmp/', 'test0001.tmp/',
                         'bzrlib/', 'tests/',
                         'bzr', 'setup.py', 'test9999.tmp'])

        root = os.getcwdu()
        before = os.listdir(root)
        before.sort()
        self.assertEquals(['bzr','bzrlib','setup.py',
                           'test0000.tmp','test0001.tmp',
                           'test9999.tmp','tests'],
                           before)
        clean_selftest_output(root, quiet=True)
        after = os.listdir(root)
        after.sort()
        self.assertEquals(['bzr','bzrlib','setup.py',
                           'test9999.tmp','tests'],
                           after)

    def test_clean_readonly(self):
        # test for delete read-only files
        self.build_tree(['test0000.tmp/', 'test0000.tmp/foo'])
        osutils.make_readonly('test0000.tmp/foo')
        root = os.getcwdu()
        before = os.listdir(root);  before.sort()
        self.assertEquals(['test0000.tmp'], before)
        clean_selftest_output(root, quiet=True)
        after = os.listdir(root);   after.sort()
        self.assertEquals([], after)


class TestKnownFailure(TestCase):

    def test_known_failure(self):
        """Check that KnownFailure is defined appropriately."""
        # a KnownFailure is an assertion error for compatability with unaware
        # runners.
        self.assertIsInstance(KnownFailure(""), AssertionError)

    def test_expect_failure(self):
        try:
            self.expectFailure("Doomed to failure", self.assertTrue, False)
        except KnownFailure, e:
            self.assertEqual('Doomed to failure', e.args[0])
        try:
            self.expectFailure("Doomed to failure", self.assertTrue, True)
        except AssertionError, e:
            self.assertEqual('Unexpected success.  Should have failed:'
                             ' Doomed to failure', e.args[0])
        else:
            self.fail('Assertion not raised')


class TestFeature(TestCase):

    def test_caching(self):
        """Feature._probe is called by the feature at most once."""
        class InstrumentedFeature(Feature):
            def __init__(self):
                Feature.__init__(self)
                self.calls = []
            def _probe(self):
                self.calls.append('_probe')
                return False
        feature = InstrumentedFeature()
        feature.available()
        self.assertEqual(['_probe'], feature.calls)
        feature.available()
        self.assertEqual(['_probe'], feature.calls)

    def test_named_str(self):
        """Feature.__str__ should thunk to feature_name()."""
        class NamedFeature(Feature):
            def feature_name(self):
                return 'symlinks'
        feature = NamedFeature()
        self.assertEqual('symlinks', str(feature))

    def test_default_str(self):
        """Feature.__str__ should default to __class__.__name__."""
        class NamedFeature(Feature):
            pass
        feature = NamedFeature()
        self.assertEqual('NamedFeature', str(feature))


class TestUnavailableFeature(TestCase):

    def test_access_feature(self):
        feature = Feature()
        exception = UnavailableFeature(feature)
        self.assertIs(feature, exception.args[0])
