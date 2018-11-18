# Copyright (C) 2009, 2010 Canonical Ltd
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

from ..cleanup import (
    _do_with_cleanups,
    _run_cleanup,
    ObjectWithCleanups,
    OperationWithCleanups,
    )
from .. import (
    debug,
    tests,
    )


class ErrorA(Exception):
    """Sample exception type A."""


class ErrorB(Exception):
    """Sample exception type B."""


class CleanupsTestCase(tests.TestCase):

    def setUp(self):
        super(CleanupsTestCase, self).setUp()
        self.call_log = []

    def no_op_cleanup(self):
        self.call_log.append('no_op_cleanup')

    def assertLogContains(self, regex):
        self.assertContainsRe(self.get_log(), regex, re.DOTALL)

    def failing_cleanup(self):
        self.call_log.append('failing_cleanup')
        raise Exception("failing_cleanup goes boom!")


class TestRunCleanup(CleanupsTestCase):

    def test_no_errors(self):
        """The function passed to _run_cleanup is run."""
        self.assertTrue(_run_cleanup(self.no_op_cleanup))
        self.assertEqual(['no_op_cleanup'], self.call_log)

    def test_cleanup_with_args_kwargs(self):
        def func_taking_args_kwargs(*args, **kwargs):
            self.call_log.append(('func', args, kwargs))
        _run_cleanup(func_taking_args_kwargs, 'an arg', kwarg='foo')
        self.assertEqual(
            [('func', ('an arg',), {'kwarg': 'foo'})], self.call_log)

    def test_cleanup_error(self):
        """An error from the cleanup function is logged by _run_cleanup, but not
        propagated.

        This is there's no way for _run_cleanup to know if there's an existing
        exception in this situation::
            try:
              some_func()
            finally:
              _run_cleanup(cleanup_func)
        So, the best _run_cleanup can do is always log errors but never raise
        them.
        """
        self.assertFalse(_run_cleanup(self.failing_cleanup))
        self.assertLogContains('Cleanup failed:.*failing_cleanup goes boom')

    def test_cleanup_error_debug_flag(self):
        """The -Dcleanup debug flag causes cleanup errors to be reported to the
        user.
        """
        debug.debug_flags.add('cleanup')
        self.assertFalse(_run_cleanup(self.failing_cleanup))
        self.assertContainsRe(
            self.get_log(),
            "brz: warning: Cleanup failed:.*failing_cleanup goes boom")

    def test_prior_error_cleanup_succeeds(self):
        """Calling _run_cleanup from a finally block will not interfere with an
        exception from the try block.
        """
        def failing_operation():
            try:
                1 / 0
            finally:
                _run_cleanup(self.no_op_cleanup)
        self.assertRaises(ZeroDivisionError, failing_operation)
        self.assertEqual(['no_op_cleanup'], self.call_log)

    def test_prior_error_cleanup_fails(self):
        """Calling _run_cleanup from a finally block will not interfere with an
        exception from the try block even when the cleanup itself raises an
        exception.

        The cleanup exception will be logged.
        """
        def failing_operation():
            try:
                1 / 0
            finally:
                _run_cleanup(self.failing_cleanup)
        self.assertRaises(ZeroDivisionError, failing_operation)
        self.assertLogContains('Cleanup failed:.*failing_cleanup goes boom')


class TestDoWithCleanups(CleanupsTestCase):

    def trivial_func(self):
        self.call_log.append('trivial_func')
        return 'trivial result'

    def test_runs_func(self):
        """_do_with_cleanups runs the function it is given, and returns the
        result.
        """
        result = _do_with_cleanups([], self.trivial_func)
        self.assertEqual('trivial result', result)

    def test_runs_cleanups(self):
        """Cleanup functions are run (in the given order)."""
        cleanup_func_1 = (self.call_log.append, ('cleanup 1',), {})
        cleanup_func_2 = (self.call_log.append, ('cleanup 2',), {})
        _do_with_cleanups([cleanup_func_1, cleanup_func_2], self.trivial_func)
        self.assertEqual(
            ['trivial_func', 'cleanup 1', 'cleanup 2'], self.call_log)

    def failing_func(self):
        self.call_log.append('failing_func')
        1 / 0

    def test_func_error_propagates(self):
        """Errors from the main function are propagated (after running
        cleanups).
        """
        self.assertRaises(
            ZeroDivisionError, _do_with_cleanups,
            [(self.no_op_cleanup, (), {})], self.failing_func)
        self.assertEqual(['failing_func', 'no_op_cleanup'], self.call_log)

    def test_func_error_trumps_cleanup_error(self):
        """Errors from the main function a propagated even if a cleanup raises
        an error.

        The cleanup error is be logged.
        """
        self.assertRaises(
            ZeroDivisionError, _do_with_cleanups,
            [(self.failing_cleanup, (), {})], self.failing_func)
        self.assertLogContains('Cleanup failed:.*failing_cleanup goes boom')

    def test_func_passes_and_error_from_cleanup(self):
        """An error from a cleanup is propagated when the main function doesn't
        raise an error.  Later cleanups are still executed.
        """
        exc = self.assertRaises(
            Exception, _do_with_cleanups,
            [(self.failing_cleanup, (), {}), (self.no_op_cleanup, (), {})],
            self.trivial_func)
        self.assertEqual('failing_cleanup goes boom!', exc.args[0])
        self.assertEqual(
            ['trivial_func', 'failing_cleanup', 'no_op_cleanup'],
            self.call_log)

    def test_multiple_cleanup_failures(self):
        """When multiple cleanups fail (as tends to happen when something has
        gone wrong), the first error is propagated, and subsequent errors are
        logged.
        """
        cleanups = self.make_two_failing_cleanup_funcs()
        self.assertRaises(ErrorA, _do_with_cleanups, cleanups,
                          self.trivial_func)
        self.assertLogContains('Cleanup failed:.*ErrorB')
        # Error A may appear in the log (with Python 3 exception chaining), but
        # Error B should be the last error recorded.
        self.assertContainsRe(
            self.get_log(),
            'Traceback \\(most recent call last\\):\n(  .*\n)+'
            '.*ErrorB: Error B\n$')

    def make_two_failing_cleanup_funcs(self):
        def raise_a():
            raise ErrorA('Error A')

        def raise_b():
            raise ErrorB('Error B')
        return [(raise_a, (), {}), (raise_b, (), {})]

    def test_multiple_cleanup_failures_debug_flag(self):
        debug.debug_flags.add('cleanup')
        cleanups = self.make_two_failing_cleanup_funcs()
        self.assertRaises(ErrorA, _do_with_cleanups, cleanups,
                          self.trivial_func)
        trace_value = self.get_log()
        self.assertContainsRe(
            trace_value, "brz: warning: Cleanup failed:.*Error B\n")
        self.assertEqual(1, trace_value.count('brz: warning:'))

    def test_func_and_cleanup_errors_debug_flag(self):
        debug.debug_flags.add('cleanup')
        cleanups = self.make_two_failing_cleanup_funcs()
        self.assertRaises(ZeroDivisionError, _do_with_cleanups, cleanups,
                          self.failing_func)
        trace_value = self.get_log()
        self.assertContainsRe(
            trace_value, "brz: warning: Cleanup failed:.*Error A\n")
        self.assertContainsRe(
            trace_value, "brz: warning: Cleanup failed:.*Error B\n")
        self.assertEqual(2, trace_value.count('brz: warning:'))

    def test_func_may_mutate_cleanups(self):
        """The main func may mutate the cleanups before it returns.

        This allows a function to gradually add cleanups as it acquires
        resources, rather than planning all the cleanups up-front.  The
        OperationWithCleanups helper relies on this working.
        """
        cleanups_list = []

        def func_that_adds_cleanups():
            self.call_log.append('func_that_adds_cleanups')
            cleanups_list.append((self.no_op_cleanup, (), {}))
            return 'result'
        result = _do_with_cleanups(cleanups_list, func_that_adds_cleanups)
        self.assertEqual('result', result)
        self.assertEqual(
            ['func_that_adds_cleanups', 'no_op_cleanup'], self.call_log)

    def test_cleanup_error_debug_flag(self):
        """The -Dcleanup debug flag causes cleanup errors to be reported to the
        user.
        """
        debug.debug_flags.add('cleanup')
        self.assertRaises(ZeroDivisionError, _do_with_cleanups,
                          [(self.failing_cleanup, (), {})], self.failing_func)
        trace_value = self.get_log()
        self.assertContainsRe(
            trace_value,
            "brz: warning: Cleanup failed:.*failing_cleanup goes boom")
        self.assertEqual(1, trace_value.count('brz: warning:'))


class TestOperationWithCleanups(CleanupsTestCase):

    def test_cleanup_ordering(self):
        """Cleanups are added in LIFO order.

        So cleanups added before run is called are run last, and the last
        cleanup added during the func is run first.
        """
        call_log = []

        def func(op, foo):
            call_log.append(('func called', foo))
            op.add_cleanup(call_log.append, 'cleanup 2')
            op.add_cleanup(call_log.append, 'cleanup 1')
            return 'result'
        owc = OperationWithCleanups(func)
        owc.add_cleanup(call_log.append, 'cleanup 4')
        owc.add_cleanup(call_log.append, 'cleanup 3')
        result = owc.run('foo')
        self.assertEqual('result', result)
        self.assertEqual(
            [('func called', 'foo'), 'cleanup 1', 'cleanup 2', 'cleanup 3',
             'cleanup 4'], call_log)


class SampleWithCleanups(ObjectWithCleanups):
    """Minimal ObjectWithCleanups subclass."""


class TestObjectWithCleanups(tests.TestCase):

    def test_object_with_cleanups(self):
        a = []
        s = SampleWithCleanups()
        s.add_cleanup(a.append, 42)
        s.cleanup_now()
        self.assertEqual(a, [42])
