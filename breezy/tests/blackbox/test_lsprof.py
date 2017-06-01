# Copyright (C) 2005, 2006, 2007 Canonical Ltd
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

from breezy import tests
from breezy.tests import features


class TestLSProf(tests.TestCaseInTempDir):

    _test_needs_features = [features.lsprof_feature]

    def test_file(self):
        out, err = self.run_bzr('--lsprof-file output.callgrind rocks')
        self.assertNotContainsRe(out, 'Profile data written to')
        self.assertContainsRe(err, 'Profile data written to')

    def test_stdout(self):
        out, err = self.run_bzr('--lsprof rocks')
        self.assertContainsRe(out, 'CallCount')
        self.assertNotContainsRe(err, 'Profile data written to')
