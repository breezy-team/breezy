# Copyright (C) 2009-2012 Canonical Ltd
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

"""Launchpad URIs."""

from yarl import URL


# We use production as the default because edge has been deprecated circa
# 2010-11 (see bug https://bugs.launchpad.net/bzr/+bug/583667)
DEFAULT_INSTANCE = 'production'

LAUNCHPAD_DOMAINS = {
    'production': 'launchpad.net',
    'staging': 'staging.launchpad.net',
    'qastaging': 'qastaging.launchpad.net',
    'demo': 'demo.launchpad.net',
    'test': 'launchpad.test',
    }

LAUNCHPAD_BAZAAR_DOMAINS = [
    'bazaar.%s' % domain
    for domain in LAUNCHPAD_DOMAINS.values()]

LPNET_SERVICE_ROOT = "https://api.launchpad.net/"
QASTAGING_SERVICE_ROOT = "https://api.qastaging.launchpad.net/"
STAGING_SERVICE_ROOT = "https://api.staging.launchpad.net/"
DEV_SERVICE_ROOT = "https://api.launchpad.test/"
DOGFOOD_SERVICE_ROOT = "https://api.dogfood.paddev.net/"
TEST_DEV_SERVICE_ROOT = "http://api.launchpad.test:8085/"

service_roots = dict(
    production=LPNET_SERVICE_ROOT,
    edge=LPNET_SERVICE_ROOT,
    qastaging=QASTAGING_SERVICE_ROOT,
    staging=STAGING_SERVICE_ROOT,
    dogfood=DOGFOOD_SERVICE_ROOT,
    dev=DEV_SERVICE_ROOT,
    test_dev=TEST_DEV_SERVICE_ROOT,
)


def lookup_service_root(root):
    """Dereference an alias to a service root.

    A recognized server alias such as "staging" gets turned into the
    appropriate URI. A URI gets returned as is. Any other string raises a
    ValueError.
    """
    if root in service_roots:
        return service_roots[root]

    # It's not an alias. Is it a valid URL?
    parsed_url = URL(root)
    if parsed_url.scheme != "" and parsed_url.host != "":
        return root

    # It's not an alias or a valid URL.
    raise ValueError(
        "%s is not a valid URL or an alias for any Launchpad " "server" % root
    )


def web_root_for_service_root(service_root):
    """Turn a service root URL into a web root URL.

    This is done heuristically, not with a lookup.
    """
    service_root = lookup_service_root(service_root)
    web_root_uri = URL(service_root)
    web_root_uri = web_root_uri.with_path("")
    web_root_uri = web_root_uri.with_host(web_root_uri.host.replace("api.", "", 1))
    return str(web_root_uri)


def canonical_url(object):
    """Return the canonical URL for a branch."""
    parsed_url = URL(str(object.self_link))
    parsed_url = parsed_url.with_path('/'.join(parsed_url.parts[2:]))
    parsed_url = parsed_url.with_host(parsed_url.host.replace('api.', 'code.'))
    return str(parsed_url)
