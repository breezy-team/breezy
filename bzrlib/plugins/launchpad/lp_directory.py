# Copyright (C) 2007-2010 Canonical Ltd
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


"""Directory lookup that uses Launchpad."""

from urlparse import urlsplit
import xmlrpclib

from bzrlib import (
    debug,
    errors,
    trace,
    transport,
    )

from bzrlib.plugins.launchpad.lp_registration import (
    LaunchpadService, ResolveLaunchpadPathRequest)
from bzrlib.plugins.launchpad.account import get_lp_login


# As bzrlib.transport.remote may not be loaded yet, make sure bzr+ssh
# is counted as a netloc protocol.
transport.register_urlparse_netloc_protocol('bzr+ssh')
transport.register_urlparse_netloc_protocol('lp')

_ubuntu_series_shortcuts = {
    'n': 'natty',
    'm': 'maverick',
    'l': 'lucid',
    'k': 'karmic',
    'j': 'jaunty',
    'h': 'hardy',
    'd': 'dapper',
    }


class LaunchpadDirectory(object):

    def _requires_launchpad_login(self, scheme, netloc, path, query,
                                  fragment):
        """Does the URL require a Launchpad login in order to be reached?

        The URL is specified by its parsed components, as returned from
        urlsplit.
        """
        return (scheme in ('bzr+ssh', 'sftp')
                and (netloc.endswith('launchpad.net')
                     or netloc.endswith('launchpad.dev')))

    def look_up(self, name, url):
        """See DirectoryService.look_up"""
        return self._resolve(url)

    def _resolve(self, url,
                 _request_factory=ResolveLaunchpadPathRequest,
                 _lp_login=None):
        """Resolve the base URL for this transport."""
        # Do ubuntu: and debianlp: expansions.
        scheme, netloc, path, query, fragment = urlsplit(url)
        if scheme in ('ubuntu', 'debianlp'):
            if scheme == 'ubuntu':
                distro = 'ubuntu'
                distro_series = _ubuntu_series_shortcuts
            elif scheme == 'debianlp':
                distro = 'debian'
                # No shortcuts for Debian distroseries.
                distro_series = {}
            else:
                raise AssertionError('scheme should be ubuntu: or debianlp:')
            # Split the path.  It's either going to be 'project' or
            # 'series/project', but recognize that it may be a series we don't
            # know about.
            path_parts = path.split('/')
            if len(path_parts) == 1:
                # It's just a project name.
                lp_url_template = 'lp:%(distro)s/%(project)s'
                project = path_parts[0]
                series = None
            elif len(path_parts) == 2:
                # It's a series and project.
                lp_url_template = 'lp:%(distro)s/%(series)s/%(project)s'
                series, project = path_parts
            else:
                # There are either 0 or > 2 path parts, neither of which is
                # supported for these schemes.
                raise errors.InvalidURL('Bad path: %s' % result.path)
            # Expand any series shortcuts, but keep unknown series.
            series = distro_series.get(series, series)
            # Hack the url and let the following do the final resolution.
            url = lp_url_template % dict(
                distro=distro,
                series=series,
                project=project)
            scheme, netloc, path, query, fragment = urlsplit(url)
        service = LaunchpadService.for_url(url)
        if _lp_login is None:
            _lp_login = get_lp_login()
        path = path.strip('/')
        if path.startswith('~/'):
            if _lp_login is None:
                raise errors.InvalidURL(path=url,
                    extra='Cannot resolve "~" to your username.'
                          ' See "bzr help launchpad-login"')
            path = '~' + _lp_login + path[1:]
        resolve = _request_factory(path)
        try:
            result = resolve.submit(service)
        except xmlrpclib.Fault, fault:
            raise errors.InvalidURL(
                path=url, extra=fault.faultString)

        if 'launchpad' in debug.debug_flags:
            trace.mutter("resolve_lp_path(%r) == %r", url, result)

        _warned_login = False
        for url in result['urls']:
            scheme, netloc, path, query, fragment = urlsplit(url)
            if self._requires_launchpad_login(scheme, netloc, path, query,
                                              fragment):
                # Only accept launchpad.net bzr+ssh URLs if we know
                # the user's Launchpad login:
                if _lp_login is not None:
                    break
                if _lp_login is None:
                    if not _warned_login:
                        trace.warning(
'You have not informed bzr of your Launchpad ID, and you must do this to\n'
'write to Launchpad or access private data.  See "bzr help launchpad-login".')
                        _warned_login = True
            else:
                # Use the URL if we can create a transport for it.
                try:
                    transport.get_transport(url)
                except (errors.PathError, errors.TransportError):
                    pass
                else:
                    break
        else:
            raise errors.InvalidURL(path=url, extra='no supported schemes')
        return url


def get_test_permutations():
    # Since this transport doesn't do anything once opened, it's not subjected
    # to the usual transport tests.
    return []
