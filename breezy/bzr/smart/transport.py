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
helper that knows how to build a smart medium from each kind of transport
breezy understands.
"""

from dromedary.errors import TransportError
from dromedary.http.urllib import HttpTransport as _HttpTransport


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

    Dispatches by transport type:

    - :class:`breezy.transport.remote.RemoteTransport` already *is* a smart
      transport; its connection is the medium.
    - HTTP transports (``http://``, ``https://``) are wrapped in a
      :class:`breezy.bzr.smart.http.SmartClientHTTPMedium` that tunnels the
      smart protocol over HTTP POST.
    - Everything else (local filesystem, ftp, ...) cannot tunnel the smart
      protocol and raises :class:`NoSmartMedium`.
    """
    # Avoid an import cycle: RemoteTransport imports this module.
    from breezy.transport.remote import RemoteTransport

    if isinstance(transport, RemoteTransport):
        return transport._get_connection()
    if isinstance(transport, _HttpTransport):
        from breezy.bzr.smart.http import SmartClientHTTPMedium

        # Cache the medium on the transport: callers like
        # RemoteHTTPTransport build it more than once and the smart-medium
        # tests rely on identity across calls.
        if transport._medium is None:
            transport._medium = SmartClientHTTPMedium(transport)
        return transport._medium
    raise NoSmartMedium(transport)
