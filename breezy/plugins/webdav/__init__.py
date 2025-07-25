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

from breezy import transport

from ... import version_info  # noqa: F401

transport.register_urlparse_netloc_protocol("http+webdav")
transport.register_urlparse_netloc_protocol("https+webdav")

transport.register_lazy_transport(
    "https+webdav://", __name__ + ".webdav", "HttpDavTransport"
)
transport.register_lazy_transport(
    "http+webdav://", __name__ + ".webdav", "HttpDavTransport"
)


def load_tests(loader, basic_tests, pattern):
    testmod_names = [
        "tests",
    ]
    for tmn in testmod_names:
        basic_tests.addTest(loader.loadTestsFromName(f"{__name__}.{tmn}"))
    return basic_tests
