# Copyright (C) 2008 Canonical Ltd
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

"""Implementation of Transport that never has a smart medium.

This is mainly useful with HTTP transports, which sometimes have a smart medium
and sometimes don't.  By using this decorator, you can force those transports
to never have a smart medium.
"""

from .. import errors
from ..transport import decorator


class NoSmartTransportDecorator(decorator.TransportDecorator):
    """A decorator for transports that disables get_smart_medium."""

    @classmethod
    def _get_url_prefix(self):
        return "nosmart+"

    def get_smart_medium(self):
        """Raise NoSmartMedium exception to disable smart medium functionality.

        This method intentionally raises an exception to prevent the use of
        smart mediums, forcing the transport to use standard protocols.

        Raises:
            NoSmartMedium: Always raised to indicate no smart medium is available.
        """
        raise errors.NoSmartMedium(self)


def get_test_permutations():
    """Return the permutations to be used in testing."""
    from ..tests import test_server

    return [(NoSmartTransportDecorator, test_server.NoSmartTransportServer)]
