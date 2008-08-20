# Copyright (C) 2007 Canonical Ltd
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Library API versioning support.

Added in bzrlib 0.18 this allows export of compatibility information about
bzrlib. Please see doc/developers/api-versioning.txt for design details and
examples.
"""

import bzrlib
from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
from bzrlib.errors import IncompatibleAPI
""")


def get_current_api_version(object_with_api):
    """Return the API version tuple for object_with_api.

    :param object_with_api: An object to look for an API version on. If the
        object has a api_current_version attribute, that is used. Otherwise if
        there is a version_info attribute, its first three elements are used.
        Finally if there was no version_info attribute, the current api version
        of bzrlib itself is used.

    Added in bzrlib 0.18.
    """
    try:
        return object_with_api.api_current_version
    except AttributeError:
        try:
            return object_with_api.version_info[0:3]
        except AttributeError:
            return get_current_api_version(bzrlib)


def get_minimum_api_version(object_with_api):
    """Return the minimum API version supported by object_with_api.

    :param object_with_api: An object to look for an API version on. If the
        object has a api_minimum_version attribute, that is used. Otherwise the
        minimum api version of bzrlib itself is used.

    Added in bzrlib 0.18.
    """
    try:
        return object_with_api.api_minimum_version
    except AttributeError:
        return get_minimum_api_version(bzrlib)


def require_api(object_with_api, wanted_api):
    """Check if object_with_api supports the api version wanted_api.

    :param object_with_api: An object which exports an API minimum and current
        version. See get_minimum_api_version and get_current_api_version for
        details.
    :param wanted_api: The API version for which support is required.
    :return None:
    :raises IncompatibleAPI: When the wanted_api is not supported by
        object_with_api.

    Added in bzrlib 0.18.
    """
    current = get_current_api_version(object_with_api)
    minimum = get_minimum_api_version(object_with_api)
    if wanted_api < minimum or wanted_api > current:
        raise IncompatibleAPI(object_with_api, wanted_api, minimum, current)
