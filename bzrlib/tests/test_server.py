# Copyright (C) 2005, 2006, 2007, 2008, 2010 Canonical Ltd
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

from bzrlib import (
    transport,
    )


class TestServer(transport.Server):
    """A Transport Server dedicated to tests.

    The TestServer interface provides a server for a given transport. We use
    these servers as loopback testing tools. For any given transport the
    Servers it provides must either allow writing, or serve the contents
    of os.getcwdu() at the time start_server is called.

    Note that these are real servers - they must implement all the things
    that we want bzr transports to take advantage of.
    """

    def get_url(self):
        """Return a url for this server.

        If the transport does not represent a disk directory (i.e. it is
        a database like svn, or a memory only transport, it should return
        a connection to a newly established resource for this Server.
        Otherwise it should return a url that will provide access to the path
        that was os.getcwdu() when start_server() was called.

        Subsequent calls will return the same resource.
        """
        raise NotImplementedError

    def get_bogus_url(self):
        """Return a url for this protocol, that will fail to connect.

        This may raise NotImplementedError to indicate that this server cannot
        provide bogus urls.
        """
        raise NotImplementedError


class LocalURLServer(Server):
    """A pretend server for local transports, using file:// urls.

    Of course no actual server is required to access the local filesystem, so
    this just exists to tell the test code how to get to it.
    """

    def start_server(self):
        pass

    def get_url(self):
        """See Transport.Server.get_url."""
        return urlutils.local_path_to_url('')


class MemoryServer(Server):
    """Server for the MemoryTransport for testing with."""

    def start_server(self):
        self._dirs = {'/':None}
        self._files = {}
        self._locks = {}
        self._scheme = "memory+%s:///" % id(self)
        def memory_factory(url):
            from bzrlib.transport import memory
            result = memory.MemoryTransport(url)
            result._dirs = self._dirs
            result._files = self._files
            result._locks = self._locks
            return result
        self._memory_factory = memory_factory
        transport.register_transport(self._scheme, self._memory_factory)

    def stop_server(self):
        # unregister this server
        transport.unregister_transport(self._scheme, self._memory_factory)

    def get_url(self):
        """See bzrlib.transport.Server.get_url."""
        return self._scheme


class DecoratorServer(Server):
    """Server for the TransportDecorator for testing with.

    To use this when subclassing TransportDecorator, override override the
    get_decorator_class method.
    """

    def start_server(self, server=None):
        """See bzrlib.transport.Server.start_server.

        :server: decorate the urls given by server. If not provided a
        LocalServer is created.
        """
        if server is not None:
            self._made_server = False
            self._server = server
        else:
            self._made_server = True
            self._server = LocalURLServer()
            self._server.start_server()

    def stop_server(self):
        if self._made_server:
            self._server.stop_server()

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


