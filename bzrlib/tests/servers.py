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
        self._please_stop = False
        self.thread.start()

    def accept_and_close(self):
        fd = self.sock.fileno()
        self.sock.setblocking(False)
        while not self._please_stop:
            try:
                # We can't just accept here, because accept is not interrupted
                # by the listen socket being asynchronously closed by
                # stop_server.  However, select will be interrupted.
                select.select([fd], [fd], [fd], 10)
                conn, addr = self.sock.accept()
            except (select.error, socket.error), e:
                en = getattr(e, 'errno') or e[0]
                if en == errno.EBADF:
                    # Probably (hopefully) because the stop method was called
                    # and we should stop.
                    break
                elif en == errno.EAGAIN or en == errno.EWOULDBLOCK:
                    continue
                else:
                    raise
            conn.shutdown(socket.SHUT_RDWR)
            conn.close()

    def get_url(self):
        return 'bzr://127.0.0.1:%d/' % (self.port,)

    def stop_server(self):
        self._please_stop = True
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
