# Copyright (C) 2005-2011 Canonical Ltd
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


import errno
import socket
import select
import threading


class DisconnectingTCPServer(object):
    """A TCP server that immediately closes any connection made to it."""

    def start_server(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(('127.0.0.1', 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self.thread = threading.Thread(
            name='%s (port %d)' % (self.__class__.__name__, self.port),
            target=self.accept_and_close)
        self.thread.start()

    def accept_and_close(self):
        # We apparently can't do a blocking accept() because Python
        # can get jammed up between here and the main thread - see
        # https://code.launchpad.net/~jelmer/bzr/2.5-client-reconnect-819604/+merge/83425
        fd = self.sock.fileno()
        self.sock.setblocking(False)
        while True:
            try:
                select.select([fd], [], [fd], 1.0)
                conn, addr = self.sock.accept()
            except socket.error, e:
                if e.errno == errno.EBADF:
                    # Probably (hopefully) because the stop method was called
                    # and we should stop.
                    return
                else:
                    raise
            except select.error, e:
                # Gratuituous incompatibility: no errno attribute.
                if e[0] == errno.EBADF:
                    return
                else:
                    raise
            conn.shutdown(socket.SHUT_RDWR)
            conn.close()

    def get_url(self):
        return 'bzr://127.0.0.1:%d/' % (self.port,)

    def stop_server(self):
        try:
            # make sure the thread dies by connecting to the listening socket,
            # just in case the test failed to do so.
            conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            conn.connect(self.sock.getsockname())
            conn.close()
        except socket.error:
            pass
        self.sock.close()
        self.thread.join()
