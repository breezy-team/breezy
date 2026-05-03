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

from dromedary._transport_rs import TransportDecorator as _RustTransportDecorator
from dromedary.decorator import TransportDecorator as _PyTransportDecorator
from dromedary.errors import TransportError
from dromedary.http.urllib import HttpTransport as _HttpTransport

# Both decorator hierarchies expose ``_decorated`` and route arbitrary
# attribute access to the wrapped transport. Match either when unwrapping.
_TransportDecorator = (_PyTransportDecorator, _RustTransportDecorator)


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

    - HTTP transports (``http://``, ``https://``) are wrapped in a
      :class:`breezy.bzr.smart.http.SmartClientHTTPMedium` that tunnels the
      smart protocol over HTTP POST.
    - Decorators wrapping a transport delegate to whatever they wrap, except
      ``nosmart+...`` which deliberately hides the wrapped medium.
    - Anything else exposing a ``get_smart_medium`` method (notably
      :class:`breezy.transport.remote.RemoteTransport`) returns the result
      of calling it.
    - Everything else raises :class:`NoSmartMedium`.

    The HTTP and decorator cases are checked first so this module does not
    have to import ``breezy.transport.remote`` (which would pull in
    ``breezy.bzr.remote``, ``breezy.bzr.smart.client`` and ``breezy.gpg``,
    bloating the import tariff for ``bzr serve``).
    """
    if isinstance(transport, _HttpTransport):
        from breezy.bzr.smart.http import SmartClientHTTPMedium

        # Cache the medium on the transport: callers like
        # RemoteHTTPTransport build it more than once and the smart-medium
        # tests rely on identity across calls.
        if transport._medium is None:
            transport._medium = SmartClientHTTPMedium(transport)
        return transport._medium
    if isinstance(transport, _TransportDecorator):
        # NoSmartTransportDecorator is also a TransportDecorator; check its
        # url-prefix marker so we can short-circuit without importing the
        # breezy.transport.nosmart module.
        prefix = type(transport)._get_url_prefix()
        if prefix == "nosmart+":
            raise NoSmartMedium(transport)
        return get_smart_medium(transport._decorated)
    method = getattr(transport, "get_smart_medium", None)
    if method is None:
        raise NoSmartMedium(transport)
    return method()
