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

import re

from . import urlutils
from .hooks import Hooks


class LocationHooks(Hooks):
    """Dictionary mapping hook name to a list of callables for location hooks."""

    def __init__(self):
        Hooks.__init__(self, "breezy.location", "hooks")
        self.add_hook(
            "rewrite_url",
            "Possibly rewrite a URL. Called with a URL to rewrite and the "
            "purpose of the URL.",
            (3, 0),
        )
        self.add_hook(
            "rewrite_location",
            "Possibly rewrite a location. Called with a location string to "
            "rewrite and the purpose of the URL.",
            (3, 2),
        )


hooks = LocationHooks()


def parse_rcp_location(location):
    """Convert a rcp-style location to a URL.

    :param location: Location to convert, e.g. "foo:bar"
    :param scheme: URL scheme to return, defaults to "ssh"
    :return: A URL, e.g. "ssh://foo/bar"
    :raises ValueError: if this is not a RCP-style URL
    """
    m = re.match("^(?P<user>[^@:/]+@)?(?P<host>[^/:]{2,}):(?P<path>.*)$", location)
    if not m:
        raise ValueError("Not a RCP URL")
    if m.group("path").startswith("//"):
        raise ValueError("Not a RCP URL: already looks like a URL")
    return (
        m.group("host"),
        m.group("user")[:-1] if m.group("user") else None,
        m.group("path"),
    )


def rcp_location_to_url(location, scheme="ssh"):
    """Convert a rcp-style location to a URL.

    :param location: Location to convert, e.g. "foo:bar"
    :param scheme: URL scheme to return, defaults to "ssh"
    :return: A URL, e.g. "ssh://foo/bar"
    :raises ValueError: if this is not a RCP-style URL
    """
    (host, user, path) = parse_rcp_location(location)
    quoted_user = urlutils.quote(user) if user else None
    url = urlutils.URL(
        scheme=scheme,
        quoted_user=quoted_user,
        port=None,
        quoted_password=None,
        quoted_host=urlutils.quote(host),
        quoted_path=urlutils.quote(path),
    )
    return str(url)


def parse_cvs_location(location):
    parts = location.split(":")
    if parts[0] or parts[1] not in ("pserver", "ssh", "extssh"):
        raise ValueError("not a valid CVS location string")
    try:
        (username, hostname) = parts[2].split("@", 1)
    except IndexError:
        hostname = parts[2]
        username = None
    scheme = parts[1]
    if scheme == "extssh":
        scheme = "ssh"
    try:
        path = parts[3]
    except IndexError:
        raise ValueError("no path element in CVS location {}".format(location))
    return (scheme, hostname, username, path)


def cvs_to_url(location):
    """Convert a CVS pserver location string to a URL.

    :param location: pserver URL
    :return: A cvs+pserver URL
    """
    try:
        (scheme, host, user, path) = parse_cvs_location(location)
    except ValueError as e:
        raise urlutils.InvalidURL(path=location, extra=str(e))
    return str(
        urlutils.URL(
            scheme="cvs+" + scheme,
            quoted_user=urlutils.quote(user) if user else None,
            quoted_host=urlutils.quote(host),
            quoted_password=None,
            port=None,
            quoted_path=urlutils.quote(path),
        )
    )


def location_to_url(location, purpose=None):
    """Determine a fully qualified URL from a location string.

    This will try to interpret location as both a URL and a directory path. It
    will also lookup the location in directories.

    :param location: Unicode or byte string object with a location
    :param purpose: Intended method of access (None, 'read' or 'write')
    :raise InvalidURL: If the location is already a URL, but not valid.
    :return: Byte string with resulting URL
    """
    if not isinstance(location, str):
        raise AssertionError("location not a byte or unicode string")

    for hook in hooks["rewrite_location"]:
        location = hook(location, purpose=purpose)

    if location.startswith(":pserver:") or location.startswith(":extssh:"):
        return cvs_to_url(location)

    from .directory_service import directories

    location = directories.dereference(location, purpose)

    # Catch any URLs which are passing Unicode rather than ASCII
    try:
        location = location.encode("ascii")
    except UnicodeError:
        if urlutils.is_url(location):
            raise urlutils.InvalidURL(
                path=location, extra="URLs must be properly escaped"
            )
        location = urlutils.local_path_to_url(location)
    else:
        location = location.decode("ascii")

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

    for hook in hooks["rewrite_url"]:
        location = hook(location, purpose=purpose)

    return location
