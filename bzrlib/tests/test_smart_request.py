# Copyright (C) 2009 Canonical Ltd
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

"""Tests for smart server request infrastructure (bzrlib.smart.request)."""

from bzrlib import errors
from bzrlib.smart import request
from bzrlib.tests import TestCase


class NoBodyRequest(request.SmartServerRequest):
    """A request that does not implement do_body."""

    def do(self):
        return request.SuccessfulSmartServerResponse(('ok',))


class TestSmartRequest(TestCase):

    def test_request_class_without_do_body(self):
        """If a request has no body data, and the request's implementation does
        not override do_body, then no exception is raised.
        """
        # Create a SmartServerRequestHandler with a SmartServerRequest subclass
        # that does not implement do_body.
        handler = request.SmartServerRequestHandler(
            None, {'foo': NoBodyRequest}, '/')
        # Emulate a request with no body (i.e. just args).
        handler.args_received(('foo',))
        handler.end_received()
        # Request done, no exception was raised.

    def test_unexpected_body(self):
        """If a request implementation receives an unexpected body, it
        raises an error.
        """
        # Create a SmartServerRequestHandler with a SmartServerRequest subclass
        # that does not implement do_body.
        handler = request.SmartServerRequestHandler(
            None, {'foo': NoBodyRequest}, '/')
        # Emulate a request with a body
        handler.args_received(('foo',))
        handler.accept_body('some body bytes')
        # Note that the exception currently occurs at the end of the request.
        # In principle it would also be ok for it to happen earlier, during
        # accept_body.
        exc = self.assertRaises(errors.SmartProtocolError, handler.end_received)
        self.assertEquals('Request does not expect a body', exc.details)

