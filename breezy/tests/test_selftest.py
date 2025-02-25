# Copyright (C) 2005-2013, 2016 Canonical Ltd
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

import contextlib
import doctest
import gc
import os
import signal
import sys
import threading
import time
import unittest
import warnings
from functools import reduce
from io import BytesIO, StringIO, TextIOWrapper

import testtools.testresult.doubles
from testtools import ExtendedToOriginalDecorator, MultiTestResult
from testtools.content import Content
from testtools.content_type import ContentType
from testtools.matchers import DocTestMatches, Equals

import breezy

from .. import (
    branchbuilder,
    controldir,
    errors,
    hooks,
    lockdir,
    memorytree,
    osutils,
    repository,
    symbol_versioning,
    tests,
    transport,
    workingtree,
)
from ..bzr import bzrdir, groupcompress_repo, remote, workingtree_3, workingtree_4
from ..git import workingtree as git_workingtree
from ..symbol_versioning import deprecated_function, deprecated_in, deprecated_method
from ..trace import mutter, note
from ..transport import memory
from . import TestUtil, features, test_server


def _test_ids(test_suite):
    """Get the ids for the tests in a test suite."""
    return [t.id() for t in tests.iter_suite_tests(test_suite)]


class MetaTestLog(tests.TestCase):
    def test_logging(self):
        """Test logs are captured when a test fails."""
        self.log("a test message")
        details = self.getDetails()
        log = details["log"]
        self.assertThat(
            log.content_type, Equals(ContentType("text", "plain", {"charset": "utf8"}))
        )
        self.assertThat("".join(log.iter_text()), Equals(self.get_log()))
        self.assertThat(
            self.get_log(), DocTestMatches("...a test message\n", doctest.ELLIPSIS)
        )


class TestTreeShape(tests.TestCaseInTempDir):
    def test_unicode_paths(self):
        self.requireFeature(features.UnicodeFilenameFeature)

        filename = "hell\u00d8"
        self.build_tree_contents([(filename, b"contents of hello")])
        self.assertPathExists(filename)


class TestClassesAvailable(tests.TestCase):
    """As a convenience we expose Test* classes from breezy.tests."""

    def test_test_case(self):
        pass

    def test_test_loader(self):
        pass

    def test_test_suite(self):
        pass


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
        class MockModule:
            def get_test_permutations(self):
                return sample_permutation

        sample_permutation = [(1, 2), (3, 4)]
        from .per_transport import get_transport_test_permutations

        self.assertEqual(
            sample_permutation, get_transport_test_permutations(MockModule())
        )

    def test_scenarios_include_all_modules(self):
        # this checks that the scenario generator returns as many permutations
        # as there are in all the registered transport modules - we assume if
        # this matches its probably doing the right thing especially in
        # combination with the tests for setting the right classes below.
        from ..transport import _get_transport_modules
        from .per_transport import transport_test_permutations

        modules = _get_transport_modules()
        permutation_count = 0
        for module in modules:
            with contextlib.suppress(errors.DependencyNotPresent):
                permutation_count += len(
                    reduce(
                        getattr,
                        (module + ".get_test_permutations").split(".")[1:],
                        __import__(module),
                    )()
                )
        scenarios = transport_test_permutations()
        self.assertEqual(permutation_count, len(scenarios))

    def test_scenarios_include_transport_class(self):
        # This test used to know about all the possible transports and the
        # order they were returned but that seems overly brittle (mbp
        # 20060307)
        from .per_transport import transport_test_permutations

        scenarios = transport_test_permutations()
        # there are at least that many builtin transports
        self.assertGreater(len(scenarios), 6)
        one_scenario = scenarios[0]
        self.assertIsInstance(one_scenario[0], str)
        self.assertTrue(
            issubclass(one_scenario[1]["transport_class"], breezy.transport.Transport)
        )
        self.assertTrue(
            issubclass(one_scenario[1]["transport_server"], breezy.transport.Server)
        )


class TestBranchScenarios(tests.TestCase):
    def test_scenarios(self):
        # check that constructor parameters are passed through to the adapted
        # test.
        from .per_branch import make_scenarios

        server1 = "a"
        server2 = "b"
        formats = [("c", "C"), ("d", "D")]
        scenarios = make_scenarios(server1, server2, formats)
        self.assertEqual(2, len(scenarios))
        self.assertEqual(
            [
                (
                    "str",
                    {
                        "branch_format": "c",
                        "bzrdir_format": "C",
                        "transport_readonly_server": "b",
                        "transport_server": "a",
                    },
                ),
                (
                    "str",
                    {
                        "branch_format": "d",
                        "bzrdir_format": "D",
                        "transport_readonly_server": "b",
                        "transport_server": "a",
                    },
                ),
            ],
            scenarios,
        )


class TestBzrDirScenarios(tests.TestCase):
    def test_scenarios(self):
        # check that constructor parameters are passed through to the adapted
        # test.
        from .per_controldir import make_scenarios

        vfs_factory = "v"
        server1 = "a"
        server2 = "b"
        formats = ["c", "d"]
        scenarios = make_scenarios(vfs_factory, server1, server2, formats)
        self.assertEqual(
            [
                (
                    "str",
                    {
                        "bzrdir_format": "c",
                        "transport_readonly_server": "b",
                        "transport_server": "a",
                        "vfs_transport_factory": "v",
                    },
                ),
                (
                    "str",
                    {
                        "bzrdir_format": "d",
                        "transport_readonly_server": "b",
                        "transport_server": "a",
                        "vfs_transport_factory": "v",
                    },
                ),
            ],
            scenarios,
        )


class TestRepositoryScenarios(tests.TestCase):
    def test_formats_to_scenarios(self):
        from .per_repository import formats_to_scenarios

        formats = [
            ("(c)", remote.RemoteRepositoryFormat()),
            (
                "(d)",
                repository.format_registry.get(
                    b"Bazaar repository format 2a (needs bzr 1.16 or later)\n"
                ),
            ),
        ]
        no_vfs_scenarios = formats_to_scenarios(formats, "server", "readonly", None)
        vfs_scenarios = formats_to_scenarios(
            formats, "server", "readonly", vfs_transport_factory="vfs"
        )
        # no_vfs generate scenarios without vfs_transport_factory
        expected = [
            (
                "RemoteRepositoryFormat(c)",
                {
                    "bzrdir_format": remote.RemoteBzrDirFormat(),
                    "repository_format": remote.RemoteRepositoryFormat(),
                    "transport_readonly_server": "readonly",
                    "transport_server": "server",
                },
            ),
            (
                "RepositoryFormat2a(d)",
                {
                    "bzrdir_format": bzrdir.BzrDirMetaFormat1(),
                    "repository_format": groupcompress_repo.RepositoryFormat2a(),
                    "transport_readonly_server": "readonly",
                    "transport_server": "server",
                },
            ),
        ]
        self.assertEqual(expected, no_vfs_scenarios)
        self.assertEqual(
            [
                (
                    "RemoteRepositoryFormat(c)",
                    {
                        "bzrdir_format": remote.RemoteBzrDirFormat(),
                        "repository_format": remote.RemoteRepositoryFormat(),
                        "transport_readonly_server": "readonly",
                        "transport_server": "server",
                        "vfs_transport_factory": "vfs",
                    },
                ),
                (
                    "RepositoryFormat2a(d)",
                    {
                        "bzrdir_format": bzrdir.BzrDirMetaFormat1(),
                        "repository_format": groupcompress_repo.RepositoryFormat2a(),
                        "transport_readonly_server": "readonly",
                        "transport_server": "server",
                        "vfs_transport_factory": "vfs",
                    },
                ),
            ],
            vfs_scenarios,
        )


class TestTestScenarioApplication(tests.TestCase):
    """Tests for the test adaption facilities."""

    def test_apply_scenario(self):
        from breezy.tests import apply_scenario

        input_test = TestTestScenarioApplication("test_apply_scenario")
        # setup two adapted tests
        adapted_test1 = apply_scenario(
            input_test,
            (
                "new id",
                {
                    "bzrdir_format": "bzr_format",
                    "repository_format": "repo_fmt",
                    "transport_server": "transport_server",
                    "transport_readonly_server": "readonly-server",
                },
            ),
        )
        adapted_test2 = apply_scenario(
            input_test, ("new id 2", {"bzrdir_format": None})
        )
        # input_test should have been altered.
        self.assertRaises(AttributeError, getattr, input_test, "bzrdir_format")
        # the new tests are mutually incompatible, ensuring it has
        # made new ones, and unspecified elements in the scenario
        # should not have been altered.
        self.assertEqual("bzr_format", adapted_test1.bzrdir_format)
        self.assertEqual("repo_fmt", adapted_test1.repository_format)
        self.assertEqual("transport_server", adapted_test1.transport_server)
        self.assertEqual("readonly-server", adapted_test1.transport_readonly_server)
        self.assertEqual(
            "breezy.tests.test_selftest.TestTestScenarioApplication."
            "test_apply_scenario(new id)",
            adapted_test1.id(),
        )
        self.assertEqual(None, adapted_test2.bzrdir_format)
        self.assertEqual(
            "breezy.tests.test_selftest.TestTestScenarioApplication."
            "test_apply_scenario(new id 2)",
            adapted_test2.id(),
        )


class TestInterRepositoryScenarios(tests.TestCase):
    def test_scenarios(self):
        # check that constructor parameters are passed through to the adapted
        # test.
        from .per_interrepository import make_scenarios

        server1 = "a"
        server2 = "b"
        formats = [("C0", "C1", "C2", "C3"), ("D0", "D1", "D2", "D3")]
        scenarios = make_scenarios(server1, server2, formats)
        self.assertEqual(
            [
                (
                    "C0,str,str",
                    {
                        "repository_format": "C1",
                        "repository_format_to": "C2",
                        "transport_readonly_server": "b",
                        "transport_server": "a",
                        "extra_setup": "C3",
                    },
                ),
                (
                    "D0,str,str",
                    {
                        "repository_format": "D1",
                        "repository_format_to": "D2",
                        "transport_readonly_server": "b",
                        "transport_server": "a",
                        "extra_setup": "D3",
                    },
                ),
            ],
            scenarios,
        )


class TestWorkingTreeScenarios(tests.TestCase):
    def test_scenarios(self):
        # check that constructor parameters are passed through to the adapted
        # test.
        from .per_workingtree import make_scenarios

        server1 = "a"
        server2 = "b"
        formats = [
            workingtree_4.WorkingTreeFormat4(),
            workingtree_3.WorkingTreeFormat3(),
            workingtree_4.WorkingTreeFormat6(),
        ]
        scenarios = make_scenarios(
            server1,
            server2,
            formats,
            remote_server="c",
            remote_readonly_server="d",
            remote_backing_server="e",
        )
        self.assertEqual(
            [
                (
                    "WorkingTreeFormat4",
                    {
                        "bzrdir_format": formats[0]._matchingcontroldir,
                        "transport_readonly_server": "b",
                        "transport_server": "a",
                        "workingtree_format": formats[0],
                    },
                ),
                (
                    "WorkingTreeFormat3",
                    {
                        "bzrdir_format": formats[1]._matchingcontroldir,
                        "transport_readonly_server": "b",
                        "transport_server": "a",
                        "workingtree_format": formats[1],
                    },
                ),
                (
                    "WorkingTreeFormat6",
                    {
                        "bzrdir_format": formats[2]._matchingcontroldir,
                        "transport_readonly_server": "b",
                        "transport_server": "a",
                        "workingtree_format": formats[2],
                    },
                ),
                (
                    "WorkingTreeFormat6,remote",
                    {
                        "bzrdir_format": formats[2]._matchingcontroldir,
                        "repo_is_remote": True,
                        "transport_readonly_server": "d",
                        "transport_server": "c",
                        "vfs_transport_factory": "e",
                        "workingtree_format": formats[2],
                    },
                ),
            ],
            scenarios,
        )


class TestTreeScenarios(tests.TestCase):
    def test_scenarios(self):
        # the tree implementation scenario generator is meant to setup one
        # instance for each working tree format, one additional instance
        # that will use the default wt format, but create a revision tree for
        # the tests, and one more that uses the default wt format as a
        # lightweight checkout of a remote repository.  This means that the wt
        # ones should have the workingtree_to_test_tree attribute set to
        # 'return_parameter' and the revision one set to
        # revision_tree_from_workingtree.

        from .per_tree import (
            _dirstate_tree_from_workingtree,
            make_scenarios,
            preview_tree_post,
            preview_tree_pre,
            return_parameter,
            revision_tree_from_workingtree,
        )

        server1 = "a"
        server2 = "b"
        smart_server = test_server.SmartTCPServer_for_testing
        smart_readonly_server = test_server.ReadonlySmartTCPServer_for_testing
        mem_server = memory.MemoryServer
        formats = [
            workingtree_4.WorkingTreeFormat4(),
            workingtree_3.WorkingTreeFormat3(),
        ]
        scenarios = make_scenarios(server1, server2, formats)
        self.assertEqual(9, len(scenarios))
        default_wt_format = workingtree.format_registry.get_default()
        wt4_format = workingtree_4.WorkingTreeFormat4()
        wt5_format = workingtree_4.WorkingTreeFormat5()
        wt6_format = workingtree_4.WorkingTreeFormat6()
        git_wt_format = git_workingtree.GitWorkingTreeFormat()
        expected_scenarios = [
            (
                "WorkingTreeFormat4",
                {
                    "bzrdir_format": formats[0]._matchingcontroldir,
                    "transport_readonly_server": "b",
                    "transport_server": "a",
                    "workingtree_format": formats[0],
                    "_workingtree_to_test_tree": return_parameter,
                },
            ),
            (
                "WorkingTreeFormat3",
                {
                    "bzrdir_format": formats[1]._matchingcontroldir,
                    "transport_readonly_server": "b",
                    "transport_server": "a",
                    "workingtree_format": formats[1],
                    "_workingtree_to_test_tree": return_parameter,
                },
            ),
            (
                "WorkingTreeFormat6,remote",
                {
                    "bzrdir_format": wt6_format._matchingcontroldir,
                    "repo_is_remote": True,
                    "transport_readonly_server": smart_readonly_server,
                    "transport_server": smart_server,
                    "vfs_transport_factory": mem_server,
                    "workingtree_format": wt6_format,
                    "_workingtree_to_test_tree": return_parameter,
                },
            ),
            (
                "RevisionTree",
                {
                    "_workingtree_to_test_tree": revision_tree_from_workingtree,
                    "bzrdir_format": default_wt_format._matchingcontroldir,
                    "transport_readonly_server": "b",
                    "transport_server": "a",
                    "workingtree_format": default_wt_format,
                },
            ),
            (
                "GitRevisionTree",
                {
                    "_workingtree_to_test_tree": revision_tree_from_workingtree,
                    "bzrdir_format": git_wt_format._matchingcontroldir,
                    "transport_readonly_server": "b",
                    "transport_server": "a",
                    "workingtree_format": git_wt_format,
                },
            ),
            (
                "DirStateRevisionTree,WT4",
                {
                    "_workingtree_to_test_tree": _dirstate_tree_from_workingtree,
                    "bzrdir_format": wt4_format._matchingcontroldir,
                    "transport_readonly_server": "b",
                    "transport_server": "a",
                    "workingtree_format": wt4_format,
                },
            ),
            (
                "DirStateRevisionTree,WT5",
                {
                    "_workingtree_to_test_tree": _dirstate_tree_from_workingtree,
                    "bzrdir_format": wt5_format._matchingcontroldir,
                    "transport_readonly_server": "b",
                    "transport_server": "a",
                    "workingtree_format": wt5_format,
                },
            ),
            (
                "PreviewTree",
                {
                    "_workingtree_to_test_tree": preview_tree_pre,
                    "bzrdir_format": default_wt_format._matchingcontroldir,
                    "transport_readonly_server": "b",
                    "transport_server": "a",
                    "workingtree_format": default_wt_format,
                },
            ),
            (
                "PreviewTreePost",
                {
                    "_workingtree_to_test_tree": preview_tree_post,
                    "bzrdir_format": default_wt_format._matchingcontroldir,
                    "transport_readonly_server": "b",
                    "transport_server": "a",
                    "workingtree_format": default_wt_format,
                },
            ),
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
        from ..bzr.workingtree_3 import WorkingTreeFormat3
        from ..bzr.workingtree_4 import WorkingTreeFormat4
        from .per_intertree import make_scenarios
        from .per_tree import return_parameter

        TestInterTreeScenarios("test_scenarios")
        server1 = "a"
        server2 = "b"
        format1 = WorkingTreeFormat4()
        format2 = WorkingTreeFormat3()
        formats = [
            ("1", str, format1, format2, "converter1"),
            ("2", int, format2, format1, "converter2"),
        ]
        scenarios = make_scenarios(server1, server2, formats)
        self.assertEqual(2, len(scenarios))
        expected_scenarios = [
            (
                "1",
                {
                    "bzrdir_format": format1._matchingcontroldir,
                    "intertree_class": formats[0][1],
                    "workingtree_format": formats[0][2],
                    "workingtree_format_to": formats[0][3],
                    "mutable_trees_to_test_trees": formats[0][4],
                    "_workingtree_to_test_tree": return_parameter,
                    "transport_server": server1,
                    "transport_readonly_server": server2,
                },
            ),
            (
                "2",
                {
                    "bzrdir_format": format2._matchingcontroldir,
                    "intertree_class": formats[1][1],
                    "workingtree_format": formats[1][2],
                    "workingtree_format_to": formats[1][3],
                    "mutable_trees_to_test_trees": formats[1][4],
                    "_workingtree_to_test_tree": return_parameter,
                    "transport_server": server1,
                    "transport_readonly_server": server2,
                },
            ),
        ]
        self.assertEqual(scenarios, expected_scenarios)


class TestTestCaseInTempDir(tests.TestCaseInTempDir):
    def test_home_is_not_working(self):
        self.assertNotEqual(self.test_dir, self.test_home_dir)
        cwd = osutils.getcwd()
        self.assertIsSameRealPath(self.test_dir, cwd)
        self.assertIsSameRealPath(self.test_home_dir, os.environ["HOME"])

    def test_assertEqualStat_equal(self):
        from ..bzr.tests.test_dirstate import _FakeStat

        self.build_tree(["foo"])
        real = os.lstat("foo")
        fake = _FakeStat(
            real.st_size,
            real.st_mtime,
            real.st_ctime,
            real.st_dev,
            real.st_ino,
            real.st_mode,
        )
        self.assertEqualStat(real, fake)

    def test_assertEqualStat_notequal(self):
        self.build_tree(["foo", "longname"])
        self.assertRaises(
            AssertionError, self.assertEqualStat, os.lstat("foo"), os.lstat("longname")
        )

    def test_assertPathExists(self):
        self.assertPathExists(".")
        self.build_tree(["foo/", "foo/bar"])
        self.assertPathExists("foo/bar")
        self.assertPathDoesNotExist("foo/foo")


class TestTestCaseWithMemoryTransport(tests.TestCaseWithMemoryTransport):
    def test_home_is_non_existant_dir_under_root(self):
        """The test_home_dir for TestCaseWithMemoryTransport is missing.

        This is because TestCaseWithMemoryTransport is for tests that do not
        need any disk resources: they should be hooked into breezy in such a
        way that no global settings are being changed by the test (only a
        few tests should need to do that), and having a missing dir as home is
        an effective way to ensure that this is the case.
        """
        self.assertIsSameRealPath(
            self.TEST_ROOT + "/MemoryTransportMissingHomeDir", self.test_home_dir
        )
        self.assertIsSameRealPath(self.test_home_dir, os.environ["HOME"])

    def test_cwd_is_TEST_ROOT(self):
        self.assertIsSameRealPath(self.test_dir, self.TEST_ROOT)
        cwd = osutils.getcwd()
        self.assertIsSameRealPath(self.test_dir, cwd)

    def test_BRZ_HOME_and_HOME_are_bytestrings(self):
        """The $BRZ_HOME and $HOME environment variables should not be unicode.

        See https://bugs.launchpad.net/bzr/+bug/464174
        """
        self.assertIsInstance(os.environ["BRZ_HOME"], str)
        self.assertIsInstance(os.environ["HOME"], str)

    def test_make_branch_and_memory_tree(self):
        """In TestCaseWithMemoryTransport we should not make the branch on disk.

        This is hard to comprehensively robustly test, so we settle for making
        a branch and checking no directory was created at its relpath.
        """
        tree = self.make_branch_and_memory_tree("dir")
        # Guard against regression into MemoryTransport leaking
        # files to disk instead of keeping them in memory.
        self.assertFalse(osutils.lexists("dir"))
        self.assertIsInstance(tree, memorytree.MemoryTree)

    def test_make_branch_and_memory_tree_with_format(self):
        """make_branch_and_memory_tree should accept a format option."""
        format = bzrdir.BzrDirMetaFormat1()
        format.repository_format = repository.format_registry.get_default()
        tree = self.make_branch_and_memory_tree("dir", format=format)
        # Guard against regression into MemoryTransport leaking
        # files to disk instead of keeping them in memory.
        self.assertFalse(osutils.lexists("dir"))
        self.assertIsInstance(tree, memorytree.MemoryTree)
        self.assertEqual(
            format.repository_format.__class__, tree.branch.repository._format.__class__
        )

    def test_make_branch_builder(self):
        builder = self.make_branch_builder("dir")
        self.assertIsInstance(builder, branchbuilder.BranchBuilder)
        # Guard against regression into MemoryTransport leaking
        # files to disk instead of keeping them in memory.
        self.assertFalse(osutils.lexists("dir"))

    def test_make_branch_builder_with_format(self):
        # Use a repo layout that doesn't conform to a 'named' layout, to ensure
        # that the format objects are used.
        format = bzrdir.BzrDirMetaFormat1()
        repo_format = repository.format_registry.get_default()
        format.repository_format = repo_format
        builder = self.make_branch_builder("dir", format=format)
        the_branch = builder.get_branch()
        # Guard against regression into MemoryTransport leaking
        # files to disk instead of keeping them in memory.
        self.assertFalse(osutils.lexists("dir"))
        self.assertEqual(
            format.repository_format.__class__, the_branch.repository._format.__class__
        )
        self.assertEqual(
            repo_format.get_format_string(),
            self.get_transport().get_bytes("dir/.bzr/repository/format"),
        )

    def test_make_branch_builder_with_format_name(self):
        builder = self.make_branch_builder("dir", format="knit")
        the_branch = builder.get_branch()
        # Guard against regression into MemoryTransport leaking
        # files to disk instead of keeping them in memory.
        self.assertFalse(osutils.lexists("dir"))
        dir_format = controldir.format_registry.make_controldir("knit")
        self.assertEqual(
            dir_format.repository_format.__class__,
            the_branch.repository._format.__class__,
        )
        self.assertEqual(
            b"Bazaar-NG Knit Repository Format 1",
            self.get_transport().get_bytes("dir/.bzr/repository/format"),
        )

    def test_dangling_locks_cause_failures(self):
        class TestDanglingLock(tests.TestCaseWithMemoryTransport):
            def test_function(self):
                t = self.get_transport_from_path(".")
                l = lockdir.LockDir(t, "lock")
                l.create()
                l.attempt_lock()

        test = TestDanglingLock("test_function")
        result = test.run()
        total_failures = result.errors + result.failures
        if self._lock_check_thorough:
            self.assertEqual(1, len(total_failures))
        else:
            # When _lock_check_thorough is disabled, then we don't trigger a
            # failure
            self.assertEqual(0, len(total_failures))


class TestTestCaseWithTransport(tests.TestCaseWithTransport):
    """Tests for the convenience functions TestCaseWithTransport introduces."""

    def test_get_readonly_url_none(self):
        from ..transport.readonly import ReadonlyTransportDecorator

        self.vfs_transport_factory = memory.MemoryServer
        self.transport_readonly_server = None
        # calling get_readonly_transport() constructs a decorator on the url
        # for the server
        url = self.get_readonly_url()
        url2 = self.get_readonly_url("foo/bar")
        t = transport.get_transport_from_url(url)
        t2 = transport.get_transport_from_url(url2)
        self.assertIsInstance(t, ReadonlyTransportDecorator)
        self.assertIsInstance(t2, ReadonlyTransportDecorator)
        self.assertEqual(t2.base[:-1], t.abspath("foo/bar"))

    def test_get_readonly_url_http(self):
        from ..transport.http.urllib import HttpTransport
        from .http_server import HttpServer

        self.transport_server = test_server.LocalURLServer
        self.transport_readonly_server = HttpServer
        # calling get_readonly_transport() gives us a HTTP server instance.
        url = self.get_readonly_url()
        url2 = self.get_readonly_url("foo/bar")
        # the transport returned may be any HttpTransportBase subclass
        t = transport.get_transport_from_url(url)
        t2 = transport.get_transport_from_url(url2)
        self.assertIsInstance(t, HttpTransport)
        self.assertIsInstance(t2, HttpTransport)
        self.assertEqual(t2.base[:-1], t.abspath("foo/bar"))

    def test_is_directory(self):
        """Test assertIsDirectory assertion."""
        t = self.get_transport()
        self.build_tree(["a_dir/", "a_file"], transport=t)
        self.assertIsDirectory("a_dir", t)
        self.assertRaises(AssertionError, self.assertIsDirectory, "a_file", t)
        self.assertRaises(AssertionError, self.assertIsDirectory, "not_here", t)

    def test_make_branch_builder(self):
        builder = self.make_branch_builder("dir")
        rev_id = builder.build_commit()
        self.assertPathExists("dir")
        a_dir = controldir.ControlDir.open("dir")
        self.assertRaises(errors.NoWorkingTree, a_dir.open_workingtree)
        a_branch = a_dir.open_branch()
        builder_branch = builder.get_branch()
        self.assertEqual(a_branch.base, builder_branch.base)
        self.assertEqual((1, rev_id), builder_branch.last_revision_info())
        self.assertEqual((1, rev_id), a_branch.last_revision_info())


class TestTestCaseTransports(tests.TestCaseWithTransport):
    def setUp(self):
        super().setUp()
        self.vfs_transport_factory = memory.MemoryServer

    def test_make_controldir_preserves_transport(self):
        self.get_transport()
        result_bzrdir = self.make_controldir("subdir")
        self.assertIsInstance(result_bzrdir.transport, memory.MemoryTransport)
        # should not be on disk, should only be in memory
        self.assertPathDoesNotExist("subdir")


class TestChrootedTest(tests.ChrootedTestCase):
    def test_root_is_root(self):
        t = transport.get_transport_from_url(self.get_readonly_url())
        url = t.base
        self.assertEqual(url, t.clone("..").base)


class TestProfileResult(tests.TestCase):
    def test_profiles_tests(self):
        self.requireFeature(features.lsprof_feature)
        terminal = testtools.testresult.doubles.ExtendedTestResult()
        result = tests.ProfileResult(terminal)

        class Sample(tests.TestCase):
            def a(self):
                self.sample_function()

            def sample_function(self):
                pass

        test = Sample("a")
        test.run(result)
        case = terminal._events[0][1]
        self.assertLength(1, case._benchcalls)
        # We must be able to unpack it as the test reporting code wants
        (_, _, _), stats = case._benchcalls[0]
        self.assertTrue(callable(stats.pprint))


class TestTestResult(tests.TestCase):
    def check_timing(self, test_case, expected_re):
        result = tests.TextTestResult(StringIO(), descriptions=0, verbosity=1)
        capture = testtools.testresult.doubles.ExtendedTestResult()
        test_case.run(MultiTestResult(result, capture))
        run_case = capture._events[0][1]
        timed_string = result._testTimeString(run_case)
        self.assertContainsRe(timed_string, expected_re)

    def test_test_reporting(self):
        class ShortDelayTestCase(tests.TestCase):
            def test_short_delay(self):
                time.sleep(0.003)

            def test_short_benchmark(self):
                self.time(time.sleep, 0.003)

        self.check_timing(ShortDelayTestCase("test_short_delay"), r"^ +[0-9]+ms$")
        # if a benchmark time is given, we now show just that time followed by
        # a star
        self.check_timing(ShortDelayTestCase("test_short_benchmark"), r"^ +[0-9]+ms\*$")

    def test_unittest_reporting_unittest_class(self):
        # getting the time from a non-breezy test works ok
        class ShortDelayTestCase(unittest.TestCase):
            def test_short_delay(self):
                time.sleep(0.003)

        self.check_timing(ShortDelayTestCase("test_short_delay"), r"^ +[0-9]+ms$")

    def _time_hello_world_encoding(self):
        """Profile two sleep calls.

        This is used to exercise the test framework.
        """
        self.time(str, b"hello", errors="replace")
        self.time(str, b"world", errors="replace")

    def test_lsprofiling(self):
        """Verbose test result prints lsprof statistics from test cases."""
        self.requireFeature(features.lsprof_feature)
        result_stream = StringIO()
        result = breezy.tests.VerboseTestResult(
            result_stream,
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
        self.assertContainsRe(
            output,
            r"LSProf output for <class 'str'>\(\(b'hello',\), {'errors': 'replace'}\)",
        )
        self.assertContainsRe(
            output,
            r"LSProf output for <class 'str'>\(\(b'world',\), {'errors': 'replace'}\)",
        )
        self.assertContainsRe(
            output,
            r" *CallCount *Recursive *Total\(ms\) *Inline\(ms\) *module:lineno\(function\)\n",
        )
        self.assertContainsRe(
            output,
            r"( +1 +0 +0\.\d+ +0\.\d+ +<method 'disable' of '_lsprof\.Profiler' objects>\n)?",
        )

    def test_uses_time_from_testtools(self):
        """Test case timings in verbose results should use testtools times."""
        import datetime

        class TimeAddedVerboseTestResult(tests.VerboseTestResult):
            def startTest(self, test):
                try:
                    dt = datetime.datetime.fromtimestamp(1.145, datetime.UTC)
                except AttributeError:
                    dt = datetime.datetime.utcfromtimestamp(1.145)
                self.time(dt)
                super().startTest(test)

            def addSuccess(self, test):
                try:
                    dt = datetime.datetime.fromtimestamp(51.147, datetime.UTC)
                except AttributeError:
                    dt = datetime.datetime.utcfromtimestamp(51.147)
                self.time(dt)
                super().addSuccess(test)

            def report_tests_starting(self):
                pass

        sio = StringIO()
        self.get_passing_test().run(TimeAddedVerboseTestResult(sio, 0, 2))
        self.assertEndsWith(sio.getvalue(), "OK    50002ms\n")

    def test_known_failure(self):
        """Using knownFailure should trigger several result actions."""

        class InstrumentedTestResult(tests.ExtendedTestResult):
            def stopTestRun(self):
                pass

            def report_tests_starting(self):
                pass

            def report_known_failure(self, test, err=None, details=None):
                self._call = test, "known failure"

        result = InstrumentedTestResult(None, None, None, None)

        class Test(tests.TestCase):
            def test_function(self):
                self.knownFailure("failed!")

        test = Test("test_function")
        test.run(result)
        # it should invoke 'report_known_failure'.
        self.assertEqual(2, len(result._call))
        self.assertEqual(test.id(), result._call[0].id())
        self.assertEqual("known failure", result._call[1])
        # we dont introspec the traceback, if the rest is ok, it would be
        # exceptional for it not to be.
        # it should update the known_failure_count on the object.
        self.assertEqual(1, result.known_failure_count)
        # the result should be successful.
        self.assertTrue(result.wasSuccessful())

    def test_verbose_report_known_failure(self):
        # verbose test output formatting
        result_stream = StringIO()
        result = breezy.tests.VerboseTestResult(
            result_stream,
            descriptions=0,
            verbosity=2,
        )
        _get_test("test_xfail").run(result)
        self.assertContainsRe(
            result_stream.getvalue(),
            "\n\\S+\\.test_xfail\\s+XFAIL\\s+\\d+ms\n"
            "\\s*(?:Text attachment: )?reason"
            "(?:\n-+\n|: {{{)"
            "this_fails"
            "(?:\n-+\n|}}}\n)",
        )

    def get_passing_test(self):
        """Return a test object that can't be run usefully."""

        def passing_test():
            pass

        return unittest.FunctionTestCase(passing_test)

    def test_add_not_supported(self):
        """Test the behaviour of invoking addNotSupported."""

        class InstrumentedTestResult(tests.ExtendedTestResult):
            def stopTestRun(self):
                pass

            def report_tests_starting(self):
                pass

            def report_unsupported(self, test, feature):
                self._call = test, feature

        result = InstrumentedTestResult(None, None, None, None)
        test = SampleTestCase("_test_pass")
        feature = features.Feature()
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
        self.assertEqual(1, result.unsupported["Feature"])
        # and invoking it again should increment that counter
        result.addNotSupported(test, feature)
        self.assertEqual(2, result.unsupported["Feature"])

    def test_verbose_report_unsupported(self):
        # verbose test output formatting
        result_stream = StringIO()
        result = breezy.tests.VerboseTestResult(
            result_stream,
            descriptions=0,
            verbosity=2,
        )
        test = self.get_passing_test()
        feature = features.Feature()
        result.startTest(test)
        prefix = len(result_stream.getvalue())
        result.report_unsupported(test, feature)
        output = result_stream.getvalue()[prefix:]
        lines = output.splitlines()
        # We don't check for the final '0ms' since it may fail on slow hosts
        self.assertStartsWith(lines[0], "NODEP")
        self.assertEqual(lines[1], "    The feature 'Feature' is not available.")

    def test_unavailable_exception(self):
        """An UnavailableFeature being raised should invoke addNotSupported."""

        class InstrumentedTestResult(tests.ExtendedTestResult):
            def stopTestRun(self):
                pass

            def report_tests_starting(self):
                pass

            def addNotSupported(self, test, feature):
                self._call = test, feature

        result = InstrumentedTestResult(None, None, None, None)
        feature = features.Feature()

        class Test(tests.TestCase):
            def test_function(self):
                raise tests.UnavailableFeature(feature)

        test = Test("test_function")
        test.run(result)
        # it should invoke 'addNotSupported'.
        self.assertEqual(2, len(result._call))
        self.assertEqual(test.id(), result._call[0].id())
        self.assertEqual(feature, result._call[1])
        # and not count as an error
        self.assertEqual(0, result.error_count)

    def test_strict_with_unsupported_feature(self):
        result = tests.TextTestResult(StringIO(), descriptions=0, verbosity=1)
        test = self.get_passing_test()
        feature = "Unsupported Feature"
        result.addNotSupported(test, feature)
        self.assertFalse(result.wasStrictlySuccessful())
        self.assertEqual(None, result._extractBenchmarkTime(test))

    def test_strict_with_known_failure(self):
        result = tests.TextTestResult(StringIO(), descriptions=0, verbosity=1)
        test = _get_test("test_xfail")
        test.run(result)
        self.assertFalse(result.wasStrictlySuccessful())
        self.assertEqual(None, result._extractBenchmarkTime(test))

    def test_strict_with_success(self):
        result = tests.TextTestResult(StringIO(), descriptions=0, verbosity=1)
        test = self.get_passing_test()
        result.addSuccess(test)
        self.assertTrue(result.wasStrictlySuccessful())
        self.assertEqual(None, result._extractBenchmarkTime(test))

    def test_startTests(self):
        """Starting the first test should trigger startTests."""

        class InstrumentedTestResult(tests.ExtendedTestResult):
            calls = 0

            def startTests(self):
                self.calls += 1

        result = InstrumentedTestResult(None, None, None, None)

        def test_function():
            pass

        test = unittest.FunctionTestCase(test_function)
        test.run(result)
        self.assertEqual(1, result.calls)

    def test_startTests_only_once(self):
        """With multiple tests startTests should still only be called once."""

        class InstrumentedTestResult(tests.ExtendedTestResult):
            calls = 0

            def startTests(self):
                self.calls += 1

        result = InstrumentedTestResult(None, None, None, None)
        suite = unittest.TestSuite(
            [
                unittest.FunctionTestCase(lambda: None),
                unittest.FunctionTestCase(lambda: None),
            ]
        )
        suite.run(result)
        self.assertEqual(1, result.calls)
        self.assertEqual(2, result.count)


class TestRunner(tests.TestCase):
    def dummy_test(self):
        pass

    def run_test_runner(self, testrunner, test):
        """Run suite in testrunner, saving global state and restoring it.

        This current saves and restores:
        TestCaseInTempDir.TEST_ROOT

        There should be no tests in this file that use
        breezy.tests.TextTestRunner without using this convenience method,
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
        class Test(tests.TestCase):
            def known_failure_test(self):
                self.expectFailure("failed", self.assertTrue, False)

        test = unittest.TestSuite()
        test.addTest(Test("known_failure_test"))

        def failing_test():
            raise AssertionError("foo")

        test.addTest(unittest.FunctionTestCase(failing_test))
        stream = StringIO()
        runner = tests.TextTestRunner(stream=stream)
        self.run_test_runner(runner, test)
        self.assertContainsRe(
            stream.getvalue(),
            "(?sm)^brz selftest.*$"
            ".*"
            "^======================================================================\n"
            "^FAIL: failing_test\n"
            "^----------------------------------------------------------------------\n"
            "Traceback \\(most recent call last\\):\n"
            "  .*"  # File .*, line .*, in failing_test' - but maybe not from .pyc
            '    raise AssertionError\\("foo"\\)\n'
            ".*"
            "^----------------------------------------------------------------------\n"
            ".*"
            "FAILED \\(failures=1, known_failure_count=1\\)",
        )

    def test_known_failure_ok_run(self):
        # run a test that generates a known failure which should be printed in
        # the final output.
        class Test(tests.TestCase):
            def known_failure_test(self):
                self.knownFailure("Never works...")

        test = Test("known_failure_test")
        stream = StringIO()
        runner = tests.TextTestRunner(stream=stream)
        self.run_test_runner(runner, test)
        self.assertContainsRe(
            stream.getvalue(),
            "\n-*\nRan 1 test in .*\n\nOK \\(known_failures=1\\)\n",
        )

    def test_unexpected_success_bad(self):
        class Test(tests.TestCase):
            def test_truth(self):
                self.expectFailure("No absolute truth", self.assertTrue, True)

        runner = tests.TextTestRunner(stream=StringIO())
        self.run_test_runner(runner, Test("test_truth"))
        self.assertContainsRe(
            runner.stream.getvalue(),
            "=+\n"
            "FAIL: \\S+\\.test_truth\n"
            "-+\n"
            "(?:.*\n)*"
            "\\s*(?:Text attachment: )?reason"
            "(?:\n-+\n|: {{{)"
            "No absolute truth"
            "(?:\n-+\n|}}}\n)"
            "(?:.*\n)*"
            "-+\n"
            "Ran 1 test in .*\n"
            "\n"
            "FAILED \\(failures=1\\)\n\\Z",
        )

    def test_result_decorator(self):
        # decorate results
        calls = []

        class LoggingDecorator(ExtendedToOriginalDecorator):
            def startTest(self, test):
                ExtendedToOriginalDecorator.startTest(self, test)
                calls.append("start")

        test = unittest.FunctionTestCase(lambda: None)
        stream = StringIO()
        runner = tests.TextTestRunner(
            stream=stream, result_decorators=[LoggingDecorator]
        )
        self.run_test_runner(runner, test)
        self.assertLength(1, calls)

    def test_skipped_test(self):
        # run a test that is skipped, and check the suite as a whole still
        # succeeds.
        # skipping_test must be hidden in here so it's not run as a real test
        class SkippingTest(tests.TestCase):
            def skipping_test(self):
                raise tests.TestSkipped("test intentionally skipped")

        runner = tests.TextTestRunner(stream=StringIO())
        test = SkippingTest("skipping_test")
        result = self.run_test_runner(runner, test)
        self.assertTrue(result.wasSuccessful())

    def test_skipped_from_setup(self):
        calls = []

        class SkippedSetupTest(tests.TestCase):
            def setUp(self):
                calls.append("setUp")
                self.addCleanup(self.cleanup)
                raise tests.TestSkipped("skipped setup")

            def test_skip(self):
                self.fail("test reached")

            def cleanup(self):
                calls.append("cleanup")

        runner = tests.TextTestRunner(stream=StringIO())
        test = SkippedSetupTest("test_skip")
        result = self.run_test_runner(runner, test)
        self.assertTrue(result.wasSuccessful())
        # Check if cleanup was called the right number of times.
        self.assertEqual(["setUp", "cleanup"], calls)

    def test_skipped_from_test(self):
        calls = []

        class SkippedTest(tests.TestCase):
            def setUp(self):
                super().setUp()
                calls.append("setUp")
                self.addCleanup(self.cleanup)

            def test_skip(self):
                raise tests.TestSkipped("skipped test")

            def cleanup(self):
                calls.append("cleanup")

        runner = tests.TextTestRunner(stream=StringIO())
        test = SkippedTest("test_skip")
        result = self.run_test_runner(runner, test)
        self.assertTrue(result.wasSuccessful())
        # Check if cleanup was called the right number of times.
        self.assertEqual(["setUp", "cleanup"], calls)

    def test_not_applicable(self):
        # run a test that is skipped because it's not applicable
        class Test(tests.TestCase):
            def not_applicable_test(self):
                raise tests.TestNotApplicable("this test never runs")

        out = StringIO()
        runner = tests.TextTestRunner(stream=out, verbosity=2)
        test = Test("not_applicable_test")
        result = self.run_test_runner(runner, test)
        self.log(out.getvalue())
        self.assertTrue(result.wasSuccessful())
        self.assertTrue(result.wasStrictlySuccessful())
        self.assertContainsRe(out.getvalue(), r"(?m)not_applicable_test  * N/A")
        self.assertContainsRe(out.getvalue(), r"(?m)^    this test never runs")

    def test_unsupported_features_listed(self):
        """When unsupported features are encountered they are detailed."""

        class Feature1(features.Feature):
            def _probe(self):
                return False

        class Feature2(features.Feature):
            def _probe(self):
                return False

        # create sample tests
        test1 = SampleTestCase("_test_pass")
        test1._test_needs_features = [Feature1()]
        test2 = SampleTestCase("_test_pass")
        test2._test_needs_features = [Feature2()]
        test = unittest.TestSuite()
        test.addTest(test1)
        test.addTest(test2)
        stream = StringIO()
        runner = tests.TextTestRunner(stream=stream)
        self.run_test_runner(runner, test)
        lines = stream.getvalue().splitlines()
        self.assertEqual(
            [
                "OK",
                "Missing feature 'Feature1' skipped 1 tests.",
                "Missing feature 'Feature2' skipped 1 tests.",
            ],
            lines[-3:],
        )

    def test_verbose_test_count(self):
        """A verbose test run reports the right test count at the start."""
        suite = TestUtil.TestSuite(
            [
                unittest.FunctionTestCase(lambda: None),
                unittest.FunctionTestCase(lambda: None),
            ]
        )
        self.assertEqual(suite.countTestCases(), 2)
        stream = StringIO()
        runner = tests.TextTestRunner(stream=stream, verbosity=2)
        # Need to use the CountingDecorator as that's what sets num_tests
        self.run_test_runner(runner, tests.CountingDecorator(suite))
        self.assertStartsWith(stream.getvalue(), "running 2 tests")

    def test_startTestRun(self):
        """Run should call result.startTestRun()."""
        calls = []

        class LoggingDecorator(ExtendedToOriginalDecorator):
            def startTestRun(self):
                ExtendedToOriginalDecorator.startTestRun(self)
                calls.append("startTestRun")

        test = unittest.FunctionTestCase(lambda: None)
        stream = StringIO()
        runner = tests.TextTestRunner(
            stream=stream, result_decorators=[LoggingDecorator]
        )
        self.run_test_runner(runner, test)
        self.assertLength(1, calls)

    def test_stopTestRun(self):
        """Run should call result.stopTestRun()."""
        calls = []

        class LoggingDecorator(ExtendedToOriginalDecorator):
            def stopTestRun(self):
                ExtendedToOriginalDecorator.stopTestRun(self)
                calls.append("stopTestRun")

        test = unittest.FunctionTestCase(lambda: None)
        stream = StringIO()
        runner = tests.TextTestRunner(
            stream=stream, result_decorators=[LoggingDecorator]
        )
        self.run_test_runner(runner, test)
        self.assertLength(1, calls)

    def test_unicode_test_output_on_ascii_stream(self):
        """Showing results should always succeed even on an ascii console."""

        class FailureWithUnicode(tests.TestCase):
            def test_log_unicode(self):
                self.log("\u2606")
                self.fail("Now print that log!")

        bio = BytesIO()
        out = TextIOWrapper(bio, "ascii", "backslashreplace")
        self.overrideAttr(osutils, "get_terminal_encoding", lambda trace=False: "ascii")
        self.run_test_runner(
            tests.TextTestRunner(stream=out), FailureWithUnicode("test_log_unicode")
        )
        out.flush()
        self.assertContainsRe(
            bio.getvalue(),
            b"(?:Text attachment: )?log"
            b"(?:\n-+\n|: {{{)"
            b"\\d+\\.\\d+  \\\\u2606"
            b"(?:\n-+\n|}}}\n)",
        )


class SampleTestCase(tests.TestCase):
    def _test_pass(self):
        pass


class _TestException(Exception):
    pass


class TestTestCase(tests.TestCase):
    """Tests that test the core breezy TestCase."""

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
        exception = self.assertRaises(AssertionError, self.assertLength, 2, a_list)
        self.assertEqual(
            "Incorrect length: wanted 2, got 3 for [1, 2, 3]", exception.args[0]
        )

    def test_base_setUp_not_called_causes_failure(self):
        class TestCaseWithBrokenSetUp(tests.TestCase):
            def setUp(self):
                pass  # does not call TestCase.setUp

            def test_foo(self):
                pass

        test = TestCaseWithBrokenSetUp("test_foo")
        result = unittest.TestResult()
        test.run(result)
        self.assertFalse(result.wasSuccessful())
        self.assertEqual(1, result.testsRun)

    def test_base_tearDown_not_called_causes_failure(self):
        class TestCaseWithBrokenTearDown(tests.TestCase):
            def tearDown(self):
                pass  # does not call TestCase.tearDown

            def test_foo(self):
                pass

        test = TestCaseWithBrokenTearDown("test_foo")
        result = unittest.TestResult()
        test.run(result)
        self.assertFalse(result.wasSuccessful())
        self.assertEqual(1, result.testsRun)

    def test_debug_flags_sanitised(self):
        """The breezy debug flags should be sanitised by setUp."""
        if "allow_debug" in tests.selftest_debug_flags:
            raise tests.TestNotApplicable(
                "-Eallow_debug option prevents debug flag sanitisation"
            )
        # we could set something and run a test that will check
        # it gets santised, but this is probably sufficient for now:
        # if someone runs the test with -Dsomething it will error.
        flags = set()
        if self._lock_check_thorough:
            flags.add("strict_locks")
        self.assertEqual(flags, breezy.debug.get_debug_flags())

    def change_selftest_debug_flags(self, new_flags):
        self.overrideAttr(tests, "selftest_debug_flags", set(new_flags))

    def test_allow_debug_flag(self):
        """The -Eallow_debug flag prevents breezy.debug.debug_flags from being
        sanitised (i.e. cleared) before running a test.
        """
        self.change_selftest_debug_flags({"allow_debug"})
        breezy.debug.clear_debug_flags()
        breezy.debug.set_debug_flag("a-flag")

        class TestThatRecordsFlags(tests.TestCase):
            def test_foo(nested_self):  # noqa: N805
                self.flags = breezy.debug.get_debug_flags()

        test = TestThatRecordsFlags("test_foo")
        test.run(self.make_test_result())
        flags = {"a-flag"}
        if "disable_lock_checks" not in tests.selftest_debug_flags:
            flags.add("strict_locks")
        self.assertEqual(flags, self.flags)

    def test_disable_lock_checks(self):
        """The -Edisable_lock_checks flag disables thorough checks."""

        class TestThatRecordsFlags(tests.TestCase):
            def test_foo(nested_self):  # noqa: N805
                self.flags = breezy.debug.get_debug_flags()
                self.test_lock_check_thorough = nested_self._lock_check_thorough

        self.change_selftest_debug_flags(set())
        test = TestThatRecordsFlags("test_foo")
        test.run(self.make_test_result())
        # By default we do strict lock checking and thorough lock/unlock
        # tracking.
        self.assertTrue(self.test_lock_check_thorough)
        self.assertEqual({"strict_locks"}, self.flags)
        # Now set the disable_lock_checks flag, and show that this changed.
        self.change_selftest_debug_flags({"disable_lock_checks"})
        test = TestThatRecordsFlags("test_foo")
        test.run(self.make_test_result())
        self.assertFalse(self.test_lock_check_thorough)
        self.assertEqual(set(), self.flags)

    def test_this_fails_strict_lock_check(self):
        class TestThatRecordsFlags(tests.TestCase):
            def test_foo(nested_self):  # noqa: N805
                self.flags1 = breezy.debug.get_debug_flags()
                self.thisFailsStrictLockCheck()
                self.flags2 = breezy.debug.get_debug_flags()

        # Make sure lock checking is active
        self.change_selftest_debug_flags(set())
        test = TestThatRecordsFlags("test_foo")
        test.run(self.make_test_result())
        self.assertEqual({"strict_locks"}, self.flags1)
        self.assertEqual(set(), self.flags2)

    def test_debug_flags_restored(self):
        """The breezy debug flags should be restored to their original state
        after the test was run, even if allow_debug is set.
        """
        self.change_selftest_debug_flags({"allow_debug"})
        # Now run a test that modifies debug.debug_flags.
        breezy.debug.clear_debug_flags()
        breezy.debug.set_debug_flag("original-state")

        class TestThatModifiesFlags(tests.TestCase):
            def test_foo(self):
                breezy.debug.clear_debug_flags()
                breezy.debug.set_debug_flag("modified")

        test = TestThatModifiesFlags("test_foo")
        test.run(self.make_test_result())
        self.assertEqual({"original-state"}, breezy.debug.get_debug_flags())

    def make_test_result(self):
        """Get a test result that writes to a StringIO."""
        return tests.TextTestResult(StringIO(), descriptions=0, verbosity=1)

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
        self.addCleanup(osutils.delete_any, self._log_file_name)

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
        original_trace = breezy.trace._trace_handler
        outer_test = TestTestCase("outer_child")
        result = self.make_test_result()
        outer_test.run(result)
        self.assertEqual(original_trace, breezy.trace._trace_handler)

    def method_that_times_a_bit_twice(self):
        # call self.time twice to ensure it aggregates
        self.time(time.sleep, 0.007)
        self.time(time.sleep, 0.007)

    def test_time_creates_benchmark_in_result(self):
        """The TestCase.time() method accumulates a benchmark time."""
        sample_test = TestTestCase("method_that_times_a_bit_twice")
        output_stream = StringIO()
        result = breezy.tests.VerboseTestResult(
            output_stream, descriptions=0, verbosity=2
        )
        sample_test.run(result)
        self.assertContainsRe(output_stream.getvalue(), r"\d+ms\*\n$")

    def test_hooks_sanitised(self):
        """The breezy hooks should be sanitised by setUp."""
        # Note this test won't fail with hooks that the core library doesn't
        # use - but it trigger with a plugin that adds hooks, so its still a
        # useful warning in that case.
        self.assertEqual(breezy.branch.BranchHooks(), breezy.branch.Branch.hooks)
        self.assertEqual(
            breezy.bzr.smart.server.SmartServerHooks(),
            breezy.bzr.smart.server.SmartTCPServer.hooks,
        )
        self.assertEqual(breezy.commands.CommandHooks(), breezy.commands.Command.hooks)

    def test__gather_lsprof_in_benchmarks(self):
        """When _gather_lsprof_in_benchmarks is on, accumulate profile data.

        Each self.time() call is individually and separately profiled.
        """
        self.requireFeature(features.lsprof_feature)
        # overrides the class member with an instance member so no cleanup
        # needed.
        self._gather_lsprof_in_benchmarks = True
        self.time(time.sleep, 0.000)
        self.time(time.sleep, 0.003)
        self.assertEqual(2, len(self._benchcalls))
        self.assertEqual((time.sleep, (0.000,), {}), self._benchcalls[0][0])
        self.assertEqual((time.sleep, (0.003,), {}), self._benchcalls[1][0])
        self.assertIsInstance(self._benchcalls[0][1], breezy.lsprof.Stats)
        self.assertIsInstance(self._benchcalls[1][1], breezy.lsprof.Stats)
        del self._benchcalls[:]

    def test_knownFailure(self):
        """Self.knownFailure() should raise a KnownFailure exception."""
        self.assertRaises(tests.KnownFailure, self.knownFailure, "A Failure")

    def test_open_bzrdir_safe_roots(self):
        # even a memory transport should fail to open when its url isn't
        # permitted.
        # Manually set one up (TestCase doesn't and shouldn't provide magic
        # machinery)
        transport_server = memory.MemoryServer()
        transport_server.start_server()
        self.addCleanup(transport_server.stop_server)
        t = transport.get_transport_from_url(transport_server.get_url())
        controldir.ControlDir.create(t.base)
        self.assertRaises(errors.BzrError, controldir.ControlDir.open_from_transport, t)
        # But if we declare this as safe, we can open the bzrdir.
        self.permit_url(t.base)
        self._bzr_selftest_roots.append(t.base)
        controldir.ControlDir.open_from_transport(t)

    def test_requireFeature_available(self):
        """self.requireFeature(available) is a no-op."""

        class Available(features.Feature):
            def _probe(self):
                return True

        feature = Available()
        self.requireFeature(feature)

    def test_requireFeature_unavailable(self):
        """self.requireFeature(unavailable) raises UnavailableFeature."""

        class Unavailable(features.Feature):
            def _probe(self):
                return False

        feature = Unavailable()
        self.assertRaises(tests.UnavailableFeature, self.requireFeature, feature)

    def test_run_no_parameters(self):
        test = SampleTestCase("_test_pass")
        test.run()

    def test_run_enabled_unittest_result(self):
        """Test we revert to regular behaviour when the test is enabled."""
        test = SampleTestCase("_test_pass")

        class EnabledFeature:
            def available(self):
                return True

        test._test_needs_features = [EnabledFeature()]
        result = unittest.TestResult()
        test.run(result)
        self.assertEqual(1, result.testsRun)
        self.assertEqual([], result.errors)
        self.assertEqual([], result.failures)

    def test_run_disabled_unittest_result(self):
        """Test our compatibility for disabled tests with unittest results."""
        test = SampleTestCase("_test_pass")

        class DisabledFeature:
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
        test = SampleTestCase("_test_pass")

        class DisabledFeature:
            def __eq__(self, other):
                return isinstance(other, DisabledFeature)

            def available(self):
                return False

        the_feature = DisabledFeature()
        test._test_needs_features = [the_feature]

        class InstrumentedTestResult(unittest.TestResult):
            def __init__(self):
                unittest.TestResult.__init__(self)
                self.calls = []

            def startTest(self, test):
                self.calls.append(("startTest", test))

            def stopTest(self, test):
                self.calls.append(("stopTest", test))

            def addNotSupported(self, test, feature):
                self.calls.append(("addNotSupported", test, feature))

        result = InstrumentedTestResult()
        test.run(result)
        case = result.calls[0][1]
        self.assertEqual(
            [
                ("startTest", case),
                ("addNotSupported", case, the_feature),
                ("stopTest", case),
            ],
            result.calls,
        )

    def test_start_server_registers_url(self):
        transport_server = memory.MemoryServer()
        # A little strict, but unlikely to be changed soon.
        self.assertEqual([], self._bzr_selftest_roots)
        self.start_server(transport_server)
        self.assertSubset([transport_server.get_url()], self._bzr_selftest_roots)

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
        self.assertRaises(
            _NotTestException, self.assertListRaises, _TestException, wrong_exception
        )
        self.assertRaises(
            _NotTestException,
            self.assertListRaises,
            _TestException,
            wrong_exception_generator,
        )

    def test_assert_list_raises_no_exception(self):
        def success():
            return []

        def success_generator():
            yield 1
            yield 2

        self.assertRaises(
            AssertionError, self.assertListRaises, _TestException, success
        )

        self.assertRaises(
            AssertionError, self.assertListRaises, _TestException, success_generator
        )

    def _run_successful_test(self, test):
        result = testtools.TestResult()
        test.run(result)
        self.assertTrue(result.wasSuccessful())
        return result

    def test_overrideAttr_without_value(self):
        self.test_attr = "original"  # Define a test attribute
        obj = self  # Make 'obj' visible to the embedded test

        class Test(tests.TestCase):
            def setUp(self):
                super().setUp()
                self.orig = self.overrideAttr(obj, "test_attr")

            def test_value(self):
                self.assertEqual("original", self.orig)
                self.assertEqual("original", obj.test_attr)
                obj.test_attr = "modified"
                self.assertEqual("modified", obj.test_attr)

        self._run_successful_test(Test("test_value"))
        self.assertEqual("original", obj.test_attr)

    def test_overrideAttr_with_value(self):
        self.test_attr = "original"  # Define a test attribute
        obj = self  # Make 'obj' visible to the embedded test

        class Test(tests.TestCase):
            def setUp(self):
                super().setUp()
                self.orig = self.overrideAttr(obj, "test_attr", new="modified")

            def test_value(self):
                self.assertEqual("original", self.orig)
                self.assertEqual("modified", obj.test_attr)

        self._run_successful_test(Test("test_value"))
        self.assertEqual("original", obj.test_attr)

    def test_overrideAttr_with_no_existing_value_and_value(self):
        # Do not define the test_attribute
        obj = self  # Make 'obj' visible to the embedded test

        class Test(tests.TestCase):
            def setUp(self):
                tests.TestCase.setUp(self)
                self.orig = self.overrideAttr(obj, "test_attr", new="modified")

            def test_value(self):
                self.assertEqual(tests._unitialized_attr, self.orig)
                self.assertEqual("modified", obj.test_attr)

        self._run_successful_test(Test("test_value"))
        self.assertRaises(AttributeError, getattr, obj, "test_attr")

    def test_overrideAttr_with_no_existing_value_and_no_value(self):
        # Do not define the test_attribute
        obj = self  # Make 'obj' visible to the embedded test

        class Test(tests.TestCase):
            def setUp(self):
                tests.TestCase.setUp(self)
                self.orig = self.overrideAttr(obj, "test_attr")

            def test_value(self):
                self.assertEqual(tests._unitialized_attr, self.orig)
                self.assertRaises(AttributeError, getattr, obj, "test_attr")

        self._run_successful_test(Test("test_value"))
        self.assertRaises(AttributeError, getattr, obj, "test_attr")

    def test_recordCalls(self):
        from breezy.tests import test_selftest

        calls = self.recordCalls(test_selftest, "_add_numbers")
        self.assertEqual(test_selftest._add_numbers(2, 10), 12)
        self.assertEqual(calls, [((2, 10), {})])


def _add_numbers(a, b):
    return a + b


class _MissingFeature(features.Feature):
    def _probe(self):
        return False


missing_feature = _MissingFeature()


def _get_test(name):
    """Get an instance of a specific example test.

    We protect this in a function so that they don't auto-run in the test
    suite.
    """

    class ExampleTests(tests.TestCase):
        def test_fail(self):
            mutter("this was a failing test")
            self.fail("this test will fail")

        def test_error(self):
            mutter("this test errored")
            raise RuntimeError("gotcha")

        def test_missing_feature(self):
            mutter("missing the feature")
            self.requireFeature(missing_feature)

        def test_skip(self):
            mutter("this test will be skipped")
            raise tests.TestSkipped("reason")

        def test_success(self):
            mutter("this test succeeds")

        def test_xfail(self):
            mutter("test with expected failure")
            self.knownFailure("this_fails")

        def test_unexpected_success(self):
            mutter("test with unexpected success")
            self.expectFailure("should_fail", lambda: None)

    return ExampleTests(name)


class TestTestCaseLogDetails(tests.TestCase):
    def _run_test(self, test_name):
        test = _get_test(test_name)
        result = testtools.TestResult()
        test.run(result)
        return result

    def test_fail_has_log(self):
        result = self._run_test("test_fail")
        self.assertEqual(1, len(result.failures))
        result_content = result.failures[0][1]
        self.assertContainsRe(result_content, "(?m)^(?:Text attachment: )?log(?:$|: )")
        self.assertContainsRe(result_content, "this was a failing test")

    def test_error_has_log(self):
        result = self._run_test("test_error")
        self.assertEqual(1, len(result.errors))
        result_content = result.errors[0][1]
        self.assertContainsRe(result_content, "(?m)^(?:Text attachment: )?log(?:$|: )")
        self.assertContainsRe(result_content, "this test errored")

    def test_skip_has_no_log(self):
        result = self._run_test("test_skip")
        reasons = result.skip_reasons
        self.assertEqual({"reason"}, set(reasons))
        skips = reasons["reason"]
        self.assertEqual(1, len(skips))
        test = skips[0]
        self.assertNotIn("log", test.getDetails())

    def test_missing_feature_has_no_log(self):
        # testtools doesn't know about addNotSupported, so it just gets
        # considered as a skip
        result = self._run_test("test_missing_feature")
        reasons = result.skip_reasons
        self.assertEqual({str(missing_feature)}, set(reasons))
        skips = reasons[str(missing_feature)]
        self.assertEqual(1, len(skips))
        test = skips[0]
        self.assertNotIn("log", test.getDetails())

    def test_xfail_has_no_log(self):
        result = self._run_test("test_xfail")
        self.assertEqual(1, len(result.expectedFailures))
        result_content = result.expectedFailures[0][1]
        self.assertNotContainsRe(
            result_content, "(?m)^(?:Text attachment: )?log(?:$|: )"
        )
        self.assertNotContainsRe(result_content, "test with expected failure")

    def test_unexpected_success_has_log(self):
        result = self._run_test("test_unexpected_success")
        self.assertEqual(1, len(result.unexpectedSuccesses))
        # Inconsistency, unexpectedSuccesses is a list of tests,
        # expectedFailures is a list of reasons?
        test = result.unexpectedSuccesses[0]
        details = test.getDetails()
        self.assertIn("log", details)


class TestTestCloning(tests.TestCase):
    """Tests that test cloning of TestCases (as used by multiply_tests)."""

    def test_cloned_testcase_does_not_share_details(self):
        """A TestCase cloned with clone_test does not share mutable attributes
        such as details or cleanups.
        """

        class Test(tests.TestCase):
            def test_foo(self):
                self.addDetail("foo", Content("text/plain", lambda: "foo"))

        orig_test = Test("test_foo")
        cloned_test = tests.clone_test(orig_test, orig_test.id() + "(cloned)")
        orig_test.run(unittest.TestResult())
        self.assertEqual("foo", orig_test.getDetails()["foo"].iter_bytes())
        self.assertEqual(None, cloned_test.getDetails().get("foo"))

    def test_double_apply_scenario_preserves_first_scenario(self):
        """Applying two levels of scenarios to a test preserves the attributes
        added by both scenarios.
        """

        class Test(tests.TestCase):
            def test_foo(self):
                pass

        test = Test("test_foo")
        scenarios_x = [("x=1", {"x": 1}), ("x=2", {"x": 2})]
        scenarios_y = [("y=1", {"y": 1}), ("y=2", {"y": 2})]
        suite = tests.multiply_tests(test, scenarios_x, unittest.TestSuite())
        suite = tests.multiply_tests(suite, scenarios_y, unittest.TestSuite())
        all_tests = list(tests.iter_suite_tests(suite))
        self.assertLength(4, all_tests)
        all_xys = sorted((t.x, t.y) for t in all_tests)
        self.assertEqual([(1, 1), (1, 2), (2, 1), (2, 2)], all_xys)


# NB: Don't delete this; it's not actually from 0.11!
@deprecated_function(deprecated_in((0, 11, 0)))
def sample_deprecated_function():
    """A deprecated function to test applyDeprecated with."""
    return 2


def sample_undeprecated_function(a_param):
    """A undeprecated function to test applyDeprecated with."""


class ApplyDeprecatedHelper:
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
    """Tests for new test assertions in breezy test suite."""

    def test_assert_isinstance(self):
        self.assertIsInstance(2, int)
        self.assertIsInstance("", str)
        e = self.assertRaises(AssertionError, self.assertIsInstance, None, int)
        self.assertIn(
            str(e),
            [
                "None is an instance of <type 'NoneType'> rather than <type 'int'>",
                "None is an instance of <class 'NoneType'> rather than <class 'int'>",
            ],
        )
        self.assertRaises(AssertionError, self.assertIsInstance, 23.3, int)
        e = self.assertRaises(
            AssertionError, self.assertIsInstance, None, int, "it's just not"
        )
        self.assertEqual(
            str(e),
            "None is an instance of <class 'NoneType'> rather "
            "than <class 'int'>: it's just not",
        )

    def test_assertEndsWith(self):
        self.assertEndsWith("foo", "oo")
        self.assertRaises(AssertionError, self.assertEndsWith, "o", "oo")

    def test_assertEqualDiff(self):
        e = self.assertRaises(AssertionError, self.assertEqualDiff, "", "\n")
        self.assertEqual(
            str(e),
            # Don't blink ! The '+' applies to the second string
            "first string is missing a final newline.\n+ \n",
        )
        e = self.assertRaises(AssertionError, self.assertEqualDiff, "\n", "")
        self.assertEqual(
            str(e),
            # Don't blink ! The '-' applies to the second string
            "second string is missing a final newline.\n- \n",
        )


class TestDeprecations(tests.TestCase):
    def test_applyDeprecated_not_deprecated(self):
        sample_object = ApplyDeprecatedHelper()
        # calling an undeprecated callable raises an assertion
        self.assertRaises(
            AssertionError,
            self.applyDeprecated,
            deprecated_in((0, 11, 0)),
            sample_object.sample_normal_method,
        )
        self.assertRaises(
            AssertionError,
            self.applyDeprecated,
            deprecated_in((0, 11, 0)),
            sample_undeprecated_function,
            "a param value",
        )
        # calling a deprecated callable (function or method) with the wrong
        # expected deprecation fails.
        self.assertRaises(
            AssertionError,
            self.applyDeprecated,
            deprecated_in((0, 10, 0)),
            sample_object.sample_deprecated_method,
            "a param value",
        )
        self.assertRaises(
            AssertionError,
            self.applyDeprecated,
            deprecated_in((0, 10, 0)),
            sample_deprecated_function,
        )
        # calling a deprecated callable (function or method) with the right
        # expected deprecation returns the functions result.
        self.assertEqual(
            "a param value",
            self.applyDeprecated(
                deprecated_in((0, 11, 0)),
                sample_object.sample_deprecated_method,
                "a param value",
            ),
        )
        self.assertEqual(
            2,
            self.applyDeprecated(deprecated_in((0, 11, 0)), sample_deprecated_function),
        )
        # calling a nested deprecation with the wrong deprecation version
        # fails even if a deeper nested function was deprecated with the
        # supplied version.
        self.assertRaises(
            AssertionError,
            self.applyDeprecated,
            deprecated_in((0, 11, 0)),
            sample_object.sample_nested_deprecation,
        )
        # calling a nested deprecation with the right deprecation value
        # returns the calls result.
        self.assertEqual(
            2,
            self.applyDeprecated(
                deprecated_in((0, 10, 0)), sample_object.sample_nested_deprecation
            ),
        )

    def test_callDeprecated(self):
        def testfunc(be_deprecated, result=None):
            if be_deprecated is True:
                symbol_versioning.warn(
                    "i am deprecated", DeprecationWarning, stacklevel=1
                )
            return result

        result = self.callDeprecated(["i am deprecated"], testfunc, True)
        self.assertIs(None, result)
        result = self.callDeprecated([], testfunc, False, "result")
        self.assertEqual("result", result)
        self.callDeprecated(["i am deprecated"], testfunc, be_deprecated=True)
        self.callDeprecated([], testfunc, be_deprecated=False)


class TestWarningTests(tests.TestCase):
    """Tests for calling methods that raise warnings."""

    def test_callCatchWarnings(self):
        def meth(a, b):
            warnings.warn("this is your last warning", stacklevel=1)
            return a + b

        wlist, result = self.callCatchWarnings(meth, 1, 2)
        self.assertEqual(3, result)
        # would like just to compare them, but UserWarning doesn't implement
        # eq well
        (w0,) = wlist
        self.assertIsInstance(w0, UserWarning)
        self.assertEqual("this is your last warning", str(w0))


class TestConvenienceMakers(tests.TestCaseWithTransport):
    """Test for the make_* convenience functions."""

    def test_make_branch_and_tree_with_format(self):
        # we should be able to supply a format to make_branch_and_tree
        self.make_branch_and_tree("a", format=breezy.bzr.bzrdir.BzrDirMetaFormat1())
        self.assertIsInstance(
            breezy.controldir.ControlDir.open("a")._format,
            breezy.bzr.bzrdir.BzrDirMetaFormat1,
        )

    def test_make_branch_and_memory_tree(self):
        # we should be able to get a new branch and a mutable tree from
        # TestCaseWithTransport
        tree = self.make_branch_and_memory_tree("a")
        self.assertIsInstance(tree, breezy.memorytree.MemoryTree)

    def test_make_tree_for_local_vfs_backed_transport(self):
        # make_branch_and_tree has to use local branch and repositories
        # when the vfs transport and local disk are colocated, even if
        # a different transport is in use for url generation.
        self.transport_server = test_server.FakeVFATServer
        self.assertFalse(self.get_url("t1").startswith("file://"))
        tree = self.make_branch_and_tree("t1")
        base = tree.controldir.root_transport.base
        self.assertStartsWith(base, "file://")
        self.assertEqual(
            tree.controldir.root_transport, tree.branch.controldir.root_transport
        )
        self.assertEqual(
            tree.controldir.root_transport,
            tree.branch.repository.controldir.root_transport,
        )


class SelfTestHelper:
    def run_selftest(self, **kwargs):
        """Run selftest returning its output."""
        bio = BytesIO()
        output = TextIOWrapper(bio, "utf-8")
        old_transport = breezy.tests.default_transport
        old_root = tests.TestCaseWithMemoryTransport.TEST_ROOT
        tests.TestCaseWithMemoryTransport.TEST_ROOT = None
        try:
            self.assertEqual(True, tests.selftest(stream=output, **kwargs))
        finally:
            breezy.tests.default_transport = old_transport
            tests.TestCaseWithMemoryTransport.TEST_ROOT = old_root
        output.flush()
        output.detach()
        bio.seek(0)
        return bio


class TestSelftest(tests.TestCase, SelfTestHelper):
    """Tests of breezy.tests.selftest."""

    def test_selftest_benchmark_parameter_invokes_test_suite__benchmark__(self):
        factory_called = []

        def factory():
            factory_called.append(True)
            return TestUtil.TestSuite()

        out = StringIO()
        err = StringIO()
        self.apply_redirected(
            out, err, None, breezy.tests.selftest, test_suite_factory=factory
        )
        self.assertEqual([True], factory_called)

    def factory(self):
        """A test suite factory."""

        class Test(tests.TestCase):
            def id(self):
                return __name__ + ".Test." + self._testMethodName

            def a(self):
                pass

            def b(self):
                pass

            def c(self):
                pass

        return TestUtil.TestSuite([Test("a"), Test("b"), Test("c")])

    def test_list_only(self):
        output = self.run_selftest(test_suite_factory=self.factory, list_only=True)
        self.assertEqual(3, len(output.readlines()))

    def test_list_only_filtered(self):
        output = self.run_selftest(
            test_suite_factory=self.factory, list_only=True, pattern="Test.b"
        )
        self.assertEndsWith(output.getvalue(), b"Test.b\n")
        self.assertLength(1, output.readlines())

    def test_list_only_excludes(self):
        output = self.run_selftest(
            test_suite_factory=self.factory, list_only=True, exclude_pattern="Test.b"
        )
        self.assertNotContainsRe(b"Test.b", output.getvalue())
        self.assertLength(2, output.readlines())

    def test_lsprof_tests(self):
        self.requireFeature(features.lsprof_feature)
        results = []

        class Test:
            def __call__(test, result):  # noqa: N805
                test.run(result)

            def run(test, result):  # noqa: N805
                results.append(result)

            def countTestCases(self):
                return 1

        self.run_selftest(test_suite_factory=Test, lsprof_tests=True)
        self.assertLength(1, results)
        self.assertIsInstance(results.pop(), ExtendedToOriginalDecorator)

    def test_random(self):
        # test randomising by listing a number of tests.
        output_123 = self.run_selftest(
            test_suite_factory=self.factory, list_only=True, random_seed="123"
        )
        output_234 = self.run_selftest(
            test_suite_factory=self.factory, list_only=True, random_seed="234"
        )
        self.assertNotEqual(output_123, output_234)
        # "Randominzing test order..\n\n
        self.assertLength(5, output_123.readlines())
        self.assertLength(5, output_234.readlines())

    def test_random_reuse_is_same_order(self):
        # test randomising by listing a number of tests.
        expected = self.run_selftest(
            test_suite_factory=self.factory, list_only=True, random_seed="123"
        )
        repeated = self.run_selftest(
            test_suite_factory=self.factory, list_only=True, random_seed="123"
        )
        self.assertEqual(expected.getvalue(), repeated.getvalue())

    def test_runner_class(self):
        self.requireFeature(features.subunit)
        from subunit import ProtocolTestCase

        stream = self.run_selftest(
            runner_class=tests.SubUnitBzrRunnerv1, test_suite_factory=self.factory
        )
        test = ProtocolTestCase(stream)
        result = unittest.TestResult()
        test.run(result)
        self.assertEqual(3, result.testsRun)

    def test_starting_with_single_argument(self):
        output = self.run_selftest(
            test_suite_factory=self.factory,
            starting_with=["breezy.tests.test_selftest.Test.a"],
            list_only=True,
        )
        self.assertEqual(b"breezy.tests.test_selftest.Test.a\n", output.getvalue())

    def test_starting_with_multiple_argument(self):
        output = self.run_selftest(
            test_suite_factory=self.factory,
            starting_with=[
                "breezy.tests.test_selftest.Test.a",
                "breezy.tests.test_selftest.Test.b",
            ],
            list_only=True,
        )
        self.assertEqual(
            b"breezy.tests.test_selftest.Test.a\nbreezy.tests.test_selftest.Test.b\n",
            output.getvalue(),
        )

    def check_transport_set(self, transport_server):
        captured_transport = []

        def seen_transport(a_transport):
            captured_transport.append(a_transport)

        class Capture(tests.TestCase):
            def a(self):
                seen_transport(breezy.tests.default_transport)

        def factory():
            return TestUtil.TestSuite([Capture("a")])

        self.run_selftest(transport=transport_server, test_suite_factory=factory)
        self.assertEqual(transport_server, captured_transport[0])

    def test_transport_sftp(self):
        self.requireFeature(features.paramiko)
        from breezy.tests import stub_sftp

        self.check_transport_set(stub_sftp.SFTPAbsoluteServer)

    def test_transport_memory(self):
        self.check_transport_set(memory.MemoryServer)


class TestSelftestWithIdList(tests.TestCaseInTempDir, SelfTestHelper):
    # Does IO: reads test.list

    def test_load_list(self):
        # Provide a list with one test - this test.
        test_id_line = b"%s\n" % self.id().encode("ascii")
        self.build_tree_contents([("test.list", test_id_line)])
        # And generate a list of the tests in  the suite.
        stream = self.run_selftest(load_list="test.list", list_only=True)
        self.assertEqual(test_id_line, stream.getvalue())

    def test_load_unknown(self):
        # Provide a list with one test - this test.
        # And generate a list of the tests in  the suite.
        self.assertRaises(
            transport.NoSuchFile,
            self.run_selftest,
            load_list="missing file name",
            list_only=True,
        )


class TestSubunitLogDetails(tests.TestCase, SelfTestHelper):
    _test_needs_features = [features.subunit]

    def run_subunit_stream(self, test_name):
        from subunit import ProtocolTestCase

        def factory():
            return TestUtil.TestSuite([_get_test(test_name)])

        stream = self.run_selftest(
            runner_class=tests.SubUnitBzrRunnerv1, test_suite_factory=factory
        )
        test = ProtocolTestCase(stream)
        result = testtools.TestResult()
        test.run(result)
        content = stream.getvalue()
        return content, result

    def test_fail_has_log(self):
        content, result = self.run_subunit_stream("test_fail")
        self.assertEqual(1, len(result.failures))
        self.assertContainsRe(content, b"(?m)^log$")
        self.assertContainsRe(content, b"this test will fail")

    def test_error_has_log(self):
        content, result = self.run_subunit_stream("test_error")
        self.assertContainsRe(content, b"(?m)^log$")
        self.assertContainsRe(content, b"this test errored")

    def test_skip_has_no_log(self):
        content, result = self.run_subunit_stream("test_skip")
        self.assertNotContainsRe(content, b"(?m)^log$")
        self.assertNotContainsRe(content, b"this test will be skipped")
        reasons = result.skip_reasons
        self.assertEqual({"reason"}, set(reasons))
        skips = reasons["reason"]
        self.assertEqual(1, len(skips))
        # test = skips[0]
        # RemotedTestCase doesn't preserve the "details"
        # self.assertFalse('log' in test.getDetails())

    def test_missing_feature_has_no_log(self):
        content, result = self.run_subunit_stream("test_missing_feature")
        self.assertNotContainsRe(content, b"(?m)^log$")
        self.assertNotContainsRe(content, b"missing the feature")
        reasons = result.skip_reasons
        self.assertEqual({"_MissingFeature\n"}, set(reasons))
        skips = reasons["_MissingFeature\n"]
        self.assertEqual(1, len(skips))
        # test = skips[0]
        # RemotedTestCase doesn't preserve the "details"
        # self.assertFalse('log' in test.getDetails())

    def test_xfail_has_no_log(self):
        content, result = self.run_subunit_stream("test_xfail")
        self.assertNotContainsRe(content, b"(?m)^log$")
        self.assertNotContainsRe(content, b"test with expected failure")
        self.assertEqual(1, len(result.expectedFailures))
        result_content = result.expectedFailures[0][1]
        self.assertNotContainsRe(
            result_content, "(?m)^(?:Text attachment: )?log(?:$|: )"
        )
        self.assertNotContainsRe(result_content, "test with expected failure")

    def test_unexpected_success_has_log(self):
        content, result = self.run_subunit_stream("test_unexpected_success")
        self.assertContainsRe(content, b"(?m)^log$")
        self.assertContainsRe(content, b"test with unexpected success")
        self.assertEqual(1, len(result.unexpectedSuccesses))
        # test = result.unexpectedSuccesses[0]
        # RemotedTestCase doesn't preserve the "details"
        # self.assertTrue('log' in test.getDetails())

    def test_success_has_no_log(self):
        content, result = self.run_subunit_stream("test_success")
        self.assertEqual(1, result.testsRun)
        self.assertNotContainsRe(content, b"(?m)^log$")
        self.assertNotContainsRe(content, b"this test succeeds")


class TestRunBzr(tests.TestCase):
    result = 0
    out = ""
    err = ""

    def _run_bzr_core(
        self,
        argv,
        encoding=None,
        stdin=None,
        stdout=None,
        stderr=None,
        working_dir=None,
    ):
        """Override _run_bzr_core to test how it is invoked by run_bzr.

        Attempts to run bzr from inside this class don't actually run it.

        We test how run_bzr actually invokes bzr in another location.  Here we
        only need to test that it passes the right parameters to run_bzr.
        """
        self.argv = list(argv)
        self.encoding = encoding
        self.stdin = stdin
        self.working_dir = working_dir
        stdout.write(self.out)
        stderr.write(self.err)
        return self.result

    def test_run_bzr_error(self):
        self.out = "It sure does!\n"
        self.result = 34
        out, err = self.run_bzr_error(["^$"], ["rocks"], retcode=34)
        self.assertEqual(["rocks"], self.argv)
        self.assertEqual("It sure does!\n", out)
        self.assertEqual(out, self.out)
        self.assertEqual("", err)
        self.assertEqual(err, self.err)

    def test_run_bzr_error_regexes(self):
        self.out = ""
        self.err = "bzr: ERROR: foobarbaz is not versioned"
        self.result = 3
        out, err = self.run_bzr_error(
            ["bzr: ERROR: foobarbaz is not versioned"], ["file-id", "foobarbaz"]
        )

    def test_encoding(self):
        """Test that run_bzr passes encoding to _run_bzr_core."""
        self.run_bzr("foo bar")
        self.assertEqual(osutils.get_user_encoding(), self.encoding)
        self.assertEqual(["foo", "bar"], self.argv)

        self.run_bzr("foo bar", encoding="baz")
        self.assertEqual("baz", self.encoding)
        self.assertEqual(["foo", "bar"], self.argv)

    def test_stdin(self):
        # test that the stdin keyword to run_bzr is passed through to
        # _run_bzr_core as-is. We do this by overriding
        # _run_bzr_core in this class, and then calling run_bzr,
        # which is a convenience function for _run_bzr_core, so
        # should invoke it.
        self.run_bzr("foo bar", stdin="gam")
        self.assertEqual("gam", self.stdin)
        self.assertEqual(["foo", "bar"], self.argv)

        self.run_bzr("foo bar", stdin="zippy")
        self.assertEqual("zippy", self.stdin)
        self.assertEqual(["foo", "bar"], self.argv)

    def test_working_dir(self):
        """Test that run_bzr passes working_dir to _run_bzr_core."""
        self.run_bzr("foo bar")
        self.assertEqual(None, self.working_dir)
        self.assertEqual(["foo", "bar"], self.argv)

        self.run_bzr("foo bar", working_dir="baz")
        self.assertEqual("baz", self.working_dir)
        self.assertEqual(["foo", "bar"], self.argv)

    def test_reject_extra_keyword_arguments(self):
        self.assertRaises(
            TypeError, self.run_bzr, "foo bar", error_regex=["error message"]
        )


class TestRunBzrCaptured(tests.TestCaseWithTransport):
    # Does IO when testing the working_dir parameter.

    def apply_redirected(
        self, stdin=None, stdout=None, stderr=None, a_callable=None, *args, **kwargs
    ):
        self.stdin = stdin
        self.factory_stdin = getattr(breezy.ui.ui_factory, "stdin", None)
        self.factory = breezy.ui.ui_factory
        self.working_dir = osutils.getcwd()
        stdout.write("foo\n")
        stderr.write("bar\n")
        return 0

    def test_stdin(self):
        # test that the stdin keyword to _run_bzr_core is passed through to
        # apply_redirected as a StringIO. We do this by overriding
        # apply_redirected in this class, and then calling _run_bzr_core,
        # which calls apply_redirected.
        self.run_bzr(["foo", "bar"], stdin="gam")
        self.assertEqual("gam", self.stdin.read())
        self.assertIs(self.stdin, self.factory_stdin)
        self.run_bzr(["foo", "bar"], stdin="zippy")
        self.assertEqual("zippy", self.stdin.read())
        self.assertIs(self.stdin, self.factory_stdin)

    def test_ui_factory(self):
        # each invocation of self.run_bzr should get its
        # own UI factory, which is an instance of TestUIFactory,
        # with stdin, stdout and stderr attached to the stdin,
        # stdout and stderr of the invoked run_bzr
        current_factory = breezy.ui.ui_factory
        self.run_bzr(["foo"])
        self.assertIsNot(current_factory, self.factory)
        self.assertNotEqual(sys.stdout, self.factory.stdout)
        self.assertNotEqual(sys.stderr, self.factory.stderr)
        self.assertEqual("foo\n", self.factory.stdout.getvalue())
        self.assertEqual("bar\n", self.factory.stderr.getvalue())
        self.assertIsInstance(self.factory, tests.TestUIFactory)

    def test_working_dir(self):
        self.build_tree(["one/", "two/"])
        cwd = osutils.getcwd()

        # Default is to work in the current directory
        self.run_bzr(["foo", "bar"])
        self.assertEqual(cwd, self.working_dir)

        self.run_bzr(["foo", "bar"], working_dir=None)
        self.assertEqual(cwd, self.working_dir)

        # The function should be run in the alternative directory
        # but afterwards the current working dir shouldn't be changed
        self.run_bzr(["foo", "bar"], working_dir="one")
        self.assertNotEqual(cwd, self.working_dir)
        self.assertEndsWith(self.working_dir, "one")
        self.assertEqual(cwd, osutils.getcwd())

        self.run_bzr(["foo", "bar"], working_dir="two")
        self.assertNotEqual(cwd, self.working_dir)
        self.assertEndsWith(self.working_dir, "two")
        self.assertEqual(cwd, osutils.getcwd())


class StubProcess:
    """A stub process for testing run_brz_subprocess."""

    def __init__(self, out="", err="", retcode=0):
        self.out = out
        self.err = err
        self.returncode = retcode

    def communicate(self):
        return self.out, self.err


class TestWithFakedStartBzrSubprocess(tests.TestCaseWithTransport):
    """Base class for tests testing how we might run bzr."""

    def setUp(self):
        super().setUp()
        self.subprocess_calls = []

    def start_brz_subprocess(
        self,
        process_args,
        env_changes=None,
        skip_if_plan_to_signal=False,
        working_dir=None,
        allow_plugins=False,
    ):
        """Capture what run_brz_subprocess tries to do."""
        self.subprocess_calls.append(
            {
                "process_args": process_args,
                "env_changes": env_changes,
                "skip_if_plan_to_signal": skip_if_plan_to_signal,
                "working_dir": working_dir,
                "allow_plugins": allow_plugins,
            }
        )
        return self.next_subprocess


class TestRunBzrSubprocess(TestWithFakedStartBzrSubprocess):
    def assertRunBzrSubprocess(self, expected_args, process, *args, **kwargs):
        """Run run_brz_subprocess with args and kwargs using a stubbed process.

        Inside TestRunBzrSubprocessCommands we use a stub start_brz_subprocess
        that will return static results. This assertion method populates those
        results and also checks the arguments run_brz_subprocess generates.
        """
        self.next_subprocess = process
        try:
            result = self.run_brz_subprocess(*args, **kwargs)
        except BaseException:
            self.next_subprocess = None
            for key, expected in expected_args.items():
                self.assertEqual(expected, self.subprocess_calls[-1][key])
            raise
        else:
            self.next_subprocess = None
            for key, expected in expected_args.items():
                self.assertEqual(expected, self.subprocess_calls[-1][key])
            return result

    def test_run_brz_subprocess(self):
        """The run_bzr_helper_external command behaves nicely."""
        self.assertRunBzrSubprocess(
            {"process_args": ["--version"]}, StubProcess(), "--version"
        )
        self.assertRunBzrSubprocess(
            {"process_args": ["--version"]}, StubProcess(), ["--version"]
        )
        # retcode=None disables retcode checking
        result = self.assertRunBzrSubprocess(
            {}, StubProcess(retcode=3), "--version", retcode=None
        )
        result = self.assertRunBzrSubprocess(
            {}, StubProcess(out="is free software"), "--version"
        )
        self.assertContainsRe(result[0], "is free software")
        # Running a subcommand that is missing errors
        self.assertRaises(
            AssertionError,
            self.assertRunBzrSubprocess,
            {"process_args": ["--versionn"]},
            StubProcess(retcode=3),
            "--versionn",
        )
        # Unless it is told to expect the error from the subprocess
        result = self.assertRunBzrSubprocess(
            {}, StubProcess(retcode=3), "--versionn", retcode=3
        )
        # Or to ignore retcode checking
        result = self.assertRunBzrSubprocess(
            {},
            StubProcess(err="unknown command", retcode=3),
            "--versionn",
            retcode=None,
        )
        self.assertContainsRe(result[1], "unknown command")

    def test_env_change_passes_through(self):
        self.assertRunBzrSubprocess(
            {"env_changes": {"new": "value", "changed": "newvalue", "deleted": None}},
            StubProcess(),
            "",
            env_changes={"new": "value", "changed": "newvalue", "deleted": None},
        )

    def test_no_working_dir_passed_as_None(self):
        self.assertRunBzrSubprocess({"working_dir": None}, StubProcess(), "")

    def test_no_working_dir_passed_through(self):
        self.assertRunBzrSubprocess(
            {"working_dir": "dir"}, StubProcess(), "", working_dir="dir"
        )

    def test_run_brz_subprocess_no_plugins(self):
        self.assertRunBzrSubprocess({"allow_plugins": False}, StubProcess(), "")

    def test_allow_plugins(self):
        self.assertRunBzrSubprocess(
            {"allow_plugins": True}, StubProcess(), "", allow_plugins=True
        )


class TestFinishBzrSubprocess(TestWithFakedStartBzrSubprocess):
    def test_finish_brz_subprocess_with_error(self):
        """finish_brz_subprocess allows specification of the desired exit code."""
        process = StubProcess(err="unknown command", retcode=3)
        result = self.finish_brz_subprocess(process, retcode=3)
        self.assertEqual("", result[0])
        self.assertContainsRe(result[1], "unknown command")

    def test_finish_brz_subprocess_ignoring_retcode(self):
        """finish_brz_subprocess allows the exit code to be ignored."""
        process = StubProcess(err="unknown command", retcode=3)
        result = self.finish_brz_subprocess(process, retcode=None)
        self.assertEqual("", result[0])
        self.assertContainsRe(result[1], "unknown command")

    def test_finish_subprocess_with_unexpected_retcode(self):
        """finish_brz_subprocess raises self.failureException if the retcode is
        not the expected one.
        """
        process = StubProcess(err="unknown command", retcode=3)
        self.assertRaises(self.failureException, self.finish_brz_subprocess, process)


class _DontSpawnProcess(Exception):
    """A simple exception which just allows us to skip unnecessary steps."""


class TestStartBzrSubProcess(tests.TestCase):
    """Stub test start_brz_subprocess."""

    def _subprocess_log_cleanup(self):
        """Inhibits the base version as we don't produce a log file."""

    def _popen(self, *args, **kwargs):
        """Override the base version to record the command that is run.

        From there we can ensure it is correct without spawning a real process.
        """
        self.check_popen_state()
        self._popen_args = args
        self._popen_kwargs = kwargs
        raise _DontSpawnProcess()

    def check_popen_state(self):
        """Replace to make assertions when popen is called."""

    def test_run_brz_subprocess_no_plugins(self):
        self.assertRaises(_DontSpawnProcess, self.start_brz_subprocess, [])
        command = self._popen_args[0]
        if self.get_brz_path().endswith("__main__.py"):
            self.assertEqual(sys.executable, command[0])
            self.assertEqual("-m", command[1])
            self.assertEqual("breezy", command[2])
            rest = command[3:]
        else:
            self.assertEqual(self.get_brz_path(), command[0])
            rest = command[1:]
        self.assertEqual(["--no-plugins"], rest)

    def test_allow_plugins(self):
        self.assertRaises(
            _DontSpawnProcess, self.start_brz_subprocess, [], allow_plugins=True
        )
        command = self._popen_args[0]
        if self.get_brz_path().endswith("__main__.py"):
            rest = command[3:]
        else:
            rest = command[1:]
        self.assertEqual([], rest)

    def test_set_env(self):
        self.assertNotIn("EXISTANT_ENV_VAR", os.environ)
        # set in the child

        def check_environment():
            self.assertEqual("set variable", os.environ["EXISTANT_ENV_VAR"])

        self.check_popen_state = check_environment
        self.assertRaises(
            _DontSpawnProcess,
            self.start_brz_subprocess,
            [],
            env_changes={"EXISTANT_ENV_VAR": "set variable"},
        )
        # not set in theparent
        self.assertNotIn("EXISTANT_ENV_VAR", os.environ)

    def test_run_brz_subprocess_env_del(self):
        """run_brz_subprocess can remove environment variables too."""
        self.assertNotIn("EXISTANT_ENV_VAR", os.environ)

        def check_environment():
            self.assertNotIn("EXISTANT_ENV_VAR", os.environ)

        os.environ["EXISTANT_ENV_VAR"] = "set variable"
        self.check_popen_state = check_environment
        self.assertRaises(
            _DontSpawnProcess,
            self.start_brz_subprocess,
            [],
            env_changes={"EXISTANT_ENV_VAR": None},
        )
        # Still set in parent
        self.assertEqual("set variable", os.environ["EXISTANT_ENV_VAR"])
        del os.environ["EXISTANT_ENV_VAR"]

    def test_env_del_missing(self):
        self.assertNotIn("NON_EXISTANT_ENV_VAR", os.environ)

        def check_environment():
            self.assertNotIn("NON_EXISTANT_ENV_VAR", os.environ)

        self.check_popen_state = check_environment
        self.assertRaises(
            _DontSpawnProcess,
            self.start_brz_subprocess,
            [],
            env_changes={"NON_EXISTANT_ENV_VAR": None},
        )

    def test_working_dir(self):
        """Test that we can specify the working dir for the child."""
        chdirs = []

        def chdir(path):
            chdirs.append(path)

        self.overrideAttr(os, "chdir", chdir)

        def getcwd():
            return "current"

        self.overrideAttr(osutils, "getcwd", getcwd)
        self.assertRaises(
            _DontSpawnProcess, self.start_brz_subprocess, [], working_dir="foo"
        )
        self.assertEqual(["foo", "current"], chdirs)

    def test_get_brz_path_with_cwd_breezy(self):
        self.get_source_path = lambda: ""
        self.overrideAttr(os.path, "isfile", lambda path: True)
        self.assertEqual(self.get_brz_path(), "brz")


class TestActuallyStartBzrSubprocess(tests.TestCaseWithTransport):
    """Tests that really need to do things with an external bzr."""

    def test_start_and_stop_bzr_subprocess_send_signal(self):
        """finish_brz_subprocess raises self.failureException if the retcode is
        not the expected one.
        """
        self.disable_missing_extensions_warning()
        process = self.start_brz_subprocess(
            ["wait-until-signalled"], skip_if_plan_to_signal=True
        )
        self.assertEqual(b"running\n", process.stdout.readline())
        result = self.finish_brz_subprocess(
            process, send_signal=signal.SIGINT, retcode=3
        )
        self.assertEqual(b"", result[0])
        self.assertEqual(b"brz: interrupted\n", result[1])


class TestSelftestFiltering(tests.TestCase):
    def setUp(self):
        super().setUp()
        self.suite = TestUtil.TestSuite()
        self.loader = TestUtil.TestLoader()
        self.suite.addTest(
            self.loader.loadTestsFromModule(sys.modules["breezy.tests.test_selftest"])
        )
        self.all_names = _test_ids(self.suite)

    def test_condition_id_re(self):
        test_name = (
            "breezy.tests.test_selftest.TestSelftestFiltering.test_condition_id_re"
        )
        filtered_suite = tests.filter_suite_by_condition(
            self.suite, tests.condition_id_re("test_condition_id_re")
        )
        self.assertEqual([test_name], _test_ids(filtered_suite))

    def test_condition_id_in_list(self):
        test_names = [
            "breezy.tests.test_selftest.TestSelftestFiltering.test_condition_id_in_list"
        ]
        id_list = tests.TestIdList(test_names)
        filtered_suite = tests.filter_suite_by_condition(
            self.suite, tests.condition_id_in_list(id_list)
        )
        my_pattern = "TestSelftestFiltering.*test_condition_id_in_list"
        re_filtered = tests.filter_suite_by_re(self.suite, my_pattern)
        self.assertEqual(_test_ids(re_filtered), _test_ids(filtered_suite))

    def test_condition_id_startswith(self):
        klass = "breezy.tests.test_selftest.TestSelftestFiltering."
        start1 = klass + "test_condition_id_starts"
        start2 = klass + "test_condition_id_in"
        test_names = [
            klass + "test_condition_id_in_list",
            klass + "test_condition_id_startswith",
        ]
        filtered_suite = tests.filter_suite_by_condition(
            self.suite, tests.condition_id_startswith([start1, start2])
        )
        self.assertEqual(test_names, _test_ids(filtered_suite))

    def test_condition_isinstance(self):
        filtered_suite = tests.filter_suite_by_condition(
            self.suite, tests.condition_isinstance(self.__class__)
        )
        class_pattern = "breezy.tests.test_selftest.TestSelftestFiltering."
        re_filtered = tests.filter_suite_by_re(self.suite, class_pattern)
        self.assertEqual(_test_ids(re_filtered), _test_ids(filtered_suite))

    def test_exclude_tests_by_condition(self):
        excluded_name = (
            "breezy.tests.test_selftest.TestSelftestFiltering."
            "test_exclude_tests_by_condition"
        )
        filtered_suite = tests.exclude_tests_by_condition(
            self.suite, lambda x: x.id() == excluded_name
        )
        self.assertEqual(len(self.all_names) - 1, filtered_suite.countTestCases())
        self.assertNotIn(excluded_name, _test_ids(filtered_suite))
        remaining_names = list(self.all_names)
        remaining_names.remove(excluded_name)
        self.assertEqual(remaining_names, _test_ids(filtered_suite))

    def test_exclude_tests_by_re(self):
        self.all_names = _test_ids(self.suite)
        filtered_suite = tests.exclude_tests_by_re(self.suite, "exclude_tests_by_re")
        excluded_name = (
            "breezy.tests.test_selftest.TestSelftestFiltering.test_exclude_tests_by_re"
        )
        self.assertEqual(len(self.all_names) - 1, filtered_suite.countTestCases())
        self.assertNotIn(excluded_name, _test_ids(filtered_suite))
        remaining_names = list(self.all_names)
        remaining_names.remove(excluded_name)
        self.assertEqual(remaining_names, _test_ids(filtered_suite))

    def test_filter_suite_by_condition(self):
        test_name = (
            "breezy.tests.test_selftest.TestSelftestFiltering."
            "test_filter_suite_by_condition"
        )
        filtered_suite = tests.filter_suite_by_condition(
            self.suite, lambda x: x.id() == test_name
        )
        self.assertEqual([test_name], _test_ids(filtered_suite))

    def test_filter_suite_by_re(self):
        filtered_suite = tests.filter_suite_by_re(self.suite, "test_filter_suite_by_r")
        filtered_names = _test_ids(filtered_suite)
        self.assertEqual(
            filtered_names,
            [
                "breezy.tests.test_selftest."
                "TestSelftestFiltering.test_filter_suite_by_re"
            ],
        )

    def test_filter_suite_by_id_list(self):
        test_list = [
            "breezy.tests.test_selftest."
            "TestSelftestFiltering.test_filter_suite_by_id_list"
        ]
        filtered_suite = tests.filter_suite_by_id_list(
            self.suite, tests.TestIdList(test_list)
        )
        filtered_names = _test_ids(filtered_suite)
        self.assertEqual(
            filtered_names,
            [
                "breezy.tests.test_selftest."
                "TestSelftestFiltering.test_filter_suite_by_id_list"
            ],
        )

    def test_filter_suite_by_id_startswith(self):
        # By design this test may fail if another test is added whose name also
        # begins with one of the start value used.
        klass = "breezy.tests.test_selftest.TestSelftestFiltering."
        start1 = klass + "test_filter_suite_by_id_starts"
        start2 = klass + "test_filter_suite_by_id_li"
        test_list = [
            klass + "test_filter_suite_by_id_list",
            klass + "test_filter_suite_by_id_startswith",
        ]
        filtered_suite = tests.filter_suite_by_id_startswith(
            self.suite, [start1, start2]
        )
        self.assertEqual(
            test_list,
            _test_ids(filtered_suite),
        )

    def test_preserve_input(self):
        # NB: Surely this is something in the stdlib to do this?
        self.assertIs(self.suite, tests.preserve_input(self.suite))
        self.assertEqual("@#$", tests.preserve_input("@#$"))

    def test_randomize_suite(self):
        randomized_suite = tests.randomize_suite(self.suite)
        # randomizing should not add or remove test names.
        self.assertEqual(set(_test_ids(self.suite)), set(_test_ids(randomized_suite)))
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
        condition = tests.condition_id_re("test_filter_suite_by_r")
        split_suite = tests.split_suite_by_condition(self.suite, condition)
        filtered_name = (
            "breezy.tests.test_selftest.TestSelftestFiltering.test_filter_suite_by_re"
        )
        self.assertEqual([filtered_name], _test_ids(split_suite[0]))
        self.assertNotIn(filtered_name, _test_ids(split_suite[1]))
        remaining_names = list(self.all_names)
        remaining_names.remove(filtered_name)
        self.assertEqual(remaining_names, _test_ids(split_suite[1]))

    def test_split_suit_by_re(self):
        self.all_names = _test_ids(self.suite)
        split_suite = tests.split_suite_by_re(self.suite, "test_filter_suite_by_r")
        filtered_name = (
            "breezy.tests.test_selftest.TestSelftestFiltering.test_filter_suite_by_re"
        )
        self.assertEqual([filtered_name], _test_ids(split_suite[0]))
        self.assertNotIn(filtered_name, _test_ids(split_suite[1]))
        remaining_names = list(self.all_names)
        remaining_names.remove(filtered_name)
        self.assertEqual(remaining_names, _test_ids(split_suite[1]))


class TestCheckTreeShape(tests.TestCaseWithTransport):
    def test_check_tree_shape(self):
        files = ["a", "b/", "b/c"]
        tree = self.make_branch_and_tree(".")
        self.build_tree(files)
        tree.add(files)
        tree.lock_read()
        try:
            self.check_tree_shape(tree, files)
        finally:
            tree.unlock()


class TestBlackboxSupport(tests.TestCase):
    """Tests for testsuite blackbox features."""

    def test_run_bzr_failure_not_caught(self):
        # When we run bzr in blackbox mode, we want any unexpected errors to
        # propagate up to the test suite so that it can show the error in the
        # usual way, and we won't get a double traceback.
        e = self.assertRaises(AssertionError, self.run_bzr, ["assert-fail"])
        # make sure we got the real thing, not an error from somewhere else in
        # the test framework
        self.assertEqual("always fails", str(e))
        # check that there's no traceback in the test log
        self.assertNotContainsRe(self.get_log(), r"Traceback")

    def test_run_bzr_user_error_caught(self):
        # Running bzr in blackbox mode, normal/expected/user errors should be
        # caught in the regular way and turned into an error message plus exit
        # code.
        transport_server = memory.MemoryServer()
        transport_server.start_server()
        self.addCleanup(transport_server.stop_server)
        url = transport_server.get_url()
        self.permit_url(url)
        out, err = self.run_bzr(["log", f"{url}/nonexistantpath"], retcode=3)
        self.assertEqual(out, "")
        self.assertContainsRe(err, 'brz: ERROR: Not a branch: ".*nonexistantpath/".\n')


class TestTestLoader(tests.TestCase):
    """Tests for the test loader."""

    def _get_loader_and_module(self):
        """Gets a TestLoader and a module with one test in it."""
        loader = TestUtil.TestLoader()
        module = {}

        class Stub(tests.TestCase):
            def test_foo(self):
                pass

        class MyModule:
            pass

        MyModule.a_class = Stub
        module = MyModule()
        module.__name__ = "fake_module"
        return loader, module

    def test_module_no_load_tests_attribute_loads_classes(self):
        loader, module = self._get_loader_and_module()
        self.assertEqual(1, loader.loadTestsFromModule(module).countTestCases())

    def test_module_load_tests_attribute_gets_called(self):
        loader, module = self._get_loader_and_module()

        def load_tests(loader, standard_tests, pattern):
            result = loader.suiteClass()
            for test in tests.iter_suite_tests(standard_tests):
                result.addTests([test, test])
            return result

        # add a load_tests() method which multiplies the tests from the module.
        module.__class__.load_tests = staticmethod(load_tests)
        self.assertEqual(
            2 * [str(module.a_class("test_foo"))],
            list(map(str, loader.loadTestsFromModule(module))),
        )

    def test_load_tests_from_module_name_smoke_test(self):
        loader = TestUtil.TestLoader()
        suite = loader.loadTestsFromModuleName("breezy.tests.test_sampler")
        self.assertEqual(
            ["breezy.tests.test_sampler.DemoTest.test_nothing"], _test_ids(suite)
        )

    def test_load_tests_from_module_name_with_bogus_module_name(self):
        loader = TestUtil.TestLoader()
        self.assertRaises(ImportError, loader.loadTestsFromModuleName, "bogus")


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
            t = Stub("test_foo")
            t.id = _create_test_id(id)
            suite.addTest(t)
        return suite

    def _test_ids(self, test_suite):
        """Get the ids for the tests in a test suite."""
        return [t.id() for t in tests.iter_suite_tests(test_suite)]

    def test_empty_list(self):
        id_list = self._create_id_list([])
        self.assertEqual({}, id_list.tests)
        self.assertEqual({}, id_list.modules)

    def test_valid_list(self):
        id_list = self._create_id_list(
            [
                "mod1.cl1.meth1",
                "mod1.cl1.meth2",
                "mod1.func1",
                "mod1.cl2.meth2",
                "mod1.submod1",
                "mod1.submod2.cl1.meth1",
                "mod1.submod2.cl2.meth2",
            ]
        )
        self.assertTrue(id_list.refers_to("mod1"))
        self.assertTrue(id_list.refers_to("mod1.submod1"))
        self.assertTrue(id_list.refers_to("mod1.submod2"))
        self.assertTrue(id_list.includes("mod1.cl1.meth1"))
        self.assertTrue(id_list.includes("mod1.submod1"))
        self.assertTrue(id_list.includes("mod1.func1"))

    def test_bad_chars_in_params(self):
        id_list = self._create_id_list(["mod1.cl1.meth1(xx.yy)"])
        self.assertTrue(id_list.refers_to("mod1"))
        self.assertTrue(id_list.includes("mod1.cl1.meth1(xx.yy)"))

    def test_module_used(self):
        id_list = self._create_id_list(["mod.class.meth"])
        self.assertTrue(id_list.refers_to("mod"))
        self.assertTrue(id_list.refers_to("mod.class"))
        self.assertTrue(id_list.refers_to("mod.class.meth"))

    def test_test_suite_matches_id_list_with_unknown(self):
        loader = TestUtil.TestLoader()
        suite = loader.loadTestsFromModuleName("breezy.tests.test_sampler")
        test_list = ["breezy.tests.test_sampler.DemoTest.test_nothing", "bogus"]
        not_found, duplicates = tests.suite_matches_id_list(suite, test_list)
        self.assertEqual(["bogus"], not_found)
        self.assertEqual([], duplicates)

    def test_suite_matches_id_list_with_duplicates(self):
        loader = TestUtil.TestLoader()
        suite = loader.loadTestsFromModuleName("breezy.tests.test_sampler")
        dupes = loader.suiteClass()
        for test in tests.iter_suite_tests(suite):
            dupes.addTest(test)
            dupes.addTest(test)  # Add it again

        test_list = [
            "breezy.tests.test_sampler.DemoTest.test_nothing",
        ]
        not_found, duplicates = tests.suite_matches_id_list(dupes, test_list)
        self.assertEqual([], not_found)
        self.assertEqual(
            ["breezy.tests.test_sampler.DemoTest.test_nothing"], duplicates
        )


class TestTestSuite(tests.TestCase):
    def test__test_suite_testmod_names(self):
        # Test that a plausible list of test module names are returned
        # by _test_suite_testmod_names.
        test_list = tests._test_suite_testmod_names()
        self.assertSubset(
            [
                "breezy.tests.blackbox",
                "breezy.tests.per_transport",
                "breezy.tests.test_selftest",
            ],
            test_list,
        )

    def test__test_suite_modules_to_doctest(self):
        # Test that a plausible list of modules to doctest is returned
        # by _test_suite_modules_to_doctest.
        test_list = tests._test_suite_modules_to_doctest()
        if __doc__ is None:
            # When docstrings are stripped, there are no modules to doctest
            self.assertEqual([], test_list)
            return
        self.assertSubset(
            [
                "breezy.symbol_versioning",
            ],
            test_list,
        )

    def test_test_suite(self):
        # test_suite() loads the entire test suite to operate. To avoid this
        # overhead, and yet still be confident that things are happening,
        # we temporarily replace two functions used by test_suite with
        # test doubles that supply a few sample tests to load, and check they
        # are loaded.
        calls = []

        def testmod_names():
            calls.append("testmod_names")
            return [
                "breezy.tests.blackbox.test_branch",
                "breezy.tests.per_transport",
                "breezy.tests.test_selftest",
            ]

        self.overrideAttr(tests, "_test_suite_testmod_names", testmod_names)

        def doctests():
            calls.append("modules_to_doctest")
            if __doc__ is None:
                return []
            return ["breezy.symbol_versioning"]

        self.overrideAttr(tests, "_test_suite_modules_to_doctest", doctests)
        expected_test_list = [
            # testmod_names
            "breezy.tests.blackbox.test_branch.TestBranch.test_branch",
            (
                "breezy.tests.per_transport.TransportTests"
                ".test_abspath(LocalTransport,LocalURLServer)"
            ),
            "breezy.tests.test_selftest.TestTestSuite.test_test_suite",
            # plugins can't be tested that way since selftest may be run with
            # --no-plugins
        ]
        suite = tests.test_suite()
        self.assertEqual({"testmod_names", "modules_to_doctest"}, set(calls))
        self.assertSubset(expected_test_list, _test_ids(suite))

    def test_test_suite_list_and_start(self):
        # We cannot test this at the same time as the main load, because we
        # want to know that starting_with == None works. So a second load is
        # incurred - note that the starting_with parameter causes a partial
        # load rather than a full load so this test should be pretty quick.
        test_list = ["breezy.tests.test_selftest.TestTestSuite.test_test_suite"]
        suite = tests.test_suite(
            test_list, ["breezy.tests.test_selftest.TestTestSuite"]
        )
        # test_test_suite_list_and_start is not included
        self.assertEqual(test_list, _test_ids(suite))


class TestLoadTestIdList(tests.TestCaseInTempDir):
    def _create_test_list_file(self, file_name, content):
        fl = open(file_name, "w")
        fl.write(content)
        fl.close()

    def test_load_unknown(self):
        self.assertRaises(
            transport.NoSuchFile, tests.load_test_id_list, "i_do_not_exist"
        )

    def test_load_test_list(self):
        test_list_fname = "test.list"
        self._create_test_list_file(test_list_fname, "mod1.cl1.meth1\nmod2.cl2.meth2\n")
        tlist = tests.load_test_id_list(test_list_fname)
        self.assertEqual(2, len(tlist))
        self.assertEqual("mod1.cl1.meth1", tlist[0])
        self.assertEqual("mod2.cl2.meth2", tlist[1])

    def test_load_dirty_file(self):
        test_list_fname = "test.list"
        self._create_test_list_file(
            test_list_fname, "  mod1.cl1.meth1\n\nmod2.cl2.meth2  \nbar baz\n"
        )
        tlist = tests.load_test_id_list(test_list_fname)
        self.assertEqual(4, len(tlist))
        self.assertEqual("mod1.cl1.meth1", tlist[0])
        self.assertEqual("", tlist[1])
        self.assertEqual("mod2.cl2.meth2", tlist[2])
        self.assertEqual("bar baz", tlist[3])


class TestFilteredByModuleTestLoader(tests.TestCase):
    def _create_loader(self, test_list):
        id_filter = tests.TestIdList(test_list)
        loader = TestUtil.FilteredByModuleTestLoader(id_filter.refers_to)
        return loader

    def test_load_tests(self):
        test_list = ["breezy.tests.test_sampler.DemoTest.test_nothing"]
        loader = self._create_loader(test_list)
        suite = loader.loadTestsFromModuleName("breezy.tests.test_sampler")
        self.assertEqual(test_list, _test_ids(suite))

    def test_exclude_tests(self):
        test_list = ["bogus"]
        loader = self._create_loader(test_list)
        suite = loader.loadTestsFromModuleName("breezy.tests.test_sampler")
        self.assertEqual([], _test_ids(suite))


class TestFilteredByNameStartTestLoader(tests.TestCase):
    def _create_loader(self, name_start):
        def needs_module(name):
            return name.startswith(name_start) or name_start.startswith(name)

        loader = TestUtil.FilteredByModuleTestLoader(needs_module)
        return loader

    def test_load_tests(self):
        test_list = ["breezy.tests.test_sampler.DemoTest.test_nothing"]
        loader = self._create_loader("breezy.tests.test_samp")

        suite = loader.loadTestsFromModuleName("breezy.tests.test_sampler")
        self.assertEqual(test_list, _test_ids(suite))

    def test_load_tests_inside_module(self):
        test_list = ["breezy.tests.test_sampler.DemoTest.test_nothing"]
        loader = self._create_loader("breezy.tests.test_sampler.Demo")

        suite = loader.loadTestsFromModuleName("breezy.tests.test_sampler")
        self.assertEqual(test_list, _test_ids(suite))

    def test_exclude_tests(self):
        loader = self._create_loader("bogus")

        suite = loader.loadTestsFromModuleName("breezy.tests.test_sampler")
        self.assertEqual([], _test_ids(suite))


class TestTestPrefixRegistry(tests.TestCase):
    def _get_registry(self):
        tp_registry = tests.TestPrefixAliasRegistry()
        return tp_registry

    def test_register_new_prefix(self):
        tpr = self._get_registry()
        tpr.register("foo", "fff.ooo.ooo")
        self.assertEqual("fff.ooo.ooo", tpr.get("foo"))

    def test_register_existing_prefix(self):
        tpr = self._get_registry()
        tpr.register("bar", "bbb.aaa.rrr")
        tpr.register("bar", "bBB.aAA.rRR")
        self.assertEqual("bbb.aaa.rrr", tpr.get("bar"))
        self.assertThat(
            self.get_log(),
            DocTestMatches("...bar...bbb.aaa.rrr...BB.aAA.rRR", doctest.ELLIPSIS),
        )

    def test_get_unknown_prefix(self):
        tpr = self._get_registry()
        self.assertRaises(KeyError, tpr.get, "I am not a prefix")

    def test_resolve_prefix(self):
        tpr = self._get_registry()
        tpr.register("bar", "bb.aa.rr")
        self.assertEqual("bb.aa.rr", tpr.resolve_alias("bar"))

    def test_resolve_unknown_alias(self):
        tpr = self._get_registry()
        self.assertRaises(errors.CommandError, tpr.resolve_alias, "I am not a prefix")

    def test_predefined_prefixes(self):
        tpr = tests.test_prefix_alias_registry
        self.assertEqual("breezy", tpr.resolve_alias("breezy"))
        self.assertEqual("breezy.doc", tpr.resolve_alias("bd"))
        self.assertEqual("breezy.utils", tpr.resolve_alias("bu"))
        self.assertEqual("breezy.tests", tpr.resolve_alias("bt"))
        self.assertEqual("breezy.tests.blackbox", tpr.resolve_alias("bb"))
        self.assertEqual("breezy.plugins", tpr.resolve_alias("bp"))


class TestThreadLeakDetection(tests.TestCase):
    """Ensure when tests leak threads we detect and report it."""

    class LeakRecordingResult(tests.ExtendedTestResult):
        def __init__(self):
            tests.ExtendedTestResult.__init__(self, StringIO(), 0, 1)
            self.leaks = []

        def _report_thread_leak(self, test, leaks, alive):
            self.leaks.append((test, leaks))

    def test_testcase_without_addCleanups(self):
        """Check old TestCase instances don't break with leak detection."""

        class Test(unittest.TestCase):
            def runTest(self):
                pass

        result = self.LeakRecordingResult()
        test = Test()
        result.startTestRun()
        test.run(result)
        result.stopTestRun()
        self.assertEqual(result._tests_leaking_threads_count, 0)
        self.assertEqual(result.leaks, [])

    def test_thread_leak(self):
        """Ensure a thread that outlives the running of a test is reported.

        Uses a thread that blocks on an event, and is started by the inner
        test case. As the thread outlives the inner case's run, it should be
        detected as a leak, but the event is then set so that the thread can
        be safely joined in cleanup so it's not leaked for real.
        """
        event = threading.Event()
        thread = threading.Thread(name="Leaker", target=event.wait)

        class Test(tests.TestCase):
            def test_leak(self):
                thread.start()

        result = self.LeakRecordingResult()
        test = Test("test_leak")
        self.addCleanup(thread.join)
        self.addCleanup(event.set)
        result.startTestRun()
        test.run(result)
        result.stopTestRun()
        self.assertEqual(result._tests_leaking_threads_count, 1)
        self.assertEqual(result._first_thread_leaker_id, test.id())
        self.assertEqual(result.leaks, [(test, {thread})])
        self.assertContainsString(result.stream.getvalue(), "leaking threads")

    def test_multiple_leaks(self):
        """Check multiple leaks are blamed on the test cases at fault.

        Same concept as the previous test, but has one inner test method that
        leaks two threads, and one that doesn't leak at all.
        """
        event = threading.Event()
        thread_a = threading.Thread(name="LeakerA", target=event.wait)
        thread_b = threading.Thread(name="LeakerB", target=event.wait)
        thread_c = threading.Thread(name="LeakerC", target=event.wait)

        class Test(tests.TestCase):
            def test_first_leak(self):
                thread_b.start()

            def test_second_no_leak(self):
                pass

            def test_third_leak(self):
                thread_c.start()
                thread_a.start()

        result = self.LeakRecordingResult()
        first_test = Test("test_first_leak")
        third_test = Test("test_third_leak")
        self.addCleanup(thread_a.join)
        self.addCleanup(thread_b.join)
        self.addCleanup(thread_c.join)
        self.addCleanup(event.set)
        result.startTestRun()
        unittest.TestSuite([first_test, Test("test_second_no_leak"), third_test]).run(
            result
        )
        result.stopTestRun()
        self.assertEqual(result._tests_leaking_threads_count, 2)
        self.assertEqual(result._first_thread_leaker_id, first_test.id())
        self.assertEqual(
            result.leaks, [(first_test, {thread_b}), (third_test, {thread_a, thread_c})]
        )
        self.assertContainsString(result.stream.getvalue(), "leaking threads")


class TestPostMortemDebugging(tests.TestCase):
    """Check post mortem debugging works when tests fail or error."""

    class TracebackRecordingResult(tests.ExtendedTestResult):
        def __init__(self):
            tests.ExtendedTestResult.__init__(self, StringIO(), 0, 1)
            self.postcode = None

        def _post_mortem(self, tb=None):
            """Record the code object at the end of the current traceback."""
            tb = tb or sys.exc_info()[2]
            if tb is not None:
                next = tb.tb_next
                while next is not None:
                    tb = next
                    next = next.tb_next
                self.postcode = tb.tb_frame.f_code

        def report_error(self, test, err):
            pass

        def report_failure(self, test, err):
            pass

    def test_location_unittest_error(self):
        """Needs right post mortem traceback with erroring unittest case."""

        class Test(unittest.TestCase):
            def runTest(self):
                raise RuntimeError

        result = self.TracebackRecordingResult()
        Test().run(result)
        self.assertEqual(result.postcode, Test.runTest.__code__)

    def test_location_unittest_failure(self):
        """Needs right post mortem traceback with failing unittest case."""

        class Test(unittest.TestCase):
            def runTest(self):
                raise self.failureException

        result = self.TracebackRecordingResult()
        Test().run(result)
        self.assertEqual(result.postcode, Test.runTest.__code__)

    def test_location_bt_error(self):
        """Needs right post mortem traceback with erroring breezy.tests case."""

        class Test(tests.TestCase):
            def test_error(self):
                raise RuntimeError

        result = self.TracebackRecordingResult()
        Test("test_error").run(result)
        self.assertEqual(result.postcode, Test.test_error.__code__)

    def test_location_bt_failure(self):
        """Needs right post mortem traceback with failing breezy.tests case."""

        class Test(tests.TestCase):
            def test_failure(self):
                raise self.failureException

        result = self.TracebackRecordingResult()
        Test("test_failure").run(result)
        self.assertEqual(result.postcode, Test.test_failure.__code__)

    def test_env_var_triggers_post_mortem(self):
        """Check pdb.post_mortem is called iff BRZ_TEST_PDB is set."""
        import pdb

        result = tests.ExtendedTestResult(StringIO(), 0, 1)
        post_mortem_calls = []
        self.overrideAttr(pdb, "post_mortem", post_mortem_calls.append)
        self.overrideEnv("BRZ_TEST_PDB", None)
        result._post_mortem(1)
        self.overrideEnv("BRZ_TEST_PDB", "on")
        result._post_mortem(2)
        self.assertEqual([2], post_mortem_calls)


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
                return tests.ExtendedTestResult(
                    self.stream, self.descriptions, self.verbosity
                )

        tests.run_suite(suite, runner_class=MyRunner, stream=StringIO())
        self.assertLength(1, calls)


class _Selftest:
    """Mixin for tests needing full selftest output."""

    def _inject_stream_into_subunit(self, stream):
        """To be overridden by subclasses that run tests out of process."""

    def _run_selftest(self, **kwargs):
        bio = BytesIO()
        sio = TextIOWrapper(bio, "utf-8")
        self._inject_stream_into_subunit(bio)
        tests.selftest(stream=sio, stop_on_failure=False, **kwargs)
        sio.flush()
        return bio.getvalue()


class _ForkedSelftest(_Selftest):
    """Mixin for tests needing full selftest output with forked children."""

    _test_needs_features = [features.subunit]

    def _inject_stream_into_subunit(self, stream):
        """Monkey-patch subunit so the extra output goes to stream not stdout.

        Some APIs need rewriting so this kind of bogus hackery can be replaced
        by passing the stream param from run_tests down into ProtocolTestCase.
        """
        from subunit import ProtocolTestCase

        _original_init = ProtocolTestCase.__init__

        def _init_with_passthrough(self, *args, **kwargs):
            _original_init(self, *args, **kwargs)
            self._passthrough = stream

        self.overrideAttr(ProtocolTestCase, "__init__", _init_with_passthrough)

    def _run_selftest(self, **kwargs):
        # GZ 2011-05-26: Add a PosixSystem feature so this check can go away
        if getattr(os, "fork", None) is None:
            raise tests.TestNotApplicable("Platform doesn't support forking")
        # Make sure the fork code is actually invoked by claiming two cores
        self.overrideAttr(osutils, "local_concurrency", lambda: 2)
        kwargs.setdefault("suite_decorators", []).append(tests.fork_decorator)
        return super()._run_selftest(**kwargs)


class TestParallelFork(_ForkedSelftest, tests.TestCase):
    """Check operation of --parallel=fork selftest option."""

    def test_error_in_child_during_fork(self):
        """Error in a forked child during test setup should get reported."""

        class Test(tests.TestCase):
            def testMethod(self):
                pass

        # We don't care what, just break something that a child will run
        self.overrideAttr(tests, "workaround_zealous_crypto_random", None)
        out = self._run_selftest(test_suite_factory=Test)
        # Lines from the tracebacks of the two child processes may be mixed
        # together due to the way subunit parses and forwards the streams,
        # so permit extra lines between each part of the error output.
        self.assertContainsRe(
            out,
            b"Traceback.*:\n"
            b"(?:.*\n)*"
            b".+ in fork_for_tests\n"
            b"(?:.*\n)*"
            b"\\s*workaround_zealous_crypto_random\\(\\)\n"
            b"(?:.*\n)*"
            b"TypeError:",
        )


class TestUncollectedWarnings(_Selftest, tests.TestCase):
    """Check a test case still alive after being run emits a warning."""

    class Test(tests.TestCase):
        def test_pass(self):
            pass

        def test_self_ref(self):
            self.also_self = self.test_self_ref

        def test_skip(self):
            self.skipTest("Don't need")

    def _get_suite(self):
        return TestUtil.TestSuite(
            [
                self.Test("test_pass"),
                self.Test("test_self_ref"),
                self.Test("test_skip"),
            ]
        )

    def _run_selftest_with_suite(self, **kwargs):
        old_flags = tests.selftest_debug_flags
        tests.selftest_debug_flags = old_flags.union(["uncollected_cases"])
        gc_on = gc.isenabled()
        if gc_on:
            gc.disable()
        try:
            output = self._run_selftest(test_suite_factory=self._get_suite, **kwargs)
        finally:
            if gc_on:
                gc.enable()
            tests.selftest_debug_flags = old_flags
        self.assertNotContainsRe(output, b"Uncollected test case.*test_pass")
        self.assertContainsRe(output, b"Uncollected test case.*test_self_ref")
        return output

    def test_testsuite(self):
        self._run_selftest_with_suite()

    def test_pattern(self):
        out = self._run_selftest_with_suite(pattern="test_(?:pass|self_ref)$")
        self.assertNotContainsRe(out, b"test_skip")

    def test_exclude_pattern(self):
        out = self._run_selftest_with_suite(exclude_pattern="test_skip$")
        self.assertNotContainsRe(out, b"test_skip")

    def test_random_seed(self):
        self._run_selftest_with_suite(random_seed="now")

    def test_matching_tests_first(self):
        self._run_selftest_with_suite(
            matching_tests_first=True, pattern="test_self_ref$"
        )

    def test_starting_with_and_exclude(self):
        out = self._run_selftest_with_suite(
            starting_with=["bt."], exclude_pattern="test_skip$"
        )
        self.assertNotContainsRe(out, b"test_skip")

    def test_additonal_decorator(self):
        self._run_selftest_with_suite(suite_decorators=[tests.TestDecorator])


class TestUncollectedWarningsSubunit(TestUncollectedWarnings):
    """Check warnings from tests staying alive are emitted with subunit."""

    _test_needs_features = [features.subunit]

    def _run_selftest_with_suite(self, **kwargs):
        return TestUncollectedWarnings._run_selftest_with_suite(
            self, runner_class=tests.SubUnitBzrRunnerv1, **kwargs
        )


class TestUncollectedWarningsForked(_ForkedSelftest, TestUncollectedWarnings):
    """Check warnings from tests staying alive are emitted when forking."""


class TestEnvironHandling(tests.TestCase):
    def test_overrideEnv_None_called_twice_doesnt_leak(self):
        self.assertNotIn("MYVAR", os.environ)
        self.overrideEnv("MYVAR", "42")
        # We use an embedded test to make sure we fix the _captureVar bug

        class Test(tests.TestCase):
            def test_me(self):
                # The first call save the 42 value
                self.overrideEnv("MYVAR", None)
                self.assertEqual(None, os.environ.get("MYVAR"))
                # Make sure we can call it twice
                self.overrideEnv("MYVAR", None)
                self.assertEqual(None, os.environ.get("MYVAR"))

        output = StringIO()
        result = tests.TextTestResult(output, 0, 1)
        Test("test_me").run(result)
        if not result.wasStrictlySuccessful():
            self.fail(output.getvalue())
        # We get our value back
        self.assertEqual("42", os.environ.get("MYVAR"))


class TestIsolatedEnv(tests.TestCase):
    """Test isolating tests from os.environ.

    Since we use tests that are already isolated from os.environ a bit of care
    should be taken when designing the tests to avoid bootstrap side-effects.
    The tests start an already clean os.environ which allow doing valid
    assertions about which variables are present or not and design tests around
    these assertions.
    """

    class ScratchMonkey(tests.TestCase):
        def test_me(self):
            pass

    def test_basics(self):
        # Make sure we know the definition of BRZ_HOME: not part of os.environ
        # for tests.TestCase.
        self.assertIn("BRZ_HOME", tests.isolated_environ)
        self.assertEqual(None, tests.isolated_environ["BRZ_HOME"])
        # Being part of isolated_environ, BRZ_HOME should not appear here
        self.assertNotIn("BRZ_HOME", os.environ)
        # Make sure we know the definition of LINES: part of os.environ for
        # tests.TestCase
        self.assertIn("LINES", tests.isolated_environ)
        self.assertEqual("25", tests.isolated_environ["LINES"])
        self.assertEqual("25", os.environ["LINES"])

    def test_injecting_unknown_variable(self):
        # BRZ_HOME is known to be absent from os.environ
        test = self.ScratchMonkey("test_me")
        tests.override_os_environ(test, {"BRZ_HOME": "foo"})
        self.assertEqual("foo", os.environ["BRZ_HOME"])
        tests.restore_os_environ(test)
        self.assertNotIn("BRZ_HOME", os.environ)

    def test_injecting_known_variable(self):
        test = self.ScratchMonkey("test_me")
        # LINES is known to be present in os.environ
        tests.override_os_environ(test, {"LINES": "42"})
        self.assertEqual("42", os.environ["LINES"])
        tests.restore_os_environ(test)
        self.assertEqual("25", os.environ["LINES"])

    def test_deleting_variable(self):
        test = self.ScratchMonkey("test_me")
        # LINES is known to be present in os.environ
        tests.override_os_environ(test, {"LINES": None})
        self.assertNotIn("LINES", os.environ)
        tests.restore_os_environ(test)
        self.assertEqual("25", os.environ["LINES"])


class TestDocTestSuiteIsolation(tests.TestCase):
    """Test that `tests.DocTestSuite` isolates doc tests from os.environ.

    Since tests.TestCase alreay provides an isolation from os.environ, we use
    the clean environment as a base for testing. To precisely capture the
    isolation provided by tests.DocTestSuite, we use doctest.DocTestSuite to
    compare against.

    We want to make sure `tests.DocTestSuite` respect `tests.isolated_environ`,
    not `os.environ` so each test overrides it to suit its needs.

    """

    def get_doctest_suite_for_string(self, klass, string):
        class Finder(doctest.DocTestFinder):
            def find(*args, **kwargs):
                test = doctest.DocTestParser().get_doctest(
                    string, {}, "foo", "foo.py", 0
                )
                return [test]

        suite = klass(test_finder=Finder())
        return suite

    def run_doctest_suite_for_string(self, klass, string):
        suite = self.get_doctest_suite_for_string(klass, string)
        output = StringIO()
        result = tests.TextTestResult(output, 0, 1)
        suite.run(result)
        return result, output

    def assertDocTestStringSucceds(self, klass, string):
        result, output = self.run_doctest_suite_for_string(klass, string)
        if not result.wasStrictlySuccessful():
            self.fail(output.getvalue())

    def assertDocTestStringFails(self, klass, string):
        result, output = self.run_doctest_suite_for_string(klass, string)
        if result.wasStrictlySuccessful():
            self.fail(output.getvalue())

    def test_injected_variable(self):
        self.overrideAttr(tests, "isolated_environ", {"LINES": "42"})
        test = """
            >>> import os
            >>> os.environ['LINES']
            '42'
            """
        # doctest.DocTestSuite fails as it sees '25'
        self.assertDocTestStringFails(doctest.DocTestSuite, test)
        # tests.DocTestSuite sees '42'
        self.assertDocTestStringSucceds(tests.IsolatedDocTestSuite, test)

    def test_deleted_variable(self):
        self.overrideAttr(tests, "isolated_environ", {"LINES": None})
        test = """
            >>> import os
            >>> os.environ.get('LINES')
            """
        # doctest.DocTestSuite fails as it sees '25'
        self.assertDocTestStringFails(doctest.DocTestSuite, test)
        # tests.DocTestSuite sees None
        self.assertDocTestStringSucceds(tests.IsolatedDocTestSuite, test)


class TestSelftestExcludePatterns(tests.TestCase):
    def setUp(self):
        super().setUp()
        self.overrideAttr(tests, "test_suite", self.suite_factory)

    def suite_factory(self, keep_only=None, starting_with=None):
        """A test suite factory with only a few tests."""

        class Test(tests.TestCase):
            def id(self):
                # We don't need the full class path
                return self._testMethodName

            def a(self):
                pass

            def b(self):
                pass

            def c(self):
                pass

        return TestUtil.TestSuite([Test("a"), Test("b"), Test("c")])

    def assertTestList(self, expected, *selftest_args):
        # We rely on setUp installing the right test suite factory so we can
        # test at the command level without loading the whole test suite
        out, err = self.run_bzr(("selftest", "--list") + selftest_args)
        actual = out.splitlines()
        self.assertEqual(expected, actual)

    def test_full_list(self):
        self.assertTestList(["a", "b", "c"])

    def test_single_exclude(self):
        self.assertTestList(["b", "c"], "-x", "a")

    def test_mutiple_excludes(self):
        self.assertTestList(["c"], "-x", "a", "-x", "b")


class TestCounterHooks(tests.TestCase, SelfTestHelper):
    _test_needs_features = [features.subunit]

    def setUp(self):
        super().setUp()

        class Test(tests.TestCase):
            def setUp(self):
                super().setUp()
                self.hooks = hooks.Hooks()
                self.hooks.add_hook("myhook", "Foo bar blah", (2, 4))
                self.install_counter_hook(self.hooks, "myhook")

            def no_hook(self):
                pass

            def run_hook_once(self):
                for hook in self.hooks["myhook"]:
                    hook(self)

        self.test_class = Test

    def assertHookCalls(self, expected_calls, test_name):
        test = self.test_class(test_name)
        result = unittest.TestResult()
        test.run(result)
        self.assertTrue(hasattr(test, "_counters"))
        self.assertIn("myhook", test._counters)
        self.assertEqual(expected_calls, test._counters["myhook"])

    def test_no_hook(self):
        self.assertHookCalls(0, "no_hook")

    def test_run_hook_once(self):
        tt = features.testtools
        if tt.module.__version__ < (0, 9, 8):
            raise tests.TestSkipped("testtools-0.9.8 required for addDetail")
        self.assertHookCalls(1, "run_hook_once")
