# Copyright (C) 2006 Canonical Ltd
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

"""Tests for display of exceptions."""

import os
import sys

from bzrlib import bzrdir, repository

from bzrlib.tests import TestCaseInTempDir, TestCase
from bzrlib.errors import NotBranchError

class TestExceptionReporting(TestCase):

    def test_report_exception(self):
        """When an error occurs, display bug report details to stderr"""
        out, err = self.run_bzr("assert-fail", retcode=3)
        self.assertContainsRe(err,
                r'bzr: ERROR: exceptions\.AssertionError: always fails\n')
        self.assertContainsRe(err, r'please send this report to')

    # TODO: assert-fail doesn't need to always be present; we could just
    # register (and unregister) it from tests that want to touch it.
    #
    # TODO: Some kind of test for the feature of invoking pdb
    

class TestDeprecationWarning(TestCaseInTempDir):

    def test_repository_deprecation_warning(self):
        """Old formats give a warning"""
        # the warning's normally off for testing but we reenable it
        repository._deprecation_warning_done = False
        try:
            os.mkdir('foo')
            bzrdir.BzrDirFormat5().initialize('foo')
            out, err = self.run_bzr("status", "foo")
            self.assertContainsRe(self._get_log(keep_log_file=True),
                                  "bzr upgrade")
        finally:
            repository._deprecation_warning_done = True

