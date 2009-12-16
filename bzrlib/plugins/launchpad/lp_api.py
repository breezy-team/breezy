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

import os

from bzrlib import (
    errors,
    trace,
    )
from bzrlib.plugins.launchpad.lp_registration import (
    InvalidLaunchpadInstance,
    NotLaunchpadBranch,
    )

from launchpadlib.credentials import Credentials
from launchpadlib.launchpad import (
    EDGE_SERVICE_ROOT,
    STAGING_SERVICE_ROOT,
    Launchpad,
    )
from lazr.uri import URI


# XXX: Not the right value for Windows
# Look in win32 utils -- maybe wrap it up
CACHE_DIRECTORY = os.path.expanduser('~/.launchpadlib/cache')


LAUNCHPAD_API_URLS = {
    'production': EDGE_SERVICE_ROOT,
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


def _get_credential_path(service):
    """Return the path to cached credentials for 'service'.

    :param service: A `LaunchpadService` object.
    :return: The path to a cached credentials file, which might not exist.
    """
    web_root_uri = URI(_get_api_url(service))
    credential_name = 'creds-%s-bzr' % (web_root_uri.host)
    return os.path.join(CACHE_DIRECTORY, credential_name)


def _login_from_cache(consumer_name, service_root, cache_dir,
                      credential_cache, timeout=None, proxy_info=None):
    """Use cached credentials if they exist, log in otherwise."""
    # XXX: make sure credentials are private
    try:
        credentials = Credentials.load_from_path(credential_cache)
    except (OSError, IOError):
        launchpad = Launchpad.get_token_and_login(
            consumer_name, service_root, cache_dir, timeout, proxy_info)
        launchpad.credentials.save_to_path(credential_cache)
    else:
        access_key = credentials.access_token.key
        access_secret = credentials.access_token.secret
        launchpad = Launchpad.login(
            consumer_name, access_key, access_secret, service_root,
            cache_dir, timeout, proxy_info)
    return launchpad


def login(service, timeout=None, proxy_info=None):
    """Log in to the Launchpad API.

    :return: The root `Launchpad` object from launchpadlib.
    """
    credential_path = _get_credential_path(service)
    launchpad = _login_from_cache(
        'bzr', _get_api_url(service), CACHE_DIRECTORY, credential_path,
        timeout, proxy_info)
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
