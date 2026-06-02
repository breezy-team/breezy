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

"""Compatibility shim re-exporting dromedary's HTTP and WebDAV transports.

The smart-protocol dispatch lives in :mod:`breezy.bzr.smart.transport`
which special-cases these classes — no breezy-side subclass is needed
just to attach a ``get_smart_medium`` method.
"""

from dromedary.http.urllib import HttpTransport
from dromedary.webdav import HttpDavTransport

__all__ = ["HttpDavTransport", "HttpTransport"]
