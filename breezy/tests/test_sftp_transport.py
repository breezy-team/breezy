# Copyright (C) 2005-2012, 2016 Robey Pointer <robey@lag.net>
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

import os
import socket
import sys
import time

from breezy import config, controldir, errors, tests, ui
from breezy import transport as _mod_transport
from breezy.tests import TestCase, TestCaseWithTransport, TestSkipped, features

from ..osutils import lexists
from .http_server import HttpServer

if features.paramiko.available():
    from breezy.tests import stub_sftp
    from breezy.transport import sftp as _mod_sftp


def set_test_transport_to_sftp(testcase):
    """A helper to set transports on test case instances."""
    if getattr(testcase, "_get_remote_is_absolute", None) is None:
        testcase._get_remote_is_absolute = True
    if testcase._get_remote_is_absolute:
        testcase.transport_server = stub_sftp.SFTPAbsoluteServer
    else:
        testcase.transport_server = stub_sftp.SFTPHomeDirServer
    testcase.transport_readonly_server = HttpServer


class TestCaseWithSFTPServer(TestCaseWithTransport):
    """A test case base class that provides a sftp server on localhost."""

    def setUp(self):
        super().setUp()
        self.requireFeature(features.paramiko)
        set_test_transport_to_sftp(self)


class SFTPLockTests(TestCaseWithSFTPServer):
    def test_sftp_locks(self):
        from ..errors import LockError

        t = self.get_transport()

        l = t.lock_write("bogus")
        self.assertPathExists("bogus.write-lock")

        # Don't wait for the lock, locking an already locked
        # file should raise an assert
        self.assertRaises(LockError, t.lock_write, "bogus")

        l.unlock()
        self.assertFalse(lexists("bogus.write-lock"))

        with open("something.write-lock", "wb") as f:
            f.write(b"fake lock\n")
        self.assertRaises(LockError, t.lock_write, "something")
        os.remove("something.write-lock")

        l = t.lock_write("something")

        l2 = t.lock_write("bogus")

        l.unlock()
        l2.unlock()


class SFTPTransportTestRelative(TestCaseWithSFTPServer):
    """Test the SFTP transport with homedir based relative paths."""

    def test__remote_path(self):
        if sys.platform == "darwin":
            # This test is about sftp absolute path handling. There is already
            # (in this test) a TODO about windows needing an absolute path
            # without drive letter. To me, using self.test_dir is a trick to
            # get an absolute path for comparison purposes.  That fails for OSX
            # because the sftp server doesn't resolve the links (and it doesn't
            # have to). --vila 20070924
            self.knownFailure(
                "Mac OSX symlinks /tmp to /private/tmp,"
                " testing against self.test_dir"
                " is not appropriate"
            )
        t = self.get_transport()
        # This test require unix-like absolute path
        test_dir = self.test_dir
        if sys.platform == "win32":
            # using hack suggested by John Meinel.
            # TODO: write another mock server for this test
            #       and use absolute path without drive letter
            test_dir = "/" + test_dir
        # try what is currently used:
        # remote path = self._abspath(relpath)
        self.assertIsSameRealPath(test_dir + "/relative", t._remote_path("relative"))
        # we dont os.path.join because windows gives us the wrong path
        root_segments = test_dir.split("/")
        root_parent = "/".join(root_segments[:-1])
        # .. should be honoured
        self.assertIsSameRealPath(
            root_parent + "/sibling", t._remote_path("../sibling")
        )
        # /  should be illegal ?
        # FIXME decide and then test for all transports. RBC20051208


class SFTPTransportTestRelativeRoot(TestCaseWithSFTPServer):
    """Test the SFTP transport with homedir based relative paths."""

    def setUp(self):
        # Only SFTPHomeDirServer is tested here
        self._get_remote_is_absolute = False
        super().setUp()

    def test__remote_path_relative_root(self):
        # relative paths are preserved
        t = self.get_transport("")
        self.assertEqual("/~/", t._parsed_url.path)
        # the remote path should be relative to home dir
        # (i.e. not begining with a '/')
        self.assertEqual("a", t._remote_path("a"))


class SFTPNonServerTest(TestCase):
    def setUp(self):
        super().setUp()
        self.requireFeature(features.paramiko)

    def test_parse_url_with_home_dir(self):
        s = _mod_sftp.SFTPTransport("sftp://ro%62ey:h%40t@example.com:2222/~/relative")
        self.assertEqual(s._parsed_url.host, "example.com")
        self.assertEqual(s._parsed_url.port, 2222)
        self.assertEqual(s._parsed_url.user, "robey")
        self.assertEqual(s._parsed_url.password, "h@t")
        self.assertEqual(s._parsed_url.path, "/~/relative/")

    def test_relpath(self):
        s = _mod_sftp.SFTPTransport("sftp://user@host.com/abs/path")
        self.assertRaises(
            errors.PathNotChild, s.relpath, "sftp://user@host.com/~/rel/path/sub"
        )

    def test_get_paramiko_vendor(self):
        """Test that if no 'ssh' is available we get builtin paramiko."""
        from breezy.transport import ssh
        from breezy.transport.ssh.paramiko import ParamikoVendor

        # set '.' as the only location in the path, forcing no 'ssh' to exist
        self.overrideAttr(ssh, "_ssh_vendor_manager")
        self.overrideEnv("PATH", ".")
        ssh._ssh_vendor_manager.clear_cache()
        vendor = ssh._get_ssh_vendor()
        self.assertIsInstance(vendor, ParamikoVendor)

    def test_abspath_root_sibling_server(self):
        server = stub_sftp.SFTPSiblingAbsoluteServer()
        server.start_server()
        self.addCleanup(server.stop_server)

        transport = _mod_transport.get_transport_from_url(server.get_url())
        self.assertFalse(transport.abspath("/").endswith("/~/"))
        self.assertTrue(transport.abspath("/").endswith("/"))
        del transport


class SFTPBranchTest(TestCaseWithSFTPServer):
    """Test some stuff when accessing a bzr Branch over sftp."""

    def test_push_support(self):
        self.build_tree(["a/", "a/foo"])
        t = controldir.ControlDir.create_standalone_workingtree("a")
        b = t.branch
        t.add("foo")
        revid1 = t.commit("foo")

        b2 = controldir.ControlDir.create_branch_and_repo(self.get_url("/b"))
        b2.pull(b)

        self.assertEqual(b2.last_revision(), revid1)

        with open("a/foo", "w") as f:
            f.write("something new in foo\n")
        revid2 = t.commit("new")
        b2.pull(b)

        self.assertEqual(b2.last_revision(), revid2)


class SSHVendorConnection(TestCaseWithSFTPServer):
    """Test that the ssh vendors can all connect.

    Verify that a full-handshake (SSH over loopback TCP) sftp connection works.

    We have 3 sftp implementations in the test suite:
      'loopback': Doesn't use ssh, just uses a local socket. Most tests are
                  done this way to save the handshaking time, so it is not
                  tested again here
      'none':     This uses paramiko's built-in ssh client and server, and
                  layers sftp on top of it.
      None:       If 'ssh' exists on the machine, then it will be spawned as a
                  child process.
    """

    def setUp(self):
        super().setUp()

        def create_server():
            """Just a wrapper so that when created, it will set _vendor."""
            # SFTPFullAbsoluteServer can handle any vendor,
            # it just needs to be set between the time it is instantiated
            # and the time .setUp() is called
            server = stub_sftp.SFTPFullAbsoluteServer()
            server._vendor = self._test_vendor
            return server

        self._test_vendor = "loopback"
        self.vfs_transport_server = create_server
        f = open("a_file", "wb")
        try:
            f.write(b"foobar\n")
        finally:
            f.close()

    def set_vendor(self, vendor):
        self._test_vendor = vendor

    def test_connection_paramiko(self):
        from breezy.transport.ssh.paramiko import ParamikoVendor

        self.set_vendor(ParamikoVendor())
        t = self.get_transport()
        self.assertEqual(b"foobar\n", t.get("a_file").read())

    def test_connection_vendor(self):
        raise TestSkipped(
            "We don't test spawning real ssh,"
            " because it prompts for a password."
            " Enable this test if we figure out"
            " how to prevent this."
        )
        self.set_vendor(None)
        t = self.get_transport()
        self.assertEqual(b"foobar\n", t.get("a_file").read())


class SSHVendorBadConnection(TestCaseWithTransport):
    """Test that the ssh vendors handle bad connection properly.

    We don't subclass TestCaseWithSFTPServer, because we don't actually
    need an SFTP connection.
    """

    def setUp(self):
        self.requireFeature(features.paramiko)
        super().setUp()

        # open a random port, so we know nobody else is using it
        # but don't actually listen on the port.
        s = socket.socket()
        s.bind(("localhost", 0))
        self.addCleanup(s.close)
        self.bogus_url = "sftp://{}:{}/".format(*s.getsockname())

    def set_vendor(self, vendor, subprocess_stderr=None):
        from breezy.transport import ssh

        self.overrideAttr(ssh._ssh_vendor_manager, "_cached_ssh_vendor", vendor)
        if subprocess_stderr is not None:
            self.overrideAttr(ssh.SubprocessVendor, "_stderr_target", subprocess_stderr)

    def test_bad_connection_paramiko(self):
        """Test that a real connection attempt raises the right error."""
        from breezy.transport.ssh.paramiko import ParamikoVendor

        self.set_vendor(ParamikoVendor())
        t = _mod_transport.get_transport_from_url(self.bogus_url)
        self.assertRaises(ConnectionError, t.get, "foobar")

    def test_bad_connection_ssh(self):
        """None => auto-detect vendor."""
        f = open(os.devnull, "wb")
        self.addCleanup(f.close)
        self.set_vendor(None, f)
        t = _mod_transport.get_transport_from_url(self.bogus_url)
        try:
            self.assertRaises(ConnectionError, t.get, "foobar")
        except NameError as e:
            if "global name 'SSHException'" in str(e):
                self.knownFailure("Known NameError bug in paramiko 1.6.1")
            raise


class SFTPLatencyKnob(TestCaseWithSFTPServer):
    """Test that the testing SFTPServer's latency knob works."""

    def test_latency_knob_slows_transport(self):
        # change the latency knob to 500ms. We take about 40ms for a
        # loopback connection ordinarily.
        start_time = time.time()
        self.get_server().add_latency = 0.5
        transport = self.get_transport()
        transport.has("not me")  # Force connection by issuing a request
        with_latency_knob_time = time.time() - start_time
        self.assertGreater(with_latency_knob_time, 0.4)

    def test_default(self):
        # This test is potentially brittle: under extremely high machine load
        # it could fail, but that is quite unlikely
        raise TestSkipped("Timing-sensitive test")
        start_time = time.time()
        transport = self.get_transport()
        transport.has("not me")  # Force connection by issuing a request
        regular_time = time.time() - start_time
        self.assertLess(regular_time, 0.5)


class FakeSocket:
    """Fake socket object used to test the SocketDelay wrapper without
    using a real socket.
    """

    def __init__(self):
        self._data = ""

    def send(self, data, flags=0):
        self._data += data
        return len(data)

    def sendall(self, data, flags=0):
        self._data += data
        return len(data)

    def recv(self, size, flags=0):
        if size < len(self._data):
            result = self._data[:size]
            self._data = self._data[size:]
            return result
        else:
            result = self._data
            self._data = ""
            return result


class TestSocketDelay(TestCase):
    def setUp(self):
        super().setUp()
        self.requireFeature(features.paramiko)

    def test_delay(self):
        sending = FakeSocket()
        receiving = stub_sftp.SocketDelay(
            sending, 0.1, bandwidth=1000000, really_sleep=False
        )
        # check that simulated time is charged only per round-trip:
        t1 = stub_sftp.SocketDelay.simulated_time
        receiving.send("connect1")
        self.assertEqual(sending.recv(1024), "connect1")
        t2 = stub_sftp.SocketDelay.simulated_time
        self.assertAlmostEqual(t2 - t1, 0.1)
        receiving.send("connect2")
        self.assertEqual(sending.recv(1024), "connect2")
        sending.send("hello")
        self.assertEqual(receiving.recv(1024), "hello")
        t3 = stub_sftp.SocketDelay.simulated_time
        self.assertAlmostEqual(t3 - t2, 0.1)
        sending.send("hello")
        self.assertEqual(receiving.recv(1024), "hello")
        sending.send("hello")
        self.assertEqual(receiving.recv(1024), "hello")
        sending.send("hello")
        self.assertEqual(receiving.recv(1024), "hello")
        t4 = stub_sftp.SocketDelay.simulated_time
        self.assertAlmostEqual(t4, t3)

    def test_bandwidth(self):
        sending = FakeSocket()
        receiving = stub_sftp.SocketDelay(
            sending, 0, bandwidth=8.0 / (1024 * 1024), really_sleep=False
        )
        # check that simulated time is charged only per round-trip:
        t1 = stub_sftp.SocketDelay.simulated_time
        receiving.send("connect")
        self.assertEqual(sending.recv(1024), "connect")
        sending.send("a" * 100)
        self.assertEqual(receiving.recv(1024), "a" * 100)
        t2 = stub_sftp.SocketDelay.simulated_time
        self.assertAlmostEqual(t2 - t1, 100 + 7)


class ReadvFile:
    """An object that acts like Paramiko's SFTPFile when readv() is used."""

    def __init__(self, data):
        self._data = data

    def readv(self, requests):
        for start, length in requests:
            yield self._data[start : start + length]

    def close(self):
        pass


def _null_report_activity(*a, **k):
    pass


class Test_SFTPReadvHelper(tests.TestCase):
    def checkGetRequests(self, expected_requests, offsets):
        self.requireFeature(features.paramiko)
        helper = _mod_sftp._SFTPReadvHelper(
            offsets, "artificial_test", _null_report_activity
        )
        self.assertEqual(expected_requests, helper._get_requests())

    def test__get_requests(self):
        # Small single requests become a single readv request
        self.checkGetRequests([(0, 100)], [(0, 20), (30, 50), (20, 10), (80, 20)])
        # Non-contiguous ranges are given as multiple requests
        self.checkGetRequests(
            [(0, 20), (30, 50)], [(10, 10), (30, 20), (0, 10), (50, 30)]
        )
        # Ranges larger than _max_request_size (32kB) are broken up into
        # multiple requests, even if it actually spans multiple logical
        # requests
        self.checkGetRequests(
            [(0, 66000)], [(0, 40000), (40000, 100), (40100, 1900), (42000, 24000)]
        )

    def checkRequestAndYield(self, expected, data, offsets):
        self.requireFeature(features.paramiko)
        helper = _mod_sftp._SFTPReadvHelper(
            offsets, "artificial_test", _null_report_activity
        )
        data_f = ReadvFile(data)
        result = list(helper.request_and_yield_offsets(data_f))
        self.assertEqual(expected, result)

    def test_request_and_yield_offsets(self):
        data = b"abcdefghijklmnopqrstuvwxyz"
        self.checkRequestAndYield(
            [(0, b"a"), (5, b"f"), (10, b"klm")], data, [(0, 1), (5, 1), (10, 3)]
        )
        # Should combine requests, and split them again
        self.checkRequestAndYield(
            [(0, b"a"), (1, b"b"), (10, b"klm")], data, [(0, 1), (1, 1), (10, 3)]
        )
        # Out of order requests. The requests should get combined, but then be
        # yielded out-of-order. We also need one that is at the end of a
        # previous range. See bug #293746
        self.checkRequestAndYield(
            [(0, b"a"), (10, b"k"), (4, b"efg"), (1, b"bcd")],
            data,
            [(0, 1), (10, 1), (4, 3), (1, 3)],
        )


class TestUsesAuthConfig(TestCaseWithSFTPServer):
    """Test that AuthenticationConfig can supply default usernames."""

    def get_transport_for_connection(self, set_config):
        port = self.get_server().port
        if set_config:
            conf = config.AuthenticationConfig()
            conf._get_config().update(
                {"sftptest": {"scheme": "ssh", "port": port, "user": "bar"}}
            )
            conf._save()
        t = _mod_transport.get_transport_from_url("sftp://localhost:%d" % port)
        # force a connection to be performed.
        t.has("foo")
        return t

    def test_sftp_uses_config(self):
        t = self.get_transport_for_connection(set_config=True)
        self.assertEqual("bar", t._get_credentials()[0])

    def test_sftp_is_none_if_no_config(self):
        t = self.get_transport_for_connection(set_config=False)
        self.assertIs(None, t._get_credentials()[0])

    def test_sftp_doesnt_prompt_username(self):
        ui.ui_factory = tests.TestUIFactory(stdin="joe\nfoo\n")
        t = self.get_transport_for_connection(set_config=False)
        self.assertIs(None, t._get_credentials()[0])
        # No prompts should've been printed, stdin shouldn't have been read
        self.assertEqual("", ui.ui_factory.stdout.getvalue())
        self.assertEqual(0, ui.ui_factory.stdin.tell())
