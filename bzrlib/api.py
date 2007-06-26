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

"""Library API versioning support."""

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
    """
    try:
        return object_with_api.api_minimum_version
    except AttributeError:
        return get_minimum_api_version(bzrlib)
