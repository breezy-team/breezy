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

import re

from bzrlib.tests import TestCase
from bzrlib.cleanup import run_cleanup


class TestCleanup(TestCase):

    def no_op_cleanup(self):
        self.cleanup_was_run = True

    def test_no_errors(self):
        self.assertTrue(run_cleanup(self.no_op_cleanup))
        self.assertTrue(self.cleanup_was_run)

    def assertLogContains(self, regex):
        log = self._get_log(keep_log_file=True)
        self.assertContainsRe(log, regex, re.DOTALL)

    def test_cleanup_error(self):
        # Because python sucks, there's no way for run_cleanup to know if
        # there's an existing exception in this situation:
        #   try:
        #     some_func()
        #   finally:
        #     run_cleanup(cleanup_func)
        # So, the best run_cleanup can do is always log errors but never raise
        # them.
        self.assertFalse(run_cleanup(self.failing_cleanup))
        self.assertLogContains('Cleanup failed:.*failing_cleanup goes boom')

    def test_prior_error_cleanup_succeeds(self):
        def failing_operation():
            try:
                1/0
            finally:
                run_cleanup(self.no_op_cleanup)
        self.assertRaises(ZeroDivisionError, failing_operation)
        self.assertTrue(self.cleanup_was_run)

    def failing_cleanup(self):
        raise Exception("failing_cleanup goes boom!")

    def test_prior_error_cleanup_fails(self):
        def failing_operation():
            try:
                1/0
            finally:
                run_cleanup(self.failing_cleanup)
        self.assertRaises(ZeroDivisionError, failing_operation)
        self.assertLogContains('Cleanup failed:.*failing_cleanup goes boom')

#    def test_cleanup_error_reported(self):



# do_with_cleanups tests to write:
#  - runs func (& returns result)
#  - runs cleanups, in order
#  - error from func propagated with healthy cleanups
#  - error from func trumps error from cleanups (cleanup errs logged, all
#    cleanups run)
#  - healthy func, one error from cleanups => all cleanups run, error
#    propagated (& returns func result)
#  - healthy func, multiple errs from cleanups => all cleanups run, first err
#    propagated, subsequent logged (& returns func result)
#  - ? what about -Dcleanup, does it influnced do_with_cleanups' behaviour?
#  - func appending new cleanups to cleanup_funcs

