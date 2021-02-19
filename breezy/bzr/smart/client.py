# Copyright (C) 2006-2010 Canonical Ltd
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

from ... import lazy_import
lazy_import.lazy_import(globals(), """
from breezy.bzr.smart import request as _mod_request
""")

import breezy
from . import message, protocol
from ... import (
    debug,
    errors,
    hooks,
    trace,
    )


class _SmartClient(object):

    def __init__(self, medium, headers=None):
        """Constructor.

        :param medium: a SmartClientMedium
        """
        self._medium = medium
        if headers is None:
            self._headers = {
                b'Software version': breezy.__version__.encode('utf-8')}
        else:
            self._headers = dict(headers)

    def __repr__(self):
        return '%s(%r)' % (self.__class__.__name__, self._medium)

    def _call_and_read_response(self, method, args, body=None, readv_body=None,
                                body_stream=None, expect_response_body=True):
        request = _SmartClientRequest(self, method, args, body=body,
                                      readv_body=readv_body, body_stream=body_stream,
                                      expect_response_body=expect_response_body)
        return request.call_and_read_response()

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
        if not isinstance(method, bytes):
            raise TypeError('method must be a byte string, not %r' % (method,))
        for arg in args:
            if not isinstance(arg, bytes):
                raise TypeError('args must be byte strings, not %r' % (args,))
        if not isinstance(body, bytes):
            raise TypeError('body must be byte string, not %r' % (body,))
        response, response_handler = self._call_and_read_response(
            method, args, body=body, expect_response_body=False)
        return response

    def call_with_body_bytes_expecting_body(self, method, args, body):
        """Call a method on the remote server with body bytes."""
        if not isinstance(method, bytes):
            raise TypeError('method must be a byte string, not %r' % (method,))
        for arg in args:
            if not isinstance(arg, bytes):
                raise TypeError('args must be byte strings, not %r' % (args,))
        if not isinstance(body, bytes):
            raise TypeError('body must be byte string, not %r' % (body,))
        response, response_handler = self._call_and_read_response(
            method, args, body=body, expect_response_body=True)
        return (response, response_handler)

    def call_with_body_readv_array(self, args, body):
        response, response_handler = self._call_and_read_response(
            args[0], args[1:], readv_body=body, expect_response_body=True)
        return (response, response_handler)

    def call_with_body_stream(self, args, stream):
        response, response_handler = self._call_and_read_response(
            args[0], args[1:], body_stream=stream,
            expect_response_body=False)
        return (response, response_handler)

    def remote_path_from_transport(self, transport):
        """Convert transport into a path suitable for using in a request.

        Note that the resulting remote path doesn't encode the host name or
        anything but path, so it is only safe to use it in requests sent over
        the medium from the matching transport.
        """
        return self._medium.remote_path_from_transport(transport).encode('utf-8')


class _SmartClientRequest(object):
    """Encapsulate the logic for a single request.

    This class handles things like reconnecting and sending the request a
    second time when the connection is reset in the middle. It also handles the
    multiple requests that get made if we don't know what protocol the server
    supports yet.

    Generally, you build up one of these objects, passing in the arguments that
    you want to send to the server, and then use 'call_and_read_response' to
    get the response from the server.
    """

    def __init__(self, client, method, args, body=None, readv_body=None,
                 body_stream=None, expect_response_body=True):
        self.client = client
        self.method = method
        self.args = args
        self.body = body
        self.readv_body = readv_body
        self.body_stream = body_stream
        self.expect_response_body = expect_response_body

    def call_and_read_response(self):
        """Send the request to the server, and read the initial response.

        This doesn't read all of the body content of the response, instead it
        returns (response_tuple, response_handler). response_tuple is the 'ok',
        or 'error' information, and 'response_handler' can be used to get the
        content stream out.
        """
        self._run_call_hooks()
        protocol_version = self.client._medium._protocol_version
        if protocol_version is None:
            return self._call_determining_protocol_version()
        else:
            return self._call(protocol_version)

    def _is_safe_to_send_twice(self):
        """Check if the current method is re-entrant safe."""
        if self.body_stream is not None or 'noretry' in debug.debug_flags:
            # We can't restart a body stream that has already been consumed.
            return False
        request_type = _mod_request.request_handlers.get_info(self.method)
        if request_type in ('read', 'idem', 'semi'):
            return True
        # If we have gotten this far, 'stream' cannot be retried, because we
        # already consumed the local stream.
        if request_type in ('semivfs', 'mutate', 'stream'):
            return False
        trace.mutter('Unknown request type: %s for method %s'
                     % (request_type, self.method))
        return False

    def _run_call_hooks(self):
        if not _SmartClient.hooks['call']:
            return
        params = CallHookParams(self.method, self.args, self.body,
                                self.readv_body, self.client._medium)
        for hook in _SmartClient.hooks['call']:
            hook(params)

    def _call(self, protocol_version):
        """We know the protocol version.

        So this just sends the request, and then reads the response. This is
        where the code will be to retry requests if the connection is closed.
        """
        response_handler = self._send(protocol_version)
        try:
            response_tuple = response_handler.read_response_tuple(
                expect_body=self.expect_response_body)
        except errors.ConnectionReset as e:
            self.client._medium.reset()
            if not self._is_safe_to_send_twice():
                raise
            trace.warning('ConnectionReset reading response for %r, retrying'
                          % (self.method,))
            trace.log_exception_quietly()
            encoder, response_handler = self._construct_protocol(
                protocol_version)
            self._send_no_retry(encoder)
            response_tuple = response_handler.read_response_tuple(
                expect_body=self.expect_response_body)
        return (response_tuple, response_handler)

    def _call_determining_protocol_version(self):
        """Determine what protocol the remote server supports.

        We do this by placing a request in the most recent protocol, and
        handling the UnexpectedProtocolVersionMarker from the server.
        """
        last_err = None
        for protocol_version in [3, 2]:
            if protocol_version == 2:
                # If v3 doesn't work, the remote side is older than 1.6.
                self.client._medium._remember_remote_is_before((1, 6))
            try:
                response_tuple, response_handler = self._call(protocol_version)
            except errors.UnexpectedProtocolVersionMarker as err:
                # TODO: We could recover from this without disconnecting if
                # we recognise the protocol version.
                trace.warning(
                    'Server does not understand Bazaar network protocol %d,'
                    ' reconnecting.  (Upgrade the server to avoid this.)'
                    % (protocol_version,))
                self.client._medium.disconnect()
                last_err = err
                continue
            except errors.ErrorFromSmartServer:
                # If we received an error reply from the server, then it
                # must be ok with this protocol version.
                self.client._medium._protocol_version = protocol_version
                raise
            else:
                self.client._medium._protocol_version = protocol_version
                return response_tuple, response_handler
        raise errors.SmartProtocolError(
            'Server is not a Bazaar server: ' + str(last_err))

    def _construct_protocol(self, version):
        """Build the encoding stack for a given protocol version."""
        request = self.client._medium.get_request()
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

    def _send(self, protocol_version):
        """Encode the request, and send it to the server.

        This will retry a request if we get a ConnectionReset while sending the
        request to the server. (Unless we have a body_stream that we have
        already started consuming, since we can't restart body_streams)

        :return: response_handler as defined by _construct_protocol
        """
        encoder, response_handler = self._construct_protocol(protocol_version)
        try:
            self._send_no_retry(encoder)
        except errors.ConnectionReset as e:
            # If we fail during the _send_no_retry phase, then we can
            # be confident that the server did not get our request, because we
            # haven't started waiting for the reply yet. So try the request
            # again. We only issue a single retry, because if the connection
            # really is down, there is no reason to loop endlessly.

            # Connection is dead, so close our end of it.
            self.client._medium.reset()
            if (('noretry' in debug.debug_flags) or
                (self.body_stream is not None and
                    encoder.body_stream_started)):
                # We can't restart a body_stream that has been partially
                # consumed, so we don't retry.
                # Note: We don't have to worry about
                #   SmartClientRequestProtocolOne or Two, because they don't
                #   support client-side body streams.
                raise
            trace.warning('ConnectionReset calling %r, retrying'
                          % (self.method,))
            trace.log_exception_quietly()
            encoder, response_handler = self._construct_protocol(
                protocol_version)
            self._send_no_retry(encoder)
        return response_handler

    def _send_no_retry(self, encoder):
        """Just encode the request and try to send it."""
        encoder.set_headers(self.client._headers)
        if self.body is not None:
            if self.readv_body is not None:
                raise AssertionError(
                    "body and readv_body are mutually exclusive.")
            if self.body_stream is not None:
                raise AssertionError(
                    "body and body_stream are mutually exclusive.")
            encoder.call_with_body_bytes(
                (self.method, ) + self.args, self.body)
        elif self.readv_body is not None:
            if self.body_stream is not None:
                raise AssertionError(
                    "readv_body and body_stream are mutually exclusive.")
            encoder.call_with_body_readv_array((self.method, ) + self.args,
                                               self.readv_body)
        elif self.body_stream is not None:
            encoder.call_with_body_stream((self.method, ) + self.args,
                                          self.body_stream)
        else:
            encoder.call(self.method, *self.args)


class SmartClientHooks(hooks.Hooks):

    def __init__(self):
        hooks.Hooks.__init__(
            self, "breezy.bzr.smart.client", "_SmartClient.hooks")
        self.add_hook('call',
                      "Called when the smart client is submitting a request to the "
                      "smart server. Called with a breezy.bzr.smart.client.CallHookParams "
                      "object. Streaming request bodies, and responses, are not "
                      "accessible.", None)


_SmartClient.hooks = SmartClientHooks()


class CallHookParams(object):

    def __init__(self, method, args, body, readv_body, medium):
        self.method = method
        self.args = args
        self.body = body
        self.readv_body = readv_body
        self.medium = medium

    def __repr__(self):
        attrs = dict((k, v) for k, v in self.__dict__.items()
                     if v is not None)
        return '<%s %r>' % (self.__class__.__name__, attrs)

    def __eq__(self, other):
        if not isinstance(other, type(self)):
            return NotImplemented
        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        return not self == other
