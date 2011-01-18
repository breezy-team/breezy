# Copyright (C) 2009, 2010 Canonical Ltd
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
import re
import urlparse

from bzrlib import (
    branch,
    config,
    errors,
    osutils,
    trace,
    transport,
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
    STAGING_SERVICE_ROOT,
    Launchpad,
    )
from launchpadlib import uris

LPNET_SERVICE_ROOT = getattr(uris, 'LPNET_SERVICE_ROOT',
                             'https://api.launchpad.net/beta/')
QASTAGING_SERVICE_ROOT = getattr(uris, 'QASTAGING_SERVICE_ROOT',
                                 'https://api.qastaging.launchpad.net/')

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
    'production': LPNET_SERVICE_ROOT,
    'qastaging': QASTAGING_SERVICE_ROOT,
    'staging': STAGING_SERVICE_ROOT,
    'dev': 'https://api.launchpad.dev/beta/',
    }


def _get_api_url(service):
    """Return the root URL of the Launchpad API.

    e.g. For the 'staging' Launchpad service, this function returns
    launchpadlib.launchpad.STAGING_SERVICE_ROOT.

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


class NoLaunchpadBranch(errors.BzrError):
    _fmt = 'No launchpad branch could be found for branch "%(url)s".'

    def __init__(self, branch):
        errors.BzrError.__init__(self, branch=branch, url=branch.base)


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


class LaunchpadBranch(object):
    """Provide bzr and lp API access to a Launchpad branch."""

    def __init__(self, lp_branch, bzr_url, bzr_branch=None, check_update=True):
        """Constructor.

        :param lp_branch: The Launchpad branch.
        :param bzr_url: The URL of the Bazaar branch.
        :param bzr_branch: An instance of the Bazaar branch.
        """
        self.bzr_url = bzr_url
        self._bzr = bzr_branch
        self._push_bzr = None
        self._check_update = check_update
        self.lp = lp_branch

    @property
    def bzr(self):
        """Return the bzr branch for this branch."""
        if self._bzr is None:
            self._bzr = branch.Branch.open(self.bzr_url)
        return self._bzr

    @property
    def push_bzr(self):
        """Return the push branch for this branch."""
        if self._push_bzr is None:
            self._push_bzr = branch.Branch.open(self.lp.bzr_identity)
        return self._push_bzr

    @staticmethod
    def plausible_launchpad_url(url):
        """Is 'url' something that could conceivably be pushed to LP?

        :param url: A URL that may refer to a Launchpad branch.
        :return: A boolean.
        """
        if url is None:
            return False
        if url.startswith('lp:'):
            return True
        regex = re.compile('([a-z]*\+)*(bzr\+ssh|http)'
                           '://bazaar.*.launchpad.net')
        return bool(regex.match(url))

    @staticmethod
    def candidate_urls(bzr_branch):
        """Iterate through related URLs that might be Launchpad URLs.

        :param bzr_branch: A Bazaar branch to find URLs from.
        :return: a generator of URL strings.
        """
        url = bzr_branch.get_public_branch()
        if url is not None:
            yield url
        url = bzr_branch.get_push_location()
        if url is not None:
            yield url
        yield bzr_branch.base

    @staticmethod
    def tweak_url(url, launchpad):
        """Adjust a URL to work with staging, if needed."""
        if str(launchpad._root_uri) == STAGING_SERVICE_ROOT:
            return url.replace('bazaar.launchpad.net',
                               'bazaar.staging.launchpad.net')
        elif str(launchpad._root_uri) == QASTAGING_SERVICE_ROOT:
            return url.replace('bazaar.launchpad.net',
                               'bazaar.qastaging.launchpad.net')
        return url

    @classmethod
    def from_bzr(cls, launchpad, bzr_branch, create_missing=True):
        """Find a Launchpad branch from a bzr branch."""
        check_update = True
        for url in cls.candidate_urls(bzr_branch):
            url = cls.tweak_url(url, launchpad)
            if not cls.plausible_launchpad_url(url):
                continue
            lp_branch = launchpad.branches.getByUrl(url=url)
            if lp_branch is not None:
                break
        else:
            if not create_missing:
                raise NoLaunchpadBranch(bzr_branch)
            lp_branch = cls.create_now(launchpad, bzr_branch)
            check_update = False
        return cls(lp_branch, bzr_branch.base, bzr_branch, check_update)

    @classmethod
    def create_now(cls, launchpad, bzr_branch):
        """Create a Bazaar branch on Launchpad for the supplied branch."""
        url = cls.tweak_url(bzr_branch.get_push_location(), launchpad)
        if not cls.plausible_launchpad_url(url):
            raise errors.BzrError('%s is not registered on Launchpad' %
                                  bzr_branch.base)
        bzr_branch.create_clone_on_transport(transport.get_transport(url))
        lp_branch = launchpad.branches.getByUrl(url=url)
        if lp_branch is None:
            raise errors.BzrError('%s is not registered on Launchpad' % url)
        return lp_branch

    def get_dev_focus(self):
        """Return the 'LaunchpadBranch' for the dev focus of this one."""
        lp_branch = self.lp
        if lp_branch.project is None:
            raise errors.BzrError('%s has no product.' %
                                  lp_branch.bzr_identity)
        dev_focus = lp_branch.project.development_focus.branch
        if dev_focus is None:
            raise errors.BzrError('%s has no development focus.' %
                                  lp_branch.bzr_identity)
        return LaunchpadBranch(dev_focus, dev_focus.bzr_identity)

    def update_lp(self):
        """Update the Launchpad copy of this branch."""
        if not self._check_update:
            return
        self.bzr.lock_read()
        try:
            if self.lp.last_scanned_id is not None:
                if self.bzr.last_revision() == self.lp.last_scanned_id:
                    trace.note('%s is already up-to-date.' %
                               self.lp.bzr_identity)
                    return
                graph = self.bzr.repository.get_graph()
                if not graph.is_ancestor(self.lp.last_scanned_id,
                                         self.bzr.last_revision()):
                    raise errors.DivergedBranches(self.bzr, self.push_bzr)
                trace.note('Pushing to %s' % self.lp.bzr_identity)
            self.bzr.push(self.push_bzr)
        finally:
            self.bzr.unlock()

    def find_lca_tree(self, other):
        """Find the revision tree for the LCA of this branch and other.

        :param other: Another LaunchpadBranch
        :return: The RevisionTree of the LCA of this branch and other.
        """
        graph = self.bzr.repository.get_graph(other.bzr.repository)
        lca = graph.find_unique_lca(self.bzr.last_revision(),
                                    other.bzr.last_revision())
        return self.bzr.repository.revision_tree(lca)


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


def canonical_url(object):
    """Return the canonical URL for a branch."""
    scheme, netloc, path, params, query, fragment = urlparse.urlparse(
        str(object.self_link))
    path = '/'.join(path.split('/')[2:])
    netloc = netloc.replace('api.', 'code.')
    return urlparse.urlunparse((scheme, netloc, path, params, query,
                                fragment))
