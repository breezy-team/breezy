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

"""Testing of bzrlib.transport.http.ca_bundle module"""

import os
import sys

import bzrlib
from bzrlib import osutils
from bzrlib.tests import (
    TestCaseInTempDir,
    TestSkipped,
    )
from bzrlib.transport.http import ca_bundle


class TestGetCAPath(TestCaseInTempDir):

    def setUp(self):
        TestCaseInTempDir.setUp(self)
        new_env = {
            'CURL_CA_BUNDLE': None,
            'PATH': None,
            }
        self._old_env = {}
        self.addCleanup(self._restore)
        for name, value in new_env.iteritems():
            self._old_env[name] = osutils.set_or_unset_env(name, None)

    def _restore(self):
        for name, value in self._old_env.iteritems():
            osutils.set_or_unset_env(name, value)

    def _make_file(self, in_dir='.'):
        fname = os.path.join(in_dir, 'curl-ca-bundle.crt')
        f = file(fname,'w')
        f.write('spam')
        f.close()

    def test_found_nothing(self):
        self.assertEqual('', ca_bundle.get_ca_path(use_cache=False))

    def test_env_var(self):
        osutils.set_or_unset_env('CURL_CA_BUNDLE', 'foo.bar')
        self._make_file()
        self.assertEqual('foo.bar', ca_bundle.get_ca_path(use_cache=False))

    def test_in_path(self):
        if sys.platform != 'win32':
            raise TestSkipped('Searching in PATH implemented only for win32')
        os.mkdir('foo')
        in_dir = os.path.join(os.getcwd(), 'foo')
        self._make_file(in_dir=in_dir)
        osutils.set_or_unset_env('PATH', in_dir)
        shouldbe = os.path.join(in_dir, 'curl-ca-bundle.crt')
        self.assertEqual(shouldbe, ca_bundle.get_ca_path(use_cache=False))
