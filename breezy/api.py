# Copyright (C) 2007, 2008, 2009, 2011 Canonical Ltd
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

"""Library API versioning support.

Added in breezy 0.18 this allows export of compatibility information about
breezy. Please see doc/developers/api-versioning.txt for design details and
examples.
"""

from __future__ import absolute_import

import breezy
from .errors import IncompatibleAPI


def get_current_api_version():
    """Return the API version tuple for breezy.

    Added in breezy 0.18.
    """
    return breezy.version_info[0:3]


def require_api(wanted_api):
    """Check if breezy supports the api version wanted_api.

    :param wanted_api: The API version for which support is required.
    :return: None
    :raises IncompatibleAPI: When the wanted_api is not supported by
        breezy.

    Added in breezy 0.18.
    """
    current = get_current_api_version()
    if wanted_api != current:
        raise IncompatibleAPI(breezy, wanted_api, current)


def require_any_api(wanted_api_list):
    """Check if breezy supports the api version wanted_api.

    :param wanted_api: A list of API versions, any of which being available is
        sufficent.
    :return: None
    :raises IncompatibleAPI: When the wanted_api is not supported by
        breezy.

    Added in breezy 1.9.
    """
    current = get_current_api_version()
    if not current in wanted_api_list:
        raise IncompatibleAPI(breezy, wanted_api_list[-1], current)
