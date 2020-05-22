# Copyright (C) 2006-2010 Canonical Ltd
# Copyright (C) 2018 Breezy Developers
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

"""UI location string handling."""

from __future__ import absolute_import

import re

from . import (
    urlutils,
    )
from .hooks import Hooks
from .sixish import (
    PY3,
    string_types,
    )


class LocationHooks(Hooks):
    """Dictionary mapping hook name to a list of callables for location hooks.
    """

    def __init__(self):
        Hooks.__init__(self, "breezy.location", "hooks")
        self.add_hook(
            'rewrite_url',
            "Possibly rewrite a URL. Called with a URL to rewrite and the "
            "purpose of the URL.", (3, 0))


hooks = LocationHooks()


def rcp_location_to_url(location, scheme='ssh'):
    """Convert a rcp-style location to a URL.

    :param location: Location to convert, e.g. "foo:bar"
    :param schenme: URL scheme to return, defaults to "ssh"
    :return: A URL, e.g. "ssh://foo/bar"
    :raises ValueError: if this is not a RCP-style URL
    """
    m = re.match('^(?P<user>[^@:/]+@)?(?P<host>[^/:]+):(?P<path>.*)$', location)
    if not m:
        raise ValueError("Not a RCP URL")
    if m.group('path').startswith('//'):
        raise ValueError("Not a RCP URL: already looks like a URL")
    quoted_user = urlutils.quote(m.group('user')[:-1]) if m.group('user') else None
    url = urlutils.URL(
        scheme=scheme, quoted_user=quoted_user,
        port=None, quoted_password=None,
        quoted_host=urlutils.quote(m.group('host')),
        quoted_path=urlutils.quote(m.group('path')))
    return str(url)


def pserver_to_url(location):
    """Convert a CVS pserver location string to a URL.

    :param location: pserver URL
    :return: A cvs+pserver URL
    """
    parts = location.split(':')
    if parts[0] or parts[1] != 'pserver':
        raise ValueError('not a valid pserver location string')
    try:
        (username, hostname) = parts[2].split('@', 1)
    except IndexError:
        hostname = parts[2]
        username = None
    return str(urlutils.URL(
        scheme='cvs+pserver',
        quoted_user=urlutils.quote(username) if username else None,
        quoted_host=urlutils.quote(hostname),
        quoted_password=None,
        port=None,
        quoted_path=urlutils.quote(parts[3])))


def location_to_url(location, purpose=None):
    """Determine a fully qualified URL from a location string.

    This will try to interpret location as both a URL and a directory path. It
    will also lookup the location in directories.

    :param location: Unicode or byte string object with a location
    :param purpose: Intended method of access (None, 'read' or 'write')
    :raise InvalidURL: If the location is already a URL, but not valid.
    :return: Byte string with resulting URL
    """
    if not isinstance(location, string_types):
        raise AssertionError("location not a byte or unicode string")

    if location.startswith(':pserver:'):
        return pserver_to_url(location)

    from .directory_service import directories
    location = directories.dereference(location, purpose)

    # Catch any URLs which are passing Unicode rather than ASCII
    try:
        location = location.encode('ascii')
    except UnicodeError:
        if urlutils.is_url(location):
            raise urlutils.InvalidURL(
                path=location, extra='URLs must be properly escaped')
        location = urlutils.local_path_to_url(location)
    else:
        if PY3:
            location = location.decode('ascii')

    if location.startswith("file:") and not location.startswith("file://"):
        return urlutils.join(urlutils.local_path_to_url("."), location[5:])

    try:
        url = rcp_location_to_url(location, scheme="ssh")
    except ValueError:
        pass
    else:
        return url

    if not urlutils.is_url(location):
        return urlutils.local_path_to_url(location)

    for hook in hooks['rewrite_url']:
        location = hook(location, purpose=purpose)

    return location
