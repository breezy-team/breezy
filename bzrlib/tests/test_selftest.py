# Copyright (C) 2005, 2006 by Canonical Ltd
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

"""Tests for the test framework."""

import os
from StringIO import StringIO
import sys
import time
import unittest
import warnings

from bzrlib import osutils
import bzrlib
from bzrlib.progress import _BaseProgressBar
from bzrlib.tests import (
                          ChrootedTestCase,
                          TestCase,
                          TestCaseInTempDir,
                          TestCaseWithTransport,
                          TestSkipped,
                          TestSuite,
                          TextTestRunner,
                          )
from bzrlib.tests.TestUtil import _load_module_by_name
import bzrlib.errors as errors
from bzrlib import symbol_versioning
from bzrlib.trace import note
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
        server1 = "a"
        server2 = "b"
        formats = ["c", "d"]
        adapter = BzrDirTestProviderAdapter(server1, server2, formats)
        suite = adapter.adapt(input_test)
        tests = list(iter(suite))
        self.assertEqual(2, len(tests))
        self.assertEqual(tests[0].bzrdir_format, formats[0])
        self.assertEqual(tests[0].transport_server, server1)
        self.assertEqual(tests[0].transport_readonly_server, server2)
        self.assertEqual(tests[1].bzrdir_format, formats[1])
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
        from bzrlib.workingtree import WorkingTreeFormat
        input_test = TestTreeProviderAdapter(
            "test_adapted_tests")
        server1 = "a"
        server2 = "b"
        formats = [("c", "C"), ("d", "D")]
        adapter = TreeTestProviderAdapter(server1, server2, formats)
        suite = adapter.adapt(input_test)
        tests = list(iter(suite))
        self.assertEqual(3, len(tests))
        default_format = WorkingTreeFormat.get_default_format()
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
        self.assertEqual(tests[2].workingtree_format, default_format)
        self.assertEqual(tests[2].bzrdir_format, default_format._matchingbzrdir)
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
        formats = [(str, format1, format2, False, True),
            (int, format2, format1, False, True)]
        adapter = InterTreeTestProviderAdapter(server1, server2, formats)
        suite = adapter.adapt(input_test)
        tests = list(iter(suite))
        self.assertEqual(2, len(tests))
        self.assertEqual(tests[0].intertree_class, formats[0][0])
        self.assertEqual(tests[0].workingtree_format, formats[0][1])
        self.assertEqual(tests[0].workingtree_to_test_tree, formats[0][2])
        self.assertEqual(tests[0].workingtree_format_to, formats[0][3])
        self.assertEqual(tests[0].workingtree_to_test_tree_to, formats[0][4])
        self.assertEqual(tests[0].transport_server, server1)
        self.assertEqual(tests[0].transport_readonly_server, server2)
        self.assertEqual(tests[1].intertree_class, formats[1][0])
        self.assertEqual(tests[1].workingtree_format, formats[1][1])
        self.assertEqual(tests[1].workingtree_to_test_tree, formats[1][2])
        self.assertEqual(tests[1].workingtree_format_to, formats[1][3])
        self.assertEqual(tests[1].workingtree_to_test_tree_to, formats[1][4])
        self.assertEqual(tests[1].transport_server, server1)
        self.assertEqual(tests[1].transport_readonly_server, server2)

class TestTestCaseWithTransport(TestCaseWithTransport):
    """Tests for the convenience functions TestCaseWithTransport introduces."""

    def test_get_readonly_url_none(self):
        from bzrlib.transport import get_transport
        from bzrlib.transport.memory import MemoryServer
        from bzrlib.transport.readonly import ReadonlyTransportDecorator
        self.transport_server = MemoryServer
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
        from bzrlib.transport import get_transport
        from bzrlib.transport.local import LocalRelpathServer
        from bzrlib.transport.http import HttpServer, HttpTransportBase
        self.transport_server = LocalRelpathServer
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

    def test_progress_bar_style_quiet(self):
        # test using a progress bar.
        dummy_test = TestTestResult('test_progress_bar_style_quiet')
        dummy_error = (Exception, None, [])
        mypb = MockProgress()
        mypb.update('Running tests', 0, 4)
        last_calls = mypb.calls[:]

        result = bzrlib.tests._MyResult(self._log_file,
                                        descriptions=0,
                                        verbosity=1,
                                        pb=mypb)
        self.assertEqual(last_calls, mypb.calls)

        def shorten(s):
            """Shorten a string based on the terminal width"""
            return result._ellipsise_unimportant_words(s,
                                 osutils.terminal_width())

        # an error 
        result.startTest(dummy_test)
        # starting a test prints the test name
        last_calls += [('update', '...tyle_quiet', 0, None)]
        self.assertEqual(last_calls, mypb.calls)
        result.addError(dummy_test, dummy_error)
        last_calls += [('update', 'ERROR        ', 1, None),
                       ('note', shorten(dummy_test.id() + ': ERROR'), ())
                      ]
        self.assertEqual(last_calls, mypb.calls)

        # a failure
        result.startTest(dummy_test)
        last_calls += [('update', '...tyle_quiet', 1, None)]
        self.assertEqual(last_calls, mypb.calls)
        last_calls += [('update', 'FAIL         ', 2, None),
                       ('note', shorten(dummy_test.id() + ': FAIL'), ())
                      ]
        result.addFailure(dummy_test, dummy_error)
        self.assertEqual(last_calls, mypb.calls)

        # a success
        result.startTest(dummy_test)
        last_calls += [('update', '...tyle_quiet', 2, None)]
        self.assertEqual(last_calls, mypb.calls)
        result.addSuccess(dummy_test)
        last_calls += [('update', 'OK           ', 3, None)]
        self.assertEqual(last_calls, mypb.calls)

        # a skip
        result.startTest(dummy_test)
        last_calls += [('update', '...tyle_quiet', 3, None)]
        self.assertEqual(last_calls, mypb.calls)
        result.addSkipped(dummy_test, dummy_error)
        last_calls += [('update', 'SKIP         ', 4, None)]
        self.assertEqual(last_calls, mypb.calls)

    def test_elapsed_time_with_benchmarking(self):
        result = bzrlib.tests._MyResult(self._log_file,
                                        descriptions=0,
                                        verbosity=1,
                                        )
        result._recordTestStartTime()
        time.sleep(0.003)
        result.extractBenchmarkTime(self)
        timed_string = result._testTimeString()
        # without explicit benchmarking, we should get a simple time.
        self.assertContainsRe(timed_string, "^         [ 1-9][0-9]ms$")
        # if a benchmark time is given, we want a x of y style result.
        self.time(time.sleep, 0.001)
        result.extractBenchmarkTime(self)
        timed_string = result._testTimeString()
        self.assertContainsRe(timed_string, "^   [ 1-9][0-9]ms/   [ 1-9][0-9]ms$")
        # extracting the time from a non-bzrlib testcase sets to None
        result._recordTestStartTime()
        result.extractBenchmarkTime(
            unittest.FunctionTestCase(self.test_elapsed_time_with_benchmarking))
        timed_string = result._testTimeString()
        self.assertContainsRe(timed_string, "^         [ 1-9][0-9]ms$")
        # cheat. Yes, wash thy mouth out with soap.
        self._benchtime = None

    def test_assigned_benchmark_file_stores_date(self):
        output = StringIO()
        result = bzrlib.tests._MyResult(self._log_file,
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
        result = bzrlib.tests._MyResult(
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
        result = bzrlib.tests._MyResult(
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

    def test_accepts_and_uses_pb_parameter(self):
        test = TestRunner('dummy_test')
        mypb = MockProgress()
        self.assertEqual([], mypb.calls)
        runner = TextTestRunner(stream=self._log_file, pb=mypb)
        result = self.run_test_runner(runner, test)
        self.assertEqual(1, result.testsRun)
        self.assertEqual(('update', 'Running tests', 0, 1), mypb.calls[0])
        self.assertEqual(('update', '...dummy_test', 0, None), mypb.calls[1])
        self.assertEqual(('update', 'OK           ', 1, None), mypb.calls[2])
        self.assertEqual(('update', 'Cleaning up', 0, 1), mypb.calls[3])
        self.assertEqual(('clear',), mypb.calls[4])
        self.assertEqual(5, len(mypb.calls))

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


class TestTestCase(TestCase):
    """Tests that test the core bzrlib TestCase."""

    def inner_test(self):
        # the inner child test
        note("inner_test")

    def outer_child(self):
        # the outer child test
        note("outer_start")
        self.inner_test = TestTestCase("inner_child")
        result = bzrlib.tests._MyResult(self._log_file,
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
        result = bzrlib.tests._MyResult(self._log_file,
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
        result = bzrlib.tests._MyResult(
            unittest._WritelnDecorator(output_stream),
            descriptions=0,
            verbosity=2)
        sample_test.run(result)
        self.assertContainsRe(
            output_stream.getvalue(),
            "[1-9][0-9]ms/   [1-9][0-9]ms\n$")
        
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
        self.callDeprecated(['i am deprecated'], testfunc, 
                              be_deprecated=True)
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
