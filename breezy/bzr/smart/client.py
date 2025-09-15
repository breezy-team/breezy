"""Smart client for Breezy smart server protocol."""
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

import breezy

from ... import debug, errors, hooks, trace
from . import message, protocol


class _SmartClient:
    """Smart client for communicating with a Bazaar smart server.

    This class provides the low-level interface for making RPC calls to a
    Bazaar smart server. It handles protocol negotiation, request encoding,
    and response decoding.

    The client supports multiple protocol versions and will automatically
    negotiate the best version supported by both client and server.

    Attributes:
        _medium: The SmartClientMedium used for communication.
        _headers: Dictionary of headers to send with each request.
    """

    def __init__(self, medium, headers=None):
        """Constructor.

        :param medium: a SmartClientMedium
        """
        self._medium = medium
        if headers is None:
            self._headers = {b"Software version": breezy.__version__.encode("utf-8")}
        else:
            self._headers = dict(headers)

    def __repr__(self):
        """Return a string representation of the SmartClient.

        Returns:
            String representation showing the class name and medium.
        """
        return f"{self.__class__.__name__}({self._medium!r})"

    def _call_and_read_response(
        self,
        method,
        args,
        body=None,
        readv_body=None,
        body_stream=None,
        expect_response_body=True,
    ):
        """Internal method to send a request and read the response.

        This creates a _SmartClientRequest object to handle the actual
        communication, including retries and protocol version negotiation.

        Args:
            method: The remote method name to call (byte string).
            args: Tuple of arguments for the method (byte strings).
            body: Optional body bytes to send with the request.
            readv_body: Optional readv array for the request body.
            body_stream: Optional stream object for the request body.
            expect_response_body: Whether to expect a response body.

        Returns:
            Tuple of (response_tuple, response_handler) where response_tuple
            contains the response status and arguments, and response_handler
            can be used to read the response body if present.
        """
        request = _SmartClientRequest(
            self,
            method,
            args,
            body=body,
            readv_body=readv_body,
            body_stream=body_stream,
            expect_response_body=expect_response_body,
        )
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
        return self._call_and_read_response(method, args, expect_response_body=True)

    def call_with_body_bytes(self, method, args, body):
        """Call a method on the remote server with body bytes."""
        if not isinstance(method, bytes):
            raise TypeError(f"method must be a byte string, not {method!r}")
        for arg in args:
            if not isinstance(arg, bytes):
                raise TypeError(f"args must be byte strings, not {args!r}")
        if not isinstance(body, bytes):
            raise TypeError(f"body must be byte string, not {body!r}")
        response, _response_handler = self._call_and_read_response(
            method, args, body=body, expect_response_body=False
        )
        return response

    def call_with_body_bytes_expecting_body(self, method, args, body):
        """Call a method on the remote server with body bytes."""
        if not isinstance(method, bytes):
            raise TypeError(f"method must be a byte string, not {method!r}")
        for arg in args:
            if not isinstance(arg, bytes):
                raise TypeError(f"args must be byte strings, not {args!r}")
        if not isinstance(body, bytes):
            raise TypeError(f"body must be byte string, not {body!r}")
        response, response_handler = self._call_and_read_response(
            method, args, body=body, expect_response_body=True
        )
        return (response, response_handler)

    def call_with_body_readv_array(self, args, body):
        """Call a method with a readv array body.

        This is used for requests that need to send multiple byte ranges
        as the request body, typically for optimized bulk data transfers.

        Args:
            args: Tuple where first element is the method name and remaining
                elements are method arguments (all byte strings).
            body: A readv array specifying byte ranges to send.

        Returns:
            Tuple of (response, response_handler) where response contains
            the response status and arguments, and response_handler can be
            used to read the response body.
        """
        response, response_handler = self._call_and_read_response(
            args[0], args[1:], readv_body=body, expect_response_body=True
        )
        return (response, response_handler)

    def call_with_body_stream(self, args, stream):
        """Call a method with a streaming body.

        This is used for requests that need to send large amounts of data
        without loading it all into memory at once.

        Args:
            args: Tuple where first element is the method name and remaining
                elements are method arguments (all byte strings).
            stream: A file-like object to stream as the request body.

        Returns:
            Tuple of (response, response_handler) where response contains
            the response status and arguments.

        Note:
            Streaming requests cannot be retried if the connection fails
            after streaming has begun.
        """
        response, response_handler = self._call_and_read_response(
            args[0], args[1:], body_stream=stream, expect_response_body=False
        )
        return (response, response_handler)

    def remote_path_from_transport(self, transport):
        """Convert transport into a path suitable for using in a request.

        Note that the resulting remote path doesn't encode the host name or
        anything but path, so it is only safe to use it in requests sent over
        the medium from the matching transport.
        """
        return self._medium.remote_path_from_transport(transport).encode("utf-8")


class _SmartClientRequest:
    """Encapsulate the logic for a single request.

    This class handles things like reconnecting and sending the request a
    second time when the connection is reset in the middle. It also handles the
    multiple requests that get made if we don't know what protocol the server
    supports yet.

    Generally, you build up one of these objects, passing in the arguments that
    you want to send to the server, and then use 'call_and_read_response' to
    get the response from the server.
    """

    def __init__(
        self,
        client,
        method,
        args,
        body=None,
        readv_body=None,
        body_stream=None,
        expect_response_body=True,
    ):
        """Initialize a SmartClientRequest.

        Args:
            client: The _SmartClient that owns this request.
            method: The remote method name to call (byte string).
            args: Tuple of arguments for the method (byte strings).
            body: Optional body bytes to send with the request.
            readv_body: Optional readv array for the request body.
            body_stream: Optional stream object for the request body.
            expect_response_body: Whether to expect a response body.
        """
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
        if self.body_stream is not None or debug.debug_flag_enabled("noretry"):
            # We can't restart a body stream that has already been consumed.
            return False
        from breezy.bzr.smart import request as _mod_request

        request_type = _mod_request.request_handlers.get_info(self.method)
        if request_type in ("read", "idem", "semi"):
            return True
        # If we have gotten this far, 'stream' cannot be retried, because we
        # already consumed the local stream.
        if request_type in ("semivfs", "mutate", "stream"):
            return False
        trace.mutter(f"Unknown request type: {request_type} for method {self.method}")
        return False

    def _run_call_hooks(self):
        """Run any registered call hooks.

        This method executes all hooks registered for 'call' events,
        passing them information about the current request.
        """
        if not _SmartClient.hooks["call"]:
            return
        params = CallHookParams(
            self.method, self.args, self.body, self.readv_body, self.client._medium
        )
        for hook in _SmartClient.hooks["call"]:
            hook(params)

    def _call(self, protocol_version):
        """We know the protocol version.

        So this just sends the request, and then reads the response. This is
        where the code will be to retry requests if the connection is closed.
        """
        response_handler = self._send(protocol_version)
        try:
            response_tuple = response_handler.read_response_tuple(
                expect_body=self.expect_response_body
            )
        except ConnectionResetError:
            self.client._medium.reset()
            if not self._is_safe_to_send_twice():
                raise
            trace.warning(
                f"ConnectionReset reading response for {self.method!r}, retrying"
            )
            trace.log_exception_quietly()
            encoder, response_handler = self._construct_protocol(protocol_version)
            self._send_no_retry(encoder)
            response_tuple = response_handler.read_response_tuple(
                expect_body=self.expect_response_body
            )
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
                    "Server does not understand Bazaar network protocol %d,"
                    " reconnecting.  (Upgrade the server to avoid this.)"
                    % (protocol_version,)
                )
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
            "Server is not a Bazaar server: " + str(last_err)
        )

    def _construct_protocol(self, version):
        """Build the encoding stack for a given protocol version."""
        request = self.client._medium.get_request()
        if version == 3:
            request_encoder = protocol.ProtocolThreeRequester(request)
            response_handler = message.ConventionalResponseHandler()
            response_proto = protocol.ProtocolThreeDecoder(
                response_handler, expect_version_marker=True
            )
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
        except ConnectionResetError:
            # If we fail during the _send_no_retry phase, then we can
            # be confident that the server did not get our request, because we
            # haven't started waiting for the reply yet. So try the request
            # again. We only issue a single retry, because if the connection
            # really is down, there is no reason to loop endlessly.

            # Connection is dead, so close our end of it.
            self.client._medium.reset()
            if (debug.debug_flag_enabled("noretry")) or (
                self.body_stream is not None and encoder.body_stream_started
            ):
                # We can't restart a body_stream that has been partially
                # consumed, so we don't retry.
                # Note: We don't have to worry about
                #   SmartClientRequestProtocolOne or Two, because they don't
                #   support client-side body streams.
                raise
            trace.warning(f"ConnectionReset calling {self.method!r}, retrying")
            trace.log_exception_quietly()
            encoder, response_handler = self._construct_protocol(protocol_version)
            self._send_no_retry(encoder)
        return response_handler

    def _send_no_retry(self, encoder):
        """Just encode the request and try to send it."""
        encoder.set_headers(self.client._headers)
        if self.body is not None:
            if self.readv_body is not None:
                raise AssertionError("body and readv_body are mutually exclusive.")
            if self.body_stream is not None:
                raise AssertionError("body and body_stream are mutually exclusive.")
            encoder.call_with_body_bytes((self.method,) + self.args, self.body)
        elif self.readv_body is not None:
            if self.body_stream is not None:
                raise AssertionError(
                    "readv_body and body_stream are mutually exclusive."
                )
            encoder.call_with_body_readv_array(
                (self.method,) + self.args, self.readv_body
            )
        elif self.body_stream is not None:
            encoder.call_with_body_stream((self.method,) + self.args, self.body_stream)
        else:
            encoder.call(self.method, *self.args)


class SmartClientHooks(hooks.Hooks):
    """Hook management for smart client operations.

    This class defines the hooks available for smart client operations,
    allowing extensions to monitor or modify client behavior.
    """

    def __init__(self):
        """Initialize the SmartClientHooks.

        Registers the available hook points for smart client operations.
        """
        hooks.Hooks.__init__(self, "breezy.bzr.smart.client", "_SmartClient.hooks")
        self.add_hook(
            "call",
            "Called when the smart client is submitting a request to the "
            "smart server. Called with a breezy.bzr.smart.client.CallHookParams "
            "object. Streaming request bodies, and responses, are not "
            "accessible.",
            None,
        )


_SmartClient.hooks = SmartClientHooks()  # type: ignore


class CallHookParams:
    """Parameters passed to smart client call hooks.

    This class encapsulates all the information about a smart client
    request that is passed to registered hooks. Hooks can inspect but
    not modify these parameters.

    Attributes:
        method: The method name being called (byte string).
        args: Tuple of arguments for the method (byte strings).
        body: Optional request body bytes.
        readv_body: Optional readv array for the request.
        medium: The SmartClientMedium being used.
    """

    def __init__(self, method, args, body, readv_body, medium):
        """Initialize CallHookParams.

        Args:
            method: The method name being called (byte string).
            args: Tuple of arguments for the method (byte strings).
            body: Optional request body bytes.
            readv_body: Optional readv array for the request.
            medium: The SmartClientMedium being used.
        """
        self.method = method
        self.args = args
        self.body = body
        self.readv_body = readv_body
        self.medium = medium

    def __repr__(self):
        """Return a string representation of the CallHookParams.

        Returns:
            String representation showing non-None attributes.
        """
        attrs = {k: v for k, v in self.__dict__.items() if v is not None}
        return f"<{self.__class__.__name__} {attrs!r}>"

    def __eq__(self, other):
        """Check equality with another CallHookParams instance.

        Args:
            other: Object to compare with.

        Returns:
            True if both objects have the same attributes, False otherwise.
            NotImplemented if other is not a CallHookParams instance.
        """
        if not isinstance(other, type(self)):
            return NotImplemented
        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        """Check inequality with another CallHookParams instance.

        Args:
            other: Object to compare with.

        Returns:
            True if objects are not equal, False if they are equal.
        """
        return not self == other
