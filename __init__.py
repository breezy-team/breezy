# Copyright (C) 2006-2009, 2011, 2012 Canonical Ltd
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

"""An http transport, using webdav to allow pushing.

This defines the HttpWebDAV transport, which implement the necessary
handling of WebDAV to allow pushing on an http server.
"""

import bzrlib
import bzrlib.api

from info import (
    bzr_plugin_version as version_info,
    bzr_compatible_versions,
    )

if version_info[3] == 'final':
    version_string = '%d.%d.%d' % version_info[:3]
else:
    version_string = '%d.%d.%d%s%d' % version_info
__version__ = version_string

if bzrlib.version_info >= (2, 5):
    # We need bzr < 2.5
    from bzrlib import (
        errors,
        trace,
        )
    raise errors.BzrError("not installing http[s]+webdav://."
                          " It requires 2.4 <= bzr < 2.5, you're using %s"
                          % (bzrlib.version_info,))


bzrlib.api.require_any_api(bzrlib, bzr_compatible_versions)

from bzrlib import transport

transport.register_urlparse_netloc_protocol('http+webdav')
transport.register_urlparse_netloc_protocol('https+webdav')

transport.register_lazy_transport(
    'https+webdav://', 'bzrlib.plugins.webdav.webdav', 'HttpDavTransport')
transport.register_lazy_transport(
    'http+webdav://', 'bzrlib.plugins.webdav.webdav', 'HttpDavTransport')


def load_tests(basic_tests, module, loader):
    testmod_names = [
        'tests',
        ]
    basic_tests.addTest(loader.loadTestsFromModuleNames(
            ["%s.%s" % (__name__, tmn) for tmn in testmod_names]))
    return basic_tests

