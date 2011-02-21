# Copyright (C) 2006, 2007, 2009, 2010, 2011 Canonical Ltd
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

"""Tests for display of exceptions."""

import sys

from bzrlib import (
    config,
    controldir,
    errors,
    osutils,
    repository,
    tests,
    )
from bzrlib.repofmt.groupcompress_repo import RepositoryFormat2a

from bzrlib.tests import TestCase


class TestExceptionReporting(TestCase):

    def test_exception_exitcode(self):
        # we must use a subprocess, because the normal in-memory mechanism
        # allows errors to propagate up through the test suite
        out, err = self.run_bzr_subprocess(['assert-fail'],
            universal_newlines=True,
            retcode=errors.EXIT_INTERNAL_ERROR)
        self.assertEqual(4, errors.EXIT_INTERNAL_ERROR)
        self.assertContainsRe(err,
                r'exceptions\.AssertionError: always fails\n')
        self.assertContainsRe(err, r'Bazaar has encountered an internal error')


class TestOptParseBugHandling(TestCase):
    "Test that we handle http://bugs.python.org/issue2931"

    def test_nonascii_optparse(self):
        """Reasonable error raised when non-ascii in option name"""
        if sys.version_info < (2,5):
            error_re = 'no such option'
        else:
            error_re = 'Only ASCII permitted in option names'
        out = self.run_bzr_error([error_re], ['st',u'-\xe4'])


class TestObsoleteRepoFormat(RepositoryFormat2a):

    @classmethod
    def get_format_string(cls):
        return "Test Obsolete Repository Format"

    def is_deprecated(self):
        return True


class TestDeprecationWarning(tests.TestCaseWithTransport):
    """The deprecation warning is controlled via a global variable:
    repository._deprecation_warning_done. As such, it can be emitted only once
    during a bzr invocation, no matter how many repositories are involved.

    It would be better if it was a repo attribute instead but that's far more
    work than I want to do right now -- vila 20091215.
    """

    def setUp(self):
        super(TestDeprecationWarning, self).setUp()
        self.addCleanup(repository.format_registry.remove,
            TestObsoleteRepoFormat)
        repository.format_registry.register(TestObsoleteRepoFormat)
        self.addCleanup(controldir.format_registry.remove, "testobsolete")
        bzrdir.register_metadir(controldir.format_registry, "testobsolete",
            "bzrlib.tests.blackbox.test_exceptions.TestObsoleteRepoFormat",
            branch_format='bzrlib.branch.BzrBranchFormat7',
            tree_format='bzrlib.workingtree.WorkingTreeFormat6',
            deprecated=True,
            help='Same as 2a, but with an obsolete repo format.')
        self.disable_deprecation_warning()

    def enable_deprecation_warning(self, repo=None):
        """repo is not used yet since _deprecation_warning_done is a global"""
        repository._deprecation_warning_done = False

    def disable_deprecation_warning(self, repo=None):
        """repo is not used yet since _deprecation_warning_done is a global"""
        repository._deprecation_warning_done = True

    def make_obsolete_repo(self, path):
        # We don't want the deprecation raising during the repo creation
        format = controldir.format_registry.make_bzrdir("testobsolete")
        tree = self.make_branch_and_tree(path, format=format)
        return tree

    def check_warning(self, present):
        if present:
            check = self.assertContainsRe
        else:
            check = self.assertNotContainsRe
        check(self._get_log(keep_log_file=True), 'WARNING.*bzr upgrade')

    def test_repository_deprecation_warning(self):
        """Old formats give a warning"""
        self.make_obsolete_repo('foo')
        self.enable_deprecation_warning()
        out, err = self.run_bzr('status', working_dir='foo')
        self.check_warning(True)

    def test_repository_deprecation_warning_suppressed_global(self):
        """Old formats give a warning"""
        conf = config.GlobalConfig()
        conf.set_user_option('suppress_warnings', 'format_deprecation')
        self.make_obsolete_repo('foo')
        self.enable_deprecation_warning()
        out, err = self.run_bzr('status', working_dir='foo')
        self.check_warning(False)

    def test_repository_deprecation_warning_suppressed_locations(self):
        """Old formats give a warning"""
        self.make_obsolete_repo('foo')
        conf = config.LocationConfig(osutils.pathjoin(self.test_dir, 'foo'))
        conf.set_user_option('suppress_warnings', 'format_deprecation')
        self.enable_deprecation_warning()
        out, err = self.run_bzr('status', working_dir='foo')
        self.check_warning(False)

    def test_repository_deprecation_warning_suppressed_branch(self):
        """Old formats give a warning"""
        tree = self.make_obsolete_repo('foo')
        conf = tree.branch.get_config()
        conf.set_user_option('suppress_warnings', 'format_deprecation')
        self.enable_deprecation_warning()
        out, err = self.run_bzr('status', working_dir='foo')
        self.check_warning(False)
