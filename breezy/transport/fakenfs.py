# Copyright (C) 2005, 2006, 2008 Canonical Ltd
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

"""Transport implementation that adapts another transport to look like NFS.

Currently this means that the rename() call will raise ResourceBusy when a
target path is a directory.

To get a fake nfs transport use get_transport('fakenfs+' + real_url)
"""

from stat import S_ISDIR

from .. import (
    errors,
    transport as _mod_transport,
    urlutils,
    )
from . import decorator


class FakeNFSTransportDecorator(decorator.TransportDecorator):
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
        except (errors.DirectoryNotEmpty, _mod_transport.FileExists) as e:
            # if this is a directory rename, raise
            # resourcebusy rather than DirectoryNotEmpty
            stat = self._decorated.stat(rel_to)
            if S_ISDIR(stat.st_mode):
                raise errors.ResourceBusy(rel_to)
            else:
                raise

    def delete(self, relpath):
        if urlutils.basename(relpath).startswith('.nfs'):
            raise errors.ResourceBusy(self.abspath(relpath))
        return self._decorated.delete(relpath)


def get_test_permutations():
    """Return the permutations to be used in testing."""
    from breezy.tests import test_server
    return [(FakeNFSTransportDecorator, test_server.FakeNFSServer), ]
