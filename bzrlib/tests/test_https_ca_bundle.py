# Copyright (C) 2007, 2009, 2010, 2011 Canonical Ltd
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

"""Testing of bzrlib.transport.http.ca_bundle module"""

import os
import sys

from bzrlib.tests import (
    TestCaseInTempDir,
    TestSkipped,
    )
from bzrlib.transport.http import ca_bundle


class TestGetCAPath(TestCaseInTempDir):

    def setUp(self):
        super(TestGetCAPath, self).setUp()
        self.overrideEnv('CURL_CA_BUNDLE', None)
        self.overrideEnv('PATH', None)

    def _make_file(self, in_dir='.'):
        fname = os.path.join(in_dir, 'curl-ca-bundle.crt')
        f = file(fname,'w')
        f.write('spam')
        f.close()

    def test_found_nothing(self):
        self.assertEqual('', ca_bundle.get_ca_path(use_cache=False))

    def test_env_var(self):
        self.overrideEnv('CURL_CA_BUNDLE', 'foo.bar')
        self._make_file()
        self.assertEqual('foo.bar', ca_bundle.get_ca_path(use_cache=False))

    def test_in_path(self):
        if sys.platform != 'win32':
            raise TestSkipped('Searching in PATH implemented only for win32')
        os.mkdir('foo')
        in_dir = os.path.join(os.getcwd(), 'foo')
        self._make_file(in_dir=in_dir)
        self.overrideEnv('PATH', in_dir)
        shouldbe = os.path.join(in_dir, 'curl-ca-bundle.crt')
        self.assertEqual(shouldbe, ca_bundle.get_ca_path(use_cache=False))
