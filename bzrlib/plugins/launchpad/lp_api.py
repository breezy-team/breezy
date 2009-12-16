# Copyright (C) 2009 Canonical Ltd
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

"""Tools for dealing with the Launchpad API."""

# Importing this module will be expensive, since it imports launchpadlib and
# its dependencies. However, our plan is to only load this module when it is
# needed by a command that uses it.

# XXX: Do some sort of version check for 1.5.1 or greater.

import os
import sys

from bzrlib import (
    errors,
    osutils,
    trace,
    win32utils,
    )
from bzrlib.plugins.launchpad.lp_registration import (
    InvalidLaunchpadInstance,
    NotLaunchpadBranch,
    )

from launchpadlib.launchpad import (
    EDGE_SERVICE_ROOT,
    STAGING_SERVICE_ROOT,
    Launchpad,
    )


def get_cache_directory():
    """Return the directory to cache launchpadlib objects in."""
    if sys.platform == 'win32':
        base = win32utils.get_appdata_location_unicode()
        if base is None:
            base = os.environ.get('HOME', None)
        if base is None:
            raise errors.BzrError('You must have one of BZR_HOME, APPDATA,'
                                  ' or HOME set')
    else:
        base = os.path.expanduser('~/.cache')
    return osutils.pathjoin(base, 'launchpadlib')


LAUNCHPAD_API_URLS = {
    'production': 'https://api.launchpad.net/beta/',
    'edge': EDGE_SERVICE_ROOT,
    'staging': STAGING_SERVICE_ROOT,
    'dev': 'https://api.launchpad.dev/beta/',
    }


def _get_api_url(service):
    """Return the root URL of the Launchpad API.

    e.g. For the 'edge' Launchpad service, this function returns
    launchpadlib.launchpad.EDGE_SERVICE_ROOT.

    :param service: A `LaunchpadService` object.
    :return: A URL as a string.
    """
    if service._lp_instance is None:
        lp_instance = service.DEFAULT_INSTANCE
    else:
        lp_instance = service._lp_instance
    try:
        return LAUNCHPAD_API_URLS[lp_instance]
    except KeyError:
        raise InvalidLaunchpadInstance(lp_instance)


def login(service, timeout=None, proxy_info=None):
    """Log in to the Launchpad API.

    :return: The root `Launchpad` object from launchpadlib.
    """
    cache_directory = get_cache_directory()
    launchpad = Launchpad.login_with(
        'bzr', _get_api_url(service), cache_directory, timeout=timeout,
        proxy_info=proxy_info)
    # XXX: Work-around a minor security bug in launchpadlib 1.5.1, which would
    # create this directory with default umask.
    os.chmod(cache_directory, 0700)
    # XXX: Why does this set the private member of a class?
    launchpad._service = service
    return launchpad


def load_branch(launchpad, branch):
    """Return the launchpadlib Branch object corresponding to 'branch'.

    :param launchpad: The root `Launchpad` object from launchpadlib.
    :param branch: A `bzrlib.branch.Branch`.
    :raise NotLaunchpadBranch: If we cannot determine the Launchpad URL of
        `branch`.
    :return: A launchpadlib Branch object.
    """
    # XXX: Why does this need service and _guess_branch_path?
    service = launchpad._service
    for url in branch.get_public_branch(), branch.get_push_location():
        if url is None:
            continue
        try:
            path = service._guess_branch_path(url)
        except (errors.InvalidURL, NotLaunchpadBranch):
            pass
        else:
            trace.mutter('Guessing path: %s', path)
            uri = launchpad._root_uri.append(path)
            uri_str = str(uri)
            trace.mutter('Guessing url: %s', uri_str)
            return launchpad.load(uri_str)
    raise NotLaunchpadBranch(url)
