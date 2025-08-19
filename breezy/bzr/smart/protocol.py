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
from ..._bzr_rs import smart as _smart_rs
from ...trace import log_exception_quietly, mutter
from . import message, request

# Protocol version strings.  These are sent as prefixes of bzr requests and
# responses to identify the protocol version being used. (There are no version
# one strings because that version doesn't send any).
REQUEST_VERSION_TWO = _smart_rs.REQUEST_VERSION_TWO
RESPONSE_VERSION_TWO = _smart_rs.RESPONSE_VERSION_TWO

MESSAGE_VERSION_THREE = _smart_rs.MESSAGE_VERSION_THREE
REQUEST_VERSION_THREE = _smart_rs.REQUEST_VERSION_THREE
RESPONSE_VERSION_THREE = _smart_rs.RESPONSE_VERSION_THREE


class SmartMessageHandlerError(errors.InternalBzrError):
    """Error raised when a smart message handler encounters an exception.

    This error wraps exceptions that occur during smart protocol message
    handling, providing traceback information for debugging.

    Attributes:
        exc_type: The exception type that was raised.
        exc_value: The exception instance that was raised.
        exc_tb: The traceback object for the exception.
        exc_info: The complete sys.exc_info() tuple.
        traceback_text: String representation of the traceback.
    """

    _fmt = "The message handler raised an exception:\n%(traceback_text)s"

    def __init__(self, exc_info):
        """Initialize SmartMessageHandlerError with exception information.

        Args:
            exc_info: The sys.exc_info() tuple containing exception details.
        """
        import traceback

        # GZ 2010-08-10: Cycle with exc_tb/exc_info affects at least one test
        self.exc_type, self.exc_value, self.exc_tb = exc_info
        self.exc_info = exc_info
        traceback_strings = traceback.format_exception(
            self.exc_type, self.exc_value, self.exc_tb
        )
        self.traceback_text = "".join(traceback_strings)


def _recv_tuple(from_file):
    """Receive a tuple from a file-like object.

    Reads a line from the file and decodes it as a tuple using the smart
    protocol tuple encoding.

    Args:
        from_file: A file-like object to read from.

    Returns:
        A tuple decoded from the line, or None if no data available.
    """
    req_line = from_file.readline()
    return _decode_tuple(req_line)


def _decode_tuple(req_line):
    r"""Decode a byte string into a tuple using smart protocol encoding.

    The smart protocol encodes tuples by joining elements with ASCII 0x01
    (SOH - Start of Header) characters and terminating with a newline.

    Args:
        req_line: Bytes representing an encoded tuple, or None/empty bytes.

    Returns:
        A tuple of byte strings, or None if req_line is None or empty.

    Raises:
        SmartProtocolError: If the line is not properly terminated with '\n'.
    """
    if req_line is None or req_line == b"":
        return None
    if not req_line.endswith(b"\n"):
        raise errors.SmartProtocolError(f"request {req_line!r} not terminated")
    return tuple(req_line[:-1].split(b"\x01"))


def _encode_tuple(args):
    """Encode a tuple of arguments to a bytestream using smart protocol encoding.

    The smart protocol encodes tuples by joining elements with ASCII 0x01
    (SOH - Start of Header) characters and terminating with a newline.

    Args:
        args: A tuple or sequence of byte string arguments to encode.

    Returns:
        A byte string representing the encoded tuple.

    Raises:
        TypeError: If any argument is a unicode string instead of bytes.
    """
    for arg in args:
        if isinstance(arg, str):
            raise TypeError(args)
    return b"\x01".join(args) + b"\n"


class Requester:
    """Abstract base class for objects that can issue requests on a smart medium.

    This class defines the interface for making remote calls through the smart
    protocol. Concrete implementations handle the actual network communication
    and protocol-specific encoding/decoding.

    The smart protocol supports several types of requests:
    - Simple calls with arguments only
    - Calls with binary body data
    - Calls with readv offset arrays for efficient bulk reading
    - Protocol version 3+ supports streaming body data
    """

    def call(self, *args):
        """Make a remote call with the given arguments.

        Args:
            *args: The command and arguments to send to the remote server.
                  All arguments must be byte strings.

        Raises:
            NotImplementedError: This method must be implemented by subclasses.
        """
        raise NotImplementedError(self.call)

    def call_with_body_bytes(self, args, body):
        """Make a remote call with binary body data.

        Args:
            args: Sequence of byte string arguments for the remote call.
            body: Binary data to send as the request body.

        Raises:
            NotImplementedError: This method must be implemented by subclasses.
        """
        raise NotImplementedError(self.call_with_body_bytes)

    def call_with_body_readv_array(self, args, body):
        """Make a remote call with a readv offset array.

        This is used for efficient bulk reading operations where the client
        needs specific byte ranges from a remote file or stream.

        Args:
            args: Sequence of byte string arguments for the remote call.
            body: Iterable of (start, length) tuples specifying byte ranges
                 to read from the remote resource.

        Raises:
            NotImplementedError: This method must be implemented by subclasses.
        """
        raise NotImplementedError(self.call_with_body_readv_array)

    def set_headers(self, headers):
        """Set headers for the next request.

        Args:
            headers: Dictionary of header name/value pairs to send.

        Raises:
            NotImplementedError: This method must be implemented by subclasses.
        """
        raise NotImplementedError(self.set_headers)


class SmartProtocolBase:
    """Base class providing methods common to smart protocol clients and servers.

    This class contains utility methods for encoding and serializing data
    used by both client and server sides of the smart protocol communication.
    The methods handle the low-level protocol details like bulk data encoding
    and offset serialization for readv operations.
    """

    # TODO: this only actually accomodates a single block; possibly should
    # support multiple chunks?
    def _encode_bulk_data(self, body):
        r"""Encode binary data as a length-prefixed bulk data chunk.

        The smart protocol uses a simple length-prefixed format for bulk data:
        - Length as decimal digits followed by newline
        - The actual data bytes
        - "done\n" terminator

        Args:
            body: Binary data to encode as a bulk data chunk.

        Returns:
            Encoded bulk data as bytes, ready to send over the wire.
        """
        return b"".join((b"%d\n" % len(body), body, b"done\n"))

    def _serialise_offsets(self, offsets):
        """Serialize a list of readv offsets for transmission.

        Readv operations allow efficient reading of multiple byte ranges
        from a remote resource. Each offset is encoded as "start,length"
        with offsets separated by newlines.

        Args:
            offsets: Iterable of (start, length) tuples specifying byte ranges.

        Returns:
            Serialized offsets as bytes, with each offset on a separate line.
        """
        txt = []
        for start, length in offsets:
            txt.append(b"%d,%d" % (start, length))
        return b"\n".join(txt)


class SmartServerRequestProtocolOne(SmartProtocolBase):
    """Server-side protocol handler for smart protocol version 1.

    This class implements the server-side logic for handling smart protocol
    version 1 requests. It manages the state machine for parsing incoming
    requests, dispatching them to appropriate handlers, and sending responses.

    Protocol version 1 characteristics:
    - No explicit protocol version markers
    - Simple success/failure indication
    - Length-prefixed bulk data encoding
    - Tuple-based argument encoding with 0x01 separators

    Attributes:
        unused_data: Any data received but not consumed by the protocol.
        request: The current SmartServerRequestHandler instance.
    """

    def __init__(
        self, backing_transport, write_func, root_client_path="/", jail_root=None
    ):
        """Initialize a smart server protocol version 1 handler.

        Args:
            backing_transport: Transport object providing access to the repository.
            write_func: Callable to write response data to the client.
            root_client_path: Root path for client requests (default "/").
            jail_root: Optional path to jail client access within.
        """
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
        """Accept incoming bytes and advance the protocol state machine.

        This method processes incoming data through the protocol state machine,
        parsing request arguments, handling body data, and generating responses.
        The state machine handles:
        1. Parsing the initial request line with command arguments
        2. Reading any request body data if required
        3. Dispatching to the appropriate request handler
        4. Sending the response back to the client

        Args:
            data: Incoming bytes from the client connection.

        Raises:
            ValueError: If data is not a byte string.
            SmartProtocolError: If the request format is invalid.
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
                    f"bad request '{err.verb.decode('ascii')}'"
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
        """Send a smart server response to the client.

        Formats and sends a complete response including protocol markers,
        success/failure status, response arguments, and any response body.

        Args:
            response: SmartServerResponse object containing the response data.

        Raises:
            AssertionError: If a response has already been sent.
            ValueError: If response body is not bytes.
        """
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
        """Write protocol version markers if required.

        Version one doesn't send protocol version markers, so this is a no-op.
        Subclasses for later protocol versions override this to send markers.
        """

    def _write_success_or_failure_prefix(self, response):
        """Write protocol-specific success/failure indicators.

        Protocol version 1 doesn't send explicit success/failure prefixes,
        but we validate the response by calling is_successful() to ensure
        the response object is properly formed.

        Args:
            response: SmartServerResponse to validate and process.
        """
        response.is_successful()

    def next_read_size(self):
        """Return the number of bytes needed for the next protocol operation.

        This helps optimize network reads by indicating how much data should
        be read in the next operation to make progress through the protocol.

        Returns:
            Number of bytes needed, or 0 if protocol processing is complete.
        """
        if self._finished:
            return 0
        if self._body_decoder is None:
            return 1
        else:
            return self._body_decoder.next_read_size()


class SmartServerRequestProtocolTwo(SmartServerRequestProtocolOne):
    r"""Server-side protocol handler for smart protocol version 2.

    This class extends version 1 with explicit success/failure status indicators
    and protocol version markers. This makes the protocol more robust and allows
    better error handling.

    Protocol version 2 enhancements over version 1:
    - Explicit RESPONSE_VERSION_TWO marker at start of responses
    - "success\n" or "failed\n" status indicators before response args
    - Support for streaming response bodies in addition to bulk data
    - Better error propagation and handling

    Attributes:
        response_marker: Version marker sent at start of responses.
        request_marker: Version marker expected from clients.
    """

    response_marker = RESPONSE_VERSION_TWO
    request_marker = REQUEST_VERSION_TWO

    def _write_success_or_failure_prefix(self, response):
        r"""Write explicit success/failure status indicators.

        Protocol version 2 sends "success\n" for successful responses
        and "failed\n" for error responses, allowing clients to distinguish
        between success and failure before parsing response arguments.

        Args:
            response: SmartServerResponse to check and indicate status for.
        """
        if response.is_successful():
            self._write_func(b"success\n")
        else:
            self._write_func(b"failed\n")

    def _write_protocol_version(self):
        r"""Write the protocol version marker for version 2.

        Sends RESPONSE_VERSION_TWO marker to identify this as a version 2
        response, allowing clients to use the appropriate parsing logic.
        """
        self._write_func(self.response_marker)

    def _send_response(self, response):
        """Send a smart server response using protocol version 2 format.

        This method handles both regular bulk body responses and streaming
        body responses, with proper protocol version markers and status
        indicators for robust client parsing.

        Args:
            response: SmartServerResponse object containing response data.

        Raises:
            AssertionError: If response has already been sent or if both
                          body and body_stream are set.
        """
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
    r"""Send a stream of data using chunked encoding.

    This function implements HTTP-like chunked encoding for streaming
    response bodies. It sends a "chunked\n" header, followed by the
    chunked data, and terminates with "END\n".

    Args:
        stream: Iterable yielding byte chunks or FailedSmartServerResponse objects.
        write_func: Function to call for writing data to the client.
    """
    write_func(b"chunked\n")
    _send_chunks(stream, write_func)
    write_func(b"END\n")


def _send_chunks(stream, write_func):
    """Send individual chunks from a stream with length prefixes.

    Each chunk is sent with a hexadecimal length prefix (like HTTP chunked
    encoding). If a FailedSmartServerResponse is encountered, an error
    indicator is sent followed by the error details.

    Args:
        stream: Iterable of byte chunks or FailedSmartServerResponse objects.
        write_func: Function to call for writing data to the client.

    Raises:
        BzrError: If a chunk is neither bytes nor FailedSmartServerResponse.
    """
    for chunk in stream:
        if isinstance(chunk, bytes):
            data = f"{len(chunk):x}\n".encode("ascii") + chunk
            write_func(data)
        elif isinstance(chunk, request.FailedSmartServerResponse):
            write_func(b"ERR\n")
            _send_chunks(chunk.args, write_func)
            return
        else:
            raise errors.BzrError(
                f"Chunks must be str or FailedSmartServerResponse, got {chunk!r}"
            )


class _NeedMoreBytes(Exception):
    """Exception raised by state machine decoders when more input is needed.

    This exception is used internally by _StatefulDecoder subclasses to signal
    that the current decoding operation cannot proceed without additional bytes.
    It allows the decoder to pause processing and resume when more data arrives.

    This is a control flow mechanism that enables efficient streaming protocol
    parsing without blocking on incomplete data.

    Attributes:
        count: Total number of bytes needed to proceed, or None if unknown.
    """

    def __init__(self, count=None):
        """Initialize a _NeedMoreBytes exception.

        Args:
            count: Total number of bytes needed by the current decoder state.
                  May be None if the exact number is unknown.
        """
        self.count = count


class _StatefulDecoder:
    """Base class for implementing streaming protocol decoders using state machines.

    This class provides infrastructure for building protocol parsers that can
    handle partial input gracefully. Subclasses implement specific protocol
    logic by defining state transition functions.

    Key features:
    - Buffered input handling for incomplete data
    - State machine architecture with pluggable state functions
    - Efficient memory management for large streams
    - Support for both known and unknown-length data parsing

    The state machine works by:
    1. Accepting new bytes via accept_bytes()
    2. Calling the current state_accept function repeatedly
    3. State functions can change self.state_accept to transition states
    4. State functions raise _NeedMoreBytes when input is insufficient

    Attributes:
        finished_reading: True when decoding is complete.
        unused_data: Any bytes received but not consumed.
        bytes_left: Number of bytes remaining in current operation.
        state_accept: Current state function to process bytes.

    See ProtocolThreeDecoder and ChunkedBodyDecoder for example subclasses.
    """

    def __init__(self):
        self.finished_reading = False
        self._in_buffer_list = []
        self._in_buffer_len = 0
        self.unused_data = b""
        self.bytes_left = None
        self._number_needed_bytes = None

    def _get_in_buffer(self):
        """Get the complete contents of the input buffer as a single bytes object.

        This method efficiently handles the case where the buffer consists of
        multiple fragments by joining them only when necessary. For single-fragment
        buffers, it returns the fragment directly.

        Returns:
            All buffered input data as a single bytes object.

        Raises:
            AssertionError: If internal buffer length tracking is inconsistent.
        """
        if len(self._in_buffer_list) == 1:
            return self._in_buffer_list[0]
        in_buffer = b"".join(self._in_buffer_list)
        if len(in_buffer) != self._in_buffer_len:
            raise AssertionError(
                "Length of buffer did not match expected value: {} != {}".format(
                    len(in_buffer), self._in_buffer_len
                ),
            )
        self._in_buffer_list = [in_buffer]
        return in_buffer

    def _get_in_bytes(self, count):
        """Extract a specified number of bytes from the input buffer without consuming them.

        This method allows peeking at buffered data to determine if enough bytes
        are available for parsing. The bytes remain in the buffer until explicitly
        consumed via _get_in_buffer() and _set_in_buffer().

        Args:
            count: Number of bytes to extract from the front of the buffer.

        Returns:
            First 'count' bytes from the input buffer.

        Raises:
            AssertionError: If called when no bytes are buffered.

        Note:
            Callers should verify self._in_buffer_len >= count before calling.
            This method does not consume the bytes - use _set_in_buffer() to consume.
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
        """Set the contents of the input buffer, replacing any existing data.

        This method is used to update the buffer after consuming bytes during
        parsing. It efficiently handles both data replacement and buffer clearing.

        Args:
            new_buf: New buffer contents as bytes, or None to clear the buffer.

        Raises:
            TypeError: If new_buf is not bytes (when not None).
        """
        if new_buf is not None:
            if not isinstance(new_buf, bytes):
                raise TypeError(new_buf)
            self._in_buffer_list = [new_buf]
            self._in_buffer_len = len(new_buf)
        else:
            self._in_buffer_list = []
            self._in_buffer_len = 0

    def accept_bytes(self, new_buf):
        """Accept new bytes and advance the decoder state machine as far as possible.

        This method adds new bytes to the internal buffer and runs the state
        machine until it can no longer make progress (due to insufficient data
        or completion). Any excess data is stored in unused_data.

        The state machine will run through multiple state transitions in a single
        call if sufficient data is available, making parsing as efficient as possible.

        Args:
            new_buf: New bytes to add to the input buffer for processing.

        Raises:
            TypeError: If new_buf is not bytes.
            _NeedMoreBytes: Set internally to control state machine flow.

        Side Effects:
            - Updates finished_reading when decoding is complete
            - Stores excess data in unused_data
            - Advances state machine through multiple transitions if possible
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
    r"""Decoder for HTTP-style chunked transfer encoding used in smart protocol v2+.

    This decoder handles streaming response bodies that are sent as a series of
    length-prefixed chunks, similar to HTTP/1.1 chunked transfer encoding.
    It supports both normal data chunks and error conditions within the stream.

    Protocol format:
    1. "chunked\n" header
    2. Series of chunks, each with:
       - Hexadecimal length + "\n"
       - Chunk data (length bytes)
    3. "END\n" terminator

    Error handling:
    - "ERR\n" indicates error chunks follow
    - Error chunks contain structured error information

    Attributes:
        chunk_in_progress: Current chunk being assembled, or None.
        chunks: Queue of completed chunks ready for consumption.
        error: True if processing error chunks.
        error_in_progress: List of error chunk parts being assembled.

    See `doc/developers/network-protocol.txt` for full format specification.
    """

    def __init__(self):
        """Initialize a chunked body decoder.

        Sets up the state machine to begin expecting the "chunked" header.
        """
        _StatefulDecoder.__init__(self)
        self.state_accept = self._state_accept_expecting_header
        self.chunk_in_progress = None
        self.chunks = deque()
        self.error = False
        self.error_in_progress = None

    def next_read_size(self):
        """Calculate optimal number of bytes to read for the next parsing step.

        This method helps optimize network I/O by suggesting how many bytes
        should be read to make progress in the current decoder state. The
        calculation accounts for protocol overhead and current parsing position.

        Returns:
            Suggested number of bytes to read, or 0/1 if no specific size needed.

        Raises:
            AssertionError: If decoder is in an unexpected state.
        """
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
            raise AssertionError(f"Impossible state: {self.state_accept!r}")

    def read_next_chunk(self):
        """Retrieve the next completed chunk from the queue.

        Returns chunks in the order they were received. If an error was
        encountered during parsing, the returned chunk may be a
        FailedSmartServerResponse object instead of bytes.

        Returns:
            Next chunk as bytes, FailedSmartServerResponse for errors,
            or None if no chunks are available.
        """
        try:
            return self.chunks.popleft()
        except IndexError:
            return None

    def _extract_line(self):
        """Extract a complete line from the input buffer.

        Searches for and extracts text up to the first newline character.
        The newline is consumed but not included in the returned data.

        Returns:
            Line content as bytes, excluding the newline character.

        Raises:
            _NeedMoreBytes: If no complete line is available in the buffer.
        """
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
        """Complete the chunked decoding process and clean up state.

        This method is called when the "END" marker is encountered, indicating
        all chunks have been received. It handles final error processing if
        needed and marks the decoder as finished.

        Side Effects:
            - Moves any remaining buffer data to unused_data
            - Transitions to reading_unused state
            - Creates FailedSmartServerResponse for any pending errors
            - Sets finished_reading to True
        """
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
        r"""State function: Parse and validate the chunked transfer header.

        Expects to receive "chunked\n" as the first line of a chunked response.
        Transitions to expecting chunk length on success.

        Raises:
            SmartProtocolError: If header is not "chunked".
        """
        prefix = self._extract_line()
        if prefix == b"chunked":
            self.state_accept = self._state_accept_expecting_length
        else:
            raise errors.SmartProtocolError(f'Bad chunked body header: "{prefix}"')

    def _state_accept_expecting_length(self):
        """State function: Parse chunk length or control markers.

        Handles three possible inputs:
        - Hexadecimal chunk length: Sets up for reading that many bytes
        - "ERR": Switches to error mode for processing error chunks
        - "END": Completes decoding and marks as finished

        The hexadecimal length follows HTTP chunked encoding conventions.
        """
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
        """State function: Read chunk data up to the expected length.

        Accumulates bytes into the current chunk until the full length
        is received. Handles partial reads gracefully by updating the
        remaining byte count and continuing on the next call.

        When complete, adds the chunk to the appropriate queue (normal
        chunks or error chunks) and transitions back to expecting length.
        """
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
        """State function: Accumulate any extra data after decoding is complete.

        This state is entered after "END" is received. Any additional bytes
        are stored in unused_data for potential use by subsequent operations.
        """
        self.unused_data += self._get_in_buffer()
        self._in_buffer_list = []


class LengthPrefixedBodyDecoder(_StatefulDecoder):
    r"""Decoder for length-prefixed bulk data used in smart protocol v1 and v2.

    This decoder handles the simple bulk data format used for request and response
    bodies in smart protocol versions 1 and 2. The format consists of:
    1. Decimal length followed by newline
    2. Exactly that many bytes of data
    3. "done\n" trailer

    This format is simpler than chunked encoding and is used when the total
    data size is known in advance, such as for file contents or fixed-size
    serialized data structures.

    Protocol format example:
        "1024\n"     (length)
        <1024 bytes> (data)
        "done\n"     (trailer)

    Attributes:
        _body: Accumulated body data.
        _trailer_buffer: Buffer for reading the "done\n" trailer.
        state_read: Current read state function for extracting decoded data.
    """

    def __init__(self):
        """Initialize a length-prefixed body decoder.

        Sets up the state machine to begin expecting a decimal length.
        """
        _StatefulDecoder.__init__(self)
        self.state_accept = self._state_accept_expecting_length
        self.state_read = self._state_read_no_data
        self._body = b""
        self._trailer_buffer = b""

    def next_read_size(self):
        """Calculate optimal number of bytes to read for the next parsing step.

        Returns an estimate of how many bytes should be read to make progress
        in the current state. This helps optimize I/O by suggesting larger
        reads when possible (e.g., reading body + trailer together).

        Returns:
            Suggested number of bytes to read for optimal progress.
        """
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
        """Return any decoded body data that is ready for consumption.

        This method uses the current read state function to extract available
        data. Before the body is fully read, it returns empty bytes. Once body
        parsing begins, it returns data incrementally.

        Returns:
            Decoded body data as bytes, or empty bytes if none available.
        """
        return self.state_read()

    def _state_accept_expecting_length(self):
        """State function: Parse the decimal length prefix.

        Searches for a newline-terminated decimal number indicating how many
        bytes of body data follow. Transitions to body reading state once
        a complete length is available.

        Side Effects:
            - Sets bytes_left to the parsed length
            - Transitions to reading_body state
            - Switches to body_buffer read state
        """
        in_buf = self._get_in_buffer()
        pos = in_buf.find(b"\n")
        if pos == -1:
            return
        self.bytes_left = int(in_buf[:pos])
        self._set_in_buffer(in_buf[pos + 1 :])
        self.state_accept = self._state_accept_reading_body
        self.state_read = self._state_read_body_buffer

    def _state_accept_reading_body(self):
        """State function: Accumulate body data up to the expected length.

        Reads all available buffer data into the body, tracking how many bytes
        remain. If more data than expected is available, the excess is moved
        to the trailer buffer. Transitions to trailer reading when complete.

        Side Effects:
            - Accumulates data in _body
            - Updates bytes_left counter
            - Handles excess data in _trailer_buffer
            - Transitions to reading_trailer state when body is complete
        """
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
        """State function: Read and validate the "done\n" trailer.

        Accumulates data until "done\n" is found, then completes decoding.
        Any data after "done\n" is stored as unused_data.

        TODO: Consider raising ProtocolViolation if trailer doesn't match.

        Side Effects:
            - Accumulates trailer data in _trailer_buffer
            - Sets finished_reading when "done\n" found
            - Stores excess data in unused_data
        """
        self._trailer_buffer += self._get_in_buffer()
        self._set_in_buffer(None)
        # TODO: what if the trailer does not match "done\n"?  Should this raise
        # a ProtocolViolation exception?
        if self._trailer_buffer.startswith(b"done\n"):
            self.unused_data = self._trailer_buffer[len(b"done\n") :]
            self.state_accept = self._state_accept_reading_unused
            self.finished_reading = True

    def _state_accept_reading_unused(self):
        r"""State function: Accumulate unused data after decoding completes.

        This state handles any additional data received after the "done\\n"
        trailer. All such data is stored in unused_data.
        """
        self.unused_data += self._get_in_buffer()
        self._set_in_buffer(None)

    def _state_read_no_data(self):
        """Read state function: Return empty data when no body is available yet.

        Returns:
            Empty bytes, indicating no decoded data is available.
        """
        return b""

    def _state_read_body_buffer(self):
        """Read state function: Return and clear the accumulated body data.

        This implements a "read once" pattern where the body data is returned
        and then cleared, ensuring each piece of data is only consumed once.

        Returns:
            All accumulated body data as bytes, clearing the internal buffer.
        """
        result = self._body
        self._body = b""
        return result


class SmartClientRequestProtocolOne(
    SmartProtocolBase, Requester, message.ResponseHandler
):
    """Client-side implementation of smart protocol version 1.

    This class handles the client side of smart protocol version 1 communication,
    including request serialization, response parsing, and body data handling.
    It implements the Requester interface for making various types of calls.

    Protocol version 1 client characteristics:
    - No explicit protocol version markers in requests
    - Supports simple calls, calls with body bytes, and readv calls
    - Uses length-prefixed encoding for body data
    - Basic error detection and handling

    Attributes:
        _request: Underlying SmartClientMediumRequest for network communication.
        _body_buffer: Buffer for reading response body data.
        _last_verb: Last command verb sent, used for error handling.
        _headers: Request headers to send.
    """

    def __init__(self, request):
        """Initialize a smart client protocol version 1 handler.

        Args:
            request: SmartClientMediumRequest object that handles the actual
                    network communication and low-level request/response handling.
        """
        self._request = request
        self._body_buffer = None
        self._request_start_time = None
        self._last_verb = None
        self._headers = None

    def set_headers(self, headers):
        """Set headers for subsequent requests.

        Args:
            headers: Dictionary of header name/value pairs.
        """
        self._headers = dict(headers)

    def call(self, *args):
        """Execute remote call with given arguments.

        Args:
            *args: Arguments to pass to the remote method.

        Returns:
            Response from the remote call.
        """
        if debug.debug_flag_enabled("hpss"):
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
        if debug.debug_flag_enabled("hpss"):
            mutter("hpss call w/body: %s (%r...)", repr(args)[1:-1], body[:20])
            if getattr(self._request._medium, "_path", None) is not None:
                mutter("                  (to %s)", self._request._medium._path)
            mutter("              %d bytes", len(body))
            self._request_start_time = osutils.perf_counter()
            if debug.debug_flag_enabled("hpssdetail"):
                mutter("hpss body content: %s", body)
        self._write_args(args)
        bytes = self._encode_bulk_data(body)
        self._request.accept_bytes(bytes)
        self._request.finished_writing()
        self._last_verb = args[0]

    def call_with_body_readv_array(self, args, body):
        r"""Make a remote call with a readv array.

        The body is encoded with one line per readv offset pair. The numbers in
        each pair are separated by a comma, and no trailing \n is emitted.
        """
        if debug.debug_flag_enabled("hpss"):
            mutter("hpss call w/readv: %s", repr(args)[1:-1])
            if getattr(self._request._medium, "_path", None) is not None:
                mutter("                  (to %s)", self._request._medium._path)
            self._request_start_time = osutils.perf_counter()
        self._write_args(args)
        readv_bytes = self._serialise_offsets(body)
        bytes = self._encode_bulk_data(readv_bytes)
        self._request.accept_bytes(bytes)
        self._request.finished_writing()
        if debug.debug_flag_enabled("hpss"):
            mutter("              %d bytes in readv request", len(readv_bytes))
        self._last_verb = args[0]

    def call_with_body_stream(self, args, stream):
        """Attempt to make a call with a streaming body (not supported in v1).

        Protocol versions 1 and 2 don't support streaming request bodies.
        This method immediately raises UnknownSmartMethod since any command
        requiring streaming would not be supported by v1/v2 servers.

        Args:
            args: Command arguments.
            stream: Iterator of body data chunks (unused).

        Raises:
            UnknownSmartMethod: Always raised since v1 doesn't support streaming.
        """
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
        if debug.debug_flag_enabled("hpss"):
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
                raise ConnectionResetError(
                    "Connection lost while reading response body."
                )
            _body_decoder.accept_bytes(bytes)
        self._request.finished_reading()
        self._body_buffer = BytesIO(_body_decoder.read_pending_data())
        # XXX: TODO check the trailer result.
        if debug.debug_flag_enabled("hpss"):
            mutter(
                "              %d body bytes read", len(self._body_buffer.getvalue())
            )
        return self._body_buffer.read(count)

    def _recv_tuple(self):
        """Receive a tuple from the medium request."""
        return _decode_tuple(self._request.read_line())

    def query_version(self):
        """Query the server's supported smart protocol version.

        Sends a "hello" request to determine what protocol version the
        server supports. This is used for protocol version negotiation.

        Returns:
            Integer protocol version number (1 or 2).

        Raises:
            SmartProtocolError: If server response is not recognized.
        """
        self.call(b"hello")
        resp = self.read_response_tuple()
        if resp == (b"ok", b"1"):
            return 1
        elif resp == (b"ok", b"2"):
            return 2
        else:
            raise errors.SmartProtocolError(f"bad response {resp!r}")

    def _write_args(self, args):
        self._write_protocol_version()
        bytes = _encode_tuple(args)
        self._request.accept_bytes(bytes)

    def _write_protocol_version(self):
        """Write protocol version markers if required.

        Version one doesn't send protocol version markers, so this is a no-op.
        Subclasses for later protocol versions override this to send markers.
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
            raise errors.SmartProtocolError(f"bad protocol status {response_status!r}")

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
                raise ConnectionResetError(
                    "Connection lost while reading streamed body."
                )
            _body_decoder.accept_bytes(bytes)
            for body_bytes in iter(_body_decoder.read_next_chunk, None):
                if debug.debug_flag_enabled("hpss") and isinstance(body_bytes, str):
                    mutter("              %d byte chunk read", len(body_bytes))
                yield body_bytes
        self._request.finished_reading()


def build_server_protocol_three(
    backing_transport, write_func, root_client_path, jail_root=None
):
    """Build and configure a complete smart protocol version 3 server stack.

    This factory function creates all the components needed for handling
    smart protocol version 3 requests on the server side, including the
    decoder, message handler, request handler, and responder.

    Args:
        backing_transport: Transport providing access to the repository data.
        write_func: Function to call for writing response data to the client.
        root_client_path: Root path for client requests.
        jail_root: Optional path to restrict client access within.

    Returns:
        ProtocolThreeDecoder configured with a complete request handling stack.
    """
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
    """Decoder for version 3 of the smart protocol.

    Handles decoding of protocol version 3 messages including
    headers, body chunks, and error handling.
    """

    response_marker = RESPONSE_VERSION_THREE
    request_marker = REQUEST_VERSION_THREE

    def __init__(self, message_handler, expect_version_marker=False):
        """Initialize ProtocolThreeDecoder.

        Args:
            message_handler: Handler for processing decoded messages.
            expect_version_marker: Whether to expect protocol version marker.
        """
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
        """Accept and process incoming bytes.

        Args:
            bytes: Bytes to process.
        """
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
                f"Bytes {prefixed_bytes!r} not bencoded"
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
            raise errors.SmartProtocolError(f"Header object {decoded!r} is not a dict")
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
                f"Bad message kind byte: {message_part_kind!r}"
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
        """Mark decoding as complete and process unused data."""
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
        """Get the size of the next read operation.

        Returns:
            int: Number of bytes to read next, or 0 if done.
        """
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
    """Encoder for version 3 of the smart protocol.

    Handles encoding and buffering of protocol version 3 messages
    with support for chunked bodies and structured responses.
    """

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
    """Responder for version 3 of the smart protocol.

    Handles sending responses using protocol version 3 encoding
    with support for success/error status and body streaming.
    """

    def __init__(self, write_func):
        """Initialize ProtocolThreeResponder.

        Args:
            write_func: Function to write response bytes.
        """
        _ProtocolThreeEncoder.__init__(self, write_func)
        self.response_sent = False
        self._headers = {b"Software version": breezy.__version__.encode("utf-8")}
        if debug.debug_flag_enabled("hpss"):
            self._thread_id = _thread.get_ident()
            self._response_start_time = None

    def _trace(self, action, message, extra_bytes=None, include_time=False):
        if self._response_start_time is None:
            self._response_start_time = osutils.perf_counter()
        if include_time:
            t = f"{osutils.perf_counter() - self._response_start_time:5.3f}s "
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
        """Send an error response.

        Args:
            exception: Exception to send as error response.

        Raises:
            AssertionError: If response was already sent.
        """
        if self.response_sent:
            raise AssertionError(
                f"send_error({exception}) called, but response already sent."
            )
        if isinstance(exception, errors.UnknownSmartMethod):
            failure = request.FailedSmartServerResponse(
                (b"UnknownMethod", exception.verb)
            )
            self.send_response(failure)
            return
        if debug.debug_flag_enabled("hpss"):
            self._trace("error", str(exception))
        self.response_sent = True
        self._write_protocol_version()
        self._write_headers(self._headers)
        self._write_error_status()
        self._write_structure((b"error", str(exception).encode("utf-8", "replace")))
        self._write_end()

    def send_response(self, response):
        """Send a response.

        Args:
            response: Response object to send.

        Raises:
            AssertionError: If response was already sent.
        """
        if self.response_sent:
            raise AssertionError(
                f"send_response({response!r}) called, but response already sent."
            )
        self.response_sent = True
        self._write_protocol_version()
        self._write_headers(self._headers)
        if response.is_successful():
            self._write_success_status()
        else:
            self._write_error_status()
        if debug.debug_flag_enabled("hpss"):
            self._trace("response", repr(response.args))
        self._write_structure(response.args)
        if response.body is not None:
            self._write_prefixed_body(response.body)
            if debug.debug_flag_enabled("hpss"):
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
                    if debug.debug_flag_enabled("hpssdetail"):
                        # Not worth timing separately, as _write_func is
                        # actually buffered
                        self._trace(
                            "body chunk",
                            f"{len(chunk)} bytes",
                            chunk,
                            suppress_time=True,
                        )
            if debug.debug_flag_enabled("hpss"):
                self._trace(
                    "body stream",
                    "%d bytes %d chunks" % (num_bytes, count),
                    first_chunk,
                )
        self._write_end()
        if debug.debug_flag_enabled("hpss"):
            self._trace("response end", "", include_time=True)


def _iter_with_errors(iterable):
    """Safely iterate over an iterable, capturing exceptions from next() calls.

    This utility function provides a safer way to iterate over potentially
    problematic iterables by isolating exceptions that occur during iteration
    from exceptions that might occur in the consuming code.

    The function yields (exc_info, value) tuples:
    - (None, value): Normal iteration, value is from iterable
    - (exc_info, None): Exception occurred, exc_info is sys.exc_info() tuple

    Usage example::

        for exc_info, value in _iter_with_errors(stream):
            if exc_info is not None:
                # Handle the exception from iteration
                log_error(exc_info)
                break
            else:
                # Process the value normally
                process(value)

    This is safer than a try/except around a for loop because it only catches
    exceptions from the iterator's next() method, not from the loop body.

    Args:
        iterable: Any iterable object to iterate over safely.

    Yields:
        Tuples of (exc_info, value):
        - exc_info: None for normal values, sys.exc_info() tuple for errors
        - value: Iterator value or None when exc_info is not None

    Note:
        KeyboardInterrupt and SystemExit are not caught and will propagate
        normally to allow proper program termination.
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
    """Requester for version 3 of the smart protocol.

    Handles making requests using protocol version 3 encoding
    with support for protocol negotiation and error handling.
    """

    def __init__(self, medium_request):
        """Initialize ProtocolThreeRequester.

        Args:
            medium_request: Medium request to use for communication.
        """
        _ProtocolThreeEncoder.__init__(self, medium_request.accept_bytes)
        self._medium_request = medium_request
        self._headers = {}
        self.body_stream_started = None

    def set_headers(self, headers):
        """Set request headers.

        Args:
            headers: Dictionary of headers to set.
        """
        self._headers = headers.copy()

    def call(self, *args):
        """Make a remote call.

        Args:
            *args: Arguments for the remote call.

        Returns:
            Response from the remote call.
        """
        if debug.debug_flag_enabled("hpss"):
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
        if debug.debug_flag_enabled("hpss"):
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
        each pair are separated by a comma, and no trailing \n is emitted.
        """
        if debug.debug_flag_enabled("hpss"):
            mutter("hpss call w/readv: %s", repr(args)[1:-1])
            path = getattr(self._medium_request._medium, "_path", None)
            if path is not None:
                mutter("                  (to %s)", path)
            self._request_start_time = osutils.perf_counter()
        self._write_protocol_version()
        self._write_headers(self._headers)
        self._write_structure(args)
        readv_bytes = self._serialise_offsets(body)
        if debug.debug_flag_enabled("hpss"):
            mutter("              %d bytes in readv request", len(readv_bytes))
        self._write_prefixed_body(readv_bytes)
        self._write_end()
        self._medium_request.finished_writing()

    def call_with_body_stream(self, args, stream):
        """Make a remote call with a body stream.

        Args:
            args: Arguments for the remote call.
            stream: Body stream to send with the call.

        Returns:
            Response from the remote call.
        """
        if debug.debug_flag_enabled("hpss"):
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
