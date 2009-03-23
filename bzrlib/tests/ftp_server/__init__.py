# Copyright (C) 2009 Canonical Ltd
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

from bzrlib import tests


try:
    from bzrlib.tests.ftp_server import medusa_based
    # medusa is bogus under python2.6
    medusa_available = sys.version_info < (2, 6)
except ImportError:
    medusa_available = False


try:
    from bzrlib.tests.ftp_server import pyftpdlib_based
    pyftpdlib_available = True
except ImportError:
    pyftpdlib_available = False


class _FTPServerFeature(tests.Feature):
    """Some tests want an FTP Server, check if one is available.

    Right now, the only way this is available is if one of the following is
    installed:

    - 'medusa': http://www.amk.ca/python/code/medusa.html
    - 'pyftpdlib': http://code.google.com/p/pyftpdlib/
    """

    def _probe(self):
        return medusa_available or pyftpdlib_available

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

    def setUp(self, vfs_server=None):
        pass

    def tearDown(self):
        pass

    def get_url(self):
        raise tests.UnavailableFeature(FTPServerFeature)

    def get_bogus_url(self):
        raise tests.UnavailableFeature(FTPServerFeature)


if medusa_available:
    FTPTestServer = medusa_based.FTPTestServer
elif pyftpdlib_available:
    FTPTestServer = pyftpdlib_based.FTPTestServer
else:
    FTPTestServer = UnavailableFTPTestServer
