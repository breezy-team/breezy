# Copyright (C) 2006-2010 Canonical Ltd
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

"""Implementation of Transport that prevents access to locations above a set
root.
"""

from . import pathfilter, register_transport


class ChrootServer(pathfilter.PathFilteringServer):
    """User space 'chroot' facility.

    The server's get_url returns the url for a chroot transport mapped to the
    backing transport. The url is of the form chroot-xxx:/// so parent
    directories of the backing transport are not visible. The chroot url will
    not allow '..' sequences to result in requests to the chroot affecting
    directories outside the backing transport.

    PathFilteringServer does all the path sanitation needed to enforce a
    chroot, so this is a simple subclass of PathFilteringServer that ignores
    filter_func.
    """

    def __init__(self, backing_transport):
        """Initialize the ChrootServer.

        Args:
            backing_transport: The underlying transport to use as the root.
        """
        pathfilter.PathFilteringServer.__init__(self, backing_transport, None)

    def _factory(self, url):
        return ChrootTransport(self, url)

    def start_server(self):
        """Start the chroot server and register its transport.

        Creates a unique URL scheme for this server instance and registers
        the transport factory with the transport registry.
        """
        self.scheme = "chroot-%d:///" % id(self)
        register_transport(self.scheme, self._factory)


class ChrootTransport(pathfilter.PathFilteringTransport):
    """A ChrootTransport.

    Please see ChrootServer for details.
    """

    def _filter(self, relpath):
        # A simplified version of PathFilteringTransport's _filter that omits
        # the call to self.server.filter_func.
        return self._relpath_from_server_root(relpath)


def get_test_permutations():
    """Return the permutations to be used in testing."""
    from breezy.tests import test_server

    return [(ChrootTransport, test_server.TestingChrootServer)]
