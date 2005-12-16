# Copyright (C) 2005 by Canonical Ltd
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as published by
# the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Tests for the test framework
"""

import os
import sys
import unittest

from bzrlib.tests import TestCase, _load_module_by_name, \
        TestSkipped
import bzrlib.tests


class SelftestTests(TestCase):

    def test_import_tests(self):
        mod = _load_module_by_name('bzrlib.tests.test_selftest')
        self.assertEqual(mod.SelftestTests, SelftestTests)

    def test_import_test_failure(self):
        self.assertRaises(ImportError,
                          _load_module_by_name,
                          'bzrlib.no-name-yet')


class MetaTestLog(TestCase):
    def test_logging(self):
        """Test logs are captured when a test fails."""
        self.log('a test message')
        self._log_file.flush()
        self.assertContainsRe(self._get_log(), 'a test message\n')


class TestSkippedTest(TestCase):
    """Try running a test which is skipped, make sure it's reported properly."""
    def test_skipped_test(self):
        # must be hidden in here so it's not run as a real test
        def skipping_test():
            raise TestSkipped('test intentionally skipped')
        runner = bzrlib.tests.TextTestRunner(stream=self._log_file)
        test = unittest.FunctionTestCase(skipping_test)
        result = runner.run(test)
        self.assertTrue(result.wasSuccessful())
