# Copyright (C) 2005-2012 Canonical Ltd
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

"""Smart-protocol glue between breezy and dromedary transports.

The dromedary package dropped its built-in SmartMedium support because the
smart protocol is bzr-specific. This module re-introduces the pieces breezy
needs: the :class:`NoSmartMedium` exception and a :func:`get_smart_medium`
helper that calls ``transport.get_smart_medium()`` when the transport
provides it and raises :class:`NoSmartMedium` otherwise.
"""

from dromedary.errors import TransportError


class NoSmartMedium(TransportError):
    """Raised when a transport cannot tunnel the smart protocol."""

    _fmt = "The transport '%(transport)s' cannot tunnel the smart protocol."

    internal_error = True

    def __init__(self, transport):
        """Initialize with the transport that lacks smart-protocol support."""
        self.transport = transport
        TransportError.__init__(self)


def get_smart_medium(transport):
    """Return a smart client medium for ``transport``.

    Transports that can tunnel the bzr smart protocol (e.g. ``bzr://``,
    ``bzr+ssh://`` and ``http://``) implement a ``get_smart_medium`` method
    returning a :class:`breezy.bzr.smart.medium.SmartClientMedium`. Transports
    that cannot (e.g. local filesystem) don't implement that method, in which
    case this helper raises :class:`NoSmartMedium`.
    """
    method = getattr(transport, "get_smart_medium", None)
    if method is None:
        raise NoSmartMedium(transport)
    return method()
