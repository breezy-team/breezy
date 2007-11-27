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


"""Transport indirection that uses Launchpad as a directory lookup.

When the transport is opened, it immediately redirects to a url
on Launchpad, which can then either serve the branch itself or redirect
again.
"""

from urlparse import urlsplit, urlunsplit
import xmlrpclib

from bzrlib import (
    debug,
    errors,
    trace,
    urlutils,
    )
from bzrlib.transport import (
    get_transport,
    register_urlparse_netloc_protocol,
    Transport,
    )

from bzrlib.plugins.launchpad.lp_registration import (
    LaunchpadService, ResolveLaunchpadPathRequest)
from bzrlib.plugins.launchpad.account import get_lp_login


# As bzrlib.transport.remote may not be loaded yet, make sure bzr+ssh
# is counted as a netloc protocol.
register_urlparse_netloc_protocol('bzr+ssh')
register_urlparse_netloc_protocol('lp')


class LaunchpadTransport(Transport):
    """lp:/// URL transport

    This transport redirects requests to the real branch location
    after resolving the URL via an XMLRPC request to Launchpad.
    """

    def __init__(self, base):
        super(LaunchpadTransport, self).__init__(base)
        # We only support URLs without a netloc
        netloc = urlsplit(base)[1]
        if netloc != '':
            raise errors.InvalidURL(path=base)

    def _requires_launchpad_login(self, url):
        """Does the URL require a Launchpad login in order to be reached?"""
        scheme, netloc, path, query, fragment = urlsplit(url)
        return scheme == 'bzr+ssh' and (netloc.endswith('launchpad.net') or
                                        netloc.endswith('launchpad.dev'))

    def _resolve(self, abspath,
                 _request_factory=ResolveLaunchpadPathRequest,
                 _lp_login=None):
        """Resolve the base URL for this transport."""
        path = urlsplit(abspath)[2].lstrip('/')
        # Perform an XMLRPC request to resolve the path
        resolve = _request_factory(path)
        service = LaunchpadService()
        try:
            result = resolve.submit(service)
        except xmlrpclib.Fault, fault:
            raise errors.InvalidURL(
                path=abspath, extra=fault.faultString)

        if 'launchpad' in debug.debug_flags:
            trace.mutter("resolve_lp_path(%r) == %r", path, result)

        if _lp_login is None:
            _lp_login = get_lp_login()
        for url in result['urls']:
            scheme, netloc, path, query, fragment = urlsplit(url)
            if self._requires_launchpad_login(url):
                # Only accept launchpad.net bzr+ssh URLs if we know
                # the user's Launchpad login:
                if _lp_login is None:
                    continue
                url = urlunsplit((scheme, '%s@%s' % (_lp_login, netloc),
                                  path, query, fragment))
                break
            else:
                # Use the URL if we can create a transport for it.
                try:
                    get_transport(url)
                except (errors.PathError, errors.TransportError):
                    pass
                else:
                    break
        else:
            raise errors.InvalidURL(path=abspath,
                                    extra='no supported schemes')
        return url

    def _request_redirect(self, relpath):
        source = urlutils.join(self.base, relpath)
        # Split the source location into the branch location, and the
        # extra path components.
        pos = source.find('/.bzr/')
        if pos >= 0:
            branchpath = source[:pos]
            extra = source[pos:]
        else:
            branchpath = source
            extra = ''
        target = self._resolve(branchpath) + extra
        raise errors.RedirectRequested(
            source=source,
            target=target)

    def get(self, relpath):
        """See Transport.get()."""
        self._request_redirect(relpath)

    def mkdir(self, relpath, mode=None):
        """See Transport.mkdir()."""
        self._request_redirect(relpath)


def get_test_permutations():
    # Since this transport doesn't do anything once opened, it's not subjected
    # to the usual transport tests.
    return []
