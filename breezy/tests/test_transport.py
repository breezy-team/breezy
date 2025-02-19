# Copyright (C) 2005-2011, 2015, 2016 Canonical Ltd
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


import errno
import os
import subprocess
import sys
import threading
from io import BytesIO

import breezy.transport.trace

from .. import errors, osutils, tests, transport, urlutils
from ..transport import (
    FileExists,
    NoSuchFile,
    UnsupportedProtocol,
    chroot,
    fakenfs,
    local,
    memory,
    pathfilter,
    readonly,
)
from . import features, test_server

# TODO: Should possibly split transport-specific tests into their own files.


class TestTransport(tests.TestCase):
    """Test the non transport-concrete class functionality."""

    def test__get_set_protocol_handlers(self):
        handlers = transport._get_protocol_handlers()
        self.assertNotEqual([], handlers.keys())
        transport._clear_protocol_handlers()
        self.addCleanup(transport._set_protocol_handlers, handlers)
        self.assertEqual([], transport._get_protocol_handlers().keys())

    def test_get_transport_modules(self):
        handlers = transport._get_protocol_handlers()
        self.addCleanup(transport._set_protocol_handlers, handlers)
        # don't pollute the current handlers
        transport._clear_protocol_handlers()

        class SampleHandler:
            """I exist, isnt that enough?"""

        transport._clear_protocol_handlers()
        transport.register_transport_proto("foo")
        transport.register_lazy_transport(
            "foo", "breezy.tests.test_transport", "TestTransport.SampleHandler"
        )
        transport.register_transport_proto("bar")
        transport.register_lazy_transport(
            "bar", "breezy.tests.test_transport", "TestTransport.SampleHandler"
        )
        self.assertEqual(
            [
                SampleHandler.__module__,
                "breezy.transport.chroot",
                "breezy.transport.pathfilter",
            ],
            transport._get_transport_modules(),
        )

    def test_transport_dependency(self):
        """Transport with missing dependency causes no error"""
        saved_handlers = transport._get_protocol_handlers()
        self.addCleanup(transport._set_protocol_handlers, saved_handlers)
        # don't pollute the current handlers
        transport._clear_protocol_handlers()
        transport.register_transport_proto("foo")
        transport.register_lazy_transport(
            "foo", "breezy.tests.test_transport", "BadTransportHandler"
        )
        try:
            transport.get_transport_from_url("foo://fooserver/foo")
        except UnsupportedProtocol as e:
            self.assertEqual(
                "Unsupported protocol"
                ' for url "foo://fooserver/foo":'
                ' Unable to import library "some_lib":'
                " testing missing dependency",
                str(e),
            )
        else:
            self.fail("Did not raise UnsupportedProtocol")

    def test_transport_fallback(self):
        """Transport with missing dependency causes no error"""
        saved_handlers = transport._get_protocol_handlers()
        self.addCleanup(transport._set_protocol_handlers, saved_handlers)
        transport._clear_protocol_handlers()
        transport.register_transport_proto("foo")
        transport.register_lazy_transport(
            "foo", "breezy.tests.test_transport", "BackupTransportHandler"
        )
        transport.register_lazy_transport(
            "foo", "breezy.tests.test_transport", "BadTransportHandler"
        )
        t = transport.get_transport_from_url("foo://fooserver/foo")
        self.assertTrue(isinstance(t, BackupTransportHandler))

    def test_ssh_hints(self):
        """Transport ssh:// should raise an error pointing out bzr+ssh://"""
        try:
            transport.get_transport_from_url("ssh://fooserver/foo")
        except UnsupportedProtocol as e:
            self.assertEqual(
                "Unsupported protocol"
                ' for url "ssh://fooserver/foo":'
                " Use bzr+ssh for Bazaar operations over SSH, "
                'e.g. "bzr+ssh://fooserver/foo". Use git+ssh '
                'for Git operations over SSH, e.g. "git+ssh://fooserver/foo".',
                str(e),
            )
        else:
            self.fail("Did not raise UnsupportedProtocol")

    def test_LateReadError(self):
        """The LateReadError helper should raise on read()."""
        a_file = transport.LateReadError("a path")
        try:
            a_file.read()
        except errors.ReadError as error:
            self.assertEqual("a path", error.path)
        self.assertRaises(errors.ReadError, a_file.read, 40)
        a_file.close()

    def test_local_abspath_non_local_transport(self):
        # the base implementation should throw
        t = memory.MemoryTransport()
        e = self.assertRaises(errors.NotLocalUrl, t.local_abspath, "t")
        self.assertEqual("memory:///t is not a local path.", str(e))


class TestCoalesceOffsets(tests.TestCase):
    def check(self, expected, offsets, limit=0, max_size=0, fudge=0):
        coalesce = transport.Transport._coalesce_offsets
        exp = [transport._CoalescedOffset(*x) for x in expected]
        out = list(
            coalesce(offsets, limit=limit, fudge_factor=fudge, max_size=max_size)
        )
        self.assertEqual(exp, out)

    def test_coalesce_empty(self):
        self.check([], [])

    def test_coalesce_simple(self):
        self.check([(0, 10, [(0, 10)])], [(0, 10)])

    def test_coalesce_unrelated(self):
        self.check(
            [
                (0, 10, [(0, 10)]),
                (20, 10, [(0, 10)]),
            ],
            [(0, 10), (20, 10)],
        )

    def test_coalesce_unsorted(self):
        self.check(
            [
                (20, 10, [(0, 10)]),
                (0, 10, [(0, 10)]),
            ],
            [(20, 10), (0, 10)],
        )

    def test_coalesce_nearby(self):
        self.check([(0, 20, [(0, 10), (10, 10)])], [(0, 10), (10, 10)])

    def test_coalesce_overlapped(self):
        self.assertRaises(
            ValueError, self.check, [(0, 15, [(0, 10), (5, 10)])], [(0, 10), (5, 10)]
        )

    def test_coalesce_limit(self):
        self.check(
            [
                (10, 50, [(0, 10), (10, 10), (20, 10), (30, 10), (40, 10)]),
                (60, 50, [(0, 10), (10, 10), (20, 10), (30, 10), (40, 10)]),
            ],
            [
                (10, 10),
                (20, 10),
                (30, 10),
                (40, 10),
                (50, 10),
                (60, 10),
                (70, 10),
                (80, 10),
                (90, 10),
                (100, 10),
            ],
            limit=5,
        )

    def test_coalesce_no_limit(self):
        self.check(
            [
                (
                    10,
                    100,
                    [
                        (0, 10),
                        (10, 10),
                        (20, 10),
                        (30, 10),
                        (40, 10),
                        (50, 10),
                        (60, 10),
                        (70, 10),
                        (80, 10),
                        (90, 10),
                    ],
                ),
            ],
            [
                (10, 10),
                (20, 10),
                (30, 10),
                (40, 10),
                (50, 10),
                (60, 10),
                (70, 10),
                (80, 10),
                (90, 10),
                (100, 10),
            ],
        )

    def test_coalesce_fudge(self):
        self.check(
            [
                (10, 30, [(0, 10), (20, 10)]),
                (100, 10, [(0, 10)]),
            ],
            [(10, 10), (30, 10), (100, 10)],
            fudge=10,
        )

    def test_coalesce_max_size(self):
        self.check(
            [
                (10, 20, [(0, 10), (10, 10)]),
                (30, 50, [(0, 50)]),
                # If one range is above max_size, it gets its own coalesced
                # offset
                (100, 80, [(0, 80)]),
            ],
            [(10, 10), (20, 10), (30, 50), (100, 80)],
            max_size=50,
        )

    def test_coalesce_no_max_size(self):
        self.check(
            [(10, 170, [(0, 10), (10, 10), (20, 50), (70, 100)])],
            [(10, 10), (20, 10), (30, 50), (80, 100)],
        )

    def test_coalesce_default_limit(self):
        # By default we use a 100MB max size.
        ten_mb = 10 * 1024 * 1024
        self.check(
            [
                (0, 10 * ten_mb, [(i * ten_mb, ten_mb) for i in range(10)]),
                (10 * ten_mb, ten_mb, [(0, ten_mb)]),
            ],
            [(i * ten_mb, ten_mb) for i in range(11)],
        )
        self.check(
            [(0, 11 * ten_mb, [(i * ten_mb, ten_mb) for i in range(11)])],
            [(i * ten_mb, ten_mb) for i in range(11)],
            max_size=1 * 1024 * 1024 * 1024,
        )


class TestMemoryServer(tests.TestCase):
    def test_create_server(self):
        server = memory.MemoryServer()
        server.start_server()
        url = server.get_url()
        self.assertTrue(url in transport.transport_list_registry)
        t = transport.get_transport_from_url(url)
        del t
        server.stop_server()
        self.assertFalse(url in transport.transport_list_registry)
        self.assertRaises(UnsupportedProtocol, transport.get_transport, url)


class TestMemoryTransport(tests.TestCase):
    def test_get_transport(self):
        memory.MemoryTransport()

    def test_clone(self):
        t = memory.MemoryTransport()
        self.assertTrue(isinstance(t, memory.MemoryTransport))
        self.assertEqual("memory:///", t.clone("/").base)

    def test_abspath(self):
        t = memory.MemoryTransport()
        self.assertEqual("memory:///relpath", t.abspath("relpath"))

    def test_abspath_of_root(self):
        t = memory.MemoryTransport()
        self.assertEqual("memory:///", t.base)
        self.assertEqual("memory:///", t.abspath("/"))

    def test_abspath_of_relpath_starting_at_root(self):
        t = memory.MemoryTransport()
        self.assertEqual("memory:///foo", t.abspath("/foo"))

    def test_append_and_get(self):
        t = memory.MemoryTransport()
        t.append_bytes("path", b"content")
        self.assertEqual(t.get("path").read(), b"content")
        t.append_file("path", BytesIO(b"content"))
        with t.get("path") as f:
            self.assertEqual(f.read(), b"contentcontent")

    def test_put_and_get(self):
        t = memory.MemoryTransport()
        t.put_file("path", BytesIO(b"content"))
        self.assertEqual(t.get("path").read(), b"content")
        t.put_bytes("path", b"content")
        self.assertEqual(t.get("path").read(), b"content")

    def test_append_without_dir_fails(self):
        t = memory.MemoryTransport()
        self.assertRaises(NoSuchFile, t.append_bytes, "dir/path", b"content")

    def test_put_without_dir_fails(self):
        t = memory.MemoryTransport()
        self.assertRaises(NoSuchFile, t.put_file, "dir/path", BytesIO(b"content"))

    def test_get_missing(self):
        transport = memory.MemoryTransport()
        self.assertRaises(NoSuchFile, transport.get, "foo")

    def test_has_missing(self):
        t = memory.MemoryTransport()
        self.assertEqual(False, t.has("foo"))

    def test_has_present(self):
        t = memory.MemoryTransport()
        t.append_bytes("foo", b"content")
        self.assertEqual(True, t.has("foo"))

    def test_list_dir(self):
        t = memory.MemoryTransport()
        t.put_bytes("foo", b"content")
        t.mkdir("dir")
        t.put_bytes("dir/subfoo", b"content")
        t.put_bytes("dirlike", b"content")

        self.assertEqual(["dir", "dirlike", "foo"], sorted(t.list_dir(".")))
        self.assertEqual(["subfoo"], sorted(t.list_dir("dir")))

    def test_mkdir(self):
        t = memory.MemoryTransport()
        t.mkdir("dir")
        t.append_bytes("dir/path", b"content")
        with t.get("dir/path") as f:
            self.assertEqual(f.read(), b"content")

    def test_mkdir_missing_parent(self):
        t = memory.MemoryTransport()
        self.assertRaises(NoSuchFile, t.mkdir, "dir/dir")

    def test_mkdir_twice(self):
        t = memory.MemoryTransport()
        t.mkdir("dir")
        self.assertRaises(FileExists, t.mkdir, "dir")

    def test_parameters(self):
        t = memory.MemoryTransport()
        self.assertEqual(True, t.listable())
        self.assertEqual(False, t.is_readonly())

    def test_iter_files_recursive(self):
        t = memory.MemoryTransport()
        t.mkdir("dir")
        t.put_bytes("dir/foo", b"content")
        t.put_bytes("dir/bar", b"content")
        t.put_bytes("bar", b"content")
        paths = set(t.iter_files_recursive())
        self.assertEqual({"dir/foo", "dir/bar", "bar"}, paths)

    def test_stat(self):
        t = memory.MemoryTransport()
        t.put_bytes("foo", b"content")
        t.put_bytes("bar", b"phowar")
        self.assertEqual(7, t.stat("foo").st_size)
        self.assertEqual(6, t.stat("bar").st_size)


class ChrootDecoratorTransportTest(tests.TestCase):
    """Chroot decoration specific tests."""

    def test_abspath(self):
        # The abspath is always relative to the chroot_url.
        server = chroot.ChrootServer(
            transport.get_transport_from_url("memory:///foo/bar/")
        )
        self.start_server(server)
        t = transport.get_transport_from_url(server.get_url())
        self.assertEqual(server.get_url(), t.abspath("/"))

        subdir_t = t.clone("subdir")
        self.assertEqual(server.get_url(), subdir_t.abspath("/"))

    def test_clone(self):
        server = chroot.ChrootServer(
            transport.get_transport_from_url("memory:///foo/bar/")
        )
        self.start_server(server)
        t = transport.get_transport_from_url(server.get_url())
        # relpath from root and root path are the same
        relpath_cloned = t.clone("foo")
        abspath_cloned = t.clone("/foo")
        self.assertEqual(server, relpath_cloned.server)
        self.assertEqual(server, abspath_cloned.server)

    def test_chroot_url_preserves_chroot(self):
        """Calling get_transport on a chroot transport's base should produce a
        transport with exactly the same behaviour as the original chroot
        transport.

        This is so that it is not possible to escape a chroot by doing::
            url = chroot_transport.base
            parent_url = urlutils.join(url, '..')
            new_t = transport.get_transport_from_url(parent_url)
        """
        server = chroot.ChrootServer(
            transport.get_transport_from_url("memory:///path/subpath")
        )
        self.start_server(server)
        t = transport.get_transport_from_url(server.get_url())
        new_t = transport.get_transport_from_url(t.base)
        self.assertEqual(t.server, new_t.server)
        self.assertEqual(t.base, new_t.base)

    def test_urljoin_preserves_chroot(self):
        """Using urlutils.join(url, '..') on a chroot URL should not produce a
        URL that escapes the intended chroot.

        This is so that it is not possible to escape a chroot by doing::
            url = chroot_transport.base
            parent_url = urlutils.join(url, '..')
            new_t = transport.get_transport_from_url(parent_url)
        """
        server = chroot.ChrootServer(
            transport.get_transport_from_url("memory:///path/")
        )
        self.start_server(server)
        t = transport.get_transport_from_url(server.get_url())
        self.assertRaises(urlutils.InvalidURLJoin, urlutils.join, t.base, "..")


class TestChrootServer(tests.TestCase):
    def test_construct(self):
        backing_transport = memory.MemoryTransport()
        server = chroot.ChrootServer(backing_transport)
        self.assertEqual(backing_transport, server.backing_transport)

    def test_setUp(self):
        backing_transport = memory.MemoryTransport()
        server = chroot.ChrootServer(backing_transport)
        server.start_server()
        self.addCleanup(server.stop_server)
        self.assertTrue(server.scheme in transport._get_protocol_handlers().keys())

    def test_stop_server(self):
        backing_transport = memory.MemoryTransport()
        server = chroot.ChrootServer(backing_transport)
        server.start_server()
        server.stop_server()
        self.assertFalse(server.scheme in transport._get_protocol_handlers().keys())

    def test_get_url(self):
        backing_transport = memory.MemoryTransport()
        server = chroot.ChrootServer(backing_transport)
        server.start_server()
        self.addCleanup(server.stop_server)
        self.assertEqual("chroot-%d:///" % id(server), server.get_url())


class TestHooks(tests.TestCase):
    """Basic tests for transport hooks"""

    def _get_connected_transport(self):
        return transport.ConnectedTransport("bogus:nowhere")

    def test_transporthooks_initialisation(self):
        """Check all expected transport hook points are set up"""
        hookpoint = transport.TransportHooks()
        self.assertTrue(
            "post_connect" in hookpoint, "post_connect not in {}".format(hookpoint)
        )

    def test_post_connect(self):
        """Ensure the post_connect hook is called when _set_transport is"""
        calls = []
        transport.Transport.hooks.install_named_hook("post_connect", calls.append, None)
        t = self._get_connected_transport()
        self.assertLength(0, calls)
        t._set_connection("connection", "auth")
        self.assertEqual(calls, [t])


class PathFilteringDecoratorTransportTest(tests.TestCase):
    """Pathfilter decoration specific tests."""

    def test_abspath(self):
        # The abspath is always relative to the base of the backing transport.
        server = pathfilter.PathFilteringServer(
            transport.get_transport_from_url("memory:///foo/bar/"), lambda x: x
        )
        server.start_server()
        t = transport.get_transport_from_url(server.get_url())
        self.assertEqual(server.get_url(), t.abspath("/"))

        subdir_t = t.clone("subdir")
        self.assertEqual(server.get_url(), subdir_t.abspath("/"))
        server.stop_server()

    def make_pf_transport(self, filter_func=None):
        """Make a PathFilteringTransport backed by a MemoryTransport.

        :param filter_func: by default this will be a no-op function.  Use this
            parameter to override it.
        """
        if filter_func is None:

            def filter_func(x):
                return x

        server = pathfilter.PathFilteringServer(
            transport.get_transport_from_url("memory:///foo/bar/"), filter_func
        )
        server.start_server()
        self.addCleanup(server.stop_server)
        return transport.get_transport_from_url(server.get_url())

    def test__filter(self):
        # _filter (with an identity func as filter_func) always returns
        # paths relative to the base of the backing transport.
        t = self.make_pf_transport()
        self.assertEqual("foo", t._filter("foo"))
        self.assertEqual("foo/bar", t._filter("foo/bar"))
        self.assertEqual("", t._filter(".."))
        self.assertEqual("", t._filter("/"))
        # The base of the pathfiltering transport is taken into account too.
        t = t.clone("subdir1/subdir2")
        self.assertEqual("subdir1/subdir2/foo", t._filter("foo"))
        self.assertEqual("subdir1/subdir2/foo/bar", t._filter("foo/bar"))
        self.assertEqual("subdir1", t._filter(".."))
        self.assertEqual("", t._filter("/"))

    def test_filter_invocation(self):
        filter_log = []

        def filter(path):
            filter_log.append(path)
            return path

        t = self.make_pf_transport(filter)
        t.has("abc")
        self.assertEqual(["abc"], filter_log)
        del filter_log[:]
        t.clone("abc").has("xyz")
        self.assertEqual(["abc/xyz"], filter_log)
        del filter_log[:]
        t.has("/abc")
        self.assertEqual(["abc"], filter_log)

    def test_clone(self):
        t = self.make_pf_transport()
        # relpath from root and root path are the same
        relpath_cloned = t.clone("foo")
        abspath_cloned = t.clone("/foo")
        self.assertEqual(t.server, relpath_cloned.server)
        self.assertEqual(t.server, abspath_cloned.server)

    def test_url_preserves_pathfiltering(self):
        """Calling get_transport on a pathfiltered transport's base should
        produce a transport with exactly the same behaviour as the original
        pathfiltered transport.

        This is so that it is not possible to escape (accidentally or
        otherwise) the filtering by doing::
            url = filtered_transport.base
            parent_url = urlutils.join(url, '..')
            new_t = transport.get_transport_from_url(parent_url)
        """
        t = self.make_pf_transport()
        new_t = transport.get_transport_from_url(t.base)
        self.assertEqual(t.server, new_t.server)
        self.assertEqual(t.base, new_t.base)


class ReadonlyDecoratorTransportTest(tests.TestCase):
    """Readonly decoration specific tests."""

    def test_local_parameters(self):
        # connect to . in readonly mode
        t = readonly.ReadonlyTransportDecorator("readonly+.")
        self.assertEqual(True, t.listable())
        self.assertEqual(True, t.is_readonly())

    def test_http_parameters(self):
        from breezy.tests.http_server import HttpServer

        # connect to '.' via http which is not listable
        server = HttpServer()
        self.start_server(server)
        t = transport.get_transport_from_url("readonly+" + server.get_url())
        self.assertIsInstance(t, readonly.ReadonlyTransportDecorator)
        self.assertEqual(False, t.listable())
        self.assertEqual(True, t.is_readonly())


class FakeNFSDecoratorTests(tests.TestCaseInTempDir):
    """NFS decorator specific tests."""

    def get_nfs_transport(self, url):
        # connect to url with nfs decoration
        return fakenfs.FakeNFSTransportDecorator("fakenfs+" + url)

    def test_local_parameters(self):
        # the listable and is_readonly parameters
        # are not changed by the fakenfs decorator
        t = self.get_nfs_transport(".")
        self.assertEqual(True, t.listable())
        self.assertEqual(False, t.is_readonly())

    def test_http_parameters(self):
        # the listable and is_readonly parameters
        # are not changed by the fakenfs decorator
        from breezy.tests.http_server import HttpServer

        # connect to '.' via http which is not listable
        server = HttpServer()
        self.start_server(server)
        t = self.get_nfs_transport(server.get_url())
        self.assertIsInstance(t, fakenfs.FakeNFSTransportDecorator)
        self.assertEqual(False, t.listable())
        self.assertEqual(True, t.is_readonly())

    def test_fakenfs_server_default(self):
        # a FakeNFSServer() should bring up a local relpath server for itself
        server = test_server.FakeNFSServer()
        self.start_server(server)
        # the url should be decorated appropriately
        self.assertStartsWith(server.get_url(), "fakenfs+")
        # and we should be able to get a transport for it
        t = transport.get_transport_from_url(server.get_url())
        # which must be a FakeNFSTransportDecorator instance.
        self.assertIsInstance(t, fakenfs.FakeNFSTransportDecorator)

    def test_fakenfs_rename_semantics(self):
        # a FakeNFS transport must mangle the way rename errors occur to
        # look like NFS problems.
        t = self.get_nfs_transport(".")
        self.build_tree(["from/", "from/foo", "to/", "to/bar"], transport=t)
        self.assertRaises(errors.ResourceBusy, t.rename, "from", "to")


class FakeVFATDecoratorTests(tests.TestCaseInTempDir):
    """Tests for simulation of VFAT restrictions"""

    def get_vfat_transport(self, url):
        """Return vfat-backed transport for test directory"""
        from breezy.transport.fakevfat import FakeVFATTransportDecorator

        return FakeVFATTransportDecorator("vfat+" + url)

    def test_transport_creation(self):
        from breezy.transport.fakevfat import FakeVFATTransportDecorator

        t = self.get_vfat_transport(".")
        self.assertIsInstance(t, FakeVFATTransportDecorator)

    def test_transport_mkdir(self):
        t = self.get_vfat_transport(".")
        t.mkdir("HELLO")
        self.assertTrue(t.has("hello"))
        self.assertTrue(t.has("Hello"))

    def test_forbidden_chars(self):
        t = self.get_vfat_transport(".")
        self.assertRaises(ValueError, t.has, "<NU>")


class BadTransportHandler(transport.Transport):
    def __init__(self, base_url):
        raise errors.DependencyNotPresent("some_lib", "testing missing dependency")


class BackupTransportHandler(transport.Transport):
    """Test transport that works as a backup for the BadTransportHandler"""

    pass


class TestTransportImplementation(tests.TestCaseInTempDir):
    """Implementation verification for transports.

    To verify a transport we need a server factory, which is a callable
    that accepts no parameters and returns an implementation of
    breezy.transport.Server.

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
        super().setUp()
        self._server = self.transport_server()
        self.start_server(self._server)

    def get_transport(self, relpath=None):
        """Return a connected transport to the local directory.

        :param relpath: a path relative to the base url.
        """
        base_url = self._server.get_url()
        url = self._adjust_url(base_url, relpath)
        # try getting the transport via the regular interface:
        t = transport.get_transport_from_url(url)
        # vila--20070607 if the following are commented out the test suite
        # still pass. Is this really still needed or was it a forgotten
        # temporary fix ?
        if not isinstance(t, self.transport_class):
            # we did not get the correct transport class type. Override the
            # regular connection behaviour by direct construction.
            t = self.transport_class(url)
        return t


class TestTransportFromPath(tests.TestCaseInTempDir):
    def test_with_path(self):
        t = transport.get_transport_from_path(self.test_dir)
        self.assertIsInstance(t, local.LocalTransport)
        self.assertEqual(t.base.rstrip("/"), urlutils.local_path_to_url(self.test_dir))

    def test_with_url(self):
        t = transport.get_transport_from_path("file:")
        self.assertIsInstance(t, local.LocalTransport)
        self.assertEqual(
            t.base.rstrip("/"),
            urlutils.local_path_to_url(os.path.join(self.test_dir, "file:")),
        )


class TestTransportFromUrl(tests.TestCaseInTempDir):
    def test_with_path(self):
        self.assertRaises(
            urlutils.InvalidURL, transport.get_transport_from_url, self.test_dir
        )

    def test_with_url(self):
        url = urlutils.local_path_to_url(self.test_dir)
        t = transport.get_transport_from_url(url)
        self.assertIsInstance(t, local.LocalTransport)
        self.assertEqual(t.base.rstrip("/"), url)

    def test_with_url_and_segment_parameters(self):
        url = urlutils.local_path_to_url(self.test_dir) + ",branch=foo"
        t = transport.get_transport_from_url(url)
        self.assertIsInstance(t, local.LocalTransport)
        self.assertEqual(t.base.rstrip("/"), url)
        with open(os.path.join(self.test_dir, "afile"), "w") as f:
            f.write("data")
        self.assertTrue(t.has("afile"))


class TestLocalTransports(tests.TestCase):
    def test_get_transport_from_abspath(self):
        here = osutils.abspath(".")
        t = transport.get_transport(here)
        self.assertIsInstance(t, local.LocalTransport)
        self.assertEqual(t.base, urlutils.local_path_to_url(here) + "/")

    def test_get_transport_from_relpath(self):
        t = transport.get_transport(".")
        self.assertIsInstance(t, local.LocalTransport)
        self.assertEqual(t.base, urlutils.local_path_to_url(".") + "/")

    def test_get_transport_from_local_url(self):
        here = osutils.abspath(".")
        here_url = urlutils.local_path_to_url(here) + "/"
        t = transport.get_transport(here_url)
        self.assertIsInstance(t, local.LocalTransport)
        self.assertEqual(t.base, here_url)

    def test_local_abspath(self):
        here = osutils.abspath(".")
        t = transport.get_transport(here)
        self.assertEqual(t.local_abspath(""), here)


class TestLocalTransportMutation(tests.TestCaseInTempDir):
    def test_local_transport_mkdir(self):
        here = osutils.abspath(".")
        t = transport.get_transport(here)
        t.mkdir("test")
        self.assertTrue(os.path.exists("test"))

    def test_local_transport_mkdir_permission_denied(self):
        # See https://bugs.launchpad.net/bzr/+bug/606537
        here = osutils.abspath(".")
        t = transport.get_transport(here)

        def fake_chmod(path, mode):
            e = OSError("permission denied")
            e.errno = errno.EPERM
            raise e

        self.overrideAttr(os, "chmod", fake_chmod)
        t.mkdir("test")
        t.mkdir("test2", mode=0o707)
        self.assertTrue(os.path.exists("test"))
        self.assertTrue(os.path.exists("test2"))


class TestLocalTransportWriteStream(tests.TestCaseWithTransport):
    def test_local_fdatasync_calls_fdatasync(self):
        """Check fdatasync on a stream tries to flush the data to the OS.

        We can't easily observe the external effect but we can at least see
        it's called.
        """
        sentinel = object()
        fdatasync = getattr(os, "fdatasync", sentinel)
        if fdatasync is sentinel:
            raise tests.TestNotApplicable("fdatasync not supported")
        t = self.get_transport(".")
        calls = self.recordCalls(os, "fdatasync")
        w = t.open_write_stream("out")
        w.write(b"foo")
        w.fdatasync()
        with open("out", "rb") as f:
            # Should have been flushed.
            self.assertEqual(f.read(), b"foo")
        self.assertEqual(len(calls), 1, calls)

    def test_missing_directory(self):
        t = self.get_transport(".")
        self.assertRaises(NoSuchFile, t.open_write_stream, "dir/foo")


class TestWin32LocalTransport(tests.TestCase):
    def test_unc_clone_to_root(self):
        self.requireFeature(features.win32_feature)
        # Win32 UNC path like \\HOST\path
        # clone to root should stop at least at \\HOST part
        # not on \\
        t = local.EmulatedWin32LocalTransport("file://HOST/path/to/some/dir/")
        for i in range(4):
            t = t.clone("..")
        self.assertEqual(t.base, "file://HOST/")
        # make sure we reach the root
        t = t.clone("..")
        self.assertEqual(t.base, "file://HOST/")


class TestConnectedTransport(tests.TestCase):
    """Tests for connected to remote server transports"""

    def test_parse_url(self):
        t = transport.ConnectedTransport("http://simple.example.com/home/source")
        self.assertEqual(t._parsed_url.host, "simple.example.com")
        self.assertEqual(t._parsed_url.port, None)
        self.assertEqual(t._parsed_url.path, "/home/source/")
        self.assertTrue(t._parsed_url.user is None)
        self.assertTrue(t._parsed_url.password is None)

        self.assertEqual(t.base, "http://simple.example.com/home/source/")

    def test_parse_url_with_at_in_user(self):
        # Bug 228058
        t = transport.ConnectedTransport("ftp://user@host.com@www.host.com/")
        self.assertEqual(t._parsed_url.user, "user@host.com")

    def test_parse_quoted_url(self):
        t = transport.ConnectedTransport("http://ro%62ey:h%40t@ex%41mple.com:2222/path")
        self.assertEqual(t._parsed_url.host, "exAmple.com")
        self.assertEqual(t._parsed_url.port, 2222)
        self.assertEqual(t._parsed_url.user, "robey")
        self.assertEqual(t._parsed_url.password, "h@t")
        self.assertEqual(t._parsed_url.path, "/path/")

        # Base should not keep track of the password
        self.assertEqual(t.base, "http://ro%62ey@ex%41mple.com:2222/path/")

    def test_parse_invalid_url(self):
        self.assertRaises(
            urlutils.InvalidURL,
            transport.ConnectedTransport,
            "sftp://lily.org:~janneke/public/bzr/gub",
        )

    def test_relpath(self):
        t = transport.ConnectedTransport("sftp://user@host.com/abs/path")

        self.assertEqual(t.relpath("sftp://user@host.com/abs/path/sub"), "sub")
        self.assertRaises(
            errors.PathNotChild, t.relpath, "http://user@host.com/abs/path/sub"
        )
        self.assertRaises(
            errors.PathNotChild, t.relpath, "sftp://user2@host.com/abs/path/sub"
        )
        self.assertRaises(
            errors.PathNotChild, t.relpath, "sftp://user@otherhost.com/abs/path/sub"
        )
        self.assertRaises(
            errors.PathNotChild, t.relpath, "sftp://user@host.com:33/abs/path/sub"
        )
        # Make sure it works when we don't supply a username
        t = transport.ConnectedTransport("sftp://host.com/abs/path")
        self.assertEqual(t.relpath("sftp://host.com/abs/path/sub"), "sub")

        # Make sure it works when parts of the path will be url encoded
        t = transport.ConnectedTransport("sftp://host.com/dev/%path")
        self.assertEqual(t.relpath("sftp://host.com/dev/%path/sub"), "sub")

    def test_connection_sharing_propagate_credentials(self):
        t = transport.ConnectedTransport("ftp://user@host.com/abs/path")
        self.assertEqual("user", t._parsed_url.user)
        self.assertEqual("host.com", t._parsed_url.host)
        self.assertIs(None, t._get_connection())
        self.assertIs(None, t._parsed_url.password)
        c = t.clone("subdir")
        self.assertIs(None, c._get_connection())
        self.assertIs(None, t._parsed_url.password)

        # Simulate the user entering a password
        password = "secret"
        connection = object()
        t._set_connection(connection, password)
        self.assertIs(connection, t._get_connection())
        self.assertIs(password, t._get_credentials())
        self.assertIs(connection, c._get_connection())
        self.assertIs(password, c._get_credentials())

        # credentials can be updated
        new_password = "even more secret"
        c._update_credentials(new_password)
        self.assertIs(connection, t._get_connection())
        self.assertIs(new_password, t._get_credentials())
        self.assertIs(connection, c._get_connection())
        self.assertIs(new_password, c._get_credentials())


class TestReusedTransports(tests.TestCase):
    """Tests for transport reuse"""

    def test_reuse_same_transport(self):
        possible_transports = []
        t1 = transport.get_transport_from_url(
            "http://foo/", possible_transports=possible_transports
        )
        self.assertEqual([t1], possible_transports)
        t2 = transport.get_transport_from_url("http://foo/", possible_transports=[t1])
        self.assertIs(t1, t2)

        # Also check that final '/' are handled correctly
        t3 = transport.get_transport_from_url("http://foo/path/")
        t4 = transport.get_transport_from_url(
            "http://foo/path", possible_transports=[t3]
        )
        self.assertIs(t3, t4)

        t5 = transport.get_transport_from_url("http://foo/path")
        t6 = transport.get_transport_from_url(
            "http://foo/path/", possible_transports=[t5]
        )
        self.assertIs(t5, t6)

    def test_don_t_reuse_different_transport(self):
        t1 = transport.get_transport_from_url("http://foo/path")
        t2 = transport.get_transport_from_url(
            "http://bar/path", possible_transports=[t1]
        )
        self.assertIsNot(t1, t2)


class TestTransportTrace(tests.TestCase):
    def test_decorator(self):
        t = transport.get_transport_from_url("trace+memory://")
        self.assertIsInstance(t, breezy.transport.trace.TransportTraceDecorator)

    def test_clone_preserves_activity(self):
        t = transport.get_transport_from_url("trace+memory://")
        t2 = t.clone(".")
        self.assertTrue(t is not t2)
        self.assertTrue(t._activity is t2._activity)

    # the following specific tests are for the operations that have made use of
    # logging in tests; we could test every single operation but doing that
    # still won't cause a test failure when the top level Transport API
    # changes; so there is little return doing that.
    def test_get(self):
        t = transport.get_transport_from_url("trace+memory:///")
        t.put_bytes("foo", b"barish")
        t.get("foo")
        expected_result = []
        # put_bytes records the bytes, not the content to avoid memory
        # pressure.
        expected_result.append(("put_bytes", "foo", 6, None))
        # get records the file name only.
        expected_result.append(("get", "foo"))
        self.assertEqual(expected_result, t._activity)

    def test_readv(self):
        t = transport.get_transport_from_url("trace+memory:///")
        t.put_bytes("foo", b"barish")
        list(t.readv("foo", [(0, 1), (3, 2)], adjust_for_latency=True, upper_limit=6))
        expected_result = []
        # put_bytes records the bytes, not the content to avoid memory
        # pressure.
        expected_result.append(("put_bytes", "foo", 6, None))
        # readv records the supplied offset request
        expected_result.append(("readv", "foo", [(0, 1), (3, 2)], True, 6))
        self.assertEqual(expected_result, t._activity)


class TestSSHConnections(tests.TestCaseWithTransport):
    def test_bzr_connect_to_bzr_ssh(self):
        """get_transport of a bzr+ssh:// behaves correctly.

        bzr+ssh:// should cause bzr to run a remote bzr smart server over SSH.
        """
        # This test actually causes a bzr instance to be invoked, which is very
        # expensive: it should be the only such test in the test suite.
        # A reasonable evolution for this would be to simply check inside
        # check_channel_exec_request that the command is appropriate, and then
        # satisfy requests in-process.
        self.requireFeature(features.paramiko)
        # SFTPFullAbsoluteServer has a get_url method, and doesn't
        # override the interface (doesn't change self._vendor).
        # Note that this does encryption, so can be slow.
        from breezy.tests import stub_sftp

        # Start an SSH server
        self.command_executed = []
        # XXX: This is horrible -- we define a really dumb SSH server that
        # executes commands, and manage the hooking up of stdin/out/err to the
        # SSH channel ourselves.  Surely this has already been implemented
        # elsewhere?
        started = []

        class StubSSHServer(stub_sftp.StubServer):
            test = self

            def check_channel_exec_request(self, channel, command):
                self.test.command_executed.append(command)
                proc = subprocess.Popen(
                    command,
                    shell=True,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    bufsize=0,
                )

                # XXX: horribly inefficient, not to mention ugly.
                # Start a thread for each of stdin/out/err, and relay bytes
                # from the subprocess to channel and vice versa.
                def ferry_bytes(read, write, close):
                    while True:
                        bytes = read(1)
                        if bytes == b"":
                            close()
                            break
                        write(bytes)

                file_functions = [
                    (channel.recv, proc.stdin.write, proc.stdin.close),
                    (proc.stdout.read, channel.sendall, channel.close),
                    (proc.stderr.read, channel.sendall_stderr, channel.close),
                ]
                started.append(proc)
                for read, write, close in file_functions:
                    t = threading.Thread(target=ferry_bytes, args=(read, write, close))
                    t.start()
                    started.append(t)

                return True

        ssh_server = stub_sftp.SFTPFullAbsoluteServer(StubSSHServer)
        # We *don't* want to override the default SSH vendor: the detected one
        # is the one to use.

        # FIXME: I don't understand the above comment, SFTPFullAbsoluteServer
        # inherits from SFTPServer which forces the SSH vendor to
        # ssh.ParamikoVendor(). So it's forced, not detected. --vila 20100623
        self.start_server(ssh_server)
        port = ssh_server.port

        bzr_remote_command = self.get_brz_command()
        self.overrideEnv("BZR_REMOTE_PATH", " ".join(bzr_remote_command))
        self.overrideEnv("PYTHONPATH", ":".join(sys.path))

        # Access the branch via a bzr+ssh URL.  The BZR_REMOTE_PATH environment
        # variable is used to tell bzr what command to run on the remote end.
        path_to_branch = osutils.abspath(".")
        if sys.platform == "win32":
            # On Windows, we export all drives as '/C:/, etc. So we need to
            # prefix a '/' to get the right path.
            path_to_branch = "/" + path_to_branch
        url = "bzr+ssh://fred:secret@localhost:%d%s" % (port, path_to_branch)
        t = transport.get_transport(url)
        self.permit_url(t.base)
        t.mkdir("foo")

        self.assertEqual(
            [
                b"%s serve --inet --directory=/ --allow-writes"
                % " ".join(bzr_remote_command).encode()
            ],
            self.command_executed,
        )
        # Make sure to disconnect, so that the remote process can stop, and we
        # can cleanup. Then pause the test until everything is shutdown
        t._client._medium.disconnect()
        if not started:
            return
        # First wait for the subprocess
        started[0].wait()
        # And the rest are threads
        for t in started[1:]:
            t.join()
