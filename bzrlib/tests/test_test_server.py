# Copyright (C) 2010 Canonical Ltd
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

import socket
import SocketServer

from bzrlib import (
    osutils,
    tests,
    )
from bzrlib.tests import test_server

class TCPClient(object):

    def __init__(self):
        self.sock = None

    def connect(self, addr):
        if self.sock is not None:
            raise AssertionError('Already connected to %r'
                                 % (self.sock.getsockname(),))
        self.sock = osutils.connect_socket(addr)

    def disconnect(self):
        if self.sock is not None:
            self.sock.shutdown(socket.SHUT_RDWR)
            self.sock.close()
            self.sock = None

    def write(self, s):
        return self.sock.sendall(s)

    def read(self, bufsize=4096):
        return self.sock.recv(bufsize)


class TCPConnectionHandler(SocketServer.StreamRequestHandler):

    def handle(self):
        self.done = False
        self.handle_connection()
        while not self.done:
            self.handle_connection()

    def handle_connection(self):
        req = self.rfile.readline()
        if not req:
            self.done = True
        elif req == 'ping\n':
            self.wfile.write('pong\n')
        else:
            raise ValueError('[%s] not understood' % req)


class TestTestingServerInAThread(tests.TestCase):

    def get_server(self):
        server =  test_server.TestingTCPServerInAThread(
            ('localhost', 0), test_server.TestingTCPServer,
            TCPConnectionHandler)
        server.start_server()
        self.addCleanup(server.stop_server)
        return server

    def get_client(self):
        client = TCPClient()
        self.addCleanup(client.disconnect)
        return client

    def test_start_stop(self):
        server = self.get_server()
        client = self.get_client()
        client.connect(server.server_address)
        server.stop_server()
        # since the server doesn't accept connections anymore attempting to
        # connect should fail
        client = self.get_client()
        self.assertRaises(socket.error, client.connect, server.server_address)


    def test_client_talks_server_respond(self):
        server = self.get_server()
        client = self.get_client()
        client.connect(server.server_address)
        self.assertIs(None, client.write('ping\n'))
        resp = client.read()
        self.assertEquals('pong\n', resp)
