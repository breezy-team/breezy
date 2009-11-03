# Copyright (C) 2005, 2006, 2007, 2008, 2009 Canonical Ltd
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

"""Tests for the test framework."""

from cStringIO import StringIO
import os
import signal
import sys
import time
import unittest
import warnings

import bzrlib
from bzrlib import (
    branchbuilder,
    bzrdir,
    debug,
    errors,
    lockdir,
    memorytree,
    osutils,
    progress,
    remote,
    repository,
    symbol_versioning,
    tests,
    workingtree,
    )
from bzrlib.repofmt import (
    groupcompress_repo,
    pack_repo,
    weaverepo,
    )
from bzrlib.symbol_versioning import (
    deprecated_function,
    deprecated_in,
    deprecated_method,
    )
from bzrlib.tests import (
    SubUnitFeature,
    test_lsprof,
    test_sftp_transport,
    TestUtil,
    )
from bzrlib.trace import note
from bzrlib.transport.memory import MemoryServer, MemoryTransport
from bzrlib.version import _get_bzr_source_tree


def _test_ids(test_suite):
    """Get the ids for the tests in a test suite."""
    return [t.id() for t in tests.iter_suite_tests(test_suite)]


class SelftestTests(tests.TestCase):

    def test_import_tests(self):
        mod = TestUtil._load_module_by_name('bzrlib.tests.test_selftest')
        self.assertEqual(mod.SelftestTests, SelftestTests)

    def test_import_test_failure(self):
        self.assertRaises(ImportError,
                          TestUtil._load_module_by_name,
                          'bzrlib.no-name-yet')

class MetaTestLog(tests.TestCase):

    def test_logging(self):
        """Test logs are captured when a test fails."""
        self.log('a test message')
        self._log_file.flush()
        self.assertContainsRe(self._get_log(keep_log_file=True),
                              'a test message\n')


class TestUnicodeFilename(tests.TestCase):

    def test_probe_passes(self):
        """UnicodeFilename._probe passes."""
        # We can't test much more than that because the behaviour depends
        # on the platform.
        tests.UnicodeFilename._probe()


class TestTreeShape(tests.TestCaseInTempDir):

    def test_unicode_paths(self):
        self.requireFeature(tests.UnicodeFilename)

        filename = u'hell\u00d8'
        self.build_tree_contents([(filename, 'contents of hello')])
        self.failUnlessExists(filename)


class TestTransportScenarios(tests.TestCase):
    """A group of tests that test the transport implementation adaption core.

    This is a meta test that the tests are applied to all available
    transports.

    This will be generalised in the future which is why it is in this
    test file even though it is specific to transport tests at the moment.
    """

    def test_get_transport_permutations(self):
        # this checks that get_test_permutations defined by the module is
        # called by the get_transport_test_permutations function.
        class MockModule(object):
            def get_test_permutations(self):
                return sample_permutation
        sample_permutation = [(1,2), (3,4)]
        from bzrlib.tests.per_transport import get_transport_test_permutations
        self.assertEqual(sample_permutation,
                         get_transport_test_permutations(MockModule()))

    def test_scenarios_include_all_modules(self):
        # this checks that the scenario generator returns as many permutations
        # as there are in all the registered transport modules - we assume if
        # this matches its probably doing the right thing especially in
        # combination with the tests for setting the right classes below.
        from bzrlib.tests.per_transport import transport_test_permutations
        from bzrlib.transport import _get_transport_modules
        modules = _get_transport_modules()
        permutation_count = 0
        for module in modules:
            try:
                permutation_count += len(reduce(getattr,
                    (module + ".get_test_permutations").split('.')[1:],
                     __import__(module))())
            except errors.DependencyNotPresent:
                pass
        scenarios = transport_test_permutations()
        self.assertEqual(permutation_count, len(scenarios))

    def test_scenarios_include_transport_class(self):
        # This test used to know about all the possible transports and the
        # order they were returned but that seems overly brittle (mbp
        # 20060307)
        from bzrlib.tests.per_transport import transport_test_permutations
        scenarios = transport_test_permutations()
        # there are at least that many builtin transports
        self.assertTrue(len(scenarios) > 6)
        one_scenario = scenarios[0]
        self.assertIsInstance(one_scenario[0], str)
        self.assertTrue(issubclass(one_scenario[1]["transport_class"],
                                   bzrlib.transport.Transport))
        self.assertTrue(issubclass(one_scenario[1]["transport_server"],
                                   bzrlib.transport.Server))


class TestBranchScenarios(tests.TestCase):

    def test_scenarios(self):
        # check that constructor parameters are passed through to the adapted
        # test.
        from bzrlib.tests.per_branch import make_scenarios
        server1 = "a"
        server2 = "b"
        formats = [("c", "C"), ("d", "D")]
        scenarios = make_scenarios(server1, server2, formats)
        self.assertEqual(2, len(scenarios))
        self.assertEqual([
            ('str',
             {'branch_format': 'c',
              'bzrdir_format': 'C',
              'transport_readonly_server': 'b',
              'transport_server': 'a'}),
            ('str',
             {'branch_format': 'd',
              'bzrdir_format': 'D',
              'transport_readonly_server': 'b',
              'transport_server': 'a'})],
            scenarios)


class TestBzrDirScenarios(tests.TestCase):

    def test_scenarios(self):
        # check that constructor parameters are passed through to the adapted
        # test.
        from bzrlib.tests.per_bzrdir import make_scenarios
        vfs_factory = "v"
        server1 = "a"
        server2 = "b"
        formats = ["c", "d"]
        scenarios = make_scenarios(vfs_factory, server1, server2, formats)
        self.assertEqual([
            ('str',
             {'bzrdir_format': 'c',
              'transport_readonly_server': 'b',
              'transport_server': 'a',
              'vfs_transport_factory': 'v'}),
            ('str',
             {'bzrdir_format': 'd',
              'transport_readonly_server': 'b',
              'transport_server': 'a',
              'vfs_transport_factory': 'v'})],
            scenarios)


class TestRepositoryScenarios(tests.TestCase):

    def test_formats_to_scenarios(self):
        from bzrlib.tests.per_repository import formats_to_scenarios
        formats = [("(c)", remote.RemoteRepositoryFormat()),
                   ("(d)", repository.format_registry.get(
                    'Bazaar repository format 2a (needs bzr 1.16 or later)\n'))]
        no_vfs_scenarios = formats_to_scenarios(formats, "server", "readonly",
            None)
        vfs_scenarios = formats_to_scenarios(formats, "server", "readonly",
            vfs_transport_factory="vfs")
        # no_vfs generate scenarios without vfs_transport_factory
        expected = [
            ('RemoteRepositoryFormat(c)',
             {'bzrdir_format': remote.RemoteBzrDirFormat(),
              'repository_format': remote.RemoteRepositoryFormat(),
              'transport_readonly_server': 'readonly',
              'transport_server': 'server'}),
            ('RepositoryFormat2a(d)',
             {'bzrdir_format': bzrdir.BzrDirMetaFormat1(),
              'repository_format': groupcompress_repo.RepositoryFormat2a(),
              'transport_readonly_server': 'readonly',
              'transport_server': 'server'})]
        self.assertEqual(expected, no_vfs_scenarios)
        self.assertEqual([
            ('RemoteRepositoryFormat(c)',
             {'bzrdir_format': remote.RemoteBzrDirFormat(),
              'repository_format': remote.RemoteRepositoryFormat(),
              'transport_readonly_server': 'readonly',
              'transport_server': 'server',
              'vfs_transport_factory': 'vfs'}),
            ('RepositoryFormat2a(d)',
             {'bzrdir_format': bzrdir.BzrDirMetaFormat1(),
              'repository_format': groupcompress_repo.RepositoryFormat2a(),
              'transport_readonly_server': 'readonly',
              'transport_server': 'server',
              'vfs_transport_factory': 'vfs'})],
            vfs_scenarios)


class TestTestScenarioApplication(tests.TestCase):
    """Tests for the test adaption facilities."""

    def test_apply_scenario(self):
        from bzrlib.tests import apply_scenario
        input_test = TestTestScenarioApplication("test_apply_scenario")
        # setup two adapted tests
        adapted_test1 = apply_scenario(input_test,
            ("new id",
            {"bzrdir_format":"bzr_format",
             "repository_format":"repo_fmt",
             "transport_server":"transport_server",
             "transport_readonly_server":"readonly-server"}))
        adapted_test2 = apply_scenario(input_test,
            ("new id 2", {"bzrdir_format":None}))
        # input_test should have been altered.
        self.assertRaises(AttributeError, getattr, input_test, "bzrdir_format")
        # the new tests are mutually incompatible, ensuring it has
        # made new ones, and unspecified elements in the scenario
        # should not have been altered.
        self.assertEqual("bzr_format", adapted_test1.bzrdir_format)
        self.assertEqual("repo_fmt", adapted_test1.repository_format)
        self.assertEqual("transport_server", adapted_test1.transport_server)
        self.assertEqual("readonly-server",
            adapted_test1.transport_readonly_server)
        self.assertEqual(
            "bzrlib.tests.test_selftest.TestTestScenarioApplication."
            "test_apply_scenario(new id)",
            adapted_test1.id())
        self.assertEqual(None, adapted_test2.bzrdir_format)
        self.assertEqual(
            "bzrlib.tests.test_selftest.TestTestScenarioApplication."
            "test_apply_scenario(new id 2)",
            adapted_test2.id())


class TestInterRepositoryScenarios(tests.TestCase):

    def test_scenarios(self):
        # check that constructor parameters are passed through to the adapted
        # test.
        from bzrlib.tests.per_interrepository import make_scenarios
        server1 = "a"
        server2 = "b"
        formats = [("C0", "C1", "C2"), ("D0", "D1", "D2")]
        scenarios = make_scenarios(server1, server2, formats)
        self.assertEqual([
            ('C0,str,str',
             {'repository_format': 'C1',
              'repository_format_to': 'C2',
              'transport_readonly_server': 'b',
              'transport_server': 'a'}),
            ('D0,str,str',
             {'repository_format': 'D1',
              'repository_format_to': 'D2',
              'transport_readonly_server': 'b',
              'transport_server': 'a'})],
            scenarios)


class TestWorkingTreeScenarios(tests.TestCase):

    def test_scenarios(self):
        # check that constructor parameters are passed through to the adapted
        # test.
        from bzrlib.tests.per_workingtree import make_scenarios
        server1 = "a"
        server2 = "b"
        formats = [workingtree.WorkingTreeFormat2(),
                   workingtree.WorkingTreeFormat3(),]
        scenarios = make_scenarios(server1, server2, formats)
        self.assertEqual([
            ('WorkingTreeFormat2',
             {'bzrdir_format': formats[0]._matchingbzrdir,
              'transport_readonly_server': 'b',
              'transport_server': 'a',
              'workingtree_format': formats[0]}),
            ('WorkingTreeFormat3',
             {'bzrdir_format': formats[1]._matchingbzrdir,
              'transport_readonly_server': 'b',
              'transport_server': 'a',
              'workingtree_format': formats[1]})],
            scenarios)


class TestTreeScenarios(tests.TestCase):

    def test_scenarios(self):
        # the tree implementation scenario generator is meant to setup one
        # instance for each working tree format, and one additional instance
        # that will use the default wt format, but create a revision tree for
        # the tests.  this means that the wt ones should have the
        # workingtree_to_test_tree attribute set to 'return_parameter' and the
        # revision one set to revision_tree_from_workingtree.

        from bzrlib.tests.per_tree import (
            _dirstate_tree_from_workingtree,
            make_scenarios,
            preview_tree_pre,
            preview_tree_post,
            return_parameter,
            revision_tree_from_workingtree
            )
        server1 = "a"
        server2 = "b"
        formats = [workingtree.WorkingTreeFormat2(),
                   workingtree.WorkingTreeFormat3(),]
        scenarios = make_scenarios(server1, server2, formats)
        self.assertEqual(7, len(scenarios))
        default_wt_format = workingtree.WorkingTreeFormat4._default_format
        wt4_format = workingtree.WorkingTreeFormat4()
        wt5_format = workingtree.WorkingTreeFormat5()
        expected_scenarios = [
            ('WorkingTreeFormat2',
             {'bzrdir_format': formats[0]._matchingbzrdir,
              'transport_readonly_server': 'b',
              'transport_server': 'a',
              'workingtree_format': formats[0],
              '_workingtree_to_test_tree': return_parameter,
              }),
            ('WorkingTreeFormat3',
             {'bzrdir_format': formats[1]._matchingbzrdir,
              'transport_readonly_server': 'b',
              'transport_server': 'a',
              'workingtree_format': formats[1],
              '_workingtree_to_test_tree': return_parameter,
             }),
            ('RevisionTree',
             {'_workingtree_to_test_tree': revision_tree_from_workingtree,
              'bzrdir_format': default_wt_format._matchingbzrdir,
              'transport_readonly_server': 'b',
              'transport_server': 'a',
              'workingtree_format': default_wt_format,
             }),
            ('DirStateRevisionTree,WT4',
             {'_workingtree_to_test_tree': _dirstate_tree_from_workingtree,
              'bzrdir_format': wt4_format._matchingbzrdir,
              'transport_readonly_server': 'b',
              'transport_server': 'a',
              'workingtree_format': wt4_format,
             }),
            ('DirStateRevisionTree,WT5',
             {'_workingtree_to_test_tree': _dirstate_tree_from_workingtree,
              'bzrdir_format': wt5_format._matchingbzrdir,
              'transport_readonly_server': 'b',
              'transport_server': 'a',
              'workingtree_format': wt5_format,
             }),
            ('PreviewTree',
             {'_workingtree_to_test_tree': preview_tree_pre,
              'bzrdir_format': default_wt_format._matchingbzrdir,
              'transport_readonly_server': 'b',
              'transport_server': 'a',
              'workingtree_format': default_wt_format}),
            ('PreviewTreePost',
             {'_workingtree_to_test_tree': preview_tree_post,
              'bzrdir_format': default_wt_format._matchingbzrdir,
              'transport_readonly_server': 'b',
              'transport_server': 'a',
              'workingtree_format': default_wt_format}),
             ]
        self.assertEqual(expected_scenarios, scenarios)


class TestInterTreeScenarios(tests.TestCase):
    """A group of tests that test the InterTreeTestAdapter."""

    def test_scenarios(self):
        # check that constructor parameters are passed through to the adapted
        # test.
        # for InterTree tests we want the machinery to bring up two trees in
        # each instance: the base one, and the one we are interacting with.
        # because each optimiser can be direction specific, we need to test
        # each optimiser in its chosen direction.
        # unlike the TestProviderAdapter we dont want to automatically add a
        # parameterized one for WorkingTree - the optimisers will tell us what
        # ones to add.
        from bzrlib.tests.per_tree import (
            return_parameter,
            revision_tree_from_workingtree
            )
        from bzrlib.tests.per_intertree import (
            make_scenarios,
            )
        from bzrlib.workingtree import WorkingTreeFormat2, WorkingTreeFormat3
        input_test = TestInterTreeScenarios(
            "test_scenarios")
        server1 = "a"
        server2 = "b"
        format1 = WorkingTreeFormat2()
        format2 = WorkingTreeFormat3()
        formats = [("1", str, format1, format2, "converter1"),
            ("2", int, format2, format1, "converter2")]
        scenarios = make_scenarios(server1, server2, formats)
        self.assertEqual(2, len(scenarios))
        expected_scenarios = [
            ("1", {
                "bzrdir_format": format1._matchingbzrdir,
                "intertree_class": formats[0][1],
                "workingtree_format": formats[0][2],
                "workingtree_format_to": formats[0][3],
                "mutable_trees_to_test_trees": formats[0][4],
                "_workingtree_to_test_tree": return_parameter,
                "transport_server": server1,
                "transport_readonly_server": server2,
                }),
            ("2", {
                "bzrdir_format": format2._matchingbzrdir,
                "intertree_class": formats[1][1],
                "workingtree_format": formats[1][2],
                "workingtree_format_to": formats[1][3],
                "mutable_trees_to_test_trees": formats[1][4],
                "_workingtree_to_test_tree": return_parameter,
                "transport_server": server1,
                "transport_readonly_server": server2,
                }),
            ]
        self.assertEqual(scenarios, expected_scenarios)


class TestTestCaseInTempDir(tests.TestCaseInTempDir):

    def test_home_is_not_working(self):
        self.assertNotEqual(self.test_dir, self.test_home_dir)
        cwd = osutils.getcwd()
        self.assertIsSameRealPath(self.test_dir, cwd)
        self.assertIsSameRealPath(self.test_home_dir, os.environ['HOME'])

    def test_assertEqualStat_equal(self):
        from bzrlib.tests.test_dirstate import _FakeStat
        self.build_tree(["foo"])
        real = os.lstat("foo")
        fake = _FakeStat(real.st_size, real.st_mtime, real.st_ctime,
            real.st_dev, real.st_ino, real.st_mode)
        self.assertEqualStat(real, fake)

    def test_assertEqualStat_notequal(self):
        self.build_tree(["foo", "bar"])
        self.assertRaises(AssertionError, self.assertEqualStat,
            os.lstat("foo"), os.lstat("bar"))


class TestTestCaseWithMemoryTransport(tests.TestCaseWithMemoryTransport):

    def test_home_is_non_existant_dir_under_root(self):
        """The test_home_dir for TestCaseWithMemoryTransport is missing.

        This is because TestCaseWithMemoryTransport is for tests that do not
        need any disk resources: they should be hooked into bzrlib in such a
        way that no global settings are being changed by the test (only a
        few tests should need to do that), and having a missing dir as home is
        an effective way to ensure that this is the case.
        """
        self.assertIsSameRealPath(
            self.TEST_ROOT + "/MemoryTransportMissingHomeDir",
            self.test_home_dir)
        self.assertIsSameRealPath(self.test_home_dir, os.environ['HOME'])

    def test_cwd_is_TEST_ROOT(self):
        self.assertIsSameRealPath(self.test_dir, self.TEST_ROOT)
        cwd = osutils.getcwd()
        self.assertIsSameRealPath(self.test_dir, cwd)

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

    def test_make_branch_builder(self):
        builder = self.make_branch_builder('dir')
        self.assertIsInstance(builder, branchbuilder.BranchBuilder)
        # Guard against regression into MemoryTransport leaking
        # files to disk instead of keeping them in memory.
        self.failIf(osutils.lexists('dir'))

    def test_make_branch_builder_with_format(self):
        # Use a repo layout that doesn't conform to a 'named' layout, to ensure
        # that the format objects are used.
        format = bzrdir.BzrDirMetaFormat1()
        repo_format = weaverepo.RepositoryFormat7()
        format.repository_format = repo_format
        builder = self.make_branch_builder('dir', format=format)
        the_branch = builder.get_branch()
        # Guard against regression into MemoryTransport leaking
        # files to disk instead of keeping them in memory.
        self.failIf(osutils.lexists('dir'))
        self.assertEqual(format.repository_format.__class__,
                         the_branch.repository._format.__class__)
        self.assertEqual(repo_format.get_format_string(),
                         self.get_transport().get_bytes(
                            'dir/.bzr/repository/format'))

    def test_make_branch_builder_with_format_name(self):
        builder = self.make_branch_builder('dir', format='knit')
        the_branch = builder.get_branch()
        # Guard against regression into MemoryTransport leaking
        # files to disk instead of keeping them in memory.
        self.failIf(osutils.lexists('dir'))
        dir_format = bzrdir.format_registry.make_bzrdir('knit')
        self.assertEqual(dir_format.repository_format.__class__,
                         the_branch.repository._format.__class__)
        self.assertEqual('Bazaar-NG Knit Repository Format 1',
                         self.get_transport().get_bytes(
                            'dir/.bzr/repository/format'))

    def test_safety_net(self):
        """No test should modify the safety .bzr directory.

        We just test that the _check_safety_net private method raises
        AssertionError, it's easier than building a test suite with the same
        test.
        """
        # Oops, a commit in the current directory (i.e. without local .bzr
        # directory) will crawl up the hierarchy to find a .bzr directory.
        self.run_bzr(['commit', '-mfoo', '--unchanged'])
        # But we have a safety net in place.
        self.assertRaises(AssertionError, self._check_safety_net)

    def test_dangling_locks_cause_failures(self):
        class TestDanglingLock(tests.TestCaseWithMemoryTransport):
            def test_function(self):
                t = self.get_transport('.')
                l = lockdir.LockDir(t, 'lock')
                l.create()
                l.attempt_lock()
        test = TestDanglingLock('test_function')
        result = test.run()
        if self._lock_check_thorough:
            self.assertEqual(1, len(result.errors))
        else:
            # When _lock_check_thorough is disabled, then we don't trigger a
            # failure
            self.assertEqual(0, len(result.errors))


class TestTestCaseWithTransport(tests.TestCaseWithTransport):
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
        from bzrlib.tests.http_server import HttpServer
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

    def test_make_branch_builder(self):
        builder = self.make_branch_builder('dir')
        rev_id = builder.build_commit()
        self.failUnlessExists('dir')
        a_dir = bzrdir.BzrDir.open('dir')
        self.assertRaises(errors.NoWorkingTree, a_dir.open_workingtree)
        a_branch = a_dir.open_branch()
        builder_branch = builder.get_branch()
        self.assertEqual(a_branch.base, builder_branch.base)
        self.assertEqual((1, rev_id), builder_branch.last_revision_info())
        self.assertEqual((1, rev_id), a_branch.last_revision_info())


class TestTestCaseTransports(tests.TestCaseWithTransport):

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


class TestChrootedTest(tests.ChrootedTestCase):

    def test_root_is_root(self):
        from bzrlib.transport import get_transport
        t = get_transport(self.get_readonly_url())
        url = t.base
        self.assertEqual(url, t.clone('..').base)


class TestTestResult(tests.TestCase):

    def check_timing(self, test_case, expected_re):
        result = bzrlib.tests.TextTestResult(self._log_file,
                descriptions=0,
                verbosity=1,
                )
        test_case.run(result)
        timed_string = result._testTimeString(test_case)
        self.assertContainsRe(timed_string, expected_re)

    def test_test_reporting(self):
        class ShortDelayTestCase(tests.TestCase):
            def test_short_delay(self):
                time.sleep(0.003)
            def test_short_benchmark(self):
                self.time(time.sleep, 0.003)
        self.check_timing(ShortDelayTestCase('test_short_delay'),
                          r"^ +[0-9]+ms$")
        # if a benchmark time is given, we now show just that time followed by
        # a star
        self.check_timing(ShortDelayTestCase('test_short_benchmark'),
                          r"^ +[0-9]+ms\*$")

    def test_unittest_reporting_unittest_class(self):
        # getting the time from a non-bzrlib test works ok
        class ShortDelayTestCase(unittest.TestCase):
            def test_short_delay(self):
                time.sleep(0.003)
        self.check_timing(ShortDelayTestCase('test_short_delay'),
                          r"^ +[0-9]+ms$")

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
        self.requireFeature(test_lsprof.LSProfFeature)
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
        class InstrumentedTestResult(tests.ExtendedTestResult):
            def done(self): pass
            def startTests(self): pass
            def report_test_start(self, test): pass
            def report_known_failure(self, test, err):
                self._call = test, err
        result = InstrumentedTestResult(None, None, None, None)
        def test_function():
            raise tests.KnownFailure('failed!')
        test = unittest.FunctionTestCase(test_function)
        test.run(result)
        # it should invoke 'report_known_failure'.
        self.assertEqual(2, len(result._call))
        self.assertEqual(test, result._call[0])
        self.assertEqual(tests.KnownFailure, result._call[1][0])
        self.assertIsInstance(result._call[1][1], tests.KnownFailure)
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
        prefix = len(result_stream.getvalue())
        # the err parameter has the shape:
        # (class, exception object, traceback)
        # KnownFailures dont get their tracebacks shown though, so we
        # can skip that.
        err = (tests.KnownFailure, tests.KnownFailure('foo'), None)
        result.report_known_failure(test, err)
        output = result_stream.getvalue()[prefix:]
        lines = output.splitlines()
        self.assertContainsRe(lines[0], r'XFAIL *\d+ms$')
        self.assertEqual(lines[1], '    foo')
        self.assertEqual(2, len(lines))

    def get_passing_test(self):
        """Return a test object that can't be run usefully."""
        def passing_test():
            pass
        return unittest.FunctionTestCase(passing_test)

    def test_add_not_supported(self):
        """Test the behaviour of invoking addNotSupported."""
        class InstrumentedTestResult(tests.ExtendedTestResult):
            def done(self): pass
            def startTests(self): pass
            def report_test_start(self, test): pass
            def report_unsupported(self, test, feature):
                self._call = test, feature
        result = InstrumentedTestResult(None, None, None, None)
        test = SampleTestCase('_test_pass')
        feature = tests.Feature()
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
        feature = tests.Feature()
        result.startTest(test)
        prefix = len(result_stream.getvalue())
        result.report_unsupported(test, feature)
        output = result_stream.getvalue()[prefix:]
        lines = output.splitlines()
        self.assertEqual(lines, ['NODEP        0ms',
                                 "    The feature 'Feature' is not available."])

    def test_unavailable_exception(self):
        """An UnavailableFeature being raised should invoke addNotSupported."""
        class InstrumentedTestResult(tests.ExtendedTestResult):
            def done(self): pass
            def startTests(self): pass
            def report_test_start(self, test): pass
            def addNotSupported(self, test, feature):
                self._call = test, feature
        result = InstrumentedTestResult(None, None, None, None)
        feature = tests.Feature()
        def test_function():
            raise tests.UnavailableFeature(feature)
        test = unittest.FunctionTestCase(test_function)
        test.run(result)
        # it should invoke 'addNotSupported'.
        self.assertEqual(2, len(result._call))
        self.assertEqual(test, result._call[0])
        self.assertEqual(feature, result._call[1])
        # and not count as an error
        self.assertEqual(0, result.error_count)

    def test_strict_with_unsupported_feature(self):
        result = bzrlib.tests.TextTestResult(self._log_file, descriptions=0,
                                             verbosity=1)
        test = self.get_passing_test()
        feature = "Unsupported Feature"
        result.addNotSupported(test, feature)
        self.assertFalse(result.wasStrictlySuccessful())
        self.assertEqual(None, result._extractBenchmarkTime(test))

    def test_strict_with_known_failure(self):
        result = bzrlib.tests.TextTestResult(self._log_file, descriptions=0,
                                             verbosity=1)
        test = self.get_passing_test()
        err = (tests.KnownFailure, tests.KnownFailure('foo'), None)
        result._addKnownFailure(test, err)
        self.assertFalse(result.wasStrictlySuccessful())
        self.assertEqual(None, result._extractBenchmarkTime(test))

    def test_strict_with_success(self):
        result = bzrlib.tests.TextTestResult(self._log_file, descriptions=0,
                                             verbosity=1)
        test = self.get_passing_test()
        result.addSuccess(test)
        self.assertTrue(result.wasStrictlySuccessful())
        self.assertEqual(None, result._extractBenchmarkTime(test))

    def test_startTests(self):
        """Starting the first test should trigger startTests."""
        class InstrumentedTestResult(tests.ExtendedTestResult):
            calls = 0
            def startTests(self): self.calls += 1
            def report_test_start(self, test): pass
        result = InstrumentedTestResult(None, None, None, None)
        def test_function():
            pass
        test = unittest.FunctionTestCase(test_function)
        test.run(result)
        self.assertEquals(1, result.calls)


class TestUnicodeFilenameFeature(tests.TestCase):

    def test_probe_passes(self):
        """UnicodeFilenameFeature._probe passes."""
        # We can't test much more than that because the behaviour depends
        # on the platform.
        tests.UnicodeFilenameFeature._probe()


class TestRunner(tests.TestCase):

    def dummy_test(self):
        pass

    def run_test_runner(self, testrunner, test):
        """Run suite in testrunner, saving global state and restoring it.

        This current saves and restores:
        TestCaseInTempDir.TEST_ROOT

        There should be no tests in this file that use
        bzrlib.tests.TextTestRunner without using this convenience method,
        because of our use of global state.
        """
        old_root = tests.TestCaseInTempDir.TEST_ROOT
        try:
            tests.TestCaseInTempDir.TEST_ROOT = None
            return testrunner.run(test)
        finally:
            tests.TestCaseInTempDir.TEST_ROOT = old_root

    def test_known_failure_failed_run(self):
        # run a test that generates a known failure which should be printed in
        # the final output when real failures occur.
        def known_failure_test():
            raise tests.KnownFailure('failed')
        test = unittest.TestSuite()
        test.addTest(unittest.FunctionTestCase(known_failure_test))
        def failing_test():
            raise AssertionError('foo')
        test.addTest(unittest.FunctionTestCase(failing_test))
        stream = StringIO()
        runner = tests.TextTestRunner(stream=stream)
        result = self.run_test_runner(runner, test)
        lines = stream.getvalue().splitlines()
        self.assertContainsRe(stream.getvalue(),
            '(?sm)^testing.*$'
            '.*'
            '^======================================================================\n'
            '^FAIL: unittest.FunctionTestCase \\(failing_test\\)\n'
            '^----------------------------------------------------------------------\n'
            'Traceback \\(most recent call last\\):\n'
            '  .*' # File .*, line .*, in failing_test' - but maybe not from .pyc
            '    raise AssertionError\\(\'foo\'\\)\n'
            '.*'
            '^----------------------------------------------------------------------\n'
            '.*'
            'FAILED \\(failures=1, known_failure_count=1\\)'
            )

    def test_known_failure_ok_run(self):
        # run a test that generates a known failure which should be printed in the final output.
        def known_failure_test():
            raise tests.KnownFailure('failed')
        test = unittest.FunctionTestCase(known_failure_test)
        stream = StringIO()
        runner = tests.TextTestRunner(stream=stream)
        result = self.run_test_runner(runner, test)
        self.assertContainsRe(stream.getvalue(),
            '\n'
            '-*\n'
            'Ran 1 test in .*\n'
            '\n'
            'OK \\(known_failures=1\\)\n')

    def test_skipped_test(self):
        # run a test that is skipped, and check the suite as a whole still
        # succeeds.
        # skipping_test must be hidden in here so it's not run as a real test
        class SkippingTest(tests.TestCase):
            def skipping_test(self):
                raise tests.TestSkipped('test intentionally skipped')
        runner = tests.TextTestRunner(stream=self._log_file)
        test = SkippingTest("skipping_test")
        result = self.run_test_runner(runner, test)
        self.assertTrue(result.wasSuccessful())

    def test_skipped_from_setup(self):
        calls = []
        class SkippedSetupTest(tests.TestCase):

            def setUp(self):
                calls.append('setUp')
                self.addCleanup(self.cleanup)
                raise tests.TestSkipped('skipped setup')

            def test_skip(self):
                self.fail('test reached')

            def cleanup(self):
                calls.append('cleanup')

        runner = tests.TextTestRunner(stream=self._log_file)
        test = SkippedSetupTest('test_skip')
        result = self.run_test_runner(runner, test)
        self.assertTrue(result.wasSuccessful())
        # Check if cleanup was called the right number of times.
        self.assertEqual(['setUp', 'cleanup'], calls)

    def test_skipped_from_test(self):
        calls = []
        class SkippedTest(tests.TestCase):

            def setUp(self):
                tests.TestCase.setUp(self)
                calls.append('setUp')
                self.addCleanup(self.cleanup)

            def test_skip(self):
                raise tests.TestSkipped('skipped test')

            def cleanup(self):
                calls.append('cleanup')

        runner = tests.TextTestRunner(stream=self._log_file)
        test = SkippedTest('test_skip')
        result = self.run_test_runner(runner, test)
        self.assertTrue(result.wasSuccessful())
        # Check if cleanup was called the right number of times.
        self.assertEqual(['setUp', 'cleanup'], calls)

    def test_not_applicable(self):
        # run a test that is skipped because it's not applicable
        def not_applicable_test():
            raise tests.TestNotApplicable('this test never runs')
        out = StringIO()
        runner = tests.TextTestRunner(stream=out, verbosity=2)
        test = unittest.FunctionTestCase(not_applicable_test)
        result = self.run_test_runner(runner, test)
        self._log_file.write(out.getvalue())
        self.assertTrue(result.wasSuccessful())
        self.assertTrue(result.wasStrictlySuccessful())
        self.assertContainsRe(out.getvalue(),
                r'(?m)not_applicable_test   * N/A')
        self.assertContainsRe(out.getvalue(),
                r'(?m)^    this test never runs')

    def test_not_applicable_demo(self):
        # just so you can see it in the test output
        raise tests.TestNotApplicable('this test is just a demonstation')

    def test_unsupported_features_listed(self):
        """When unsupported features are encountered they are detailed."""
        class Feature1(tests.Feature):
            def _probe(self): return False
        class Feature2(tests.Feature):
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
        runner = tests.TextTestRunner(stream=stream)
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
        runner = tests.TextTestRunner(stream=self._log_file,
                                      bench_history=output)
        result = self.run_test_runner(runner, test)
        output_string = output.getvalue()
        self.assertContainsRe(output_string, "--date [0-9.]+")
        if workingtree is not None:
            revision_id = workingtree.get_parent_ids()[0]
            self.assertEndsWith(output_string.rstrip(), revision_id)

    def assertLogDeleted(self, test):
        log = test._get_log()
        self.assertEqual("DELETED log file to reduce memory footprint", log)
        self.assertEqual('', test._log_contents)
        self.assertIs(None, test._log_file_name)

    def test_success_log_deleted(self):
        """Successful tests have their log deleted"""

        class LogTester(tests.TestCase):

            def test_success(self):
                self.log('this will be removed\n')

        sio = StringIO()
        runner = tests.TextTestRunner(stream=sio)
        test = LogTester('test_success')
        result = self.run_test_runner(runner, test)

        self.assertLogDeleted(test)

    def test_skipped_log_deleted(self):
        """Skipped tests have their log deleted"""

        class LogTester(tests.TestCase):

            def test_skipped(self):
                self.log('this will be removed\n')
                raise tests.TestSkipped()

        sio = StringIO()
        runner = tests.TextTestRunner(stream=sio)
        test = LogTester('test_skipped')
        result = self.run_test_runner(runner, test)

        self.assertLogDeleted(test)

    def test_not_aplicable_log_deleted(self):
        """Not applicable tests have their log deleted"""

        class LogTester(tests.TestCase):

            def test_not_applicable(self):
                self.log('this will be removed\n')
                raise tests.TestNotApplicable()

        sio = StringIO()
        runner = tests.TextTestRunner(stream=sio)
        test = LogTester('test_not_applicable')
        result = self.run_test_runner(runner, test)

        self.assertLogDeleted(test)

    def test_known_failure_log_deleted(self):
        """Know failure tests have their log deleted"""

        class LogTester(tests.TestCase):

            def test_known_failure(self):
                self.log('this will be removed\n')
                raise tests.KnownFailure()

        sio = StringIO()
        runner = tests.TextTestRunner(stream=sio)
        test = LogTester('test_known_failure')
        result = self.run_test_runner(runner, test)

        self.assertLogDeleted(test)

    def test_fail_log_kept(self):
        """Failed tests have their log kept"""

        class LogTester(tests.TestCase):

            def test_fail(self):
                self.log('this will be kept\n')
                self.fail('this test fails')

        sio = StringIO()
        runner = tests.TextTestRunner(stream=sio)
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

        class LogTester(tests.TestCase):

            def test_error(self):
                self.log('this will be kept\n')
                raise ValueError('random exception raised')

        sio = StringIO()
        runner = tests.TextTestRunner(stream=sio)
        test = LogTester('test_error')
        result = self.run_test_runner(runner, test)

        text = sio.getvalue()
        self.assertContainsRe(text, 'this will be kept')
        self.assertContainsRe(text, 'random exception raised')

        log = test._get_log()
        self.assertContainsRe(log, 'this will be kept')
        self.assertEqual(log, test._log_contents)


class SampleTestCase(tests.TestCase):

    def _test_pass(self):
        pass

class _TestException(Exception):
    pass


class TestTestCase(tests.TestCase):
    """Tests that test the core bzrlib TestCase."""

    def test_assertLength_matches_empty(self):
        a_list = []
        self.assertLength(0, a_list)

    def test_assertLength_matches_nonempty(self):
        a_list = [1, 2, 3]
        self.assertLength(3, a_list)

    def test_assertLength_fails_different(self):
        a_list = []
        self.assertRaises(AssertionError, self.assertLength, 1, a_list)

    def test_assertLength_shows_sequence_in_failure(self):
        a_list = [1, 2, 3]
        exception = self.assertRaises(AssertionError, self.assertLength, 2,
            a_list)
        self.assertEqual('Incorrect length: wanted 2, got 3 for [1, 2, 3]',
            exception.args[0])

    def test_base_setUp_not_called_causes_failure(self):
        class TestCaseWithBrokenSetUp(tests.TestCase):
            def setUp(self):
                pass # does not call TestCase.setUp
            def test_foo(self):
                pass
        test = TestCaseWithBrokenSetUp('test_foo')
        result = unittest.TestResult()
        test.run(result)
        self.assertFalse(result.wasSuccessful())
        self.assertEqual(1, result.testsRun)

    def test_base_tearDown_not_called_causes_failure(self):
        class TestCaseWithBrokenTearDown(tests.TestCase):
            def tearDown(self):
                pass # does not call TestCase.tearDown
            def test_foo(self):
                pass
        test = TestCaseWithBrokenTearDown('test_foo')
        result = unittest.TestResult()
        test.run(result)
        self.assertFalse(result.wasSuccessful())
        self.assertEqual(1, result.testsRun)

    def test_debug_flags_sanitised(self):
        """The bzrlib debug flags should be sanitised by setUp."""
        if 'allow_debug' in tests.selftest_debug_flags:
            raise tests.TestNotApplicable(
                '-Eallow_debug option prevents debug flag sanitisation')
        # we could set something and run a test that will check
        # it gets santised, but this is probably sufficient for now:
        # if someone runs the test with -Dsomething it will error.
        flags = set()
        if self._lock_check_thorough:
            flags.add('strict_locks')
        self.assertEqual(flags, bzrlib.debug.debug_flags)

    def change_selftest_debug_flags(self, new_flags):
        orig_selftest_flags = tests.selftest_debug_flags
        self.addCleanup(self._restore_selftest_debug_flags, orig_selftest_flags)
        tests.selftest_debug_flags = set(new_flags)

    def _restore_selftest_debug_flags(self, flags):
        tests.selftest_debug_flags = flags

    def test_allow_debug_flag(self):
        """The -Eallow_debug flag prevents bzrlib.debug.debug_flags from being
        sanitised (i.e. cleared) before running a test.
        """
        self.change_selftest_debug_flags(set(['allow_debug']))
        bzrlib.debug.debug_flags = set(['a-flag'])
        class TestThatRecordsFlags(tests.TestCase):
            def test_foo(nested_self):
                self.flags = set(bzrlib.debug.debug_flags)
        test = TestThatRecordsFlags('test_foo')
        test.run(self.make_test_result())
        flags = set(['a-flag'])
        if 'disable_lock_checks' not in tests.selftest_debug_flags:
            flags.add('strict_locks')
        self.assertEqual(flags, self.flags)

    def test_disable_lock_checks(self):
        """The -Edisable_lock_checks flag disables thorough checks."""
        class TestThatRecordsFlags(tests.TestCase):
            def test_foo(nested_self):
                self.flags = set(bzrlib.debug.debug_flags)
                self.test_lock_check_thorough = nested_self._lock_check_thorough
        self.change_selftest_debug_flags(set())
        test = TestThatRecordsFlags('test_foo')
        test.run(self.make_test_result())
        # By default we do strict lock checking and thorough lock/unlock
        # tracking.
        self.assertTrue(self.test_lock_check_thorough)
        self.assertEqual(set(['strict_locks']), self.flags)
        # Now set the disable_lock_checks flag, and show that this changed.
        self.change_selftest_debug_flags(set(['disable_lock_checks']))
        test = TestThatRecordsFlags('test_foo')
        test.run(self.make_test_result())
        self.assertFalse(self.test_lock_check_thorough)
        self.assertEqual(set(), self.flags)

    def test_this_fails_strict_lock_check(self):
        class TestThatRecordsFlags(tests.TestCase):
            def test_foo(nested_self):
                self.flags1 = set(bzrlib.debug.debug_flags)
                self.thisFailsStrictLockCheck()
                self.flags2 = set(bzrlib.debug.debug_flags)
        # Make sure lock checking is active
        self.change_selftest_debug_flags(set())
        test = TestThatRecordsFlags('test_foo')
        test.run(self.make_test_result())
        self.assertEqual(set(['strict_locks']), self.flags1)
        self.assertEqual(set(), self.flags2)

    def test_debug_flags_restored(self):
        """The bzrlib debug flags should be restored to their original state
        after the test was run, even if allow_debug is set.
        """
        self.change_selftest_debug_flags(set(['allow_debug']))
        # Now run a test that modifies debug.debug_flags.
        bzrlib.debug.debug_flags = set(['original-state'])
        class TestThatModifiesFlags(tests.TestCase):
            def test_foo(self):
                bzrlib.debug.debug_flags = set(['modified'])
        test = TestThatModifiesFlags('test_foo')
        test.run(self.make_test_result())
        self.assertEqual(set(['original-state']), bzrlib.debug.debug_flags)

    def make_test_result(self):
        return tests.TextTestResult(self._log_file, descriptions=0, verbosity=1)

    def inner_test(self):
        # the inner child test
        note("inner_test")

    def outer_child(self):
        # the outer child test
        note("outer_start")
        self.inner_test = TestTestCase("inner_child")
        result = self.make_test_result()
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
        result = self.make_test_result()
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
            verbosity=2)
        sample_test.run(result)
        self.assertContainsRe(
            output_stream.getvalue(),
            r"\d+ms\*\n$")

    def test_hooks_sanitised(self):
        """The bzrlib hooks should be sanitised by setUp."""
        # Note this test won't fail with hooks that the core library doesn't
        # use - but it trigger with a plugin that adds hooks, so its still a
        # useful warning in that case.
        self.assertEqual(bzrlib.branch.BranchHooks(),
            bzrlib.branch.Branch.hooks)
        self.assertEqual(bzrlib.smart.server.SmartServerHooks(),
            bzrlib.smart.server.SmartTCPServer.hooks)
        self.assertEqual(bzrlib.commands.CommandHooks(),
            bzrlib.commands.Command.hooks)

    def test__gather_lsprof_in_benchmarks(self):
        """When _gather_lsprof_in_benchmarks is on, accumulate profile data.

        Each self.time() call is individually and separately profiled.
        """
        self.requireFeature(test_lsprof.LSProfFeature)
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
        self.assertRaises(tests.KnownFailure, self.knownFailure, "A Failure")

    def test_requireFeature_available(self):
        """self.requireFeature(available) is a no-op."""
        class Available(tests.Feature):
            def _probe(self):return True
        feature = Available()
        self.requireFeature(feature)

    def test_requireFeature_unavailable(self):
        """self.requireFeature(unavailable) raises UnavailableFeature."""
        class Unavailable(tests.Feature):
            def _probe(self):return False
        feature = Unavailable()
        self.assertRaises(tests.UnavailableFeature,
                          self.requireFeature, feature)

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

    def test_assert_list_raises_on_generator(self):
        def generator_which_will_raise():
            # This will not raise until after the first yield
            yield 1
            raise _TestException()

        e = self.assertListRaises(_TestException, generator_which_will_raise)
        self.assertIsInstance(e, _TestException)

        e = self.assertListRaises(Exception, generator_which_will_raise)
        self.assertIsInstance(e, _TestException)

    def test_assert_list_raises_on_plain(self):
        def plain_exception():
            raise _TestException()
            return []

        e = self.assertListRaises(_TestException, plain_exception)
        self.assertIsInstance(e, _TestException)

        e = self.assertListRaises(Exception, plain_exception)
        self.assertIsInstance(e, _TestException)

    def test_assert_list_raises_assert_wrong_exception(self):
        class _NotTestException(Exception):
            pass

        def wrong_exception():
            raise _NotTestException()

        def wrong_exception_generator():
            yield 1
            yield 2
            raise _NotTestException()

        # Wrong exceptions are not intercepted
        self.assertRaises(_NotTestException,
            self.assertListRaises, _TestException, wrong_exception)
        self.assertRaises(_NotTestException,
            self.assertListRaises, _TestException, wrong_exception_generator)

    def test_assert_list_raises_no_exception(self):
        def success():
            return []

        def success_generator():
            yield 1
            yield 2

        self.assertRaises(AssertionError,
            self.assertListRaises, _TestException, success)

        self.assertRaises(AssertionError,
            self.assertListRaises, _TestException, success_generator)


# NB: Don't delete this; it's not actually from 0.11!
@deprecated_function(deprecated_in((0, 11, 0)))
def sample_deprecated_function():
    """A deprecated function to test applyDeprecated with."""
    return 2


def sample_undeprecated_function(a_param):
    """A undeprecated function to test applyDeprecated with."""


class ApplyDeprecatedHelper(object):
    """A helper class for ApplyDeprecated tests."""

    @deprecated_method(deprecated_in((0, 11, 0)))
    def sample_deprecated_method(self, param_one):
        """A deprecated method for testing with."""
        return param_one

    def sample_normal_method(self):
        """A undeprecated method."""

    @deprecated_method(deprecated_in((0, 10, 0)))
    def sample_nested_deprecation(self):
        return sample_deprecated_function()


class TestExtraAssertions(tests.TestCase):
    """Tests for new test assertions in bzrlib test suite"""

    def test_assert_isinstance(self):
        self.assertIsInstance(2, int)
        self.assertIsInstance(u'', basestring)
        e = self.assertRaises(AssertionError, self.assertIsInstance, None, int)
        self.assertEquals(str(e),
            "None is an instance of <type 'NoneType'> rather than <type 'int'>")
        self.assertRaises(AssertionError, self.assertIsInstance, 23.3, int)
        e = self.assertRaises(AssertionError,
            self.assertIsInstance, None, int, "it's just not")
        self.assertEquals(str(e),
            "None is an instance of <type 'NoneType'> rather than <type 'int'>"
            ": it's just not")

    def test_assertEndsWith(self):
        self.assertEndsWith('foo', 'oo')
        self.assertRaises(AssertionError, self.assertEndsWith, 'o', 'oo')

    def test_applyDeprecated_not_deprecated(self):
        sample_object = ApplyDeprecatedHelper()
        # calling an undeprecated callable raises an assertion
        self.assertRaises(AssertionError, self.applyDeprecated,
            deprecated_in((0, 11, 0)),
            sample_object.sample_normal_method)
        self.assertRaises(AssertionError, self.applyDeprecated,
            deprecated_in((0, 11, 0)),
            sample_undeprecated_function, "a param value")
        # calling a deprecated callable (function or method) with the wrong
        # expected deprecation fails.
        self.assertRaises(AssertionError, self.applyDeprecated,
            deprecated_in((0, 10, 0)),
            sample_object.sample_deprecated_method, "a param value")
        self.assertRaises(AssertionError, self.applyDeprecated,
            deprecated_in((0, 10, 0)),
            sample_deprecated_function)
        # calling a deprecated callable (function or method) with the right
        # expected deprecation returns the functions result.
        self.assertEqual("a param value",
            self.applyDeprecated(deprecated_in((0, 11, 0)),
            sample_object.sample_deprecated_method, "a param value"))
        self.assertEqual(2, self.applyDeprecated(deprecated_in((0, 11, 0)),
            sample_deprecated_function))
        # calling a nested deprecation with the wrong deprecation version
        # fails even if a deeper nested function was deprecated with the
        # supplied version.
        self.assertRaises(AssertionError, self.applyDeprecated,
            deprecated_in((0, 11, 0)), sample_object.sample_nested_deprecation)
        # calling a nested deprecation with the right deprecation value
        # returns the calls result.
        self.assertEqual(2, self.applyDeprecated(deprecated_in((0, 10, 0)),
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


class TestWarningTests(tests.TestCase):
    """Tests for calling methods that raise warnings."""

    def test_callCatchWarnings(self):
        def meth(a, b):
            warnings.warn("this is your last warning")
            return a + b
        wlist, result = self.callCatchWarnings(meth, 1, 2)
        self.assertEquals(3, result)
        # would like just to compare them, but UserWarning doesn't implement
        # eq well
        w0, = wlist
        self.assertIsInstance(w0, UserWarning)
        self.assertEquals("this is your last warning", str(w0))


class TestConvenienceMakers(tests.TestCaseWithTransport):
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


class TestSFTPMakeBranchAndTree(test_sftp_transport.TestCaseWithSFTPServer):

    def test_make_tree_for_sftp_branch(self):
        """Transports backed by local directories create local trees."""
        # NB: This is arguably a bug in the definition of make_branch_and_tree.
        tree = self.make_branch_and_tree('t1')
        base = tree.bzrdir.root_transport.base
        self.failIf(base.startswith('sftp'),
                'base %r is on sftp but should be local' % base)
        self.assertEquals(tree.bzrdir.root_transport,
                tree.branch.bzrdir.root_transport)
        self.assertEquals(tree.bzrdir.root_transport,
                tree.branch.repository.bzrdir.root_transport)


class SelfTestHelper:

    def run_selftest(self, **kwargs):
        """Run selftest returning its output."""
        output = StringIO()
        old_transport = bzrlib.tests.default_transport
        old_root = tests.TestCaseWithMemoryTransport.TEST_ROOT
        tests.TestCaseWithMemoryTransport.TEST_ROOT = None
        try:
            self.assertEqual(True, tests.selftest(stream=output, **kwargs))
        finally:
            bzrlib.tests.default_transport = old_transport
            tests.TestCaseWithMemoryTransport.TEST_ROOT = old_root
        output.seek(0)
        return output


class TestSelftest(tests.TestCase, SelfTestHelper):
    """Tests of bzrlib.tests.selftest."""

    def test_selftest_benchmark_parameter_invokes_test_suite__benchmark__(self):
        factory_called = []
        def factory():
            factory_called.append(True)
            return TestUtil.TestSuite()
        out = StringIO()
        err = StringIO()
        self.apply_redirected(out, err, None, bzrlib.tests.selftest,
            test_suite_factory=factory)
        self.assertEqual([True], factory_called)

    def factory(self):
        """A test suite factory."""
        class Test(tests.TestCase):
            def a(self):
                pass
            def b(self):
                pass
            def c(self):
                pass
        return TestUtil.TestSuite([Test("a"), Test("b"), Test("c")])

    def test_list_only(self):
        output = self.run_selftest(test_suite_factory=self.factory,
            list_only=True)
        self.assertEqual(3, len(output.readlines()))

    def test_list_only_filtered(self):
        output = self.run_selftest(test_suite_factory=self.factory,
            list_only=True, pattern="Test.b")
        self.assertEndsWith(output.getvalue(), "Test.b\n")
        self.assertLength(1, output.readlines())

    def test_list_only_excludes(self):
        output = self.run_selftest(test_suite_factory=self.factory,
            list_only=True, exclude_pattern="Test.b")
        self.assertNotContainsRe("Test.b", output.getvalue())
        self.assertLength(2, output.readlines())

    def test_random(self):
        # test randomising by listing a number of tests.
        output_123 = self.run_selftest(test_suite_factory=self.factory,
            list_only=True, random_seed="123")
        output_234 = self.run_selftest(test_suite_factory=self.factory,
            list_only=True, random_seed="234")
        self.assertNotEqual(output_123, output_234)
        # "Randominzing test order..\n\n
        self.assertLength(5, output_123.readlines())
        self.assertLength(5, output_234.readlines())

    def test_random_reuse_is_same_order(self):
        # test randomising by listing a number of tests.
        expected = self.run_selftest(test_suite_factory=self.factory,
            list_only=True, random_seed="123")
        repeated = self.run_selftest(test_suite_factory=self.factory,
            list_only=True, random_seed="123")
        self.assertEqual(expected.getvalue(), repeated.getvalue())

    def test_runner_class(self):
        self.requireFeature(SubUnitFeature)
        from subunit import ProtocolTestCase
        stream = self.run_selftest(runner_class=tests.SubUnitBzrRunner,
            test_suite_factory=self.factory)
        test = ProtocolTestCase(stream)
        result = unittest.TestResult()
        test.run(result)
        self.assertEqual(3, result.testsRun)

    def test_starting_with_single_argument(self):
        output = self.run_selftest(test_suite_factory=self.factory,
            starting_with=['bzrlib.tests.test_selftest.Test.a'],
            list_only=True)
        self.assertEqual('bzrlib.tests.test_selftest.Test.a\n',
            output.getvalue())

    def test_starting_with_multiple_argument(self):
        output = self.run_selftest(test_suite_factory=self.factory,
            starting_with=['bzrlib.tests.test_selftest.Test.a',
                'bzrlib.tests.test_selftest.Test.b'],
            list_only=True)
        self.assertEqual('bzrlib.tests.test_selftest.Test.a\n'
            'bzrlib.tests.test_selftest.Test.b\n',
            output.getvalue())

    def check_transport_set(self, transport_server):
        captured_transport = []
        def seen_transport(a_transport):
            captured_transport.append(a_transport)
        class Capture(tests.TestCase):
            def a(self):
                seen_transport(bzrlib.tests.default_transport)
        def factory():
            return TestUtil.TestSuite([Capture("a")])
        self.run_selftest(transport=transport_server, test_suite_factory=factory)
        self.assertEqual(transport_server, captured_transport[0])

    def test_transport_sftp(self):
        try:
            import bzrlib.transport.sftp
        except errors.ParamikoNotPresent:
            raise tests.TestSkipped("Paramiko not present")
        self.check_transport_set(bzrlib.transport.sftp.SFTPAbsoluteServer)

    def test_transport_memory(self):
        self.check_transport_set(bzrlib.transport.memory.MemoryServer)


class TestSelftestWithIdList(tests.TestCaseInTempDir, SelfTestHelper):
    # Does IO: reads test.list

    def test_load_list(self):
        # Provide a list with one test - this test.
        test_id_line = '%s\n' % self.id()
        self.build_tree_contents([('test.list', test_id_line)])
        # And generate a list of the tests in  the suite.
        stream = self.run_selftest(load_list='test.list', list_only=True)
        self.assertEqual(test_id_line, stream.getvalue())

    def test_load_unknown(self):
        # Provide a list with one test - this test.
        # And generate a list of the tests in  the suite.
        err = self.assertRaises(errors.NoSuchFile, self.run_selftest,
            load_list='missing file name', list_only=True)


class TestRunBzr(tests.TestCase):

    out = ''
    err = ''

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
        return self.out, self.err

    def test_run_bzr_error(self):
        self.out = "It sure does!\n"
        out, err = self.run_bzr_error(['^$'], ['rocks'], retcode=34)
        self.assertEqual(['rocks'], self.argv)
        self.assertEqual(34, self.retcode)
        self.assertEqual(out, 'It sure does!\n')

    def test_run_bzr_error_regexes(self):
        self.out = ''
        self.err = "bzr: ERROR: foobarbaz is not versioned"
        out, err = self.run_bzr_error(
                ["bzr: ERROR: foobarbaz is not versioned"],
                ['file-id', 'foobarbaz'])

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


class TestRunBzrCaptured(tests.TestCaseWithTransport):
    # Does IO when testing the working_dir parameter.

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
        self.assertIsInstance(self.factory, tests.TestUIFactory)

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


class StubProcess(object):
    """A stub process for testing run_bzr_subprocess."""
    
    def __init__(self, out="", err="", retcode=0):
        self.out = out
        self.err = err
        self.returncode = retcode

    def communicate(self):
        return self.out, self.err


class TestRunBzrSubprocess(tests.TestCaseWithTransport):

    def setUp(self):
        tests.TestCaseWithTransport.setUp(self)
        self.subprocess_calls = []

    def start_bzr_subprocess(self, process_args, env_changes=None,
                             skip_if_plan_to_signal=False,
                             working_dir=None,
                             allow_plugins=False):
        """capture what run_bzr_subprocess tries to do."""
        self.subprocess_calls.append({'process_args':process_args,
            'env_changes':env_changes,
            'skip_if_plan_to_signal':skip_if_plan_to_signal,
            'working_dir':working_dir, 'allow_plugins':allow_plugins})
        return self.next_subprocess

    def assertRunBzrSubprocess(self, expected_args, process, *args, **kwargs):
        """Run run_bzr_subprocess with args and kwargs using a stubbed process.

        Inside TestRunBzrSubprocessCommands we use a stub start_bzr_subprocess
        that will return static results. This assertion method populates those
        results and also checks the arguments run_bzr_subprocess generates.
        """
        self.next_subprocess = process
        try:
            result = self.run_bzr_subprocess(*args, **kwargs)
        except:
            self.next_subprocess = None
            for key, expected in expected_args.iteritems():
                self.assertEqual(expected, self.subprocess_calls[-1][key])
            raise
        else:
            self.next_subprocess = None
            for key, expected in expected_args.iteritems():
                self.assertEqual(expected, self.subprocess_calls[-1][key])
            return result

    def test_run_bzr_subprocess(self):
        """The run_bzr_helper_external command behaves nicely."""
        self.assertRunBzrSubprocess({'process_args':['--version']},
            StubProcess(), '--version')
        self.assertRunBzrSubprocess({'process_args':['--version']},
            StubProcess(), ['--version'])
        # retcode=None disables retcode checking
        result = self.assertRunBzrSubprocess({},
            StubProcess(retcode=3), '--version', retcode=None)
        result = self.assertRunBzrSubprocess({},
            StubProcess(out="is free software"), '--version')
        self.assertContainsRe(result[0], 'is free software')
        # Running a subcommand that is missing errors
        self.assertRaises(AssertionError, self.assertRunBzrSubprocess,
            {'process_args':['--versionn']}, StubProcess(retcode=3),
            '--versionn')
        # Unless it is told to expect the error from the subprocess
        result = self.assertRunBzrSubprocess({},
            StubProcess(retcode=3), '--versionn', retcode=3)
        # Or to ignore retcode checking
        result = self.assertRunBzrSubprocess({},
            StubProcess(err="unknown command", retcode=3), '--versionn',
            retcode=None)
        self.assertContainsRe(result[1], 'unknown command')

    def test_env_change_passes_through(self):
        self.assertRunBzrSubprocess(
            {'env_changes':{'new':'value', 'changed':'newvalue', 'deleted':None}},
            StubProcess(), '',
            env_changes={'new':'value', 'changed':'newvalue', 'deleted':None})

    def test_no_working_dir_passed_as_None(self):
        self.assertRunBzrSubprocess({'working_dir': None}, StubProcess(), '')

    def test_no_working_dir_passed_through(self):
        self.assertRunBzrSubprocess({'working_dir': 'dir'}, StubProcess(), '',
            working_dir='dir')

    def test_run_bzr_subprocess_no_plugins(self):
        self.assertRunBzrSubprocess({'allow_plugins': False},
            StubProcess(), '')

    def test_allow_plugins(self):
        self.assertRunBzrSubprocess({'allow_plugins': True},
            StubProcess(), '', allow_plugins=True)


class _DontSpawnProcess(Exception):
    """A simple exception which just allows us to skip unnecessary steps"""


class TestStartBzrSubProcess(tests.TestCase):

    def check_popen_state(self):
        """Replace to make assertions when popen is called."""

    def _popen(self, *args, **kwargs):
        """Record the command that is run, so that we can ensure it is correct"""
        self.check_popen_state()
        self._popen_args = args
        self._popen_kwargs = kwargs
        raise _DontSpawnProcess()

    def test_run_bzr_subprocess_no_plugins(self):
        self.assertRaises(_DontSpawnProcess, self.start_bzr_subprocess, [])
        command = self._popen_args[0]
        self.assertEqual(sys.executable, command[0])
        self.assertEqual(self.get_bzr_path(), command[1])
        self.assertEqual(['--no-plugins'], command[2:])

    def test_allow_plugins(self):
        self.assertRaises(_DontSpawnProcess, self.start_bzr_subprocess, [],
            allow_plugins=True)
        command = self._popen_args[0]
        self.assertEqual([], command[2:])

    def test_set_env(self):
        self.failIf('EXISTANT_ENV_VAR' in os.environ)
        # set in the child
        def check_environment():
            self.assertEqual('set variable', os.environ['EXISTANT_ENV_VAR'])
        self.check_popen_state = check_environment
        self.assertRaises(_DontSpawnProcess, self.start_bzr_subprocess, [],
            env_changes={'EXISTANT_ENV_VAR':'set variable'})
        # not set in theparent
        self.assertFalse('EXISTANT_ENV_VAR' in os.environ)

    def test_run_bzr_subprocess_env_del(self):
        """run_bzr_subprocess can remove environment variables too."""
        self.failIf('EXISTANT_ENV_VAR' in os.environ)
        def check_environment():
            self.assertFalse('EXISTANT_ENV_VAR' in os.environ)
        os.environ['EXISTANT_ENV_VAR'] = 'set variable'
        self.check_popen_state = check_environment
        self.assertRaises(_DontSpawnProcess, self.start_bzr_subprocess, [],
            env_changes={'EXISTANT_ENV_VAR':None})
        # Still set in parent
        self.assertEqual('set variable', os.environ['EXISTANT_ENV_VAR'])
        del os.environ['EXISTANT_ENV_VAR']

    def test_env_del_missing(self):
        self.failIf('NON_EXISTANT_ENV_VAR' in os.environ)
        def check_environment():
            self.assertFalse('NON_EXISTANT_ENV_VAR' in os.environ)
        self.check_popen_state = check_environment
        self.assertRaises(_DontSpawnProcess, self.start_bzr_subprocess, [],
            env_changes={'NON_EXISTANT_ENV_VAR':None})

    def test_working_dir(self):
        """Test that we can specify the working dir for the child"""
        orig_getcwd = osutils.getcwd
        orig_chdir = os.chdir
        chdirs = []
        def chdir(path):
            chdirs.append(path)
        os.chdir = chdir
        try:
            def getcwd():
                return 'current'
            osutils.getcwd = getcwd
            try:
                self.assertRaises(_DontSpawnProcess, self.start_bzr_subprocess, [],
                    working_dir='foo')
            finally:
                osutils.getcwd = orig_getcwd
        finally:
            os.chdir = orig_chdir
        self.assertEqual(['foo', 'current'], chdirs)


class TestBzrSubprocess(tests.TestCaseWithTransport):

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


class TestKnownFailure(tests.TestCase):

    def test_known_failure(self):
        """Check that KnownFailure is defined appropriately."""
        # a KnownFailure is an assertion error for compatability with unaware
        # runners.
        self.assertIsInstance(tests.KnownFailure(""), AssertionError)

    def test_expect_failure(self):
        try:
            self.expectFailure("Doomed to failure", self.assertTrue, False)
        except tests.KnownFailure, e:
            self.assertEqual('Doomed to failure', e.args[0])
        try:
            self.expectFailure("Doomed to failure", self.assertTrue, True)
        except AssertionError, e:
            self.assertEqual('Unexpected success.  Should have failed:'
                             ' Doomed to failure', e.args[0])
        else:
            self.fail('Assertion not raised')


class TestFeature(tests.TestCase):

    def test_caching(self):
        """Feature._probe is called by the feature at most once."""
        class InstrumentedFeature(tests.Feature):
            def __init__(self):
                super(InstrumentedFeature, self).__init__()
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
        class NamedFeature(tests.Feature):
            def feature_name(self):
                return 'symlinks'
        feature = NamedFeature()
        self.assertEqual('symlinks', str(feature))

    def test_default_str(self):
        """Feature.__str__ should default to __class__.__name__."""
        class NamedFeature(tests.Feature):
            pass
        feature = NamedFeature()
        self.assertEqual('NamedFeature', str(feature))


class TestUnavailableFeature(tests.TestCase):

    def test_access_feature(self):
        feature = tests.Feature()
        exception = tests.UnavailableFeature(feature)
        self.assertIs(feature, exception.args[0])


class TestSelftestFiltering(tests.TestCase):

    def setUp(self):
        tests.TestCase.setUp(self)
        self.suite = TestUtil.TestSuite()
        self.loader = TestUtil.TestLoader()
        self.suite.addTest(self.loader.loadTestsFromModule(
            sys.modules['bzrlib.tests.test_selftest']))
        self.all_names = _test_ids(self.suite)

    def test_condition_id_re(self):
        test_name = ('bzrlib.tests.test_selftest.TestSelftestFiltering.'
            'test_condition_id_re')
        filtered_suite = tests.filter_suite_by_condition(
            self.suite, tests.condition_id_re('test_condition_id_re'))
        self.assertEqual([test_name], _test_ids(filtered_suite))

    def test_condition_id_in_list(self):
        test_names = ['bzrlib.tests.test_selftest.TestSelftestFiltering.'
                      'test_condition_id_in_list']
        id_list = tests.TestIdList(test_names)
        filtered_suite = tests.filter_suite_by_condition(
            self.suite, tests.condition_id_in_list(id_list))
        my_pattern = 'TestSelftestFiltering.*test_condition_id_in_list'
        re_filtered = tests.filter_suite_by_re(self.suite, my_pattern)
        self.assertEqual(_test_ids(re_filtered), _test_ids(filtered_suite))

    def test_condition_id_startswith(self):
        klass = 'bzrlib.tests.test_selftest.TestSelftestFiltering.'
        start1 = klass + 'test_condition_id_starts'
        start2 = klass + 'test_condition_id_in'
        test_names = [ klass + 'test_condition_id_in_list',
                      klass + 'test_condition_id_startswith',
                     ]
        filtered_suite = tests.filter_suite_by_condition(
            self.suite, tests.condition_id_startswith([start1, start2]))
        self.assertEqual(test_names, _test_ids(filtered_suite))

    def test_condition_isinstance(self):
        filtered_suite = tests.filter_suite_by_condition(
            self.suite, tests.condition_isinstance(self.__class__))
        class_pattern = 'bzrlib.tests.test_selftest.TestSelftestFiltering.'
        re_filtered = tests.filter_suite_by_re(self.suite, class_pattern)
        self.assertEqual(_test_ids(re_filtered), _test_ids(filtered_suite))

    def test_exclude_tests_by_condition(self):
        excluded_name = ('bzrlib.tests.test_selftest.TestSelftestFiltering.'
            'test_exclude_tests_by_condition')
        filtered_suite = tests.exclude_tests_by_condition(self.suite,
            lambda x:x.id() == excluded_name)
        self.assertEqual(len(self.all_names) - 1,
            filtered_suite.countTestCases())
        self.assertFalse(excluded_name in _test_ids(filtered_suite))
        remaining_names = list(self.all_names)
        remaining_names.remove(excluded_name)
        self.assertEqual(remaining_names, _test_ids(filtered_suite))

    def test_exclude_tests_by_re(self):
        self.all_names = _test_ids(self.suite)
        filtered_suite = tests.exclude_tests_by_re(self.suite,
                                                   'exclude_tests_by_re')
        excluded_name = ('bzrlib.tests.test_selftest.TestSelftestFiltering.'
            'test_exclude_tests_by_re')
        self.assertEqual(len(self.all_names) - 1,
            filtered_suite.countTestCases())
        self.assertFalse(excluded_name in _test_ids(filtered_suite))
        remaining_names = list(self.all_names)
        remaining_names.remove(excluded_name)
        self.assertEqual(remaining_names, _test_ids(filtered_suite))

    def test_filter_suite_by_condition(self):
        test_name = ('bzrlib.tests.test_selftest.TestSelftestFiltering.'
            'test_filter_suite_by_condition')
        filtered_suite = tests.filter_suite_by_condition(self.suite,
            lambda x:x.id() == test_name)
        self.assertEqual([test_name], _test_ids(filtered_suite))

    def test_filter_suite_by_re(self):
        filtered_suite = tests.filter_suite_by_re(self.suite,
                                                  'test_filter_suite_by_r')
        filtered_names = _test_ids(filtered_suite)
        self.assertEqual(filtered_names, ['bzrlib.tests.test_selftest.'
            'TestSelftestFiltering.test_filter_suite_by_re'])

    def test_filter_suite_by_id_list(self):
        test_list = ['bzrlib.tests.test_selftest.'
                     'TestSelftestFiltering.test_filter_suite_by_id_list']
        filtered_suite = tests.filter_suite_by_id_list(
            self.suite, tests.TestIdList(test_list))
        filtered_names = _test_ids(filtered_suite)
        self.assertEqual(
            filtered_names,
            ['bzrlib.tests.test_selftest.'
             'TestSelftestFiltering.test_filter_suite_by_id_list'])

    def test_filter_suite_by_id_startswith(self):
        # By design this test may fail if another test is added whose name also
        # begins with one of the start value used.
        klass = 'bzrlib.tests.test_selftest.TestSelftestFiltering.'
        start1 = klass + 'test_filter_suite_by_id_starts'
        start2 = klass + 'test_filter_suite_by_id_li'
        test_list = [klass + 'test_filter_suite_by_id_list',
                     klass + 'test_filter_suite_by_id_startswith',
                     ]
        filtered_suite = tests.filter_suite_by_id_startswith(
            self.suite, [start1, start2])
        self.assertEqual(
            test_list,
            _test_ids(filtered_suite),
            )

    def test_preserve_input(self):
        # NB: Surely this is something in the stdlib to do this?
        self.assertTrue(self.suite is tests.preserve_input(self.suite))
        self.assertTrue("@#$" is tests.preserve_input("@#$"))

    def test_randomize_suite(self):
        randomized_suite = tests.randomize_suite(self.suite)
        # randomizing should not add or remove test names.
        self.assertEqual(set(_test_ids(self.suite)),
                         set(_test_ids(randomized_suite)))
        # Technically, this *can* fail, because random.shuffle(list) can be
        # equal to list. Trying multiple times just pushes the frequency back.
        # As its len(self.all_names)!:1, the failure frequency should be low
        # enough to ignore. RBC 20071021.
        # It should change the order.
        self.assertNotEqual(self.all_names, _test_ids(randomized_suite))
        # But not the length. (Possibly redundant with the set test, but not
        # necessarily.)
        self.assertEqual(len(self.all_names), len(_test_ids(randomized_suite)))

    def test_split_suit_by_condition(self):
        self.all_names = _test_ids(self.suite)
        condition = tests.condition_id_re('test_filter_suite_by_r')
        split_suite = tests.split_suite_by_condition(self.suite, condition)
        filtered_name = ('bzrlib.tests.test_selftest.TestSelftestFiltering.'
            'test_filter_suite_by_re')
        self.assertEqual([filtered_name], _test_ids(split_suite[0]))
        self.assertFalse(filtered_name in _test_ids(split_suite[1]))
        remaining_names = list(self.all_names)
        remaining_names.remove(filtered_name)
        self.assertEqual(remaining_names, _test_ids(split_suite[1]))

    def test_split_suit_by_re(self):
        self.all_names = _test_ids(self.suite)
        split_suite = tests.split_suite_by_re(self.suite,
                                              'test_filter_suite_by_r')
        filtered_name = ('bzrlib.tests.test_selftest.TestSelftestFiltering.'
            'test_filter_suite_by_re')
        self.assertEqual([filtered_name], _test_ids(split_suite[0]))
        self.assertFalse(filtered_name in _test_ids(split_suite[1]))
        remaining_names = list(self.all_names)
        remaining_names.remove(filtered_name)
        self.assertEqual(remaining_names, _test_ids(split_suite[1]))


class TestCheckInventoryShape(tests.TestCaseWithTransport):

    def test_check_inventory_shape(self):
        files = ['a', 'b/', 'b/c']
        tree = self.make_branch_and_tree('.')
        self.build_tree(files)
        tree.add(files)
        tree.lock_read()
        try:
            self.check_inventory_shape(tree.inventory, files)
        finally:
            tree.unlock()


class TestBlackboxSupport(tests.TestCase):
    """Tests for testsuite blackbox features."""

    def test_run_bzr_failure_not_caught(self):
        # When we run bzr in blackbox mode, we want any unexpected errors to
        # propagate up to the test suite so that it can show the error in the
        # usual way, and we won't get a double traceback.
        e = self.assertRaises(
            AssertionError,
            self.run_bzr, ['assert-fail'])
        # make sure we got the real thing, not an error from somewhere else in
        # the test framework
        self.assertEquals('always fails', str(e))
        # check that there's no traceback in the test log
        self.assertNotContainsRe(self._get_log(keep_log_file=True),
            r'Traceback')

    def test_run_bzr_user_error_caught(self):
        # Running bzr in blackbox mode, normal/expected/user errors should be
        # caught in the regular way and turned into an error message plus exit
        # code.
        out, err = self.run_bzr(["log", "/nonexistantpath"], retcode=3)
        self.assertEqual(out, '')
        self.assertContainsRe(err,
            'bzr: ERROR: Not a branch: ".*nonexistantpath/".\n')


class TestTestLoader(tests.TestCase):
    """Tests for the test loader."""

    def _get_loader_and_module(self):
        """Gets a TestLoader and a module with one test in it."""
        loader = TestUtil.TestLoader()
        module = {}
        class Stub(tests.TestCase):
            def test_foo(self):
                pass
        class MyModule(object):
            pass
        MyModule.a_class = Stub
        module = MyModule()
        return loader, module

    def test_module_no_load_tests_attribute_loads_classes(self):
        loader, module = self._get_loader_and_module()
        self.assertEqual(1, loader.loadTestsFromModule(module).countTestCases())

    def test_module_load_tests_attribute_gets_called(self):
        loader, module = self._get_loader_and_module()
        # 'self' is here because we're faking the module with a class. Regular
        # load_tests do not need that :)
        def load_tests(self, standard_tests, module, loader):
            result = loader.suiteClass()
            for test in tests.iter_suite_tests(standard_tests):
                result.addTests([test, test])
            return result
        # add a load_tests() method which multiplies the tests from the module.
        module.__class__.load_tests = load_tests
        self.assertEqual(2, loader.loadTestsFromModule(module).countTestCases())

    def test_load_tests_from_module_name_smoke_test(self):
        loader = TestUtil.TestLoader()
        suite = loader.loadTestsFromModuleName('bzrlib.tests.test_sampler')
        self.assertEquals(['bzrlib.tests.test_sampler.DemoTest.test_nothing'],
                          _test_ids(suite))

    def test_load_tests_from_module_name_with_bogus_module_name(self):
        loader = TestUtil.TestLoader()
        self.assertRaises(ImportError, loader.loadTestsFromModuleName, 'bogus')


class TestTestIdList(tests.TestCase):

    def _create_id_list(self, test_list):
        return tests.TestIdList(test_list)

    def _create_suite(self, test_id_list):

        class Stub(tests.TestCase):
            def test_foo(self):
                pass

        def _create_test_id(id):
            return lambda: id

        suite = TestUtil.TestSuite()
        for id in test_id_list:
            t  = Stub('test_foo')
            t.id = _create_test_id(id)
            suite.addTest(t)
        return suite

    def _test_ids(self, test_suite):
        """Get the ids for the tests in a test suite."""
        return [t.id() for t in tests.iter_suite_tests(test_suite)]

    def test_empty_list(self):
        id_list = self._create_id_list([])
        self.assertEquals({}, id_list.tests)
        self.assertEquals({}, id_list.modules)

    def test_valid_list(self):
        id_list = self._create_id_list(
            ['mod1.cl1.meth1', 'mod1.cl1.meth2',
             'mod1.func1', 'mod1.cl2.meth2',
             'mod1.submod1',
             'mod1.submod2.cl1.meth1', 'mod1.submod2.cl2.meth2',
             ])
        self.assertTrue(id_list.refers_to('mod1'))
        self.assertTrue(id_list.refers_to('mod1.submod1'))
        self.assertTrue(id_list.refers_to('mod1.submod2'))
        self.assertTrue(id_list.includes('mod1.cl1.meth1'))
        self.assertTrue(id_list.includes('mod1.submod1'))
        self.assertTrue(id_list.includes('mod1.func1'))

    def test_bad_chars_in_params(self):
        id_list = self._create_id_list(['mod1.cl1.meth1(xx.yy)'])
        self.assertTrue(id_list.refers_to('mod1'))
        self.assertTrue(id_list.includes('mod1.cl1.meth1(xx.yy)'))

    def test_module_used(self):
        id_list = self._create_id_list(['mod.class.meth'])
        self.assertTrue(id_list.refers_to('mod'))
        self.assertTrue(id_list.refers_to('mod.class'))
        self.assertTrue(id_list.refers_to('mod.class.meth'))

    def test_test_suite_matches_id_list_with_unknown(self):
        loader = TestUtil.TestLoader()
        suite = loader.loadTestsFromModuleName('bzrlib.tests.test_sampler')
        test_list = ['bzrlib.tests.test_sampler.DemoTest.test_nothing',
                     'bogus']
        not_found, duplicates = tests.suite_matches_id_list(suite, test_list)
        self.assertEquals(['bogus'], not_found)
        self.assertEquals([], duplicates)

    def test_suite_matches_id_list_with_duplicates(self):
        loader = TestUtil.TestLoader()
        suite = loader.loadTestsFromModuleName('bzrlib.tests.test_sampler')
        dupes = loader.suiteClass()
        for test in tests.iter_suite_tests(suite):
            dupes.addTest(test)
            dupes.addTest(test) # Add it again

        test_list = ['bzrlib.tests.test_sampler.DemoTest.test_nothing',]
        not_found, duplicates = tests.suite_matches_id_list(
            dupes, test_list)
        self.assertEquals([], not_found)
        self.assertEquals(['bzrlib.tests.test_sampler.DemoTest.test_nothing'],
                          duplicates)


class TestTestSuite(tests.TestCase):

    def test_test_suite(self):
        # This test is slow - it loads the entire test suite to operate, so we
        # do a single test with one test in each category
        test_list = [
            # testmod_names
            'bzrlib.tests.blackbox.test_branch.TestBranch.test_branch',
            ('bzrlib.tests.per_transport.TransportTests'
             '.test_abspath(LocalURLServer)'),
            'bzrlib.tests.test_selftest.TestTestSuite.test_test_suite',
            # modules_to_doctest
            'bzrlib.timestamp.format_highres_date',
            # plugins can't be tested that way since selftest may be run with
            # --no-plugins
            ]
        suite = tests.test_suite(test_list)
        self.assertEquals(test_list, _test_ids(suite))

    def test_test_suite_list_and_start(self):
        # We cannot test this at the same time as the main load, because we want
        # to know that starting_with == None works. So a second full load is
        # incurred.
        test_list = ['bzrlib.tests.test_selftest.TestTestSuite.test_test_suite']
        suite = tests.test_suite(test_list,
                                 ['bzrlib.tests.test_selftest.TestTestSuite'])
        # test_test_suite_list_and_start is not included 
        self.assertEquals(test_list, _test_ids(suite))


class TestLoadTestIdList(tests.TestCaseInTempDir):

    def _create_test_list_file(self, file_name, content):
        fl = open(file_name, 'wt')
        fl.write(content)
        fl.close()

    def test_load_unknown(self):
        self.assertRaises(errors.NoSuchFile,
                          tests.load_test_id_list, 'i_do_not_exist')

    def test_load_test_list(self):
        test_list_fname = 'test.list'
        self._create_test_list_file(test_list_fname,
                                    'mod1.cl1.meth1\nmod2.cl2.meth2\n')
        tlist = tests.load_test_id_list(test_list_fname)
        self.assertEquals(2, len(tlist))
        self.assertEquals('mod1.cl1.meth1', tlist[0])
        self.assertEquals('mod2.cl2.meth2', tlist[1])

    def test_load_dirty_file(self):
        test_list_fname = 'test.list'
        self._create_test_list_file(test_list_fname,
                                    '  mod1.cl1.meth1\n\nmod2.cl2.meth2  \n'
                                    'bar baz\n')
        tlist = tests.load_test_id_list(test_list_fname)
        self.assertEquals(4, len(tlist))
        self.assertEquals('mod1.cl1.meth1', tlist[0])
        self.assertEquals('', tlist[1])
        self.assertEquals('mod2.cl2.meth2', tlist[2])
        self.assertEquals('bar baz', tlist[3])


class TestFilteredByModuleTestLoader(tests.TestCase):

    def _create_loader(self, test_list):
        id_filter = tests.TestIdList(test_list)
        loader = TestUtil.FilteredByModuleTestLoader(id_filter.refers_to)
        return loader

    def test_load_tests(self):
        test_list = ['bzrlib.tests.test_sampler.DemoTest.test_nothing']
        loader = self._create_loader(test_list)

        suite = loader.loadTestsFromModuleName('bzrlib.tests.test_sampler')
        self.assertEquals(test_list, _test_ids(suite))

    def test_exclude_tests(self):
        test_list = ['bogus']
        loader = self._create_loader(test_list)

        suite = loader.loadTestsFromModuleName('bzrlib.tests.test_sampler')
        self.assertEquals([], _test_ids(suite))


class TestFilteredByNameStartTestLoader(tests.TestCase):

    def _create_loader(self, name_start):
        def needs_module(name):
            return name.startswith(name_start) or name_start.startswith(name)
        loader = TestUtil.FilteredByModuleTestLoader(needs_module)
        return loader

    def test_load_tests(self):
        test_list = ['bzrlib.tests.test_sampler.DemoTest.test_nothing']
        loader = self._create_loader('bzrlib.tests.test_samp')

        suite = loader.loadTestsFromModuleName('bzrlib.tests.test_sampler')
        self.assertEquals(test_list, _test_ids(suite))

    def test_load_tests_inside_module(self):
        test_list = ['bzrlib.tests.test_sampler.DemoTest.test_nothing']
        loader = self._create_loader('bzrlib.tests.test_sampler.Demo')

        suite = loader.loadTestsFromModuleName('bzrlib.tests.test_sampler')
        self.assertEquals(test_list, _test_ids(suite))

    def test_exclude_tests(self):
        test_list = ['bogus']
        loader = self._create_loader('bogus')

        suite = loader.loadTestsFromModuleName('bzrlib.tests.test_sampler')
        self.assertEquals([], _test_ids(suite))


class TestTestPrefixRegistry(tests.TestCase):

    def _get_registry(self):
        tp_registry = tests.TestPrefixAliasRegistry()
        return tp_registry

    def test_register_new_prefix(self):
        tpr = self._get_registry()
        tpr.register('foo', 'fff.ooo.ooo')
        self.assertEquals('fff.ooo.ooo', tpr.get('foo'))

    def test_register_existing_prefix(self):
        tpr = self._get_registry()
        tpr.register('bar', 'bbb.aaa.rrr')
        tpr.register('bar', 'bBB.aAA.rRR')
        self.assertEquals('bbb.aaa.rrr', tpr.get('bar'))
        self.assertContainsRe(self._get_log(keep_log_file=True),
                              r'.*bar.*bbb.aaa.rrr.*bBB.aAA.rRR')

    def test_get_unknown_prefix(self):
        tpr = self._get_registry()
        self.assertRaises(KeyError, tpr.get, 'I am not a prefix')

    def test_resolve_prefix(self):
        tpr = self._get_registry()
        tpr.register('bar', 'bb.aa.rr')
        self.assertEquals('bb.aa.rr', tpr.resolve_alias('bar'))

    def test_resolve_unknown_alias(self):
        tpr = self._get_registry()
        self.assertRaises(errors.BzrCommandError,
                          tpr.resolve_alias, 'I am not a prefix')

    def test_predefined_prefixes(self):
        tpr = tests.test_prefix_alias_registry
        self.assertEquals('bzrlib', tpr.resolve_alias('bzrlib'))
        self.assertEquals('bzrlib.doc', tpr.resolve_alias('bd'))
        self.assertEquals('bzrlib.utils', tpr.resolve_alias('bu'))
        self.assertEquals('bzrlib.tests', tpr.resolve_alias('bt'))
        self.assertEquals('bzrlib.tests.blackbox', tpr.resolve_alias('bb'))
        self.assertEquals('bzrlib.plugins', tpr.resolve_alias('bp'))


class TestRunSuite(tests.TestCase):

    def test_runner_class(self):
        """run_suite accepts and uses a runner_class keyword argument."""
        class Stub(tests.TestCase):
            def test_foo(self):
                pass
        suite = Stub("test_foo")
        calls = []
        class MyRunner(tests.TextTestRunner):
            def run(self, test):
                calls.append(test)
                return tests.ExtendedTestResult(self.stream, self.descriptions,
                                                self.verbosity)
        tests.run_suite(suite, runner_class=MyRunner, stream=StringIO())
        self.assertLength(1, calls)

    def test_done(self):
        """run_suite should call result.done()"""
        self.calls = 0
        def one_more_call(): self.calls += 1
        def test_function():
            pass
        test = unittest.FunctionTestCase(test_function)
        class InstrumentedTestResult(tests.ExtendedTestResult):
            def done(self): one_more_call()
        class MyRunner(tests.TextTestRunner):
            def run(self, test):
                return InstrumentedTestResult(self.stream, self.descriptions,
                                              self.verbosity)
        tests.run_suite(test, runner_class=MyRunner, stream=StringIO())
        self.assertEquals(1, self.calls)
