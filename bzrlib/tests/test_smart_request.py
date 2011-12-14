# Copyright (C) 2009, 2010 Canonical Ltd
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

"""Tests for smart server request infrastructure (bzrlib.smart.request)."""

import threading

from bzrlib import (
    errors,
    transport,
    )
from bzrlib.bzrdir import BzrDir
from bzrlib.smart import request
from bzrlib.tests import TestCase, TestCaseWithMemoryTransport


class NoBodyRequest(request.SmartServerRequest):
    """A request that does not implement do_body."""

    def do(self):
        return request.SuccessfulSmartServerResponse(('ok',))


class DoErrorRequest(request.SmartServerRequest):
    """A request that raises an error from self.do()."""

    def do(self):
        raise errors.NoSuchFile('xyzzy')


class DoUnexpectedErrorRequest(request.SmartServerRequest):
    """A request that encounters a generic error in self.do()"""

    def do(self):
        dict()[1]


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


class CheckJailRequest(request.SmartServerRequest):

    def __init__(self, *args):
        request.SmartServerRequest.__init__(self, *args)
        self.jail_transports_log = []

    def do(self):
        self.jail_transports_log.append(request.jail_info.transports)

    def do_chunk(self, bytes):
        self.jail_transports_log.append(request.jail_info.transports)

    def do_end(self):
        self.jail_transports_log.append(request.jail_info.transports)


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

    def test_only_request_code_is_jailed(self):
        transport = 'dummy transport'
        handler = request.SmartServerRequestHandler(
            transport, {'foo': CheckJailRequest}, '/')
        handler.args_received(('foo',))
        self.assertEqual(None, request.jail_info.transports)
        handler.accept_body('bytes')
        self.assertEqual(None, request.jail_info.transports)
        handler.end_received()
        self.assertEqual(None, request.jail_info.transports)
        self.assertEqual(
            [[transport]] * 3, handler._command.jail_transports_log)

    def test_all_registered_requests_are_safety_qualified(self):
        unclassified_requests = []
        allowed_info = ('read', 'idem', 'mutate', 'semivfs', 'semi', 'stream')
        for key in request.request_handlers.keys():
            info = request.request_handlers.get_info(key)
            if info is None or info not in allowed_info:
                unclassified_requests.append(key)
        if unclassified_requests:
            self.fail('These requests were not categorized as safe/unsafe'
                      ' to retry: %s'  % (unclassified_requests,))


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

    def test_unexpected_error_translation(self):
        handler = request.SmartServerRequestHandler(
            None, {'foo': DoUnexpectedErrorRequest}, '/')
        handler.args_received(('foo',))
        self.assertEqual(
            request.FailedSmartServerResponse(('error', 'KeyError', "1")),
            handler.response)


class TestRequestHanderErrorTranslation(TestCase):
    """Tests for bzrlib.smart.request._translate_error."""

    def assertTranslationEqual(self, expected_tuple, error):
        self.assertEqual(expected_tuple, request._translate_error(error))

    def test_NoSuchFile(self):
        self.assertTranslationEqual(
            ('NoSuchFile', 'path'), errors.NoSuchFile('path'))

    def test_LockContention(self):
        # For now, LockContentions are always transmitted with no details.
        # Eventually they should include a relpath or url or something else to
        # identify which lock is busy.
        self.assertTranslationEqual(
            ('LockContention',), errors.LockContention('lock', 'msg'))

    def test_TokenMismatch(self):
        self.assertTranslationEqual(
            ('TokenMismatch', 'some-token', 'actual-token'),
            errors.TokenMismatch('some-token', 'actual-token'))

    def test_MemoryError(self):
        self.assertTranslationEqual(("MemoryError",), MemoryError())

    def test_generic_Exception(self):
        self.assertTranslationEqual(('error', 'Exception', ""),
            Exception())

    def test_generic_BzrError(self):
        self.assertTranslationEqual(('error', 'BzrError', "some text"),
            errors.BzrError(msg="some text"))

    def test_generic_zlib_error(self):
        from zlib import error
        msg = "Error -3 while decompressing data: incorrect data check"
        self.assertTranslationEqual(('error', 'zlib.error', msg),
            error(msg))


class TestRequestJail(TestCaseWithMemoryTransport):

    def test_jail(self):
        transport = self.get_transport('blah')
        req = request.SmartServerRequest(transport)
        self.assertEqual(None, request.jail_info.transports)
        req.setup_jail()
        self.assertEqual([transport], request.jail_info.transports)
        req.teardown_jail()
        self.assertEqual(None, request.jail_info.transports)


class TestJailHook(TestCaseWithMemoryTransport):

    def setUp(self):
        super(TestJailHook, self).setUp()
        def clear_jail_info():
            request.jail_info.transports = None
        self.addCleanup(clear_jail_info)

    def test_jail_hook(self):
        request.jail_info.transports = None
        _pre_open_hook = request._pre_open_hook
        # Any transport is fine if jail_info.transports is None
        t = self.get_transport('foo')
        _pre_open_hook(t)
        # A transport in jail_info.transports is allowed
        request.jail_info.transports = [t]
        _pre_open_hook(t)
        # A child of a transport in jail_info is allowed
        _pre_open_hook(t.clone('child'))
        # A parent is not allowed
        self.assertRaises(errors.JailBreak, _pre_open_hook, t.clone('..'))
        # A completely unrelated transport is not allowed
        self.assertRaises(errors.JailBreak, _pre_open_hook,
                          transport.get_transport_from_url('http://host/'))

    def test_open_bzrdir_in_non_main_thread(self):
        """Opening a bzrdir in a non-main thread should work ok.
        
        This makes sure that the globally-installed
        bzrlib.smart.request._pre_open_hook, which uses a threading.local(),
        works in a newly created thread.
        """
        bzrdir = self.make_bzrdir('.')
        transport = bzrdir.root_transport
        thread_result = []
        def t():
            BzrDir.open_from_transport(transport)
            thread_result.append('ok')
        thread = threading.Thread(target=t)
        thread.start()
        thread.join()
        self.assertEqual(['ok'], thread_result)

