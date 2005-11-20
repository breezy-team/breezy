# Copyright (C) 2005 Robey Pointer <robey@lag.net>, Canonical Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

import os
import socket
import threading
import unittest

from bzrlib.selftest import TestCaseInTempDir
from bzrlib.selftest.testtransport import TestTransportMixIn

try:
    import paramiko
    from stub_sftp import StubServer, StubSFTPServer
    paramiko_loaded = True
except ImportError:
    paramiko_loaded = False


STUB_SERVER_KEY = """
-----BEGIN RSA PRIVATE KEY-----
MIICWgIBAAKBgQDTj1bqB4WmayWNPB+8jVSYpZYk80Ujvj680pOTh2bORBjbIAyz
oWGW+GUjzKxTiiPvVmxFgx5wdsFvF03v34lEVVhMpouqPAYQ15N37K/ir5XY+9m/
d8ufMCkjeXsQkKqFbAlQcnWMCRnOoPHS3I4vi6hmnDDeeYTSRvfLbW0fhwIBIwKB
gBIiOqZYaoqbeD9OS9z2K9KR2atlTxGxOJPXiP4ESqP3NVScWNwyZ3NXHpyrJLa0
EbVtzsQhLn6rF+TzXnOlcipFvjsem3iYzCpuChfGQ6SovTcOjHV9z+hnpXvQ/fon
soVRZY65wKnF7IAoUwTmJS9opqgrN6kRgCd3DASAMd1bAkEA96SBVWFt/fJBNJ9H
tYnBKZGw0VeHOYmVYbvMSstssn8un+pQpUm9vlG/bp7Oxd/m+b9KWEh2xPfv6zqU
avNwHwJBANqzGZa/EpzF4J8pGti7oIAPUIDGMtfIcmqNXVMckrmzQ2vTfqtkEZsA
4rE1IERRyiJQx6EJsz21wJmGV9WJQ5kCQQDwkS0uXqVdFzgHO6S++tjmjYcxwr3g
H0CoFYSgbddOT6miqRskOQF3DZVkJT3kyuBgU2zKygz52ukQZMqxCb1fAkASvuTv
qfpH87Qq5kQhNKdbbwbmd2NxlNabazPijWuphGTdW0VfJdWfklyS2Kr+iqrs/5wV
HhathJt636Eg7oIjAkA8ht3MQ+XSl9yIJIS8gVpbPxSw5OMfw0PjVE7tBdQruiSc
nvuQES5C9BMHjF39LZiGH1iLQy7FgdHyoP+eodI7
-----END RSA PRIVATE KEY-----
"""
    

class SingleListener (threading.Thread):
    def __init__(self, callback):
        threading.Thread.__init__(self)
        self._callback = callback
        self._socket = socket.socket()
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind(('localhost', 0))
        self._socket.listen(1)
        self.port = self._socket.getsockname()[1]
        self.stop_event = threading.Event()

    def run(self):
        s, _ = self._socket.accept()
        # now close the listen socket
        self._socket.close()
        self._callback(s, self.stop_event)
    
    def stop(self):
        self.stop_event.set()
        
        
class TestCaseWithSFTPServer (TestCaseInTempDir):
    """
    Execute a test case with a stub SFTP server, serving files from the local
    filesystem over the loopback network.
    """
    
    def _run_server(self, s, stop_event):
        ssh_server = paramiko.Transport(s)
        key_file = os.path.join(self._root, 'test_rsa.key')
        file(key_file, 'w').write(STUB_SERVER_KEY)
        host_key = paramiko.RSAKey.from_private_key_file(key_file)
        ssh_server.add_server_key(host_key)
        server = StubServer()
        ssh_server.set_subsystem_handler('sftp', paramiko.SFTPServer, StubSFTPServer, root=self._root)
        event = threading.Event()
        ssh_server.start_server(event, server)
        event.wait(5.0)
        stop_event.wait(30.0)

    def setUp(self):
        TestCaseInTempDir.setUp(self)
        self._root = self.test_dir

    def delayed_setup(self):
        # some tests are just stubs that call setUp and then immediately call
        # tearDwon.  so don't create the port listener until get_transport is
        # called and we know we're in an actual test.
        self._listener = SingleListener(self._run_server)
        self._listener.setDaemon(True)
        self._listener.start()        
        self._sftp_url = 'sftp://foo:bar@localhost:%d/' % (self._listener.port,)
        
    def tearDown(self):
        try:
            self._listener.stop()
        except AttributeError:
            pass
        TestCaseInTempDir.tearDown(self)

        
class SFTPTransportTest (TestCaseWithSFTPServer, TestTransportMixIn):
    readonly = False
    setup = True

    def get_transport(self):
        if self.setup:
            self.delayed_setup()
            self.setup = False
        from bzrlib.transport.sftp import SFTPTransport
        url = self._sftp_url
        return SFTPTransport(url)

    def test_sftp_locks(self):
        from bzrlib.errors import LockError
        t = self.get_transport()

        l = t.lock_write('bogus')
        self.failUnlessExists('bogus.write-lock')

        # Don't wait for the lock, locking an already locked
        # file should raise an assert
        self.assertRaises(LockError, t.lock_write, 'bogus')

        l.unlock()
        self.failIf(os.path.lexists('bogus.write-lock'))

        open('something.write-lock', 'wb').write('fake lock\n')
        self.assertRaises(LockError, t.lock_write, 'something')
        os.remove('something.write-lock')

        l = t.lock_write('something')

        l2 = t.lock_write('bogus')

        l.unlock()
        l2.unlock()


class FakeSFTPTransport (object):
    _sftp = object()
fake = FakeSFTPTransport()


class SFTPNonServerTest (unittest.TestCase):
    def test_parse_url(self):
        from bzrlib.transport.sftp import SFTPTransport
        s = SFTPTransport('sftp://simple.example.com/%2fhome/source', clone_from=fake)
        self.assertEquals(s._host, 'simple.example.com')
        self.assertEquals(s._port, 22)
        self.assertEquals(s._path, '/home/source')
        self.assert_(s._password is None)
        
        s = SFTPTransport('sftp://ro%62ey:h%40t@example.com:2222/relative', clone_from=fake)
        self.assertEquals(s._host, 'example.com')
        self.assertEquals(s._port, 2222)
        self.assertEquals(s._username, 'robey')
        self.assertEquals(s._password, 'h@t')
        self.assertEquals(s._path, 'relative')
        

class SFTPBranchTest(TestCaseWithSFTPServer):
    """Test some stuff when accessing a bzr Branch over sftp"""

    def test_lock_file(self):
        """Make sure that a Branch accessed over sftp tries to lock itself."""
        from bzrlib.branch import Branch

        b = Branch.initialize(self._sftp_url)
        self.failUnlessExists('.bzr/')
        self.failUnlessExists('.bzr/branch-format')
        self.failUnlessExists('.bzr/branch-lock')

        self.failIf(os.path.lexists('.bzr/branch-lock.write-lock'))
        b.lock_write()
        self.failUnlessExists('.bzr/branch-lock.write-lock')
        b.unlock()
        self.failIf(os.path.lexists('.bzr/branch-lock.write-lock'))


if not paramiko_loaded:
    # TODO: Skip these
    del SFTPTransportTest
    del SFTPNonServerTest
    del SFTPBranchTest
