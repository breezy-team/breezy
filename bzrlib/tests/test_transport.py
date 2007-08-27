# Copyright (C) 2004, 2005, 2006, 2007 Canonical Ltd
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


import os
import sys
import stat
from cStringIO import StringIO

import bzrlib
from bzrlib import (
    errors,
    urlutils,
    )
from bzrlib.errors import (ConnectionError,
                           DependencyNotPresent,
                           FileExists,
                           InvalidURLJoin,
                           NoSuchFile,
                           PathNotChild,
                           TransportNotPossible,
                           ConnectionError,
                           DependencyNotPresent,
                           ReadError,
                           UnsupportedProtocol,
                           )
from bzrlib.tests import TestCase, TestCaseInTempDir
from bzrlib.transport import (_CoalescedOffset,
                              ConnectedTransport,
                              _get_protocol_handlers,
                              _set_protocol_handlers,
                              _get_transport_modules,
                              get_transport,
                              LateReadError,
                              register_lazy_transport,
                              register_transport_proto,
                              _clear_protocol_handlers,
                              Transport,
                              )
from bzrlib.transport.chroot import ChrootServer
from bzrlib.transport.memory import MemoryTransport
from bzrlib.transport.local import (LocalTransport,
                                    EmulatedWin32LocalTransport)


# TODO: Should possibly split transport-specific tests into their own files.


class TestTransport(TestCase):
    """Test the non transport-concrete class functionality."""

    def test__get_set_protocol_handlers(self):
        handlers = _get_protocol_handlers()
        self.assertNotEqual([], handlers.keys( ))
        try:
            _clear_protocol_handlers()
            self.assertEqual([], _get_protocol_handlers().keys())
        finally:
            _set_protocol_handlers(handlers)

    def test_get_transport_modules(self):
        handlers = _get_protocol_handlers()
        class SampleHandler(object):
            """I exist, isnt that enough?"""
        try:
            _clear_protocol_handlers()
            register_transport_proto('foo')
            register_lazy_transport('foo', 'bzrlib.tests.test_transport', 'TestTransport.SampleHandler')
            register_transport_proto('bar')
            register_lazy_transport('bar', 'bzrlib.tests.test_transport', 'TestTransport.SampleHandler')
            self.assertEqual([SampleHandler.__module__, 'bzrlib.transport.chroot'],
                             _get_transport_modules())
        finally:
            _set_protocol_handlers(handlers)

    def test_transport_dependency(self):
        """Transport with missing dependency causes no error"""
        saved_handlers = _get_protocol_handlers()
        try:
            register_transport_proto('foo')
            register_lazy_transport('foo', 'bzrlib.tests.test_transport',
                    'BadTransportHandler')
            try:
                get_transport('foo://fooserver/foo')
            except UnsupportedProtocol, e:
                e_str = str(e)
                self.assertEquals('Unsupported protocol'
                                  ' for url "foo://fooserver/foo":'
                                  ' Unable to import library "some_lib":'
                                  ' testing missing dependency', str(e))
            else:
                self.fail('Did not raise UnsupportedProtocol')
        finally:
            # restore original values
            _set_protocol_handlers(saved_handlers)
            
    def test_transport_fallback(self):
        """Transport with missing dependency causes no error"""
        saved_handlers = _get_protocol_handlers()
        try:
            _clear_protocol_handlers()
            register_transport_proto('foo')
            register_lazy_transport('foo', 'bzrlib.tests.test_transport',
                    'BackupTransportHandler')
            register_lazy_transport('foo', 'bzrlib.tests.test_transport',
                    'BadTransportHandler')
            t = get_transport('foo://fooserver/foo')
            self.assertTrue(isinstance(t, BackupTransportHandler))
        finally:
            _set_protocol_handlers(saved_handlers)

    def test_LateReadError(self):
        """The LateReadError helper should raise on read()."""
        a_file = LateReadError('a path')
        try:
            a_file.read()
        except ReadError, error:
            self.assertEqual('a path', error.path)
        self.assertRaises(ReadError, a_file.read, 40)
        a_file.close()

    def test__combine_paths(self):
        t = Transport('/')
        self.assertEqual('/home/sarah/project/foo',
                         t._combine_paths('/home/sarah', 'project/foo'))
        self.assertEqual('/etc',
                         t._combine_paths('/home/sarah', '../../etc'))
        self.assertEqual('/etc',
                         t._combine_paths('/home/sarah', '../../../etc'))
        self.assertEqual('/etc',
                         t._combine_paths('/home/sarah', '/etc'))

    def test_local_abspath_non_local_transport(self):
        # the base implementation should throw
        t = MemoryTransport()
        e = self.assertRaises(errors.NotLocalUrl, t.local_abspath, 't')
        self.assertEqual('memory:///t is not a local path.', str(e))


class TestCoalesceOffsets(TestCase):
    
    def check(self, expected, offsets, limit=0, fudge=0):
        coalesce = Transport._coalesce_offsets
        exp = [_CoalescedOffset(*x) for x in expected]
        out = list(coalesce(offsets, limit=limit, fudge_factor=fudge))
        self.assertEqual(exp, out)

    def test_coalesce_empty(self):
        self.check([], [])

    def test_coalesce_simple(self):
        self.check([(0, 10, [(0, 10)])], [(0, 10)])

    def test_coalesce_unrelated(self):
        self.check([(0, 10, [(0, 10)]),
                    (20, 10, [(0, 10)]),
                   ], [(0, 10), (20, 10)])
            
    def test_coalesce_unsorted(self):
        self.check([(20, 10, [(0, 10)]),
                    (0, 10, [(0, 10)]),
                   ], [(20, 10), (0, 10)])

    def test_coalesce_nearby(self):
        self.check([(0, 20, [(0, 10), (10, 10)])],
                   [(0, 10), (10, 10)])

    def test_coalesce_overlapped(self):
        self.check([(0, 15, [(0, 10), (5, 10)])],
                   [(0, 10), (5, 10)])

    def test_coalesce_limit(self):
        self.check([(10, 50, [(0, 10), (10, 10), (20, 10),
                              (30, 10), (40, 10)]),
                    (60, 50, [(0, 10), (10, 10), (20, 10),
                              (30, 10), (40, 10)]),
                   ], [(10, 10), (20, 10), (30, 10), (40, 10),
                       (50, 10), (60, 10), (70, 10), (80, 10),
                       (90, 10), (100, 10)],
                    limit=5)

    def test_coalesce_no_limit(self):
        self.check([(10, 100, [(0, 10), (10, 10), (20, 10),
                               (30, 10), (40, 10), (50, 10),
                               (60, 10), (70, 10), (80, 10),
                               (90, 10)]),
                   ], [(10, 10), (20, 10), (30, 10), (40, 10),
                       (50, 10), (60, 10), (70, 10), (80, 10),
                       (90, 10), (100, 10)])

    def test_coalesce_fudge(self):
        self.check([(10, 30, [(0, 10), (20, 10)]),
                    (100, 10, [(0, 10),]),
                   ], [(10, 10), (30, 10), (100, 10)],
                   fudge=10
                  )


class TestMemoryTransport(TestCase):

    def test_get_transport(self):
        MemoryTransport()

    def test_clone(self):
        transport = MemoryTransport()
        self.assertTrue(isinstance(transport, MemoryTransport))
        self.assertEqual("memory:///", transport.clone("/").base)

    def test_abspath(self):
        transport = MemoryTransport()
        self.assertEqual("memory:///relpath", transport.abspath('relpath'))

    def test_abspath_of_root(self):
        transport = MemoryTransport()
        self.assertEqual("memory:///", transport.base)
        self.assertEqual("memory:///", transport.abspath('/'))

    def test_abspath_of_relpath_starting_at_root(self):
        transport = MemoryTransport()
        self.assertEqual("memory:///foo", transport.abspath('/foo'))

    def test_append_and_get(self):
        transport = MemoryTransport()
        transport.append_bytes('path', 'content')
        self.assertEqual(transport.get('path').read(), 'content')
        transport.append_file('path', StringIO('content'))
        self.assertEqual(transport.get('path').read(), 'contentcontent')

    def test_put_and_get(self):
        transport = MemoryTransport()
        transport.put_file('path', StringIO('content'))
        self.assertEqual(transport.get('path').read(), 'content')
        transport.put_bytes('path', 'content')
        self.assertEqual(transport.get('path').read(), 'content')

    def test_append_without_dir_fails(self):
        transport = MemoryTransport()
        self.assertRaises(NoSuchFile,
                          transport.append_bytes, 'dir/path', 'content')

    def test_put_without_dir_fails(self):
        transport = MemoryTransport()
        self.assertRaises(NoSuchFile,
                          transport.put_file, 'dir/path', StringIO('content'))

    def test_get_missing(self):
        transport = MemoryTransport()
        self.assertRaises(NoSuchFile, transport.get, 'foo')

    def test_has_missing(self):
        transport = MemoryTransport()
        self.assertEquals(False, transport.has('foo'))

    def test_has_present(self):
        transport = MemoryTransport()
        transport.append_bytes('foo', 'content')
        self.assertEquals(True, transport.has('foo'))

    def test_list_dir(self):
        transport = MemoryTransport()
        transport.put_bytes('foo', 'content')
        transport.mkdir('dir')
        transport.put_bytes('dir/subfoo', 'content')
        transport.put_bytes('dirlike', 'content')

        self.assertEquals(['dir', 'dirlike', 'foo'], sorted(transport.list_dir('.')))
        self.assertEquals(['subfoo'], sorted(transport.list_dir('dir')))

    def test_mkdir(self):
        transport = MemoryTransport()
        transport.mkdir('dir')
        transport.append_bytes('dir/path', 'content')
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
        self.assertEqual(False, transport.is_readonly())

    def test_iter_files_recursive(self):
        transport = MemoryTransport()
        transport.mkdir('dir')
        transport.put_bytes('dir/foo', 'content')
        transport.put_bytes('dir/bar', 'content')
        transport.put_bytes('bar', 'content')
        paths = set(transport.iter_files_recursive())
        self.assertEqual(set(['dir/foo', 'dir/bar', 'bar']), paths)

    def test_stat(self):
        transport = MemoryTransport()
        transport.put_bytes('foo', 'content')
        transport.put_bytes('bar', 'phowar')
        self.assertEqual(7, transport.stat('foo').st_size)
        self.assertEqual(6, transport.stat('bar').st_size)


class ChrootDecoratorTransportTest(TestCase):
    """Chroot decoration specific tests."""

    def test_abspath(self):
        # The abspath is always relative to the chroot_url.
        server = ChrootServer(get_transport('memory:///foo/bar/'))
        server.setUp()
        transport = get_transport(server.get_url())
        self.assertEqual(server.get_url(), transport.abspath('/'))

        subdir_transport = transport.clone('subdir')
        self.assertEqual(server.get_url(), subdir_transport.abspath('/'))
        server.tearDown()

    def test_clone(self):
        server = ChrootServer(get_transport('memory:///foo/bar/'))
        server.setUp()
        transport = get_transport(server.get_url())
        # relpath from root and root path are the same
        relpath_cloned = transport.clone('foo')
        abspath_cloned = transport.clone('/foo')
        self.assertEqual(server, relpath_cloned.server)
        self.assertEqual(server, abspath_cloned.server)
        server.tearDown()
    
    def test_chroot_url_preserves_chroot(self):
        """Calling get_transport on a chroot transport's base should produce a
        transport with exactly the same behaviour as the original chroot
        transport.

        This is so that it is not possible to escape a chroot by doing::
            url = chroot_transport.base
            parent_url = urlutils.join(url, '..')
            new_transport = get_transport(parent_url)
        """
        server = ChrootServer(get_transport('memory:///path/subpath'))
        server.setUp()
        transport = get_transport(server.get_url())
        new_transport = get_transport(transport.base)
        self.assertEqual(transport.server, new_transport.server)
        self.assertEqual(transport.base, new_transport.base)
        server.tearDown()
        
    def test_urljoin_preserves_chroot(self):
        """Using urlutils.join(url, '..') on a chroot URL should not produce a
        URL that escapes the intended chroot.

        This is so that it is not possible to escape a chroot by doing::
            url = chroot_transport.base
            parent_url = urlutils.join(url, '..')
            new_transport = get_transport(parent_url)
        """
        server = ChrootServer(get_transport('memory:///path/'))
        server.setUp()
        transport = get_transport(server.get_url())
        self.assertRaises(
            InvalidURLJoin, urlutils.join, transport.base, '..')
        server.tearDown()


class ChrootServerTest(TestCase):

    def test_construct(self):
        backing_transport = MemoryTransport()
        server = ChrootServer(backing_transport)
        self.assertEqual(backing_transport, server.backing_transport)

    def test_setUp(self):
        backing_transport = MemoryTransport()
        server = ChrootServer(backing_transport)
        server.setUp()
        self.assertTrue(server.scheme in _get_protocol_handlers().keys())

    def test_tearDown(self):
        backing_transport = MemoryTransport()
        server = ChrootServer(backing_transport)
        server.setUp()
        server.tearDown()
        self.assertFalse(server.scheme in _get_protocol_handlers().keys())

    def test_get_url(self):
        backing_transport = MemoryTransport()
        server = ChrootServer(backing_transport)
        server.setUp()
        self.assertEqual('chroot-%d:///' % id(server), server.get_url())
        server.tearDown()


class ReadonlyDecoratorTransportTest(TestCase):
    """Readonly decoration specific tests."""

    def test_local_parameters(self):
        import bzrlib.transport.readonly as readonly
        # connect to . in readonly mode
        transport = readonly.ReadonlyTransportDecorator('readonly+.')
        self.assertEqual(True, transport.listable())
        self.assertEqual(True, transport.is_readonly())

    def test_http_parameters(self):
        from bzrlib.tests.HttpServer import HttpServer
        import bzrlib.transport.readonly as readonly
        # connect to . via http which is not listable
        server = HttpServer()
        server.setUp()
        try:
            transport = get_transport('readonly+' + server.get_url())
            self.failUnless(isinstance(transport,
                                       readonly.ReadonlyTransportDecorator))
            self.assertEqual(False, transport.listable())
            self.assertEqual(True, transport.is_readonly())
        finally:
            server.tearDown()


class FakeNFSDecoratorTests(TestCaseInTempDir):
    """NFS decorator specific tests."""

    def get_nfs_transport(self, url):
        import bzrlib.transport.fakenfs as fakenfs
        # connect to url with nfs decoration
        return fakenfs.FakeNFSTransportDecorator('fakenfs+' + url)

    def test_local_parameters(self):
        # the listable and is_readonly parameters
        # are not changed by the fakenfs decorator
        transport = self.get_nfs_transport('.')
        self.assertEqual(True, transport.listable())
        self.assertEqual(False, transport.is_readonly())

    def test_http_parameters(self):
        # the listable and is_readonly parameters
        # are not changed by the fakenfs decorator
        from bzrlib.tests.HttpServer import HttpServer
        # connect to . via http which is not listable
        server = HttpServer()
        server.setUp()
        try:
            transport = self.get_nfs_transport(server.get_url())
            self.assertIsInstance(
                transport, bzrlib.transport.fakenfs.FakeNFSTransportDecorator)
            self.assertEqual(False, transport.listable())
            self.assertEqual(True, transport.is_readonly())
        finally:
            server.tearDown()

    def test_fakenfs_server_default(self):
        # a FakeNFSServer() should bring up a local relpath server for itself
        import bzrlib.transport.fakenfs as fakenfs
        server = fakenfs.FakeNFSServer()
        server.setUp()
        try:
            # the url should be decorated appropriately
            self.assertStartsWith(server.get_url(), 'fakenfs+')
            # and we should be able to get a transport for it
            transport = get_transport(server.get_url())
            # which must be a FakeNFSTransportDecorator instance.
            self.assertIsInstance(
                transport, fakenfs.FakeNFSTransportDecorator)
        finally:
            server.tearDown()

    def test_fakenfs_rename_semantics(self):
        # a FakeNFS transport must mangle the way rename errors occur to
        # look like NFS problems.
        transport = self.get_nfs_transport('.')
        self.build_tree(['from/', 'from/foo', 'to/', 'to/bar'],
                        transport=transport)
        self.assertRaises(errors.ResourceBusy,
                          transport.rename, 'from', 'to')


class FakeVFATDecoratorTests(TestCaseInTempDir):
    """Tests for simulation of VFAT restrictions"""

    def get_vfat_transport(self, url):
        """Return vfat-backed transport for test directory"""
        from bzrlib.transport.fakevfat import FakeVFATTransportDecorator
        return FakeVFATTransportDecorator('vfat+' + url)

    def test_transport_creation(self):
        from bzrlib.transport.fakevfat import FakeVFATTransportDecorator
        transport = self.get_vfat_transport('.')
        self.assertIsInstance(transport, FakeVFATTransportDecorator)

    def test_transport_mkdir(self):
        transport = self.get_vfat_transport('.')
        transport.mkdir('HELLO')
        self.assertTrue(transport.has('hello'))
        self.assertTrue(transport.has('Hello'))

    def test_forbidden_chars(self):
        transport = self.get_vfat_transport('.')
        self.assertRaises(ValueError, transport.has, "<NU>")


class BadTransportHandler(Transport):
    def __init__(self, base_url):
        raise DependencyNotPresent('some_lib', 'testing missing dependency')


class BackupTransportHandler(Transport):
    """Test transport that works as a backup for the BadTransportHandler"""
    pass


class TestTransportImplementation(TestCaseInTempDir):
    """Implementation verification for transports.
    
    To verify a transport we need a server factory, which is a callable
    that accepts no parameters and returns an implementation of
    bzrlib.transport.Server.
    
    That Server is then used to construct transport instances and test
    the transport via loopback activity.

    Currently this assumes that the Transport object is connected to the 
    current working directory.  So that whatever is done 
    through the transport, should show up in the working 
    directory, and vice-versa. This is a bug, because its possible to have
    URL schemes which provide access to something that may not be 
    result in storage on the local disk, i.e. due to file system limits, or 
    due to it being a database or some other non-filesystem tool.

    This also tests to make sure that the functions work with both
    generators and lists (assuming iter(list) is effectively a generator)
    """
    
    def setUp(self):
        super(TestTransportImplementation, self).setUp()
        self._server = self.transport_server()
        self._server.setUp()
        self.addCleanup(self._server.tearDown)

    def get_transport(self, relpath=None):
        """Return a connected transport to the local directory.

        :param relpath: a path relative to the base url.
        """
        base_url = self._server.get_url()
        url = self._adjust_url(base_url, relpath)
        # try getting the transport via the regular interface:
        t = get_transport(url)
        # vila--20070607 if the following are commented out the test suite
        # still pass. Is this really still needed or was it a forgotten
        # temporary fix ?
        if not isinstance(t, self.transport_class):
            # we did not get the correct transport class type. Override the
            # regular connection behaviour by direct construction.
            t = self.transport_class(url)
        return t


class TestLocalTransports(TestCase):

    def test_get_transport_from_abspath(self):
        here = os.path.abspath('.')
        t = get_transport(here)
        self.assertIsInstance(t, LocalTransport)
        self.assertEquals(t.base, urlutils.local_path_to_url(here) + '/')

    def test_get_transport_from_relpath(self):
        here = os.path.abspath('.')
        t = get_transport('.')
        self.assertIsInstance(t, LocalTransport)
        self.assertEquals(t.base, urlutils.local_path_to_url('.') + '/')

    def test_get_transport_from_local_url(self):
        here = os.path.abspath('.')
        here_url = urlutils.local_path_to_url(here) + '/'
        t = get_transport(here_url)
        self.assertIsInstance(t, LocalTransport)
        self.assertEquals(t.base, here_url)

    def test_local_abspath(self):
        here = os.path.abspath('.')
        t = get_transport(here)
        self.assertEquals(t.local_abspath(''), here)


class TestWin32LocalTransport(TestCase):

    def test_unc_clone_to_root(self):
        # Win32 UNC path like \\HOST\path
        # clone to root should stop at least at \\HOST part
        # not on \\
        t = EmulatedWin32LocalTransport('file://HOST/path/to/some/dir/')
        for i in xrange(4):
            t = t.clone('..')
        self.assertEquals(t.base, 'file://HOST/')
        # make sure we reach the root
        t = t.clone('..')
        self.assertEquals(t.base, 'file://HOST/')


class TestConnectedTransport(TestCase):
    """Tests for connected to remote server transports"""

    def test_parse_url(self):
        t = ConnectedTransport('sftp://simple.example.com/home/source')
        self.assertEquals(t._host, 'simple.example.com')
        self.assertEquals(t._port, None)
        self.assertEquals(t._path, '/home/source/')
        self.failUnless(t._user is None)
        self.failUnless(t._password is None)

        self.assertEquals(t.base, 'sftp://simple.example.com/home/source/')

    def test_parse_quoted_url(self):
        t = ConnectedTransport('http://ro%62ey:h%40t@ex%41mple.com:2222/path')
        self.assertEquals(t._host, 'exAmple.com')
        self.assertEquals(t._port, 2222)
        self.assertEquals(t._user, 'robey')
        self.assertEquals(t._password, 'h@t')
        self.assertEquals(t._path, '/path/')

        # Base should not keep track of the password
        self.assertEquals(t.base, 'http://robey@exAmple.com:2222/path/')

    def test_parse_invalid_url(self):
        self.assertRaises(errors.InvalidURL,
                          ConnectedTransport,
                          'sftp://lily.org:~janneke/public/bzr/gub')

    def test_relpath(self):
        t = ConnectedTransport('sftp://user@host.com/abs/path')

        self.assertEquals(t.relpath('sftp://user@host.com/abs/path/sub'), 'sub')
        self.assertRaises(errors.PathNotChild, t.relpath,
                          'http://user@host.com/abs/path/sub')
        self.assertRaises(errors.PathNotChild, t.relpath,
                          'sftp://user2@host.com/abs/path/sub')
        self.assertRaises(errors.PathNotChild, t.relpath,
                          'sftp://user@otherhost.com/abs/path/sub')
        self.assertRaises(errors.PathNotChild, t.relpath,
                          'sftp://user@host.com:33/abs/path/sub')
        # Make sure it works when we don't supply a username
        t = ConnectedTransport('sftp://host.com/abs/path')
        self.assertEquals(t.relpath('sftp://host.com/abs/path/sub'), 'sub')

        # Make sure it works when parts of the path will be url encoded
        t = ConnectedTransport('sftp://host.com/dev/%path')
        self.assertEquals(t.relpath('sftp://host.com/dev/%path/sub'), 'sub')

    def test_connection_sharing_propagate_credentials(self):
        t = ConnectedTransport('foo://user@host.com/abs/path')
        self.assertIs(None, t._get_connection())
        self.assertIs(None, t._password)
        c = t.clone('subdir')
        self.assertEquals(None, c._get_connection())
        self.assertIs(None, t._password)

        # Simulate the user entering a password
        password = 'secret'
        connection = object()
        t._set_connection(connection, password)
        self.assertIs(connection, t._get_connection())
        self.assertIs(password, t._get_credentials())
        self.assertIs(connection, c._get_connection())
        self.assertIs(password, c._get_credentials())

        # credentials can be updated
        new_password = 'even more secret'
        c._update_credentials(new_password)
        self.assertIs(connection, t._get_connection())
        self.assertIs(new_password, t._get_credentials())
        self.assertIs(connection, c._get_connection())
        self.assertIs(new_password, c._get_credentials())


class TestReusedTransports(TestCase):
    """Tests for transport reuse"""

    def test_reuse_same_transport(self):
        possible_transports = []
        t1 = get_transport('http://foo/',
                           possible_transports=possible_transports)
        self.assertEqual([t1], possible_transports)
        t2 = get_transport('http://foo/', possible_transports=[t1])
        self.assertIs(t1, t2)

        # Also check that final '/' are handled correctly
        t3 = get_transport('http://foo/path/')
        t4 = get_transport('http://foo/path', possible_transports=[t3])
        self.assertIs(t3, t4)

        t5 = get_transport('http://foo/path')
        t6 = get_transport('http://foo/path/', possible_transports=[t5])
        self.assertIs(t5, t6)

    def test_don_t_reuse_different_transport(self):
        t1 = get_transport('http://foo/path')
        t2 = get_transport('http://bar/path', possible_transports=[t1])
        self.assertIsNot(t1, t2)


def get_test_permutations():
    """Return transport permutations to be used in testing.

    This module registers some transports, but they're only for testing
    registration.  We don't really want to run all the transport tests against
    them.
    """
    return []
