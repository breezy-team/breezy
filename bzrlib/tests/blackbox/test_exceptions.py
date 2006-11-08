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

from bzrlib import bzrdir, repository, trace
from bzrlib.tests import TestCaseInTempDir, TestCase
from bzrlib.errors import NotBranchError


class TestExceptionReporting(TestCase):

    def test_report_exception(self):
        """When an error occurs, display bug report details to stderr"""
        old_use_apport = trace._use_apport
        trace._use_apport = False
        try:
            self.run_bzr_error(
                [
                    r'bzr: ERROR: exceptions\.AssertionError: always fails\n',
                    r'please send this report to',
                ],
                "assert-fail")
        finally:
            trace._use_apport = old_use_apport

    def test_apport_report(self):
        # If apport is present, bzr should tell the user the url to visit to 
        # file the bug, and the file to upload as an attachment containing the
        # backtrace, installed versions, plugin information etc.
        # the file contents are tested in the library tests, this test just
        # checks the ui.
        try:
            import apport_utils
        except ImportError:
            raise TestSkipped('apport not present')
        out, err = self.run_bzr_error(
            [
                r'bzr: ERROR: exceptions\.AssertionError: always fails\n',
                r'This is an unexpected error within bzr and we would appreciate a bug report.\n',
                r'bzr has written a crash report file that will assist our debugging of this\n',
                r'in the file /tmp/bzr-crash-[a-zA-Z0-9_]+\.txt\n',
                r'This is a plain text file, whose contents you can check if you have privacy\n',
                r'concerns. We gather the package data about bzr, your command line, plugins\n',
                r'And the backtrace from within bzr. If you had a password in the URL you\n',
                r'provided to bzr, you should edit that file to remove the password.\n',
                r'\*\* To file a bug for this please visit our bugtracker at the URL \n',
                r'"https://launchpad.net/products/bzr/\+filebug" and report a bug describing\n',
                r'what you were attempting and attach the bzr-crash file mentioned above.\n',
                r'Alternatively you can email bazaar-ng@lists.canonical.com with the same\n',
                r'description and attach the bzr-crash file to the email\.\n',
            ],
            "assert-fail")
        self.assertEqualDiff('', out)


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

