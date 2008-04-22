# Copyright (C) 8 Canonical Ltd
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

from bzrlib import errors

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
        # XXX
        pass


class ConventionalRequestHandler(MessageHandler):

    def __init__(self, request_handler, responder):
        MessageHandler.__init__(self)
        self.request_handler = request_handler
        self.responder = responder
        self.args_received = False
#        self.args = None
#        self.error = None
#        self.prefixed_body = None
#        self.body_stream = None

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

    def end_received(self):
        # XXX
        pass


class ConventionalResponseHandler(MessageHandler):

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

    def setProtoAndMedium(self, protocol_decoder, medium):
        self._protocol_decoder = protocol_decoder
        self._medium = medium

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
            self._medium.finished_reading()
            return
        bytes = self._medium.read_bytes(next_read_size)
        if bytes == '':
            # end of file encountered reading from server
            raise errors.ConnectionReset(
                "please check connectivity and permissions",
                "(and try -Dhpss if further diagnosis is required)")
        self._protocol_decoder.accept_bytes(bytes)

    def read_response_tuple(self, expect_body=False):
        """Read a response tuple from the wire.

        The expect_body flag is ignored.
        """
        self._wait_for_response_args()
        if not expect_body:
            self._wait_for_response_end()
        #if self.status == 'E':
        #    xxx_translate_error() # XXX
        return tuple(self.args)

    def read_body_bytes(self, count=-1):
        """Read bytes from the body, decoding into a byte stream.
        
        We read all bytes at once to ensure we've checked the trailer for 
        errors, and then feed the buffer back as read_body_bytes is called.
        """
        # XXX: don't buffer the full request
        if self._body is None:
            self._wait_for_response_end()
            self._body = StringIO(''.join(self._bytes_parts))
            self._bytes_parts = None
        return self._body.read(count)

    def read_streamed_body(self):
        while not self.finished_reading:
            while self._bytes_parts:
                yield self._bytes_parts.popleft()
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
    if error_name == 'LockContention':
        raise errors.LockContention('(remote lock)')
    elif error_name == 'LockFailed':
        raise errors.LockContention(*error_args[:2])
    else:
        raise errors.ErrorFromSmartServer(error_tuple)
