# Copyright (C) 2006 Canonical Ltd
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

from urlparse import urlparse

from bzrlib.smart import protocol
from bzrlib.urlutils import unescape


class SmartClient(object):

    def __init__(self, medium):
        self._medium = medium

    def call(self, method, *args):
        """Call a method on the remote server."""
        result, protocol = self.call2(method, *args)
        protocol.cancel_read_body()
        return result

    def call2(self, method, *args):
        """Call a method and return the result and the protocol object."""
        request = self._medium.get_request()
        smart_protocol = protocol.SmartClientRequestProtocolOne(request)
        smart_protocol.call(method, *args)
        return smart_protocol.read_response_tuple(expect_body=True), smart_protocol

    def call_with_body_bytes(self, method, args, body):
        """Call a method on the remote server with body bytes."""
        request = self._medium.get_request()
        smart_protocol = protocol.SmartClientRequestProtocolOne(request)
        smart_protocol.call_with_body_bytes((method, ) + args, body)
        return smart_protocol.read_response_tuple()

    def remote_path_from_transport(self, transport):
        """Convert transport into a path suitable for using in a request."""
        return unescape(urlparse(transport.base)[2]).encode('utf8')
