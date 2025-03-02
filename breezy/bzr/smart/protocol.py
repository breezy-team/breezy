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

"""Wire-level encoding and decoding of requests and responses for the smart
client and server.
"""

import _thread
import struct
import sys
from collections import deque
from io import BytesIO

from fastbencode import bdecode_as_tuple, bencode

import breezy

from ... import debug, errors, osutils
from ...trace import log_exception_quietly, mutter
from . import message, request

# Protocol version strings.  These are sent as prefixes of bzr requests and
# responses to identify the protocol version being used. (There are no version
# one strings because that version doesn't send any).
REQUEST_VERSION_TWO = b"bzr request 2\n"
RESPONSE_VERSION_TWO = b"bzr response 2\n"

MESSAGE_VERSION_THREE = b"bzr message 3 (bzr 1.6)\n"
RESPONSE_VERSION_THREE = REQUEST_VERSION_THREE = MESSAGE_VERSION_THREE


class SmartMessageHandlerError(errors.InternalBzrError):
    _fmt = "The message handler raised an exception:\n%(traceback_text)s"

    def __init__(self, exc_info):
        import traceback

        # GZ 2010-08-10: Cycle with exc_tb/exc_info affects at least one test
        self.exc_type, self.exc_value, self.exc_tb = exc_info
        self.exc_info = exc_info
        traceback_strings = traceback.format_exception(
            self.exc_type, self.exc_value, self.exc_tb
        )
        self.traceback_text = "".join(traceback_strings)


def _recv_tuple(from_file):
    req_line = from_file.readline()
    return _decode_tuple(req_line)


def _decode_tuple(req_line):
    if req_line is None or req_line == b"":
        return None
    if not req_line.endswith(b"\n"):
        raise errors.SmartProtocolError("request {!r} not terminated".format(req_line))
    return tuple(req_line[:-1].split(b"\x01"))


def _encode_tuple(args):
    """Encode the tuple args to a bytestream."""
    for arg in args:
        if isinstance(arg, str):
            raise TypeError(args)
    return b"\x01".join(args) + b"\n"


class Requester:
    """Abstract base class for an object that can issue requests on a smart
    medium.
    """

    def call(self, *args):
        """Make a remote call.

        :param args: the arguments of this call.
        """
        raise NotImplementedError(self.call)

    def call_with_body_bytes(self, args, body):
        """Make a remote call with a body.

        :param args: the arguments of this call.
        :type body: str
        :param body: the body to send with the request.
        """
        raise NotImplementedError(self.call_with_body_bytes)

    def call_with_body_readv_array(self, args, body):
        """Make a remote call with a readv array.

        :param args: the arguments of this call.
        :type body: iterable of (start, length) tuples.
        :param body: the readv ranges to send with this request.
        """
        raise NotImplementedError(self.call_with_body_readv_array)

    def set_headers(self, headers):
        raise NotImplementedError(self.set_headers)


class SmartProtocolBase:
    """Methods common to client and server."""

    # TODO: this only actually accomodates a single block; possibly should
    # support multiple chunks?
    def _encode_bulk_data(self, body):
        """Encode body as a bulk data chunk."""
        return b"".join((b"%d\n" % len(body), body, b"done\n"))

    def _serialise_offsets(self, offsets):
        """Serialise a readv offset list."""
        txt = []
        for start, length in offsets:
            txt.append(b"%d,%d" % (start, length))
        return b"\n".join(txt)


class SmartServerRequestProtocolOne(SmartProtocolBase):
    """Server-side encoding and decoding logic for smart version 1."""

    def __init__(
        self, backing_transport, write_func, root_client_path="/", jail_root=None
    ):
        self._backing_transport = backing_transport
        self._root_client_path = root_client_path
        self._jail_root = jail_root
        self.unused_data = b""
        self._finished = False
        self.in_buffer = b""
        self._has_dispatched = False
        self.request = None
        self._body_decoder = None
        self._write_func = write_func

    def accept_bytes(self, data):
        """Take bytes, and advance the internal state machine appropriately.

        :param data: must be a byte string
        """
        if not isinstance(data, bytes):
            raise ValueError(data)
        self.in_buffer += data
        if not self._has_dispatched:
            if b"\n" not in self.in_buffer:
                # no command line yet
                return
            self._has_dispatched = True
            try:
                first_line, self.in_buffer = self.in_buffer.split(b"\n", 1)
                first_line += b"\n"
                req_args = _decode_tuple(first_line)
                self.request = request.SmartServerRequestHandler(
                    self._backing_transport,
                    commands=request.request_handlers,
                    root_client_path=self._root_client_path,
                    jail_root=self._jail_root,
                )
                self.request.args_received(req_args)
                if self.request.finished_reading:
                    # trivial request
                    self.unused_data = self.in_buffer
                    self.in_buffer = b""
                    self._send_response(self.request.response)
            except KeyboardInterrupt:
                raise
            except errors.UnknownSmartMethod as err:
                protocol_error = errors.SmartProtocolError(
                    "bad request '{}'".format(err.verb.decode("ascii"))
                )
                failure = request.FailedSmartServerResponse(
                    (b"error", str(protocol_error).encode("utf-8"))
                )
                self._send_response(failure)
                return
            except Exception as exception:
                # everything else: pass to client, flush, and quit
                log_exception_quietly()
                self._send_response(
                    request.FailedSmartServerResponse(
                        (b"error", str(exception).encode("utf-8"))
                    )
                )
                return

        if self._has_dispatched:
            if self._finished:
                # nothing to do.XXX: this routine should be a single state
                # machine too.
                self.unused_data += self.in_buffer
                self.in_buffer = b""
                return
            if self._body_decoder is None:
                self._body_decoder = LengthPrefixedBodyDecoder()
            self._body_decoder.accept_bytes(self.in_buffer)
            self.in_buffer = self._body_decoder.unused_data
            body_data = self._body_decoder.read_pending_data()
            self.request.accept_body(body_data)
            if self._body_decoder.finished_reading:
                self.request.end_of_body()
                if not self.request.finished_reading:
                    raise AssertionError("no more body, request not finished")
            if self.request.response is not None:
                self._send_response(self.request.response)
                self.unused_data = self.in_buffer
                self.in_buffer = b""
            else:
                if self.request.finished_reading:
                    raise AssertionError("no response and we have finished reading.")

    def _send_response(self, response):
        """Send a smart server response down the output stream."""
        if self._finished:
            raise AssertionError("response already sent")
        args = response.args
        body = response.body
        self._finished = True
        self._write_protocol_version()
        self._write_success_or_failure_prefix(response)
        self._write_func(_encode_tuple(args))
        if body is not None:
            if not isinstance(body, bytes):
                raise ValueError(body)
            data = self._encode_bulk_data(body)
            self._write_func(data)

    def _write_protocol_version(self):
        """Write any prefixes this protocol requires.

        Version one doesn't send protocol versions.
        """

    def _write_success_or_failure_prefix(self, response):
        """Write the protocol specific success/failure prefix.

        For SmartServerRequestProtocolOne this is omitted but we
        call is_successful to ensure that the response is valid.
        """
        response.is_successful()

    def next_read_size(self):
        if self._finished:
            return 0
        if self._body_decoder is None:
            return 1
        else:
            return self._body_decoder.next_read_size()


class SmartServerRequestProtocolTwo(SmartServerRequestProtocolOne):
    r"""Version two of the server side of the smart protocol.

    This prefixes responses with the value of RESPONSE_VERSION_TWO.
    """

    response_marker = RESPONSE_VERSION_TWO
    request_marker = REQUEST_VERSION_TWO

    def _write_success_or_failure_prefix(self, response):
        """Write the protocol specific success/failure prefix."""
        if response.is_successful():
            self._write_func(b"success\n")
        else:
            self._write_func(b"failed\n")

    def _write_protocol_version(self):
        r"""Write any prefixes this protocol requires.

        Version two sends the value of RESPONSE_VERSION_TWO.
        """
        self._write_func(self.response_marker)

    def _send_response(self, response):
        """Send a smart server response down the output stream."""
        if self._finished:
            raise AssertionError("response already sent")
        self._finished = True
        self._write_protocol_version()
        self._write_success_or_failure_prefix(response)
        self._write_func(_encode_tuple(response.args))
        if response.body is not None:
            if not isinstance(response.body, bytes):
                raise AssertionError("body must be bytes")
            if response.body_stream is not None:
                raise AssertionError("body_stream and body cannot both be set")
            data = self._encode_bulk_data(response.body)
            self._write_func(data)
        elif response.body_stream is not None:
            _send_stream(response.body_stream, self._write_func)


def _send_stream(stream, write_func):
    write_func(b"chunked\n")
    _send_chunks(stream, write_func)
    write_func(b"END\n")


def _send_chunks(stream, write_func):
    for chunk in stream:
        if isinstance(chunk, bytes):
            data = ("{:x}\n".format(len(chunk))).encode("ascii") + chunk
            write_func(data)
        elif isinstance(chunk, request.FailedSmartServerResponse):
            write_func(b"ERR\n")
            _send_chunks(chunk.args, write_func)
            return
        else:
            raise errors.BzrError(
                "Chunks must be str or FailedSmartServerResponse, got {!r}".format(chunk)
            )


class _NeedMoreBytes(Exception):
    """Raise this inside a _StatefulDecoder to stop decoding until more bytes
    have been received.
    """

    def __init__(self, count=None):
        """Constructor.

        :param count: the total number of bytes needed by the current state.
            May be None if the number of bytes needed is unknown.
        """
        self.count = count


class _StatefulDecoder:
    """Base class for writing state machines to decode byte streams.

    Subclasses should provide a self.state_accept attribute that accepts bytes
    and, if appropriate, updates self.state_accept to a different function.
    accept_bytes will call state_accept as often as necessary to make sure the
    state machine has progressed as far as possible before it returns.

    See ProtocolThreeDecoder for an example subclass.
    """

    def __init__(self):
        self.finished_reading = False
        self._in_buffer_list = []
        self._in_buffer_len = 0
        self.unused_data = b""
        self.bytes_left = None
        self._number_needed_bytes = None

    def _get_in_buffer(self):
        if len(self._in_buffer_list) == 1:
            return self._in_buffer_list[0]
        in_buffer = b"".join(self._in_buffer_list)
        if len(in_buffer) != self._in_buffer_len:
            raise AssertionError(
                "Length of buffer did not match expected value: {} != {}".format(*self._in_buffer_len),
                len(in_buffer),
            )
        self._in_buffer_list = [in_buffer]
        return in_buffer

    def _get_in_bytes(self, count):
        """Grab X bytes from the input_buffer.

        Callers should have already checked that self._in_buffer_len is >
        count. Note, this does not consume the bytes from the buffer. The
        caller will still need to call _get_in_buffer() and then
        _set_in_buffer() if they actually need to consume the bytes.
        """
        # check if we can yield the bytes from just the first entry in our list
        if len(self._in_buffer_list) == 0:
            raise AssertionError(
                "Callers must be sure we have buffered bytes"
                " before calling _get_in_bytes"
            )
        if len(self._in_buffer_list[0]) > count:
            return self._in_buffer_list[0][:count]
        # We can't yield it from the first buffer, so collapse all buffers, and
        # yield it from that
        in_buf = self._get_in_buffer()
        return in_buf[:count]

    def _set_in_buffer(self, new_buf):
        if new_buf is not None:
            if not isinstance(new_buf, bytes):
                raise TypeError(new_buf)
            self._in_buffer_list = [new_buf]
            self._in_buffer_len = len(new_buf)
        else:
            self._in_buffer_list = []
            self._in_buffer_len = 0

    def accept_bytes(self, new_buf):
        """Decode as much of bytes as possible.

        If 'new_buf' contains too much data it will be appended to
        self.unused_data.

        finished_reading will be set when no more data is required.  Further
        data will be appended to self.unused_data.
        """
        if not isinstance(new_buf, bytes):
            raise TypeError(new_buf)
        # accept_bytes is allowed to change the state
        self._number_needed_bytes = None
        # lsprof puts a very large amount of time on this specific call for
        # large readv arrays
        self._in_buffer_list.append(new_buf)
        self._in_buffer_len += len(new_buf)
        try:
            # Run the function for the current state.
            current_state = self.state_accept
            self.state_accept()
            while current_state != self.state_accept:
                # The current state has changed.  Run the function for the new
                # current state, so that it can:
                #   - decode any unconsumed bytes left in a buffer, and
                #   - signal how many more bytes are expected (via raising
                #     _NeedMoreBytes).
                current_state = self.state_accept
                self.state_accept()
        except _NeedMoreBytes as e:
            self._number_needed_bytes = e.count


class ChunkedBodyDecoder(_StatefulDecoder):
    """Decoder for chunked body data.

    This is very similar the HTTP's chunked encoding.  See the description of
    streamed body data in `doc/developers/network-protocol.txt` for details.
    """

    def __init__(self):
        _StatefulDecoder.__init__(self)
        self.state_accept = self._state_accept_expecting_header
        self.chunk_in_progress = None
        self.chunks = deque()
        self.error = False
        self.error_in_progress = None

    def next_read_size(self):
        # Note: the shortest possible chunk is 2 bytes: '0\n', and the
        # end-of-body marker is 4 bytes: 'END\n'.
        if self.state_accept == self._state_accept_reading_chunk:
            # We're expecting more chunk content.  So we're expecting at least
            # the rest of this chunk plus an END chunk.
            return self.bytes_left + 4
        elif self.state_accept == self._state_accept_expecting_length:
            if self._in_buffer_len == 0:
                # We're expecting a chunk length.  There's at least two bytes
                # left: a digit plus '\n'.
                return 2
            else:
                # We're in the middle of reading a chunk length.  So there's at
                # least one byte left, the '\n' that terminates the length.
                return 1
        elif self.state_accept == self._state_accept_reading_unused:
            return 1
        elif self.state_accept == self._state_accept_expecting_header:
            return max(0, len("chunked\n") - self._in_buffer_len)
        else:
            raise AssertionError("Impossible state: {!r}".format(self.state_accept))

    def read_next_chunk(self):
        try:
            return self.chunks.popleft()
        except IndexError:
            return None

    def _extract_line(self):
        in_buf = self._get_in_buffer()
        pos = in_buf.find(b"\n")
        if pos == -1:
            # We haven't read a complete line yet, so request more bytes before
            # we continue.
            raise _NeedMoreBytes(1)
        line = in_buf[:pos]
        # Trim the prefix (including '\n' delimiter) from the _in_buffer.
        self._set_in_buffer(in_buf[pos + 1 :])
        return line

    def _finished(self):
        self.unused_data = self._get_in_buffer()
        self._in_buffer_list = []
        self._in_buffer_len = 0
        self.state_accept = self._state_accept_reading_unused
        if self.error:
            error_args = tuple(self.error_in_progress)
            self.chunks.append(request.FailedSmartServerResponse(error_args))
            self.error_in_progress = None
        self.finished_reading = True

    def _state_accept_expecting_header(self):
        prefix = self._extract_line()
        if prefix == b"chunked":
            self.state_accept = self._state_accept_expecting_length
        else:
            raise errors.SmartProtocolError(
                'Bad chunked body header: "{}"'.format(prefix)
            )

    def _state_accept_expecting_length(self):
        prefix = self._extract_line()
        if prefix == b"ERR":
            self.error = True
            self.error_in_progress = []
            self._state_accept_expecting_length()
            return
        elif prefix == b"END":
            # We've read the end-of-body marker.
            # Any further bytes are unused data, including the bytes left in
            # the _in_buffer.
            self._finished()
            return
        else:
            self.bytes_left = int(prefix, 16)
            self.chunk_in_progress = b""
            self.state_accept = self._state_accept_reading_chunk

    def _state_accept_reading_chunk(self):
        in_buf = self._get_in_buffer()
        in_buffer_len = len(in_buf)
        self.chunk_in_progress += in_buf[: self.bytes_left]
        self._set_in_buffer(in_buf[self.bytes_left :])
        self.bytes_left -= in_buffer_len
        if self.bytes_left <= 0:
            # Finished with chunk
            self.bytes_left = None
            if self.error:
                self.error_in_progress.append(self.chunk_in_progress)
            else:
                self.chunks.append(self.chunk_in_progress)
            self.chunk_in_progress = None
            self.state_accept = self._state_accept_expecting_length

    def _state_accept_reading_unused(self):
        self.unused_data += self._get_in_buffer()
        self._in_buffer_list = []


class LengthPrefixedBodyDecoder(_StatefulDecoder):
    """Decodes the length-prefixed bulk data."""

    def __init__(self):
        _StatefulDecoder.__init__(self)
        self.state_accept = self._state_accept_expecting_length
        self.state_read = self._state_read_no_data
        self._body = b""
        self._trailer_buffer = b""

    def next_read_size(self):
        if self.bytes_left is not None:
            # Ideally we want to read all the remainder of the body and the
            # trailer in one go.
            return self.bytes_left + 5
        elif self.state_accept == self._state_accept_reading_trailer:
            # Just the trailer left
            return 5 - len(self._trailer_buffer)
        elif self.state_accept == self._state_accept_expecting_length:
            # There's still at least 6 bytes left ('\n' to end the length, plus
            # 'done\n').
            return 6
        else:
            # Reading excess data.  Either way, 1 byte at a time is fine.
            return 1

    def read_pending_data(self):
        """Return any pending data that has been decoded."""
        return self.state_read()

    def _state_accept_expecting_length(self):
        in_buf = self._get_in_buffer()
        pos = in_buf.find(b"\n")
        if pos == -1:
            return
        self.bytes_left = int(in_buf[:pos])
        self._set_in_buffer(in_buf[pos + 1 :])
        self.state_accept = self._state_accept_reading_body
        self.state_read = self._state_read_body_buffer

    def _state_accept_reading_body(self):
        in_buf = self._get_in_buffer()
        self._body += in_buf
        self.bytes_left -= len(in_buf)
        self._set_in_buffer(None)
        if self.bytes_left <= 0:
            # Finished with body
            if self.bytes_left != 0:
                self._trailer_buffer = self._body[self.bytes_left :]
                self._body = self._body[: self.bytes_left]
            self.bytes_left = None
            self.state_accept = self._state_accept_reading_trailer

    def _state_accept_reading_trailer(self):
        self._trailer_buffer += self._get_in_buffer()
        self._set_in_buffer(None)
        # TODO: what if the trailer does not match "done\n"?  Should this raise
        # a ProtocolViolation exception?
        if self._trailer_buffer.startswith(b"done\n"):
            self.unused_data = self._trailer_buffer[len(b"done\n") :]
            self.state_accept = self._state_accept_reading_unused
            self.finished_reading = True

    def _state_accept_reading_unused(self):
        self.unused_data += self._get_in_buffer()
        self._set_in_buffer(None)

    def _state_read_no_data(self):
        return b""

    def _state_read_body_buffer(self):
        result = self._body
        self._body = b""
        return result


class SmartClientRequestProtocolOne(
    SmartProtocolBase, Requester, message.ResponseHandler
):
    """The client-side protocol for smart version 1."""

    def __init__(self, request):
        """Construct a SmartClientRequestProtocolOne.

        :param request: A SmartClientMediumRequest to serialise onto and
            deserialise from.
        """
        self._request = request
        self._body_buffer = None
        self._request_start_time = None
        self._last_verb = None
        self._headers = None

    def set_headers(self, headers):
        self._headers = dict(headers)

    def call(self, *args):
        if "hpss" in debug.debug_flags:
            mutter("hpss call:   %s", repr(args)[1:-1])
            if getattr(self._request._medium, "base", None) is not None:
                mutter("             (to %s)", self._request._medium.base)
            self._request_start_time = osutils.perf_counter()
        self._write_args(args)
        self._request.finished_writing()
        self._last_verb = args[0]

    def call_with_body_bytes(self, args, body):
        """Make a remote call of args with body bytes 'body'.

        After calling this, call read_response_tuple to find the result out.
        """
        if "hpss" in debug.debug_flags:
            mutter("hpss call w/body: %s (%r...)", repr(args)[1:-1], body[:20])
            if getattr(self._request._medium, "_path", None) is not None:
                mutter("                  (to %s)", self._request._medium._path)
            mutter("              %d bytes", len(body))
            self._request_start_time = osutils.perf_counter()
            if "hpssdetail" in debug.debug_flags:
                mutter("hpss body content: %s", body)
        self._write_args(args)
        bytes = self._encode_bulk_data(body)
        self._request.accept_bytes(bytes)
        self._request.finished_writing()
        self._last_verb = args[0]

    def call_with_body_readv_array(self, args, body):
        r"""Make a remote call with a readv array.

        The body is encoded with one line per readv offset pair. The numbers in
        each pair are separated by a comma, and no trailing \\n is emitted.
        """
        if "hpss" in debug.debug_flags:
            mutter("hpss call w/readv: %s", repr(args)[1:-1])
            if getattr(self._request._medium, "_path", None) is not None:
                mutter("                  (to %s)", self._request._medium._path)
            self._request_start_time = osutils.perf_counter()
        self._write_args(args)
        readv_bytes = self._serialise_offsets(body)
        bytes = self._encode_bulk_data(readv_bytes)
        self._request.accept_bytes(bytes)
        self._request.finished_writing()
        if "hpss" in debug.debug_flags:
            mutter("              %d bytes in readv request", len(readv_bytes))
        self._last_verb = args[0]

    def call_with_body_stream(self, args, stream):
        # Protocols v1 and v2 don't support body streams.  So it's safe to
        # assume that a v1/v2 server doesn't support whatever method we're
        # trying to call with a body stream.
        self._request.finished_writing()
        self._request.finished_reading()
        raise errors.UnknownSmartMethod(args[0])

    def cancel_read_body(self):
        """After expecting a body, a response code may indicate one otherwise.

        This method lets the domain client inform the protocol that no body
        will be transmitted. This is a terminal method: after calling it the
        protocol is not able to be used further.
        """
        self._request.finished_reading()

    def _read_response_tuple(self):
        result = self._recv_tuple()
        if "hpss" in debug.debug_flags:
            if self._request_start_time is not None:
                mutter(
                    "   result:   %6.3fs  %s",
                    osutils.perf_counter() - self._request_start_time,
                    repr(result)[1:-1],
                )
                self._request_start_time = None
            else:
                mutter("   result:   %s", repr(result)[1:-1])
        return result

    def read_response_tuple(self, expect_body=False):
        """Read a response tuple from the wire.

        This should only be called once.
        """
        result = self._read_response_tuple()
        self._response_is_unknown_method(result)
        self._raise_args_if_error(result)
        if not expect_body:
            self._request.finished_reading()
        return result

    def _raise_args_if_error(self, result_tuple):
        # Later protocol versions have an explicit flag in the protocol to say
        # if an error response is "failed" or not.  In version 1 we don't have
        # that luxury.  So here is a complete list of errors that can be
        # returned in response to existing version 1 smart requests.  Responses
        # starting with these codes are always "failed" responses.
        v1_error_codes = [
            b"norepository",
            b"NoSuchFile",
            b"FileExists",
            b"DirectoryNotEmpty",
            b"ShortReadvError",
            b"UnicodeEncodeError",
            b"UnicodeDecodeError",
            b"ReadOnlyError",
            b"nobranch",
            b"NoSuchRevision",
            b"nosuchrevision",
            b"LockContention",
            b"UnlockableTransport",
            b"LockFailed",
            b"TokenMismatch",
            b"ReadError",
            b"PermissionDenied",
        ]
        if result_tuple[0] in v1_error_codes:
            self._request.finished_reading()
            raise errors.ErrorFromSmartServer(result_tuple)

    def _response_is_unknown_method(self, result_tuple):
        """Raise UnexpectedSmartServerResponse if the response is an 'unknonwn
        method' response to the request.

        :param response: The response from a smart client call_expecting_body
            call.
        :param verb: The verb used in that call.
        :raises: UnexpectedSmartServerResponse
        """
        if result_tuple == (
            b"error",
            b"Generic bzr smart protocol error: bad request '" + self._last_verb + b"'",
        ) or result_tuple == (
            b"error",
            b"Generic bzr smart protocol error: bad request u'%s'" % self._last_verb,
        ):
            # The response will have no body, so we've finished reading.
            self._request.finished_reading()
            raise errors.UnknownSmartMethod(self._last_verb)

    def read_body_bytes(self, count=-1):
        """Read bytes from the body, decoding into a byte stream.

        We read all bytes at once to ensure we've checked the trailer for
        errors, and then feed the buffer back as read_body_bytes is called.
        """
        if self._body_buffer is not None:
            return self._body_buffer.read(count)
        _body_decoder = LengthPrefixedBodyDecoder()

        while not _body_decoder.finished_reading:
            bytes = self._request.read_bytes(_body_decoder.next_read_size())
            if bytes == b"":
                # end of file encountered reading from server
                raise errors.ConnectionReset(
                    "Connection lost while reading response body."
                )
            _body_decoder.accept_bytes(bytes)
        self._request.finished_reading()
        self._body_buffer = BytesIO(_body_decoder.read_pending_data())
        # XXX: TODO check the trailer result.
        if "hpss" in debug.debug_flags:
            mutter(
                "              %d body bytes read", len(self._body_buffer.getvalue())
            )
        return self._body_buffer.read(count)

    def _recv_tuple(self):
        """Receive a tuple from the medium request."""
        return _decode_tuple(self._request.read_line())

    def query_version(self):
        """Return protocol version number of the server."""
        self.call(b"hello")
        resp = self.read_response_tuple()
        if resp == (b"ok", b"1"):
            return 1
        elif resp == (b"ok", b"2"):
            return 2
        else:
            raise errors.SmartProtocolError("bad response {!r}".format(resp))

    def _write_args(self, args):
        self._write_protocol_version()
        bytes = _encode_tuple(args)
        self._request.accept_bytes(bytes)

    def _write_protocol_version(self):
        """Write any prefixes this protocol requires.

        Version one doesn't send protocol versions.
        """


class SmartClientRequestProtocolTwo(SmartClientRequestProtocolOne):
    """Version two of the client side of the smart protocol.

    This prefixes the request with the value of REQUEST_VERSION_TWO.
    """

    response_marker = RESPONSE_VERSION_TWO
    request_marker = REQUEST_VERSION_TWO

    def read_response_tuple(self, expect_body=False):
        """Read a response tuple from the wire.

        This should only be called once.
        """
        version = self._request.read_line()
        if version != self.response_marker:
            self._request.finished_reading()
            raise errors.UnexpectedProtocolVersionMarker(version)
        response_status = self._request.read_line()
        result = SmartClientRequestProtocolOne._read_response_tuple(self)
        self._response_is_unknown_method(result)
        if response_status == b"success\n":
            self.response_status = True
            if not expect_body:
                self._request.finished_reading()
            return result
        elif response_status == b"failed\n":
            self.response_status = False
            self._request.finished_reading()
            raise errors.ErrorFromSmartServer(result)
        else:
            raise errors.SmartProtocolError("bad protocol status {!r}".format(response_status))

    def _write_protocol_version(self):
        """Write any prefixes this protocol requires.

        Version two sends the value of REQUEST_VERSION_TWO.
        """
        self._request.accept_bytes(self.request_marker)

    def read_streamed_body(self):
        """Read bytes from the body, decoding into a byte stream."""
        # Read no more than 64k at a time so that we don't risk error 10055 (no
        # buffer space available) on Windows.
        _body_decoder = ChunkedBodyDecoder()
        while not _body_decoder.finished_reading:
            bytes = self._request.read_bytes(_body_decoder.next_read_size())
            if bytes == b"":
                # end of file encountered reading from server
                raise errors.ConnectionReset(
                    "Connection lost while reading streamed body."
                )
            _body_decoder.accept_bytes(bytes)
            for body_bytes in iter(_body_decoder.read_next_chunk, None):
                if "hpss" in debug.debug_flags and isinstance(body_bytes, str):
                    mutter("              %d byte chunk read", len(body_bytes))
                yield body_bytes
        self._request.finished_reading()


def build_server_protocol_three(
    backing_transport, write_func, root_client_path, jail_root=None
):
    request_handler = request.SmartServerRequestHandler(
        backing_transport,
        commands=request.request_handlers,
        root_client_path=root_client_path,
        jail_root=jail_root,
    )
    responder = ProtocolThreeResponder(write_func)
    message_handler = message.ConventionalRequestHandler(request_handler, responder)
    return ProtocolThreeDecoder(message_handler)


class ProtocolThreeDecoder(_StatefulDecoder):
    response_marker = RESPONSE_VERSION_THREE
    request_marker = REQUEST_VERSION_THREE

    def __init__(self, message_handler, expect_version_marker=False):
        _StatefulDecoder.__init__(self)
        self._has_dispatched = False
        # Initial state
        if expect_version_marker:
            self.state_accept = self._state_accept_expecting_protocol_version
            # We're expecting at least the protocol version marker + some
            # headers.
            self._number_needed_bytes = len(MESSAGE_VERSION_THREE) + 4
        else:
            self.state_accept = self._state_accept_expecting_headers
            self._number_needed_bytes = 4
        self.decoding_failed = False
        self.request_handler = self.message_handler = message_handler

    def accept_bytes(self, bytes):
        self._number_needed_bytes = None
        try:
            _StatefulDecoder.accept_bytes(self, bytes)
        except KeyboardInterrupt:
            raise
        except SmartMessageHandlerError as exception:
            # We do *not* set self.decoding_failed here.  The message handler
            # has raised an error, but the decoder is still able to parse bytes
            # and determine when this message ends.
            if not isinstance(exception.exc_value, errors.UnknownSmartMethod):
                log_exception_quietly()
            self.message_handler.protocol_error(exception.exc_value)
            # The state machine is ready to continue decoding, but the
            # exception has interrupted the loop that runs the state machine.
            # So we call accept_bytes again to restart it.
            self.accept_bytes(b"")
        except Exception as exception:
            # The decoder itself has raised an exception.  We cannot continue
            # decoding.
            self.decoding_failed = True
            if isinstance(exception, errors.UnexpectedProtocolVersionMarker):
                # This happens during normal operation when the client tries a
                # protocol version the server doesn't understand, so no need to
                # log a traceback every time.
                # Note that this can only happen when
                # expect_version_marker=True, which is only the case on the
                # client side.
                pass
            else:
                log_exception_quietly()
            self.message_handler.protocol_error(exception)

    def _extract_length_prefixed_bytes(self):
        if self._in_buffer_len < 4:
            # A length prefix by itself is 4 bytes, and we don't even have that
            # many yet.
            raise _NeedMoreBytes(4)
        (length,) = struct.unpack("!L", self._get_in_bytes(4))
        end_of_bytes = 4 + length
        if self._in_buffer_len < end_of_bytes:
            # We haven't yet read as many bytes as the length-prefix says there
            # are.
            raise _NeedMoreBytes(end_of_bytes)
        # Extract the bytes from the buffer.
        in_buf = self._get_in_buffer()
        bytes = in_buf[4:end_of_bytes]
        self._set_in_buffer(in_buf[end_of_bytes:])
        return bytes

    def _extract_prefixed_bencoded_data(self):
        prefixed_bytes = self._extract_length_prefixed_bytes()
        try:
            decoded = bdecode_as_tuple(prefixed_bytes)
        except ValueError as e:
            raise errors.SmartProtocolError(
                "Bytes {!r} not bencoded".format(prefixed_bytes)
            ) from e
        return decoded

    def _extract_single_byte(self):
        if self._in_buffer_len == 0:
            # The buffer is empty
            raise _NeedMoreBytes(1)
        in_buf = self._get_in_buffer()
        one_byte = in_buf[0:1]
        self._set_in_buffer(in_buf[1:])
        return one_byte

    def _state_accept_expecting_protocol_version(self):
        needed_bytes = len(MESSAGE_VERSION_THREE) - self._in_buffer_len
        in_buf = self._get_in_buffer()
        if needed_bytes > 0:
            # We don't have enough bytes to check if the protocol version
            # marker is right.  But we can check if it is already wrong by
            # checking that the start of MESSAGE_VERSION_THREE matches what
            # we've read so far.
            # [In fact, if the remote end isn't bzr we might never receive
            # len(MESSAGE_VERSION_THREE) bytes.  So if the bytes we have so far
            # are wrong then we should just raise immediately rather than
            # stall.]
            if not MESSAGE_VERSION_THREE.startswith(in_buf):
                # We have enough bytes to know the protocol version is wrong
                raise errors.UnexpectedProtocolVersionMarker(in_buf)
            raise _NeedMoreBytes(len(MESSAGE_VERSION_THREE))
        if not in_buf.startswith(MESSAGE_VERSION_THREE):
            raise errors.UnexpectedProtocolVersionMarker(in_buf)
        self._set_in_buffer(in_buf[len(MESSAGE_VERSION_THREE) :])
        self.state_accept = self._state_accept_expecting_headers

    def _state_accept_expecting_headers(self):
        decoded = self._extract_prefixed_bencoded_data()
        if not isinstance(decoded, dict):
            raise errors.SmartProtocolError(
                "Header object {!r} is not a dict".format(decoded)
            )
        self.state_accept = self._state_accept_expecting_message_part
        try:
            self.message_handler.headers_received(decoded)
        except BaseException as e:
            raise SmartMessageHandlerError(sys.exc_info()) from e

    def _state_accept_expecting_message_part(self):
        message_part_kind = self._extract_single_byte()
        if message_part_kind == b"o":
            self.state_accept = self._state_accept_expecting_one_byte
        elif message_part_kind == b"s":
            self.state_accept = self._state_accept_expecting_structure
        elif message_part_kind == b"b":
            self.state_accept = self._state_accept_expecting_bytes
        elif message_part_kind == b"e":
            self.done()
        else:
            raise errors.SmartProtocolError(
                "Bad message kind byte: {!r}".format(message_part_kind)
            )

    def _state_accept_expecting_one_byte(self):
        byte = self._extract_single_byte()
        self.state_accept = self._state_accept_expecting_message_part
        try:
            self.message_handler.byte_part_received(byte)
        except BaseException as e:
            raise SmartMessageHandlerError(sys.exc_info()) from e

    def _state_accept_expecting_bytes(self):
        # XXX: this should not buffer whole message part, but instead deliver
        # the bytes as they arrive.
        prefixed_bytes = self._extract_length_prefixed_bytes()
        self.state_accept = self._state_accept_expecting_message_part
        try:
            self.message_handler.bytes_part_received(prefixed_bytes)
        except BaseException as e:
            raise SmartMessageHandlerError(sys.exc_info()) from e

    def _state_accept_expecting_structure(self):
        structure = self._extract_prefixed_bencoded_data()
        self.state_accept = self._state_accept_expecting_message_part
        try:
            self.message_handler.structure_part_received(structure)
        except BaseException as e:
            raise SmartMessageHandlerError(sys.exc_info()) from e

    def done(self):
        self.unused_data = self._get_in_buffer()
        self._set_in_buffer(None)
        self.state_accept = self._state_accept_reading_unused
        try:
            self.message_handler.end_received()
        except BaseException as e:
            raise SmartMessageHandlerError(sys.exc_info()) from e

    def _state_accept_reading_unused(self):
        self.unused_data += self._get_in_buffer()
        self._set_in_buffer(None)

    def next_read_size(self):
        if self.state_accept == self._state_accept_reading_unused:
            return 0
        elif self.decoding_failed:
            # An exception occured while processing this message, probably from
            # self.message_handler.  We're not sure that this state machine is
            # in a consistent state, so just signal that we're done (i.e. give
            # up).
            return 0
        else:
            if self._number_needed_bytes is not None:
                return self._number_needed_bytes - self._in_buffer_len
            else:
                raise AssertionError("don't know how many bytes are expected!")


class _ProtocolThreeEncoder:
    response_marker = request_marker = MESSAGE_VERSION_THREE
    BUFFER_SIZE = 1024 * 1024  # 1 MiB buffer before flushing

    def __init__(self, write_func):
        self._buf = []
        self._buf_len = 0
        self._real_write_func = write_func

    def _write_func(self, bytes):
        # TODO: Another possibility would be to turn this into an async model.
        #       Where we let another thread know that we have some bytes if
        #       they want it, but we don't actually block for it
        #       Note that osutils.send_all always sends 64kB chunks anyway, so
        #       we might just push out smaller bits at a time?
        self._buf.append(bytes)
        self._buf_len += len(bytes)
        if self._buf_len > self.BUFFER_SIZE:
            self.flush()

    def flush(self):
        if self._buf:
            self._real_write_func(b"".join(self._buf))
            del self._buf[:]
            self._buf_len = 0

    def _serialise_offsets(self, offsets):
        """Serialise a readv offset list."""
        txt = []
        for start, length in offsets:
            txt.append(b"%d,%d" % (start, length))
        return b"\n".join(txt)

    def _write_protocol_version(self):
        self._write_func(MESSAGE_VERSION_THREE)

    def _write_prefixed_bencode(self, structure):
        bytes = bencode(structure)
        self._write_func(struct.pack("!L", len(bytes)))
        self._write_func(bytes)

    def _write_headers(self, headers):
        self._write_prefixed_bencode(headers)

    def _write_structure(self, args):
        self._write_func(b"s")
        utf8_args = []
        for arg in args:
            if isinstance(arg, str):
                utf8_args.append(arg.encode("utf8"))
            else:
                utf8_args.append(arg)
        self._write_prefixed_bencode(utf8_args)

    def _write_end(self):
        self._write_func(b"e")
        self.flush()

    def _write_prefixed_body(self, bytes):
        self._write_func(b"b")
        self._write_func(struct.pack("!L", len(bytes)))
        self._write_func(bytes)

    def _write_chunked_body_start(self):
        self._write_func(b"oC")

    def _write_error_status(self):
        self._write_func(b"oE")

    def _write_success_status(self):
        self._write_func(b"oS")


class ProtocolThreeResponder(_ProtocolThreeEncoder):
    def __init__(self, write_func):
        _ProtocolThreeEncoder.__init__(self, write_func)
        self.response_sent = False
        self._headers = {b"Software version": breezy.__version__.encode("utf-8")}
        if "hpss" in debug.debug_flags:
            self._thread_id = _thread.get_ident()
            self._response_start_time = None

    def _trace(self, action, message, extra_bytes=None, include_time=False):
        if self._response_start_time is None:
            self._response_start_time = osutils.perf_counter()
        if include_time:
            t = "%5.3fs " % (osutils.perf_counter() - self._response_start_time)
        else:
            t = ""
        if extra_bytes is None:
            extra = ""
        else:
            extra = " " + repr(extra_bytes[:40])
            if len(extra) > 33:
                extra = extra[:29] + extra[-1] + "..."
        mutter("%12s: [%s] %s%s%s" % (action, self._thread_id, t, message, extra))

    def send_error(self, exception):
        if self.response_sent:
            raise AssertionError(
                "send_error({}) called, but response already sent.".format(exception)
            )
        if isinstance(exception, errors.UnknownSmartMethod):
            failure = request.FailedSmartServerResponse(
                (b"UnknownMethod", exception.verb)
            )
            self.send_response(failure)
            return
        if "hpss" in debug.debug_flags:
            self._trace("error", str(exception))
        self.response_sent = True
        self._write_protocol_version()
        self._write_headers(self._headers)
        self._write_error_status()
        self._write_structure((b"error", str(exception).encode("utf-8", "replace")))
        self._write_end()

    def send_response(self, response):
        if self.response_sent:
            raise AssertionError(
                "send_response({!r}) called, but response already sent.".format(response)
            )
        self.response_sent = True
        self._write_protocol_version()
        self._write_headers(self._headers)
        if response.is_successful():
            self._write_success_status()
        else:
            self._write_error_status()
        if "hpss" in debug.debug_flags:
            self._trace("response", repr(response.args))
        self._write_structure(response.args)
        if response.body is not None:
            self._write_prefixed_body(response.body)
            if "hpss" in debug.debug_flags:
                self._trace(
                    "body",
                    f"{len(response.body)} bytes",
                    response.body,
                    include_time=True,
                )
        elif response.body_stream is not None:
            count = num_bytes = 0
            first_chunk = None
            for exc_info, chunk in _iter_with_errors(response.body_stream):
                count += 1
                if exc_info is not None:
                    self._write_error_status()
                    error_struct = request._translate_error(exc_info[1])
                    self._write_structure(error_struct)
                    break
                else:
                    if isinstance(chunk, request.FailedSmartServerResponse):
                        self._write_error_status()
                        self._write_structure(chunk.args)
                        break
                    num_bytes += len(chunk)
                    if first_chunk is None:
                        first_chunk = chunk
                    self._write_prefixed_body(chunk)
                    self.flush()
                    if "hpssdetail" in debug.debug_flags:
                        # Not worth timing separately, as _write_func is
                        # actually buffered
                        self._trace(
                            "body chunk",
                            f"{len(chunk)} bytes",
                            chunk,
                            suppress_time=True,
                        )
            if "hpss" in debug.debug_flags:
                self._trace(
                    "body stream",
                    f"{num_bytes} bytes {count} chunks",
                    first_chunk,
                )
        self._write_end()
        if "hpss" in debug.debug_flags:
            self._trace("response end", "", include_time=True)


def _iter_with_errors(iterable):
    """Handle errors from iterable.next().

    Use like::

        for exc_info, value in _iter_with_errors(iterable):
            ...

    This is a safer alternative to::

        try:
            for value in iterable:
               ...
        except:
            ...

    Because the latter will catch errors from the for-loop body, not just
    iterable.next()

    If an error occurs, exc_info will be a exc_info tuple, and the generator
    will terminate.  Otherwise exc_info will be None, and value will be the
    value from iterable.next().  Note that KeyboardInterrupt and SystemExit
    will not be itercepted.
    """
    iterator = iter(iterable)
    while True:
        try:
            yield None, next(iterator)
        except StopIteration:
            return
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            mutter("_iter_with_errors caught error")
            log_exception_quietly()
            yield sys.exc_info(), None
            return


class ProtocolThreeRequester(_ProtocolThreeEncoder, Requester):
    def __init__(self, medium_request):
        _ProtocolThreeEncoder.__init__(self, medium_request.accept_bytes)
        self._medium_request = medium_request
        self._headers = {}
        self.body_stream_started = None

    def set_headers(self, headers):
        self._headers = headers.copy()

    def call(self, *args):
        if "hpss" in debug.debug_flags:
            mutter("hpss call:   %s", repr(args)[1:-1])
            base = getattr(self._medium_request._medium, "base", None)
            if base is not None:
                mutter("             (to %s)", base)
            self._request_start_time = osutils.perf_counter()
        self._write_protocol_version()
        self._write_headers(self._headers)
        self._write_structure(args)
        self._write_end()
        self._medium_request.finished_writing()

    def call_with_body_bytes(self, args, body):
        """Make a remote call of args with body bytes 'body'.

        After calling this, call read_response_tuple to find the result out.
        """
        if "hpss" in debug.debug_flags:
            mutter("hpss call w/body: %s (%r...)", repr(args)[1:-1], body[:20])
            path = getattr(self._medium_request._medium, "_path", None)
            if path is not None:
                mutter("                  (to %s)", path)
            mutter("              %d bytes", len(body))
            self._request_start_time = osutils.perf_counter()
        self._write_protocol_version()
        self._write_headers(self._headers)
        self._write_structure(args)
        self._write_prefixed_body(body)
        self._write_end()
        self._medium_request.finished_writing()

    def call_with_body_readv_array(self, args, body):
        r"""Make a remote call with a readv array.

        The body is encoded with one line per readv offset pair. The numbers in
        each pair are separated by a comma, and no trailing \\n is emitted.
        """
        if "hpss" in debug.debug_flags:
            mutter("hpss call w/readv: %s", repr(args)[1:-1])
            path = getattr(self._medium_request._medium, "_path", None)
            if path is not None:
                mutter("                  (to %s)", path)
            self._request_start_time = osutils.perf_counter()
        self._write_protocol_version()
        self._write_headers(self._headers)
        self._write_structure(args)
        readv_bytes = self._serialise_offsets(body)
        if "hpss" in debug.debug_flags:
            mutter("              %d bytes in readv request", len(readv_bytes))
        self._write_prefixed_body(readv_bytes)
        self._write_end()
        self._medium_request.finished_writing()

    def call_with_body_stream(self, args, stream):
        if "hpss" in debug.debug_flags:
            mutter("hpss call w/body stream: %r", args)
            path = getattr(self._medium_request._medium, "_path", None)
            if path is not None:
                mutter("                  (to %s)", path)
            self._request_start_time = osutils.perf_counter()
        self.body_stream_started = False
        self._write_protocol_version()
        self._write_headers(self._headers)
        self._write_structure(args)
        # TODO: notice if the server has sent an early error reply before we
        #       have finished sending the stream.  We would notice at the end
        #       anyway, but if the medium can deliver it early then it's good
        #       to short-circuit the whole request...
        # Provoke any ConnectionReset failures before we start the body stream.
        self.flush()
        self.body_stream_started = True
        for exc_info, part in _iter_with_errors(stream):
            if exc_info is not None:
                # Iterating the stream failed.  Cleanly abort the request.
                self._write_error_status()
                # Currently the client unconditionally sends ('error',) as the
                # error args.
                self._write_structure((b"error",))
                self._write_end()
                self._medium_request.finished_writing()
                (exc_type, exc_val, exc_tb) = exc_info
                try:
                    raise exc_val
                finally:
                    del exc_info
            else:
                self._write_prefixed_body(part)
                self.flush()
        self._write_end()
        self._medium_request.finished_writing()
