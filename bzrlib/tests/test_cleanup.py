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
from bzrlib.cleanup import (
    do_with_cleanups,
    run_cleanup,
    )


class CleanupsTestCase(TestCase):

    def setUp(self):
        super(CleanupsTestCase, self).setUp()
        self.call_log = []

    def no_op_cleanup(self):
        self.call_log.append('no_op_cleanup')

    def assertLogContains(self, regex):
        log = self._get_log(keep_log_file=True)
        self.assertContainsRe(log, regex, re.DOTALL)

    def failing_cleanup(self):
        self.call_log.append('failing_cleanup')
        raise Exception("failing_cleanup goes boom!")


class TestRunCleanup(CleanupsTestCase):

    def test_no_errors(self):
        """The function passed to run_cleanup is run."""
        self.assertTrue(run_cleanup(self.no_op_cleanup))
        self.assertEqual(['no_op_cleanup'], self.call_log)

#    def test_cleanup_with_args_kwargs(self):

    def test_cleanup_error(self):
        """An error from the cleanup function is logged by run_cleanup, but not
        propagated.

        This is there's no way for run_cleanup to know if there's an existing
        exception in this situation::
            try:
              some_func()
            finally:
              run_cleanup(cleanup_func)
        So, the best run_cleanup can do is always log errors but never raise
        them.
        """
        self.assertFalse(run_cleanup(self.failing_cleanup))
        self.assertLogContains('Cleanup failed:.*failing_cleanup goes boom')

    def test_prior_error_cleanup_succeeds(self):
        """Calling run_cleanup from a finally block will not interfere with an
        exception from the try block.
        """
        def failing_operation():
            try:
                1/0
            finally:
                run_cleanup(self.no_op_cleanup)
        self.assertRaises(ZeroDivisionError, failing_operation)
        self.assertEqual(['no_op_cleanup'], self.call_log)

    def test_prior_error_cleanup_fails(self):
        """Calling run_cleanup from a finally block will not interfere with an
        exception from the try block even when the cleanup itself raises an
        exception.

        The cleanup exception will be logged.
        """
        def failing_operation():
            try:
                1/0
            finally:
                run_cleanup(self.failing_cleanup)
        self.assertRaises(ZeroDivisionError, failing_operation)
        self.assertLogContains('Cleanup failed:.*failing_cleanup goes boom')


#class TestRunCleanupReportingErrors(CleanupsTestCase):
#
#    def test_cleanup_error_reported(self):
#        xxx


class TestDoWithCleanups(CleanupsTestCase):

    def trivial_func(self):
        self.call_log.append('trivial_func')
        return 'trivial result'

    def test_runs_func(self):
        """do_with_cleanups runs the function it is given, and returns the
        result.
        """
        result = do_with_cleanups(self.trivial_func, [])
        self.assertEqual('trivial result', result)

    def test_runs_cleanups(self):
        """Cleanup functions are run (in the given order)."""
        cleanup_func_1 = lambda: self.call_log.append('cleanup 1')
        cleanup_func_2 = lambda: self.call_log.append('cleanup 2')
        do_with_cleanups(self.trivial_func, [cleanup_func_1, cleanup_func_2])
        self.assertEqual(
            ['trivial_func', 'cleanup 1', 'cleanup 2'], self.call_log)

    def failing_func(self):
        self.call_log.append('failing_func')
        1/0

    def test_func_error_propagates(self):
        """Errors from the main function are propagated (after running
        cleanups).
        """
        self.assertRaises(
            ZeroDivisionError, do_with_cleanups, self.failing_func,
            [self.no_op_cleanup])
        self.assertEqual(['failing_func', 'no_op_cleanup'], self.call_log)

    def test_func_error_trumps_cleanup_error(self):
        """Errors from the main function a propagated even if a cleanup raises
        an error.

        The cleanup error is be logged.
        """
        self.assertRaises(
            ZeroDivisionError, do_with_cleanups, self.failing_func,
            [self.failing_cleanup])
        self.assertLogContains('Cleanup failed:.*failing_cleanup goes boom')

    def test_func_passes_and_error_from_cleanup(self):
        """An error from a cleanup is propagated when the main function doesn't
        raise an error.  Later cleanups are still executed.
        """
        exc = self.assertRaises(
            Exception, do_with_cleanups, self.trivial_func,
            [self.failing_cleanup, self.no_op_cleanup])
        self.assertEqual('failing_cleanup goes boom!', exc.args[0])
        self.assertEqual(
            ['trivial_func', 'failing_cleanup', 'no_op_cleanup'],
            self.call_log)

    def test_multiple_cleanup_failures(self):
        """When multiple cleanups fail (as tends to happen when something has
        gone wrong), the first error is propagated, and subsequent errors are
        logged.
        """
        class ErrorA(Exception): pass
        class ErrorB(Exception): pass
        def raise_a():
            raise ErrorA()
        def raise_b():
            raise ErrorB()
        self.assertRaises(ErrorA, do_with_cleanups, self.trivial_func,
            [raise_a, raise_b])
        self.assertLogContains('Cleanup failed:.*ErrorB')
        log = self._get_log(keep_log_file=True)
        self.assertFalse('ErrorA' in log)

    def test_func_may_mutate_cleanups(self):
        """The main func may mutate the cleanups before it returns.
        
        This allows a function to gradually add cleanups as it acquires
        resources, rather than planning all the cleanups up-front.
        """
        # XXX: this is cute, but an object with an 'add_cleanup' method may
        # make a better API?
        cleanups_list = []
        def func_that_adds_cleanups():
            self.call_log.append('func_that_adds_cleanups')
            cleanups_list.append(self.no_op_cleanup)
            return 'result'
        result = do_with_cleanups(func_that_adds_cleanups, cleanups_list)
        self.assertEqual('result', result)
        self.assertEqual(
            ['func_that_adds_cleanups', 'no_op_cleanup'], self.call_log)
