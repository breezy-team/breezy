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

"""Implementation of Transport that decorates another transport.

This does not change the transport behaviour at all, but provides all the 
stub functions to allow other decorators to be written easily.
"""

from bzrlib.transport import get_transport, Transport, Server


class TransportDecorator(Transport):
    """A no-change decorator for Transports.

    Subclasses of this are new transports that are based on an
    underlying transport and can override or intercept some 
    behavior.  For example ReadonlyTransportDecorator prevents 
    all write attempts, and FakeNFSTransportDecorator simulates 
    some NFS quirks.

    This decorator class is not directly usable as a decorator:
    you must use a subclass which has overridden the _get_url_prefix() class
    method to return the url prefix for the subclass.
    """

    def __init__(self, url, _decorated=None):
        """Set the 'base' path where files will be stored.
        
        _decorated is a private parameter for cloning."""
        prefix = self._get_url_prefix()
        assert url.startswith(prefix), \
                "url %r doesn't start with decorator prefix %r" % \
                (url, prefix)
        decorated_url = url[len(prefix):]
        if _decorated is None:
            self._decorated = get_transport(decorated_url)
        else:
            self._decorated = _decorated
        super(TransportDecorator, self).__init__(
            prefix + self._decorated.base)

    def abspath(self, relpath):
        """See Transport.abspath()."""
        return self._get_url_prefix() + self._decorated.abspath(relpath)

    def append(self, relpath, f):
        """See Transport.append()."""
        return self._decorated.append(relpath, f)

    def clone(self, offset=None):
        """See Transport.clone()."""
        decorated_clone = self._decorated.clone(offset)
        return self.__class__(
            self._get_url_prefix() + decorated_clone.base, decorated_clone)

    def delete(self, relpath):
        """See Transport.delete()."""
        return self._decorated.delete(relpath)

    def delete_tree(self, relpath):
        """See Transport.delete_tree()."""
        return self._decorated.delete_tree(relpath)

    @classmethod
    def _get_url_prefix(self):
        """Return the URL prefix of this decorator."""
        raise NotImplementedError(self._get_url_prefix)

    def get(self, relpath):
        """See Transport.get()."""
        return self._decorated.get(relpath)

    def has(self, relpath):
        """See Transport.has()."""
        return self._decorated.has(relpath)

    def is_readonly(self):
        """See Transport.is_readonly."""
        return self._decorated.is_readonly()

    def mkdir(self, relpath, mode=None):
        """See Transport.mkdir()."""
        return self._decorated.mkdir(relpath, mode)

    def put(self, relpath, f, mode=None):
        """See Transport.put()."""
        return self._decorated.put(relpath, f, mode)
    
    def listable(self):
        """See Transport.listable."""
        return self._decorated.listable()

    def iter_files_recursive(self):
        """See Transport.iter_files_recursive()."""
        return self._decorated.iter_files_recursive()
    
    def list_dir(self, relpath):
        """See Transport.list_dir()."""
        return self._decorated.list_dir(relpath)

    def rename(self, rel_from, rel_to):
        return self._decorated.rename(rel_from, rel_to)
    
    def rmdir(self, relpath):
        """See Transport.rmdir."""
        return self._decorated.rmdir(relpath)

    def should_cache(self):
        """See Transport.should_cache()."""
        return self._decorated.should_cache()

    def stat(self, relpath):
        """See Transport.stat()."""
        return self._decorated.stat(relpath)

    def lock_read(self, relpath):
        """See Transport.lock_read."""
        return self._decorated.lock_read(relpath)

    def lock_write(self, relpath):
        """See Transport.lock_write."""
        return self._decorated.lock_write(relpath)


class DecoratorServer(Server):
    """Server for the TransportDecorator for testing with.
    
    To use this when subclassing TransportDecorator, override override the
    get_decorator_class method.
    """

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

    def get_decorator_class(self):
        """Return the class of the decorators we should be constructing."""
        raise NotImplementedError(self.get_decorator_class)

    def get_url_prefix(self):
        """What URL prefix does this decorator produce?"""
        return self.get_decorator_class()._get_url_prefix()

    def get_bogus_url(self):
        """See bzrlib.transport.Server.get_bogus_url."""
        return self.get_url_prefix() + self._server.get_bogus_url()

    def get_url(self):
        """See bzrlib.transport.Server.get_url."""
        return self.get_url_prefix() + self._server.get_url()


def get_test_permutations():
    """Return the permutations to be used in testing.
    
    The Decorator class is not directly usable, and testing it would not have
    any benefit - its the concrete classes which need to be tested.
    """
    return []
