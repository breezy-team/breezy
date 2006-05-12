# Copyright (C) 2005, 2006 Canonical Ltd

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

"""Transport implementation that adapts another transport to look like NFS.

Currently this means that the rename() call will raise ResourceBusy when a
target path is a directory.

To get a fake nfs transport use get_transport('fakenfs+' + real_url)
"""

from stat import *

import bzrlib.errors as errors
from bzrlib.transport.decorator import TransportDecorator, DecoratorServer


class FakeNFSTransportDecorator(TransportDecorator):
    """A transport that behaves like NFS, for testing"""

    @classmethod
    def _get_url_prefix(self):
        """FakeNFS transports are identified by 'fakenfs+'"""
        return 'fakenfs+'

    def rename(self, rel_from, rel_to):
        """See Transport.rename().

        This variation on rename converts DirectoryNotEmpty and FileExists
        errors into ResourceBusy if the target is a directory.
        """
        try:
            self._decorated.rename(rel_from, rel_to)
        except (errors.DirectoryNotEmpty, errors.FileExists), e:
            # if this is a directory rename, raise
            # resourcebusy rather than DirectoryNotEmpty
            stat = self._decorated.stat(rel_to)
            if S_ISDIR(stat.st_mode):
                raise errors.ResourceBusy(rel_to)
            else:
                raise


class FakeNFSServer(DecoratorServer):
    """Server for the FakeNFSTransportDecorator for testing with."""

    def get_decorator_class(self):
        return FakeNFSTransportDecorator


def get_test_permutations():
    """Return the permutations to be used in testing."""
    return [(FakeNFSTransportDecorator, FakeNFSServer),
            ]
