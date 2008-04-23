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

    def __init__(self):
        self.headers = None

    def headers_received(self, headers):
        self.headers = headers

    def byte_part_received(self, byte):
        raise NotImplementedError(self.byte_received)

    def bytes_part_received(self, bytes):
        raise NotImplementedError(self.bytes_received)

    def structure_part_received(self, structure):
        raise NotImplementedError(self.bytes_received)

    def protocol_error(self, exception):
        """Called when there is a protocol decoding error."""
        raise
    
    def end_received(self):
        # No-op by default.
        pass


class ConventionalRequestHandler(MessageHandler):

    def __init__(self, request_handler, responder):
        MessageHandler.__init__(self)
        self.request_handler = request_handler
        self.responder = responder
        self.args_received = False

    def protocol_error(self, exception):
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
        # XXX: this API requires monolithic bodies to be buffered
        # XXX: how to distinguish between a monolithic body and a chunk stream?
        #      Hmm, I guess the request handler knows which it is expecting
        #      (once the args have been received), so it should just deal?  We
        #      don't yet have requests that expect a stream anyway.
        #      *Maybe* a one-byte 'c' or 'm' (chunk or monolithic) flag before
        #      first bytes part?
        self.request_handler.accept_body(bytes)
        self.request_handler.end_of_body()
        assert self.request_handler.finished_reading
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
            raise errors.ConnectionReset(
                "please check connectivity and permissions",
                "(and try -Dhpss if further diagnosis is required)")
        self._protocol_decoder.accept_bytes(bytes)

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
        """
        # XXX: don't buffer the full request
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
    if error_name == 'UnknownSmartMethod':
        raise errors.UnknownSmartMethod(error_args[1])
    if error_name == 'LockContention':
        raise errors.LockContention('(remote lock)')
    elif error_name == 'LockFailed':
        raise errors.LockFailed(*error_args[:2])
    else:
        raise errors.ErrorFromSmartServer(error_tuple)
