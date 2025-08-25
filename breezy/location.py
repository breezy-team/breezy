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

from . import _cmd_rs, urlutils
from .hooks import Hooks


class LocationHooks(Hooks):
    """Dictionary mapping hook name to a list of callables for location hooks."""

    def __init__(self):
        """Initialize LocationHooks with predefined hook points.

        Registers hooks for URL and location rewriting operations.
        """
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

parse_rcp_location = _cmd_rs.parse_rcp_location
rcp_location_to_url = _cmd_rs.rcp_location_to_url
parse_cvs_location = _cmd_rs.parse_cvs_location
cvs_to_url = _cmd_rs.cvs_to_url


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
    except UnicodeError as err:
        if urlutils.is_url(location):
            raise urlutils.InvalidURL(
                path=location, extra="URLs must be properly escaped"
            ) from err
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
