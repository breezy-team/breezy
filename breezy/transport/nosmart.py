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

This is mainly useful with HTTP transports, which sometimes have a smart
medium and sometimes don't. By wrapping a transport in this decorator, the
:func:`breezy.bzr.smart.transport.get_smart_medium` dispatcher sees a plain
``Transport`` rather than the underlying ``HttpTransport`` and raises
``NoSmartMedium``.
"""

from dromedary import decorator


class NoSmartTransportDecorator(decorator.TransportDecorator):
    """A decorator that hides the smart-medium capability of its inner transport."""

    @classmethod
    def _get_url_prefix(self):
        return "nosmart+"


def get_test_permutations():
    """Return the permutations to be used in testing."""
    from breezy.tests import test_server

    return [(NoSmartTransportDecorator, test_server.NoSmartTransportServer)]
