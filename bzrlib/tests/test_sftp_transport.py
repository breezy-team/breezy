# Copyright (C) 2005 Robey Pointer <robey@lag.net>, Canonical Ltd
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

import os
import socket
import threading
import time

import bzrlib.bzrdir as bzrdir
import bzrlib.errors as errors
from bzrlib.osutils import pathjoin, lexists
from bzrlib.tests import TestCaseWithTransport, TestCase, TestSkipped
import bzrlib.transport
import bzrlib.transport.http
from bzrlib.workingtree import WorkingTree

try:
    import paramiko
    paramiko_loaded = True
except ImportError:
    paramiko_loaded = False


def set_test_transport_to_sftp(testcase):
    """A helper to set transports on test case instances."""
    from bzrlib.transport.sftp import SFTPAbsoluteServer, SFTPHomeDirServer
    if getattr(testcase, '_get_remote_is_absolute', None) is None:
        testcase._get_remote_is_absolute = True
    if testcase._get_remote_is_absolute:
        testcase.transport_server = SFTPAbsoluteServer
    else:
        testcase.transport_server = SFTPHomeDirServer
    testcase.transport_readonly_server = bzrlib.transport.http.HttpServer


class TestCaseWithSFTPServer(TestCaseWithTransport):
    """A test case base class that provides a sftp server on localhost."""

    def setUp(self):
        super(TestCaseWithSFTPServer, self).setUp()
        if not paramiko_loaded:
            raise TestSkipped('you must have paramiko to run this test')
        set_test_transport_to_sftp(self) 

    def get_transport(self, path=None):
        """Return a transport relative to self._test_root."""
        return bzrlib.transport.get_transport(self.get_url(path))


class SFTPLockTests (TestCaseWithSFTPServer):

    def test_sftp_locks(self):
        from bzrlib.errors import LockError
        t = self.get_transport()

        l = t.lock_write('bogus')
        self.failUnlessExists('bogus.write-lock')

        # Don't wait for the lock, locking an already locked
        # file should raise an assert
        self.assertRaises(LockError, t.lock_write, 'bogus')

        l.unlock()
        self.failIf(lexists('bogus.write-lock'))

        open('something.write-lock', 'wb').write('fake lock\n')
        self.assertRaises(LockError, t.lock_write, 'something')
        os.remove('something.write-lock')

        l = t.lock_write('something')

        l2 = t.lock_write('bogus')

        l.unlock()
        l2.unlock()

    def test_multiple_connections(self):
        t = self.get_transport()
        self.assertTrue('sftpserver - new connection' in self.get_server().logs)
        self.get_server().logs = []
        # The second request should reuse the first connection
        # SingleListener only allows for a single connection,
        # So the next line fails unless the connection is reused
        t2 = self.get_transport()
        self.assertEquals(self.get_server().logs, [])


class SFTPTransportTestRelative(TestCaseWithSFTPServer):
    """Test the SFTP transport with homedir based relative paths."""

    def test__remote_path(self):
        t = self.get_transport()
        # try what is currently used:
        # remote path = self._abspath(relpath)
        self.assertEqual(self.test_dir + '/relative', t._remote_path('relative'))
        # we dont os.path.join because windows gives us the wrong path
        root_segments = self.test_dir.split('/')
        root_parent = '/'.join(root_segments[:-1])
        # .. should be honoured
        self.assertEqual(root_parent + '/sibling', t._remote_path('../sibling'))
        # /  should be illegal ?
        ### FIXME decide and then test for all transports. RBC20051208


class SFTPTransportTestRelative(TestCaseWithSFTPServer):
    """Test the SFTP transport with homedir based relative paths."""

    def setUp(self):
        self._get_remote_is_absolute = False
        super(SFTPTransportTestRelative, self).setUp()

    def test__remote_path_relative_root(self):
        # relative paths are preserved
        t = self.get_transport('')
        self.assertEqual('a', t._remote_path('a'))


class FakeSFTPTransport (object):
    _sftp = object()
fake = FakeSFTPTransport()


class SFTPNonServerTest(TestCase):
    def setUp(self):
        TestCase.setUp(self)
        if not paramiko_loaded:
            raise TestSkipped('you must have paramiko to run this test')

    def test_parse_url(self):
        from bzrlib.transport.sftp import SFTPTransport
        s = SFTPTransport('sftp://simple.example.com/home/source', clone_from=fake)
        self.assertEquals(s._host, 'simple.example.com')
        self.assertEquals(s._port, None)
        self.assertEquals(s._path, '/home/source')
        self.failUnless(s._password is None)

        self.assertEquals(s.base, 'sftp://simple.example.com/home/source/')

        s = SFTPTransport('sftp://ro%62ey:h%40t@example.com:2222/~/relative', clone_from=fake)
        self.assertEquals(s._host, 'example.com')
        self.assertEquals(s._port, 2222)
        self.assertEquals(s._username, 'robey')
        self.assertEquals(s._password, 'h@t')
        self.assertEquals(s._path, 'relative')

        # Base should not keep track of the password
        self.assertEquals(s.base, 'sftp://robey@example.com:2222/~/relative/')

    def test_relpath(self):
        from bzrlib.transport.sftp import SFTPTransport
        from bzrlib.errors import PathNotChild

        s = SFTPTransport('sftp://user@host.com/abs/path', clone_from=fake)
        self.assertEquals(s.relpath('sftp://user@host.com/abs/path/sub'), 'sub')
        # Can't test this one, because we actually get an AssertionError
        # TODO: Consider raising an exception rather than an assert
        #self.assertRaises(PathNotChild, s.relpath, 'http://user@host.com/abs/path/sub')
        self.assertRaises(PathNotChild, s.relpath, 'sftp://user2@host.com/abs/path/sub')
        self.assertRaises(PathNotChild, s.relpath, 'sftp://user@otherhost.com/abs/path/sub')
        self.assertRaises(PathNotChild, s.relpath, 'sftp://user@host.com:33/abs/path/sub')
        self.assertRaises(PathNotChild, s.relpath, 'sftp://user@host.com/~/rel/path/sub')

        # Make sure it works when we don't supply a username
        s = SFTPTransport('sftp://host.com/abs/path', clone_from=fake)
        self.assertEquals(s.relpath('sftp://host.com/abs/path/sub'), 'sub')

        # Make sure it works when parts of the path will be url encoded
        # TODO: These may be incorrect, we might need to urllib.urlencode() before
        # we pass the paths into the SFTPTransport constructor
        s = SFTPTransport('sftp://host.com/dev/,path', clone_from=fake)
        self.assertEquals(s.relpath('sftp://host.com/dev/,path/sub'), 'sub')
        s = SFTPTransport('sftp://host.com/dev/%path', clone_from=fake)
        self.assertEquals(s.relpath('sftp://host.com/dev/%path/sub'), 'sub')

    def test_parse_invalid_url(self):
        from bzrlib.transport.sftp import SFTPTransport, TransportError
        try:
            s = SFTPTransport('sftp://lilypond.org:~janneke/public_html/bzr/gub',
                              clone_from=fake)
            self.fail('expected exception not raised')
        except TransportError, e:
            self.assertEquals(str(e),
                    'Transport error: '
                    'invalid port number ~janneke in url:\n'
                    'sftp://lilypond.org:~janneke/public_html/bzr/gub ')


class SFTPBranchTest(TestCaseWithSFTPServer):
    """Test some stuff when accessing a bzr Branch over sftp"""

    def test_lock_file(self):
        # old format branches use a special lock file on sftp.
        b = self.make_branch('', format=bzrdir.BzrDirFormat6())
        b = bzrlib.branch.Branch.open(self.get_url())
        self.failUnlessExists('.bzr/')
        self.failUnlessExists('.bzr/branch-format')
        self.failUnlessExists('.bzr/branch-lock')

        self.failIf(lexists('.bzr/branch-lock.write-lock'))
        b.lock_write()
        self.failUnlessExists('.bzr/branch-lock.write-lock')
        b.unlock()
        self.failIf(lexists('.bzr/branch-lock.write-lock'))

    def test_push_support(self):
        self.build_tree(['a/', 'a/foo'])
        t = bzrdir.BzrDir.create_standalone_workingtree('a')
        b = t.branch
        t.add('foo')
        t.commit('foo', rev_id='a1')

        b2 = bzrdir.BzrDir.create_branch_and_repo(self.get_url('/b'))
        b2.pull(b)

        self.assertEquals(b2.revision_history(), ['a1'])

        open('a/foo', 'wt').write('something new in foo\n')
        t.commit('new', rev_id='a2')
        b2.pull(b)

        self.assertEquals(b2.revision_history(), ['a1', 'a2'])


class SSHVendorConnection(TestCaseWithSFTPServer):
    """Test that the ssh vendors can all connect.

    Verify that a full-handshake (SSH over loopback TCP) sftp connection works.

    We have 3 sftp implementations in the test suite:
      'loopback': Doesn't use ssh, just uses a local socket. Most tests are
                  done this way to save the handshaking time, so it is not
                  tested again here
      'none':     This uses paramiko's built-in ssh client and server, and layers
                  sftp on top of it.
      None:       If 'ssh' exists on the machine, then it will be spawned as a
                  child process.
    """
    
    def setUp(self):
        super(SSHVendorConnection, self).setUp()
        from bzrlib.transport.sftp import SFTPFullAbsoluteServer

        def create_server():
            """Just a wrapper so that when created, it will set _vendor"""
            # SFTPFullAbsoluteServer can handle any vendor,
            # it just needs to be set between the time it is instantiated
            # and the time .setUp() is called
            server = SFTPFullAbsoluteServer()
            server._vendor = self._test_vendor
            return server
        self._test_vendor = 'loopback'
        self.transport_server = create_server
        f = open('a_file', 'wb')
        try:
            f.write('foobar\n')
        finally:
            f.close()

    def set_vendor(self, vendor):
        self._test_vendor = vendor

    def test_connection_paramiko(self):
        from bzrlib.transport import ssh
        self.set_vendor(ssh.ParamikoVendor())
        t = self.get_transport()
        self.assertEqual('foobar\n', t.get('a_file').read())

    def test_connection_vendor(self):
        raise TestSkipped("We don't test spawning real ssh,"
                          " because it prompts for a password."
                          " Enable this test if we figure out"
                          " how to prevent this.")
        self.set_vendor(None)
        t = self.get_transport()
        self.assertEqual('foobar\n', t.get('a_file').read())


class SSHVendorBadConnection(TestCaseWithTransport):
    """Test that the ssh vendors handle bad connection properly

    We don't subclass TestCaseWithSFTPServer, because we don't actually
    need an SFTP connection.
    """

    def setUp(self):
        if not paramiko_loaded:
            raise TestSkipped('you must have paramiko to run this test')
        super(SSHVendorBadConnection, self).setUp()
        import bzrlib.transport.ssh

        # open a random port, so we know nobody else is using it
        # but don't actually listen on the port.
        s = socket.socket()
        s.bind(('localhost', 0))
        self.bogus_url = 'sftp://%s:%s/' % s.getsockname()

        orig_vendor = bzrlib.transport.ssh._ssh_vendor
        def reset():
            bzrlib.transport.ssh._ssh_vendor = orig_vendor
            s.close()
        self.addCleanup(reset)

    def set_vendor(self, vendor):
        import bzrlib.transport.ssh
        bzrlib.transport.ssh._ssh_vendor = vendor

    def test_bad_connection_paramiko(self):
        """Test that a real connection attempt raises the right error"""
        from bzrlib.transport import ssh
        self.set_vendor(ssh.ParamikoVendor())
        self.assertRaises(errors.ConnectionError,
                          bzrlib.transport.get_transport, self.bogus_url)

    def test_bad_connection_ssh(self):
        """None => auto-detect vendor"""
        self.set_vendor(None)
        # This is how I would normally test the connection code
        # it makes it very clear what we are testing.
        # However, 'ssh' will create stipple on the output, so instead
        # I'm using run_bzr_subprocess, and parsing the output
        # try:
        #     t = bzrlib.transport.get_transport(self.bogus_url)
        # except errors.ConnectionError:
        #     # Correct error
        #     pass
        # except errors.NameError, e:
        #     if 'SSHException' in str(e):
        #         raise TestSkipped('Known NameError bug in paramiko 1.6.1')
        #     raise
        # else:
        #     self.fail('Excepted ConnectionError to be raised')

        out, err = self.run_bzr_subprocess('log', self.bogus_url, retcode=3)
        self.assertEqual('', out)
        if "NameError: global name 'SSHException'" in err:
            # We aren't fixing this bug, because it is a bug in
            # paramiko, but we know about it, so we don't have to
            # fail the test
            raise TestSkipped('Known NameError bug with paramiko-1.6.1')
        self.assertContainsRe(err, 'Connection error')


class SFTPLatencyKnob(TestCaseWithSFTPServer):
    """Test that the testing SFTPServer's latency knob works."""

    def test_latency_knob_slows_transport(self):
        # change the latency knob to 500ms. We take about 40ms for a 
        # loopback connection ordinarily.
        start_time = time.time()
        self.get_server().add_latency = 0.5
        transport = self.get_transport()
        with_latency_knob_time = time.time() - start_time
        self.assertTrue(with_latency_knob_time > 0.4)

    def test_default(self):
        # This test is potentially brittle: under extremely high machine load
        # it could fail, but that is quite unlikely
        start_time = time.time()
        transport = self.get_transport()
        regular_time = time.time() - start_time
        self.assertTrue(regular_time < 0.5)


class FakeSocket(object):
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
        TestCase.setUp(self)

    def test_delay(self):
        from bzrlib.transport.sftp import SocketDelay
        sending = FakeSocket()
        receiving = SocketDelay(sending, 0.1, bandwidth=1000000,
                                really_sleep=False)
        # check that simulated time is charged only per round-trip:
        t1 = SocketDelay.simulated_time
        receiving.send("connect1")
        self.assertEqual(sending.recv(1024), "connect1")
        t2 = SocketDelay.simulated_time
        self.assertAlmostEqual(t2 - t1, 0.1)
        receiving.send("connect2")
        self.assertEqual(sending.recv(1024), "connect2")
        sending.send("hello")
        self.assertEqual(receiving.recv(1024), "hello")
        t3 = SocketDelay.simulated_time
        self.assertAlmostEqual(t3 - t2, 0.1)
        sending.send("hello")
        self.assertEqual(receiving.recv(1024), "hello")
        sending.send("hello")
        self.assertEqual(receiving.recv(1024), "hello")
        sending.send("hello")
        self.assertEqual(receiving.recv(1024), "hello")
        t4 = SocketDelay.simulated_time
        self.assertAlmostEqual(t4, t3)

    def test_bandwidth(self):
        from bzrlib.transport.sftp import SocketDelay
        sending = FakeSocket()
        receiving = SocketDelay(sending, 0, bandwidth=8.0/(1024*1024),
                                really_sleep=False)
        # check that simulated time is charged only per round-trip:
        t1 = SocketDelay.simulated_time
        receiving.send("connect")
        self.assertEqual(sending.recv(1024), "connect")
        sending.send("a" * 100)
        self.assertEqual(receiving.recv(1024), "a" * 100)
        t2 = SocketDelay.simulated_time
        self.assertAlmostEqual(t2 - t1, 100 + 7)


