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

import urllib
from urlparse import urlparse

from bzrlib.smart import message, protocol
from bzrlib import urlutils


class _SmartClient(object):

    def __init__(self, shared_connection):
        """Constructor.

        :param shared_connection: a bzrlib.transport._SharedConnection
        """
        self._shared_connection = shared_connection

    def get_smart_medium(self):
        return self._shared_connection.connection

    def call(self, method, *args):
        """Call a method on the remote server."""
        result, protocol = self.call_expecting_body(method, *args)
        protocol.cancel_read_body()
        return result

    def call_expecting_body(self, method, *args):
        """Call a method and return the result and the protocol object.
        
        The body can be read like so::

            result, smart_protocol = smart_client.call_expecting_body(...)
            body = smart_protocol.read_body_bytes()
        """
        # Get a medium
        medium_request = self.get_smart_medium().get_request()

        # Send a request over the medium
        request_encoder = protocol.ProtocolThreeRequester(medium_request)
        request_encoder.call(method, *args)
        
        # Handle the response
        response_handler = message.ConventionalResponseHandler()
        response_proto = protocol._ProtocolThreeBase(response_handler)
        response_handler.setProtoAndMedium(response_proto, medium_request)
        response_tuple = response_handler.read_response_tuple()
        return response_tuple, response_handler

    def call_with_body_bytes(self, method, args, body):
        """Call a method on the remote server with body bytes."""
        if type(method) is not str:
            raise TypeError('method must be a byte string, not %r' % (method,))
        for arg in args:
            if type(arg) is not str:
                raise TypeError('args must be byte strings, not %r' % (args,))
        if type(body) is not str:
            raise TypeError('body must be byte string, not %r' % (body,))
        request = self.get_smart_medium().get_request()
        smart_protocol = protocol.SmartClientRequestProtocolOne(request)
        smart_protocol.call_with_body_bytes((method, ) + args, body)
        return smart_protocol.read_response_tuple()

    def call_with_body_bytes_expecting_body(self, method, args, body):
        """Call a method on the remote server with body bytes."""
        if type(method) is not str:
            raise TypeError('method must be a byte string, not %r' % (method,))
        for arg in args:
            if type(arg) is not str:
                raise TypeError('args must be byte strings, not %r' % (args,))
        if type(body) is not str:
            raise TypeError('body must be byte string, not %r' % (body,))
        request = self.get_smart_medium().get_request()
        smart_protocol = protocol.SmartClientRequestProtocolTwo(request)
        smart_protocol.call_with_body_bytes((method, ) + args, body)
        return smart_protocol.read_response_tuple(expect_body=True), smart_protocol

    def remote_path_from_transport(self, transport):
        """Convert transport into a path suitable for using in a request.
        
        Note that the resulting remote path doesn't encode the host name or
        anything but path, so it is only safe to use it in requests sent over
        the medium from the matching transport.
        """
        if self._shared_connection.base.startswith('bzr+http://'):
            medium_base = self._shared_connection.base
        else:
            medium_base = urlutils.join(self._shared_connection.base, '/')
            
        rel_url = urlutils.relative_url(medium_base, transport.base)
        return urllib.unquote(rel_url)
