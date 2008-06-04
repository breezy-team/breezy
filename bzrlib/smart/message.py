# Copyright (C) 2008 Canonical Ltd
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

import collections
from cStringIO import StringIO

from bzrlib import (
    debug,
    errors,
    )
from bzrlib.trace import mutter


class MessageHandler(object):
    """Base class for handling messages received via the smart protocol.

    As parts of a message are received, the corresponding PART_received method
    will be called.
    """

    def __init__(self):
        self.headers = None

    def headers_received(self, headers):
        """Called when message headers are received.
        
        This default implementation just stores them in self.headers.
        """
        self.headers = headers

    def byte_part_received(self, byte):
        """Called when a 'byte' part is received.

        Note that a 'byte' part is a message part consisting of exactly one
        byte.
        """
        raise NotImplementedError(self.byte_received)

    def bytes_part_received(self, bytes):
        """Called when a 'bytes' part is received.

        A 'bytes' message part can contain any number of bytes.  It should not
        be confused with a 'byte' part, which is always a single byte.
        """
        raise NotImplementedError(self.bytes_received)

    def structure_part_received(self, structure):
        """Called when a 'structure' part is received.

        :param structure: some structured data, which will be some combination
            of list, dict, int, and str objects.
        """
        raise NotImplementedError(self.bytes_received)

    def protocol_error(self, exception):
        """Called when there is a protocol decoding error.
        
        The default implementation just re-raises the exception.
        """
        raise
    
    def end_received(self):
        """Called when the end of the message is received."""
        # No-op by default.
        pass


class ConventionalRequestHandler(MessageHandler):
    """A message handler for "conventional" requests.

    "Conventional" is used in the sense described in
    doc/developers/network-protocol.txt: a simple message with arguments and an
    optional body.
    """

    def __init__(self, request_handler, responder):
        MessageHandler.__init__(self)
        self.request_handler = request_handler
        self.responder = responder
        self.args_received = False

    def protocol_error(self, exception):
        if self.responder.response_sent:
            # We can only send one response to a request, no matter how many
            # errors happen while processing it.
            return
        self.responder.send_error(exception)

    def byte_part_received(self, byte):
        raise errors.SmartProtocolError(
            'Unexpected message part: byte(%r)' % (byte,))

    def structure_part_received(self, structure):
        if self.args_received:
            raise errors.SmartProtocolError(
                'Unexpected message part: structure(%r)' % (structure,))
        self.args_received = True
        self.request_handler.dispatch_command(structure[0], structure[1:])
        if self.request_handler.finished_reading:
            self.responder.send_response(self.request_handler.response)

    def bytes_part_received(self, bytes):
        # Note that there's no intrinsic way to distinguish a monolithic body
        # from a chunk stream.  A request handler knows which it is expecting
        # (once the args have been received), so it should be able to do the
        # right thing.
        self.request_handler.accept_body(bytes)
        self.request_handler.end_of_body()
        if not self.request_handler.finished_reading:
            raise SmartProtocolError(
                "Conventional request body was received, but request handler "
                "has not finished reading.")
        self.responder.send_response(self.request_handler.response)


class ResponseHandler(object):
    """Abstract base class for an object that handles a smart response."""

    def read_response_tuple(self, expect_body=False):
        """Reads and returns the response tuple for the current request.
        
        :keyword expect_body: a boolean indicating if a body is expected in the
            response.  Some protocol versions needs this information to know
            when a response is finished.  If False, read_body_bytes should
            *not* be called afterwards.  Defaults to False.
        :returns: tuple of response arguments.
        """
        raise NotImplementedError(self.read_response_tuple)

    def read_body_bytes(self, count=-1):
        """Read and return some bytes from the body.

        :param count: if specified, read up to this many bytes.  By default,
            reads the entire body.
        :returns: str of bytes from the response body.
        """
        raise NotImplementedError(self.read_body_bytes)

    def read_streamed_body(self):
        """Returns an iterable that reads and returns a series of body chunks.
        """
        raise NotImplementedError(self.read_streamed_body)

    def cancel_read_body(self):
        """Stop expecting a body for this response.

        If expect_body was passed to read_response_tuple, this cancels that
        expectation (and thus finishes reading the response, allowing a new
        request to be issued).  This is useful if a response turns out to be an
        error rather than a normal result with a body.
        """
        raise NotImplementedError(self.cancel_read_body)


class ConventionalResponseHandler(MessageHandler, ResponseHandler):

    def __init__(self):
        MessageHandler.__init__(self)
        self.status = None
        self.args = None
        self._bytes_parts = collections.deque()
        self._body_started = False
        self._body_stream_status = None
        self._body = None
        self._body_error_args = None
        self.finished_reading = False

    def setProtoAndMediumRequest(self, protocol_decoder, medium_request):
        self._protocol_decoder = protocol_decoder
        self._medium_request = medium_request

    def byte_part_received(self, byte):
        if byte not in ['E', 'S']:
            raise errors.SmartProtocolError(
                'Unknown response status: %r' % (byte,))
        if self._body_started:
            if self._body_stream_status is not None:
                raise errors.SmartProtocolError(
                    'Unexpected byte part received: %r' % (byte,))
            self._body_stream_status = byte
        else:
            if self.status is not None:
                raise errors.SmartProtocolError(
                    'Unexpected byte part received: %r' % (byte,))
            self.status = byte

    def bytes_part_received(self, bytes):
        self._body_started = True
        self._bytes_parts.append(bytes)

    def structure_part_received(self, structure):
        if type(structure) is not list:
            raise errors.SmartProtocolError(
                'Args structure is not a sequence: %r' % (structure,))
        structure = tuple(structure)
        if not self._body_started:
            if self.args is not None:
                raise errors.SmartProtocolError(
                    'Unexpected structure received: %r (already got %r)'
                    % (structure, self.args))
            self.args = structure
        else:
            if self._body_stream_status != 'E':
                raise errors.SmartProtocolError(
                    'Unexpected structure received after body: %r'
                    % (structure,))
            self._body_error_args = structure

    def _wait_for_response_args(self):
        while self.args is None and not self.finished_reading:
            self._read_more()

    def _wait_for_response_end(self):
        while not self.finished_reading:
            self._read_more()

    def _read_more(self):
        next_read_size = self._protocol_decoder.next_read_size()
        if next_read_size == 0:
            # a complete request has been read.
            self.finished_reading = True
            self._medium_request.finished_reading()
            return
        bytes = self._medium_request.read_bytes(next_read_size)
        if bytes == '':
            # end of file encountered reading from server
            if 'hpss' in debug.debug_flags:
                mutter(
                    'decoder state: buf[:10]=%r, state_accept=%s',
                    self._protocol_decoder._in_buffer[:10],
                    self._protocol_decoder.state_accept.__name__)
            raise errors.ConnectionReset(
                "please check connectivity and permissions",
                "(and try -Dhpss if further diagnosis is required)")
        self._protocol_decoder.accept_bytes(bytes)

    def protocol_error(self, exception):
        # Whatever the error is, we're done with this request.
        self.finished_reading = True
        self._medium_request.finished_reading()
        raise
        
    def read_response_tuple(self, expect_body=False):
        """Read a response tuple from the wire."""
        self._wait_for_response_args()
        if not expect_body:
            self._wait_for_response_end()
        if 'hpss' in debug.debug_flags:
            mutter('   result:   %r', self.args)
        if self.status == 'E':
            self._wait_for_response_end()
            _translate_error(self.args)
        return tuple(self.args)

    def read_body_bytes(self, count=-1):
        """Read bytes from the body, decoding into a byte stream.
        
        We read all bytes at once to ensure we've checked the trailer for 
        errors, and then feed the buffer back as read_body_bytes is called.

        Like the builtin file.read in Python, a count of -1 (the default) means
        read the entire body.
        """
        # TODO: we don't necessarily need to buffer the full request if count
        # != -1.  (2008/04/30, Andrew Bennetts)
        if self._body is None:
            self._wait_for_response_end()
            body_bytes = ''.join(self._bytes_parts)
            if 'hpss' in debug.debug_flags:
                mutter('              %d body bytes read', len(body_bytes))
            self._body = StringIO(body_bytes)
            self._bytes_parts = None
        return self._body.read(count)

    def read_streamed_body(self):
        while not self.finished_reading:
            while self._bytes_parts:
                bytes_part = self._bytes_parts.popleft()
                if 'hpss' in debug.debug_flags:
                    mutter('              %d byte part read', len(bytes_part))
                yield bytes_part
            self._read_more()
        if self._body_stream_status == 'E':
            _translate_error(self._body_error_args)

    def cancel_read_body(self):
        self._wait_for_response_end()


def _translate_error(error_tuple):
    # Many exceptions need some state from the requestor to be properly
    # translated (e.g. they need a branch object).  So this only translates a
    # few errors, and the rest are turned into a generic ErrorFromSmartServer.
    error_name = error_tuple[0]
    error_args = error_tuple[1:]
    if error_name == 'UnknownMethod':
        raise errors.UnknownSmartMethod(error_args[0])
    if error_name == 'LockContention':
        raise errors.LockContention('(remote lock)')
    elif error_name == 'LockFailed':
        raise errors.LockFailed(*error_args[:2])
    else:
        raise errors.ErrorFromSmartServer(error_tuple)
