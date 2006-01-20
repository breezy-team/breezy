# Copyright (C) 2006 Canonical Ltd

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

"""Implementation of Transport that adapts another transport to be readonly."""

from bzrlib.errors import TransportNotPossible
from bzrlib.transport import get_transport, Transport, Server


class ReadonlyTransportDecorator(Transport):
    """A decorator that can convert any transport to be readonly.
    
    This does not use __getattr__ hacks as we need to ensure that
    new writable methods are overridden correctly.
    """

    def __init__(self, url, _decorated=None):
        """Set the 'base' path where files will be stored.
        
        _decorated is a private parameter for cloning."""
        assert url.startswith('readonly+')
        decorated_url = url[len('readonly+'):]
        if _decorated is None:
            self._decorated = get_transport(decorated_url)
        else:
            self._decorated = _decorated
        super(ReadonlyTransportDecorator, self).__init__(
            "readonly+" + self._decorated.base)

    def clone(self, offset=None):
        """See Transport.clone()."""
        decorated_clone = self._decorated.clone(offset)
        return ReadonlyTransportDecorator("readonly+" + decorated_clone.base,
                                          decorated_clone)

    def abspath(self, relpath):
        """See Transport.abspath()."""
        return "readonly+" + self._decorated.abspath(relpath)

    def append(self, relpath, f):
        """See Transport.append()."""
        raise TransportNotPossible('readonly transport')

    def has(self, relpath):
        """See Transport.has()."""
        return self._decorated.has(relpath)

    def delete(self, relpath):
        """See Transport.delete()."""
        raise TransportNotPossible('readonly transport')

    def delete_tree(self, relpath):
        """See Transport.delete_tree()."""
        raise TransportNotPossible('readonly transport')

    def get(self, relpath):
        """See Transport.get()."""
        return self._decorated.get(relpath)

    def put(self, relpath, f, mode=None):
        """See Transport.put()."""
        raise TransportNotPossible('readonly transport')

    def mkdir(self, relpath, mode=None):
        """See Transport.mkdir()."""
        raise TransportNotPossible('readonly transport')

    def is_readonly(self):
        """See Transport.is_readonly."""
        return True

    def listable(self):
        """See Transport.listable."""
        return self._decorated.listable()

    def iter_files_recursive(self):
        """See Transport.iter_files_recursive()."""
        return self._decorated.iter_files_recursive()
    
    def list_dir(self, relpath):
        """See Transport.list_dir()."""
        return self._decorated.list_dir(relpath)
    
    def rmdir(self, relpath):
        """See Transport.rmdir."""
        raise TransportNotPossible('readonly transport')

    def should_cache(self):
        """See Transport.should_cache()."""
        return self._decorated.should_cache()

    def stat(self, relpath):
        """See Transport.stat()."""
        return self._decorated.stat(relpath)

#    def lock_read(self, relpath):
#   TODO if needed / when tested
#
#    def lock_write(self, relpath):
#   TODO if needed / when tested.


class ReadonlyServer(Server):
    """Server for the ReadonlyTransportDecorator for testing with."""

    def setUp(self, server=None):
        """See bzrlib.transport.Server.setUp.

        :server: decorate the urls given by server. If not provided a
        LocalServer is created.
        """
        if server is not None:
            self._made_server = False
            self._server = server
        else:
            from bzrlib.transport.local import LocalRelpathServer
            self._made_server = True
            self._server = LocalRelpathServer()
            self._server.setUp()

    def tearDown(self):
        """See bzrlib.transport.Server.tearDown."""
        if self._made_server:
            self._server.tearDown()

    def get_bogus_url(self):
        """See bzrlib.transport.Server.get_bogus_url."""
        return "readonly+" + self._server.get_bogus_url()

    def get_url(self):
        """See bzrlib.transport.Server.get_url."""
        return "readonly+" + self._server.get_url()


def get_test_permutations():
    """Return the permutations to be used in testing."""
    return [(ReadonlyTransportDecorator, ReadonlyServer),
            ]
