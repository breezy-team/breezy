# Copyright (C) 2010 Canonical Ltd
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


import os

from bzrlib import (
    config,
    errors,
    osutils,
    )
from bzrlib.plugins.launchpad.lp_registration import (
    InvalidLaunchpadInstance,
    NotLaunchpadBranch,
    )

try:
    import launchpadlib
except ImportError, e:
    raise errors.DependencyNotPresent('launchpadlib', e)

from launchpadlib.launchpad import (
    EDGE_SERVICE_ROOT,
    STAGING_SERVICE_ROOT,
    Launchpad,
    )


# Declare the minimum version of launchpadlib that we need in order to work.
# 1.5.1 is the version of launchpadlib packaged in Ubuntu 9.10, the most
# recent Ubuntu release at the time of writing.
MINIMUM_LAUNCHPADLIB_VERSION = (1, 5, 1)


def get_cache_directory():
    """Return the directory to cache launchpadlib objects in."""
    return osutils.pathjoin(config.config_dir(), 'launchpad')


def parse_launchpadlib_version(version_number):
    """Parse a version number of the style used by launchpadlib."""
    return tuple(map(int, version_number.split('.')))


def check_launchpadlib_compatibility():
    """Raise an error if launchpadlib has the wrong version number."""
    installed_version = parse_launchpadlib_version(launchpadlib.__version__)
    if installed_version < MINIMUM_LAUNCHPADLIB_VERSION:
        raise errors.IncompatibleAPI(
            'launchpadlib', MINIMUM_LAUNCHPADLIB_VERSION,
            installed_version, installed_version)


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
    return launchpad


def load_branch(launchpad, branch):
    """Return the launchpadlib Branch object corresponding to 'branch'.

    :param launchpad: The root `Launchpad` object from launchpadlib.
    :param branch: A `bzrlib.branch.Branch`.
    :raise NotLaunchpadBranch: If we cannot determine the Launchpad URL of
        `branch`.
    :return: A launchpadlib Branch object.
    """
    # XXX: This duplicates the "What are possible URLs for the branch that
    # Launchpad might recognize" logic found in cmd_lp_open.

    # XXX: This makes multiple roundtrips to Launchpad for what is
    # conceptually a single operation -- get me the branches that match these
    # URLs. Unfortunately, Launchpad's support for such operations is poor, so
    # we have to allow multiple roundtrips.
    for url in branch.get_public_branch(), branch.get_push_location():
        lp_branch = launchpad.branches.getByUrl(url=url)
        if lp_branch:
            return lp_branch
    raise NotLaunchpadBranch(url)
