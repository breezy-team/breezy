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
    errors,
    )
from bzrlib.transport import (
    get_transport,
    Transport,
    )

from bzrlib.plugins.launchpad.lp_registration import (
    LaunchpadService, ResolveLaunchpadPathRequest)
from bzrlib.plugins.launchpad.account import get_lp_login


class LaunchpadTransport(Transport):
    """lp:/// URL transport

    This transport redirects requests to the real branch location
    after resolving the URL via an XMLRPC request to Launchpad.
    """

    def __init__(self, base):
        super(LaunchpadTransport, self).__init__(base)
        if not (base.startswith('lp:///') or
                base.startswith('lp:') and base[3] != '/'):
            raise errors.InvalidURL(path=base)
        self._base_transport = None

    def _resolve_base(self, _request_factory=ResolveLaunchpadPathRequest):
        """Resolve the base URL for this transport."""
        path = self.base[3:].lstrip('/')
        # Perform an XMLRPC request to resolve the path
        resolve = _request_factory(path)
        service = LaunchpadService()
        try:
            result = resolve.submit(service)
        except xmlrpclib.Fault, fault:
            raise errors.InvalidURL(
                path=self.base, extra=fault.faultString)

        lp_login = get_lp_login()
        for url in result['urls']:
            scheme, netloc, path, query, fragment = urlsplit(url)
            if scheme == 'bzr+ssh' and netloc.endswith('launchpad.net'):
                # Only accept launchpad.net bzr+ssh URLs if we know
                # the user's Launchpad login:
                if lp_login is None:
                    continue
                url = urlunsplit(scheme, '%s@%s' % (lp_login, netloc),
                                 path, query, fragment)
                break
            elif scheme in ['bzr+ssh', 'bzr+http', 'http']:
                break
        else:
            raise errors.InvalidURL(path=self.base,
                                    extra='no supported schemes')
        return url

    @property
    def _transport(self):
        if self._base_transport is None:
            url = self._resolve_base()
            self._base_transport = get_transport(url)
        return self._base_transport

    def abspath(self, relpath):
        """See Transport.abspath()."""
        return self._transport.abspath(relpath)

    def append_file(self, relpath, f, mode=None):
        """See Transport.append_file()."""
        return self._transport.append_file(relpath, f, mode=mode)

    def append_bytes(self, relpath, bytes, mode=None):
        """See Transport.append_bytes()."""
        return self._transport.append_bytes(relpath, f, mode=mode)

    def _can_roundtrip_unix_modebits(self):
        """See Transport._can_roundtrip_unix_modebits()."""
        return self._transport._can_roundtrip_unix_modebits()

    def clone(self, offset=None):
        """See Transport.clone()."""
        # We clone the underlying transport here so that e.g. ".." is
        # relative to the real branch rather than the virtual lp:
        # namespace.
        return self._transport.clone(offset)

    def delete(self, relpath):
        """See Transport.delete()."""
        return self._transport.delete(relpath)

    def delete_tree(self, relpath):
        """See Transport.delete_tree()."""
        return self._transport.delete_tree(relpath)

    def external_url(self):
        """See Transport.external_url()."""
        return self._transport.external_url()

    def get(self, relpath):
        """See Transport.get()."""
        return self._transport.get(relpath)

    def get_smart_client(self):
        return self._transport.get_smart_client()

    def has(self, relpath):
        """See Transport.has()."""
        return self._transport.has(relpath)

    def is_readonly(self):
        """See Transport.is_readonly."""
        return self._transport.is_readonly()

    def mkdir(self, relpath, mode=None):
        """See Transport.mkdir()."""
        return self._transport.mkdir(relpath, mode)

    def open_write_stream(self, relpath, mode=None):
        """See Transport.open_write_stream."""
        return self._transport.open_write_stream(relpath, mode=mode)

    def put_file(self, relpath, f, mode=None):
        """See Transport.put_file()."""
        return self._transport.put_file(relpath, f, mode)

    def put_bytes(self, relpath, bytes, mode=None):
        """See Transport.put_bytes()."""
        return self._transport.put_bytes(relpath, bytes, mode)

    def listable(self):
        """See Transport.listable."""
        return self._transport.listable()

    def iter_files_recursive(self):
        """See Transport.iter_files_recursive()."""
        return self._transport.iter_files_recursive()

    def list_dir(self, relpath):
        """See Transport.list_dir()."""
        return self._transport.list_dir(relpath)

    def _readv(self, relpath, offsets):
        """See Transport._readv."""
        return self._transport._readv(relpath, offsets)

    def recommended_page_size(self):
        """See Transport.recommended_page_size()."""
        return self._transport.recommended_page_size()

    def rename(self, rel_from, rel_to):
        return self._transport.rename(rel_from, rel_to)

    def rmdir(self, relpath):
        """See Transport.rmdir."""
        return self._transport.rmdir(relpath)

    def stat(self, relpath):
        """See Transport.stat()."""
        return self._transport.stat(relpath)

    def lock_read(self, relpath):
        """See Transport.lock_read."""
        return self._transport.lock_read(relpath)

    def lock_write(self, relpath):
        """See Transport.lock_write."""
        return self._transport.lock_write(relpath)


def get_test_permutations():
    # Since this transport doesn't do anything once opened, it's not subjected
    # to the usual transport tests.
    return []
