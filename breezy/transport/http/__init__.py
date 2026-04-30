# Copyright (C) 2005-2012, 2016 Canonical Ltd
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

"""HTTP transports for breezy: dromedary's HTTP and WebDAV transports with smart-protocol support."""

from dromedary.http.urllib import HttpTransport as _DromedaryHttpTransport
from dromedary.webdav import HttpDavTransport as _DromedaryHttpDavTransport


def _get_smart_medium(self):
    """Return (and cache) a smart client medium that talks bzr smart over HTTP."""
    from breezy.bzr.smart.http import SmartClientHTTPMedium

    if self._medium is None:
        self._medium = SmartClientHTTPMedium(self)
    return self._medium


class HttpTransport(_DromedaryHttpTransport):
    """HttpTransport that can tunnel the bzr smart protocol."""

    get_smart_medium = _get_smart_medium


class HttpDavTransport(_DromedaryHttpDavTransport):
    """WebDAV transport that can tunnel the bzr smart protocol."""

    get_smart_medium = _get_smart_medium


def get_test_permutations():
    """Return the permutations for testing transports."""
    from dromedary.http.urllib import get_test_permutations as _drom
    from dromedary.webdav.webdav import get_test_permutations as _drom_webdav

    permutations = []
    for cls, server in _drom():
        # Replace the dromedary HttpTransport class with our smart-aware
        # subclass so tests exercise the breezy version.
        if cls is _DromedaryHttpTransport:
            permutations.append((HttpTransport, server))
        else:
            permutations.append((cls, server))
    for cls, server in _drom_webdav():
        if cls is _DromedaryHttpDavTransport:
            permutations.append((HttpDavTransport, server))
        else:
            permutations.append((cls, server))
    return permutations
