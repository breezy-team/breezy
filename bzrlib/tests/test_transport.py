# Copyright (C) 2004, 2005 by Canonical Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


import os
import sys
import stat
from cStringIO import StringIO

from bzrlib.errors import (NoSuchFile, FileExists,
                           TransportNotPossible,
                           ConnectionError,
                           DependencyNotPresent,
                           )
from bzrlib.tests import TestCase
from bzrlib.transport import (_get_protocol_handlers,
                              _get_transport_modules,
                              get_transport,
                              register_lazy_transport,
                              _set_protocol_handlers,
                              urlescape,
                              Transport,
                              )
from bzrlib.transport.memory import MemoryTransport
from bzrlib.transport.local import LocalTransport


class TestTransport(TestCase):
    """Test the non transport-concrete class functionality."""

    def test_urlescape(self):
        self.assertEqual('%25', urlescape('%'))

    def test__get_set_protocol_handlers(self):
        handlers = _get_protocol_handlers()
        self.assertNotEqual({}, handlers)
        try:
            _set_protocol_handlers({})
            self.assertEqual({}, _get_protocol_handlers())
        finally:
            _set_protocol_handlers(handlers)

    def test_get_transport_modules(self):
        handlers = _get_protocol_handlers()
        class SampleHandler(object):
            """I exist, isnt that enough?"""
        try:
            my_handlers = {}
            _set_protocol_handlers(my_handlers)
            register_lazy_transport('foo', 'bzrlib.tests.test_transport', 'TestTransport.SampleHandler')
            register_lazy_transport('bar', 'bzrlib.tests.test_transport', 'TestTransport.SampleHandler')
            self.assertEqual([SampleHandler.__module__],
                             _get_transport_modules())
        finally:
            _set_protocol_handlers(handlers)

    def test_transport_dependency(self):
        """Transport with missing dependency causes no error"""
        saved_handlers = _get_protocol_handlers()
        try:
            register_lazy_transport('foo', 'bzrlib.tests.test_transport',
                    'BadTransportHandler')
            t = get_transport('foo://fooserver/foo')
            # because we failed to load the transport
            self.assertTrue(isinstance(t, LocalTransport))
        finally:
            # restore original values
            _set_protocol_handlers(saved_handlers)
            
    def test_transport_fallback(self):
        """Transport with missing dependency causes no error"""
        saved_handlers = _get_protocol_handlers()
        try:
            register_lazy_transport('foo', 'bzrlib.tests.test_transport',
                    'BackupTransportHandler')
            register_lazy_transport('foo', 'bzrlib.tests.test_transport',
                    'BadTransportHandler')
            t = get_transport('foo://fooserver/foo')
            # we should have got the backup one
            self.assertTrue(isinstance(t, BackupTransportHandler))
        finally:
            # restore original values
            _set_protocol_handlers(saved_handlers)
            

class TestMemoryTransport(TestCase):

    def test_get_transport(self):
        MemoryTransport()

    def test_clone(self):
        transport = MemoryTransport()
        self.assertTrue(isinstance(transport, MemoryTransport))

    def test_abspath(self):
        transport = MemoryTransport()
        self.assertEqual("memory:/relpath", transport.abspath('relpath'))

    def test_relpath(self):
        transport = MemoryTransport()

    def test_append_and_get(self):
        transport = MemoryTransport()
        transport.append('path', StringIO('content'))
        self.assertEqual(transport.get('path').read(), 'content')
        transport.append('path', StringIO('content'))
        self.assertEqual(transport.get('path').read(), 'contentcontent')

    def test_put_and_get(self):
        transport = MemoryTransport()
        transport.put('path', StringIO('content'))
        self.assertEqual(transport.get('path').read(), 'content')
        transport.put('path', StringIO('content'))
        self.assertEqual(transport.get('path').read(), 'content')

    def test_append_without_dir_fails(self):
        transport = MemoryTransport()
        self.assertRaises(NoSuchFile,
                          transport.append, 'dir/path', StringIO('content'))

    def test_put_without_dir_fails(self):
        transport = MemoryTransport()
        self.assertRaises(NoSuchFile,
                          transport.put, 'dir/path', StringIO('content'))

    def test_get_missing(self):
        transport = MemoryTransport()
        self.assertRaises(NoSuchFile, transport.get, 'foo')

    def test_has_missing(self):
        transport = MemoryTransport()
        self.assertEquals(False, transport.has('foo'))

    def test_has_present(self):
        transport = MemoryTransport()
        transport.append('foo', StringIO('content'))
        self.assertEquals(True, transport.has('foo'))

    def test_mkdir(self):
        transport = MemoryTransport()
        transport.mkdir('dir')
        transport.append('dir/path', StringIO('content'))
        self.assertEqual(transport.get('dir/path').read(), 'content')

    def test_mkdir_missing_parent(self):
        transport = MemoryTransport()
        self.assertRaises(NoSuchFile,
                          transport.mkdir, 'dir/dir')

    def test_mkdir_twice(self):
        transport = MemoryTransport()
        transport.mkdir('dir')
        self.assertRaises(FileExists, transport.mkdir, 'dir')

    def test_parameters(self):
        transport = MemoryTransport()
        self.assertEqual(True, transport.listable())
        self.assertEqual(False, transport.should_cache())
        self.assertEqual(False, transport.is_readonly())

    def test_iter_files_recursive(self):
        transport = MemoryTransport()
        transport.mkdir('dir')
        transport.put('dir/foo', StringIO('content'))
        transport.put('dir/bar', StringIO('content'))
        transport.put('bar', StringIO('content'))
        paths = set(transport.iter_files_recursive())
        self.assertEqual(set(['dir/foo', 'dir/bar', 'bar']), paths)

    def test_stat(self):
        transport = MemoryTransport()
        transport.put('foo', StringIO('content'))
        transport.put('bar', StringIO('phowar'))
        self.assertEqual(7, transport.stat('foo').st_size)
        self.assertEqual(6, transport.stat('bar').st_size)

        
class ReadonlyDecoratorTransportTest(TestCase):
    """Readonly decoration specific tests."""

    def test_local_parameters(self):
        import bzrlib.transport.readonly as readonly
        # connect to . in readonly mode
        transport = readonly.ReadonlyTransportDecorator('readonly+.')
        self.assertEqual(True, transport.listable())
        self.assertEqual(False, transport.should_cache())
        self.assertEqual(True, transport.is_readonly())

    def test_http_parameters(self):
        import bzrlib.transport.readonly as readonly
        from bzrlib.transport.http import HttpServer
        # connect to . via http which is not listable
        server = HttpServer()
        server.setUp()
        try:
            transport = get_transport('readonly+' + server.get_url())
            self.failUnless(isinstance(transport,
                                       readonly.ReadonlyTransportDecorator))
            self.assertEqual(False, transport.listable())
            self.assertEqual(True, transport.should_cache())
            self.assertEqual(True, transport.is_readonly())
        finally:
            server.tearDown()


class BadTransportHandler(Transport):
    def __init__(self, base_url):
        raise DependencyNotPresent('some_lib', 'testing missing dependency')


class BackupTransportHandler(Transport):
    """Test transport that works as a backup for the BadTransportHandler"""
    pass
