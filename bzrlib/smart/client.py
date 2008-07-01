# Copyright (C) 2006-2008 Canonical Ltd
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

import bzrlib
from bzrlib.smart import message, protocol
from bzrlib.trace import warning
from bzrlib import errors


class _SmartClient(object):

    def __init__(self, medium, headers=None):
        """Constructor.

        :param medium: a SmartClientMedium
        """
        self._medium = medium
        if headers is None:
            self._headers = {'Software version': bzrlib.__version__}
        else:
            self._headers = dict(headers)

    def _send_request(self, protocol_version, method, args, body=None,
                      readv_body=None):
        encoder, response_handler = self._construct_protocol(
            protocol_version)
        encoder.set_headers(self._headers)
        if body is not None:
            if readv_body is not None:
                raise AssertionError(
                    "body and readv_body are mutually exclusive.")
            encoder.call_with_body_bytes((method, ) + args, body)
        elif readv_body is not None:
            encoder.call_with_body_readv_array((method, ) + args,
                    readv_body)
        else:
            encoder.call(method, *args)
        return response_handler

    def _call_and_read_response(self, method, args, body=None, readv_body=None,
            expect_response_body=True):
        if self._medium._protocol_version is not None:
            response_handler = self._send_request(
                self._medium._protocol_version, method, args, body=body,
                readv_body=readv_body)
            return (response_handler.read_response_tuple(
                        expect_body=expect_response_body),
                    response_handler)
        else:
            for protocol_version in [3, 2]:
                if protocol_version == 2:
                    # If v3 doesn't work, the remote side is older than 1.6.
                    self._medium._remember_remote_is_before((1, 6))
                response_handler = self._send_request(
                    protocol_version, method, args, body=body,
                    readv_body=readv_body)
                try:
                    response_tuple = response_handler.read_response_tuple(
                        expect_body=expect_response_body)
                except errors.UnexpectedProtocolVersionMarker, err:
                    # TODO: We could recover from this without disconnecting if
                    # we recognise the protocol version.
                    warning(
                        'Server does not understand Bazaar network protocol %d,'
                        ' reconnecting.  (Upgrade the server to avoid this.)'
                        % (protocol_version,))
                    self._medium.disconnect()
                    continue
                except errors.ErrorFromSmartServer:
                    # If we received an error reply from the server, then it
                    # must be ok with this protocol version.
                    self._medium._protocol_version = protocol_version
                    raise
                else:
                    self._medium._protocol_version = protocol_version
                    return response_tuple, response_handler
            raise errors.SmartProtocolError(
                'Server is not a Bazaar server: ' + str(err))

    def _construct_protocol(self, version):
        request = self._medium.get_request()
        if version == 3:
            request_encoder = protocol.ProtocolThreeRequester(request)
            response_handler = message.ConventionalResponseHandler()
            response_proto = protocol.ProtocolThreeDecoder(
                response_handler, expect_version_marker=True)
            response_handler.setProtoAndMediumRequest(response_proto, request)
        elif version == 2:
            request_encoder = protocol.SmartClientRequestProtocolTwo(request)
            response_handler = request_encoder
        else:
            request_encoder = protocol.SmartClientRequestProtocolOne(request)
            response_handler = request_encoder
        return request_encoder, response_handler

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
        return self._call_and_read_response(
            method, args, expect_response_body=True)

    def call_with_body_bytes(self, method, args, body):
        """Call a method on the remote server with body bytes."""
        if type(method) is not str:
            raise TypeError('method must be a byte string, not %r' % (method,))
        for arg in args:
            if type(arg) is not str:
                raise TypeError('args must be byte strings, not %r' % (args,))
        if type(body) is not str:
            raise TypeError('body must be byte string, not %r' % (body,))
        response, response_handler = self._call_and_read_response(
            method, args, body=body, expect_response_body=False)
        return response

    def call_with_body_bytes_expecting_body(self, method, args, body):
        """Call a method on the remote server with body bytes."""
        if type(method) is not str:
            raise TypeError('method must be a byte string, not %r' % (method,))
        for arg in args:
            if type(arg) is not str:
                raise TypeError('args must be byte strings, not %r' % (args,))
        if type(body) is not str:
            raise TypeError('body must be byte string, not %r' % (body,))
        response, response_handler = self._call_and_read_response(
            method, args, body=body, expect_response_body=True)
        return (response, response_handler)

    def call_with_body_readv_array(self, args, body):
        response, response_handler = self._call_and_read_response(
                args[0], args[1:], readv_body=body, expect_response_body=True)
        return (response, response_handler)

    def remote_path_from_transport(self, transport):
        """Convert transport into a path suitable for using in a request.
        
        Note that the resulting remote path doesn't encode the host name or
        anything but path, so it is only safe to use it in requests sent over
        the medium from the matching transport.
        """
        return self._medium.remote_path_from_transport(transport)

