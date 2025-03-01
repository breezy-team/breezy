# Copyright (C) 2005, 2006, 2008-2011 Robey Pointer <robey@lag.net>, Canonical Ltd
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

"""A stub SFTP server for loopback SFTP testing.
Adapted from the one in paramiko's unit tests.
"""

import os
import socket
import socketserver
import sys
import time

import paramiko

from .. import osutils, trace, urlutils
from ..transport import ssh
from . import test_server


class StubServer(paramiko.ServerInterface):
    def __init__(self, test_case_server):
        paramiko.ServerInterface.__init__(self)
        self.log = test_case_server.log

    def check_auth_password(self, username, password):
        # all are allowed
        self.log("sftpserver - authorizing: {}".format(username))
        return paramiko.AUTH_SUCCESSFUL

    def check_channel_request(self, kind, chanid):
        self.log("sftpserver - channel request: {}, {}".format(kind, chanid))
        return paramiko.OPEN_SUCCEEDED


class StubSFTPHandle(paramiko.SFTPHandle):
    def stat(self):
        try:
            return paramiko.SFTPAttributes.from_stat(os.fstat(self.readfile.fileno()))
        except OSError as e:
            return paramiko.SFTPServer.convert_errno(e.errno)

    def chattr(self, attr):
        # python doesn't have equivalents to fchown or fchmod, so we have to
        # use the stored filename
        trace.mutter("Changing permissions on %s to %s", self.filename, attr)
        try:
            paramiko.SFTPServer.set_file_attr(self.filename, attr)
        except OSError as e:
            return paramiko.SFTPServer.convert_errno(e.errno)


class StubSFTPServer(paramiko.SFTPServerInterface):
    def __init__(self, server, root, home=None):
        paramiko.SFTPServerInterface.__init__(self, server)
        # All paths are actually relative to 'root'.
        # this is like implementing chroot().
        self.root = root
        if home is None:
            self.home = ""
        else:
            if not home.startswith(self.root):
                raise AssertionError(
                    "home must be a subdirectory of root ({} vs {})".format(home, root)
                )
            self.home = home[len(self.root) :]
        if self.home.startswith("/"):
            self.home = self.home[1:]
        server.log("sftpserver - new connection")

    def _realpath(self, path):
        # paths returned from self.canonicalize() always start with
        # a path separator. So if 'root' is just '/', this would cause
        # a double slash at the beginning '//home/dir'.
        if self.root == "/":
            return self.canonicalize(path)
        return self.root + self.canonicalize(path)

    if sys.platform == "win32":

        def canonicalize(self, path):
            # Win32 sftp paths end up looking like
            #     sftp://host@foo/h:/foo/bar
            # which means absolute paths look like:
            #     /h:/foo/bar
            # and relative paths stay the same:
            #     foo/bar
            # win32 needs to use the Unicode APIs. so we require the
            # paths to be utf8 (Linux just uses bytestreams)
            thispath = path.decode("utf8")
            if path.startswith("/"):
                # Abspath H:/foo/bar
                return os.path.normpath(thispath[1:])
            else:
                return os.path.normpath(os.path.join(self.home, thispath))
    else:

        def canonicalize(self, path):
            if os.path.isabs(path):
                return osutils.normpath(path)
            else:
                return osutils.normpath("/" + os.path.join(self.home, path))

    def chattr(self, path, attr):
        try:
            paramiko.SFTPServer.set_file_attr(path, attr)
        except OSError as e:
            return paramiko.SFTPServer.convert_errno(e.errno)
        return paramiko.SFTP_OK

    def list_folder(self, path):
        path = self._realpath(path)
        try:
            out = []
            # TODO: win32 incorrectly lists paths with non-ascii if path is not
            # unicode. However on unix the server should only deal with
            # bytestreams and posix.listdir does the right thing
            if sys.platform == "win32":
                flist = [f.encode("utf8") for f in os.listdir(path)]
            else:
                flist = os.listdir(path)
            for fname in flist:
                attr = paramiko.SFTPAttributes.from_stat(
                    os.stat(osutils.pathjoin(path, fname))
                )
                attr.filename = fname
                out.append(attr)
            return out
        except OSError as e:
            return paramiko.SFTPServer.convert_errno(e.errno)

    def stat(self, path):
        path = self._realpath(path)
        try:
            return paramiko.SFTPAttributes.from_stat(os.stat(path))
        except OSError as e:
            return paramiko.SFTPServer.convert_errno(e.errno)

    def lstat(self, path):
        path = self._realpath(path)
        try:
            return paramiko.SFTPAttributes.from_stat(os.lstat(path))
        except OSError as e:
            return paramiko.SFTPServer.convert_errno(e.errno)

    def open(self, path, flags, attr):
        path = self._realpath(path)
        try:
            flags |= getattr(os, "O_BINARY", 0)
            if getattr(attr, "st_mode", None):
                fd = os.open(path, flags, attr.st_mode)
            else:
                # os.open() defaults to 0777 which is
                # an odd default mode for files
                fd = os.open(path, flags, 0o666)
        except OSError as e:
            return paramiko.SFTPServer.convert_errno(e.errno)

        if (flags & os.O_CREAT) and (attr is not None):
            attr._flags &= ~attr.FLAG_PERMISSIONS
            paramiko.SFTPServer.set_file_attr(path, attr)
        if flags & os.O_WRONLY:
            fstr = "wb"
        elif flags & os.O_RDWR:
            fstr = "rb+"
        else:
            # O_RDONLY (== 0)
            fstr = "rb"
        try:
            f = os.fdopen(fd, fstr)
        except OSError as e:
            return paramiko.SFTPServer.convert_errno(e.errno)
        fobj = StubSFTPHandle()
        fobj.filename = path
        fobj.readfile = f
        fobj.writefile = f
        return fobj

    def remove(self, path):
        path = self._realpath(path)
        try:
            os.remove(path)
        except OSError as e:
            return paramiko.SFTPServer.convert_errno(e.errno)
        return paramiko.SFTP_OK

    def rename(self, oldpath, newpath):
        oldpath = self._realpath(oldpath)
        newpath = self._realpath(newpath)
        try:
            os.rename(oldpath, newpath)
        except OSError as e:
            return paramiko.SFTPServer.convert_errno(e.errno)
        return paramiko.SFTP_OK

    def symlink(self, target_path, path):
        path = self._realpath(path)
        try:
            os.symlink(target_path, path)
        except OSError as e:
            return paramiko.SFTPServer.convert_errno(e.errno)
        return paramiko.SFTP_OK

    def readlink(self, path):
        path = self._realpath(path)
        try:
            target_path = os.readlink(path)
        except OSError as e:
            return paramiko.SFTPServer.convert_errno(e.errno)
        return target_path

    def mkdir(self, path, attr):
        path = self._realpath(path)
        try:
            # Using getattr() in case st_mode is None or 0
            # both evaluate to False
            if getattr(attr, "st_mode", None):
                os.mkdir(path, attr.st_mode)
            else:
                os.mkdir(path)
            if attr is not None:
                attr._flags &= ~attr.FLAG_PERMISSIONS
                paramiko.SFTPServer.set_file_attr(path, attr)
        except OSError as e:
            return paramiko.SFTPServer.convert_errno(e.errno)
        return paramiko.SFTP_OK

    def rmdir(self, path):
        path = self._realpath(path)
        try:
            os.rmdir(path)
        except OSError as e:
            return paramiko.SFTPServer.convert_errno(e.errno)
        return paramiko.SFTP_OK

    # removed: chattr
    # (nothing in bzr's sftp transport uses those)


# ------------- server test implementation --------------

STUB_SERVER_KEY = """\
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


class SocketDelay:
    """A socket decorator to make TCP appear slower.

    This changes recv, send, and sendall to add a fixed latency to each python
    call if a new roundtrip is detected. That is, when a recv is called and the
    flag new_roundtrip is set, latency is charged. Every send and send_all
    sets this flag.

    In addition every send, sendall and recv sleeps a bit per character send to
    simulate bandwidth.

    Not all methods are implemented, this is deliberate as this class is not a
    replacement for the builtin sockets layer. fileno is not implemented to
    prevent the proxy being bypassed.
    """

    simulated_time = 0
    _proxied_arguments = dict.fromkeys(
        [
            "close",
            "getpeername",
            "getsockname",
            "getsockopt",
            "gettimeout",
            "setblocking",
            "setsockopt",
            "settimeout",
            "shutdown",
        ]
    )

    def __init__(self, sock, latency, bandwidth=1.0, really_sleep=True):
        """:param bandwith: simulated bandwith (MegaBit)
        :param really_sleep: If set to false, the SocketDelay will just
        increase a counter, instead of calling time.sleep. This is useful for
        unittesting the SocketDelay.
        """
        self.sock = sock
        self.latency = latency
        self.really_sleep = really_sleep
        self.time_per_byte = 1 / (bandwidth / 8.0 * 1024 * 1024)
        self.new_roundtrip = False

    def sleep(self, s):
        if self.really_sleep:
            time.sleep(s)
        else:
            SocketDelay.simulated_time += s

    def __getattr__(self, attr):
        if attr in SocketDelay._proxied_arguments:
            return getattr(self.sock, attr)
        raise AttributeError("'SocketDelay' object has no attribute {!r}".format(attr))

    def dup(self):
        return SocketDelay(
            self.sock.dup(), self.latency, self.time_per_byte, self._sleep
        )

    def recv(self, *args):
        data = self.sock.recv(*args)
        if data and self.new_roundtrip:
            self.new_roundtrip = False
            self.sleep(self.latency)
        self.sleep(len(data) * self.time_per_byte)
        return data

    def sendall(self, data, flags=0):
        if not self.new_roundtrip:
            self.new_roundtrip = True
            self.sleep(self.latency)
        self.sleep(len(data) * self.time_per_byte)
        return self.sock.sendall(data, flags)

    def send(self, data, flags=0):
        if not self.new_roundtrip:
            self.new_roundtrip = True
            self.sleep(self.latency)
        bytes_sent = self.sock.send(data, flags)
        self.sleep(bytes_sent * self.time_per_byte)
        return bytes_sent


class TestingSFTPConnectionHandler(socketserver.BaseRequestHandler):
    def setup(self):
        self.wrap_for_latency()
        tcs = self.server.test_case_server
        ptrans = paramiko.Transport(self.request)
        self.paramiko_transport = ptrans
        # Set it to a channel under 'bzr' so that we get debug info
        ptrans.set_log_channel("brz.paramiko.transport")
        ptrans.add_server_key(tcs.get_host_key())
        ptrans.set_subsystem_handler(
            "sftp",
            paramiko.SFTPServer,
            StubSFTPServer,
            root=tcs._root,
            home=tcs._server_homedir,
        )
        server = tcs._server_interface(tcs)
        # This blocks until the key exchange has been done
        ptrans.start_server(None, server)

    def finish(self):
        # Wait for the conversation to finish, when the paramiko.Transport
        # thread finishes
        # TODO: Consider timing out after XX seconds rather than hanging.
        #       Also we could check paramiko_transport.active and possibly
        #       paramiko_transport.getException().
        self.paramiko_transport.join()

    def wrap_for_latency(self):
        tcs = self.server.test_case_server
        if tcs.add_latency:
            # Give the socket (which the request really is) a latency adding
            # decorator.
            self.request = SocketDelay(self.request, tcs.add_latency)


class TestingSFTPWithoutSSHConnectionHandler(TestingSFTPConnectionHandler):
    def setup(self):
        self.wrap_for_latency()
        # Re-import these as locals, so that they're still accessible during
        # interpreter shutdown (when all module globals get set to None, leading
        # to confusing errors like "'NoneType' object has no attribute 'error'".

        class FakeChannel:
            def get_transport(self):
                return self

            def get_log_channel(self):
                return "brz.paramiko"

            def get_name(self):
                return "1"

            def get_hexdump(self):
                return False

            def close(self):
                pass

        tcs = self.server.test_case_server
        sftp_server = paramiko.SFTPServer(
            FakeChannel(),
            "sftp",
            StubServer(tcs),
            StubSFTPServer,
            root=tcs._root,
            home=tcs._server_homedir,
        )
        self.sftp_server = sftp_server
        sys_stderr = sys.stderr  # Used in error reporting during shutdown
        try:
            sftp_server.start_subsystem(
                "sftp", None, ssh.SocketAsChannelAdapter(self.request)
            )
        except OSError as e:
            if (len(e.args) > 0) and (e.args[0] == errno.EPIPE):
                # it's okay for the client to disconnect abruptly
                # (bug in paramiko 1.6: it should absorb this exception)
                pass
            else:
                raise
        except Exception as e:
            # This typically seems to happen during interpreter shutdown, so
            # most of the useful ways to report this error won't work.
            # Writing the exception type, and then the text of the exception,
            # seems to be the best we can do.
            # FIXME: All interpreter shutdown errors should have been related
            # to daemon threads, cleanup needed -- vila 20100623
            sys_stderr.write("\nEXCEPTION {!r}: ".format(e.__class__))
            sys_stderr.write("{}\n\n".format(e))

    def finish(self):
        self.sftp_server.finish_subsystem()


class TestingSFTPServer(test_server.TestingThreadingTCPServer):
    def __init__(self, server_address, request_handler_class, test_case_server):
        test_server.TestingThreadingTCPServer.__init__(
            self, server_address, request_handler_class
        )
        self.test_case_server = test_case_server


class SFTPServer(test_server.TestingTCPServerInAThread):
    """Common code for SFTP server facilities."""

    def __init__(self, server_interface=StubServer):
        self.host = "127.0.0.1"
        self.port = 0
        super().__init__(
            (self.host, self.port), TestingSFTPServer, TestingSFTPConnectionHandler
        )
        self._original_vendor = None
        self._vendor = ssh.ParamikoVendor()
        self._server_interface = server_interface
        self._host_key = None
        self.logs = []
        self.add_latency = 0
        self._homedir = None
        self._server_homedir = None
        self._root = None

    def _get_sftp_url(self, path):
        """Calculate an sftp url to this server for path."""
        return "sftp://foo:bar@{}:{}/{}".format(self.host, self.port, path)

    def log(self, message):
        """StubServer uses this to log when a new server is created."""
        self.logs.append(message)

    def create_server(self):
        server = self.server_class(
            (self.host, self.port), self.request_handler_class, self
        )
        return server

    def get_host_key(self):
        if self._host_key is None:
            key_file = osutils.pathjoin(self._homedir, "test_rsa.key")
            f = open(key_file, "w")
            try:
                f.write(STUB_SERVER_KEY)
            finally:
                f.close()
            self._host_key = paramiko.RSAKey.from_private_key_file(key_file)
        return self._host_key

    def start_server(self, backing_server=None):
        # XXX: TODO: make sftpserver back onto backing_server rather than local
        # disk.
        if not (
            backing_server is None
            or isinstance(backing_server, test_server.LocalURLServer)
        ):
            raise AssertionError(
                "backing_server should not be {!r}, because this can only serve "
                "the local current working directory.".format(backing_server)
            )
        self._original_vendor = ssh._ssh_vendor_manager._cached_ssh_vendor
        ssh._ssh_vendor_manager._cached_ssh_vendor = self._vendor
        self._homedir = osutils.getcwd()
        if sys.platform == "win32":
            # Normalize the path or it will be wrongly escaped
            self._homedir = osutils.normpath(self._homedir)
        else:
            self._homedir = self._homedir
        if self._server_homedir is None:
            self._server_homedir = self._homedir
        self._root = "/"
        if sys.platform == "win32":
            self._root = ""
        super().start_server()

    def stop_server(self):
        try:
            super().stop_server()
        finally:
            ssh._ssh_vendor_manager._cached_ssh_vendor = self._original_vendor

    def get_bogus_url(self):
        """See breezy.transport.Server.get_bogus_url."""
        # this is chosen to try to prevent trouble with proxies, weird dns, etc
        # we bind a random socket, so that we get a guaranteed unused port
        # we just never listen on that port
        s = socket.socket()
        s.bind(("localhost", 0))
        return "sftp://{}:{}/".format(*s.getsockname())


class SFTPFullAbsoluteServer(SFTPServer):
    """A test server for sftp transports, using absolute urls and ssh."""

    def get_url(self):
        """See breezy.transport.Server.get_url."""
        homedir = self._homedir
        if sys.platform != "win32":
            # Remove the initial '/' on all platforms but win32
            homedir = homedir[1:]
        return self._get_sftp_url(urlutils.escape(homedir))


class SFTPServerWithoutSSH(SFTPServer):
    """An SFTP server that uses a simple TCP socket pair rather than SSH."""

    def __init__(self):
        super().__init__()
        self._vendor = ssh.LoopbackVendor()
        self.request_handler_class = TestingSFTPWithoutSSHConnectionHandler

    def get_host_key(self):
        return None


class SFTPAbsoluteServer(SFTPServerWithoutSSH):
    """A test server for sftp transports, using absolute urls."""

    def get_url(self):
        """See breezy.transport.Server.get_url."""
        homedir = self._homedir
        if sys.platform != "win32":
            # Remove the initial '/' on all platforms but win32
            homedir = homedir[1:]
        return self._get_sftp_url(urlutils.escape(homedir))


class SFTPHomeDirServer(SFTPServerWithoutSSH):
    """A test server for sftp transports, using homedir relative urls."""

    def get_url(self):
        """See breezy.transport.Server.get_url."""
        return self._get_sftp_url("%7E/")


class SFTPSiblingAbsoluteServer(SFTPAbsoluteServer):
    """A test server for sftp transports where only absolute paths will work.

    It does this by serving from a deeply-nested directory that doesn't exist.
    """

    def create_server(self):
        # FIXME: Can't we do that in a cleaner way ? -- vila 20100623
        server = super().create_server()
        server._server_homedir = "/dev/noone/runs/tests/here"
        return server
