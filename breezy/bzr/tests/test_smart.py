# Copyright (C) 2006-2012, 2016 Canonical Ltd
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

"""Tests for the smart wire/domain protocol.

This module contains tests for the domain-level smart requests and responses,
such as the 'Branch.lock_write' request. Many of these use specific disk
formats to exercise calls that only make sense for formats with specific
properties.

Tests for low-level protocol encoding are found in test_smart_transport.
"""

import bz2
import tarfile
import zlib
from io import BytesIO

import fastbencode as bencode

from breezy import branch as _mod_branch
from breezy import controldir, errors, gpg, tests, transport, urlutils
from breezy.bzr import branch as _mod_bzrbranch
from breezy.bzr import inventory_delta, versionedfile
from breezy.bzr.smart import branch as smart_branch
from breezy.bzr.smart import bzrdir as smart_dir
from breezy.bzr.smart import packrepository as smart_packrepo
from breezy.bzr.smart import repository as smart_repo
from breezy.bzr.smart import request as smart_req
from breezy.bzr.smart import server, vfs
from breezy.bzr.testament import Testament
from breezy.tests import test_server
from breezy.transport import chroot, memory


def load_tests(loader, standard_tests, pattern):
    """Multiply tests version and protocol consistency."""
    # FindRepository tests.
    scenarios = [
        (
            "find_repository",
            {"_request_class": smart_dir.SmartServerRequestFindRepositoryV1},
        ),
        (
            "find_repositoryV2",
            {"_request_class": smart_dir.SmartServerRequestFindRepositoryV2},
        ),
        (
            "find_repositoryV3",
            {"_request_class": smart_dir.SmartServerRequestFindRepositoryV3},
        ),
    ]
    to_adapt, result = tests.split_suite_by_re(
        standard_tests, "TestSmartServerRequestFindRepository"
    )
    v2_only, v1_and_2 = tests.split_suite_by_re(to_adapt, "_v2")
    tests.multiply_tests(v1_and_2, scenarios, result)
    # The first scenario is only applicable to v1 protocols, it is deleted
    # since.
    tests.multiply_tests(v2_only, scenarios[1:], result)
    return result


class TestCaseWithChrootedTransport(tests.TestCaseWithTransport):
    def setUp(self):
        self.vfs_transport_factory = memory.MemoryServer
        super().setUp()
        self._chroot_server = None

    def get_transport(self, relpath=None):
        if self._chroot_server is None:
            backing_transport = tests.TestCaseWithTransport.get_transport(self)
            self._chroot_server = chroot.ChrootServer(backing_transport)
            self.start_server(self._chroot_server)
        t = transport.get_transport_from_url(self._chroot_server.get_url())
        if relpath is not None:
            t = t.clone(relpath)
        return t


class TestCaseWithSmartMedium(tests.TestCaseWithMemoryTransport):
    def setUp(self):
        super().setUp()
        # We're allowed to set  the transport class here, so that we don't use
        # the default or a parameterized class, but rather use the
        # TestCaseWithTransport infrastructure to set up a smart server and
        # transport.
        self.overrideAttr(self, "transport_server", self.make_transport_server)

    def make_transport_server(self):
        return test_server.SmartTCPServer_for_testing("-" + self.id())

    def get_smart_medium(self):
        """Get a smart medium to use in tests."""
        return self.get_transport().get_smart_medium()


class TestByteStreamToStream(tests.TestCase):
    def test_repeated_substreams_same_kind_are_one_stream(self):
        # Make a stream - an iterable of bytestrings.
        stream = [
            (
                "text",
                [versionedfile.FulltextContentFactory((b"k1",), None, None, b"foo")],
            ),
            (
                "text",
                [versionedfile.FulltextContentFactory((b"k2",), None, None, b"bar")],
            ),
        ]
        fmt = controldir.format_registry.get("pack-0.92")().repository_format
        bytes = smart_repo._stream_to_byte_stream(stream, fmt)
        streams = []
        # Iterate the resulting iterable; checking that we get only one stream
        # out.
        fmt, stream = smart_repo._byte_stream_to_stream(bytes)
        for kind, substream in stream:
            streams.append((kind, list(substream)))
        self.assertLength(1, streams)
        self.assertLength(2, streams[0][1])


class TestSmartServerResponse(tests.TestCase):
    def test__eq__(self):
        self.assertEqual(
            smart_req.SmartServerResponse((b"ok",)),
            smart_req.SmartServerResponse((b"ok",)),
        )
        self.assertEqual(
            smart_req.SmartServerResponse((b"ok",), b"body"),
            smart_req.SmartServerResponse((b"ok",), b"body"),
        )
        self.assertNotEqual(
            smart_req.SmartServerResponse((b"ok",)),
            smart_req.SmartServerResponse((b"notok",)),
        )
        self.assertNotEqual(
            smart_req.SmartServerResponse((b"ok",), b"body"),
            smart_req.SmartServerResponse((b"ok",)),
        )
        self.assertNotEqual(None, smart_req.SmartServerResponse((b"ok",)))

    def test__str__(self):
        """SmartServerResponses can be stringified."""
        self.assertIn(
            str(smart_req.SuccessfulSmartServerResponse((b"args",), b"body")),
            (
                "<SuccessfulSmartServerResponse args=(b'args',) body=b'body'>",
                "<SuccessfulSmartServerResponse args=('args',) body='body'>",
            ),
        )
        self.assertIn(
            str(smart_req.FailedSmartServerResponse((b"args",), b"body")),
            (
                "<FailedSmartServerResponse args=(b'args',) body=b'body'>",
                "<FailedSmartServerResponse args=('args',) body='body'>",
            ),
        )


class TestSmartServerRequest(tests.TestCaseWithMemoryTransport):
    def test_translate_client_path(self):
        transport = self.get_transport()
        request = smart_req.SmartServerRequest(transport, "foo/")
        self.assertEqual("./", request.translate_client_path(b"foo/"))
        self.assertRaises(
            urlutils.InvalidURLJoin, request.translate_client_path, b"foo/.."
        )
        self.assertRaises(errors.PathNotChild, request.translate_client_path, b"/")
        self.assertRaises(errors.PathNotChild, request.translate_client_path, b"bar/")
        self.assertEqual("./baz", request.translate_client_path(b"foo/baz"))
        e_acute = "\N{LATIN SMALL LETTER E WITH ACUTE}"
        self.assertEqual(
            "./" + urlutils.escape(e_acute),
            request.translate_client_path(b"foo/" + e_acute.encode("utf-8")),
        )

    def test_translate_client_path_vfs(self):
        """VfsRequests receive escaped paths rather than raw UTF-8."""
        transport = self.get_transport()
        request = vfs.VfsRequest(transport, "foo/")
        e_acute = "\N{LATIN SMALL LETTER E WITH ACUTE}"
        escaped = urlutils.escape("foo/" + e_acute)
        self.assertEqual(
            "./" + urlutils.escape(e_acute),
            request.translate_client_path(escaped.encode("ascii")),
        )

    def test_transport_from_client_path(self):
        transport = self.get_transport()
        request = smart_req.SmartServerRequest(transport, "foo/")
        self.assertEqual(
            transport.base, request.transport_from_client_path(b"foo/").base
        )


class TestSmartServerBzrDirRequestCloningMetaDir(tests.TestCaseWithMemoryTransport):
    """Tests for BzrDir.cloning_metadir."""

    def test_cloning_metadir(self):
        """When there is a bzrdir present, the call succeeds."""
        backing = self.get_transport()
        dir = self.make_controldir(".")
        local_result = dir.cloning_metadir()
        request_class = smart_dir.SmartServerBzrDirRequestCloningMetaDir
        request = request_class(backing)
        expected = smart_req.SuccessfulSmartServerResponse(
            (
                local_result.network_name(),
                local_result.repository_format.network_name(),
                (b"branch", local_result.get_branch_format().network_name()),
            )
        )
        self.assertEqual(expected, request.execute(b"", b"False"))

    def test_cloning_metadir_reference(self):
        """The request fails when bzrdir contains a branch reference."""
        backing = self.get_transport()
        referenced_branch = self.make_branch("referenced")
        dir = self.make_controldir(".")
        dir.cloning_metadir()
        _mod_bzrbranch.BranchReferenceFormat().initialize(
            dir, target_branch=referenced_branch
        )
        _mod_bzrbranch.BranchReferenceFormat().get_reference(dir)
        # The server shouldn't try to follow the branch reference, so it's fine
        # if the referenced branch isn't reachable.
        backing.rename("referenced", "moved")
        request_class = smart_dir.SmartServerBzrDirRequestCloningMetaDir
        request = request_class(backing)
        expected = smart_req.FailedSmartServerResponse((b"BranchReference",))
        self.assertEqual(expected, request.execute(b"", b"False"))


class TestSmartServerBzrDirRequestCheckoutMetaDir(tests.TestCaseWithMemoryTransport):
    """Tests for BzrDir.checkout_metadir."""

    def test_checkout_metadir(self):
        backing = self.get_transport()
        request = smart_dir.SmartServerBzrDirRequestCheckoutMetaDir(backing)
        self.make_branch(".", format="2a")
        response = request.execute(b"")
        self.assertEqual(
            smart_req.SmartServerResponse(
                (
                    b"Bazaar-NG meta directory, format 1\n",
                    b"Bazaar repository format 2a (needs bzr 1.16 or later)\n",
                    b"Bazaar Branch Format 7 (needs bzr 1.6)\n",
                )
            ),
            response,
        )


class TestSmartServerBzrDirRequestDestroyBranch(tests.TestCaseWithMemoryTransport):
    """Tests for BzrDir.destroy_branch."""

    def test_destroy_branch_default(self):
        """The default branch can be removed."""
        backing = self.get_transport()
        self.make_branch(".")
        request_class = smart_dir.SmartServerBzrDirRequestDestroyBranch
        request = request_class(backing)
        expected = smart_req.SuccessfulSmartServerResponse((b"ok",))
        self.assertEqual(expected, request.execute(b"", None))

    def test_destroy_branch_named(self):
        """A named branch can be removed."""
        backing = self.get_transport()
        dir = self.make_repository(".", format="development-colo").controldir
        dir.create_branch(name="branchname")
        request_class = smart_dir.SmartServerBzrDirRequestDestroyBranch
        request = request_class(backing)
        expected = smart_req.SuccessfulSmartServerResponse((b"ok",))
        self.assertEqual(expected, request.execute(b"", b"branchname"))

    def test_destroy_branch_missing(self):
        """An error is raised if the branch didn't exist."""
        backing = self.get_transport()
        self.make_controldir(".", format="development-colo")
        request_class = smart_dir.SmartServerBzrDirRequestDestroyBranch
        request = request_class(backing)
        expected = smart_req.FailedSmartServerResponse((b"nobranch",), None)
        self.assertEqual(expected, request.execute(b"", b"branchname"))


class TestSmartServerBzrDirRequestHasWorkingTree(tests.TestCaseWithTransport):
    """Tests for BzrDir.has_workingtree."""

    def test_has_workingtree_yes(self):
        """A working tree is present."""
        backing = self.get_transport()
        self.make_branch_and_tree(".")
        request_class = smart_dir.SmartServerBzrDirRequestHasWorkingTree
        request = request_class(backing)
        expected = smart_req.SuccessfulSmartServerResponse((b"yes",))
        self.assertEqual(expected, request.execute(b""))

    def test_has_workingtree_no(self):
        """A working tree is missing."""
        backing = self.get_transport()
        self.make_controldir(".")
        request_class = smart_dir.SmartServerBzrDirRequestHasWorkingTree
        request = request_class(backing)
        expected = smart_req.SuccessfulSmartServerResponse((b"no",))
        self.assertEqual(expected, request.execute(b""))


class TestSmartServerBzrDirRequestDestroyRepository(tests.TestCaseWithMemoryTransport):
    """Tests for BzrDir.destroy_repository."""

    def test_destroy_repository_default(self):
        """The repository can be removed."""
        backing = self.get_transport()
        self.make_repository(".")
        request_class = smart_dir.SmartServerBzrDirRequestDestroyRepository
        request = request_class(backing)
        expected = smart_req.SuccessfulSmartServerResponse((b"ok",))
        self.assertEqual(expected, request.execute(b""))

    def test_destroy_repository_missing(self):
        """An error is raised if the repository didn't exist."""
        backing = self.get_transport()
        self.make_controldir(".")
        request_class = smart_dir.SmartServerBzrDirRequestDestroyRepository
        request = request_class(backing)
        expected = smart_req.FailedSmartServerResponse((b"norepository",), None)
        self.assertEqual(expected, request.execute(b""))


class TestSmartServerRequestCreateRepository(tests.TestCaseWithMemoryTransport):
    """Tests for BzrDir.create_repository."""

    def test_makes_repository(self):
        """When there is a bzrdir present, the call succeeds."""
        backing = self.get_transport()
        self.make_controldir(".")
        request_class = smart_dir.SmartServerRequestCreateRepository
        request = request_class(backing)
        reference_bzrdir_format = controldir.format_registry.get("pack-0.92")()
        reference_format = reference_bzrdir_format.repository_format
        network_name = reference_format.network_name()
        expected = smart_req.SuccessfulSmartServerResponse(
            (b"ok", b"no", b"no", b"no", network_name)
        )
        self.assertEqual(expected, request.execute(b"", network_name, b"True"))


class TestSmartServerRequestFindRepository(tests.TestCaseWithMemoryTransport):
    """Tests for BzrDir.find_repository."""

    def test_no_repository(self):
        """If no repository is found, ('norepository', ) is returned."""
        backing = self.get_transport()
        request = self._request_class(backing)
        self.make_controldir(".")
        self.assertEqual(
            smart_req.SmartServerResponse((b"norepository",)), request.execute(b"")
        )

    def test_nonshared_repository(self):
        # nonshared repositorys only allow 'find' to return a handle when the
        # path the repository is being searched on is the same as that that
        # the repository is at.
        backing = self.get_transport()
        request = self._request_class(backing)
        result = self._make_repository_and_result()
        self.assertEqual(result, request.execute(b""))
        self.make_controldir("subdir")
        self.assertEqual(
            smart_req.SmartServerResponse((b"norepository",)),
            request.execute(b"subdir"),
        )

    def _make_repository_and_result(self, shared=False, format=None):
        """Convenience function to setup a repository.

        :result: The SmartServerResponse to expect when opening it.
        """
        repo = self.make_repository(".", shared=shared, format=format)
        if repo.supports_rich_root():
            rich_root = b"yes"
        else:
            rich_root = b"no"
        if repo._format.supports_tree_reference:
            subtrees = b"yes"
        else:
            subtrees = b"no"
        if repo._format.supports_external_lookups:
            external = b"yes"
        else:
            external = b"no"
        if smart_dir.SmartServerRequestFindRepositoryV3 == self._request_class:
            return smart_req.SuccessfulSmartServerResponse(
                (b"ok", b"", rich_root, subtrees, external, repo._format.network_name())
            )
        elif smart_dir.SmartServerRequestFindRepositoryV2 == self._request_class:
            # All tests so far are on formats, and for non-external
            # repositories.
            return smart_req.SuccessfulSmartServerResponse(
                (b"ok", b"", rich_root, subtrees, external)
            )
        else:
            return smart_req.SuccessfulSmartServerResponse(
                (b"ok", b"", rich_root, subtrees)
            )

    def test_shared_repository(self):
        """For a shared repository, we get 'ok', 'relpath-to-repo'."""
        backing = self.get_transport()
        request = self._request_class(backing)
        result = self._make_repository_and_result(shared=True)
        self.assertEqual(result, request.execute(b""))
        self.make_controldir("subdir")
        result2 = smart_req.SmartServerResponse(
            result.args[0:1] + (b"..",) + result.args[2:]
        )
        self.assertEqual(result2, request.execute(b"subdir"))
        self.make_controldir("subdir/deeper")
        result3 = smart_req.SmartServerResponse(
            result.args[0:1] + (b"../..",) + result.args[2:]
        )
        self.assertEqual(result3, request.execute(b"subdir/deeper"))

    def test_rich_root_and_subtree_encoding(self):
        """Test for the format attributes for rich root and subtree support."""
        backing = self.get_transport()
        request = self._request_class(backing)
        result = self._make_repository_and_result(format="development-subtree")
        # check the test will be valid
        self.assertEqual(b"yes", result.args[2])
        self.assertEqual(b"yes", result.args[3])
        self.assertEqual(result, request.execute(b""))

    def test_supports_external_lookups_no_v2(self):
        """Test for the supports_external_lookups attribute."""
        backing = self.get_transport()
        request = self._request_class(backing)
        result = self._make_repository_and_result(format="development-subtree")
        # check the test will be valid
        self.assertEqual(b"yes", result.args[4])
        self.assertEqual(result, request.execute(b""))


class TestSmartServerBzrDirRequestGetConfigFile(tests.TestCaseWithMemoryTransport):
    """Tests for BzrDir.get_config_file."""

    def test_present(self):
        backing = self.get_transport()
        dir = self.make_controldir(".")
        dir.get_config().set_default_stack_on("/")
        local_result = dir._get_config()._get_config_file().read()
        request_class = smart_dir.SmartServerBzrDirRequestConfigFile
        request = request_class(backing)
        expected = smart_req.SuccessfulSmartServerResponse((), local_result)
        self.assertEqual(expected, request.execute(b""))

    def test_missing(self):
        backing = self.get_transport()
        self.make_controldir(".")
        request_class = smart_dir.SmartServerBzrDirRequestConfigFile
        request = request_class(backing)
        expected = smart_req.SuccessfulSmartServerResponse((), b"")
        self.assertEqual(expected, request.execute(b""))


class TestSmartServerBzrDirRequestGetBranches(tests.TestCaseWithMemoryTransport):
    """Tests for BzrDir.get_branches."""

    def test_simple(self):
        backing = self.get_transport()
        branch = self.make_branch(".")
        request_class = smart_dir.SmartServerBzrDirRequestGetBranches
        request = request_class(backing)
        local_result = bencode.bencode(
            {b"": (b"branch", branch._format.network_name())}
        )
        expected = smart_req.SuccessfulSmartServerResponse((b"success",), local_result)
        self.assertEqual(expected, request.execute(b""))

    def test_ref(self):
        backing = self.get_transport()
        dir = self.make_controldir("foo")
        b = self.make_branch("bar")
        dir.set_branch_reference(b)
        request_class = smart_dir.SmartServerBzrDirRequestGetBranches
        request = request_class(backing)
        local_result = bencode.bencode({b"": (b"ref", b"../bar/")})
        expected = smart_req.SuccessfulSmartServerResponse((b"success",), local_result)
        self.assertEqual(expected, request.execute(b"foo"))

    def test_empty(self):
        backing = self.get_transport()
        self.make_controldir(".")
        request_class = smart_dir.SmartServerBzrDirRequestGetBranches
        request = request_class(backing)
        local_result = bencode.bencode({})
        expected = smart_req.SuccessfulSmartServerResponse((b"success",), local_result)
        self.assertEqual(expected, request.execute(b""))


class TestSmartServerRequestInitializeBzrDir(tests.TestCaseWithMemoryTransport):
    def test_empty_dir(self):
        """Initializing an empty dir should succeed and do it."""
        backing = self.get_transport()
        request = smart_dir.SmartServerRequestInitializeBzrDir(backing)
        self.assertEqual(smart_req.SmartServerResponse((b"ok",)), request.execute(b""))
        made_dir = controldir.ControlDir.open_from_transport(backing)
        # no branch, tree or repository is expected with the current
        # default formart.
        self.assertRaises(errors.NoWorkingTree, made_dir.open_workingtree)
        self.assertRaises(errors.NotBranchError, made_dir.open_branch)
        self.assertRaises(errors.NoRepositoryPresent, made_dir.open_repository)

    def test_missing_dir(self):
        """Initializing a missing directory should fail like the bzrdir api."""
        backing = self.get_transport()
        request = smart_dir.SmartServerRequestInitializeBzrDir(backing)
        self.assertRaises(transport.NoSuchFile, request.execute, b"subdir")

    def test_initialized_dir(self):
        """Initializing an extant bzrdir should fail like the bzrdir api."""
        backing = self.get_transport()
        request = smart_dir.SmartServerRequestInitializeBzrDir(backing)
        self.make_controldir("subdir")
        self.assertRaises(errors.AlreadyControlDirError, request.execute, b"subdir")


class TestSmartServerRequestBzrDirInitializeEx(tests.TestCaseWithMemoryTransport):
    """Basic tests for BzrDir.initialize_ex_1.16 in the smart server.

    The main unit tests in test_bzrdir exercise the API comprehensively.
    """

    def test_empty_dir(self):
        """Initializing an empty dir should succeed and do it."""
        backing = self.get_transport()
        name = self.make_controldir("reference")._format.network_name()
        request = smart_dir.SmartServerRequestBzrDirInitializeEx(backing)
        self.assertEqual(
            smart_req.SmartServerResponse(
                (b"", b"", b"", b"", b"", b"", name, b"False", b"", b"", b"")
            ),
            request.execute(
                name, b"", b"True", b"False", b"False", b"", b"", b"", b"", b"False"
            ),
        )
        made_dir = controldir.ControlDir.open_from_transport(backing)
        # no branch, tree or repository is expected with the current
        # default format.
        self.assertRaises(errors.NoWorkingTree, made_dir.open_workingtree)
        self.assertRaises(errors.NotBranchError, made_dir.open_branch)
        self.assertRaises(errors.NoRepositoryPresent, made_dir.open_repository)

    def test_missing_dir(self):
        """Initializing a missing directory should fail like the bzrdir api."""
        backing = self.get_transport()
        name = self.make_controldir("reference")._format.network_name()
        request = smart_dir.SmartServerRequestBzrDirInitializeEx(backing)
        self.assertRaises(
            transport.NoSuchFile,
            request.execute,
            name,
            b"subdir/dir",
            b"False",
            b"False",
            b"False",
            b"",
            b"",
            b"",
            b"",
            b"False",
        )

    def test_initialized_dir(self):
        """Initializing an extant directory should fail like the bzrdir api."""
        backing = self.get_transport()
        name = self.make_controldir("reference")._format.network_name()
        request = smart_dir.SmartServerRequestBzrDirInitializeEx(backing)
        self.make_controldir("subdir")
        self.assertRaises(
            transport.FileExists,
            request.execute,
            name,
            b"subdir",
            b"False",
            b"False",
            b"False",
            b"",
            b"",
            b"",
            b"",
            b"False",
        )


class TestSmartServerRequestOpenBzrDir(tests.TestCaseWithMemoryTransport):
    def test_no_directory(self):
        backing = self.get_transport()
        request = smart_dir.SmartServerRequestOpenBzrDir(backing)
        self.assertEqual(
            smart_req.SmartServerResponse((b"no",)), request.execute(b"does-not-exist")
        )

    def test_empty_directory(self):
        backing = self.get_transport()
        backing.mkdir("empty")
        request = smart_dir.SmartServerRequestOpenBzrDir(backing)
        self.assertEqual(
            smart_req.SmartServerResponse((b"no",)), request.execute(b"empty")
        )

    def test_outside_root_client_path(self):
        backing = self.get_transport()
        request = smart_dir.SmartServerRequestOpenBzrDir(
            backing, root_client_path="root"
        )
        self.assertEqual(
            smart_req.SmartServerResponse((b"no",)), request.execute(b"not-root")
        )


class TestSmartServerRequestOpenBzrDir_2_1(tests.TestCaseWithMemoryTransport):
    def test_no_directory(self):
        backing = self.get_transport()
        request = smart_dir.SmartServerRequestOpenBzrDir_2_1(backing)
        self.assertEqual(
            smart_req.SmartServerResponse((b"no",)), request.execute(b"does-not-exist")
        )

    def test_empty_directory(self):
        backing = self.get_transport()
        backing.mkdir("empty")
        request = smart_dir.SmartServerRequestOpenBzrDir_2_1(backing)
        self.assertEqual(
            smart_req.SmartServerResponse((b"no",)), request.execute(b"empty")
        )

    def test_present_without_workingtree(self):
        backing = self.get_transport()
        request = smart_dir.SmartServerRequestOpenBzrDir_2_1(backing)
        self.make_controldir(".")
        self.assertEqual(
            smart_req.SmartServerResponse((b"yes", b"no")), request.execute(b"")
        )

    def test_outside_root_client_path(self):
        backing = self.get_transport()
        request = smart_dir.SmartServerRequestOpenBzrDir_2_1(
            backing, root_client_path="root"
        )
        self.assertEqual(
            smart_req.SmartServerResponse((b"no",)), request.execute(b"not-root")
        )


class TestSmartServerRequestOpenBzrDir_2_1_disk(TestCaseWithChrootedTransport):
    def test_present_with_workingtree(self):
        self.vfs_transport_factory = test_server.LocalURLServer
        backing = self.get_transport()
        request = smart_dir.SmartServerRequestOpenBzrDir_2_1(backing)
        bd = self.make_controldir(".")
        bd.create_repository()
        bd.create_branch()
        bd.create_workingtree()
        self.assertEqual(
            smart_req.SmartServerResponse((b"yes", b"yes")), request.execute(b"")
        )


class TestSmartServerRequestOpenBranch(TestCaseWithChrootedTransport):
    def test_no_branch(self):
        """When there is no branch, ('nobranch', ) is returned."""
        backing = self.get_transport()
        request = smart_dir.SmartServerRequestOpenBranch(backing)
        self.make_controldir(".")
        self.assertEqual(
            smart_req.SmartServerResponse((b"nobranch",)), request.execute(b"")
        )

    def test_branch(self):
        """When there is a branch, 'ok' is returned."""
        backing = self.get_transport()
        request = smart_dir.SmartServerRequestOpenBranch(backing)
        self.make_branch(".")
        self.assertEqual(
            smart_req.SmartServerResponse((b"ok", b"")), request.execute(b"")
        )

    def test_branch_reference(self):
        """When there is a branch reference, the reference URL is returned."""
        self.vfs_transport_factory = test_server.LocalURLServer
        backing = self.get_transport()
        request = smart_dir.SmartServerRequestOpenBranch(backing)
        branch = self.make_branch("branch")
        checkout = branch.create_checkout("reference", lightweight=True)
        reference_url = (
            _mod_bzrbranch.BranchReferenceFormat()
            .get_reference(checkout.controldir)
            .encode("utf-8")
        )
        self.assertFileEqual(reference_url, "reference/.bzr/branch/location")
        self.assertEqual(
            smart_req.SmartServerResponse((b"ok", reference_url)),
            request.execute(b"reference"),
        )

    def test_notification_on_branch_from_repository(self):
        """When there is a repository, the error should return details."""
        backing = self.get_transport()
        request = smart_dir.SmartServerRequestOpenBranch(backing)
        self.make_repository(".")
        self.assertEqual(
            smart_req.SmartServerResponse((b"nobranch",)), request.execute(b"")
        )


class TestSmartServerRequestOpenBranchV2(TestCaseWithChrootedTransport):
    def test_no_branch(self):
        """When there is no branch, ('nobranch', ) is returned."""
        backing = self.get_transport()
        self.make_controldir(".")
        request = smart_dir.SmartServerRequestOpenBranchV2(backing)
        self.assertEqual(
            smart_req.SmartServerResponse((b"nobranch",)), request.execute(b"")
        )

    def test_branch(self):
        """When there is a branch, 'ok' is returned."""
        backing = self.get_transport()
        expected = self.make_branch(".")._format.network_name()
        request = smart_dir.SmartServerRequestOpenBranchV2(backing)
        self.assertEqual(
            smart_req.SuccessfulSmartServerResponse((b"branch", expected)),
            request.execute(b""),
        )

    def test_branch_reference(self):
        """When there is a branch reference, the reference URL is returned."""
        self.vfs_transport_factory = test_server.LocalURLServer
        backing = self.get_transport()
        request = smart_dir.SmartServerRequestOpenBranchV2(backing)
        branch = self.make_branch("branch")
        checkout = branch.create_checkout("reference", lightweight=True)
        reference_url = (
            _mod_bzrbranch.BranchReferenceFormat()
            .get_reference(checkout.controldir)
            .encode("utf-8")
        )
        self.assertFileEqual(reference_url, "reference/.bzr/branch/location")
        self.assertEqual(
            smart_req.SuccessfulSmartServerResponse((b"ref", reference_url)),
            request.execute(b"reference"),
        )

    def test_stacked_branch(self):
        """Opening a stacked branch does not open the stacked-on branch."""
        trunk = self.make_branch("trunk")
        feature = self.make_branch("feature")
        feature.set_stacked_on_url(trunk.base)
        opened_branches = []
        _mod_branch.Branch.hooks.install_named_hook(
            "open", opened_branches.append, None
        )
        backing = self.get_transport()
        request = smart_dir.SmartServerRequestOpenBranchV2(backing)
        request.setup_jail()
        try:
            response = request.execute(b"feature")
        finally:
            request.teardown_jail()
        expected_format = feature._format.network_name()
        self.assertEqual(
            smart_req.SuccessfulSmartServerResponse((b"branch", expected_format)),
            response,
        )
        self.assertLength(1, opened_branches)

    def test_notification_on_branch_from_repository(self):
        """When there is a repository, the error should return details."""
        backing = self.get_transport()
        request = smart_dir.SmartServerRequestOpenBranchV2(backing)
        self.make_repository(".")
        self.assertEqual(
            smart_req.SmartServerResponse((b"nobranch",)), request.execute(b"")
        )


class TestSmartServerRequestOpenBranchV3(TestCaseWithChrootedTransport):
    def test_no_branch(self):
        """When there is no branch, ('nobranch', ) is returned."""
        backing = self.get_transport()
        self.make_controldir(".")
        request = smart_dir.SmartServerRequestOpenBranchV3(backing)
        self.assertEqual(
            smart_req.SmartServerResponse((b"nobranch",)), request.execute(b"")
        )

    def test_branch(self):
        """When there is a branch, 'ok' is returned."""
        backing = self.get_transport()
        expected = self.make_branch(".")._format.network_name()
        request = smart_dir.SmartServerRequestOpenBranchV3(backing)
        self.assertEqual(
            smart_req.SuccessfulSmartServerResponse((b"branch", expected)),
            request.execute(b""),
        )

    def test_branch_reference(self):
        """When there is a branch reference, the reference URL is returned."""
        self.vfs_transport_factory = test_server.LocalURLServer
        backing = self.get_transport()
        request = smart_dir.SmartServerRequestOpenBranchV3(backing)
        branch = self.make_branch("branch")
        checkout = branch.create_checkout("reference", lightweight=True)
        reference_url = (
            _mod_bzrbranch.BranchReferenceFormat()
            .get_reference(checkout.controldir)
            .encode("utf-8")
        )
        self.assertFileEqual(reference_url, "reference/.bzr/branch/location")
        self.assertEqual(
            smart_req.SuccessfulSmartServerResponse((b"ref", reference_url)),
            request.execute(b"reference"),
        )

    def test_stacked_branch(self):
        """Opening a stacked branch does not open the stacked-on branch."""
        trunk = self.make_branch("trunk")
        feature = self.make_branch("feature")
        feature.set_stacked_on_url(trunk.base)
        opened_branches = []
        _mod_branch.Branch.hooks.install_named_hook(
            "open", opened_branches.append, None
        )
        backing = self.get_transport()
        request = smart_dir.SmartServerRequestOpenBranchV3(backing)
        request.setup_jail()
        try:
            response = request.execute(b"feature")
        finally:
            request.teardown_jail()
        expected_format = feature._format.network_name()
        self.assertEqual(
            smart_req.SuccessfulSmartServerResponse((b"branch", expected_format)),
            response,
        )
        self.assertLength(1, opened_branches)

    def test_notification_on_branch_from_repository(self):
        """When there is a repository, the error should return details."""
        backing = self.get_transport()
        request = smart_dir.SmartServerRequestOpenBranchV3(backing)
        self.make_repository(".")
        self.assertEqual(
            smart_req.SmartServerResponse((b"nobranch", b"location is a repository")),
            request.execute(b""),
        )


class TestSmartServerRequestRevisionHistory(tests.TestCaseWithMemoryTransport):
    def test_empty(self):
        """For an empty branch, the body is empty."""
        backing = self.get_transport()
        request = smart_branch.SmartServerRequestRevisionHistory(backing)
        self.make_branch(".")
        self.assertEqual(
            smart_req.SmartServerResponse((b"ok",), b""), request.execute(b"")
        )

    def test_not_empty(self):
        """For a non-empty branch, the body is empty."""
        backing = self.get_transport()
        request = smart_branch.SmartServerRequestRevisionHistory(backing)
        tree = self.make_branch_and_memory_tree(".")
        tree.lock_write()
        tree.add("")
        r1 = tree.commit("1st commit")
        r2 = tree.commit("2nd commit", rev_id="\xc8".encode())
        tree.unlock()
        self.assertEqual(
            smart_req.SmartServerResponse((b"ok",), (b"\x00".join([r1, r2]))),
            request.execute(b""),
        )


class TestSmartServerBranchRequest(tests.TestCaseWithMemoryTransport):
    def test_no_branch(self):
        """When there is a bzrdir and no branch, NotBranchError is raised."""
        backing = self.get_transport()
        request = smart_branch.SmartServerBranchRequest(backing)
        self.make_controldir(".")
        self.assertRaises(errors.NotBranchError, request.execute, b"")

    def test_branch_reference(self):
        """When there is a branch reference, NotBranchError is raised."""
        backing = self.get_transport()
        request = smart_branch.SmartServerBranchRequest(backing)
        branch = self.make_branch("branch")
        branch.create_checkout("reference", lightweight=True)
        self.assertRaises(errors.NotBranchError, request.execute, b"checkout")


class TestSmartServerBranchRequestLastRevisionInfo(tests.TestCaseWithMemoryTransport):
    def test_empty(self):
        """For an empty branch, the result is ('ok', '0', b'null:')."""
        backing = self.get_transport()
        request = smart_branch.SmartServerBranchRequestLastRevisionInfo(backing)
        self.make_branch(".")
        self.assertEqual(
            smart_req.SmartServerResponse((b"ok", b"0", b"null:")), request.execute(b"")
        )

    def test_ghost(self):
        """For an empty branch, the result is ('ok', '0', b'null:')."""
        backing = self.get_transport()
        request = smart_branch.SmartServerBranchRequestLastRevisionInfo(backing)
        branch = self.make_branch(".")

        def last_revision_info():
            raise errors.GhostRevisionsHaveNoRevno(b"revid1", b"revid2")

        self.overrideAttr(branch, "last_revision_info", last_revision_info)
        self.assertRaises(
            errors.GhostRevisionsHaveNoRevno, request.do_with_branch, branch
        )

    def test_not_empty(self):
        """For a non-empty branch, the result is ('ok', 'revno', 'revid')."""
        backing = self.get_transport()
        request = smart_branch.SmartServerBranchRequestLastRevisionInfo(backing)
        tree = self.make_branch_and_memory_tree(".")
        tree.lock_write()
        tree.add("")
        rev_id_utf8 = "\xc8".encode()
        tree.commit("1st commit")
        tree.commit("2nd commit", rev_id=rev_id_utf8)
        tree.unlock()
        self.assertEqual(
            smart_req.SmartServerResponse((b"ok", b"2", rev_id_utf8)),
            request.execute(b""),
        )


class TestSmartServerBranchRequestRevisionIdToRevno(tests.TestCaseWithMemoryTransport):
    def test_null(self):
        backing = self.get_transport()
        request = smart_branch.SmartServerBranchRequestRevisionIdToRevno(backing)
        self.make_branch(".")
        self.assertEqual(
            smart_req.SmartServerResponse((b"ok", b"0")), request.execute(b"", b"null:")
        )

    def test_ghost_revision(self):
        backing = self.get_transport()
        request = smart_branch.SmartServerBranchRequestRevisionIdToRevno(backing)
        branch = self.make_branch(".")

        def revision_id_to_dotted_revno(revid):
            raise errors.GhostRevisionsHaveNoRevno(revid, b"ghost-revid")

        self.overrideAttr(
            branch, "revision_id_to_dotted_revno", revision_id_to_dotted_revno
        )
        self.assertEqual(
            smart_req.FailedSmartServerResponse(
                (b"GhostRevisionsHaveNoRevno", b"revid", b"ghost-revid")
            ),
            request.do_with_branch(branch, b"revid"),
        )

    def test_simple(self):
        backing = self.get_transport()
        request = smart_branch.SmartServerBranchRequestRevisionIdToRevno(backing)
        tree = self.make_branch_and_memory_tree(".")
        tree.lock_write()
        tree.add("")
        r1 = tree.commit("1st commit")
        tree.unlock()
        self.assertEqual(
            smart_req.SmartServerResponse((b"ok", b"1")), request.execute(b"", r1)
        )

    def test_not_found(self):
        backing = self.get_transport()
        request = smart_branch.SmartServerBranchRequestRevisionIdToRevno(backing)
        self.make_branch(".")
        self.assertEqual(
            smart_req.FailedSmartServerResponse((b"NoSuchRevision", b"idontexist")),
            request.execute(b"", b"idontexist"),
        )


class TestSmartServerBranchRequestGetConfigFile(tests.TestCaseWithMemoryTransport):
    def test_default(self):
        """With no file, we get empty content."""
        backing = self.get_transport()
        request = smart_branch.SmartServerBranchGetConfigFile(backing)
        self.make_branch(".")
        # there should be no file by default
        content = b""
        self.assertEqual(
            smart_req.SmartServerResponse((b"ok",), content), request.execute(b"")
        )

    def test_with_content(self):
        # SmartServerBranchGetConfigFile should return the content from
        # branch.control_files.get('branch.conf') for now - in the future it
        # may perform more complex processing.
        backing = self.get_transport()
        request = smart_branch.SmartServerBranchGetConfigFile(backing)
        branch = self.make_branch(".")
        branch._transport.put_bytes("branch.conf", b"foo bar baz")
        self.assertEqual(
            smart_req.SmartServerResponse((b"ok",), b"foo bar baz"),
            request.execute(b""),
        )


class TestLockedBranch(tests.TestCaseWithMemoryTransport):
    def get_lock_tokens(self, branch):
        branch_token = branch.lock_write().token
        repo_token = branch.repository.lock_write().repository_token
        branch.repository.unlock()
        return branch_token, repo_token


class TestSmartServerBranchRequestPutConfigFile(TestLockedBranch):
    def test_with_content(self):
        backing = self.get_transport()
        request = smart_branch.SmartServerBranchPutConfigFile(backing)
        branch = self.make_branch(".")
        branch_token, repo_token = self.get_lock_tokens(branch)
        self.assertIs(None, request.execute(b"", branch_token, repo_token))
        self.assertEqual(
            smart_req.SmartServerResponse((b"ok",)), request.do_body(b"foo bar baz")
        )
        self.assertEqual(
            branch.control_transport.get_bytes("branch.conf"), b"foo bar baz"
        )
        branch.unlock()


class TestSmartServerBranchRequestSetConfigOption(TestLockedBranch):
    def test_value_name(self):
        branch = self.make_branch(".")
        request = smart_branch.SmartServerBranchRequestSetConfigOption(
            branch.controldir.root_transport
        )
        branch_token, repo_token = self.get_lock_tokens(branch)
        config = branch._get_config()
        result = request.execute(b"", branch_token, repo_token, b"bar", b"foo", b"")
        self.assertEqual(smart_req.SuccessfulSmartServerResponse(()), result)
        self.assertEqual("bar", config.get_option("foo"))
        # Cleanup
        branch.unlock()

    def test_value_name_section(self):
        branch = self.make_branch(".")
        request = smart_branch.SmartServerBranchRequestSetConfigOption(
            branch.controldir.root_transport
        )
        branch_token, repo_token = self.get_lock_tokens(branch)
        config = branch._get_config()
        result = request.execute(b"", branch_token, repo_token, b"bar", b"foo", b"gam")
        self.assertEqual(smart_req.SuccessfulSmartServerResponse(()), result)
        self.assertEqual("bar", config.get_option("foo", "gam"))
        # Cleanup
        branch.unlock()


class TestSmartServerBranchRequestSetConfigOptionDict(TestLockedBranch):
    def setUp(self):
        TestLockedBranch.setUp(self)
        # A dict with non-ascii keys and values to exercise unicode
        # roundtripping.
        self.encoded_value_dict = b"d5:ascii1:a11:unicode \xe2\x8c\x9a3:\xe2\x80\xbde"
        self.value_dict = {"ascii": "a", "unicode \N{WATCH}": "\N{INTERROBANG}"}

    def test_value_name(self):
        branch = self.make_branch(".")
        request = smart_branch.SmartServerBranchRequestSetConfigOptionDict(
            branch.controldir.root_transport
        )
        branch_token, repo_token = self.get_lock_tokens(branch)
        config = branch._get_config()
        result = request.execute(
            b"", branch_token, repo_token, self.encoded_value_dict, b"foo", b""
        )
        self.assertEqual(smart_req.SuccessfulSmartServerResponse(()), result)
        self.assertEqual(self.value_dict, config.get_option("foo"))
        # Cleanup
        branch.unlock()

    def test_value_name_section(self):
        branch = self.make_branch(".")
        request = smart_branch.SmartServerBranchRequestSetConfigOptionDict(
            branch.controldir.root_transport
        )
        branch_token, repo_token = self.get_lock_tokens(branch)
        config = branch._get_config()
        result = request.execute(
            b"", branch_token, repo_token, self.encoded_value_dict, b"foo", b"gam"
        )
        self.assertEqual(smart_req.SuccessfulSmartServerResponse(()), result)
        self.assertEqual(self.value_dict, config.get_option("foo", "gam"))
        # Cleanup
        branch.unlock()


class TestSmartServerBranchRequestSetTagsBytes(TestLockedBranch):
    # Only called when the branch format and tags match [yay factory
    # methods] so only need to test straight forward cases.

    def test_set_bytes(self):
        base_branch = self.make_branch("base")
        tag_bytes = base_branch._get_tags_bytes()
        # get_lock_tokens takes out a lock.
        branch_token, repo_token = self.get_lock_tokens(base_branch)
        request = smart_branch.SmartServerBranchSetTagsBytes(self.get_transport())
        response = request.execute(b"base", branch_token, repo_token)
        self.assertEqual(None, response)
        response = request.do_chunk(tag_bytes)
        self.assertEqual(None, response)
        response = request.do_end()
        self.assertEqual(smart_req.SuccessfulSmartServerResponse(()), response)
        base_branch.unlock()

    def test_lock_failed(self):
        base_branch = self.make_branch("base")
        base_branch.lock_write()
        tag_bytes = base_branch._get_tags_bytes()
        request = smart_branch.SmartServerBranchSetTagsBytes(self.get_transport())
        self.assertRaises(
            errors.TokenMismatch,
            request.execute,
            b"base",
            b"wrong token",
            b"wrong token",
        )
        # The request handler will keep processing the message parts, so even
        # if the request fails immediately do_chunk and do_end are still
        # called.
        request.do_chunk(tag_bytes)
        request.do_end()
        base_branch.unlock()


class SetLastRevisionTestBase(TestLockedBranch):
    """Base test case for verbs that implement set_last_revision."""

    def setUp(self):
        super().setUp()
        backing_transport = self.get_transport()
        self.request = self.request_class(backing_transport)
        self.tree = self.make_branch_and_memory_tree(".")

    def lock_branch(self):
        return self.get_lock_tokens(self.tree.branch)

    def unlock_branch(self):
        self.tree.branch.unlock()

    def set_last_revision(self, revision_id, revno):
        branch_token, repo_token = self.lock_branch()
        response = self._set_last_revision(revision_id, revno, branch_token, repo_token)
        self.unlock_branch()
        return response

    def assertRequestSucceeds(self, revision_id, revno):
        response = self.set_last_revision(revision_id, revno)
        self.assertEqual(smart_req.SuccessfulSmartServerResponse((b"ok",)), response)


class TestSetLastRevisionVerbMixin:
    """Mixin test case for verbs that implement set_last_revision."""

    def test_set_null_to_null(self):
        """An empty branch can have its last revision set to b'null:'."""
        self.assertRequestSucceeds(b"null:", 0)

    def test_NoSuchRevision(self):
        """If the revision_id is not present, the verb returns NoSuchRevision."""
        revision_id = b"non-existent revision"
        self.assertEqual(
            smart_req.FailedSmartServerResponse((b"NoSuchRevision", revision_id)),
            self.set_last_revision(revision_id, 1),
        )

    def make_tree_with_two_commits(self):
        self.tree.lock_write()
        self.tree.add("")
        rev_id_utf8 = "\xc8".encode()
        self.tree.commit("1st commit", rev_id=rev_id_utf8)
        self.tree.commit("2nd commit", rev_id=b"rev-2")
        self.tree.unlock()

    def test_branch_last_revision_info_is_updated(self):
        """A branch's tip can be set to a revision that is present in its
        repository.
        """
        # Make a branch with an empty revision history, but two revisions in
        # its repository.
        self.make_tree_with_two_commits()
        rev_id_utf8 = "\xc8".encode()
        self.tree.branch.set_last_revision_info(0, b"null:")
        self.assertEqual((0, b"null:"), self.tree.branch.last_revision_info())
        # We can update the branch to a revision that is present in the
        # repository.
        self.assertRequestSucceeds(rev_id_utf8, 1)
        self.assertEqual((1, rev_id_utf8), self.tree.branch.last_revision_info())

    def test_branch_last_revision_info_rewind(self):
        """A branch's tip can be set to a revision that is an ancestor of the
        current tip.
        """
        self.make_tree_with_two_commits()
        rev_id_utf8 = "\xc8".encode()
        self.assertEqual((2, b"rev-2"), self.tree.branch.last_revision_info())
        self.assertRequestSucceeds(rev_id_utf8, 1)
        self.assertEqual((1, rev_id_utf8), self.tree.branch.last_revision_info())

    def test_TipChangeRejected(self):
        """If a pre_change_branch_tip hook raises TipChangeRejected, the verb
        returns TipChangeRejected.
        """
        rejection_message = "rejection message\N{INTERROBANG}"

        def hook_that_rejects(params):
            raise errors.TipChangeRejected(rejection_message)

        _mod_branch.Branch.hooks.install_named_hook(
            "pre_change_branch_tip", hook_that_rejects, None
        )
        self.assertEqual(
            smart_req.FailedSmartServerResponse(
                (b"TipChangeRejected", rejection_message.encode("utf-8"))
            ),
            self.set_last_revision(b"null:", 0),
        )


class TestSmartServerBranchRequestSetLastRevision(
    SetLastRevisionTestBase, TestSetLastRevisionVerbMixin
):
    """Tests for Branch.set_last_revision verb."""

    request_class = smart_branch.SmartServerBranchRequestSetLastRevision

    def _set_last_revision(self, revision_id, revno, branch_token, repo_token):
        return self.request.execute(b"", branch_token, repo_token, revision_id)


class TestSmartServerBranchRequestSetLastRevisionInfo(
    SetLastRevisionTestBase, TestSetLastRevisionVerbMixin
):
    """Tests for Branch.set_last_revision_info verb."""

    request_class = smart_branch.SmartServerBranchRequestSetLastRevisionInfo

    def _set_last_revision(self, revision_id, revno, branch_token, repo_token):
        return self.request.execute(b"", branch_token, repo_token, revno, revision_id)

    def test_NoSuchRevision(self):
        """Branch.set_last_revision_info does not have to return
        NoSuchRevision if the revision_id is absent.
        """
        raise tests.TestNotApplicable()


class TestSmartServerBranchRequestSetLastRevisionEx(
    SetLastRevisionTestBase, TestSetLastRevisionVerbMixin
):
    """Tests for Branch.set_last_revision_ex verb."""

    request_class = smart_branch.SmartServerBranchRequestSetLastRevisionEx

    def _set_last_revision(self, revision_id, revno, branch_token, repo_token):
        return self.request.execute(b"", branch_token, repo_token, revision_id, 0, 0)

    def assertRequestSucceeds(self, revision_id, revno):
        response = self.set_last_revision(revision_id, revno)
        self.assertEqual(
            smart_req.SuccessfulSmartServerResponse((b"ok", revno, revision_id)),
            response,
        )

    def test_branch_last_revision_info_rewind(self):
        """A branch's tip can be set to a revision that is an ancestor of the
        current tip, but only if allow_overwrite_descendant is passed.
        """
        self.make_tree_with_two_commits()
        rev_id_utf8 = "\xc8".encode()
        self.assertEqual((2, b"rev-2"), self.tree.branch.last_revision_info())
        # If allow_overwrite_descendant flag is 0, then trying to set the tip
        # to an older revision ID has no effect.
        branch_token, repo_token = self.lock_branch()
        response = self.request.execute(
            b"", branch_token, repo_token, rev_id_utf8, 0, 0
        )
        self.assertEqual(
            smart_req.SuccessfulSmartServerResponse((b"ok", 2, b"rev-2")), response
        )
        self.assertEqual((2, b"rev-2"), self.tree.branch.last_revision_info())

        # If allow_overwrite_descendant flag is 1, then setting the tip to an
        # ancestor works.
        response = self.request.execute(
            b"", branch_token, repo_token, rev_id_utf8, 0, 1
        )
        self.assertEqual(
            smart_req.SuccessfulSmartServerResponse((b"ok", 1, rev_id_utf8)), response
        )
        self.unlock_branch()
        self.assertEqual((1, rev_id_utf8), self.tree.branch.last_revision_info())

    def make_branch_with_divergent_history(self):
        """Make a branch with divergent history in its repo.

        The branch's tip will be 'child-2', and the repo will also contain
        'child-1', which diverges from a common base revision.
        """
        self.tree.lock_write()
        self.tree.add("")
        self.tree.commit("1st commit")
        revno_1, revid_1 = self.tree.branch.last_revision_info()
        self.tree.commit("2nd commit", rev_id=b"child-1")
        # Undo the second commit
        self.tree.branch.set_last_revision_info(revno_1, revid_1)
        self.tree.set_parent_ids([revid_1])
        # Make a new second commit, child-2.  child-2 has diverged from
        # child-1.
        self.tree.commit("2nd commit", rev_id=b"child-2")
        self.tree.unlock()

    def test_not_allow_diverged(self):
        """If allow_diverged is not passed, then setting a divergent history
        returns a Diverged error.
        """
        self.make_branch_with_divergent_history()
        self.assertEqual(
            smart_req.FailedSmartServerResponse((b"Diverged",)),
            self.set_last_revision(b"child-1", 2),
        )
        # The branch tip was not changed.
        self.assertEqual(b"child-2", self.tree.branch.last_revision())

    def test_allow_diverged(self):
        """If allow_diverged is passed, then setting a divergent history
        succeeds.
        """
        self.make_branch_with_divergent_history()
        branch_token, repo_token = self.lock_branch()
        response = self.request.execute(b"", branch_token, repo_token, b"child-1", 1, 0)
        self.assertEqual(
            smart_req.SuccessfulSmartServerResponse((b"ok", 2, b"child-1")), response
        )
        self.unlock_branch()
        # The branch tip was changed.
        self.assertEqual(b"child-1", self.tree.branch.last_revision())


class TestSmartServerBranchBreakLock(tests.TestCaseWithMemoryTransport):
    def test_lock_to_break(self):
        base_branch = self.make_branch("base")
        request = smart_branch.SmartServerBranchBreakLock(self.get_transport())
        base_branch.lock_write()
        self.assertEqual(
            smart_req.SuccessfulSmartServerResponse((b"ok",), None),
            request.execute(b"base"),
        )

    def test_nothing_to_break(self):
        self.make_branch("base")
        request = smart_branch.SmartServerBranchBreakLock(self.get_transport())
        self.assertEqual(
            smart_req.SuccessfulSmartServerResponse((b"ok",), None),
            request.execute(b"base"),
        )


class TestSmartServerBranchRequestGetParent(tests.TestCaseWithMemoryTransport):
    def test_get_parent_none(self):
        self.make_branch("base")
        request = smart_branch.SmartServerBranchGetParent(self.get_transport())
        response = request.execute(b"base")
        self.assertEqual(smart_req.SuccessfulSmartServerResponse((b"",)), response)

    def test_get_parent_something(self):
        base_branch = self.make_branch("base")
        base_branch.set_parent(self.get_url("foo"))
        request = smart_branch.SmartServerBranchGetParent(self.get_transport())
        response = request.execute(b"base")
        self.assertEqual(
            smart_req.SuccessfulSmartServerResponse((b"../foo",)), response
        )


class TestSmartServerBranchRequestSetParent(TestLockedBranch):
    def test_set_parent_none(self):
        branch = self.make_branch("base", format="1.9")
        branch.lock_write()
        branch._set_parent_location("foo")
        branch.unlock()
        request = smart_branch.SmartServerBranchRequestSetParentLocation(
            self.get_transport()
        )
        branch_token, repo_token = self.get_lock_tokens(branch)
        try:
            response = request.execute(b"base", branch_token, repo_token, b"")
        finally:
            branch.unlock()
        self.assertEqual(smart_req.SuccessfulSmartServerResponse(()), response)
        # Refresh branch as SetParentLocation modified it
        branch = branch.controldir.open_branch()
        self.assertEqual(None, branch.get_parent())

    def test_set_parent_something(self):
        branch = self.make_branch("base", format="1.9")
        request = smart_branch.SmartServerBranchRequestSetParentLocation(
            self.get_transport()
        )
        branch_token, repo_token = self.get_lock_tokens(branch)
        try:
            response = request.execute(
                b"base", branch_token, repo_token, b"http://bar/"
            )
        finally:
            branch.unlock()
        self.assertEqual(smart_req.SuccessfulSmartServerResponse(()), response)
        refreshed = _mod_branch.Branch.open(branch.base)
        self.assertEqual("http://bar/", refreshed.get_parent())


class TestSmartServerBranchRequestGetTagsBytes(tests.TestCaseWithMemoryTransport):
    # Only called when the branch format and tags match [yay factory
    # methods] so only need to test straight forward cases.

    def test_get_bytes(self):
        self.make_branch("base")
        request = smart_branch.SmartServerBranchGetTagsBytes(self.get_transport())
        response = request.execute(b"base")
        self.assertEqual(smart_req.SuccessfulSmartServerResponse((b"",)), response)


class TestSmartServerBranchRequestGetStackedOnURL(tests.TestCaseWithMemoryTransport):
    def test_get_stacked_on_url(self):
        self.make_branch("base", format="1.6")
        stacked_branch = self.make_branch("stacked", format="1.6")
        # typically should be relative
        stacked_branch.set_stacked_on_url("../base")
        request = smart_branch.SmartServerBranchRequestGetStackedOnURL(
            self.get_transport()
        )
        response = request.execute(b"stacked")
        self.assertEqual(smart_req.SmartServerResponse((b"ok", b"../base")), response)


class TestSmartServerBranchRequestLockWrite(TestLockedBranch):
    def test_lock_write_on_unlocked_branch(self):
        backing = self.get_transport()
        request = smart_branch.SmartServerBranchRequestLockWrite(backing)
        branch = self.make_branch(".", format="knit")
        repository = branch.repository
        response = request.execute(b"")
        branch_nonce = branch.control_files._lock.peek().nonce
        repository_nonce = repository.control_files._lock.peek().nonce
        self.assertEqual(
            smart_req.SmartServerResponse((b"ok", branch_nonce, repository_nonce)),
            response,
        )
        # The branch (and associated repository) is now locked.  Verify that
        # with a new branch object.
        new_branch = repository.controldir.open_branch()
        self.assertRaises(errors.LockContention, new_branch.lock_write)
        # Cleanup
        request = smart_branch.SmartServerBranchRequestUnlock(backing)
        response = request.execute(b"", branch_nonce, repository_nonce)

    def test_lock_write_on_locked_branch(self):
        backing = self.get_transport()
        request = smart_branch.SmartServerBranchRequestLockWrite(backing)
        branch = self.make_branch(".")
        branch_token = branch.lock_write().token
        branch.leave_lock_in_place()
        branch.unlock()
        response = request.execute(b"")
        self.assertEqual(smart_req.SmartServerResponse((b"LockContention",)), response)
        # Cleanup
        branch.lock_write(branch_token)
        branch.dont_leave_lock_in_place()
        branch.unlock()

    def test_lock_write_with_tokens_on_locked_branch(self):
        backing = self.get_transport()
        request = smart_branch.SmartServerBranchRequestLockWrite(backing)
        branch = self.make_branch(".", format="knit")
        branch_token, repo_token = self.get_lock_tokens(branch)
        branch.leave_lock_in_place()
        branch.repository.leave_lock_in_place()
        branch.unlock()
        response = request.execute(b"", branch_token, repo_token)
        self.assertEqual(
            smart_req.SmartServerResponse((b"ok", branch_token, repo_token)), response
        )
        # Cleanup
        branch.repository.lock_write(repo_token)
        branch.repository.dont_leave_lock_in_place()
        branch.repository.unlock()
        branch.lock_write(branch_token)
        branch.dont_leave_lock_in_place()
        branch.unlock()

    def test_lock_write_with_mismatched_tokens_on_locked_branch(self):
        backing = self.get_transport()
        request = smart_branch.SmartServerBranchRequestLockWrite(backing)
        branch = self.make_branch(".", format="knit")
        branch_token, repo_token = self.get_lock_tokens(branch)
        branch.leave_lock_in_place()
        branch.repository.leave_lock_in_place()
        branch.unlock()
        response = request.execute(b"", branch_token + b"xxx", repo_token)
        self.assertEqual(smart_req.SmartServerResponse((b"TokenMismatch",)), response)
        # Cleanup
        branch.repository.lock_write(repo_token)
        branch.repository.dont_leave_lock_in_place()
        branch.repository.unlock()
        branch.lock_write(branch_token)
        branch.dont_leave_lock_in_place()
        branch.unlock()

    def test_lock_write_on_locked_repo(self):
        backing = self.get_transport()
        request = smart_branch.SmartServerBranchRequestLockWrite(backing)
        branch = self.make_branch(".", format="knit")
        repo = branch.repository
        repo_token = repo.lock_write().repository_token
        repo.leave_lock_in_place()
        repo.unlock()
        response = request.execute(b"")
        self.assertEqual(smart_req.SmartServerResponse((b"LockContention",)), response)
        # Cleanup
        repo.lock_write(repo_token)
        repo.dont_leave_lock_in_place()
        repo.unlock()

    def test_lock_write_on_readonly_transport(self):
        backing = self.get_readonly_transport()
        request = smart_branch.SmartServerBranchRequestLockWrite(backing)
        self.make_branch(".")
        root = self.get_transport().clone("/")
        path = urlutils.relative_url(root.base, self.get_transport().base)
        response = request.execute(path.encode("utf-8"))
        error_name, lock_str, why_str = response.args
        self.assertFalse(response.is_successful())
        self.assertEqual(b"LockFailed", error_name)


class TestSmartServerBranchRequestGetPhysicalLockStatus(TestLockedBranch):
    def test_true(self):
        backing = self.get_transport()
        request = smart_branch.SmartServerBranchRequestGetPhysicalLockStatus(backing)
        branch = self.make_branch(".")
        branch_token, repo_token = self.get_lock_tokens(branch)
        self.assertEqual(True, branch.get_physical_lock_status())
        response = request.execute(b"")
        self.assertEqual(smart_req.SmartServerResponse((b"yes",)), response)
        branch.unlock()

    def test_false(self):
        backing = self.get_transport()
        request = smart_branch.SmartServerBranchRequestGetPhysicalLockStatus(backing)
        branch = self.make_branch(".")
        self.assertEqual(False, branch.get_physical_lock_status())
        response = request.execute(b"")
        self.assertEqual(smart_req.SmartServerResponse((b"no",)), response)


class TestSmartServerBranchRequestUnlock(TestLockedBranch):
    def test_unlock_on_locked_branch_and_repo(self):
        backing = self.get_transport()
        request = smart_branch.SmartServerBranchRequestUnlock(backing)
        branch = self.make_branch(".", format="knit")
        # Lock the branch
        branch_token, repo_token = self.get_lock_tokens(branch)
        # Unlock the branch (and repo) object, leaving the physical locks
        # in place.
        branch.leave_lock_in_place()
        branch.repository.leave_lock_in_place()
        branch.unlock()
        response = request.execute(b"", branch_token, repo_token)
        self.assertEqual(smart_req.SmartServerResponse((b"ok",)), response)
        # The branch is now unlocked.  Verify that with a new branch
        # object.
        new_branch = branch.controldir.open_branch()
        new_branch.lock_write()
        new_branch.unlock()

    def test_unlock_on_unlocked_branch_unlocked_repo(self):
        backing = self.get_transport()
        request = smart_branch.SmartServerBranchRequestUnlock(backing)
        self.make_branch(".", format="knit")
        response = request.execute(b"", b"branch token", b"repo token")
        self.assertEqual(smart_req.SmartServerResponse((b"TokenMismatch",)), response)

    def test_unlock_on_unlocked_branch_locked_repo(self):
        backing = self.get_transport()
        request = smart_branch.SmartServerBranchRequestUnlock(backing)
        branch = self.make_branch(".", format="knit")
        # Lock the repository.
        repo_token = branch.repository.lock_write().repository_token
        branch.repository.leave_lock_in_place()
        branch.repository.unlock()
        # Issue branch lock_write request on the unlocked branch (with locked
        # repo).
        response = request.execute(b"", b"branch token", repo_token)
        self.assertEqual(smart_req.SmartServerResponse((b"TokenMismatch",)), response)
        # Cleanup
        branch.repository.lock_write(repo_token)
        branch.repository.dont_leave_lock_in_place()
        branch.repository.unlock()


class TestSmartServerRepositoryRequest(tests.TestCaseWithMemoryTransport):
    def test_no_repository(self):
        """Raise NoRepositoryPresent when there is a bzrdir and no repo."""
        # we test this using a shared repository above the named path,
        # thus checking the right search logic is used - that is, that
        # its the exact path being looked at and the server is not
        # searching.
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryRequest(backing)
        self.make_repository(".", shared=True)
        self.make_controldir("subdir")
        self.assertRaises(errors.NoRepositoryPresent, request.execute, b"subdir")


class TestSmartServerRepositoryAddSignatureText(tests.TestCaseWithMemoryTransport):
    def test_add_text(self):
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryAddSignatureText(backing)
        tree = self.make_branch_and_memory_tree(".")
        write_token = tree.lock_write()
        self.addCleanup(tree.unlock)
        tree.add("")
        tree.commit("Message", rev_id=b"rev1")
        tree.branch.repository.start_write_group()
        write_group_tokens = tree.branch.repository.suspend_write_group()
        self.assertEqual(
            None,
            request.execute(
                b"",
                write_token,
                b"rev1",
                *[token.encode("utf-8") for token in write_group_tokens],
            ),
        )
        response = request.do_body(b"somesignature")
        self.assertTrue(response.is_successful())
        self.assertEqual(response.args[0], b"ok")
        write_group_tokens = [token.decode("utf-8") for token in response.args[1:]]
        tree.branch.repository.resume_write_group(write_group_tokens)
        tree.branch.repository.commit_write_group()
        tree.unlock()
        self.assertEqual(
            b"somesignature", tree.branch.repository.get_signature_text(b"rev1")
        )


class TestSmartServerRepositoryAllRevisionIds(tests.TestCaseWithMemoryTransport):
    def test_empty(self):
        """An empty body should be returned for an empty repository."""
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryAllRevisionIds(backing)
        self.make_repository(".")
        self.assertEqual(
            smart_req.SuccessfulSmartServerResponse((b"ok",), b""), request.execute(b"")
        )

    def test_some_revisions(self):
        """An empty body should be returned for an empty repository."""
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryAllRevisionIds(backing)
        tree = self.make_branch_and_memory_tree(".")
        tree.lock_write()
        tree.add("")
        tree.commit(rev_id=b"origineel", message="message")
        tree.commit(rev_id=b"nog-een-revisie", message="message")
        tree.unlock()
        self.assertIn(
            request.execute(b""),
            [
                smart_req.SuccessfulSmartServerResponse(
                    (b"ok",), b"origineel\nnog-een-revisie"
                ),
                smart_req.SuccessfulSmartServerResponse(
                    (b"ok",), b"nog-een-revisie\norigineel"
                ),
            ],
        )


class TestSmartServerRepositoryBreakLock(tests.TestCaseWithMemoryTransport):
    def test_lock_to_break(self):
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryBreakLock(backing)
        tree = self.make_branch_and_memory_tree(".")
        tree.branch.repository.lock_write()
        self.assertEqual(
            smart_req.SuccessfulSmartServerResponse((b"ok",), None),
            request.execute(b""),
        )

    def test_nothing_to_break(self):
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryBreakLock(backing)
        self.make_branch_and_memory_tree(".")
        self.assertEqual(
            smart_req.SuccessfulSmartServerResponse((b"ok",), None),
            request.execute(b""),
        )


class TestSmartServerRepositoryGetParentMap(tests.TestCaseWithMemoryTransport):
    def test_trivial_bzipped(self):
        # This tests that the wire encoding is actually bzipped
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryGetParentMap(backing)
        self.make_branch_and_memory_tree(".")

        self.assertEqual(None, request.execute(b"", b"missing-id"))
        # Note that it returns a body that is bzipped.
        self.assertEqual(
            smart_req.SuccessfulSmartServerResponse((b"ok",), bz2.compress(b"")),
            request.do_body(b"\n\n0\n"),
        )

    def test_trivial_include_missing(self):
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryGetParentMap(backing)
        self.make_branch_and_memory_tree(".")

        self.assertEqual(None, request.execute(b"", b"missing-id", b"include-missing:"))
        self.assertEqual(
            smart_req.SuccessfulSmartServerResponse(
                (b"ok",), bz2.compress(b"missing:missing-id")
            ),
            request.do_body(b"\n\n0\n"),
        )


class TestSmartServerRepositoryGetRevisionGraph(tests.TestCaseWithMemoryTransport):
    def test_none_argument(self):
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryGetRevisionGraph(backing)
        tree = self.make_branch_and_memory_tree(".")
        tree.lock_write()
        tree.add("")
        r1 = tree.commit("1st commit")
        r2 = tree.commit("2nd commit", rev_id="\xc8".encode())
        tree.unlock()

        # the lines of revision_id->revision_parent_list has no guaranteed
        # order coming out of a dict, so sort both our test and response
        lines = sorted([b" ".join([r2, r1]), r1])
        response = request.execute(b"", b"")
        response.body = b"\n".join(sorted(response.body.split(b"\n")))

        self.assertEqual(
            smart_req.SmartServerResponse((b"ok",), b"\n".join(lines)), response
        )

    def test_specific_revision_argument(self):
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryGetRevisionGraph(backing)
        tree = self.make_branch_and_memory_tree(".")
        tree.lock_write()
        tree.add("")
        rev_id_utf8 = "\xc9".encode()
        tree.commit("1st commit", rev_id=rev_id_utf8)
        tree.commit("2nd commit", rev_id="\xc8".encode())
        tree.unlock()

        self.assertEqual(
            smart_req.SmartServerResponse((b"ok",), rev_id_utf8),
            request.execute(b"", rev_id_utf8),
        )

    def test_no_such_revision(self):
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryGetRevisionGraph(backing)
        tree = self.make_branch_and_memory_tree(".")
        tree.lock_write()
        tree.add("")
        tree.commit("1st commit")
        tree.unlock()

        # Note that it still returns body (of zero bytes).
        self.assertEqual(
            smart_req.SmartServerResponse(
                (
                    b"nosuchrevision",
                    b"missingrevision",
                ),
                b"",
            ),
            request.execute(b"", b"missingrevision"),
        )


class TestSmartServerRepositoryGetRevIdForRevno(tests.TestCaseWithMemoryTransport):
    def test_revno_found(self):
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryGetRevIdForRevno(backing)
        tree = self.make_branch_and_memory_tree(".")
        tree.lock_write()
        tree.add("")
        rev1_id_utf8 = "\xc8".encode()
        rev2_id_utf8 = "\xc9".encode()
        tree.commit("1st commit", rev_id=rev1_id_utf8)
        tree.commit("2nd commit", rev_id=rev2_id_utf8)
        tree.unlock()

        self.assertEqual(
            smart_req.SmartServerResponse((b"ok", rev1_id_utf8)),
            request.execute(b"", 1, (2, rev2_id_utf8)),
        )

    def test_known_revid_missing(self):
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryGetRevIdForRevno(backing)
        self.make_repository(".")
        self.assertEqual(
            smart_req.FailedSmartServerResponse((b"nosuchrevision", b"ghost")),
            request.execute(b"", 1, (2, b"ghost")),
        )

    def test_history_incomplete(self):
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryGetRevIdForRevno(backing)
        parent = self.make_branch_and_memory_tree("parent", format="1.9")
        parent.lock_write()
        parent.add([""], ids=[b"TREE_ROOT"])
        parent.commit(message="first commit")
        r2 = parent.commit(message="second commit")
        parent.unlock()
        local = self.make_branch_and_memory_tree("local", format="1.9")
        local.branch.pull(parent.branch)
        local.set_parent_ids([r2])
        r3 = local.commit(message="local commit")
        local.branch.create_clone_on_transport(
            self.get_transport("stacked"), stacked_on=self.get_url("parent")
        )
        self.assertEqual(
            smart_req.SmartServerResponse((b"history-incomplete", 2, r2)),
            request.execute(b"stacked", 1, (3, r3)),
        )


class TestSmartServerRepositoryIterRevisions(tests.TestCaseWithMemoryTransport):
    def test_basic(self):
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryIterRevisions(backing)
        tree = self.make_branch_and_memory_tree(".", format="2a")
        tree.lock_write()
        tree.add("")
        tree.commit("1st commit", rev_id=b"rev1")
        tree.commit("2nd commit", rev_id=b"rev2")
        tree.unlock()

        self.assertIs(None, request.execute(b""))
        response = request.do_body(b"rev1\nrev2")
        self.assertTrue(response.is_successful())
        # Format 2a uses serializer format 10
        self.assertEqual(response.args, (b"ok", b"10"))

        self.addCleanup(tree.branch.lock_read().unlock)
        entries = [
            zlib.compress(record.get_bytes_as("fulltext"))
            for record in tree.branch.repository.revisions.get_record_stream(
                [(b"rev1",), (b"rev2",)], "unordered", True
            )
        ]

        contents = b"".join(response.body_stream)
        self.assertTrue(
            contents
            in (b"".join([entries[0], entries[1]]), b"".join([entries[1], entries[0]]))
        )

    def test_missing(self):
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryIterRevisions(backing)
        self.make_branch_and_memory_tree(".", format="2a")

        self.assertIs(None, request.execute(b""))
        response = request.do_body(b"rev1\nrev2")
        self.assertTrue(response.is_successful())
        # Format 2a uses serializer format 10
        self.assertEqual(response.args, (b"ok", b"10"))

        contents = b"".join(response.body_stream)
        self.assertEqual(contents, b"")


class GetStreamTestBase(tests.TestCaseWithMemoryTransport):
    def make_two_commit_repo(self):
        tree = self.make_branch_and_memory_tree(".")
        tree.lock_write()
        tree.add("")
        r1 = tree.commit("1st commit")
        r2 = tree.commit("2nd commit", rev_id="\xc8".encode())
        tree.unlock()
        repo = tree.branch.repository
        return repo, r1, r2


class TestSmartServerRepositoryGetStream(GetStreamTestBase):
    def test_ancestry_of(self):
        """The search argument may be a 'ancestry-of' some heads'."""
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryGetStream(backing)
        repo, r1, r2 = self.make_two_commit_repo()
        fetch_spec = [b"ancestry-of", r2]
        lines = b"\n".join(fetch_spec)
        request.execute(b"", repo._format.network_name())
        response = request.do_body(lines)
        self.assertEqual((b"ok",), response.args)
        stream_bytes = b"".join(response.body_stream)
        self.assertStartsWith(stream_bytes, b"Bazaar pack format 1")

    def test_search(self):
        """The search argument may be a 'search' of some explicit keys."""
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryGetStream(backing)
        repo, r1, r2 = self.make_two_commit_repo()
        fetch_spec = [b"search", r1 + b" " + r2, b"null:", b"2"]
        lines = b"\n".join(fetch_spec)
        request.execute(b"", repo._format.network_name())
        response = request.do_body(lines)
        self.assertEqual((b"ok",), response.args)
        stream_bytes = b"".join(response.body_stream)
        self.assertStartsWith(stream_bytes, b"Bazaar pack format 1")

    def test_search_everything(self):
        """A search of 'everything' returns a stream."""
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryGetStream_1_19(backing)
        repo, r1, r2 = self.make_two_commit_repo()
        serialised_fetch_spec = b"everything"
        request.execute(b"", repo._format.network_name())
        response = request.do_body(serialised_fetch_spec)
        self.assertEqual((b"ok",), response.args)
        stream_bytes = b"".join(response.body_stream)
        self.assertStartsWith(stream_bytes, b"Bazaar pack format 1")


class TestSmartServerRequestHasRevision(tests.TestCaseWithMemoryTransport):
    def test_missing_revision(self):
        """For a missing revision, ('no', ) is returned."""
        backing = self.get_transport()
        request = smart_repo.SmartServerRequestHasRevision(backing)
        self.make_repository(".")
        self.assertEqual(
            smart_req.SmartServerResponse((b"no",)), request.execute(b"", b"revid")
        )

    def test_present_revision(self):
        """For a present revision, ('yes', ) is returned."""
        backing = self.get_transport()
        request = smart_repo.SmartServerRequestHasRevision(backing)
        tree = self.make_branch_and_memory_tree(".")
        tree.lock_write()
        tree.add("")
        rev_id_utf8 = "\xc8abc".encode()
        tree.commit("a commit", rev_id=rev_id_utf8)
        tree.unlock()
        self.assertTrue(tree.branch.repository.has_revision(rev_id_utf8))
        self.assertEqual(
            smart_req.SmartServerResponse((b"yes",)), request.execute(b"", rev_id_utf8)
        )


class TestSmartServerRepositoryIterFilesBytes(tests.TestCaseWithTransport):
    def test_single(self):
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryIterFilesBytes(backing)
        t = self.make_branch_and_tree(".")
        self.addCleanup(t.lock_write().unlock)
        self.build_tree_contents([("file", b"somecontents")])
        t.add(["file"], ids=[b"thefileid"])
        t.commit(rev_id=b"somerev", message="add file")
        self.assertIs(None, request.execute(b""))
        response = request.do_body(b"thefileid\0somerev\n")
        self.assertTrue(response.is_successful())
        self.assertEqual(response.args, (b"ok",))
        self.assertEqual(
            b"".join(response.body_stream),
            b"ok\x000\n" + zlib.compress(b"somecontents"),
        )

    def test_missing(self):
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryIterFilesBytes(backing)
        t = self.make_branch_and_tree(".")
        self.addCleanup(t.lock_write().unlock)
        self.assertIs(None, request.execute(b""))
        response = request.do_body(b"thefileid\0revision\n")
        self.assertTrue(response.is_successful())
        self.assertEqual(response.args, (b"ok",))
        self.assertEqual(
            b"".join(response.body_stream), b"absent\x00thefileid\x00revision\x000\n"
        )


class TestSmartServerRequestHasSignatureForRevisionId(
    tests.TestCaseWithMemoryTransport
):
    def test_missing_revision(self):
        """For a missing revision, NoSuchRevision is returned."""
        backing = self.get_transport()
        request = smart_repo.SmartServerRequestHasSignatureForRevisionId(backing)
        self.make_repository(".")
        self.assertEqual(
            smart_req.FailedSmartServerResponse((b"nosuchrevision", b"revid"), None),
            request.execute(b"", b"revid"),
        )

    def test_missing_signature(self):
        """For a missing signature, ('no', ) is returned."""
        backing = self.get_transport()
        request = smart_repo.SmartServerRequestHasSignatureForRevisionId(backing)
        tree = self.make_branch_and_memory_tree(".")
        tree.lock_write()
        tree.add("")
        tree.commit("a commit", rev_id=b"A")
        tree.unlock()
        self.assertTrue(tree.branch.repository.has_revision(b"A"))
        self.assertEqual(
            smart_req.SmartServerResponse((b"no",)), request.execute(b"", b"A")
        )

    def test_present_signature(self):
        """For a present signature, ('yes', ) is returned."""
        backing = self.get_transport()
        request = smart_repo.SmartServerRequestHasSignatureForRevisionId(backing)
        strategy = gpg.LoopbackGPGStrategy(None)
        tree = self.make_branch_and_memory_tree(".")
        tree.lock_write()
        tree.add("")
        tree.commit("a commit", rev_id=b"A")
        tree.branch.repository.start_write_group()
        tree.branch.repository.sign_revision(b"A", strategy)
        tree.branch.repository.commit_write_group()
        tree.unlock()
        self.assertTrue(tree.branch.repository.has_revision(b"A"))
        self.assertEqual(
            smart_req.SmartServerResponse((b"yes",)), request.execute(b"", b"A")
        )


class TestSmartServerRepositoryGatherStats(tests.TestCaseWithMemoryTransport):
    def test_empty_revid(self):
        """With an empty revid, we get only size an number and revisions."""
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryGatherStats(backing)
        repository = self.make_repository(".")
        repository.gather_stats()
        expected_body = b"revisions: 0\n"
        self.assertEqual(
            smart_req.SmartServerResponse((b"ok",), expected_body),
            request.execute(b"", b"", b"no"),
        )

    def test_revid_with_committers(self):
        """For a revid we get more infos."""
        backing = self.get_transport()
        rev_id_utf8 = "\xc8abc".encode()
        request = smart_repo.SmartServerRepositoryGatherStats(backing)
        tree = self.make_branch_and_memory_tree(".")
        tree.lock_write()
        tree.add("")
        # Let's build a predictable result
        tree.commit("a commit", timestamp=123456.2, timezone=3600)
        tree.commit("a commit", timestamp=654321.4, timezone=0, rev_id=rev_id_utf8)
        tree.unlock()

        tree.branch.repository.gather_stats()
        expected_body = (
            b"firstrev: 123456.200 3600\nlatestrev: 654321.400 0\nrevisions: 2\n"
        )
        self.assertEqual(
            smart_req.SmartServerResponse((b"ok",), expected_body),
            request.execute(b"", rev_id_utf8, b"no"),
        )

    def test_not_empty_repository_with_committers(self):
        """For a revid and requesting committers we get the whole thing."""
        backing = self.get_transport()
        rev_id_utf8 = "\xc8abc".encode()
        request = smart_repo.SmartServerRepositoryGatherStats(backing)
        tree = self.make_branch_and_memory_tree(".")
        tree.lock_write()
        tree.add("")
        # Let's build a predictable result
        tree.commit("a commit", timestamp=123456.2, timezone=3600, committer="foo")
        tree.commit(
            "a commit",
            timestamp=654321.4,
            timezone=0,
            committer="bar",
            rev_id=rev_id_utf8,
        )
        tree.unlock()
        tree.branch.repository.gather_stats()

        expected_body = (
            b"committers: 2\n"
            b"firstrev: 123456.200 3600\n"
            b"latestrev: 654321.400 0\n"
            b"revisions: 2\n"
        )
        self.assertEqual(
            smart_req.SmartServerResponse((b"ok",), expected_body),
            request.execute(b"", rev_id_utf8, b"yes"),
        )

    def test_unknown_revid(self):
        """An unknown revision id causes a 'nosuchrevision' error."""
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryGatherStats(backing)
        self.make_repository(".")
        self.assertEqual(
            smart_req.FailedSmartServerResponse((b"nosuchrevision", b"mia"), None),
            request.execute(b"", b"mia", b"yes"),
        )


class TestSmartServerRepositoryIsShared(tests.TestCaseWithMemoryTransport):
    def test_is_shared(self):
        """For a shared repository, ('yes', ) is returned."""
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryIsShared(backing)
        self.make_repository(".", shared=True)
        self.assertEqual(
            smart_req.SmartServerResponse((b"yes",)),
            request.execute(
                b"",
            ),
        )

    def test_is_not_shared(self):
        """For a shared repository, ('no', ) is returned."""
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryIsShared(backing)
        self.make_repository(".", shared=False)
        self.assertEqual(
            smart_req.SmartServerResponse((b"no",)),
            request.execute(
                b"",
            ),
        )


class TestSmartServerRepositoryGetRevisionSignatureText(
    tests.TestCaseWithMemoryTransport
):
    def test_get_signature(self):
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryGetRevisionSignatureText(backing)
        bb = self.make_branch_builder(".")
        bb.build_commit(rev_id=b"A")
        repo = bb.get_branch().repository
        strategy = gpg.LoopbackGPGStrategy(None)
        self.addCleanup(repo.lock_write().unlock)
        repo.start_write_group()
        repo.sign_revision(b"A", strategy)
        repo.commit_write_group()
        expected_body = (
            b"-----BEGIN PSEUDO-SIGNED CONTENT-----\n"
            + Testament.from_revision(repo, b"A").as_short_text()
            + b"-----END PSEUDO-SIGNED CONTENT-----\n"
        )
        self.assertEqual(
            smart_req.SmartServerResponse((b"ok",), expected_body),
            request.execute(b"", b"A"),
        )


class TestSmartServerRepositoryMakeWorkingTrees(tests.TestCaseWithMemoryTransport):
    def test_make_working_trees(self):
        """For a repository with working trees, ('yes', ) is returned."""
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryMakeWorkingTrees(backing)
        r = self.make_repository(".")
        r.set_make_working_trees(True)
        self.assertEqual(
            smart_req.SmartServerResponse((b"yes",)),
            request.execute(
                b"",
            ),
        )

    def test_is_not_shared(self):
        """For a repository with working trees, ('no', ) is returned."""
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryMakeWorkingTrees(backing)
        r = self.make_repository(".")
        r.set_make_working_trees(False)
        self.assertEqual(
            smart_req.SmartServerResponse((b"no",)),
            request.execute(
                b"",
            ),
        )


class TestSmartServerRepositoryLockWrite(tests.TestCaseWithMemoryTransport):
    def test_lock_write_on_unlocked_repo(self):
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryLockWrite(backing)
        repository = self.make_repository(".", format="knit")
        response = request.execute(b"")
        nonce = repository.control_files._lock.peek().nonce
        self.assertEqual(smart_req.SmartServerResponse((b"ok", nonce)), response)
        # The repository is now locked.  Verify that with a new repository
        # object.
        new_repo = repository.controldir.open_repository()
        self.assertRaises(errors.LockContention, new_repo.lock_write)
        # Cleanup
        request = smart_repo.SmartServerRepositoryUnlock(backing)
        response = request.execute(b"", nonce)

    def test_lock_write_on_locked_repo(self):
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryLockWrite(backing)
        repository = self.make_repository(".", format="knit")
        repo_token = repository.lock_write().repository_token
        repository.leave_lock_in_place()
        repository.unlock()
        response = request.execute(b"")
        self.assertEqual(smart_req.SmartServerResponse((b"LockContention",)), response)
        # Cleanup
        repository.lock_write(repo_token)
        repository.dont_leave_lock_in_place()
        repository.unlock()

    def test_lock_write_on_readonly_transport(self):
        backing = self.get_readonly_transport()
        request = smart_repo.SmartServerRepositoryLockWrite(backing)
        self.make_repository(".", format="knit")
        response = request.execute(b"")
        self.assertFalse(response.is_successful())
        self.assertEqual(b"LockFailed", response.args[0])


class TestInsertStreamBase(tests.TestCaseWithMemoryTransport):
    def make_empty_byte_stream(self, repo):
        byte_stream = smart_repo._stream_to_byte_stream([], repo._format)
        return b"".join(byte_stream)


class TestSmartServerRepositoryInsertStream(TestInsertStreamBase):
    def test_insert_stream_empty(self):
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryInsertStream(backing)
        repository = self.make_repository(".")
        response = request.execute(b"", b"")
        self.assertEqual(None, response)
        response = request.do_chunk(self.make_empty_byte_stream(repository))
        self.assertEqual(None, response)
        response = request.do_end()
        self.assertEqual(smart_req.SmartServerResponse((b"ok",)), response)


class TestSmartServerRepositoryInsertStreamLocked(TestInsertStreamBase):
    def test_insert_stream_empty(self):
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryInsertStreamLocked(backing)
        repository = self.make_repository(".", format="knit")
        lock_token = repository.lock_write().repository_token
        response = request.execute(b"", b"", lock_token)
        self.assertEqual(None, response)
        response = request.do_chunk(self.make_empty_byte_stream(repository))
        self.assertEqual(None, response)
        response = request.do_end()
        self.assertEqual(smart_req.SmartServerResponse((b"ok",)), response)
        repository.unlock()

    def test_insert_stream_with_wrong_lock_token(self):
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryInsertStreamLocked(backing)
        repository = self.make_repository(".", format="knit")
        with repository.lock_write():
            self.assertRaises(
                errors.TokenMismatch, request.execute, b"", b"", b"wrong-token"
            )


class TestSmartServerRepositoryUnlock(tests.TestCaseWithMemoryTransport):
    def test_unlock_on_locked_repo(self):
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryUnlock(backing)
        repository = self.make_repository(".", format="knit")
        token = repository.lock_write().repository_token
        repository.leave_lock_in_place()
        repository.unlock()
        response = request.execute(b"", token)
        self.assertEqual(smart_req.SmartServerResponse((b"ok",)), response)
        # The repository is now unlocked.  Verify that with a new repository
        # object.
        new_repo = repository.controldir.open_repository()
        new_repo.lock_write()
        new_repo.unlock()

    def test_unlock_on_unlocked_repo(self):
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryUnlock(backing)
        self.make_repository(".", format="knit")
        response = request.execute(b"", b"some token")
        self.assertEqual(smart_req.SmartServerResponse((b"TokenMismatch",)), response)


class TestSmartServerRepositoryGetPhysicalLockStatus(tests.TestCaseWithTransport):
    def test_with_write_lock(self):
        backing = self.get_transport()
        repo = self.make_repository(".")
        self.addCleanup(repo.lock_write().unlock)
        # lock_write() doesn't necessarily actually take a physical
        # lock out.
        if repo.get_physical_lock_status():
            expected = b"yes"
        else:
            expected = b"no"
        request_class = smart_repo.SmartServerRepositoryGetPhysicalLockStatus
        request = request_class(backing)
        self.assertEqual(
            smart_req.SuccessfulSmartServerResponse((expected,)),
            request.execute(
                b"",
            ),
        )

    def test_without_write_lock(self):
        backing = self.get_transport()
        repo = self.make_repository(".")
        self.assertEqual(False, repo.get_physical_lock_status())
        request_class = smart_repo.SmartServerRepositoryGetPhysicalLockStatus
        request = request_class(backing)
        self.assertEqual(
            smart_req.SuccessfulSmartServerResponse((b"no",)),
            request.execute(
                b"",
            ),
        )


class TestSmartServerRepositoryReconcile(tests.TestCaseWithTransport):
    def test_reconcile(self):
        backing = self.get_transport()
        repo = self.make_repository(".")
        token = repo.lock_write().repository_token
        self.addCleanup(repo.unlock)
        request_class = smart_repo.SmartServerRepositoryReconcile
        request = request_class(backing)
        self.assertEqual(
            smart_req.SuccessfulSmartServerResponse(
                (b"ok",), b"garbage_inventories: 0\ninconsistent_parents: 0\n"
            ),
            request.execute(b"", token),
        )


class TestSmartServerIsReadonly(tests.TestCaseWithMemoryTransport):
    def test_is_readonly_no(self):
        backing = self.get_transport()
        request = smart_req.SmartServerIsReadonly(backing)
        response = request.execute()
        self.assertEqual(smart_req.SmartServerResponse((b"no",)), response)

    def test_is_readonly_yes(self):
        backing = self.get_readonly_transport()
        request = smart_req.SmartServerIsReadonly(backing)
        response = request.execute()
        self.assertEqual(smart_req.SmartServerResponse((b"yes",)), response)


class TestSmartServerRepositorySetMakeWorkingTrees(tests.TestCaseWithMemoryTransport):
    def test_set_false(self):
        backing = self.get_transport()
        repo = self.make_repository(".", shared=True)
        repo.set_make_working_trees(True)
        request_class = smart_repo.SmartServerRepositorySetMakeWorkingTrees
        request = request_class(backing)
        self.assertEqual(
            smart_req.SuccessfulSmartServerResponse((b"ok",)),
            request.execute(b"", b"False"),
        )
        repo = repo.controldir.open_repository()
        self.assertFalse(repo.make_working_trees())

    def test_set_true(self):
        backing = self.get_transport()
        repo = self.make_repository(".", shared=True)
        repo.set_make_working_trees(False)
        request_class = smart_repo.SmartServerRepositorySetMakeWorkingTrees
        request = request_class(backing)
        self.assertEqual(
            smart_req.SuccessfulSmartServerResponse((b"ok",)),
            request.execute(b"", b"True"),
        )
        repo = repo.controldir.open_repository()
        self.assertTrue(repo.make_working_trees())


class TestSmartServerRepositoryGetSerializerFormat(tests.TestCaseWithMemoryTransport):
    def test_get_serializer_format(self):
        backing = self.get_transport()
        self.make_repository(".", format="2a")
        request_class = smart_repo.SmartServerRepositoryGetSerializerFormat
        request = request_class(backing)
        self.assertEqual(
            smart_req.SuccessfulSmartServerResponse((b"ok", b"10")),
            request.execute(b""),
        )


class TestSmartServerRepositoryWriteGroup(tests.TestCaseWithMemoryTransport):
    def test_start_write_group(self):
        backing = self.get_transport()
        repo = self.make_repository(".")
        lock_token = repo.lock_write().repository_token
        self.addCleanup(repo.unlock)
        request_class = smart_repo.SmartServerRepositoryStartWriteGroup
        request = request_class(backing)
        self.assertEqual(
            smart_req.SuccessfulSmartServerResponse((b"ok", [])),
            request.execute(b"", lock_token),
        )

    def test_start_write_group_unsuspendable(self):
        backing = self.get_transport()
        repo = self.make_repository(".", format="knit")
        lock_token = repo.lock_write().repository_token
        self.addCleanup(repo.unlock)
        request_class = smart_repo.SmartServerRepositoryStartWriteGroup
        request = request_class(backing)
        self.assertEqual(
            smart_req.FailedSmartServerResponse((b"UnsuspendableWriteGroup",)),
            request.execute(b"", lock_token),
        )

    def test_commit_write_group(self):
        backing = self.get_transport()
        repo = self.make_repository(".")
        lock_token = repo.lock_write().repository_token
        self.addCleanup(repo.unlock)
        repo.start_write_group()
        tokens = repo.suspend_write_group()
        request_class = smart_repo.SmartServerRepositoryCommitWriteGroup
        request = request_class(backing)
        self.assertEqual(
            smart_req.SuccessfulSmartServerResponse((b"ok",)),
            request.execute(b"", lock_token, tokens),
        )

    def test_abort_write_group(self):
        backing = self.get_transport()
        repo = self.make_repository(".")
        lock_token = repo.lock_write().repository_token
        repo.start_write_group()
        tokens = repo.suspend_write_group()
        self.addCleanup(repo.unlock)
        request_class = smart_repo.SmartServerRepositoryAbortWriteGroup
        request = request_class(backing)
        self.assertEqual(
            smart_req.SuccessfulSmartServerResponse((b"ok",)),
            request.execute(b"", lock_token, tokens),
        )

    def test_check_write_group(self):
        backing = self.get_transport()
        repo = self.make_repository(".")
        lock_token = repo.lock_write().repository_token
        repo.start_write_group()
        tokens = repo.suspend_write_group()
        self.addCleanup(repo.unlock)
        request_class = smart_repo.SmartServerRepositoryCheckWriteGroup
        request = request_class(backing)
        self.assertEqual(
            smart_req.SuccessfulSmartServerResponse((b"ok",)),
            request.execute(b"", lock_token, tokens),
        )

    def test_check_write_group_invalid(self):
        backing = self.get_transport()
        repo = self.make_repository(".")
        lock_token = repo.lock_write().repository_token
        self.addCleanup(repo.unlock)
        request_class = smart_repo.SmartServerRepositoryCheckWriteGroup
        request = request_class(backing)
        self.assertEqual(
            smart_req.FailedSmartServerResponse(
                (b"UnresumableWriteGroup", [b"random"], b"Malformed write group token")
            ),
            request.execute(b"", lock_token, [b"random"]),
        )


class TestSmartServerPackRepositoryAutopack(tests.TestCaseWithTransport):
    def make_repo_needing_autopacking(self, path="."):
        # Make a repo in need of autopacking.
        tree = self.make_branch_and_tree(".", format="pack-0.92")
        repo = tree.branch.repository
        # monkey-patch the pack collection to disable autopacking
        repo._pack_collection._max_pack_count = lambda count: count
        for x in range(10):
            tree.commit("commit {}".format(x))
        self.assertEqual(10, len(repo._pack_collection.names()))
        del repo._pack_collection._max_pack_count
        return repo

    def test_autopack_needed(self):
        repo = self.make_repo_needing_autopacking()
        repo.lock_write()
        self.addCleanup(repo.unlock)
        backing = self.get_transport()
        request = smart_packrepo.SmartServerPackRepositoryAutopack(backing)
        response = request.execute(b"")
        self.assertEqual(smart_req.SmartServerResponse((b"ok",)), response)
        repo._pack_collection.reload_pack_names()
        self.assertEqual(1, len(repo._pack_collection.names()))

    def test_autopack_not_needed(self):
        tree = self.make_branch_and_tree(".", format="pack-0.92")
        repo = tree.branch.repository
        repo.lock_write()
        self.addCleanup(repo.unlock)
        for x in range(9):
            tree.commit("commit {}".format(x))
        backing = self.get_transport()
        request = smart_packrepo.SmartServerPackRepositoryAutopack(backing)
        response = request.execute(b"")
        self.assertEqual(smart_req.SmartServerResponse((b"ok",)), response)
        repo._pack_collection.reload_pack_names()
        self.assertEqual(9, len(repo._pack_collection.names()))

    def test_autopack_on_nonpack_format(self):
        """A request to autopack a non-pack repo is a no-op."""
        self.make_repository(".", format="knit")
        backing = self.get_transport()
        request = smart_packrepo.SmartServerPackRepositoryAutopack(backing)
        response = request.execute(b"")
        self.assertEqual(smart_req.SmartServerResponse((b"ok",)), response)


class TestSmartServerVfsGet(tests.TestCaseWithMemoryTransport):
    def test_unicode_path(self):
        """VFS requests expect unicode paths to be escaped."""
        filename = "foo\N{INTERROBANG}"
        filename_escaped = urlutils.escape(filename)
        backing = self.get_transport()
        request = vfs.GetRequest(backing)
        backing.put_bytes_non_atomic(filename_escaped, b"contents")
        self.assertEqual(
            smart_req.SmartServerResponse((b"ok",), b"contents"),
            request.execute(filename_escaped.encode("ascii")),
        )


class TestHandlers(tests.TestCase):
    """Tests for the request.request_handlers object."""

    def test_all_registrations_exist(self):
        """All registered request_handlers can be found."""
        # If there's a typo in a register_lazy call, this loop will fail with
        # an AttributeError.
        for key in smart_req.request_handlers.keys():
            try:
                smart_req.request_handlers.get(key)
            except AttributeError as e:
                raise AttributeError("failed to get {}: {}".format(key, e))

    def assertHandlerEqual(self, verb, handler):
        self.assertEqual(smart_req.request_handlers.get(verb), handler)

    def test_registered_methods(self):
        """Test that known methods are registered to the correct object."""
        self.assertHandlerEqual(
            b"Branch.break_lock", smart_branch.SmartServerBranchBreakLock
        )
        self.assertHandlerEqual(
            b"Branch.get_config_file", smart_branch.SmartServerBranchGetConfigFile
        )
        self.assertHandlerEqual(
            b"Branch.put_config_file", smart_branch.SmartServerBranchPutConfigFile
        )
        self.assertHandlerEqual(
            b"Branch.get_parent", smart_branch.SmartServerBranchGetParent
        )
        self.assertHandlerEqual(
            b"Branch.get_physical_lock_status",
            smart_branch.SmartServerBranchRequestGetPhysicalLockStatus,
        )
        self.assertHandlerEqual(
            b"Branch.get_tags_bytes", smart_branch.SmartServerBranchGetTagsBytes
        )
        self.assertHandlerEqual(
            b"Branch.lock_write", smart_branch.SmartServerBranchRequestLockWrite
        )
        self.assertHandlerEqual(
            b"Branch.last_revision_info",
            smart_branch.SmartServerBranchRequestLastRevisionInfo,
        )
        self.assertHandlerEqual(
            b"Branch.revision_history", smart_branch.SmartServerRequestRevisionHistory
        )
        self.assertHandlerEqual(
            b"Branch.revision_id_to_revno",
            smart_branch.SmartServerBranchRequestRevisionIdToRevno,
        )
        self.assertHandlerEqual(
            b"Branch.set_config_option",
            smart_branch.SmartServerBranchRequestSetConfigOption,
        )
        self.assertHandlerEqual(
            b"Branch.set_last_revision",
            smart_branch.SmartServerBranchRequestSetLastRevision,
        )
        self.assertHandlerEqual(
            b"Branch.set_last_revision_info",
            smart_branch.SmartServerBranchRequestSetLastRevisionInfo,
        )
        self.assertHandlerEqual(
            b"Branch.set_last_revision_ex",
            smart_branch.SmartServerBranchRequestSetLastRevisionEx,
        )
        self.assertHandlerEqual(
            b"Branch.set_parent_location",
            smart_branch.SmartServerBranchRequestSetParentLocation,
        )
        self.assertHandlerEqual(
            b"Branch.unlock", smart_branch.SmartServerBranchRequestUnlock
        )
        self.assertHandlerEqual(
            b"BzrDir.destroy_branch", smart_dir.SmartServerBzrDirRequestDestroyBranch
        )
        self.assertHandlerEqual(
            b"BzrDir.find_repository", smart_dir.SmartServerRequestFindRepositoryV1
        )
        self.assertHandlerEqual(
            b"BzrDir.find_repositoryV2", smart_dir.SmartServerRequestFindRepositoryV2
        )
        self.assertHandlerEqual(
            b"BzrDirFormat.initialize", smart_dir.SmartServerRequestInitializeBzrDir
        )
        self.assertHandlerEqual(
            b"BzrDirFormat.initialize_ex_1.16",
            smart_dir.SmartServerRequestBzrDirInitializeEx,
        )
        self.assertHandlerEqual(
            b"BzrDir.checkout_metadir",
            smart_dir.SmartServerBzrDirRequestCheckoutMetaDir,
        )
        self.assertHandlerEqual(
            b"BzrDir.cloning_metadir", smart_dir.SmartServerBzrDirRequestCloningMetaDir
        )
        self.assertHandlerEqual(
            b"BzrDir.get_branches", smart_dir.SmartServerBzrDirRequestGetBranches
        )
        self.assertHandlerEqual(
            b"BzrDir.get_config_file", smart_dir.SmartServerBzrDirRequestConfigFile
        )
        self.assertHandlerEqual(
            b"BzrDir.open_branch", smart_dir.SmartServerRequestOpenBranch
        )
        self.assertHandlerEqual(
            b"BzrDir.open_branchV2", smart_dir.SmartServerRequestOpenBranchV2
        )
        self.assertHandlerEqual(
            b"BzrDir.open_branchV3", smart_dir.SmartServerRequestOpenBranchV3
        )
        self.assertHandlerEqual(
            b"PackRepository.autopack", smart_packrepo.SmartServerPackRepositoryAutopack
        )
        self.assertHandlerEqual(
            b"Repository.add_signature_text",
            smart_repo.SmartServerRepositoryAddSignatureText,
        )
        self.assertHandlerEqual(
            b"Repository.all_revision_ids",
            smart_repo.SmartServerRepositoryAllRevisionIds,
        )
        self.assertHandlerEqual(
            b"Repository.break_lock", smart_repo.SmartServerRepositoryBreakLock
        )
        self.assertHandlerEqual(
            b"Repository.gather_stats", smart_repo.SmartServerRepositoryGatherStats
        )
        self.assertHandlerEqual(
            b"Repository.get_parent_map", smart_repo.SmartServerRepositoryGetParentMap
        )
        self.assertHandlerEqual(
            b"Repository.get_physical_lock_status",
            smart_repo.SmartServerRepositoryGetPhysicalLockStatus,
        )
        self.assertHandlerEqual(
            b"Repository.get_rev_id_for_revno",
            smart_repo.SmartServerRepositoryGetRevIdForRevno,
        )
        self.assertHandlerEqual(
            b"Repository.get_revision_graph",
            smart_repo.SmartServerRepositoryGetRevisionGraph,
        )
        self.assertHandlerEqual(
            b"Repository.get_revision_signature_text",
            smart_repo.SmartServerRepositoryGetRevisionSignatureText,
        )
        self.assertHandlerEqual(
            b"Repository.get_stream", smart_repo.SmartServerRepositoryGetStream
        )
        self.assertHandlerEqual(
            b"Repository.get_stream_1.19",
            smart_repo.SmartServerRepositoryGetStream_1_19,
        )
        self.assertHandlerEqual(
            b"Repository.iter_revisions", smart_repo.SmartServerRepositoryIterRevisions
        )
        self.assertHandlerEqual(
            b"Repository.has_revision", smart_repo.SmartServerRequestHasRevision
        )
        self.assertHandlerEqual(
            b"Repository.insert_stream", smart_repo.SmartServerRepositoryInsertStream
        )
        self.assertHandlerEqual(
            b"Repository.insert_stream_locked",
            smart_repo.SmartServerRepositoryInsertStreamLocked,
        )
        self.assertHandlerEqual(
            b"Repository.is_shared", smart_repo.SmartServerRepositoryIsShared
        )
        self.assertHandlerEqual(
            b"Repository.iter_files_bytes",
            smart_repo.SmartServerRepositoryIterFilesBytes,
        )
        self.assertHandlerEqual(
            b"Repository.lock_write", smart_repo.SmartServerRepositoryLockWrite
        )
        self.assertHandlerEqual(
            b"Repository.make_working_trees",
            smart_repo.SmartServerRepositoryMakeWorkingTrees,
        )
        self.assertHandlerEqual(
            b"Repository.pack", smart_repo.SmartServerRepositoryPack
        )
        self.assertHandlerEqual(
            b"Repository.reconcile", smart_repo.SmartServerRepositoryReconcile
        )
        self.assertHandlerEqual(
            b"Repository.tarball", smart_repo.SmartServerRepositoryTarball
        )
        self.assertHandlerEqual(
            b"Repository.unlock", smart_repo.SmartServerRepositoryUnlock
        )
        self.assertHandlerEqual(
            b"Repository.start_write_group",
            smart_repo.SmartServerRepositoryStartWriteGroup,
        )
        self.assertHandlerEqual(
            b"Repository.check_write_group",
            smart_repo.SmartServerRepositoryCheckWriteGroup,
        )
        self.assertHandlerEqual(
            b"Repository.commit_write_group",
            smart_repo.SmartServerRepositoryCommitWriteGroup,
        )
        self.assertHandlerEqual(
            b"Repository.abort_write_group",
            smart_repo.SmartServerRepositoryAbortWriteGroup,
        )
        self.assertHandlerEqual(
            b"VersionedFileRepository.get_serializer_format",
            smart_repo.SmartServerRepositoryGetSerializerFormat,
        )
        self.assertHandlerEqual(
            b"VersionedFileRepository.get_inventories",
            smart_repo.SmartServerRepositoryGetInventories,
        )
        self.assertHandlerEqual(
            b"Transport.is_readonly", smart_req.SmartServerIsReadonly
        )


class SmartTCPServerHookTests(tests.TestCaseWithMemoryTransport):
    """Tests for SmartTCPServer hooks."""

    def setUp(self):
        super().setUp()
        self.server = server.SmartTCPServer(self.get_transport())

    def test_run_server_started_hooks(self):
        """Test the server started hooks get fired properly."""
        started_calls = []
        server.SmartTCPServer.hooks.install_named_hook(
            "server_started",
            lambda backing_urls, url: started_calls.append((backing_urls, url)),
            None,
        )
        started_ex_calls = []
        server.SmartTCPServer.hooks.install_named_hook(
            "server_started_ex",
            lambda backing_urls, url: started_ex_calls.append((backing_urls, url)),
            None,
        )
        self.server._sockname = ("example.com", 42)
        self.server.run_server_started_hooks()
        self.assertEqual(
            started_calls, [([self.get_transport().base], "bzr://example.com:42/")]
        )
        self.assertEqual(started_ex_calls, [([self.get_transport().base], self.server)])

    def test_run_server_started_hooks_ipv6(self):
        """Test that socknames can contain 4-tuples."""
        self.server._sockname = ("::", 42, 0, 0)
        started_calls = []
        server.SmartTCPServer.hooks.install_named_hook(
            "server_started",
            lambda backing_urls, url: started_calls.append((backing_urls, url)),
            None,
        )
        self.server.run_server_started_hooks()
        self.assertEqual(started_calls, [([self.get_transport().base], "bzr://:::42/")])

    def test_run_server_stopped_hooks(self):
        """Test the server stopped hooks."""
        self.server._sockname = ("example.com", 42)
        stopped_calls = []
        server.SmartTCPServer.hooks.install_named_hook(
            "server_stopped",
            lambda backing_urls, url: stopped_calls.append((backing_urls, url)),
            None,
        )
        self.server.run_server_stopped_hooks()
        self.assertEqual(
            stopped_calls, [([self.get_transport().base], "bzr://example.com:42/")]
        )


class TestSmartServerRepositoryPack(tests.TestCaseWithMemoryTransport):
    def test_pack(self):
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryPack(backing)
        tree = self.make_branch_and_memory_tree(".")
        repo_token = tree.branch.repository.lock_write().repository_token

        self.assertIs(None, request.execute(b"", repo_token, False))

        self.assertEqual(
            smart_req.SuccessfulSmartServerResponse(
                (b"ok",),
            ),
            request.do_body(b""),
        )


class TestSmartServerRepositoryGetInventories(tests.TestCaseWithTransport):
    def _get_serialized_inventory_delta(self, repository, base_revid, revid):
        base_inv = repository.revision_tree(base_revid).root_inventory
        inv = repository.revision_tree(revid).root_inventory
        inv_delta = inv._make_delta(base_inv)
        serializer = inventory_delta.InventoryDeltaSerializer(True, True)
        return b"".join(serializer.delta_to_lines(base_revid, revid, inv_delta))

    def test_single(self):
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryGetInventories(backing)
        t = self.make_branch_and_tree(".", format="2a")
        self.addCleanup(t.lock_write().unlock)
        self.build_tree_contents([("file", b"somecontents")])
        t.add(["file"], ids=[b"thefileid"])
        t.commit(rev_id=b"somerev", message="add file")
        self.assertIs(None, request.execute(b"", b"unordered"))
        response = request.do_body(b"somerev\n")
        self.assertTrue(response.is_successful())
        self.assertEqual(response.args, (b"ok",))
        stream = [
            (
                "inventory-deltas",
                [
                    versionedfile.FulltextContentFactory(
                        b"somerev",
                        None,
                        None,
                        self._get_serialized_inventory_delta(
                            t.branch.repository, b"null:", b"somerev"
                        ),
                    )
                ],
            )
        ]
        fmt = controldir.format_registry.get("2a")().repository_format
        self.assertEqual(
            b"".join(response.body_stream),
            b"".join(smart_repo._stream_to_byte_stream(stream, fmt)),
        )

    def test_empty(self):
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryGetInventories(backing)
        t = self.make_branch_and_tree(".", format="2a")
        self.addCleanup(t.lock_write().unlock)
        self.build_tree_contents([("file", b"somecontents")])
        t.add(["file"], ids=[b"thefileid"])
        t.commit(rev_id=b"somerev", message="add file")
        self.assertIs(None, request.execute(b"", b"unordered"))
        response = request.do_body(b"")
        self.assertTrue(response.is_successful())
        self.assertEqual(response.args, (b"ok",))
        self.assertEqual(
            b"".join(response.body_stream),
            b"Bazaar pack format 1 (introduced in 0.18)\nB54\n\nBazaar repository format 2a (needs bzr 1.16 or later)\nE",
        )


class TestSmartServerRepositoryGetStreamForMissingKeys(GetStreamTestBase):
    def test_missing(self):
        """The search argument may be a 'ancestry-of' some heads'."""
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryGetStreamForMissingKeys(backing)
        repo, r1, r2 = self.make_two_commit_repo()
        request.execute(b"", repo._format.network_name())
        lines = b"inventories\t" + r1
        response = request.do_body(lines)
        self.assertEqual((b"ok",), response.args)
        stream_bytes = b"".join(response.body_stream)
        self.assertStartsWith(stream_bytes, b"Bazaar pack format 1")

    def test_unknown_format(self):
        """The format may not be known by the remote server."""
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryGetStreamForMissingKeys(backing)
        repo, r1, r2 = self.make_two_commit_repo()
        request.execute(b"", b"yada yada yada")
        smart_req.FailedSmartServerResponse(
            (b"UnknownFormat", b"repository", b"yada yada yada")
        )


class TestSmartServerRepositoryRevisionArchive(tests.TestCaseWithTransport):
    def test_get(self):
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryRevisionArchive(backing)
        t = self.make_branch_and_tree(".")
        self.addCleanup(t.lock_write().unlock)
        self.build_tree_contents([("file", b"somecontents")])
        t.add(["file"], ids=[b"thefileid"])
        t.commit(rev_id=b"somerev", message="add file")
        response = request.execute(b"", b"somerev", b"tar", b"foo.tar", b"foo")
        self.assertTrue(response.is_successful())
        self.assertEqual(response.args, (b"ok",))
        b = BytesIO(b"".join(response.body_stream))
        with tarfile.open(mode="r", fileobj=b) as tf:
            self.assertEqual(["foo/file"], tf.getnames())


class TestSmartServerRepositoryAnnotateFileRevision(tests.TestCaseWithTransport):
    def test_get(self):
        backing = self.get_transport()
        request = smart_repo.SmartServerRepositoryAnnotateFileRevision(backing)
        t = self.make_branch_and_tree(".")
        self.addCleanup(t.lock_write().unlock)
        self.build_tree_contents([("file", b"somecontents\nmorecontents\n")])
        t.add(["file"], ids=[b"thefileid"])
        t.commit(rev_id=b"somerev", message="add file")
        response = request.execute(b"", b"somerev", b"file")
        self.assertTrue(response.is_successful())
        self.assertEqual(response.args, (b"ok",))
        self.assertEqual(
            [[b"somerev", b"somecontents\n"], [b"somerev", b"morecontents\n"]],
            bencode.bdecode(response.body),
        )


class TestSmartServerBranchRequestGetAllReferenceInfo(TestLockedBranch):
    def test_get_some(self):
        backing = self.get_transport()
        request = smart_branch.SmartServerBranchRequestGetAllReferenceInfo(backing)
        branch = self.make_branch(".")
        branch.set_reference_info("some/path", "http://www.example.com/")
        response = request.execute(b"")
        self.assertTrue(response.is_successful())
        self.assertEqual(response.args, (b"ok",))
        self.assertEqual(
            [[b"some/path", b"http://www.example.com/", b""]],
            bencode.bdecode(response.body),
        )
