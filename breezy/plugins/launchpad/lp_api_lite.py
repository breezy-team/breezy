# Copyright (C) 2011 Canonical Ltd
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

"""Tools for dealing with the Launchpad API without using launchpadlib.

The api itself is a RESTful interface, so we can make HTTP queries directly.
loading launchpadlib itself has a fairly high overhead (just calling
Launchpad.login_anonymously() takes a 500ms once the WADL is cached, and 5+s to
get the WADL.
"""

from __future__ import absolute_import

try:
    # Use simplejson if available, much faster, and can be easily installed in
    # older versions of python
    import simplejson as json
except ImportError:
    # Is present since python 2.6
    try:
        import json
    except ImportError:
        json = None

import time
try:
    from urllib.parse import urlencode
except ImportError:  # python < 3
    from urllib import urlencode
try:
    import urllib.request as urllib2
except ImportError:  # python < 3
    import urllib2

from ... import (
    revision,
    trace,
    )


class LatestPublication(object):
    """Encapsulate how to find the latest publication for a given project."""

    LP_API_ROOT = 'https://api.launchpad.net/1.0'

    def __init__(self, archive, series, project):
        self._archive = archive
        self._project = project
        self._setup_series_and_pocket(series)

    def _setup_series_and_pocket(self, series):
        """Parse the 'series' info into a series and a pocket.

        eg::
            _setup_series_and_pocket('natty-proposed')
            => _series == 'natty'
               _pocket == 'Proposed'
        """
        self._series = series
        self._pocket = None
        if self._series is not None and '-' in self._series:
            self._series, self._pocket = self._series.split('-', 1)
            self._pocket = self._pocket.title()
        else:
            self._pocket = 'Release'

    def _archive_URL(self):
        """Return the Launchpad 'Archive' URL that we will query.
        This is everything in the URL except the query parameters.
        """
        return '%s/%s/+archive/primary' % (self.LP_API_ROOT, self._archive)

    def _publication_status(self):
        """Handle the 'status' field.
        It seems that Launchpad tracks all 'debian' packages as 'Pending', while
        for 'ubuntu' we care about the 'Published' packages.
        """
        if self._archive == 'debian':
            # Launchpad only tracks debian packages as "Pending", it doesn't mark
            # them Published
            return 'Pending'
        return 'Published'

    def _query_params(self):
        """Get the parameters defining our query.
        This defines the actions we are making against the archive.
        :return: A dict of query parameters.
        """
        params = {'ws.op': 'getPublishedSources',
                  'exact_match': 'true',
                  # If we need to use "" shouldn't we quote the project somehow?
                  'source_name': '"%s"' % (self._project,),
                  'status': self._publication_status(),
                  # We only need the latest one, the results seem to be properly
                  # most-recent-debian-version sorted
                  'ws.size': '1',
                  }
        if self._series is not None:
            params['distro_series'] = '/%s/%s' % (self._archive, self._series)
        if self._pocket is not None:
            params['pocket'] = self._pocket
        return params

    def _query_URL(self):
        """Create the full URL that we need to query, including parameters."""
        params = self._query_params()
        # We sort to give deterministic results for testing
        encoded = urlencode(sorted(params.items()))
        return '%s?%s' % (self._archive_URL(), encoded)

    def _get_lp_info(self):
        """Place an actual HTTP query against the Launchpad service."""
        if json is None:
            return None
        query_URL = self._query_URL()
        try:
            req = urllib2.Request(query_URL)
            response = urllib2.urlopen(req)
            json_info = response.read()
        # TODO: We haven't tested the HTTPError
        except (urllib2.URLError, urllib2.HTTPError) as e:
            trace.mutter('failed to place query to %r' % (query_URL,))
            trace.log_exception_quietly()
            return None
        return json_info

    def _parse_json_info(self, json_info):
        """Parse the json response from Launchpad into objects."""
        if json is None:
            return None
        try:
            return json.loads(json_info)
        except Exception:
            trace.mutter('Failed to parse json info: %r' % (json_info,))
            trace.log_exception_quietly()
            return None

    def get_latest_version(self):
        """Get the latest published version for the given package."""
        json_info = self._get_lp_info()
        if json_info is None:
            return None
        info = self._parse_json_info(json_info)
        if info is None:
            return None
        try:
            entries = info['entries']
            if len(entries) == 0:
                return None
            return entries[0]['source_package_version']
        except KeyError:
            trace.log_exception_quietly()
            return None

    def place(self):
        """Text-form for what location this represents.

        Example::
            ubuntu, natty => Ubuntu Natty
            ubuntu, natty-proposed => Ubuntu Natty Proposed
        :return: A string representing the location we are checking.
        """
        place = self._archive
        if self._series is not None:
            place = '%s %s' % (place, self._series)
        if self._pocket is not None and self._pocket != 'Release':
            place = '%s %s' % (place, self._pocket)
        return place.title()


def get_latest_publication(archive, series, project):
    """Get the most recent publication for a given project.

    :param archive: Either 'ubuntu' or 'debian'
    :param series: Something like 'natty', 'sid', etc. Can be set as None. Can
        also include a pocket such as 'natty-proposed'.
    :param project: Something like 'bzr'
    :return: A version string indicating the most-recent version published in
        Launchpad. Might return None if there is an error.
    """
    lp = LatestPublication(archive, series, project)
    return lp.get_latest_version()


def get_most_recent_tag(tag_dict, the_branch):
    """Get the most recent revision that has been tagged."""
    # Note: this assumes that a given rev won't get tagged multiple times. But
    #       it should be valid for the package importer branches that we care
    #       about
    reverse_dict = dict((rev, tag) for tag, rev in tag_dict.items())
    with the_branch.lock_read():
        last_rev = the_branch.last_revision()
        graph = the_branch.repository.get_graph()
        stop_revisions = (None, revision.NULL_REVISION)
        for rev_id in graph.iter_lefthand_ancestry(last_rev, stop_revisions):
            if rev_id in reverse_dict:
                return reverse_dict[rev_id]


def _get_newest_versions(the_branch, latest_pub):
    """Get information about how 'fresh' this packaging branch is.

    :param the_branch: The Branch to check
    :param latest_pub: The LatestPublication used to check most recent
        published version.
    :return: (latest_ver, branch_latest_ver)
    """
    t = time.time()
    latest_ver = latest_pub.get_latest_version()
    t_latest_ver = time.time() - t
    trace.mutter('LatestPublication.get_latest_version took: %.3fs'
                 % (t_latest_ver,))
    if latest_ver is None:
        return None, None
    t = time.time()
    tags = the_branch.tags.get_tag_dict()
    t_tag_dict = time.time() - t
    trace.mutter('LatestPublication.get_tag_dict took: %.3fs' % (t_tag_dict,))
    if latest_ver in tags:
        # branch might have a newer tag, but we don't really care
        return latest_ver, latest_ver
    else:
        best_tag = get_most_recent_tag(tags, the_branch)
        return latest_ver, best_tag


def _report_freshness(latest_ver, branch_latest_ver, place, verbosity,
                      report_func):
    """Report if the branch is up-to-date."""
    if latest_ver is None:
        if verbosity == 'all':
            report_func('Most recent %s version: MISSING' % (place,))
        elif verbosity == 'short':
            report_func('%s is MISSING a version' % (place,))
        return
    elif latest_ver == branch_latest_ver:
        if verbosity == 'minimal':
            return
        elif verbosity == 'short':
            report_func('%s is CURRENT in %s' % (latest_ver, place))
        else:
            report_func('Most recent %s version: %s\n'
                        'Packaging branch status: CURRENT'
                        % (place, latest_ver))
    else:
        if verbosity in ('minimal', 'short'):
            if branch_latest_ver is None:
                branch_latest_ver = 'Branch'
            report_func('%s is OUT-OF-DATE, %s has %s'
                        % (branch_latest_ver, place, latest_ver))
        else:
            report_func('Most recent %s version: %s\n'
                        'Packaging branch version: %s\n'
                        'Packaging branch status: OUT-OF-DATE'
                        % (place, latest_ver, branch_latest_ver))


def report_freshness(the_branch, verbosity, latest_pub):
    """Report to the user how up-to-date the packaging branch is.

    :param the_branch: A Branch object
    :param verbosity: Can be one of:
        off: Do not print anything, and skip all checks.
        all: Print all information that we have in a verbose manner, this
             includes misses, etc.
        short: Print information, but only one-line summaries
        minimal: Only print a one-line summary when the package branch is
                 out-of-date
    :param latest_pub: A LatestPublication instance
    """
    if verbosity == 'off':
        return
    if verbosity is None:
        verbosity = 'all'
    latest_ver, branch_ver = _get_newest_versions(the_branch, latest_pub)
    place = latest_pub.place()
    _report_freshness(latest_ver, branch_ver, place, verbosity,
                      trace.note)
