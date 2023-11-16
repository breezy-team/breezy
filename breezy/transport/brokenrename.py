# Copyright (C) 2007 Canonical Ltd
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

"""Transport implementation that doesn't detect clashing renames."""

from .. import urlutils
from ..transport import FileExists
from . import decorator


class BrokenRenameTransportDecorator(decorator.TransportDecorator):
    """A transport that fails to detect clashing renames."""

    @classmethod
    def _get_url_prefix(self):
        """FakeNFS transports are identified by 'brokenrename+'."""
        return "brokenrename+"

    def rename(self, rel_from, rel_to):
        """See Transport.rename()."""
        try:
            if self._decorated.has(rel_to):
                rel_to = urlutils.join(rel_to, urlutils.basename(rel_from))
            self._decorated.rename(rel_from, rel_to)
        except (errors.DirectoryNotEmpty, FileExists):
            # absorb the error
            return


def get_test_permutations():
    """Return the permutations to be used in testing."""
    # we don't use this for general testing, only for the tests that
    # specifically want it
    return []
