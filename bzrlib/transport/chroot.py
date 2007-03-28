# Copyright (C) 2006 Canonical Ltd
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

"""Implementation of Transport that prevents access to locations above a set
root.
"""
from urlparse import urlparse

from bzrlib import errors, urlutils
from bzrlib.transport import (
    get_transport,
    register_transport,
    Server,
    Transport,
    unregister_transport,
    )
from bzrlib.transport.decorator import TransportDecorator, DecoratorServer
from bzrlib.transport.memory import MemoryTransport


class ChrootServer(Server):
    """Server for chroot transports."""

    def __init__(self, backing_transport):
        self.backing_transport = backing_transport

    def _factory(self, url):
        assert url.startswith(self.scheme)
        return ChrootTransport(self, url)

    def get_url(self):
        return self.scheme

    def setUp(self):
        self.scheme = 'chroot-%d:///' % id(self)
        register_transport(self.scheme, self._factory)

    def tearDown(self):
        unregister_transport(self.scheme, self._factory)


class ChrootTransport(Transport):

    def __init__(self, server, base):
        self.server = server
        if not base.endswith('/'):
            base += '/'
        Transport.__init__(self, base)
        self.base_path = self.base[len(self.server.scheme)-1:]
        self.scheme = self.server.scheme

    def _call(self, methodname, relpath, *args):
        method = getattr(self.server.backing_transport, methodname)
        return method(self._safe_relpath(relpath), *args)

    def _safe_relpath(self, relpath):
        safe_relpath = self._combine_paths(self.base_path, relpath)
        assert safe_relpath.startswith('/')
        return safe_relpath[1:]

    # Transport methods
    def abspath(self, relpath):
        return self.scheme + self._safe_relpath(relpath)

    def append_file(self, relpath, f, mode=None):
        return self._call('append_file', relpath, f, mode)

    def clone(self, relpath):
        return ChrootTransport(self.server, self.abspath(relpath))

    def delete(self, relpath):
        return self._call('delete', relpath)

    def delete_tree(self, relpath):
        return self._call('delete_tree', relpath)

    def get(self, relpath):
        return self._call('get', relpath)

    def has(self, relpath):
        return self._call('has', relpath)

    def iter_files_recursive(self):
        backing_transport = self.server.backing_transport.clone(
            self._safe_relpath('.'))
        return backing_transport.iter_files_recursive()

    def listable(self):
        return self.server.backing_transport.listable()

    def list_dir(self, relpath):
        return self._call('list_dir', relpath)

    def lock_read(self, relpath):
        return self._call('lock_read', relpath)

    def lock_write(self, relpath):
        return self._call('lock_write', relpath)

    def mkdir(self, relpath, mode=None):
        return self._call('mkdir', relpath, mode)

    def put_file(self, relpath, f, mode=None):
        return self._call('put_file', relpath, f, mode)

    def rename(self, rel_from, rel_to):
        return self._call('rename', rel_from, self._safe_relpath(rel_to))

    def rmdir(self, relpath):
        return self._call('rmdir', relpath)

    def stat(self, relpath):
        return self._call('stat', relpath)


class TestingChrootServer(ChrootServer):

    def __init__(self):
        """TestingChrootServer is not usable until setUp is called."""

    def setUp(self, backing_server=None):
        """Setup the Chroot on backing_server."""
        if backing_server is not None:
            self.backing_transport = get_transport(backing_server.get_url())
        else:
            self.backing_transport = get_transport('.')
        ChrootServer.setUp(self)


def get_test_permutations():
    """Return the permutations to be used in testing."""
    return [(ChrootTransport, TestingChrootServer),
            ]
