# Copyright (C) 2006-2013, 2016 Canonical Ltd
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

"""Tests for remote bzrdir/branch/repo/etc.

These are proxy objects which act on remote objects by sending messages
through a smart client.  The proxies are to be created when attempting to open
the object given a transport that supports smartserver rpc operations.

These tests correspond to tests.test_smart, which exercises the server side.
"""

import base64
import bz2
import tarfile
import zlib
from io import BytesIO

import fastbencode as bencode
from vcsgraph.errors import GhostRevisionsHaveNoRevno

from ... import branch, config, controldir, errors, repository, tests, treebuilder
from ... import transport as _mod_transport
from ..._bzr_rs import revision_bencode_serializer
from ...branch import Branch
from ...revision import NULL_REVISION, Revision
from ...tests import test_server
from ...tests.scenarios import load_tests_apply_scenarios
from ...transport.memory import MemoryTransport
from ...transport.remote import RemoteSSHTransport, RemoteTCPTransport, RemoteTransport
from .. import (
    RemoteBzrProber,
    bzrdir,
    groupcompress_repo,
    inventory,
    inventory_delta,
    knitpack_repo,
    remote,
    versionedfile,
    vf_search,
)
from ..bzrdir import BzrDir, BzrDirFormat
from ..remote import (
    RemoteBranch,
    RemoteBranchFormat,
    RemoteBzrDir,
    RemoteBzrDirFormat,
    RemoteRepository,
    RemoteRepositoryFormat,
    UnknownErrorFromSmartServer,
)
from ..smart import medium, request
from ..smart.client import _SmartClient
from ..smart.repository import (
    SmartServerRepositoryGetParentMap,
    SmartServerRepositoryGetStream_1_19,
    _stream_to_byte_stream,
)

load_tests = load_tests_apply_scenarios


class BasicRemoteObjectTests(tests.TestCaseWithTransport):
    scenarios = [
        (
            "HPSS-v2",
            {"transport_server": test_server.SmartTCPServer_for_testing_v2_only},
        ),
        ("HPSS-v3", {"transport_server": test_server.SmartTCPServer_for_testing}),
    ]

    def setUp(self):
        super().setUp()
        self.transport = self.get_transport()
        # make a branch that can be opened over the smart transport
        self.local_wt = BzrDir.create_standalone_workingtree(".")
        self.addCleanup(self.transport.disconnect)

    def test_create_remote_bzrdir(self):
        b = remote.RemoteBzrDir(self.transport, RemoteBzrDirFormat())
        self.assertIsInstance(b, BzrDir)

    def test_open_remote_branch(self):
        # open a standalone branch in the working directory
        b = remote.RemoteBzrDir(self.transport, RemoteBzrDirFormat())
        branch = b.open_branch()
        self.assertIsInstance(branch, Branch)

    def test_remote_repository(self):
        b = BzrDir.open_from_transport(self.transport)
        repo = b.open_repository()
        revid = "\xc823123123".encode()
        self.assertFalse(repo.has_revision(revid))
        self.local_wt.commit(message="test commit", rev_id=revid)
        self.assertTrue(repo.has_revision(revid))

    def test_find_correct_format(self):
        """Should open a RemoteBzrDir over a RemoteTransport."""
        fmt = BzrDirFormat.find_format(self.transport)
        self.assertIn(RemoteBzrProber, controldir.ControlDirFormat._probers)
        self.assertIsInstance(fmt, RemoteBzrDirFormat)

    def test_open_detected_smart_format(self):
        fmt = BzrDirFormat.find_format(self.transport)
        d = fmt.open(self.transport)
        self.assertIsInstance(d, BzrDir)

    def test_remote_branch_repr(self):
        b = BzrDir.open_from_transport(self.transport).open_branch()
        self.assertStartsWith(str(b), "RemoteBranch(")

    def test_remote_bzrdir_repr(self):
        b = BzrDir.open_from_transport(self.transport)
        self.assertStartsWith(str(b), "RemoteBzrDir(")

    def test_remote_branch_format_supports_stacking(self):
        t = self.transport
        self.make_branch("unstackable", format="pack-0.92")
        b = BzrDir.open_from_transport(t.clone("unstackable")).open_branch()
        self.assertFalse(b._format.supports_stacking())
        self.make_branch("stackable", format="1.9")
        b = BzrDir.open_from_transport(t.clone("stackable")).open_branch()
        self.assertTrue(b._format.supports_stacking())

    def test_remote_repo_format_supports_external_references(self):
        t = self.transport
        bd = self.make_controldir("unstackable", format="pack-0.92")
        r = bd.create_repository()
        self.assertFalse(r._format.supports_external_lookups)
        r = BzrDir.open_from_transport(t.clone("unstackable")).open_repository()
        self.assertFalse(r._format.supports_external_lookups)
        bd = self.make_controldir("stackable", format="1.9")
        r = bd.create_repository()
        self.assertTrue(r._format.supports_external_lookups)
        r = BzrDir.open_from_transport(t.clone("stackable")).open_repository()
        self.assertTrue(r._format.supports_external_lookups)

    def test_remote_branch_set_append_revisions_only(self):
        # Make a format 1.9 branch, which supports append_revisions_only
        branch = self.make_branch("branch", format="1.9")
        branch.set_append_revisions_only(True)
        config = branch.get_config_stack()
        self.assertEqual(True, config.get("append_revisions_only"))
        branch.set_append_revisions_only(False)
        config = branch.get_config_stack()
        self.assertEqual(False, config.get("append_revisions_only"))

    def test_remote_branch_set_append_revisions_only_upgrade_reqd(self):
        branch = self.make_branch("branch", format="knit")
        self.assertRaises(
            errors.UpgradeRequired, branch.set_append_revisions_only, True
        )


class FakeProtocol:
    """Lookalike SmartClientRequestProtocolOne allowing body reading tests."""

    def __init__(self, body, fake_client):
        self.body = body
        self._body_buffer = None
        self._fake_client = fake_client

    def read_body_bytes(self, count=-1):
        if self._body_buffer is None:
            self._body_buffer = BytesIO(self.body)
        bytes = self._body_buffer.read(count)
        if self._body_buffer.tell() == len(self._body_buffer.getvalue()):
            self._fake_client.expecting_body = False
        return bytes

    def cancel_read_body(self):
        self._fake_client.expecting_body = False

    def read_streamed_body(self):
        return self.body


class FakeClient(_SmartClient):
    """Lookalike for _SmartClient allowing testing."""

    def __init__(self, fake_medium_base="fake base"):
        """Create a FakeClient."""
        self.responses = []
        self._calls = []
        self.expecting_body = False
        # if non-None, this is the list of expected calls, with only the
        # method name and arguments included.  the body might be hard to
        # compute so is not included. If a call is None, that call can
        # be anything.
        self._expected_calls = None
        _SmartClient.__init__(self, FakeMedium(self._calls, fake_medium_base))

    def add_expected_call(
        self, call_name, call_args, response_type, response_args, response_body=None
    ):
        if self._expected_calls is None:
            self._expected_calls = []
        self._expected_calls.append((call_name, call_args))
        self.responses.append((response_type, response_args, response_body))

    def add_success_response(self, *args):
        self.responses.append((b"success", args, None))

    def add_success_response_with_body(self, body, *args):
        self.responses.append((b"success", args, body))
        if self._expected_calls is not None:
            self._expected_calls.append(None)

    def add_error_response(self, *args):
        self.responses.append((b"error", args))

    def add_unknown_method_response(self, verb):
        self.responses.append((b"unknown", verb))

    def finished_test(self):
        if self._expected_calls:
            raise AssertionError(
                f"{self!r} finished but was still expecting {self._expected_calls[0]!r}"
            )

    def _get_next_response(self):
        try:
            response_tuple = self.responses.pop(0)
        except IndexError as e:
            raise AssertionError(f"{self!r} didn't expect any more calls") from e
        if response_tuple[0] == b"unknown":
            raise errors.UnknownSmartMethod(response_tuple[1])
        elif response_tuple[0] == b"error":
            raise errors.ErrorFromSmartServer(response_tuple[1])
        return response_tuple

    def _check_call(self, method, args):
        if self._expected_calls is None:
            # the test should be updated to say what it expects
            return
        try:
            next_call = self._expected_calls.pop(0)
        except IndexError as e:
            raise AssertionError(
                f"{self!r} didn't expect any more calls but got {method!r}{args!r}"
            ) from e
        if next_call is None:
            return
        if method != next_call[0] or args != next_call[1]:
            raise AssertionError(
                f"{self!r} expected {next_call[0]!r}{next_call[1]!r} but got {method!r}{args!r}"
            )

    def call(self, method, *args):
        self._check_call(method, args)
        self._calls.append(("call", method, args))
        return self._get_next_response()[1]

    def call_expecting_body(self, method, *args):
        self._check_call(method, args)
        self._calls.append(("call_expecting_body", method, args))
        result = self._get_next_response()
        self.expecting_body = True
        return result[1], FakeProtocol(result[2], self)

    def call_with_body_bytes(self, method, args, body):
        self._check_call(method, args)
        self._calls.append(("call_with_body_bytes", method, args, body))
        result = self._get_next_response()
        return result[1], FakeProtocol(result[2], self)

    def call_with_body_bytes_expecting_body(self, method, args, body):
        self._check_call(method, args)
        self._calls.append(("call_with_body_bytes_expecting_body", method, args, body))
        result = self._get_next_response()
        self.expecting_body = True
        return result[1], FakeProtocol(result[2], self)

    def call_with_body_stream(self, args, stream):
        # Explicitly consume the stream before checking for an error, because
        # that's what happens a real medium.
        stream = list(stream)
        self._check_call(args[0], args[1:])
        self._calls.append(("call_with_body_stream", args[0], args[1:], stream))
        result = self._get_next_response()
        # The second value returned from call_with_body_stream is supposed to
        # be a response_handler object, but so far no tests depend on that.
        response_handler = None
        return result[1], response_handler


class FakeMedium(medium.SmartClientMedium):
    def __init__(self, client_calls, base):
        medium.SmartClientMedium.__init__(self, base)
        self._client_calls = client_calls

    def disconnect(self):
        self._client_calls.append(("disconnect medium",))


class TestVfsHas(tests.TestCase):
    def test_unicode_path(self):
        client = FakeClient("/")
        client.add_success_response(
            b"yes",
        )
        transport = RemoteTransport("bzr://localhost/", _client=client)
        filename = "/hell\u00d8"
        result = transport.has(filename)
        self.assertEqual([("call", b"has", (filename.encode("utf-8"),))], client._calls)
        self.assertTrue(result)


class TestRemote(tests.TestCaseWithMemoryTransport):
    def get_branch_format(self):
        reference_bzrdir_format = controldir.format_registry.get("default")()
        return reference_bzrdir_format.get_branch_format()

    def get_repo_format(self):
        reference_bzrdir_format = controldir.format_registry.get("default")()
        return reference_bzrdir_format.repository_format

    def assertFinished(self, fake_client):
        """Assert that all of a FakeClient's expected calls have occurred."""
        fake_client.finished_test()


class Test_ClientMedium_remote_path_from_transport(tests.TestCase):
    """Tests for the behaviour of client_medium.remote_path_from_transport."""

    def assertRemotePath(self, expected, client_base, transport_base):
        """Assert that the result of
        SmartClientMedium.remote_path_from_transport is the expected value for
        a given client_base and transport_base.
        """
        client_medium = medium.SmartClientMedium(client_base)
        t = _mod_transport.get_transport(transport_base)
        result = client_medium.remote_path_from_transport(t)
        self.assertEqual(expected, result)

    def test_remote_path_from_transport(self):
        """SmartClientMedium.remote_path_from_transport calculates a URL for
        the given transport relative to the root of the client base URL.
        """
        self.assertRemotePath("xyz/", "bzr://host/path", "bzr://host/xyz")
        self.assertRemotePath("path/xyz/", "bzr://host/path", "bzr://host/path/xyz")

    def assertRemotePathHTTP(self, expected, transport_base, relpath):
        """Assert that the result of
        HttpTransportBase.remote_path_from_transport is the expected value for
        a given transport_base and relpath of that transport.  (Note that
        HttpTransportBase is a subclass of SmartClientMedium).
        """
        base_transport = _mod_transport.get_transport(transport_base)
        client_medium = base_transport.get_smart_medium()
        cloned_transport = base_transport.clone(relpath)
        result = client_medium.remote_path_from_transport(cloned_transport)
        self.assertEqual(expected, result)

    def test_remote_path_from_transport_http(self):
        """Remote paths for HTTP transports are calculated differently to other
        transports.  They are just relative to the client base, not the root
        directory of the host.
        """
        for scheme in ["http:", "https:", "bzr+http:", "bzr+https:"]:
            self.assertRemotePathHTTP("../xyz/", scheme + "//host/path", "../xyz/")
            self.assertRemotePathHTTP("xyz/", scheme + "//host/path", "xyz/")


class Test_ClientMedium_remote_is_at_least(tests.TestCase):
    """Tests for the behaviour of client_medium.remote_is_at_least."""

    def test_initially_unlimited(self):
        """A fresh medium assumes that the remote side supports all
        versions.
        """
        client_medium = medium.SmartClientMedium("dummy base")
        self.assertFalse(client_medium._is_remote_before((99, 99)))

    def test__remember_remote_is_before(self):
        """Calling _remember_remote_is_before ratchets down the known remote
        version.
        """
        client_medium = medium.SmartClientMedium("dummy base")
        # Mark the remote side as being less than 1.6.  The remote side may
        # still be 1.5.
        client_medium._remember_remote_is_before((1, 6))
        self.assertTrue(client_medium._is_remote_before((1, 6)))
        self.assertFalse(client_medium._is_remote_before((1, 5)))
        # Calling _remember_remote_is_before again with a lower value works.
        client_medium._remember_remote_is_before((1, 5))
        self.assertTrue(client_medium._is_remote_before((1, 5)))
        # If you call _remember_remote_is_before with a higher value it logs a
        # warning, and continues to remember the lower value.
        self.assertNotContainsRe(self.get_log(), "_remember_remote_is_before")
        client_medium._remember_remote_is_before((1, 9))
        self.assertContainsRe(self.get_log(), "_remember_remote_is_before")
        self.assertTrue(client_medium._is_remote_before((1, 5)))


class TestBzrDirCloningMetaDir(TestRemote):
    def test_backwards_compat(self):
        self.setup_smart_server_with_call_log()
        a_dir = self.make_controldir(".")
        self.reset_smart_call_log()
        verb = b"BzrDir.cloning_metadir"
        self.disable_verb(verb)
        a_dir.cloning_metadir()
        call_count = len([call for call in self.hpss_calls if call.call.method == verb])
        self.assertEqual(1, call_count)

    def test_branch_reference(self):
        transport = self.get_transport("quack")
        referenced = self.make_branch("referenced")
        expected = referenced.controldir.cloning_metadir()
        client = FakeClient(transport.base)
        (
            client.add_expected_call(
                b"BzrDir.cloning_metadir",
                (b"quack/", b"False"),
                b"error",
                (b"BranchReference",),
            ),
        )
        (
            client.add_expected_call(
                b"BzrDir.open_branchV3",
                (b"quack/",),
                b"success",
                (b"ref", self.get_url("referenced").encode("utf-8")),
            ),
        )
        a_controldir = RemoteBzrDir(transport, RemoteBzrDirFormat(), _client=client)
        result = a_controldir.cloning_metadir()
        # We should have got a control dir matching the referenced branch.
        self.assertEqual(bzrdir.BzrDirMetaFormat1, type(result))
        self.assertEqual(expected._repository_format, result._repository_format)
        self.assertEqual(expected._branch_format, result._branch_format)
        self.assertFinished(client)

    def test_current_server(self):
        transport = self.get_transport(".")
        transport = transport.clone("quack")
        self.make_controldir("quack")
        client = FakeClient(transport.base)
        reference_bzrdir_format = controldir.format_registry.get("default")()
        control_name = reference_bzrdir_format.network_name()
        (
            client.add_expected_call(
                b"BzrDir.cloning_metadir",
                (b"quack/", b"False"),
                b"success",
                (control_name, b"", (b"branch", b"")),
            ),
        )
        a_controldir = RemoteBzrDir(transport, RemoteBzrDirFormat(), _client=client)
        result = a_controldir.cloning_metadir()
        # We should have got a reference control dir with default branch and
        # repository formats.
        # This pokes a little, just to be sure.
        self.assertEqual(bzrdir.BzrDirMetaFormat1, type(result))
        self.assertEqual(None, result._repository_format)
        self.assertEqual(None, result._branch_format)
        self.assertFinished(client)

    def test_unknown(self):
        transport = self.get_transport("quack")
        referenced = self.make_branch("referenced")
        referenced.controldir.cloning_metadir()
        client = FakeClient(transport.base)
        (
            client.add_expected_call(
                b"BzrDir.cloning_metadir",
                (b"quack/", b"False"),
                b"success",
                (b"unknown", b"unknown", (b"branch", b"")),
            ),
        )
        a_controldir = RemoteBzrDir(transport, RemoteBzrDirFormat(), _client=client)
        self.assertRaises(errors.UnknownFormatError, a_controldir.cloning_metadir)


class TestBzrDirCheckoutMetaDir(TestRemote):
    def test__get_checkout_format(self):
        transport = MemoryTransport()
        client = FakeClient(transport.base)
        reference_bzrdir_format = controldir.format_registry.get("default")()
        control_name = reference_bzrdir_format.network_name()
        client.add_expected_call(
            b"BzrDir.checkout_metadir",
            (b"quack/",),
            b"success",
            (control_name, b"", b""),
        )
        transport.mkdir("quack")
        transport = transport.clone("quack")
        a_controldir = RemoteBzrDir(transport, RemoteBzrDirFormat(), _client=client)
        result = a_controldir.checkout_metadir()
        # We should have got a reference control dir with default branch and
        # repository formats.
        self.assertEqual(bzrdir.BzrDirMetaFormat1, type(result))
        self.assertEqual(None, result._repository_format)
        self.assertEqual(None, result._branch_format)
        self.assertFinished(client)

    def test_unknown_format(self):
        transport = MemoryTransport()
        client = FakeClient(transport.base)
        client.add_expected_call(
            b"BzrDir.checkout_metadir",
            (b"quack/",),
            b"success",
            (b"dontknow", b"", b""),
        )
        transport.mkdir("quack")
        transport = transport.clone("quack")
        a_controldir = RemoteBzrDir(transport, RemoteBzrDirFormat(), _client=client)
        self.assertRaises(errors.UnknownFormatError, a_controldir.checkout_metadir)
        self.assertFinished(client)


class TestBzrDirGetBranches(TestRemote):
    def test_get_branches(self):
        transport = MemoryTransport()
        client = FakeClient(transport.base)
        reference_bzrdir_format = controldir.format_registry.get("default")()
        branch_name = reference_bzrdir_format.get_branch_format().network_name()
        client.add_success_response_with_body(
            bencode.bencode(
                {b"foo": (b"branch", branch_name), b"": (b"branch", branch_name)}
            ),
            b"success",
        )
        client.add_success_response(
            b"ok",
            b"",
            b"no",
            b"no",
            b"no",
            reference_bzrdir_format.repository_format.network_name(),
        )
        client.add_error_response(b"NotStacked")
        client.add_success_response(
            b"ok",
            b"",
            b"no",
            b"no",
            b"no",
            reference_bzrdir_format.repository_format.network_name(),
        )
        client.add_error_response(b"NotStacked")
        transport.mkdir("quack")
        transport = transport.clone("quack")
        a_controldir = RemoteBzrDir(transport, RemoteBzrDirFormat(), _client=client)
        result = a_controldir.get_branches()
        self.assertEqual({"", "foo"}, set(result.keys()))
        self.assertEqual(
            [
                ("call_expecting_body", b"BzrDir.get_branches", (b"quack/",)),
                ("call", b"BzrDir.find_repositoryV3", (b"quack/",)),
                ("call", b"Branch.get_stacked_on_url", (b"quack/",)),
                ("call", b"BzrDir.find_repositoryV3", (b"quack/",)),
                ("call", b"Branch.get_stacked_on_url", (b"quack/",)),
            ],
            client._calls,
        )


class TestBzrDirDestroyBranch(TestRemote):
    def test_destroy_default(self):
        transport = self.get_transport("quack")
        self.make_branch("referenced")
        client = FakeClient(transport.base)
        (
            client.add_expected_call(
                b"BzrDir.destroy_branch", (b"quack/",), b"success", (b"ok",)
            ),
        )
        a_controldir = RemoteBzrDir(transport, RemoteBzrDirFormat(), _client=client)
        a_controldir.destroy_branch()
        self.assertFinished(client)


class TestBzrDirHasWorkingTree(TestRemote):
    def test_has_workingtree(self):
        transport = self.get_transport("quack")
        client = FakeClient(transport.base)
        (
            client.add_expected_call(
                b"BzrDir.has_workingtree", (b"quack/",), b"success", (b"yes",)
            ),
        )
        a_controldir = RemoteBzrDir(transport, RemoteBzrDirFormat(), _client=client)
        self.assertTrue(a_controldir.has_workingtree())
        self.assertFinished(client)

    def test_no_workingtree(self):
        transport = self.get_transport("quack")
        client = FakeClient(transport.base)
        (
            client.add_expected_call(
                b"BzrDir.has_workingtree", (b"quack/",), b"success", (b"no",)
            ),
        )
        a_controldir = RemoteBzrDir(transport, RemoteBzrDirFormat(), _client=client)
        self.assertFalse(a_controldir.has_workingtree())
        self.assertFinished(client)


class TestBzrDirDestroyRepository(TestRemote):
    def test_destroy_repository(self):
        transport = self.get_transport("quack")
        client = FakeClient(transport.base)
        (
            client.add_expected_call(
                b"BzrDir.destroy_repository", (b"quack/",), b"success", (b"ok",)
            ),
        )
        a_controldir = RemoteBzrDir(transport, RemoteBzrDirFormat(), _client=client)
        a_controldir.destroy_repository()
        self.assertFinished(client)


class TestBzrDirOpen(TestRemote):
    def make_fake_client_and_transport(self, path="quack"):
        transport = MemoryTransport()
        transport.mkdir(path)
        transport = transport.clone(path)
        client = FakeClient(transport.base)
        return client, transport

    def test_absent(self):
        client, transport = self.make_fake_client_and_transport()
        client.add_expected_call(b"BzrDir.open_2.1", (b"quack/",), b"success", (b"no",))
        self.assertRaises(
            errors.NotBranchError,
            RemoteBzrDir,
            transport,
            RemoteBzrDirFormat(),
            _client=client,
            _force_probe=True,
        )
        self.assertFinished(client)

    def test_present_without_workingtree(self):
        client, transport = self.make_fake_client_and_transport()
        client.add_expected_call(
            b"BzrDir.open_2.1", (b"quack/",), b"success", (b"yes", b"no")
        )
        bd = RemoteBzrDir(
            transport, RemoteBzrDirFormat(), _client=client, _force_probe=True
        )
        self.assertIsInstance(bd, RemoteBzrDir)
        self.assertFalse(bd.has_workingtree())
        self.assertRaises(errors.NoWorkingTree, bd.open_workingtree)
        self.assertFinished(client)

    def test_present_with_workingtree(self):
        client, transport = self.make_fake_client_and_transport()
        client.add_expected_call(
            b"BzrDir.open_2.1", (b"quack/",), b"success", (b"yes", b"yes")
        )
        bd = RemoteBzrDir(
            transport, RemoteBzrDirFormat(), _client=client, _force_probe=True
        )
        self.assertIsInstance(bd, RemoteBzrDir)
        self.assertTrue(bd.has_workingtree())
        self.assertRaises(errors.NotLocalUrl, bd.open_workingtree)
        self.assertFinished(client)

    def test_backwards_compat(self):
        client, transport = self.make_fake_client_and_transport()
        client.add_expected_call(
            b"BzrDir.open_2.1", (b"quack/",), b"unknown", (b"BzrDir.open_2.1",)
        )
        client.add_expected_call(b"BzrDir.open", (b"quack/",), b"success", (b"yes",))
        bd = RemoteBzrDir(
            transport, RemoteBzrDirFormat(), _client=client, _force_probe=True
        )
        self.assertIsInstance(bd, RemoteBzrDir)
        self.assertFinished(client)

    def test_backwards_compat_hpss_v2(self):
        client, transport = self.make_fake_client_and_transport()
        # Monkey-patch fake client to simulate real-world behaviour with v2
        # server: upon first RPC call detect the protocol version, and because
        # the version is 2 also do _remember_remote_is_before((1, 6)) before
        # continuing with the RPC.
        orig_check_call = client._check_call

        def check_call(method, args):
            client._medium._protocol_version = 2
            client._medium._remember_remote_is_before((1, 6))
            client._check_call = orig_check_call
            client._check_call(method, args)

        client._check_call = check_call
        client.add_expected_call(
            b"BzrDir.open_2.1", (b"quack/",), b"unknown", (b"BzrDir.open_2.1",)
        )
        client.add_expected_call(b"BzrDir.open", (b"quack/",), b"success", (b"yes",))
        bd = RemoteBzrDir(
            transport, RemoteBzrDirFormat(), _client=client, _force_probe=True
        )
        self.assertIsInstance(bd, RemoteBzrDir)
        self.assertFinished(client)


class TestBzrDirOpenBranch(TestRemote):
    def test_backwards_compat(self):
        self.setup_smart_server_with_call_log()
        self.make_branch(".")
        a_dir = BzrDir.open(self.get_url("."))
        self.reset_smart_call_log()
        verb = b"BzrDir.open_branchV3"
        self.disable_verb(verb)
        a_dir.open_branch()
        call_count = len([call for call in self.hpss_calls if call.call.method == verb])
        self.assertEqual(1, call_count)

    def test_branch_present(self):
        reference_format = self.get_repo_format()
        network_name = reference_format.network_name()
        branch_network_name = self.get_branch_format().network_name()
        transport = MemoryTransport()
        transport.mkdir("quack")
        transport = transport.clone("quack")
        client = FakeClient(transport.base)
        client.add_expected_call(
            b"BzrDir.open_branchV3",
            (b"quack/",),
            b"success",
            (b"branch", branch_network_name),
        )
        client.add_expected_call(
            b"BzrDir.find_repositoryV3",
            (b"quack/",),
            b"success",
            (b"ok", b"", b"no", b"no", b"no", network_name),
        )
        client.add_expected_call(
            b"Branch.get_stacked_on_url", (b"quack/",), b"error", (b"NotStacked",)
        )
        bzrdir = RemoteBzrDir(transport, RemoteBzrDirFormat(), _client=client)
        result = bzrdir.open_branch()
        self.assertIsInstance(result, RemoteBranch)
        self.assertEqual(bzrdir, result.controldir)
        self.assertFinished(client)

    def test_branch_missing(self):
        transport = MemoryTransport()
        transport.mkdir("quack")
        transport = transport.clone("quack")
        client = FakeClient(transport.base)
        client.add_error_response(b"nobranch")
        bzrdir = RemoteBzrDir(transport, RemoteBzrDirFormat(), _client=client)
        self.assertRaises(errors.NotBranchError, bzrdir.open_branch)
        self.assertEqual(
            [("call", b"BzrDir.open_branchV3", (b"quack/",))], client._calls
        )

    def test__get_tree_branch(self):
        # _get_tree_branch is a form of open_branch, but it should only ask for
        # branch opening, not any other network requests.
        calls = []

        def open_branch(name=None, possible_transports=None):
            calls.append("Called")
            return "a-branch"

        transport = MemoryTransport()
        # no requests on the network - catches other api calls being made.
        client = FakeClient(transport.base)
        bzrdir = RemoteBzrDir(transport, RemoteBzrDirFormat(), _client=client)
        # patch the open_branch call to record that it was called.
        bzrdir.open_branch = open_branch
        self.assertEqual((None, "a-branch"), bzrdir._get_tree_branch())
        self.assertEqual(["Called"], calls)
        self.assertEqual([], client._calls)

    def test_url_quoting_of_path(self):
        # Relpaths on the wire should not be URL-escaped.  So "~" should be
        # transmitted as "~", not "%7E".
        transport = RemoteTCPTransport("bzr://localhost/~hello/")
        client = FakeClient(transport.base)
        reference_format = self.get_repo_format()
        network_name = reference_format.network_name()
        branch_network_name = self.get_branch_format().network_name()
        client.add_expected_call(
            b"BzrDir.open_branchV3",
            (b"~hello/",),
            b"success",
            (b"branch", branch_network_name),
        )
        client.add_expected_call(
            b"BzrDir.find_repositoryV3",
            (b"~hello/",),
            b"success",
            (b"ok", b"", b"no", b"no", b"no", network_name),
        )
        client.add_expected_call(
            b"Branch.get_stacked_on_url", (b"~hello/",), b"error", (b"NotStacked",)
        )
        bzrdir = RemoteBzrDir(transport, RemoteBzrDirFormat(), _client=client)
        bzrdir.open_branch()
        self.assertFinished(client)

    def check_open_repository(self, rich_root, subtrees, external_lookup=b"no"):
        reference_format = self.get_repo_format()
        network_name = reference_format.network_name()
        transport = MemoryTransport()
        transport.mkdir("quack")
        transport = transport.clone("quack")
        rich_response = b"yes" if rich_root else b"no"
        subtree_response = b"yes" if subtrees else b"no"
        client = FakeClient(transport.base)
        client.add_success_response(
            b"ok", b"", rich_response, subtree_response, external_lookup, network_name
        )
        bzrdir = RemoteBzrDir(transport, RemoteBzrDirFormat(), _client=client)
        result = bzrdir.open_repository()
        self.assertEqual(
            [("call", b"BzrDir.find_repositoryV3", (b"quack/",))], client._calls
        )
        self.assertIsInstance(result, RemoteRepository)
        self.assertEqual(bzrdir, result.controldir)
        self.assertEqual(rich_root, result._format.rich_root_data)
        self.assertEqual(subtrees, result._format.supports_tree_reference)

    def test_open_repository_sets_format_attributes(self):
        self.check_open_repository(True, True)
        self.check_open_repository(False, True)
        self.check_open_repository(True, False)
        self.check_open_repository(False, False)
        self.check_open_repository(False, False, b"yes")

    def test_old_server(self):
        """RemoteBzrDirFormat should fail to probe if the server version is too
        old.
        """
        self.assertRaises(
            errors.NotBranchError, RemoteBzrProber.probe_transport, OldServerTransport()
        )


class TestBzrDirCreateBranch(TestRemote):
    def test_backwards_compat(self):
        self.setup_smart_server_with_call_log()
        repo = self.make_repository(".")
        self.reset_smart_call_log()
        self.disable_verb(b"BzrDir.create_branch")
        repo.controldir.create_branch()
        create_branch_call_count = len(
            [
                call
                for call in self.hpss_calls
                if call.call.method == b"BzrDir.create_branch"
            ]
        )
        self.assertEqual(1, create_branch_call_count)

    def test_current_server(self):
        transport = self.get_transport(".")
        transport = transport.clone("quack")
        self.make_repository("quack")
        client = FakeClient(transport.base)
        reference_bzrdir_format = controldir.format_registry.get("default")()
        reference_format = reference_bzrdir_format.get_branch_format()
        network_name = reference_format.network_name()
        reference_repo_fmt = reference_bzrdir_format.repository_format
        reference_repo_name = reference_repo_fmt.network_name()
        client.add_expected_call(
            b"BzrDir.create_branch",
            (b"quack/", network_name),
            b"success",
            (b"ok", network_name, b"", b"no", b"no", b"yes", reference_repo_name),
        )
        a_controldir = RemoteBzrDir(transport, RemoteBzrDirFormat(), _client=client)
        branch = a_controldir.create_branch()
        # We should have got a remote branch
        self.assertIsInstance(branch, remote.RemoteBranch)
        # its format should have the settings from the response
        format = branch._format
        self.assertEqual(network_name, format.network_name())

    def test_already_open_repo_and_reused_medium(self):
        """Bug 726584: create_branch(..., repository=repo) should work
        regardless of what the smart medium's base URL is.
        """
        self.transport_server = test_server.SmartTCPServer_for_testing
        transport = self.get_transport(".")
        repo = self.make_repository("quack")
        # Client's medium rooted a transport root (not at the bzrdir)
        client = FakeClient(transport.base)
        transport = transport.clone("quack")
        reference_bzrdir_format = controldir.format_registry.get("default")()
        reference_format = reference_bzrdir_format.get_branch_format()
        network_name = reference_format.network_name()
        reference_repo_fmt = reference_bzrdir_format.repository_format
        reference_repo_name = reference_repo_fmt.network_name()
        client.add_expected_call(
            b"BzrDir.create_branch",
            (b"extra/quack/", network_name),
            b"success",
            (b"ok", network_name, b"", b"no", b"no", b"yes", reference_repo_name),
        )
        a_controldir = RemoteBzrDir(transport, RemoteBzrDirFormat(), _client=client)
        branch = a_controldir.create_branch(repository=repo)
        # We should have got a remote branch
        self.assertIsInstance(branch, remote.RemoteBranch)
        # its format should have the settings from the response
        format = branch._format
        self.assertEqual(network_name, format.network_name())


class TestBzrDirCreateRepository(TestRemote):
    def test_backwards_compat(self):
        self.setup_smart_server_with_call_log()
        bzrdir = self.make_controldir(".")
        self.reset_smart_call_log()
        self.disable_verb(b"BzrDir.create_repository")
        bzrdir.create_repository()
        create_repo_call_count = len(
            [
                call
                for call in self.hpss_calls
                if call.call.method == b"BzrDir.create_repository"
            ]
        )
        self.assertEqual(1, create_repo_call_count)

    def test_current_server(self):
        transport = self.get_transport(".")
        transport = transport.clone("quack")
        self.make_controldir("quack")
        client = FakeClient(transport.base)
        reference_bzrdir_format = controldir.format_registry.get("default")()
        reference_format = reference_bzrdir_format.repository_format
        network_name = reference_format.network_name()
        client.add_expected_call(
            b"BzrDir.create_repository",
            (
                b"quack/",
                b"Bazaar repository format 2a (needs bzr 1.16 or later)\n",
                b"False",
            ),
            b"success",
            (b"ok", b"yes", b"yes", b"yes", network_name),
        )
        a_controldir = RemoteBzrDir(transport, RemoteBzrDirFormat(), _client=client)
        repo = a_controldir.create_repository()
        # We should have got a remote repository
        self.assertIsInstance(repo, remote.RemoteRepository)
        # its format should have the settings from the response
        format = repo._format
        self.assertTrue(format.rich_root_data)
        self.assertTrue(format.supports_tree_reference)
        self.assertTrue(format.supports_external_lookups)
        self.assertEqual(network_name, format.network_name())


class TestBzrDirOpenRepository(TestRemote):
    def test_backwards_compat_1_2_3(self):
        # fallback all the way to the first version.
        reference_format = self.get_repo_format()
        network_name = reference_format.network_name()
        server_url = "bzr://example.com/"
        self.permit_url(server_url)
        client = FakeClient(server_url)
        client.add_unknown_method_response(b"BzrDir.find_repositoryV3")
        client.add_unknown_method_response(b"BzrDir.find_repositoryV2")
        client.add_success_response(b"ok", b"", b"no", b"no")
        # A real repository instance will be created to determine the network
        # name.
        client.add_success_response_with_body(
            b"Bazaar-NG meta directory, format 1\n", b"ok"
        )
        client.add_success_response(b"stat", b"0", b"65535")
        client.add_success_response_with_body(
            reference_format.get_format_string(), b"ok"
        )
        # PackRepository wants to do a stat
        client.add_success_response(b"stat", b"0", b"65535")
        remote_transport = RemoteTransport(
            server_url + "quack/", medium=False, _client=client
        )
        bzrdir = RemoteBzrDir(remote_transport, RemoteBzrDirFormat(), _client=client)
        repo = bzrdir.open_repository()
        self.assertEqual(
            [
                ("call", b"BzrDir.find_repositoryV3", (b"quack/",)),
                ("call", b"BzrDir.find_repositoryV2", (b"quack/",)),
                ("call", b"BzrDir.find_repository", (b"quack/",)),
                ("call_expecting_body", b"get", (b"/quack/.bzr/branch-format",)),
                ("call", b"stat", (b"/quack/.bzr",)),
                ("call_expecting_body", b"get", (b"/quack/.bzr/repository/format",)),
                ("call", b"stat", (b"/quack/.bzr/repository",)),
            ],
            client._calls,
        )
        self.assertEqual(network_name, repo._format.network_name())

    def test_backwards_compat_2(self):
        # fallback to find_repositoryV2
        reference_format = self.get_repo_format()
        network_name = reference_format.network_name()
        server_url = "bzr://example.com/"
        self.permit_url(server_url)
        client = FakeClient(server_url)
        client.add_unknown_method_response(b"BzrDir.find_repositoryV3")
        client.add_success_response(b"ok", b"", b"no", b"no", b"no")
        # A real repository instance will be created to determine the network
        # name.
        client.add_success_response_with_body(
            b"Bazaar-NG meta directory, format 1\n", b"ok"
        )
        client.add_success_response(b"stat", b"0", b"65535")
        client.add_success_response_with_body(
            reference_format.get_format_string(), b"ok"
        )
        # PackRepository wants to do a stat
        client.add_success_response(b"stat", b"0", b"65535")
        remote_transport = RemoteTransport(
            server_url + "quack/", medium=False, _client=client
        )
        bzrdir = RemoteBzrDir(remote_transport, RemoteBzrDirFormat(), _client=client)
        repo = bzrdir.open_repository()
        self.assertEqual(
            [
                ("call", b"BzrDir.find_repositoryV3", (b"quack/",)),
                ("call", b"BzrDir.find_repositoryV2", (b"quack/",)),
                ("call_expecting_body", b"get", (b"/quack/.bzr/branch-format",)),
                ("call", b"stat", (b"/quack/.bzr",)),
                ("call_expecting_body", b"get", (b"/quack/.bzr/repository/format",)),
                ("call", b"stat", (b"/quack/.bzr/repository",)),
            ],
            client._calls,
        )
        self.assertEqual(network_name, repo._format.network_name())

    def test_current_server(self):
        reference_format = self.get_repo_format()
        network_name = reference_format.network_name()
        transport = MemoryTransport()
        transport.mkdir("quack")
        transport = transport.clone("quack")
        client = FakeClient(transport.base)
        client.add_success_response(b"ok", b"", b"no", b"no", b"no", network_name)
        bzrdir = RemoteBzrDir(transport, RemoteBzrDirFormat(), _client=client)
        repo = bzrdir.open_repository()
        self.assertEqual(
            [("call", b"BzrDir.find_repositoryV3", (b"quack/",))], client._calls
        )
        self.assertEqual(network_name, repo._format.network_name())


class TestBzrDirFormatInitializeEx(TestRemote):
    def test_success(self):
        """Simple test for typical successful call."""
        fmt = RemoteBzrDirFormat()
        default_format_name = BzrDirFormat.get_default_format().network_name()
        transport = self.get_transport()
        client = FakeClient(transport.base)
        client.add_expected_call(
            b"BzrDirFormat.initialize_ex_1.16",
            (
                default_format_name,
                b"path",
                b"False",
                b"False",
                b"False",
                b"",
                b"",
                b"",
                b"",
                b"False",
            ),
            b"success",
            (
                b".",
                b"no",
                b"no",
                b"yes",
                b"repo fmt",
                b"repo bzrdir fmt",
                b"bzrdir fmt",
                b"False",
                b"",
                b"",
                b"repo lock token",
            ),
        )
        # XXX: It would be better to call fmt.initialize_on_transport_ex, but
        # it's currently hard to test that without supplying a real remote
        # transport connected to a real server.
        fmt._initialize_on_transport_ex_rpc(
            client,
            b"path",
            transport,
            False,
            False,
            False,
            None,
            None,
            None,
            None,
            False,
        )
        self.assertFinished(client)

    def test_error(self):
        """Error responses are translated, e.g. 'PermissionDenied' raises the
        corresponding error from the client.
        """
        fmt = RemoteBzrDirFormat()
        default_format_name = BzrDirFormat.get_default_format().network_name()
        transport = self.get_transport()
        client = FakeClient(transport.base)
        client.add_expected_call(
            b"BzrDirFormat.initialize_ex_1.16",
            (
                default_format_name,
                b"path",
                b"False",
                b"False",
                b"False",
                b"",
                b"",
                b"",
                b"",
                b"False",
            ),
            b"error",
            (b"PermissionDenied", b"path", b"extra info"),
        )
        # XXX: It would be better to call fmt.initialize_on_transport_ex, but
        # it's currently hard to test that without supplying a real remote
        # transport connected to a real server.
        err = self.assertRaises(
            errors.PermissionDenied,
            fmt._initialize_on_transport_ex_rpc,
            client,
            b"path",
            transport,
            False,
            False,
            False,
            None,
            None,
            None,
            None,
            False,
        )
        self.assertEqual("path", err.path)
        self.assertEqual(": extra info", err.extra)
        self.assertFinished(client)

    def test_error_from_real_server(self):
        """Integration test for error translation."""
        transport = self.make_smart_server("foo")
        transport = transport.clone("no-such-path")
        fmt = RemoteBzrDirFormat()
        self.assertRaises(
            _mod_transport.NoSuchFile,
            fmt.initialize_on_transport_ex,
            transport,
            create_prefix=False,
        )


class OldSmartClient:
    """A fake smart client for test_old_version that just returns a version one
    response to the 'hello' (query version) command.
    """

    def get_request(self):
        input_file = BytesIO(b"ok\x011\n")
        output_file = BytesIO()
        client_medium = medium.SmartSimplePipesClientMedium(input_file, output_file)
        return medium.SmartClientStreamMediumRequest(client_medium)

    def protocol_version(self):
        return 1


class OldServerTransport:
    """A fake transport for test_old_server that reports it's smart server
    protocol version as version one.
    """

    def __init__(self):
        self.base = "fake:"

    def get_smart_client(self):
        return OldSmartClient()


class RemoteBzrDirTestCase(TestRemote):
    def make_remote_bzrdir(self, transport, client):
        """Make a RemotebzrDir using 'client' as the _client."""
        return RemoteBzrDir(transport, RemoteBzrDirFormat(), _client=client)


class RemoteBranchTestCase(RemoteBzrDirTestCase):
    def lock_remote_branch(self, branch):
        """Trick a RemoteBranch into thinking it is locked."""
        branch._lock_mode = "w"
        branch._lock_count = 2
        branch._lock_token = b"branch token"
        branch._repo_lock_token = b"repo token"
        branch.repository._lock_mode = "w"
        branch.repository._lock_count = 2
        branch.repository._lock_token = b"repo token"

    def make_remote_branch(self, transport, client):
        """Make a RemoteBranch using 'client' as its _SmartClient.

        A RemoteBzrDir and RemoteRepository will also be created to fill out
        the RemoteBranch, albeit with stub values for some of their attributes.
        """
        # we do not want bzrdir to make any remote calls, so use False as its
        # _client.  If it tries to make a remote call, this will fail
        # immediately.
        bzrdir = self.make_remote_bzrdir(transport, False)
        repo = RemoteRepository(bzrdir, None, _client=client)
        branch_format = self.get_branch_format()
        format = RemoteBranchFormat(network_name=branch_format.network_name())
        return RemoteBranch(bzrdir, repo, _client=client, format=format)


class TestBranchBreakLock(RemoteBranchTestCase):
    def test_break_lock(self):
        transport = MemoryTransport()
        client = FakeClient(transport.base)
        client.add_expected_call(
            b"Branch.get_stacked_on_url", (b"quack/",), b"error", (b"NotStacked",)
        )
        client.add_expected_call(
            b"Branch.break_lock", (b"quack/",), b"success", (b"ok",)
        )
        transport.mkdir("quack")
        transport = transport.clone("quack")
        branch = self.make_remote_branch(transport, client)
        branch.break_lock()
        self.assertFinished(client)


class TestBranchGetPhysicalLockStatus(RemoteBranchTestCase):
    def test_get_physical_lock_status_yes(self):
        transport = MemoryTransport()
        client = FakeClient(transport.base)
        client.add_expected_call(
            b"Branch.get_stacked_on_url", (b"quack/",), b"error", (b"NotStacked",)
        )
        client.add_expected_call(
            b"Branch.get_physical_lock_status", (b"quack/",), b"success", (b"yes",)
        )
        transport.mkdir("quack")
        transport = transport.clone("quack")
        branch = self.make_remote_branch(transport, client)
        result = branch.get_physical_lock_status()
        self.assertFinished(client)
        self.assertEqual(True, result)

    def test_get_physical_lock_status_no(self):
        transport = MemoryTransport()
        client = FakeClient(transport.base)
        client.add_expected_call(
            b"Branch.get_stacked_on_url", (b"quack/",), b"error", (b"NotStacked",)
        )
        client.add_expected_call(
            b"Branch.get_physical_lock_status", (b"quack/",), b"success", (b"no",)
        )
        transport.mkdir("quack")
        transport = transport.clone("quack")
        branch = self.make_remote_branch(transport, client)
        result = branch.get_physical_lock_status()
        self.assertFinished(client)
        self.assertEqual(False, result)


class TestBranchGetParent(RemoteBranchTestCase):
    def test_no_parent(self):
        # in an empty branch we decode the response properly
        transport = MemoryTransport()
        client = FakeClient(transport.base)
        client.add_expected_call(
            b"Branch.get_stacked_on_url", (b"quack/",), b"error", (b"NotStacked",)
        )
        client.add_expected_call(b"Branch.get_parent", (b"quack/",), b"success", (b"",))
        transport.mkdir("quack")
        transport = transport.clone("quack")
        branch = self.make_remote_branch(transport, client)
        result = branch.get_parent()
        self.assertFinished(client)
        self.assertEqual(None, result)

    def test_parent_relative(self):
        transport = MemoryTransport()
        client = FakeClient(transport.base)
        client.add_expected_call(
            b"Branch.get_stacked_on_url", (b"kwaak/",), b"error", (b"NotStacked",)
        )
        client.add_expected_call(
            b"Branch.get_parent", (b"kwaak/",), b"success", (b"../foo/",)
        )
        transport.mkdir("kwaak")
        transport = transport.clone("kwaak")
        branch = self.make_remote_branch(transport, client)
        result = branch.get_parent()
        self.assertEqual(transport.clone("../foo").base, result)

    def test_parent_absolute(self):
        transport = MemoryTransport()
        client = FakeClient(transport.base)
        client.add_expected_call(
            b"Branch.get_stacked_on_url", (b"kwaak/",), b"error", (b"NotStacked",)
        )
        client.add_expected_call(
            b"Branch.get_parent", (b"kwaak/",), b"success", (b"http://foo/",)
        )
        transport.mkdir("kwaak")
        transport = transport.clone("kwaak")
        branch = self.make_remote_branch(transport, client)
        result = branch.get_parent()
        self.assertEqual("http://foo/", result)
        self.assertFinished(client)


class TestBranchSetParentLocation(RemoteBranchTestCase):
    def test_no_parent(self):
        # We call the verb when setting parent to None
        transport = MemoryTransport()
        client = FakeClient(transport.base)
        client.add_expected_call(
            b"Branch.get_stacked_on_url", (b"quack/",), b"error", (b"NotStacked",)
        )
        client.add_expected_call(
            b"Branch.set_parent_location", (b"quack/", b"b", b"r", b""), b"success", ()
        )
        transport.mkdir("quack")
        transport = transport.clone("quack")
        branch = self.make_remote_branch(transport, client)
        branch._lock_token = b"b"
        branch._repo_lock_token = b"r"
        branch._set_parent_location(None)
        self.assertFinished(client)

    def test_parent(self):
        transport = MemoryTransport()
        client = FakeClient(transport.base)
        client.add_expected_call(
            b"Branch.get_stacked_on_url", (b"kwaak/",), b"error", (b"NotStacked",)
        )
        client.add_expected_call(
            b"Branch.set_parent_location",
            (b"kwaak/", b"b", b"r", b"foo"),
            b"success",
            (),
        )
        transport.mkdir("kwaak")
        transport = transport.clone("kwaak")
        branch = self.make_remote_branch(transport, client)
        branch._lock_token = b"b"
        branch._repo_lock_token = b"r"
        branch._set_parent_location("foo")
        self.assertFinished(client)

    def test_backwards_compat(self):
        self.setup_smart_server_with_call_log()
        branch = self.make_branch(".")
        self.reset_smart_call_log()
        verb = b"Branch.set_parent_location"
        self.disable_verb(verb)
        branch.set_parent("http://foo/")
        self.assertLength(14, self.hpss_calls)


class TestBranchGetTagsBytes(RemoteBranchTestCase):
    def test_backwards_compat(self):
        self.setup_smart_server_with_call_log()
        branch = self.make_branch(".")
        self.reset_smart_call_log()
        verb = b"Branch.get_tags_bytes"
        self.disable_verb(verb)
        branch.tags.get_tag_dict()
        call_count = len([call for call in self.hpss_calls if call.call.method == verb])
        self.assertEqual(1, call_count)

    def test_trivial(self):
        transport = MemoryTransport()
        client = FakeClient(transport.base)
        client.add_expected_call(
            b"Branch.get_stacked_on_url", (b"quack/",), b"error", (b"NotStacked",)
        )
        client.add_expected_call(
            b"Branch.get_tags_bytes", (b"quack/",), b"success", (b"",)
        )
        transport.mkdir("quack")
        transport = transport.clone("quack")
        branch = self.make_remote_branch(transport, client)
        result = branch.tags.get_tag_dict()
        self.assertFinished(client)
        self.assertEqual({}, result)


class TestBranchSetTagsBytes(RemoteBranchTestCase):
    def test_trivial(self):
        transport = MemoryTransport()
        client = FakeClient(transport.base)
        client.add_expected_call(
            b"Branch.get_stacked_on_url", (b"quack/",), b"error", (b"NotStacked",)
        )
        client.add_expected_call(
            b"Branch.set_tags_bytes",
            (b"quack/", b"branch token", b"repo token"),
            b"success",
            ("",),
        )
        transport.mkdir("quack")
        transport = transport.clone("quack")
        branch = self.make_remote_branch(transport, client)
        self.lock_remote_branch(branch)
        branch._set_tags_bytes(b"tags bytes")
        self.assertFinished(client)
        self.assertEqual(b"tags bytes", client._calls[-1][-1])

    def test_backwards_compatible(self):
        transport = MemoryTransport()
        client = FakeClient(transport.base)
        client.add_expected_call(
            b"Branch.get_stacked_on_url", (b"quack/",), b"error", (b"NotStacked",)
        )
        client.add_expected_call(
            b"Branch.set_tags_bytes",
            (b"quack/", b"branch token", b"repo token"),
            b"unknown",
            (b"Branch.set_tags_bytes",),
        )
        transport.mkdir("quack")
        transport = transport.clone("quack")
        branch = self.make_remote_branch(transport, client)
        self.lock_remote_branch(branch)

        class StubRealBranch:
            def __init__(self):
                self.calls = []

            def _set_tags_bytes(self, bytes):
                self.calls.append(("set_tags_bytes", bytes))

        real_branch = StubRealBranch()
        branch._real_branch = real_branch
        branch._set_tags_bytes(b"tags bytes")
        # Call a second time, to exercise the 'remote version already inferred'
        # code path.
        branch._set_tags_bytes(b"tags bytes")
        self.assertFinished(client)
        self.assertEqual([("set_tags_bytes", b"tags bytes")] * 2, real_branch.calls)


class TestBranchHeadsToFetch(RemoteBranchTestCase):
    def test_uses_last_revision_info_and_tags_by_default(self):
        transport = MemoryTransport()
        client = FakeClient(transport.base)
        client.add_expected_call(
            b"Branch.get_stacked_on_url", (b"quack/",), b"error", (b"NotStacked",)
        )
        client.add_expected_call(
            b"Branch.last_revision_info",
            (b"quack/",),
            b"success",
            (b"ok", b"1", b"rev-tip"),
        )
        client.add_expected_call(
            b"Branch.get_config_file", (b"quack/",), b"success", (b"ok",), b""
        )
        transport.mkdir("quack")
        transport = transport.clone("quack")
        branch = self.make_remote_branch(transport, client)
        result = branch.heads_to_fetch()
        self.assertFinished(client)
        self.assertEqual(({b"rev-tip"}, set()), result)

    def test_uses_last_revision_info_and_tags_when_set(self):
        transport = MemoryTransport()
        client = FakeClient(transport.base)
        client.add_expected_call(
            b"Branch.get_stacked_on_url", (b"quack/",), b"error", (b"NotStacked",)
        )
        client.add_expected_call(
            b"Branch.last_revision_info",
            (b"quack/",),
            b"success",
            (b"ok", b"1", b"rev-tip"),
        )
        client.add_expected_call(
            b"Branch.get_config_file",
            (b"quack/",),
            b"success",
            (b"ok",),
            b"branch.fetch_tags = True",
        )
        # XXX: this will break if the default format's serialization of tags
        # changes, or if the RPC for fetching tags changes from get_tags_bytes.
        client.add_expected_call(
            b"Branch.get_tags_bytes",
            (b"quack/",),
            b"success",
            (b"d5:tag-17:rev-foo5:tag-27:rev-bare",),
        )
        transport.mkdir("quack")
        transport = transport.clone("quack")
        branch = self.make_remote_branch(transport, client)
        result = branch.heads_to_fetch()
        self.assertFinished(client)
        self.assertEqual(({b"rev-tip"}, {b"rev-foo", b"rev-bar"}), result)

    def test_uses_rpc_for_formats_with_non_default_heads_to_fetch(self):
        transport = MemoryTransport()
        client = FakeClient(transport.base)
        client.add_expected_call(
            b"Branch.get_stacked_on_url", (b"quack/",), b"error", (b"NotStacked",)
        )
        client.add_expected_call(
            b"Branch.heads_to_fetch",
            (b"quack/",),
            b"success",
            ([b"tip"], [b"tagged-1", b"tagged-2"]),
        )
        transport.mkdir("quack")
        transport = transport.clone("quack")
        branch = self.make_remote_branch(transport, client)
        branch._format._use_default_local_heads_to_fetch = lambda: False
        result = branch.heads_to_fetch()
        self.assertFinished(client)
        self.assertEqual(({b"tip"}, {b"tagged-1", b"tagged-2"}), result)

    def make_branch_with_tags(self):
        self.setup_smart_server_with_call_log()
        # Make a branch with a single revision.
        builder = self.make_branch_builder("foo")
        builder.start_series()
        builder.build_snapshot(
            None, [("add", ("", b"root-id", "directory", ""))], revision_id=b"tip"
        )
        builder.finish_series()
        branch = builder.get_branch()
        # Add two tags to that branch
        branch.tags.set_tag("tag-1", b"rev-1")
        branch.tags.set_tag("tag-2", b"rev-2")
        return branch

    def test_backwards_compatible(self):
        br = self.make_branch_with_tags()
        br.get_config_stack().set("branch.fetch_tags", True)
        self.addCleanup(br.lock_read().unlock)
        # Disable the heads_to_fetch verb
        verb = b"Branch.heads_to_fetch"
        self.disable_verb(verb)
        self.reset_smart_call_log()
        result = br.heads_to_fetch()
        self.assertEqual(({b"tip"}, {b"rev-1", b"rev-2"}), result)
        self.assertEqual(
            [b"Branch.last_revision_info", b"Branch.get_tags_bytes"],
            [call.call.method for call in self.hpss_calls],
        )

    def test_backwards_compatible_no_tags(self):
        br = self.make_branch_with_tags()
        br.get_config_stack().set("branch.fetch_tags", False)
        self.addCleanup(br.lock_read().unlock)
        # Disable the heads_to_fetch verb
        verb = b"Branch.heads_to_fetch"
        self.disable_verb(verb)
        self.reset_smart_call_log()
        result = br.heads_to_fetch()
        self.assertEqual(({b"tip"}, set()), result)
        self.assertEqual(
            [b"Branch.last_revision_info"],
            [call.call.method for call in self.hpss_calls],
        )


class TestBranchLastRevisionInfo(RemoteBranchTestCase):
    def test_empty_branch(self):
        # in an empty branch we decode the response properly
        transport = MemoryTransport()
        client = FakeClient(transport.base)
        client.add_expected_call(
            b"Branch.get_stacked_on_url", (b"quack/",), b"error", (b"NotStacked",)
        )
        client.add_expected_call(
            b"Branch.last_revision_info",
            (b"quack/",),
            b"success",
            (b"ok", b"0", b"null:"),
        )
        transport.mkdir("quack")
        transport = transport.clone("quack")
        branch = self.make_remote_branch(transport, client)
        result = branch.last_revision_info()
        self.assertFinished(client)
        self.assertEqual((0, NULL_REVISION), result)

    def test_non_empty_branch(self):
        # in a non-empty branch we also decode the response properly
        revid = "\xc8".encode()
        transport = MemoryTransport()
        client = FakeClient(transport.base)
        client.add_expected_call(
            b"Branch.get_stacked_on_url", (b"kwaak/",), b"error", (b"NotStacked",)
        )
        client.add_expected_call(
            b"Branch.last_revision_info", (b"kwaak/",), b"success", (b"ok", b"2", revid)
        )
        transport.mkdir("kwaak")
        transport = transport.clone("kwaak")
        branch = self.make_remote_branch(transport, client)
        result = branch.last_revision_info()
        self.assertEqual((2, revid), result)


class TestBranch_get_stacked_on_url(TestRemote):
    """Test Branch._get_stacked_on_url rpc."""

    def test_get_stacked_on_invalid_url(self):
        # test that asking for a stacked on url the server can't access works.
        # This isn't perfect, but then as we're in the same process there
        # really isn't anything we can do to be 100% sure that the server
        # doesn't just open in - this test probably needs to be rewritten using
        # a spawn()ed server.
        stacked_branch = self.make_branch("stacked", format="1.9")
        self.make_branch("base", format="1.9")
        vfs_url = self.get_vfs_only_url("base")
        stacked_branch.set_stacked_on_url(vfs_url)
        transport = stacked_branch.controldir.root_transport
        client = FakeClient(transport.base)
        client.add_expected_call(
            b"Branch.get_stacked_on_url",
            (b"stacked/",),
            b"success",
            (b"ok", vfs_url.encode("utf-8")),
        )
        # XXX: Multiple calls are bad, this second call documents what is
        # today.
        client.add_expected_call(
            b"Branch.get_stacked_on_url",
            (b"stacked/",),
            b"success",
            (b"ok", vfs_url.encode("utf-8")),
        )
        bzrdir = RemoteBzrDir(transport, RemoteBzrDirFormat(), _client=client)
        repo_fmt = remote.RemoteRepositoryFormat()
        repo_fmt._custom_format = stacked_branch.repository._format
        branch = RemoteBranch(
            bzrdir, RemoteRepository(bzrdir, repo_fmt), _client=client
        )
        result = branch.get_stacked_on_url()
        self.assertEqual(vfs_url, result)

    def test_backwards_compatible(self):
        # like with bzr1.6 with no Branch.get_stacked_on_url rpc
        self.make_branch("base", format="1.6")
        stacked_branch = self.make_branch("stacked", format="1.6")
        stacked_branch.set_stacked_on_url("../base")
        client = FakeClient(self.get_url())
        branch_network_name = self.get_branch_format().network_name()
        client.add_expected_call(
            b"BzrDir.open_branchV3",
            (b"stacked/",),
            b"success",
            (b"branch", branch_network_name),
        )
        client.add_expected_call(
            b"BzrDir.find_repositoryV3",
            (b"stacked/",),
            b"success",
            (
                b"ok",
                b"",
                b"no",
                b"no",
                b"yes",
                stacked_branch.repository._format.network_name(),
            ),
        )
        # called twice, once from constructor and then again by us
        client.add_expected_call(
            b"Branch.get_stacked_on_url",
            (b"stacked/",),
            b"unknown",
            (b"Branch.get_stacked_on_url",),
        )
        client.add_expected_call(
            b"Branch.get_stacked_on_url",
            (b"stacked/",),
            b"unknown",
            (b"Branch.get_stacked_on_url",),
        )
        # this will also do vfs access, but that goes direct to the transport
        # and isn't seen by the FakeClient.
        bzrdir = RemoteBzrDir(
            self.get_transport("stacked"), RemoteBzrDirFormat(), _client=client
        )
        branch = bzrdir.open_branch()
        result = branch.get_stacked_on_url()
        self.assertEqual("../base", result)
        self.assertFinished(client)
        # it's in the fallback list both for the RemoteRepository and its vfs
        # repository
        self.assertEqual(1, len(branch.repository._fallback_repositories))
        self.assertEqual(
            1, len(branch.repository._real_repository._fallback_repositories)
        )

    def test_get_stacked_on_real_branch(self):
        self.make_branch("base")
        stacked_branch = self.make_branch("stacked")
        stacked_branch.set_stacked_on_url("../base")
        reference_format = self.get_repo_format()
        network_name = reference_format.network_name()
        client = FakeClient(self.get_url())
        branch_network_name = self.get_branch_format().network_name()
        client.add_expected_call(
            b"BzrDir.open_branchV3",
            (b"stacked/",),
            b"success",
            (b"branch", branch_network_name),
        )
        client.add_expected_call(
            b"BzrDir.find_repositoryV3",
            (b"stacked/",),
            b"success",
            (b"ok", b"", b"yes", b"no", b"yes", network_name),
        )
        # called twice, once from constructor and then again by us
        client.add_expected_call(
            b"Branch.get_stacked_on_url",
            (b"stacked/",),
            b"success",
            (b"ok", b"../base"),
        )
        client.add_expected_call(
            b"Branch.get_stacked_on_url",
            (b"stacked/",),
            b"success",
            (b"ok", b"../base"),
        )
        bzrdir = RemoteBzrDir(
            self.get_transport("stacked"), RemoteBzrDirFormat(), _client=client
        )
        branch = bzrdir.open_branch()
        result = branch.get_stacked_on_url()
        self.assertEqual("../base", result)
        self.assertFinished(client)
        # it's in the fallback list both for the RemoteRepository.
        self.assertEqual(1, len(branch.repository._fallback_repositories))
        # And we haven't had to construct a real repository.
        self.assertEqual(None, branch.repository._real_repository)


class TestBranchSetLastRevision(RemoteBranchTestCase):
    def test_set_empty(self):
        # _set_last_revision_info('null:') is translated to calling
        # Branch.set_last_revision(path, '') on the wire.
        transport = MemoryTransport()
        transport.mkdir("branch")
        transport = transport.clone("branch")

        client = FakeClient(transport.base)
        client.add_expected_call(
            b"Branch.get_stacked_on_url", (b"branch/",), b"error", (b"NotStacked",)
        )
        client.add_expected_call(
            b"Branch.lock_write",
            (b"branch/", b"", b""),
            b"success",
            (b"ok", b"branch token", b"repo token"),
        )
        client.add_expected_call(
            b"Branch.last_revision_info",
            (b"branch/",),
            b"success",
            (b"ok", b"0", b"null:"),
        )
        client.add_expected_call(
            b"Branch.set_last_revision",
            (
                b"branch/",
                b"branch token",
                b"repo token",
                b"null:",
            ),
            b"success",
            (b"ok",),
        )
        client.add_expected_call(
            b"Branch.unlock",
            (b"branch/", b"branch token", b"repo token"),
            b"success",
            (b"ok",),
        )
        branch = self.make_remote_branch(transport, client)
        branch.lock_write()
        result = branch._set_last_revision(NULL_REVISION)
        branch.unlock()
        self.assertEqual(None, result)
        self.assertFinished(client)

    def test_set_nonempty(self):
        # set_last_revision_info(N, rev-idN) is translated to calling
        # Branch.set_last_revision(path, rev-idN) on the wire.
        transport = MemoryTransport()
        transport.mkdir("branch")
        transport = transport.clone("branch")

        client = FakeClient(transport.base)
        client.add_expected_call(
            b"Branch.get_stacked_on_url", (b"branch/",), b"error", (b"NotStacked",)
        )
        client.add_expected_call(
            b"Branch.lock_write",
            (b"branch/", b"", b""),
            b"success",
            (b"ok", b"branch token", b"repo token"),
        )
        client.add_expected_call(
            b"Branch.last_revision_info",
            (b"branch/",),
            b"success",
            (b"ok", b"0", b"null:"),
        )
        lines = [b"rev-id2"]
        encoded_body = bz2.compress(b"\n".join(lines))
        client.add_success_response_with_body(encoded_body, b"ok")
        client.add_expected_call(
            b"Branch.set_last_revision",
            (
                b"branch/",
                b"branch token",
                b"repo token",
                b"rev-id2",
            ),
            b"success",
            (b"ok",),
        )
        client.add_expected_call(
            b"Branch.unlock",
            (b"branch/", b"branch token", b"repo token"),
            b"success",
            (b"ok",),
        )
        branch = self.make_remote_branch(transport, client)
        # Lock the branch, reset the record of remote calls.
        branch.lock_write()
        result = branch._set_last_revision(b"rev-id2")
        branch.unlock()
        self.assertEqual(None, result)
        self.assertFinished(client)

    def test_no_such_revision(self):
        transport = MemoryTransport()
        transport.mkdir("branch")
        transport = transport.clone("branch")
        # A response of 'NoSuchRevision' is translated into an exception.
        client = FakeClient(transport.base)
        client.add_expected_call(
            b"Branch.get_stacked_on_url", (b"branch/",), b"error", (b"NotStacked",)
        )
        client.add_expected_call(
            b"Branch.lock_write",
            (b"branch/", b"", b""),
            b"success",
            (b"ok", b"branch token", b"repo token"),
        )
        client.add_expected_call(
            b"Branch.last_revision_info",
            (b"branch/",),
            b"success",
            (b"ok", b"0", b"null:"),
        )
        # get_graph calls to construct the revision history, for the set_rh
        # hook
        lines = [b"rev-id"]
        encoded_body = bz2.compress(b"\n".join(lines))
        client.add_success_response_with_body(encoded_body, b"ok")
        client.add_expected_call(
            b"Branch.set_last_revision",
            (
                b"branch/",
                b"branch token",
                b"repo token",
                b"rev-id",
            ),
            b"error",
            (b"NoSuchRevision", b"rev-id"),
        )
        client.add_expected_call(
            b"Branch.unlock",
            (b"branch/", b"branch token", b"repo token"),
            b"success",
            (b"ok",),
        )

        branch = self.make_remote_branch(transport, client)
        branch.lock_write()
        self.assertRaises(errors.NoSuchRevision, branch._set_last_revision, b"rev-id")
        branch.unlock()
        self.assertFinished(client)

    def test_tip_change_rejected(self):
        """TipChangeRejected responses cause a TipChangeRejected exception to
        be raised.
        """
        transport = MemoryTransport()
        transport.mkdir("branch")
        transport = transport.clone("branch")
        client = FakeClient(transport.base)
        rejection_msg_unicode = "rejection message\N{INTERROBANG}"
        rejection_msg_utf8 = rejection_msg_unicode.encode("utf8")
        client.add_expected_call(
            b"Branch.get_stacked_on_url", (b"branch/",), b"error", (b"NotStacked",)
        )
        client.add_expected_call(
            b"Branch.lock_write",
            (b"branch/", b"", b""),
            b"success",
            (b"ok", b"branch token", b"repo token"),
        )
        client.add_expected_call(
            b"Branch.last_revision_info",
            (b"branch/",),
            b"success",
            (b"ok", b"0", b"null:"),
        )
        lines = [b"rev-id"]
        encoded_body = bz2.compress(b"\n".join(lines))
        client.add_success_response_with_body(encoded_body, b"ok")
        client.add_expected_call(
            b"Branch.set_last_revision",
            (
                b"branch/",
                b"branch token",
                b"repo token",
                b"rev-id",
            ),
            b"error",
            (b"TipChangeRejected", rejection_msg_utf8),
        )
        client.add_expected_call(
            b"Branch.unlock",
            (b"branch/", b"branch token", b"repo token"),
            b"success",
            (b"ok",),
        )
        branch = self.make_remote_branch(transport, client)
        branch.lock_write()
        # The 'TipChangeRejected' error response triggered by calling
        # set_last_revision_info causes a TipChangeRejected exception.
        err = self.assertRaises(
            errors.TipChangeRejected, branch._set_last_revision, b"rev-id"
        )
        # The UTF-8 message from the response has been decoded into a unicode
        # object.
        self.assertIsInstance(err.msg, str)
        self.assertEqual(rejection_msg_unicode, err.msg)
        branch.unlock()
        self.assertFinished(client)


class TestBranchSetLastRevisionInfo(RemoteBranchTestCase):
    def test_set_last_revision_info(self):
        # set_last_revision_info(num, b'rev-id') is translated to calling
        # Branch.set_last_revision_info(num, 'rev-id') on the wire.
        transport = MemoryTransport()
        transport.mkdir("branch")
        transport = transport.clone("branch")
        client = FakeClient(transport.base)
        # get_stacked_on_url
        client.add_error_response(b"NotStacked")
        # lock_write
        client.add_success_response(b"ok", b"branch token", b"repo token")
        # query the current revision
        client.add_success_response(b"ok", b"0", b"null:")
        # set_last_revision
        client.add_success_response(b"ok")
        # unlock
        client.add_success_response(b"ok")

        branch = self.make_remote_branch(transport, client)
        # Lock the branch, reset the record of remote calls.
        branch.lock_write()
        client._calls = []
        result = branch.set_last_revision_info(1234, b"a-revision-id")
        self.assertEqual(
            [
                ("call", b"Branch.last_revision_info", (b"branch/",)),
                (
                    "call",
                    b"Branch.set_last_revision_info",
                    (
                        b"branch/",
                        b"branch token",
                        b"repo token",
                        b"1234",
                        b"a-revision-id",
                    ),
                ),
            ],
            client._calls,
        )
        self.assertEqual(None, result)

    def test_no_such_revision(self):
        # A response of 'NoSuchRevision' is translated into an exception.
        transport = MemoryTransport()
        transport.mkdir("branch")
        transport = transport.clone("branch")
        client = FakeClient(transport.base)
        # get_stacked_on_url
        client.add_error_response(b"NotStacked")
        # lock_write
        client.add_success_response(b"ok", b"branch token", b"repo token")
        # set_last_revision
        client.add_error_response(b"NoSuchRevision", b"revid")
        # unlock
        client.add_success_response(b"ok")

        branch = self.make_remote_branch(transport, client)
        # Lock the branch, reset the record of remote calls.
        branch.lock_write()
        client._calls = []

        self.assertRaises(
            errors.NoSuchRevision, branch.set_last_revision_info, 123, b"revid"
        )
        branch.unlock()

    def test_backwards_compatibility(self):
        """If the server does not support the Branch.set_last_revision_info
        verb (which is new in 1.4), then the client falls back to VFS methods.
        """
        # This test is a little messy.  Unlike most tests in this file, it
        # doesn't purely test what a Remote* object sends over the wire, and
        # how it reacts to responses from the wire.  It instead relies partly
        # on asserting that the RemoteBranch will call
        # self._real_branch.set_last_revision_info(...).

        # First, set up our RemoteBranch with a FakeClient that raises
        # UnknownSmartMethod, and a StubRealBranch that logs how it is called.
        transport = MemoryTransport()
        transport.mkdir("branch")
        transport = transport.clone("branch")
        client = FakeClient(transport.base)
        client.add_expected_call(
            b"Branch.get_stacked_on_url", (b"branch/",), b"error", (b"NotStacked",)
        )
        client.add_expected_call(
            b"Branch.last_revision_info",
            (b"branch/",),
            b"success",
            (b"ok", b"0", b"null:"),
        )
        client.add_expected_call(
            b"Branch.set_last_revision_info",
            (
                b"branch/",
                b"branch token",
                b"repo token",
                b"1234",
                b"a-revision-id",
            ),
            b"unknown",
            b"Branch.set_last_revision_info",
        )

        branch = self.make_remote_branch(transport, client)

        class StubRealBranch:
            def __init__(self):
                self.calls = []

            def set_last_revision_info(self, revno, revision_id):
                self.calls.append(("set_last_revision_info", revno, revision_id))

            def _clear_cached_state(self):
                pass

        real_branch = StubRealBranch()
        branch._real_branch = real_branch
        self.lock_remote_branch(branch)

        # Call set_last_revision_info, and verify it behaved as expected.
        branch.set_last_revision_info(1234, b"a-revision-id")
        self.assertEqual(
            [("set_last_revision_info", 1234, b"a-revision-id")], real_branch.calls
        )
        self.assertFinished(client)

    def test_unexpected_error(self):
        # If the server sends an error the client doesn't understand, it gets
        # turned into an UnknownErrorFromSmartServer, which is presented as a
        # non-internal error to the user.
        transport = MemoryTransport()
        transport.mkdir("branch")
        transport = transport.clone("branch")
        client = FakeClient(transport.base)
        # get_stacked_on_url
        client.add_error_response(b"NotStacked")
        # lock_write
        client.add_success_response(b"ok", b"branch token", b"repo token")
        # set_last_revision
        client.add_error_response(b"UnexpectedError")
        # unlock
        client.add_success_response(b"ok")

        branch = self.make_remote_branch(transport, client)
        # Lock the branch, reset the record of remote calls.
        branch.lock_write()
        client._calls = []

        err = self.assertRaises(
            UnknownErrorFromSmartServer, branch.set_last_revision_info, 123, b"revid"
        )
        self.assertEqual((b"UnexpectedError",), err.error_tuple)
        branch.unlock()

    def test_tip_change_rejected(self):
        """TipChangeRejected responses cause a TipChangeRejected exception to
        be raised.
        """
        transport = MemoryTransport()
        transport.mkdir("branch")
        transport = transport.clone("branch")
        client = FakeClient(transport.base)
        # get_stacked_on_url
        client.add_error_response(b"NotStacked")
        # lock_write
        client.add_success_response(b"ok", b"branch token", b"repo token")
        # set_last_revision
        client.add_error_response(b"TipChangeRejected", b"rejection message")
        # unlock
        client.add_success_response(b"ok")

        branch = self.make_remote_branch(transport, client)
        # Lock the branch, reset the record of remote calls.
        branch.lock_write()
        self.addCleanup(branch.unlock)
        client._calls = []

        # The 'TipChangeRejected' error response triggered by calling
        # set_last_revision_info causes a TipChangeRejected exception.
        err = self.assertRaises(
            errors.TipChangeRejected, branch.set_last_revision_info, 123, b"revid"
        )
        self.assertEqual("rejection message", err.msg)


class TestBranchGetSetConfig(RemoteBranchTestCase):
    def test_get_branch_conf(self):
        # in an empty branch we decode the response properly
        client = FakeClient()
        client.add_expected_call(
            b"Branch.get_stacked_on_url",
            (b"memory:///",),
            b"error",
            (b"NotStacked",),
        )
        client.add_success_response_with_body(b"# config file body", b"ok")
        transport = MemoryTransport()
        branch = self.make_remote_branch(transport, client)
        config = branch.get_config()
        config.has_explicit_nickname()
        self.assertEqual(
            [
                ("call", b"Branch.get_stacked_on_url", (b"memory:///",)),
                ("call_expecting_body", b"Branch.get_config_file", (b"memory:///",)),
            ],
            client._calls,
        )

    def test_get_multi_line_branch_conf(self):
        # Make sure that multiple-line branch.conf files are supported
        #
        # https://bugs.launchpad.net/bzr/+bug/354075
        client = FakeClient()
        client.add_expected_call(
            b"Branch.get_stacked_on_url",
            (b"memory:///",),
            b"error",
            (b"NotStacked",),
        )
        client.add_success_response_with_body(b"a = 1\nb = 2\nc = 3\n", b"ok")
        transport = MemoryTransport()
        branch = self.make_remote_branch(transport, client)
        config = branch.get_config()
        self.assertEqual("2", config.get_user_option("b"))

    def test_set_option(self):
        client = FakeClient()
        client.add_expected_call(
            b"Branch.get_stacked_on_url",
            (b"memory:///",),
            b"error",
            (b"NotStacked",),
        )
        client.add_expected_call(
            b"Branch.lock_write",
            (b"memory:///", b"", b""),
            b"success",
            (b"ok", b"branch token", b"repo token"),
        )
        client.add_expected_call(
            b"Branch.set_config_option",
            (b"memory:///", b"branch token", b"repo token", b"foo", b"bar", b""),
            b"success",
            (),
        )
        client.add_expected_call(
            b"Branch.unlock",
            (b"memory:///", b"branch token", b"repo token"),
            b"success",
            (b"ok",),
        )
        transport = MemoryTransport()
        branch = self.make_remote_branch(transport, client)
        branch.lock_write()
        config = branch._get_config()
        config.set_option("foo", "bar")
        branch.unlock()
        self.assertFinished(client)

    def test_set_option_with_dict(self):
        client = FakeClient()
        client.add_expected_call(
            b"Branch.get_stacked_on_url",
            (b"memory:///",),
            b"error",
            (b"NotStacked",),
        )
        client.add_expected_call(
            b"Branch.lock_write",
            (b"memory:///", b"", b""),
            b"success",
            (b"ok", b"branch token", b"repo token"),
        )
        encoded_dict_value = b"d5:ascii1:a11:unicode \xe2\x8c\x9a3:\xe2\x80\xbde"
        client.add_expected_call(
            b"Branch.set_config_option_dict",
            (
                b"memory:///",
                b"branch token",
                b"repo token",
                encoded_dict_value,
                b"foo",
                b"",
            ),
            b"success",
            (),
        )
        client.add_expected_call(
            b"Branch.unlock",
            (b"memory:///", b"branch token", b"repo token"),
            b"success",
            (b"ok",),
        )
        transport = MemoryTransport()
        branch = self.make_remote_branch(transport, client)
        branch.lock_write()
        config = branch._get_config()
        config.set_option({"ascii": "a", "unicode \N{WATCH}": "\N{INTERROBANG}"}, "foo")
        branch.unlock()
        self.assertFinished(client)

    def test_set_option_with_bool(self):
        client = FakeClient()
        client.add_expected_call(
            b"Branch.get_stacked_on_url",
            (b"memory:///",),
            b"error",
            (b"NotStacked",),
        )
        client.add_expected_call(
            b"Branch.lock_write",
            (b"memory:///", b"", b""),
            b"success",
            (b"ok", b"branch token", b"repo token"),
        )
        client.add_expected_call(
            b"Branch.set_config_option",
            (b"memory:///", b"branch token", b"repo token", b"True", b"foo", b""),
            b"success",
            (),
        )
        client.add_expected_call(
            b"Branch.unlock",
            (b"memory:///", b"branch token", b"repo token"),
            b"success",
            (b"ok",),
        )
        transport = MemoryTransport()
        branch = self.make_remote_branch(transport, client)
        branch.lock_write()
        config = branch._get_config()
        config.set_option(True, "foo")
        branch.unlock()
        self.assertFinished(client)

    def test_backwards_compat_set_option(self):
        self.setup_smart_server_with_call_log()
        branch = self.make_branch(".")
        verb = b"Branch.set_config_option"
        self.disable_verb(verb)
        branch.lock_write()
        self.addCleanup(branch.unlock)
        self.reset_smart_call_log()
        branch._get_config().set_option("value", "name")
        self.assertLength(11, self.hpss_calls)
        self.assertEqual("value", branch._get_config().get_option("name"))

    def test_backwards_compat_set_option_with_dict(self):
        self.setup_smart_server_with_call_log()
        branch = self.make_branch(".")
        verb = b"Branch.set_config_option_dict"
        self.disable_verb(verb)
        branch.lock_write()
        self.addCleanup(branch.unlock)
        self.reset_smart_call_log()
        config = branch._get_config()
        value_dict = {"ascii": "a", "unicode \N{WATCH}": "\N{INTERROBANG}"}
        config.set_option(value_dict, "name")
        self.assertLength(11, self.hpss_calls)
        self.assertEqual(value_dict, branch._get_config().get_option("name"))


class TestBranchGetPutConfigStore(RemoteBranchTestCase):
    def test_get_branch_conf(self):
        # in an empty branch we decode the response properly
        client = FakeClient()
        client.add_expected_call(
            b"Branch.get_stacked_on_url",
            (b"memory:///",),
            b"error",
            (b"NotStacked",),
        )
        client.add_success_response_with_body(b"# config file body", b"ok")
        transport = MemoryTransport()
        branch = self.make_remote_branch(transport, client)
        config = branch.get_config_stack()
        config.get("email")
        config.get("log_format")
        self.assertEqual(
            [
                ("call", b"Branch.get_stacked_on_url", (b"memory:///",)),
                ("call_expecting_body", b"Branch.get_config_file", (b"memory:///",)),
            ],
            client._calls,
        )

    def test_set_branch_conf(self):
        client = FakeClient()
        client.add_expected_call(
            b"Branch.get_stacked_on_url",
            (b"memory:///",),
            b"error",
            (b"NotStacked",),
        )
        client.add_expected_call(
            b"Branch.lock_write",
            (b"memory:///", b"", b""),
            b"success",
            (b"ok", b"branch token", b"repo token"),
        )
        client.add_expected_call(
            b"Branch.get_config_file",
            (b"memory:///",),
            b"success",
            (b"ok",),
            b"# line 1\n",
        )
        client.add_expected_call(
            b"Branch.get_config_file",
            (b"memory:///",),
            b"success",
            (b"ok",),
            b"# line 1\n",
        )
        client.add_expected_call(
            b"Branch.put_config_file",
            (b"memory:///", b"branch token", b"repo token"),
            b"success",
            (b"ok",),
        )
        client.add_expected_call(
            b"Branch.unlock",
            (b"memory:///", b"branch token", b"repo token"),
            b"success",
            (b"ok",),
        )
        transport = MemoryTransport()
        branch = self.make_remote_branch(transport, client)
        branch.lock_write()
        config = branch.get_config_stack()
        config.set("email", "The Dude <lebowski@example.com>")
        branch.unlock()
        self.assertFinished(client)
        self.assertEqual(
            [
                ("call", b"Branch.get_stacked_on_url", (b"memory:///",)),
                ("call", b"Branch.lock_write", (b"memory:///", b"", b"")),
                ("call_expecting_body", b"Branch.get_config_file", (b"memory:///",)),
                ("call_expecting_body", b"Branch.get_config_file", (b"memory:///",)),
                (
                    "call_with_body_bytes_expecting_body",
                    b"Branch.put_config_file",
                    (b"memory:///", b"branch token", b"repo token"),
                    b"# line 1\nemail = The Dude <lebowski@example.com>\n",
                ),
                (
                    "call",
                    b"Branch.unlock",
                    (b"memory:///", b"branch token", b"repo token"),
                ),
            ],
            client._calls,
        )


class TestBranchLockWrite(RemoteBranchTestCase):
    def test_lock_write_unlockable(self):
        transport = MemoryTransport()
        client = FakeClient(transport.base)
        client.add_expected_call(
            b"Branch.get_stacked_on_url",
            (b"quack/",),
            b"error",
            (b"NotStacked",),
        )
        client.add_expected_call(
            b"Branch.lock_write",
            (b"quack/", b"", b""),
            b"error",
            (b"UnlockableTransport",),
        )
        transport.mkdir("quack")
        transport = transport.clone("quack")
        branch = self.make_remote_branch(transport, client)
        self.assertRaises(errors.UnlockableTransport, branch.lock_write)
        self.assertFinished(client)


class TestBranchRevisionIdToRevno(RemoteBranchTestCase):
    def test_simple(self):
        transport = MemoryTransport()
        client = FakeClient(transport.base)
        client.add_expected_call(
            b"Branch.get_stacked_on_url",
            (b"quack/",),
            b"error",
            (b"NotStacked",),
        )
        client.add_expected_call(
            b"Branch.revision_id_to_revno",
            (b"quack/", b"null:"),
            b"success",
            (
                b"ok",
                b"0",
            ),
        )
        client.add_expected_call(
            b"Branch.revision_id_to_revno",
            (b"quack/", b"unknown"),
            b"error",
            (
                b"NoSuchRevision",
                b"unknown",
            ),
        )
        transport.mkdir("quack")
        transport = transport.clone("quack")
        branch = self.make_remote_branch(transport, client)
        self.assertEqual(0, branch.revision_id_to_revno(b"null:"))
        self.assertRaises(
            errors.NoSuchRevision, branch.revision_id_to_revno, b"unknown"
        )
        self.assertFinished(client)

    def test_dotted(self):
        transport = MemoryTransport()
        client = FakeClient(transport.base)
        client.add_expected_call(
            b"Branch.get_stacked_on_url",
            (b"quack/",),
            b"error",
            (b"NotStacked",),
        )
        client.add_expected_call(
            b"Branch.revision_id_to_revno",
            (b"quack/", b"null:"),
            b"success",
            (
                b"ok",
                b"0",
            ),
        )
        client.add_expected_call(
            b"Branch.revision_id_to_revno",
            (b"quack/", b"unknown"),
            b"error",
            (
                b"NoSuchRevision",
                b"unknown",
            ),
        )
        transport.mkdir("quack")
        transport = transport.clone("quack")
        branch = self.make_remote_branch(transport, client)
        self.assertEqual((0,), branch.revision_id_to_dotted_revno(b"null:"))
        self.assertRaises(
            errors.NoSuchRevision, branch.revision_id_to_dotted_revno, b"unknown"
        )
        self.assertFinished(client)

    def test_ghost_revid(self):
        transport = MemoryTransport()
        client = FakeClient(transport.base)
        client.add_expected_call(
            b"Branch.get_stacked_on_url",
            (b"quack/",),
            b"error",
            (b"NotStacked",),
        )
        # Some older versions of bzr/brz didn't explicitly return
        # GhostRevisionsHaveNoRevno
        client.add_expected_call(
            b"Branch.revision_id_to_revno",
            (b"quack/", b"revid"),
            b"error",
            (
                b"error",
                b"GhostRevisionsHaveNoRevno",
                b"The reivison {revid} was not found because there was "
                b"a ghost at {ghost-revid}",
            ),
        )
        client.add_expected_call(
            b"Branch.revision_id_to_revno",
            (b"quack/", b"revid"),
            b"error",
            (
                b"GhostRevisionsHaveNoRevno",
                b"revid",
                b"ghost-revid",
            ),
        )
        transport.mkdir("quack")
        transport = transport.clone("quack")
        branch = self.make_remote_branch(transport, client)
        self.assertRaises(
            GhostRevisionsHaveNoRevno,
            branch.revision_id_to_dotted_revno,
            b"revid",
        )
        self.assertRaises(
            GhostRevisionsHaveNoRevno,
            branch.revision_id_to_dotted_revno,
            b"revid",
        )
        self.assertFinished(client)

    def test_dotted_no_smart_verb(self):
        self.setup_smart_server_with_call_log()
        branch = self.make_branch(".")
        self.disable_verb(b"Branch.revision_id_to_revno")
        self.reset_smart_call_log()
        self.assertEqual((0,), branch.revision_id_to_dotted_revno(b"null:"))
        self.assertLength(8, self.hpss_calls)


class TestBzrDirGetSetConfig(RemoteBzrDirTestCase):
    def test__get_config(self):
        client = FakeClient()
        client.add_success_response_with_body(b"default_stack_on = /\n", b"ok")
        transport = MemoryTransport()
        bzrdir = self.make_remote_bzrdir(transport, client)
        config = bzrdir.get_config()
        self.assertEqual("/", config.get_default_stack_on())
        self.assertEqual(
            [("call_expecting_body", b"BzrDir.get_config_file", (b"memory:///",))],
            client._calls,
        )

    def test_set_option_uses_vfs(self):
        self.setup_smart_server_with_call_log()
        bzrdir = self.make_controldir(".")
        self.reset_smart_call_log()
        config = bzrdir.get_config()
        config.set_default_stack_on("/")
        self.assertLength(4, self.hpss_calls)

    def test_backwards_compat_get_option(self):
        self.setup_smart_server_with_call_log()
        bzrdir = self.make_controldir(".")
        verb = b"BzrDir.get_config_file"
        self.disable_verb(verb)
        self.reset_smart_call_log()
        self.assertEqual(None, bzrdir._get_config().get_option("default_stack_on"))
        self.assertLength(4, self.hpss_calls)


class TestTransportIsReadonly(tests.TestCase):
    def test_true(self):
        client = FakeClient()
        client.add_success_response(b"yes")
        transport = RemoteTransport("bzr://example.com/", medium=False, _client=client)
        self.assertEqual(True, transport.is_readonly())
        self.assertEqual([("call", b"Transport.is_readonly", ())], client._calls)

    def test_false(self):
        client = FakeClient()
        client.add_success_response(b"no")
        transport = RemoteTransport("bzr://example.com/", medium=False, _client=client)
        self.assertEqual(False, transport.is_readonly())
        self.assertEqual([("call", b"Transport.is_readonly", ())], client._calls)

    def test_error_from_old_server(self):
        """Bzr 0.15 and earlier servers don't recognise the is_readonly verb.

        Clients should treat it as a "no" response, because is_readonly is only
        advisory anyway (a transport could be read-write, but then the
        underlying filesystem could be readonly anyway).
        """
        client = FakeClient()
        client.add_unknown_method_response(b"Transport.is_readonly")
        transport = RemoteTransport("bzr://example.com/", medium=False, _client=client)
        self.assertEqual(False, transport.is_readonly())
        self.assertEqual([("call", b"Transport.is_readonly", ())], client._calls)


class TestTransportMkdir(tests.TestCase):
    def test_permissiondenied(self):
        client = FakeClient()
        client.add_error_response(b"PermissionDenied", b"remote path", b"extra")
        transport = RemoteTransport("bzr://example.com/", medium=False, _client=client)
        exc = self.assertRaises(errors.PermissionDenied, transport.mkdir, "client path")
        expected_error = errors.PermissionDenied("/client path", "extra")
        self.assertEqual(expected_error, exc)


class TestRemoteSSHTransportAuthentication(tests.TestCaseInTempDir):
    def test_defaults_to_none(self):
        t = RemoteSSHTransport("bzr+ssh://example.com")
        self.assertIs(None, t._get_credentials()[0])

    def test_uses_authentication_config(self):
        conf = config.AuthenticationConfig()
        conf._get_config().update(
            {"bzr+sshtest": {"scheme": "ssh", "user": "bar", "host": "example.com"}}
        )
        conf._save()
        t = RemoteSSHTransport("bzr+ssh://example.com")
        self.assertEqual("bar", t._get_credentials()[0])


class TestRemoteRepository(TestRemote):
    """Base for testing RemoteRepository protocol usage.

    These tests contain frozen requests and responses.  We want any changes to
    what is sent or expected to be require a thoughtful update to these tests
    because they might break compatibility with different-versioned servers.
    """

    def setup_fake_client_and_repository(self, transport_path):
        """Create the fake client and repository for testing with.

        There's no real server here; we just have canned responses sent
        back one by one.

        :param transport_path: Path below the root of the MemoryTransport
            where the repository will be created.
        """
        transport = MemoryTransport()
        transport.mkdir(transport_path)
        client = FakeClient(transport.base)
        transport = transport.clone(transport_path)
        # we do not want bzrdir to make any remote calls
        bzrdir = RemoteBzrDir(transport, RemoteBzrDirFormat(), _client=False)
        repo = RemoteRepository(bzrdir, None, _client=client)
        return repo, client


def remoted_description(format):
    return "Remote: " + format.get_format_description()


class TestBranchFormat(tests.TestCase):
    def test_get_format_description(self):
        remote_format = RemoteBranchFormat()
        real_format = branch.format_registry.get_default()
        remote_format._network_name = real_format.network_name()
        self.assertEqual(
            remoted_description(real_format), remote_format.get_format_description()
        )


class TestRepositoryFormat(TestRemoteRepository):
    def test_fast_delta(self):
        true_name = groupcompress_repo.RepositoryFormat2a().network_name()
        true_format = RemoteRepositoryFormat()
        true_format._network_name = true_name
        self.assertEqual(True, true_format.fast_deltas)
        false_name = knitpack_repo.RepositoryFormatKnitPack1().network_name()
        false_format = RemoteRepositoryFormat()
        false_format._network_name = false_name
        self.assertEqual(False, false_format.fast_deltas)

    def test_get_format_description(self):
        remote_repo_format = RemoteRepositoryFormat()
        real_format = repository.format_registry.get_default()
        remote_repo_format._network_name = real_format.network_name()
        self.assertEqual(
            remoted_description(real_format),
            remote_repo_format.get_format_description(),
        )


class TestRepositoryAllRevisionIds(TestRemoteRepository):
    def test_empty(self):
        transport_path = "quack"
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_success_response_with_body(b"", b"ok")
        self.assertEqual([], repo.all_revision_ids())
        self.assertEqual(
            [("call_expecting_body", b"Repository.all_revision_ids", (b"quack/",))],
            client._calls,
        )

    def test_with_some_content(self):
        transport_path = "quack"
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_success_response_with_body(b"rev1\nrev2\nanotherrev\n", b"ok")
        self.assertEqual(
            {b"rev1", b"rev2", b"anotherrev"}, set(repo.all_revision_ids())
        )
        self.assertEqual(
            [("call_expecting_body", b"Repository.all_revision_ids", (b"quack/",))],
            client._calls,
        )


class TestRepositoryGatherStats(TestRemoteRepository):
    def test_revid_none(self):
        # ('ok',), body with revisions and size
        transport_path = "quack"
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_success_response_with_body(b"revisions: 2\nsize: 18\n", b"ok")
        result = repo.gather_stats(None)
        self.assertEqual(
            [
                (
                    "call_expecting_body",
                    b"Repository.gather_stats",
                    (b"quack/", b"", b"no"),
                )
            ],
            client._calls,
        )
        self.assertEqual({"revisions": 2, "size": 18}, result)

    def test_revid_no_committers(self):
        # ('ok',), body without committers
        body = (
            b"firstrev: 123456.300 3600\n"
            b"latestrev: 654231.400 0\n"
            b"revisions: 2\n"
            b"size: 18\n"
        )
        transport_path = "quick"
        revid = "\xc8".encode()
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_success_response_with_body(body, b"ok")
        result = repo.gather_stats(revid)
        self.assertEqual(
            [
                (
                    "call_expecting_body",
                    b"Repository.gather_stats",
                    (b"quick/", revid, b"no"),
                )
            ],
            client._calls,
        )
        self.assertEqual(
            {
                "revisions": 2,
                "size": 18,
                "firstrev": (123456.300, 3600),
                "latestrev": (654231.400, 0),
            },
            result,
        )

    def test_revid_with_committers(self):
        # ('ok',), body with committers
        body = (
            b"committers: 128\n"
            b"firstrev: 123456.300 3600\n"
            b"latestrev: 654231.400 0\n"
            b"revisions: 2\n"
            b"size: 18\n"
        )
        transport_path = "buick"
        revid = "\xc8".encode()
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_success_response_with_body(body, b"ok")
        result = repo.gather_stats(revid, True)
        self.assertEqual(
            [
                (
                    "call_expecting_body",
                    b"Repository.gather_stats",
                    (b"buick/", revid, b"yes"),
                )
            ],
            client._calls,
        )
        self.assertEqual(
            {
                "revisions": 2,
                "size": 18,
                "committers": 128,
                "firstrev": (123456.300, 3600),
                "latestrev": (654231.400, 0),
            },
            result,
        )


class TestRepositoryBreakLock(TestRemoteRepository):
    def test_break_lock(self):
        transport_path = "quack"
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_success_response(b"ok")
        repo.break_lock()
        self.assertEqual(
            [("call", b"Repository.break_lock", (b"quack/",))], client._calls
        )


class TestRepositoryGetSerializerFormat(TestRemoteRepository):
    def test_get_serializer_format(self):
        transport_path = "hill"
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_success_response(b"ok", b"7")
        self.assertEqual(b"7", repo.get_serializer_format())
        self.assertEqual(
            [("call", b"VersionedFileRepository.get_serializer_format", (b"hill/",))],
            client._calls,
        )


class TestRepositoryReconcile(TestRemoteRepository):
    def test_reconcile(self):
        transport_path = "hill"
        repo, client = self.setup_fake_client_and_repository(transport_path)
        body = b"garbage_inventories: 2\ninconsistent_parents: 3\n"
        client.add_expected_call(
            b"Repository.lock_write", (b"hill/", b""), b"success", (b"ok", b"a token")
        )
        client.add_success_response_with_body(body, b"ok")
        reconciler = repo.reconcile()
        self.assertEqual(
            [
                ("call", b"Repository.lock_write", (b"hill/", b"")),
                (
                    "call_expecting_body",
                    b"Repository.reconcile",
                    (b"hill/", b"a token"),
                ),
            ],
            client._calls,
        )
        self.assertEqual(2, reconciler.garbage_inventories)
        self.assertEqual(3, reconciler.inconsistent_parents)


class TestRepositoryGetRevisionSignatureText(TestRemoteRepository):
    def test_text(self):
        # ('ok',), body with signature text
        transport_path = "quack"
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_success_response_with_body(b"THETEXT", b"ok")
        self.assertEqual(b"THETEXT", repo.get_signature_text(b"revid"))
        self.assertEqual(
            [
                (
                    "call_expecting_body",
                    b"Repository.get_revision_signature_text",
                    (b"quack/", b"revid"),
                )
            ],
            client._calls,
        )

    def test_no_signature(self):
        transport_path = "quick"
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_error_response(b"nosuchrevision", b"unknown")
        self.assertRaises(errors.NoSuchRevision, repo.get_signature_text, b"unknown")
        self.assertEqual(
            [
                (
                    "call_expecting_body",
                    b"Repository.get_revision_signature_text",
                    (b"quick/", b"unknown"),
                )
            ],
            client._calls,
        )


class TestRepositoryGetGraph(TestRemoteRepository):
    def test_get_graph(self):
        # get_graph returns a graph with a custom parents provider.
        transport_path = "quack"
        repo, client = self.setup_fake_client_and_repository(transport_path)
        graph = repo.get_graph()
        self.assertNotEqual(graph._parents_provider, repo)


class TestRepositoryAddSignatureText(TestRemoteRepository):
    def test_add_signature_text(self):
        transport_path = "quack"
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_expected_call(
            b"Repository.lock_write", (b"quack/", b""), b"success", (b"ok", b"a token")
        )
        client.add_expected_call(
            b"Repository.start_write_group",
            (b"quack/", b"a token"),
            b"success",
            (b"ok", (b"token1",)),
        )
        client.add_expected_call(
            b"Repository.add_signature_text",
            (b"quack/", b"a token", b"rev1", b"token1"),
            b"success",
            (b"ok",),
            None,
        )
        repo.lock_write()
        repo.start_write_group()
        self.assertIs(None, repo.add_signature_text(b"rev1", b"every bloody emperor"))
        self.assertEqual(
            (
                "call_with_body_bytes_expecting_body",
                b"Repository.add_signature_text",
                (b"quack/", b"a token", b"rev1", b"token1"),
                b"every bloody emperor",
            ),
            client._calls[-1],
        )


class TestRepositoryGetParentMap(TestRemoteRepository):
    def test_get_parent_map_caching(self):
        # get_parent_map returns from cache until unlock()
        # setup a reponse with two revisions
        r1 = "\u0e33".encode()
        r2 = "\u0dab".encode()
        lines = [b" ".join([r2, r1]), r1]
        encoded_body = bz2.compress(b"\n".join(lines))

        transport_path = "quack"
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_success_response_with_body(encoded_body, b"ok")
        client.add_success_response_with_body(encoded_body, b"ok")
        repo.lock_read()
        graph = repo.get_graph()
        parents = graph.get_parent_map([r2])
        self.assertEqual({r2: (r1,)}, parents)
        # locking and unlocking deeper should not reset
        repo.lock_read()
        repo.unlock()
        parents = graph.get_parent_map([r1])
        self.assertEqual({r1: (NULL_REVISION,)}, parents)
        self.assertEqual(
            [
                (
                    "call_with_body_bytes_expecting_body",
                    b"Repository.get_parent_map",
                    (b"quack/", b"include-missing:", r2),
                    b"\n\n0",
                )
            ],
            client._calls,
        )
        repo.unlock()
        # now we call again, and it should use the second response.
        repo.lock_read()
        graph = repo.get_graph()
        parents = graph.get_parent_map([r1])
        self.assertEqual({r1: (NULL_REVISION,)}, parents)
        self.assertEqual(
            [
                (
                    "call_with_body_bytes_expecting_body",
                    b"Repository.get_parent_map",
                    (b"quack/", b"include-missing:", r2),
                    b"\n\n0",
                ),
                (
                    "call_with_body_bytes_expecting_body",
                    b"Repository.get_parent_map",
                    (b"quack/", b"include-missing:", r1),
                    b"\n\n0",
                ),
            ],
            client._calls,
        )
        repo.unlock()

    def test_get_parent_map_reconnects_if_unknown_method(self):
        transport_path = "quack"
        rev_id = b"revision-id"
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_unknown_method_response(b"Repository.get_parent_map")
        client.add_success_response_with_body(rev_id, b"ok")
        self.assertFalse(client._medium._is_remote_before((1, 2)))
        parents = repo.get_parent_map([rev_id])
        self.assertEqual(
            [
                (
                    "call_with_body_bytes_expecting_body",
                    b"Repository.get_parent_map",
                    (b"quack/", b"include-missing:", rev_id),
                    b"\n\n0",
                ),
                ("disconnect medium",),
                (
                    "call_expecting_body",
                    b"Repository.get_revision_graph",
                    (b"quack/", b""),
                ),
            ],
            client._calls,
        )
        # The medium is now marked as being connected to an older server
        self.assertTrue(client._medium._is_remote_before((1, 2)))
        self.assertEqual({rev_id: (b"null:",)}, parents)

    def test_get_parent_map_fallback_parentless_node(self):
        """get_parent_map falls back to get_revision_graph on old servers.  The
        results from get_revision_graph are tweaked to match the get_parent_map
        API.

        Specifically, a {key: ()} result from get_revision_graph means "no
        parents" for that key, which in get_parent_map results should be
        represented as {key: ('null:',)}.

        This is the test for https://bugs.launchpad.net/bzr/+bug/214894
        """
        rev_id = b"revision-id"
        transport_path = "quack"
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_success_response_with_body(rev_id, b"ok")
        client._medium._remember_remote_is_before((1, 2))
        parents = repo.get_parent_map([rev_id])
        self.assertEqual(
            [
                (
                    "call_expecting_body",
                    b"Repository.get_revision_graph",
                    (b"quack/", b""),
                )
            ],
            client._calls,
        )
        self.assertEqual({rev_id: (b"null:",)}, parents)

    def test_get_parent_map_unexpected_response(self):
        repo, client = self.setup_fake_client_and_repository("path")
        client.add_success_response(b"something unexpected!")
        self.assertRaises(
            errors.UnexpectedSmartServerResponse,
            repo.get_parent_map,
            [b"a-revision-id"],
        )

    def test_get_parent_map_negative_caches_missing_keys(self):
        self.setup_smart_server_with_call_log()
        repo = self.make_repository("foo")
        self.assertIsInstance(repo, RemoteRepository)
        repo.lock_read()
        self.addCleanup(repo.unlock)
        self.reset_smart_call_log()
        graph = repo.get_graph()
        self.assertEqual({}, graph.get_parent_map([b"some-missing", b"other-missing"]))
        self.assertLength(1, self.hpss_calls)
        # No call if we repeat this
        self.reset_smart_call_log()
        graph = repo.get_graph()
        self.assertEqual({}, graph.get_parent_map([b"some-missing", b"other-missing"]))
        self.assertLength(0, self.hpss_calls)
        # Asking for more unknown keys makes a request.
        self.reset_smart_call_log()
        graph = repo.get_graph()
        self.assertEqual(
            {},
            graph.get_parent_map([b"some-missing", b"other-missing", b"more-missing"]),
        )
        self.assertLength(1, self.hpss_calls)

    def disableExtraResults(self):
        self.overrideAttr(SmartServerRepositoryGetParentMap, "no_extra_results", True)

    def test_null_cached_missing_and_stop_key(self):
        self.setup_smart_server_with_call_log()
        # Make a branch with a single revision.
        builder = self.make_branch_builder("foo")
        builder.start_series()
        builder.build_snapshot(
            None, [("add", ("", b"root-id", "directory", ""))], revision_id=b"first"
        )
        builder.finish_series()
        branch = builder.get_branch()
        repo = branch.repository
        self.assertIsInstance(repo, RemoteRepository)
        # Stop the server from sending extra results.
        self.disableExtraResults()
        repo.lock_read()
        self.addCleanup(repo.unlock)
        self.reset_smart_call_log()
        graph = repo.get_graph()
        # Query for b'first' and b'null:'.  Because b'null:' is a parent of
        # 'first' it will be a candidate for the stop_keys of subsequent
        # requests, and because b'null:' was queried but not returned it will
        # be cached as missing.
        self.assertEqual(
            {b"first": (b"null:",)}, graph.get_parent_map([b"first", b"null:"])
        )
        # Now query for another key.  This request will pass along a recipe of
        # start and stop keys describing the already cached results, and this
        # recipe's revision count must be correct (or else it will trigger an
        # error from the server).
        self.assertEqual({}, graph.get_parent_map([b"another-key"]))
        # This assertion guards against disableExtraResults silently failing to
        # work, thus invalidating the test.
        self.assertLength(2, self.hpss_calls)

    def test_get_parent_map_gets_ghosts_from_result(self):
        # asking for a revision should negatively cache close ghosts in its
        # ancestry.
        self.setup_smart_server_with_call_log()
        tree = self.make_branch_and_memory_tree("foo")
        with tree.lock_write():
            builder = treebuilder.TreeBuilder()
            builder.start_tree(tree)
            builder.build([])
            builder.finish_tree()
            tree.set_parent_ids([b"non-existant"], allow_leftmost_as_ghost=True)
            rev_id = tree.commit("")
        tree.lock_read()
        self.addCleanup(tree.unlock)
        repo = tree.branch.repository
        self.assertIsInstance(repo, RemoteRepository)
        # ask for rev_id
        repo.get_parent_map([rev_id])
        self.reset_smart_call_log()
        # Now asking for rev_id's ghost parent should not make calls
        self.assertEqual({}, repo.get_parent_map([b"non-existant"]))
        self.assertLength(0, self.hpss_calls)

    def test_exposes_get_cached_parent_map(self):
        """RemoteRepository exposes get_cached_parent_map from
        _unstacked_provider.
        """
        r1 = "\u0e33".encode()
        r2 = "\u0dab".encode()
        lines = [b" ".join([r2, r1]), r1]
        encoded_body = bz2.compress(b"\n".join(lines))

        transport_path = "quack"
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_success_response_with_body(encoded_body, b"ok")
        repo.lock_read()
        # get_cached_parent_map should *not* trigger an RPC
        self.assertEqual({}, repo.get_cached_parent_map([r1]))
        self.assertEqual([], client._calls)
        self.assertEqual({r2: (r1,)}, repo.get_parent_map([r2]))
        self.assertEqual({r1: (NULL_REVISION,)}, repo.get_cached_parent_map([r1]))
        self.assertEqual(
            [
                (
                    "call_with_body_bytes_expecting_body",
                    b"Repository.get_parent_map",
                    (b"quack/", b"include-missing:", r2),
                    b"\n\n0",
                )
            ],
            client._calls,
        )
        repo.unlock()


class TestGetParentMapAllowsNew(tests.TestCaseWithTransport):
    def test_allows_new_revisions(self):
        """get_parent_map's results can be updated by commit."""
        smart_server = test_server.SmartTCPServer_for_testing()
        self.start_server(smart_server)
        self.make_branch("branch")
        branch = Branch.open(smart_server.get_url() + "/branch")
        tree = branch.create_checkout("tree", lightweight=True)
        tree.lock_write()
        self.addCleanup(tree.unlock)
        graph = tree.branch.repository.get_graph()
        # This provides an opportunity for the missing rev-id to be cached.
        self.assertEqual({}, graph.get_parent_map([b"rev1"]))
        tree.commit("message", rev_id=b"rev1")
        graph = tree.branch.repository.get_graph()
        self.assertEqual({b"rev1": (b"null:",)}, graph.get_parent_map([b"rev1"]))


class TestRepositoryGetRevisions(TestRemoteRepository):
    def test_hpss_missing_revision(self):
        transport_path = "quack"
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_success_response_with_body(b"", b"ok", b"10")
        self.assertRaises(
            errors.NoSuchRevision, repo.get_revisions, [b"somerev1", b"anotherrev2"]
        )
        self.assertEqual(
            [
                (
                    "call_with_body_bytes_expecting_body",
                    b"Repository.iter_revisions",
                    (b"quack/",),
                    b"somerev1\nanotherrev2",
                )
            ],
            client._calls,
        )

    def test_hpss_get_single_revision(self):
        transport_path = "quack"
        repo, client = self.setup_fake_client_and_repository(transport_path)
        somerev1 = Revision(
            b"somerev1",
            committer="Joe Committer <joe@example.com>",
            timestamp=1321828927,
            timezone=-60,
            inventory_sha1=b"691b39be74c67b1212a75fcb19c433aaed903c2b",
            parent_ids=[],
            message="Message",
            properties={},
        )
        body = zlib.compress(
            b"".join(revision_bencode_serializer.write_revision_to_lines(somerev1))
        )
        # Split up body into two bits to make sure the zlib compression object
        # gets data fed twice.
        client.add_success_response_with_body([body[:10], body[10:]], b"ok", b"10")
        revs = repo.get_revisions([b"somerev1"])
        self.assertEqual(revs, [somerev1])
        self.assertEqual(
            [
                (
                    "call_with_body_bytes_expecting_body",
                    b"Repository.iter_revisions",
                    (b"quack/",),
                    b"somerev1",
                )
            ],
            client._calls,
        )


class TestRepositoryGetRevisionGraph(TestRemoteRepository):
    def test_null_revision(self):
        # a null revision has the predictable result {}, we should have no wire
        # traffic when calling it with this argument
        transport_path = "empty"
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_success_response(b"notused")
        # actual RemoteRepository.get_revision_graph is gone, but there's an
        # equivalent private method for testing
        result = repo._get_revision_graph(NULL_REVISION)
        self.assertEqual([], client._calls)
        self.assertEqual({}, result)

    def test_none_revision(self):
        # with none we want the entire graph
        r1 = "\u0e33".encode()
        r2 = "\u0dab".encode()
        lines = [b" ".join([r2, r1]), r1]
        encoded_body = b"\n".join(lines)

        transport_path = "sinhala"
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_success_response_with_body(encoded_body, b"ok")
        # actual RemoteRepository.get_revision_graph is gone, but there's an
        # equivalent private method for testing
        result = repo._get_revision_graph(None)
        self.assertEqual(
            [
                (
                    "call_expecting_body",
                    b"Repository.get_revision_graph",
                    (b"sinhala/", b""),
                )
            ],
            client._calls,
        )
        self.assertEqual({r1: (), r2: (r1,)}, result)

    def test_specific_revision(self):
        # with a specific revision we want the graph for that
        # with none we want the entire graph
        r11 = "\u0e33".encode()
        r12 = "\xc9".encode()
        r2 = "\u0dab".encode()
        lines = [b" ".join([r2, r11, r12]), r11, r12]
        encoded_body = b"\n".join(lines)

        transport_path = "sinhala"
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_success_response_with_body(encoded_body, b"ok")
        result = repo._get_revision_graph(r2)
        self.assertEqual(
            [
                (
                    "call_expecting_body",
                    b"Repository.get_revision_graph",
                    (b"sinhala/", r2),
                )
            ],
            client._calls,
        )
        self.assertEqual(
            {
                r11: (),
                r12: (),
                r2: (r11, r12),
            },
            result,
        )

    def test_no_such_revision(self):
        revid = b"123"
        transport_path = "sinhala"
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_error_response(b"nosuchrevision", revid)
        # also check that the right revision is reported in the error
        self.assertRaises(errors.NoSuchRevision, repo._get_revision_graph, revid)
        self.assertEqual(
            [
                (
                    "call_expecting_body",
                    b"Repository.get_revision_graph",
                    (b"sinhala/", revid),
                )
            ],
            client._calls,
        )

    def test_unexpected_error(self):
        revid = b"123"
        transport_path = "sinhala"
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_error_response(b"AnUnexpectedError")
        e = self.assertRaises(
            UnknownErrorFromSmartServer, repo._get_revision_graph, revid
        )
        self.assertEqual((b"AnUnexpectedError",), e.error_tuple)


class TestRepositoryGetRevIdForRevno(TestRemoteRepository):
    def test_ok(self):
        repo, client = self.setup_fake_client_and_repository("quack")
        client.add_expected_call(
            b"Repository.get_rev_id_for_revno",
            (b"quack/", 5, (42, b"rev-foo")),
            b"success",
            (b"ok", b"rev-five"),
        )
        result = repo.get_rev_id_for_revno(5, (42, b"rev-foo"))
        self.assertEqual((True, b"rev-five"), result)
        self.assertFinished(client)

    def test_history_incomplete(self):
        repo, client = self.setup_fake_client_and_repository("quack")
        client.add_expected_call(
            b"Repository.get_rev_id_for_revno",
            (b"quack/", 5, (42, b"rev-foo")),
            b"success",
            (b"history-incomplete", 10, b"rev-ten"),
        )
        result = repo.get_rev_id_for_revno(5, (42, b"rev-foo"))
        self.assertEqual((False, (10, b"rev-ten")), result)
        self.assertFinished(client)

    def test_history_incomplete_with_fallback(self):
        """A 'history-incomplete' response causes the fallback repository to be
        queried too, if one is set.
        """
        # Make a repo with a fallback repo, both using a FakeClient.
        format = remote.response_tuple_to_repo_format(
            (b"yes", b"no", b"yes", self.get_repo_format().network_name())
        )
        repo, client = self.setup_fake_client_and_repository("quack")
        repo._format = format
        fallback_repo, ignored = self.setup_fake_client_and_repository("fallback")
        fallback_repo._client = client
        fallback_repo._format = format
        repo.add_fallback_repository(fallback_repo)
        # First the client should ask the primary repo
        client.add_expected_call(
            b"Repository.get_rev_id_for_revno",
            (b"quack/", 1, (42, b"rev-foo")),
            b"success",
            (b"history-incomplete", 2, b"rev-two"),
        )
        # Then it should ask the fallback, using revno/revid from the
        # history-incomplete response as the known revno/revid.
        client.add_expected_call(
            b"Repository.get_rev_id_for_revno",
            (b"fallback/", 1, (2, b"rev-two")),
            b"success",
            (b"ok", b"rev-one"),
        )
        result = repo.get_rev_id_for_revno(1, (42, b"rev-foo"))
        self.assertEqual((True, b"rev-one"), result)
        self.assertFinished(client)

    def test_nosuchrevision(self):
        # 'nosuchrevision' is returned when the known-revid is not found in the
        # remote repo.  The client translates that response to NoSuchRevision.
        repo, client = self.setup_fake_client_and_repository("quack")
        client.add_expected_call(
            b"Repository.get_rev_id_for_revno",
            (b"quack/", 5, (42, b"rev-foo")),
            b"error",
            (b"nosuchrevision", b"rev-foo"),
        )
        self.assertRaises(
            errors.NoSuchRevision, repo.get_rev_id_for_revno, 5, (42, b"rev-foo")
        )
        self.assertFinished(client)

    def test_outofbounds(self):
        repo, client = self.setup_fake_client_and_repository("quack")
        client.add_expected_call(
            b"Repository.get_rev_id_for_revno",
            (b"quack/", 43, (42, b"rev-foo")),
            b"error",
            (b"revno-outofbounds", 43, 0, 42),
        )
        self.assertRaises(
            errors.RevnoOutOfBounds, repo.get_rev_id_for_revno, 43, (42, b"rev-foo")
        )
        self.assertFinished(client)

    def test_outofbounds_old(self):
        # Older versions of bzr didn't support RevnoOutOfBounds
        repo, client = self.setup_fake_client_and_repository("quack")
        client.add_expected_call(
            b"Repository.get_rev_id_for_revno",
            (b"quack/", 43, (42, b"rev-foo")),
            b"error",
            (
                b"error",
                b"ValueError",
                b"requested revno (43) is later than given known revno (42)",
            ),
        )
        self.assertRaises(
            errors.RevnoOutOfBounds, repo.get_rev_id_for_revno, 43, (42, b"rev-foo")
        )
        self.assertFinished(client)

    def test_branch_fallback_locking(self):
        """RemoteBranch.get_rev_id takes a read lock, and tries to call the
        get_rev_id_for_revno verb.  If the verb is unknown the VFS fallback
        will be invoked, which will fail if the repo is unlocked.
        """
        self.setup_smart_server_with_call_log()
        tree = self.make_branch_and_memory_tree(".")
        tree.lock_write()
        tree.add("")
        rev1 = tree.commit("First")
        tree.commit("Second")
        tree.unlock()
        branch = tree.branch
        self.assertFalse(branch.is_locked())
        self.reset_smart_call_log()
        verb = b"Repository.get_rev_id_for_revno"
        self.disable_verb(verb)
        self.assertEqual(rev1, branch.get_rev_id(1))
        self.assertLength(
            1, [call for call in self.hpss_calls if call.call.method == verb]
        )


class TestRepositoryHasSignatureForRevisionId(TestRemoteRepository):
    def test_has_signature_for_revision_id(self):
        # ('yes', ) for Repository.has_signature_for_revision_id -> 'True'.
        transport_path = "quack"
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_success_response(b"yes")
        result = repo.has_signature_for_revision_id(b"A")
        self.assertEqual(
            [("call", b"Repository.has_signature_for_revision_id", (b"quack/", b"A"))],
            client._calls,
        )
        self.assertEqual(True, result)

    def test_is_not_shared(self):
        # ('no', ) for Repository.has_signature_for_revision_id -> 'False'.
        transport_path = "qwack"
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_success_response(b"no")
        result = repo.has_signature_for_revision_id(b"A")
        self.assertEqual(
            [("call", b"Repository.has_signature_for_revision_id", (b"qwack/", b"A"))],
            client._calls,
        )
        self.assertEqual(False, result)


class TestRepositoryPhysicalLockStatus(TestRemoteRepository):
    def test_get_physical_lock_status_yes(self):
        transport_path = "qwack"
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_success_response(b"yes")
        result = repo.get_physical_lock_status()
        self.assertEqual(
            [("call", b"Repository.get_physical_lock_status", (b"qwack/",))],
            client._calls,
        )
        self.assertEqual(True, result)

    def test_get_physical_lock_status_no(self):
        transport_path = "qwack"
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_success_response(b"no")
        result = repo.get_physical_lock_status()
        self.assertEqual(
            [("call", b"Repository.get_physical_lock_status", (b"qwack/",))],
            client._calls,
        )
        self.assertEqual(False, result)


class TestRepositoryIsShared(TestRemoteRepository):
    def test_is_shared(self):
        # ('yes', ) for Repository.is_shared -> 'True'.
        transport_path = "quack"
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_success_response(b"yes")
        result = repo.is_shared()
        self.assertEqual(
            [("call", b"Repository.is_shared", (b"quack/",))], client._calls
        )
        self.assertEqual(True, result)

    def test_is_not_shared(self):
        # ('no', ) for Repository.is_shared -> 'False'.
        transport_path = "qwack"
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_success_response(b"no")
        result = repo.is_shared()
        self.assertEqual(
            [("call", b"Repository.is_shared", (b"qwack/",))], client._calls
        )
        self.assertEqual(False, result)


class TestRepositoryMakeWorkingTrees(TestRemoteRepository):
    def test_make_working_trees(self):
        # ('yes', ) for Repository.make_working_trees -> 'True'.
        transport_path = "quack"
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_success_response(b"yes")
        result = repo.make_working_trees()
        self.assertEqual(
            [("call", b"Repository.make_working_trees", (b"quack/",))], client._calls
        )
        self.assertEqual(True, result)

    def test_no_working_trees(self):
        # ('no', ) for Repository.make_working_trees -> 'False'.
        transport_path = "qwack"
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_success_response(b"no")
        result = repo.make_working_trees()
        self.assertEqual(
            [("call", b"Repository.make_working_trees", (b"qwack/",))], client._calls
        )
        self.assertEqual(False, result)


class TestRepositoryLockWrite(TestRemoteRepository):
    def test_lock_write(self):
        transport_path = "quack"
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_success_response(b"ok", b"a token")
        token = repo.lock_write().repository_token
        self.assertEqual(
            [("call", b"Repository.lock_write", (b"quack/", b""))], client._calls
        )
        self.assertEqual(b"a token", token)

    def test_lock_write_already_locked(self):
        transport_path = "quack"
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_error_response(b"LockContention")
        self.assertRaises(errors.LockContention, repo.lock_write)
        self.assertEqual(
            [("call", b"Repository.lock_write", (b"quack/", b""))], client._calls
        )

    def test_lock_write_unlockable(self):
        transport_path = "quack"
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_error_response(b"UnlockableTransport")
        self.assertRaises(errors.UnlockableTransport, repo.lock_write)
        self.assertEqual(
            [("call", b"Repository.lock_write", (b"quack/", b""))], client._calls
        )


class TestRepositoryWriteGroups(TestRemoteRepository):
    def test_start_write_group(self):
        transport_path = "quack"
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_expected_call(
            b"Repository.lock_write", (b"quack/", b""), b"success", (b"ok", b"a token")
        )
        client.add_expected_call(
            b"Repository.start_write_group",
            (b"quack/", b"a token"),
            b"success",
            (b"ok", (b"token1",)),
        )
        repo.lock_write()
        repo.start_write_group()

    def test_start_write_group_unsuspendable(self):
        # Some repositories do not support suspending write
        # groups. For those, fall back to the "real" repository.
        transport_path = "quack"
        repo, client = self.setup_fake_client_and_repository(transport_path)

        def stub_ensure_real():
            client._calls.append(("_ensure_real",))
            repo._real_repository = _StubRealPackRepository(client._calls)

        repo._ensure_real = stub_ensure_real
        client.add_expected_call(
            b"Repository.lock_write", (b"quack/", b""), b"success", (b"ok", b"a token")
        )
        client.add_expected_call(
            b"Repository.start_write_group",
            (b"quack/", b"a token"),
            b"error",
            (b"UnsuspendableWriteGroup",),
        )
        repo.lock_write()
        repo.start_write_group()
        self.assertEqual(
            client._calls[-2:], [("_ensure_real",), ("start_write_group",)]
        )

    def test_commit_write_group(self):
        transport_path = "quack"
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_expected_call(
            b"Repository.lock_write", (b"quack/", b""), b"success", (b"ok", b"a token")
        )
        client.add_expected_call(
            b"Repository.start_write_group",
            (b"quack/", b"a token"),
            b"success",
            (b"ok", [b"token1"]),
        )
        client.add_expected_call(
            b"Repository.commit_write_group",
            (b"quack/", b"a token", [b"token1"]),
            b"success",
            (b"ok",),
        )
        repo.lock_write()
        repo.start_write_group()
        repo.commit_write_group()

    def test_abort_write_group(self):
        transport_path = "quack"
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_expected_call(
            b"Repository.lock_write", (b"quack/", b""), b"success", (b"ok", b"a token")
        )
        client.add_expected_call(
            b"Repository.start_write_group",
            (b"quack/", b"a token"),
            b"success",
            (b"ok", [b"token1"]),
        )
        client.add_expected_call(
            b"Repository.abort_write_group",
            (b"quack/", b"a token", [b"token1"]),
            b"success",
            (b"ok",),
        )
        repo.lock_write()
        repo.start_write_group()
        repo.abort_write_group(False)

    def test_suspend_write_group(self):
        transport_path = "quack"
        repo, client = self.setup_fake_client_and_repository(transport_path)
        self.assertEqual([], repo.suspend_write_group())

    def test_resume_write_group(self):
        transport_path = "quack"
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_expected_call(
            b"Repository.lock_write", (b"quack/", b""), b"success", (b"ok", b"a token")
        )
        client.add_expected_call(
            b"Repository.check_write_group",
            (b"quack/", b"a token", [b"token1"]),
            b"success",
            (b"ok",),
        )
        repo.lock_write()
        repo.resume_write_group(["token1"])


class TestRepositorySetMakeWorkingTrees(TestRemoteRepository):
    def test_backwards_compat(self):
        self.setup_smart_server_with_call_log()
        repo = self.make_repository(".")
        self.reset_smart_call_log()
        verb = b"Repository.set_make_working_trees"
        self.disable_verb(verb)
        repo.set_make_working_trees(True)
        call_count = len([call for call in self.hpss_calls if call.call.method == verb])
        self.assertEqual(1, call_count)

    def test_current(self):
        transport_path = "quack"
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_expected_call(
            b"Repository.set_make_working_trees",
            (b"quack/", b"True"),
            b"success",
            (b"ok",),
        )
        client.add_expected_call(
            b"Repository.set_make_working_trees",
            (b"quack/", b"False"),
            b"success",
            (b"ok",),
        )
        repo.set_make_working_trees(True)
        repo.set_make_working_trees(False)


class TestRepositoryUnlock(TestRemoteRepository):
    def test_unlock(self):
        transport_path = "quack"
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_success_response(b"ok", b"a token")
        client.add_success_response(b"ok")
        repo.lock_write()
        repo.unlock()
        self.assertEqual(
            [
                ("call", b"Repository.lock_write", (b"quack/", b"")),
                ("call", b"Repository.unlock", (b"quack/", b"a token")),
            ],
            client._calls,
        )

    def test_unlock_wrong_token(self):
        # If somehow the token is wrong, unlock will raise TokenMismatch.
        transport_path = "quack"
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_success_response(b"ok", b"a token")
        client.add_error_response(b"TokenMismatch")
        repo.lock_write()
        self.assertRaises(errors.TokenMismatch, repo.unlock)


class TestRepositoryHasRevision(TestRemoteRepository):
    def test_none(self):
        # repo.has_revision(None) should not cause any traffic.
        transport_path = "quack"
        repo, client = self.setup_fake_client_and_repository(transport_path)

        # The null revision is always there, so has_revision(None) == True.
        self.assertEqual(True, repo.has_revision(NULL_REVISION))

        # The remote repo shouldn't be accessed.
        self.assertEqual([], client._calls)


class TestRepositoryIterFilesBytes(TestRemoteRepository):
    """Test Repository.iter_file_bytes."""

    def test_single(self):
        transport_path = "quack"
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_expected_call(
            b"Repository.iter_files_bytes",
            (b"quack/",),
            b"success",
            (b"ok",),
            iter([b"ok\x000", b"\n", zlib.compress(b"mydata" * 10)]),
        )
        for identifier, byte_stream in repo.iter_files_bytes(
            [(b"somefile", b"somerev", b"myid")]
        ):
            self.assertEqual(b"myid", identifier)
            self.assertEqual(b"".join(byte_stream), b"mydata" * 10)

    def test_missing(self):
        transport_path = "quack"
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_expected_call(
            b"Repository.iter_files_bytes",
            (b"quack/",),
            b"error",
            (b"RevisionNotPresent", b"somefile", b"somerev"),
            iter([b"absent\0somefile\0somerev\n"]),
        )
        self.assertRaises(
            errors.RevisionNotPresent,
            list,
            repo.iter_files_bytes([(b"somefile", b"somerev", b"myid")]),
        )


class TestRepositoryInsertStreamBase(TestRemoteRepository):
    """Base class for Repository.insert_stream and .insert_stream_1.19
    tests.
    """

    def checkInsertEmptyStream(self, repo, client):
        """Insert an empty stream, checking the result.

        This checks that there are no resume_tokens or missing_keys, and that
        the client is finished.
        """
        sink = repo._get_sink()
        fmt = repository.format_registry.get_default()
        resume_tokens, missing_keys = sink.insert_stream([], fmt, [])
        self.assertEqual([], resume_tokens)
        self.assertEqual(set(), missing_keys)
        self.assertFinished(client)


class TestRepositoryInsertStream(TestRepositoryInsertStreamBase):
    """Tests for using Repository.insert_stream verb when the _1.19 variant is
    not available.

    This test case is very similar to TestRepositoryInsertStream_1_19.
    """

    def setUp(self):
        super().setUp()
        self.disable_verb(b"Repository.insert_stream_1.19")

    def test_unlocked_repo(self):
        transport_path = "quack"
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_expected_call(
            b"Repository.insert_stream_1.19",
            (b"quack/", b""),
            b"unknown",
            (b"Repository.insert_stream_1.19",),
        )
        client.add_expected_call(
            b"Repository.insert_stream", (b"quack/", b""), b"success", (b"ok",)
        )
        client.add_expected_call(
            b"Repository.insert_stream", (b"quack/", b""), b"success", (b"ok",)
        )
        self.checkInsertEmptyStream(repo, client)

    def test_locked_repo_with_no_lock_token(self):
        transport_path = "quack"
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_expected_call(
            b"Repository.lock_write", (b"quack/", b""), b"success", (b"ok", b"")
        )
        client.add_expected_call(
            b"Repository.insert_stream_1.19",
            (b"quack/", b""),
            b"unknown",
            (b"Repository.insert_stream_1.19",),
        )
        client.add_expected_call(
            b"Repository.insert_stream", (b"quack/", b""), b"success", (b"ok",)
        )
        client.add_expected_call(
            b"Repository.insert_stream", (b"quack/", b""), b"success", (b"ok",)
        )
        repo.lock_write()
        self.checkInsertEmptyStream(repo, client)

    def test_locked_repo_with_lock_token(self):
        transport_path = "quack"
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_expected_call(
            b"Repository.lock_write", (b"quack/", b""), b"success", (b"ok", b"a token")
        )
        client.add_expected_call(
            b"Repository.insert_stream_1.19",
            (b"quack/", b"", b"a token"),
            b"unknown",
            (b"Repository.insert_stream_1.19",),
        )
        client.add_expected_call(
            b"Repository.insert_stream_locked",
            (b"quack/", b"", b"a token"),
            b"success",
            (b"ok",),
        )
        client.add_expected_call(
            b"Repository.insert_stream_locked",
            (b"quack/", b"", b"a token"),
            b"success",
            (b"ok",),
        )
        repo.lock_write()
        self.checkInsertEmptyStream(repo, client)

    def test_stream_with_inventory_deltas(self):
        """'inventory-deltas' substreams cannot be sent to the
        Repository.insert_stream verb, because not all servers that implement
        that verb will accept them.  So when one is encountered the RemoteSink
        immediately stops using that verb and falls back to VFS insert_stream.
        """
        transport_path = "quack"
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_expected_call(
            b"Repository.insert_stream_1.19",
            (b"quack/", b""),
            b"unknown",
            (b"Repository.insert_stream_1.19",),
        )
        client.add_expected_call(
            b"Repository.insert_stream", (b"quack/", b""), b"success", (b"ok",)
        )
        client.add_expected_call(
            b"Repository.insert_stream", (b"quack/", b""), b"success", (b"ok",)
        )
        # Create a fake real repository for insert_stream to fall back on, so
        # that we can directly see the records the RemoteSink passes to the
        # real sink.

        class FakeRealSink:
            def __init__(self):
                self.records = []

            def insert_stream(self, stream, src_format, resume_tokens):
                for substream_kind, substream in stream:
                    self.records.append(
                        (substream_kind, [record.key for record in substream])
                    )
                return [b"fake tokens"], [b"fake missing keys"]

        fake_real_sink = FakeRealSink()

        class FakeRealRepository:
            def _get_sink(self):
                return fake_real_sink

            def is_in_write_group(self):
                return False

            def refresh_data(self):
                return True

        repo._real_repository = FakeRealRepository()
        sink = repo._get_sink()
        fmt = repository.format_registry.get_default()
        stream = self.make_stream_with_inv_deltas(fmt)
        resume_tokens, missing_keys = sink.insert_stream(stream, fmt, [])
        # Every record from the first inventory delta should have been sent to
        # the VFS sink.
        expected_records = [
            ("inventory-deltas", [(b"rev2",), (b"rev3",)]),
            ("texts", [(b"some-rev", b"some-file")]),
        ]
        self.assertEqual(expected_records, fake_real_sink.records)
        # The return values from the real sink's insert_stream are propagated
        # back to the original caller.
        self.assertEqual([b"fake tokens"], resume_tokens)
        self.assertEqual([b"fake missing keys"], missing_keys)
        self.assertFinished(client)

    def make_stream_with_inv_deltas(self, fmt):
        """Make a simple stream with an inventory delta followed by more
        records and more substreams to test that all records and substreams
        from that point on are used.

        This sends, in order:
           * inventories substream: rev1, rev2, rev3.  rev2 and rev3 are
             inventory-deltas.
           * texts substream: (some-rev, some-file)
        """
        # Define a stream using generators so that it isn't rewindable.
        inv = inventory.Inventory(revision_id=b"rev1", root_revision=b"rev1")

        def stream_with_inv_delta():
            yield ("inventories", inventories_substream())
            yield ("inventory-deltas", inventory_delta_substream())
            yield (
                "texts",
                [
                    versionedfile.FulltextContentFactory(
                        (b"some-rev", b"some-file"), (), None, b"content"
                    )
                ],
            )

        def inventories_substream():
            # An empty inventory fulltext.  This will be streamed normally.
            chunks = fmt._inventory_serializer.write_inventory_to_lines(inv)
            yield versionedfile.ChunkedContentFactory((b"rev1",), (), None, chunks)

        def inventory_delta_substream():
            # An inventory delta.  This can't be streamed via this verb, so it
            # will trigger a fallback to VFS insert_stream.
            entry = inv.make_entry(
                "directory", "newdir", inv.root.file_id, b"newdir-id", revision=b"ghost"
            )
            delta = inventory_delta.InventoryDelta(
                [(None, "newdir", b"newdir-id", entry)]
            )
            serializer = inventory_delta.InventoryDeltaSerializer(
                versioned_root=True, tree_references=False
            )
            lines = serializer.delta_to_lines(b"rev1", b"rev2", delta)
            yield versionedfile.ChunkedContentFactory(
                (b"rev2",), ((b"rev1",),), None, lines
            )
            # Another delta.
            lines = serializer.delta_to_lines(b"rev1", b"rev3", delta)
            yield versionedfile.ChunkedContentFactory(
                (b"rev3",), ((b"rev1",),), None, lines
            )

        return stream_with_inv_delta()


class TestRepositoryInsertStream_1_19(TestRepositoryInsertStreamBase):
    def test_unlocked_repo(self):
        transport_path = "quack"
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_expected_call(
            b"Repository.insert_stream_1.19", (b"quack/", b""), b"success", (b"ok",)
        )
        client.add_expected_call(
            b"Repository.insert_stream_1.19", (b"quack/", b""), b"success", (b"ok",)
        )
        self.checkInsertEmptyStream(repo, client)

    def test_locked_repo_with_no_lock_token(self):
        transport_path = "quack"
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_expected_call(
            b"Repository.lock_write", (b"quack/", b""), b"success", (b"ok", b"")
        )
        client.add_expected_call(
            b"Repository.insert_stream_1.19", (b"quack/", b""), b"success", (b"ok",)
        )
        client.add_expected_call(
            b"Repository.insert_stream_1.19", (b"quack/", b""), b"success", (b"ok",)
        )
        repo.lock_write()
        self.checkInsertEmptyStream(repo, client)

    def test_locked_repo_with_lock_token(self):
        transport_path = "quack"
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_expected_call(
            b"Repository.lock_write", (b"quack/", b""), b"success", (b"ok", b"a token")
        )
        client.add_expected_call(
            b"Repository.insert_stream_1.19",
            (b"quack/", b"", b"a token"),
            b"success",
            (b"ok",),
        )
        client.add_expected_call(
            b"Repository.insert_stream_1.19",
            (b"quack/", b"", b"a token"),
            b"success",
            (b"ok",),
        )
        repo.lock_write()
        self.checkInsertEmptyStream(repo, client)


class TestRepositoryTarball(TestRemoteRepository):
    # This is a canned tarball reponse we can validate against
    tarball_content = base64.b64decode(
        "QlpoOTFBWSZTWdGkj3wAAWF/k8aQACBIB//A9+8cIX/v33AACEAYABAECEACNz"
        "JqsgJJFPTSnk1A3qh6mTQAAAANPUHkagkSTEkaA09QaNAAAGgAAAcwCYCZGAEY"
        "mJhMJghpiaYBUkKammSHqNMZQ0NABkNAeo0AGneAevnlwQoGzEzNVzaYxp/1Uk"
        "xXzA1CQX0BJMZZLcPBrluJir5SQyijWHYZ6ZUtVqqlYDdB2QoCwa9GyWwGYDMA"
        "OQYhkpLt/OKFnnlT8E0PmO8+ZNSo2WWqeCzGB5fBXZ3IvV7uNJVE7DYnWj6qwB"
        "k5DJDIrQ5OQHHIjkS9KqwG3mc3t+F1+iujb89ufyBNIKCgeZBWrl5cXxbMGoMs"
        "c9JuUkg5YsiVcaZJurc6KLi6yKOkgCUOlIlOpOoXyrTJjK8ZgbklReDdwGmFgt"
        "dkVsAIslSVCd4AtACSLbyhLHryfb14PKegrVDba+U8OL6KQtzdM5HLjAc8/p6n"
        "0lgaWU8skgO7xupPTkyuwheSckejFLK5T4ZOo0Gda9viaIhpD1Qn7JqqlKAJqC"
        "QplPKp2nqBWAfwBGaOwVrz3y1T+UZZNismXHsb2Jq18T+VaD9k4P8DqE3g70qV"
        "JLurpnDI6VS5oqDDPVbtVjMxMxMg4rzQVipn2Bv1fVNK0iq3Gl0hhnnHKm/egy"
        "nWQ7QH/F3JFOFCQ0aSPfA="
    )

    def test_repository_tarball(self):
        # Test that Repository.tarball generates the right operations
        transport_path = "repo"
        expected_calls = [
            (
                "call_expecting_body",
                b"Repository.tarball",
                (
                    b"repo/",
                    b"bz2",
                ),
            ),
        ]
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_success_response_with_body(self.tarball_content, b"ok")
        # Now actually ask for the tarball
        tarball_file = repo._get_tarball("bz2")
        try:
            self.assertEqual(expected_calls, client._calls)
            self.assertEqual(self.tarball_content, tarball_file.read())
        finally:
            tarball_file.close()


class TestRemoteRepositoryCopyContent(tests.TestCaseWithTransport):
    """RemoteRepository.copy_content_into optimizations."""

    def test_copy_content_remote_to_local(self):
        self.transport_server = test_server.SmartTCPServer_for_testing
        src_repo = self.make_repository("repo1")
        src_repo = repository.Repository.open(self.get_url("repo1"))
        # At the moment the tarball-based copy_content_into can't write back
        # into a smart server.  It would be good if it could upload the
        # tarball; once that works we'd have to create repositories of
        # different formats. -- mbp 20070410
        dest_url = self.get_vfs_only_url("repo2")
        dest_bzrdir = BzrDir.create(dest_url)
        dest_repo = dest_bzrdir.create_repository()
        self.assertNotIsInstance(dest_repo, RemoteRepository)
        self.assertIsInstance(src_repo, RemoteRepository)
        src_repo.copy_content_into(dest_repo)


class _StubRealPackRepository:
    def __init__(self, calls):
        self.calls = calls
        self._pack_collection = _StubPackCollection(calls)

    def start_write_group(self):
        self.calls.append(("start_write_group",))

    def is_in_write_group(self):
        return False

    def refresh_data(self):
        self.calls.append(("pack collection reload_pack_names",))


class _StubPackCollection:
    def __init__(self, calls):
        self.calls = calls

    def autopack(self):
        self.calls.append(("pack collection autopack",))


class TestRemotePackRepositoryAutoPack(TestRemoteRepository):
    """Tests for RemoteRepository.autopack implementation."""

    def test_ok(self):
        """When the server returns 'ok' and there's no _real_repository, then
        nothing else happens: the autopack method is done.
        """
        transport_path = "quack"
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_expected_call(
            b"PackRepository.autopack", (b"quack/",), b"success", (b"ok",)
        )
        repo.autopack()
        self.assertFinished(client)

    def test_ok_with_real_repo(self):
        """When the server returns 'ok' and there is a _real_repository, then
        the _real_repository's reload_pack_name's method will be called.
        """
        transport_path = "quack"
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_expected_call(
            b"PackRepository.autopack", (b"quack/",), b"success", (b"ok",)
        )
        repo._real_repository = _StubRealPackRepository(client._calls)
        repo.autopack()
        self.assertEqual(
            [
                ("call", b"PackRepository.autopack", (b"quack/",)),
                ("pack collection reload_pack_names",),
            ],
            client._calls,
        )

    def test_backwards_compatibility(self):
        """If the server does not recognise the PackRepository.autopack verb,
        fallback to the real_repository's implementation.
        """
        transport_path = "quack"
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_unknown_method_response(b"PackRepository.autopack")

        def stub_ensure_real():
            client._calls.append(("_ensure_real",))
            repo._real_repository = _StubRealPackRepository(client._calls)

        repo._ensure_real = stub_ensure_real
        repo.autopack()
        self.assertEqual(
            [
                ("call", b"PackRepository.autopack", (b"quack/",)),
                ("_ensure_real",),
                ("pack collection autopack",),
            ],
            client._calls,
        )

    def test_oom_error_reporting(self):
        """An out-of-memory condition on the server is reported clearly."""
        transport_path = "quack"
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_expected_call(
            b"PackRepository.autopack", (b"quack/",), b"error", (b"MemoryError",)
        )
        err = self.assertRaises(errors.BzrError, repo.autopack)
        self.assertContainsRe(str(err), "^remote server out of mem")


class TestErrorTranslationBase(tests.TestCaseWithMemoryTransport):
    """Base class for unit tests for breezy.bzr.remote._translate_error."""

    def translateTuple(self, error_tuple, **context):
        """Call _translate_error with an ErrorFromSmartServer built from the
        given error_tuple.

        :param error_tuple: A tuple of a smart server response, as would be
            passed to an ErrorFromSmartServer.
        :kwargs context: context items to call _translate_error with.

        :returns: The error raised by _translate_error.
        """
        # Raise the ErrorFromSmartServer before passing it as an argument,
        # because _translate_error may need to re-raise it with a bare 'raise'
        # statement.
        server_error = errors.ErrorFromSmartServer(error_tuple)
        translated_error = self.translateErrorFromSmartServer(server_error, **context)
        return translated_error

    def translateErrorFromSmartServer(self, error_object, **context):
        """Like translateTuple, but takes an already constructed
        ErrorFromSmartServer rather than a tuple.
        """
        try:
            raise error_object
        except errors.ErrorFromSmartServer as server_error:
            # Import vcsgraph.errors.Error for errors that come from vcsgraph
            from vcsgraph.errors import Error as VcsGraphError

            # Some errors like GhostRevisionsHaveNoRevno come from vcsgraph
            # and don't inherit from BzrError
            translated_error = self.assertRaises(
                (errors.BzrError, VcsGraphError),
                remote._translate_error,
                server_error,
                **context,
            )
        return translated_error


class TestErrorTranslationSuccess(TestErrorTranslationBase):
    """Unit tests for breezy.bzr.remote._translate_error.

    Given an ErrorFromSmartServer (which has an error tuple from a smart
    server) and some context, _translate_error raises more specific errors from
    breezy.errors.

    This test case covers the cases where _translate_error succeeds in
    translating an ErrorFromSmartServer to something better.  See
    TestErrorTranslationRobustness for other cases.
    """

    def test_NoSuchRevision(self):
        branch = self.make_branch("")
        revid = b"revid"
        translated_error = self.translateTuple(
            (b"NoSuchRevision", revid), branch=branch
        )
        expected_error = errors.NoSuchRevision(branch, revid)
        self.assertEqual(expected_error, translated_error)

    def test_nosuchrevision(self):
        repository = self.make_repository("")
        revid = b"revid"
        translated_error = self.translateTuple(
            (b"nosuchrevision", revid), repository=repository
        )
        expected_error = errors.NoSuchRevision(repository, revid)
        self.assertEqual(expected_error, translated_error)

    def test_nobranch(self):
        bzrdir = self.make_controldir("")
        translated_error = self.translateTuple((b"nobranch",), bzrdir=bzrdir)
        expected_error = errors.NotBranchError(path=bzrdir.root_transport.base)
        self.assertEqual(expected_error, translated_error)

    def test_nobranch_one_arg(self):
        bzrdir = self.make_controldir("")
        translated_error = self.translateTuple(
            (b"nobranch", b"extra detail"), bzrdir=bzrdir
        )
        expected_error = errors.NotBranchError(
            path=bzrdir.root_transport.base, detail="extra detail"
        )
        self.assertEqual(expected_error, translated_error)

    def test_norepository(self):
        bzrdir = self.make_controldir("")
        translated_error = self.translateTuple((b"norepository",), bzrdir=bzrdir)
        expected_error = errors.NoRepositoryPresent(bzrdir)
        self.assertEqual(expected_error, translated_error)

    def test_LockContention(self):
        translated_error = self.translateTuple((b"LockContention",))
        expected_error = errors.LockContention("(remote lock)")
        self.assertEqual(expected_error, translated_error)

    def test_UnlockableTransport(self):
        bzrdir = self.make_controldir("")
        translated_error = self.translateTuple((b"UnlockableTransport",), bzrdir=bzrdir)
        expected_error = errors.UnlockableTransport(bzrdir.root_transport)
        self.assertEqual(expected_error, translated_error)

    def test_LockFailed(self):
        lock = "str() of a server lock"
        why = "str() of why"
        translated_error = self.translateTuple(
            (b"LockFailed", lock.encode("ascii"), why.encode("ascii"))
        )
        expected_error = errors.LockFailed(lock, why)
        self.assertEqual(expected_error, translated_error)

    def test_TokenMismatch(self):
        token = "a lock token"
        translated_error = self.translateTuple((b"TokenMismatch",), token=token)
        expected_error = errors.TokenMismatch(token, "(remote token)")
        self.assertEqual(expected_error, translated_error)

    def test_Diverged(self):
        branch = self.make_branch("a")
        other_branch = self.make_branch("b")
        translated_error = self.translateTuple(
            (b"Diverged",), branch=branch, other_branch=other_branch
        )
        expected_error = errors.DivergedBranches(branch, other_branch)
        self.assertEqual(expected_error, translated_error)

    def test_NotStacked(self):
        branch = self.make_branch("")
        translated_error = self.translateTuple((b"NotStacked",), branch=branch)
        expected_error = errors.NotStacked(branch)
        self.assertEqual(expected_error, translated_error)

    def test_ReadError_no_args(self):
        path = "a path"
        translated_error = self.translateTuple((b"ReadError",), path=path)
        expected_error = errors.ReadError(path)
        self.assertEqual(expected_error, translated_error)

    def test_ReadError(self):
        path = "a path"
        translated_error = self.translateTuple((b"ReadError", path.encode("utf-8")))
        expected_error = errors.ReadError(path)
        self.assertEqual(expected_error, translated_error)

    def test_IncompatibleRepositories(self):
        translated_error = self.translateTuple(
            (b"IncompatibleRepositories", b"repo1", b"repo2", b"details here")
        )
        expected_error = errors.IncompatibleRepositories(
            "repo1", "repo2", "details here"
        )
        self.assertEqual(expected_error, translated_error)

    def test_GhostRevisionsHaveNoRevno(self):
        translated_error = self.translateTuple(
            (b"GhostRevisionsHaveNoRevno", b"revid1", b"revid2")
        )
        expected_error = GhostRevisionsHaveNoRevno(b"revid1", b"revid2")
        self.assertEqual(expected_error, translated_error)

    def test_PermissionDenied_no_args(self):
        path = "a path"
        translated_error = self.translateTuple((b"PermissionDenied",), path=path)
        expected_error = errors.PermissionDenied(path)
        self.assertEqual(expected_error, translated_error)

    def test_PermissionDenied_one_arg(self):
        path = "a path"
        translated_error = self.translateTuple(
            (b"PermissionDenied", path.encode("utf-8"))
        )
        expected_error = errors.PermissionDenied(path)
        self.assertEqual(expected_error, translated_error)

    def test_PermissionDenied_one_arg_and_context(self):
        """Given a choice between a path from the local context and a path on
        the wire, _translate_error prefers the path from the local context.
        """
        local_path = "local path"
        remote_path = "remote path"
        translated_error = self.translateTuple(
            (b"PermissionDenied", remote_path.encode("utf-8")), path=local_path
        )
        expected_error = errors.PermissionDenied(local_path)
        self.assertEqual(expected_error, translated_error)

    def test_PermissionDenied_two_args(self):
        path = "a path"
        extra = "a string with extra info"
        translated_error = self.translateTuple(
            (b"PermissionDenied", path.encode("utf-8"), extra.encode("utf-8"))
        )
        expected_error = errors.PermissionDenied(path, extra)
        self.assertEqual(expected_error, translated_error)

    # GZ 2011-03-02: TODO test for PermissionDenied with non-ascii 'extra'

    def test_NoSuchFile_context_path(self):
        local_path = "local path"
        translated_error = self.translateTuple(
            (b"ReadError", b"remote path"), path=local_path
        )
        expected_error = errors.ReadError(local_path)
        self.assertEqual(expected_error, translated_error)

    def test_NoSuchFile_without_context(self):
        remote_path = "remote path"
        translated_error = self.translateTuple(
            (b"ReadError", remote_path.encode("utf-8"))
        )
        expected_error = errors.ReadError(remote_path)
        self.assertEqual(expected_error, translated_error)

    def test_ReadOnlyError(self):
        translated_error = self.translateTuple((b"ReadOnlyError",))
        expected_error = errors.TransportNotPossible("readonly transport")
        self.assertEqual(expected_error, translated_error)

    def test_MemoryError(self):
        translated_error = self.translateTuple((b"MemoryError",))
        self.assertStartsWith(str(translated_error), "remote server out of memory")

    def test_generic_IndexError_no_classname(self):
        err = errors.ErrorFromSmartServer((b"error", b"list index out of range"))
        translated_error = self.translateErrorFromSmartServer(err)
        expected_error = UnknownErrorFromSmartServer(err)
        self.assertEqual(expected_error, translated_error)

    # GZ 2011-03-02: TODO test generic non-ascii error string

    def test_generic_KeyError(self):
        err = errors.ErrorFromSmartServer((b"error", b"KeyError", b"1"))
        translated_error = self.translateErrorFromSmartServer(err)
        expected_error = UnknownErrorFromSmartServer(err)
        self.assertEqual(expected_error, translated_error)

    def test_RevnoOutOfBounds(self):
        translated_error = self.translateTuple(
            ((b"revno-outofbounds", 5, 0, 3)), path=b"path"
        )
        expected_error = errors.RevnoOutOfBounds(5, (0, 3))
        self.assertEqual(expected_error, translated_error)


class TestErrorTranslationRobustness(TestErrorTranslationBase):
    """Unit tests for breezy.bzr.remote._translate_error's robustness.

    TestErrorTranslationSuccess is for cases where _translate_error can
    translate successfully.  This class about how _translate_err behaves when
    it fails to translate: it re-raises the original error.
    """

    def test_unrecognised_server_error(self):
        """If the error code from the server is not recognised, the original
        ErrorFromSmartServer is propagated unmodified.
        """
        error_tuple = (b"An unknown error tuple",)
        server_error = errors.ErrorFromSmartServer(error_tuple)
        translated_error = self.translateErrorFromSmartServer(server_error)
        expected_error = UnknownErrorFromSmartServer(server_error)
        self.assertEqual(expected_error, translated_error)

    def test_context_missing_a_key(self):
        """In case of a bug in the client, or perhaps an unexpected response
        from a server, _translate_error returns the original error tuple from
        the server and mutters a warning.
        """
        # To translate a NoSuchRevision error _translate_error needs a 'branch'
        # in the context dict.  So let's give it an empty context dict instead
        # to exercise its error recovery.
        error_tuple = (b"NoSuchRevision", b"revid")
        server_error = errors.ErrorFromSmartServer(error_tuple)
        translated_error = self.translateErrorFromSmartServer(server_error)
        self.assertEqual(server_error, translated_error)
        # In addition to re-raising ErrorFromSmartServer, some debug info has
        # been muttered to the log file for developer to look at.
        self.assertContainsRe(self.get_log(), "Missing key 'branch' in context")

    def test_path_missing(self):
        """Some translations (PermissionDenied, ReadError) can determine the
        'path' variable from either the wire or the local context.  If neither
        has it, then an error is raised.
        """
        error_tuple = (b"ReadError",)
        server_error = errors.ErrorFromSmartServer(error_tuple)
        translated_error = self.translateErrorFromSmartServer(server_error)
        self.assertEqual(server_error, translated_error)
        # In addition to re-raising ErrorFromSmartServer, some debug info has
        # been muttered to the log file for developer to look at.
        self.assertContainsRe(self.get_log(), "Missing key 'path' in context")


class TestStacking(tests.TestCaseWithTransport):
    """Tests for operations on stacked remote repositories.

    The underlying format type must support stacking.
    """

    def test_access_stacked_remote(self):
        # based on <http://launchpad.net/bugs/261315>
        # make a branch stacked on another repository containing an empty
        # revision, then open it over hpss - we should be able to see that
        # revision.
        base_builder = self.make_branch_builder("base", format="1.9")
        base_builder.start_series()
        base_revid = base_builder.build_snapshot(
            None,
            [("add", ("", None, "directory", None))],
            "message",
            revision_id=b"rev-id",
        )
        base_builder.finish_series()
        stacked_branch = self.make_branch("stacked", format="1.9")
        stacked_branch.set_stacked_on_url("../base")
        # start a server looking at this
        smart_server = test_server.SmartTCPServer_for_testing()
        self.start_server(smart_server)
        remote_bzrdir = BzrDir.open(smart_server.get_url() + "/stacked")
        # can get its branch and repository
        remote_branch = remote_bzrdir.open_branch()
        remote_repo = remote_branch.repository
        remote_repo.lock_read()
        try:
            # it should have an appropriate fallback repository, which should also
            # be a RemoteRepository
            self.assertLength(1, remote_repo._fallback_repositories)
            self.assertIsInstance(
                remote_repo._fallback_repositories[0], RemoteRepository
            )
            # and it has the revision committed to the underlying repository;
            # these have varying implementations so we try several of them
            self.assertTrue(remote_repo.has_revisions([base_revid]))
            self.assertTrue(remote_repo.has_revision(base_revid))
            self.assertEqual(remote_repo.get_revision(base_revid).message, "message")
        finally:
            remote_repo.unlock()

    def prepare_stacked_remote_branch(self):
        """Get stacked_upon and stacked branches with content in each."""
        self.setup_smart_server_with_call_log()
        tree1 = self.make_branch_and_tree("tree1", format="1.9")
        tree1.commit("rev1", rev_id=b"rev1")
        tree2 = tree1.branch.controldir.sprout("tree2", stacked=True).open_workingtree()
        local_tree = tree2.branch.create_checkout("local")
        local_tree.commit("local changes make me feel good.")
        branch2 = Branch.open(self.get_url("tree2"))
        branch2.lock_read()
        self.addCleanup(branch2.unlock)
        return tree1.branch, branch2

    def test_stacked_get_parent_map(self):
        # the public implementation of get_parent_map obeys stacking
        _, branch = self.prepare_stacked_remote_branch()
        repo = branch.repository
        self.assertEqual({b"rev1"}, set(repo.get_parent_map([b"rev1"])))

    def test_unstacked_get_parent_map(self):
        # _unstacked_provider.get_parent_map ignores stacking
        _, branch = self.prepare_stacked_remote_branch()
        provider = branch.repository._unstacked_provider
        self.assertEqual(set(), set(provider.get_parent_map([b"rev1"])))

    def fetch_stream_to_rev_order(self, stream):
        result = []
        for kind, substream in stream:
            if kind != "revisions":
                list(substream)
            else:
                for content in substream:
                    result.append(content.key[-1])
        return result

    def get_ordered_revs(self, format, order, branch_factory=None):
        """Get a list of the revisions in a stream to format format.

        :param format: The format of the target.
        :param order: the order that target should have requested.
        :param branch_factory: A callable to create a trunk and stacked branch
            to fetch from. If none, self.prepare_stacked_remote_branch is used.
        :result: The revision ids in the stream, in the order seen,
            the topological order of revisions in the source.
        """
        unordered_format = controldir.format_registry.get(format)()
        target_repository_format = unordered_format.repository_format
        # Cross check
        self.assertEqual(order, target_repository_format._fetch_order)
        if branch_factory is None:
            branch_factory = self.prepare_stacked_remote_branch
        _, stacked = branch_factory()
        source = stacked.repository._get_source(target_repository_format)
        tip = stacked.last_revision()
        stacked.repository._ensure_real()
        graph = stacked.repository.get_graph()
        revs = [r for (r, ps) in graph.iter_ancestry([tip]) if r != NULL_REVISION]
        revs.reverse()
        search = vf_search.PendingAncestryResult([tip], stacked.repository)
        self.reset_smart_call_log()
        stream = source.get_stream(search)
        # We trust that if a revision is in the stream the rest of the new
        # content for it is too, as per our main fetch tests; here we are
        # checking that the revisions are actually included at all, and their
        # order.
        return self.fetch_stream_to_rev_order(stream), revs

    def test_stacked_get_stream_unordered(self):
        # Repository._get_source.get_stream() from a stacked repository with
        # unordered yields the full data from both stacked and stacked upon
        # sources.
        rev_ord, expected_revs = self.get_ordered_revs("1.9", "unordered")
        self.assertEqual(set(expected_revs), set(rev_ord))
        # Getting unordered results should have made a streaming data request
        # from the server, then one from the backing branch.
        self.assertLength(2, self.hpss_calls)

    def test_stacked_on_stacked_get_stream_unordered(self):
        # Repository._get_source.get_stream() from a stacked repository which
        # is itself stacked yields the full data from all three sources.
        def make_stacked_stacked():
            _, stacked = self.prepare_stacked_remote_branch()
            tree = stacked.controldir.sprout("tree3", stacked=True).open_workingtree()
            local_tree = tree.branch.create_checkout("local-tree3")
            local_tree.commit("more local changes are better")
            branch = Branch.open(self.get_url("tree3"))
            branch.lock_read()
            self.addCleanup(branch.unlock)
            return None, branch

        rev_ord, expected_revs = self.get_ordered_revs(
            "1.9", "unordered", branch_factory=make_stacked_stacked
        )
        self.assertEqual(set(expected_revs), set(rev_ord))
        # Getting unordered results should have made a streaming data request
        # from the server, and one from each backing repo
        self.assertLength(3, self.hpss_calls)

    def test_stacked_get_stream_topological(self):
        # Repository._get_source.get_stream() from a stacked repository with
        # topological sorting yields the full data from both stacked and
        # stacked upon sources in topological order.
        rev_ord, expected_revs = self.get_ordered_revs("knit", "topological")
        self.assertEqual(expected_revs, rev_ord)
        # Getting topological sort requires VFS calls still - one of which is
        # pushing up from the bound branch.
        self.assertLength(14, self.hpss_calls)

    def test_stacked_get_stream_groupcompress(self):
        # Repository._get_source.get_stream() from a stacked repository with
        # groupcompress sorting yields the full data from both stacked and
        # stacked upon sources in groupcompress order.
        raise tests.TestSkipped("No groupcompress ordered format available")
        rev_ord, expected_revs = self.get_ordered_revs("dev5", "groupcompress")
        self.assertEqual(expected_revs, reversed(rev_ord))
        # Getting unordered results should have made a streaming data request
        # from the backing branch, and one from the stacked on branch.
        self.assertLength(2, self.hpss_calls)

    def test_stacked_pull_more_than_stacking_has_bug_360791(self):
        # When pulling some fixed amount of content that is more than the
        # source has (because some is coming from a fallback branch, no error
        # should be received. This was reported as bug 360791.
        # Need three branches: a trunk, a stacked branch, and a preexisting
        # branch pulling content from stacked and trunk.
        self.setup_smart_server_with_call_log()
        trunk = self.make_branch_and_tree("trunk", format="1.9-rich-root")
        trunk.commit("start")
        stacked_branch = trunk.branch.create_clone_on_transport(
            self.get_transport("stacked"), stacked_on=trunk.branch.base
        )
        local = self.make_branch("local", format="1.9-rich-root")
        local.repository.fetch(
            stacked_branch.repository, stacked_branch.last_revision()
        )


class TestRemoteBranchEffort(tests.TestCaseWithTransport):
    def setUp(self):
        super().setUp()
        # Create a smart server that publishes whatever the backing VFS server
        # does.
        self.smart_server = test_server.SmartTCPServer_for_testing()
        self.start_server(self.smart_server, self.get_server())
        # Log all HPSS calls into self.hpss_calls.
        _SmartClient.hooks.install_named_hook("call", self.capture_hpss_call, None)
        self.hpss_calls = []

    def capture_hpss_call(self, params):
        self.hpss_calls.append(params.method)

    def test_copy_content_into_avoids_revision_history(self):
        local = self.make_branch("local")
        builder = self.make_branch_builder("remote")
        builder.build_commit(message="Commit.")
        remote_branch_url = self.smart_server.get_url() + "remote"
        remote_branch = bzrdir.BzrDir.open(remote_branch_url).open_branch()
        local.repository.fetch(remote_branch.repository)
        self.hpss_calls = []
        remote_branch.copy_content_into(local)
        self.assertNotIn(b"Branch.revision_history", self.hpss_calls)

    def test_fetch_everything_needs_just_one_call(self):
        local = self.make_branch("local")
        builder = self.make_branch_builder("remote")
        builder.build_commit(message="Commit.")
        remote_branch_url = self.smart_server.get_url() + "remote"
        remote_branch = bzrdir.BzrDir.open(remote_branch_url).open_branch()
        self.hpss_calls = []
        local.repository.fetch(
            remote_branch.repository,
            fetch_spec=vf_search.EverythingResult(remote_branch.repository),
        )
        self.assertEqual([b"Repository.get_stream_1.19"], self.hpss_calls)

    def override_verb(self, verb_name, verb):
        request_handlers = request.request_handlers
        orig_verb = request_handlers.get(verb_name)
        orig_info = request_handlers.get_info(verb_name)
        request_handlers.register(verb_name, verb, override_existing=True)
        self.addCleanup(
            request_handlers.register,
            verb_name,
            orig_verb,
            override_existing=True,
            info=orig_info,
        )

    def test_fetch_everything_backwards_compat(self):
        """Can fetch with EverythingResult even with pre 2.4 servers.

        Pre-2.4 do not support 'everything' searches with the
        Repository.get_stream_1.19 verb.
        """
        verb_log = []

        class OldGetStreamVerb(SmartServerRepositoryGetStream_1_19):
            """A version of the Repository.get_stream_1.19 verb patched to
            reject 'everything' searches the way 2.3 and earlier do.
            """

            def recreate_search(self, repository, search_bytes, discard_excess=False):
                verb_log.append(search_bytes.split(b"\n", 1)[0])
                if search_bytes == b"everything":
                    return (None, request.FailedSmartServerResponse((b"BadSearch",)))
                return super().recreate_search(
                    repository, search_bytes, discard_excess=discard_excess
                )

        self.override_verb(b"Repository.get_stream_1.19", OldGetStreamVerb)
        local = self.make_branch("local")
        builder = self.make_branch_builder("remote")
        builder.build_commit(message="Commit.")
        remote_branch_url = self.smart_server.get_url() + "remote"
        remote_branch = bzrdir.BzrDir.open(remote_branch_url).open_branch()
        self.hpss_calls = []
        local.repository.fetch(
            remote_branch.repository,
            fetch_spec=vf_search.EverythingResult(remote_branch.repository),
        )
        # make sure the overridden verb was used
        self.assertLength(1, verb_log)
        # more than one HPSS call is needed, but because it's a VFS callback
        # its hard to predict exactly how many.
        self.assertGreater(len(self.hpss_calls), 1)


class TestUpdateBoundBranchWithModifiedBoundLocation(tests.TestCaseWithTransport):
    """Ensure correct handling of bound_location modifications.

    This is tested against a smart server as http://pad.lv/786980 was about a
    ReadOnlyError (write attempt during a read-only transaction) which can only
    happen in this context.
    """

    def setUp(self):
        super().setUp()
        self.transport_server = test_server.SmartTCPServer_for_testing

    def make_master_and_checkout(self, master_name, checkout_name):
        # Create the master branch and its associated checkout
        self.master = self.make_branch_and_tree(master_name)
        self.checkout = self.master.branch.create_checkout(checkout_name)
        # Modify the master branch so there is something to update
        self.master.commit("add stuff")
        self.last_revid = self.master.commit("even more stuff")
        self.bound_location = self.checkout.branch.get_bound_location()

    def assertUpdateSucceeds(self, new_location):
        self.checkout.branch.set_bound_location(new_location)
        self.checkout.update()
        self.assertEqual(self.last_revid, self.checkout.last_revision())

    def test_without_final_slash(self):
        self.make_master_and_checkout("master", "checkout")
        # For unclear reasons some users have a bound_location without a final
        # '/', simulate that by forcing such a value
        self.assertEndsWith(self.bound_location, "/")
        self.assertUpdateSucceeds(self.bound_location.rstrip("/"))

    def test_plus_sign(self):
        self.make_master_and_checkout("+master", "checkout")
        self.assertUpdateSucceeds(self.bound_location.replace("%2B", "+", 1))

    def test_tilda(self):
        # Embed ~ in the middle of the path just to avoid any $HOME
        # interpretation
        self.make_master_and_checkout("mas~ter", "checkout")
        self.assertUpdateSucceeds(self.bound_location.replace("%2E", "~", 1))


class TestWithCustomErrorHandler(RemoteBranchTestCase):
    def test_no_context(self):
        class OutOfCoffee(errors.BzrError):
            """A dummy exception for testing."""

            def __init__(self, urgency):
                self.urgency = urgency

        remote.no_context_error_translators.register(
            b"OutOfCoffee", lambda err: OutOfCoffee(err.error_args[0])
        )
        transport = MemoryTransport()
        client = FakeClient(transport.base)
        client.add_expected_call(
            b"Branch.get_stacked_on_url", (b"quack/",), b"error", (b"NotStacked",)
        )
        client.add_expected_call(
            b"Branch.last_revision_info",
            (b"quack/",),
            b"error",
            (b"OutOfCoffee", b"low"),
        )
        transport.mkdir("quack")
        transport = transport.clone("quack")
        branch = self.make_remote_branch(transport, client)
        self.assertRaises(OutOfCoffee, branch.last_revision_info)
        self.assertFinished(client)

    def test_with_context(self):
        class OutOfTea(errors.BzrError):
            def __init__(self, branch, urgency):
                self.branch = branch
                self.urgency = urgency

        remote.error_translators.register(
            b"OutOfTea",
            lambda err, find, path: OutOfTea(
                err.error_args[0].decode("utf-8"), find("branch")
            ),
        )
        transport = MemoryTransport()
        client = FakeClient(transport.base)
        client.add_expected_call(
            b"Branch.get_stacked_on_url", (b"quack/",), b"error", (b"NotStacked",)
        )
        client.add_expected_call(
            b"Branch.last_revision_info", (b"quack/",), b"error", (b"OutOfTea", b"low")
        )
        transport.mkdir("quack")
        transport = transport.clone("quack")
        branch = self.make_remote_branch(transport, client)
        self.assertRaises(OutOfTea, branch.last_revision_info)
        self.assertFinished(client)


class TestRepositoryPack(TestRemoteRepository):
    def test_pack(self):
        transport_path = "quack"
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_expected_call(
            b"Repository.lock_write", (b"quack/", b""), b"success", (b"ok", b"token")
        )
        client.add_expected_call(
            b"Repository.pack",
            (b"quack/", b"token", b"False"),
            b"success",
            (b"ok",),
        )
        client.add_expected_call(
            b"Repository.unlock", (b"quack/", b"token"), b"success", (b"ok",)
        )
        repo.pack()

    def test_pack_with_hint(self):
        transport_path = "quack"
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_expected_call(
            b"Repository.lock_write", (b"quack/", b""), b"success", (b"ok", b"token")
        )
        client.add_expected_call(
            b"Repository.pack",
            (b"quack/", b"token", b"False"),
            b"success",
            (b"ok",),
        )
        client.add_expected_call(
            b"Repository.unlock", (b"quack/", b"token", b"False"), b"success", (b"ok",)
        )
        repo.pack(["hinta", "hintb"])


class TestRepositoryIterInventories(TestRemoteRepository):
    """Test Repository.iter_inventories."""

    def _serialize_inv_delta(self, old_name, new_name, delta):
        serializer = inventory_delta.InventoryDeltaSerializer(True, False)
        return b"".join(serializer.delta_to_lines(old_name, new_name, delta))

    def test_single_empty(self):
        transport_path = "quack"
        repo, client = self.setup_fake_client_and_repository(transport_path)
        fmt = controldir.format_registry.get("2a")().repository_format
        repo._format = fmt
        stream = [
            (
                "inventory-deltas",
                [
                    versionedfile.FulltextContentFactory(
                        (b"somerevid",),
                        None,
                        None,
                        self._serialize_inv_delta(
                            b"null:", b"somerevid", inventory_delta.InventoryDelta([])
                        ),
                    )
                ],
            )
        ]
        client.add_expected_call(
            b"VersionedFileRepository.get_inventories",
            (b"quack/", b"unordered"),
            b"success",
            (b"ok",),
            _stream_to_byte_stream(stream, fmt),
        )
        ret = list(repo.iter_inventories([b"somerevid"]))
        self.assertLength(1, ret)
        inv = ret[0]
        self.assertEqual(b"somerevid", inv.revision_id)

    def test_empty(self):
        transport_path = "quack"
        repo, client = self.setup_fake_client_and_repository(transport_path)
        ret = list(repo.iter_inventories([]))
        self.assertEqual(ret, [])

    def test_missing(self):
        transport_path = "quack"
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_expected_call(
            b"VersionedFileRepository.get_inventories",
            (b"quack/", b"unordered"),
            b"success",
            (b"ok",),
            iter([]),
        )
        self.assertRaises(
            errors.NoSuchRevision, list, repo.iter_inventories([b"somerevid"])
        )


class TestRepositoryRevisionTreeArchive(TestRemoteRepository):
    """Test Repository.iter_inventories."""

    def _serialize_inv_delta(self, old_name, new_name, delta):
        serializer = inventory_delta.InventoryDeltaSerializer(True, False)
        return b"".join(serializer.delta_to_lines(old_name, new_name, delta))

    def test_simple(self):
        transport_path = "quack"
        repo, client = self.setup_fake_client_and_repository(transport_path)
        fmt = controldir.format_registry.get("2a")().repository_format
        repo._format = fmt
        stream = [
            (
                "inventory-deltas",
                [
                    versionedfile.FulltextContentFactory(
                        (b"somerevid",),
                        None,
                        None,
                        self._serialize_inv_delta(
                            b"null:", b"somerevid", inventory_delta.InventoryDelta([])
                        ),
                    )
                ],
            )
        ]
        client.add_expected_call(
            b"VersionedFileRepository.get_inventories",
            (b"quack/", b"unordered"),
            b"success",
            (b"ok",),
            _stream_to_byte_stream(stream, fmt),
        )
        f = BytesIO()
        with tarfile.open(mode="w", fileobj=f) as tf:
            info = tarfile.TarInfo("somefile")
            info.mtime = 432432
            contents = b"some data"
            info.type = tarfile.REGTYPE
            info.mode = 0o644
            info.size = len(contents)
            tf.addfile(info, BytesIO(contents))
        client.add_expected_call(
            b"Repository.revision_archive",
            (b"quack/", b"somerevid", b"tar", b"foo.tar", b"", b"", None),
            b"success",
            (b"ok",),
            f.getvalue(),
        )
        tree = repo.revision_tree(b"somerevid")
        self.assertEqual(f.getvalue(), b"".join(tree.archive("tar", "foo.tar")))


class TestRepositoryAnnotate(TestRemoteRepository):
    """Test RemoteRevisionTree.annotate.."""

    def _serialize_inv_delta(self, old_name, new_name, delta):
        serializer = inventory_delta.InventoryDeltaSerializer(True, False)
        return b"".join(serializer.delta_to_lines(old_name, new_name, delta))

    def test_simple(self):
        transport_path = "quack"
        repo, client = self.setup_fake_client_and_repository(transport_path)
        fmt = controldir.format_registry.get("2a")().repository_format
        repo._format = fmt
        stream = [
            (
                "inventory-deltas",
                [
                    versionedfile.FulltextContentFactory(
                        (b"somerevid",),
                        None,
                        None,
                        self._serialize_inv_delta(
                            b"null:", b"somerevid", inventory_delta.InventoryDelta([])
                        ),
                    )
                ],
            )
        ]
        client.add_expected_call(
            b"VersionedFileRepository.get_inventories",
            (b"quack/", b"unordered"),
            b"success",
            (b"ok",),
            _stream_to_byte_stream(stream, fmt),
        )
        client.add_expected_call(
            b"Repository.annotate_file_revision",
            (b"quack/", b"somerevid", b"filename", b"", b"current:"),
            b"success",
            (b"ok",),
            bencode.bencode([[b"baserevid", b"line 1\n"], [b"somerevid", b"line2\n"]]),
        )
        tree = repo.revision_tree(b"somerevid")
        self.assertEqual(
            [(b"baserevid", b"line 1\n"), (b"somerevid", b"line2\n")],
            list(tree.annotate_iter("filename")),
        )


class TestBranchGetAllReferenceInfo(RemoteBranchTestCase):
    def test_get_all_reference_info(self):
        transport = MemoryTransport()
        client = FakeClient(transport.base)
        client.add_expected_call(
            b"Branch.get_stacked_on_url", (b"quack/",), b"error", (b"NotStacked",)
        )
        client.add_expected_call(
            b"Branch.get_all_reference_info",
            (b"quack/",),
            b"success",
            (b"ok",),
            bencode.bencode([(b"file-id", b"https://www.example.com/", b"")]),
        )
        transport.mkdir("quack")
        transport = transport.clone("quack")
        branch = self.make_remote_branch(transport, client)
        result = branch._get_all_reference_info()
        self.assertFinished(client)
        self.assertEqual({b"file-id": ("https://www.example.com/", None)}, result)


class TestErrors(tests.TestCase):
    def test_untranslateable_error_from_smart_server(self):
        error_tuple = ("error", "tuple")
        orig_err = errors.ErrorFromSmartServer(error_tuple)
        err = UnknownErrorFromSmartServer(orig_err)
        self.assertEqual(
            "Server sent an unexpected error: ('error', 'tuple')", str(err)
        )
