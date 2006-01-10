# Copyright (C) 2005 by Canonical Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

import os


from bzrlib.tests import TestCaseInTempDir
from bzrlib.transport.http import HttpServer
from bzrlib.osutils import relpath


class TestCaseWithWebserver(TestCaseInTempDir):
    """Derived class that starts a localhost-only webserver.
    (in addition to what TestCaseInTempDir does).

    This is useful for testing things with a web server.
    """

    def get_remote_url(self, path):

        if os.path.isabs(path):
            remote_path = relpath(self.test_dir, path)
        else:
            remote_path = path
        return self.server.get_url() + remote_path

    def setUp(self):
        super(TestCaseWithWebserver, self).setUp()
        self.server = HttpServer()
        self.server.setUp()

    def tearDown(self):
        try:
            self.server.tearDown()
        finally:
            super(TestCaseWithWebserver, self).tearDown()
