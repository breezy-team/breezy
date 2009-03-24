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


class DoErrorRequest(request.SmartServerRequest):
    """A request that raises an error from self.do()."""
    
    def do(self):
        raise errors.NoSuchFile('xyzzy')


class ChunkErrorRequest(request.SmartServerRequest):
    """A request that raises an error from self.do_chunk()."""
    
    def do(self):
        """No-op."""
        pass

    def do_chunk(self, bytes):
        raise errors.NoSuchFile('xyzzy')


class EndErrorRequest(request.SmartServerRequest):
    """A request that raises an error from self.do_end()."""
    
    def do(self):
        """No-op."""
        pass

    def do_chunk(self, bytes):
        """No-op."""
        pass
        
    def do_end(self):
        raise errors.NoSuchFile('xyzzy')


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


class TestSmartRequestHandlerErrorTranslation(TestCase):
    """Tests that SmartServerRequestHandler will translate exceptions raised by
    a SmartServerRequest into FailedSmartServerResponses.
    """

    def assertNoResponse(self, handler):
        self.assertEqual(None, handler.response)

    def assertResponseIsTranslatedError(self, handler):
        expected_translation = ('NoSuchFile', 'xyzzy')
        self.assertEqual(
            request.FailedSmartServerResponse(expected_translation),
            handler.response)

    def test_error_translation_from_args_received(self):
        handler = request.SmartServerRequestHandler(
            None, {'foo': DoErrorRequest}, '/')
        handler.args_received(('foo',))
        self.assertResponseIsTranslatedError(handler)

    def test_error_translation_from_chunk_received(self):
        handler = request.SmartServerRequestHandler(
            None, {'foo': ChunkErrorRequest}, '/')
        handler.args_received(('foo',))
        self.assertNoResponse(handler)
        handler.accept_body('bytes')
        self.assertResponseIsTranslatedError(handler)

    def test_error_translation_from_end_received(self):
        handler = request.SmartServerRequestHandler(
            None, {'foo': EndErrorRequest}, '/')
        handler.args_received(('foo',))
        self.assertNoResponse(handler)
        handler.end_received()
        self.assertResponseIsTranslatedError(handler)


class TestRequestHanderErrorTranslation(TestCase):
    """Tests for bzrlib.smart.request._translate_error."""

    def assertTranslationEqual(self, expected_tuple, error):
        self.assertEqual(expected_tuple, request._translate_error(error))

    def test_NoSuchFile(self):
        self.assertTranslationEqual(
            ('NoSuchFile', 'path'), errors.NoSuchFile('path'))

    def test_LockContention(self):
        self.assertTranslationEqual(
            ('LockContention', 'lock', 'msg'),
            errors.LockContention('lock', 'msg'))

    def test_TokenMismatch(self):
        self.assertTranslationEqual(
            ('TokenMismatch', 'some-token', 'actual-token'),
            errors.TokenMismatch('some-token', 'actual-token'))

