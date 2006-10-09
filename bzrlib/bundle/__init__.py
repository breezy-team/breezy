# Copyright (C) 2005, 2006 by Canonical Ltd
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

from bzrlib.bundle.serializer import read_bundle
import bzrlib.errors as errors
import bzrlib.urlutils
import bzrlib.transport


def read_bundle_from_url(url):
    """Read a bundle from a given URL.

    :return: A BundleReader, may raise NotABundle if the target 
            is not a proper bundle.
    """
    url, filename = bzrlib.urlutils.split(url, exclude_trailing_slash=False)
    if not filename:
        # A path to a directory was passed in
        # definitely not a bundle
        raise errors.NotABundle('A directory cannot be a bundle')

    # All of this must be in the try/except
    # Some transports cannot detect that we are trying to read a
    # directory until we actually issue read() on the handle.
    try:
        t = bzrlib.transport.get_transport(url)
        f = t.get(filename)
        return read_bundle(f)
    except (errors.TransportError, errors.PathError), e:
        raise errors.NotABundle(str(e))
    except (IOError,), e:
        # jam 20060707
        # Abstraction leakage, SFTPTransport.get('directory')
        # doesn't always fail at get() time. Sometimes it fails
        # during read. And that raises a generic IOError with
        # just the string 'Failure'
        # StubSFTPServer does fail during get() (because of prefetch) 
        # so it has an opportunity to translate the error.
        raise errors.NotABundle(str(e))

