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

"""
Facilities to use ftp test servers.
"""

import sys

from breezy import tests
from breezy.tests import (
    features,
    )


try:
    import pyftpdlib
except ImportError:
    pyftpdlib_available = False
else:
    pyftpdlib_available = True


class _FTPServerFeature(features.Feature):
    """Some tests want an FTP Server, check if one is available.

    Right now, the only way this is available is if one of the following is
    installed:

    - 'pyftpdlib': http://code.google.com/p/pyftpdlib/
    """

    def _probe(self):
        return pyftpdlib_available

    def feature_name(self):
        return 'FTPServer'


FTPServerFeature = _FTPServerFeature()


class UnavailableFTPTestServer(object):
    """Dummy ftp test server.

    This allows the test suite report the number of tests needing that
    feature. We raise UnavailableFeature from methods before the test server is
    being used. Doing so in the setUp method has bad side-effects (tearDown is
    never called).
    """

    def start_server(self, vfs_server=None):
        pass

    def stop_server(self):
        pass

    def get_url(self):
        raise tests.UnavailableFeature(FTPServerFeature)

    def get_bogus_url(self):
        raise tests.UnavailableFeature(FTPServerFeature)


if pyftpdlib_available:
    from . import pyftpdlib_based
    FTPTestServer = pyftpdlib_based.FTPTestServer
else:
    FTPTestServer = UnavailableFTPTestServer
