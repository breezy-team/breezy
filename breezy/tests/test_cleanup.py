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
    ExitStack,
    )
from ..sixish import PY3
from .. import (
    tests,
    )

from contextlib import contextmanager


check_exception_chaining = PY3


# Imported from contextlib2's test_contextlib2.py
# Copyright: Copyright (c) 2001, 2002, 2003, 2004, 2005, 2006, 2007, 2008,
#   2009, 2010, 2011 Python Software Foundation
#
# PYTHON SOFTWARE FOUNDATION LICENSE VERSION 2
# --------------------------------------------
# .
# 1. This LICENSE AGREEMENT is between the Python Software Foundation
# ("PSF"), and the Individual or Organization ("Licensee") accessing and
# otherwise using this software ("Python") in source or binary form and
# its associated documentation.
# .
# 2. Subject to the terms and conditions of this License Agreement, PSF hereby
# grants Licensee a nonexclusive, royalty-free, world-wide license to reproduce,
# analyze, test, perform and/or display publicly, prepare derivative works,
# distribute, and otherwise use Python alone or in any derivative version,
# provided, however, that PSF's License Agreement and PSF's notice of copyright,
# i.e., "Copyright (c) 2001, 2002, 2003, 2004, 2005, 2006, 2007, 2008, 2009, 2010,
# 2011 Python Software Foundation; All Rights Reserved" are retained in Python
# alone or in any derivative version prepared by Licensee.
# .
# 3. In the event Licensee prepares a derivative work that is based on
# or incorporates Python or any part thereof, and wants to make
# the derivative work available to others as provided herein, then
# Licensee hereby agrees to include in any such work a brief summary of
# the changes made to Python.
# .
# 4. PSF is making Python available to Licensee on an "AS IS"
# basis.  PSF MAKES NO REPRESENTATIONS OR WARRANTIES, EXPRESS OR
# IMPLIED.  BY WAY OF EXAMPLE, BUT NOT LIMITATION, PSF MAKES NO AND
# DISCLAIMS ANY REPRESENTATION OR WARRANTY OF MERCHANTABILITY OR FITNESS
# FOR ANY PARTICULAR PURPOSE OR THAT THE USE OF PYTHON WILL NOT
# INFRINGE ANY THIRD PARTY RIGHTS.
# .
# 5. PSF SHALL NOT BE LIABLE TO LICENSEE OR ANY OTHER USERS OF PYTHON
# FOR ANY INCIDENTAL, SPECIAL, OR CONSEQUENTIAL DAMAGES OR LOSS AS
# A RESULT OF MODIFYING, DISTRIBUTING, OR OTHERWISE USING PYTHON,
# OR ANY DERIVATIVE THEREOF, EVEN IF ADVISED OF THE POSSIBILITY THEREOF.
# .
# 6. This License Agreement will automatically terminate upon a material
# breach of its terms and conditions.
# .
# 7. Nothing in this License Agreement shall be deemed to create any
# relationship of agency, partnership, or joint venture between PSF and
# Licensee.  This License Agreement does not grant permission to use PSF
# trademarks or trade name in a trademark sense to endorse or promote
# products or services of Licensee, or any third party.
# .
# 8. By copying, installing or otherwise using Python, Licensee
# agrees to be bound by the terms and conditions of this License
# Agreement.


class TestExitStack(tests.TestCase):

    def test_no_resources(self):
        with ExitStack():
            pass

    def test_callback(self):
        expected = [
            ((), {}),
            ((1,), {}),
            ((1, 2), {}),
            ((), dict(example=1)),
            ((1,), dict(example=1)),
            ((1, 2), dict(example=1)),
        ]
        result = []
        def _exit(*args, **kwds):
            """Test metadata propagation"""
            result.append((args, kwds))
        with ExitStack() as stack:
            for args, kwds in reversed(expected):
                if args and kwds:
                    f = stack.callback(_exit, *args, **kwds)
                elif args:
                    f = stack.callback(_exit, *args)
                elif kwds:
                    f = stack.callback(_exit, **kwds)
                else:
                    f = stack.callback(_exit)
                self.assertIs(f, _exit)
        self.assertEqual(result, expected)

    def test_push(self):
        exc_raised = ZeroDivisionError
        def _expect_exc(exc_type, exc, exc_tb):
            self.assertIs(exc_type, exc_raised)
        def _suppress_exc(*exc_details):
            return True
        def _expect_ok(exc_type, exc, exc_tb):
            self.assertIsNone(exc_type)
            self.assertIsNone(exc)
            self.assertIsNone(exc_tb)
        class ExitCM(object):
            def __init__(self, check_exc):
                self.check_exc = check_exc
            def __enter__(self):
                self.fail("Should not be called!")
            def __exit__(self, *exc_details):
                self.check_exc(*exc_details)
        with ExitStack() as stack:
            stack.push(_expect_ok)
            cm = ExitCM(_expect_ok)
            stack.push(cm)
            stack.push(_suppress_exc)
            cm = ExitCM(_expect_exc)
            stack.push(cm)
            stack.push(_expect_exc)
            stack.push(_expect_exc)
            1 / 0

    def test_enter_context(self):
        class TestCM(object):
            def __enter__(self):
                result.append(1)
            def __exit__(self, *exc_details):
                result.append(3)

        result = []
        cm = TestCM()
        with ExitStack() as stack:
            @stack.callback  # Registered first => cleaned up last
            def _exit():
                result.append(4)
            self.assertIsNotNone(_exit)
            stack.enter_context(cm)
            result.append(2)
        self.assertEqual(result, [1, 2, 3, 4])

    def test_close(self):
        result = []
        with ExitStack() as stack:
            @stack.callback
            def _exit():
                result.append(1)
            self.assertIsNotNone(_exit)
            stack.close()
            result.append(2)
        self.assertEqual(result, [1, 2])

    def test_pop_all(self):
        result = []
        with ExitStack() as stack:
            @stack.callback
            def _exit():
                result.append(3)
            self.assertIsNotNone(_exit)
            new_stack = stack.pop_all()
            result.append(1)
        result.append(2)
        new_stack.close()
        self.assertEqual(result, [1, 2, 3])

    def test_exit_raise(self):
        def _raise():
            with ExitStack() as stack:
                stack.push(lambda *exc: False)
                1 / 0
        self.assertRaises(ZeroDivisionError, _raise)

    def test_exit_suppress(self):
        with ExitStack() as stack:
            stack.push(lambda *exc: True)
            1 / 0

    def test_exit_exception_chaining_reference(self):
        # Sanity check to make sure that ExitStack chaining matches
        # actual nested with statements
        class RaiseExc:
            def __init__(self, exc):
                self.exc = exc
            def __enter__(self):
                return self
            def __exit__(self, *exc_details):
                raise self.exc

        class RaiseExcWithContext:
            def __init__(self, outer, inner):
                self.outer = outer
                self.inner = inner
            def __enter__(self):
                return self
            def __exit__(self, *exc_details):
                try:
                    raise self.inner
                except:
                    raise self.outer

        class SuppressExc:
            def __enter__(self):
                return self
            def __exit__(self, *exc_details):
                self.__class__.saved_details = exc_details
                return True

        try:
            with RaiseExc(IndexError):
                with RaiseExcWithContext(KeyError, AttributeError):
                    with SuppressExc():
                        with RaiseExc(ValueError):
                            1 / 0
        except IndexError as exc:
            if check_exception_chaining:
                self.assertIsInstance(exc.__context__, KeyError)
                self.assertIsInstance(exc.__context__.__context__, AttributeError)
                # Inner exceptions were suppressed
                self.assertIsNone(exc.__context__.__context__.__context__)
        else:
            self.fail("Expected IndexError, but no exception was raised")
        # Check the inner exceptions
        inner_exc = SuppressExc.saved_details[1]
        self.assertIsInstance(inner_exc, ValueError)
        if check_exception_chaining:
            self.assertIsInstance(inner_exc.__context__, ZeroDivisionError)

    def test_exit_exception_chaining(self):
        # Ensure exception chaining matches the reference behaviour
        def raise_exc(exc):
            raise exc

        saved_details = [None]
        def suppress_exc(*exc_details):
            saved_details[0] = exc_details
            return True

        try:
            with ExitStack() as stack:
                stack.callback(raise_exc, IndexError)
                stack.callback(raise_exc, KeyError)
                stack.callback(raise_exc, AttributeError)
                stack.push(suppress_exc)
                stack.callback(raise_exc, ValueError)
                1 / 0
        except IndexError as exc:
            if check_exception_chaining:
                self.assertIsInstance(exc.__context__, KeyError)
                self.assertIsInstance(exc.__context__.__context__, AttributeError)
                # Inner exceptions were suppressed
                self.assertIsNone(exc.__context__.__context__.__context__)
        else:
            self.fail("Expected IndexError, but no exception was raised")
        # Check the inner exceptions
        inner_exc = saved_details[0][1]
        self.assertIsInstance(inner_exc, ValueError)
        if check_exception_chaining:
            self.assertIsInstance(inner_exc.__context__, ZeroDivisionError)

    def test_exit_exception_non_suppressing(self):
        # http://bugs.python.org/issue19092
        def raise_exc(exc):
            raise exc

        def suppress_exc(*exc_details):
            return True

        try:
            with ExitStack() as stack:
                stack.callback(lambda: None)
                stack.callback(raise_exc, IndexError)
        except Exception as exc:
            self.assertIsInstance(exc, IndexError)
        else:
            self.fail("Expected IndexError, but no exception was raised")

        try:
            with ExitStack() as stack:
                stack.callback(raise_exc, KeyError)
                stack.push(suppress_exc)
                stack.callback(raise_exc, IndexError)
        except Exception as exc:
            self.assertIsInstance(exc, KeyError)
        else:
            self.fail("Expected KeyError, but no exception was raised")

    def test_exit_exception_with_correct_context(self):
        # http://bugs.python.org/issue20317
        @contextmanager
        def gets_the_context_right(exc):
            try:
                yield
            finally:
                raise exc

        exc1 = Exception(1)
        exc2 = Exception(2)
        exc3 = Exception(3)
        exc4 = Exception(4)

        # The contextmanager already fixes the context, so prior to the
        # fix, ExitStack would try to fix it *again* and get into an
        # infinite self-referential loop
        try:
            with ExitStack() as stack:
                stack.enter_context(gets_the_context_right(exc4))
                stack.enter_context(gets_the_context_right(exc3))
                stack.enter_context(gets_the_context_right(exc2))
                raise exc1
        except Exception as exc:
            self.assertIs(exc, exc4)
            if check_exception_chaining:
                self.assertIs(exc.__context__, exc3)
                self.assertIs(exc.__context__.__context__, exc2)
                self.assertIs(exc.__context__.__context__.__context__, exc1)
                self.assertIsNone(
                    exc.__context__.__context__.__context__.__context__)

    def test_exit_exception_with_existing_context(self):
        # Addresses a lack of test coverage discovered after checking in a
        # fix for issue 20317 that still contained debugging code.
        def raise_nested(inner_exc, outer_exc):
            try:
                raise inner_exc
            finally:
                raise outer_exc
        exc1 = Exception(1)
        exc2 = Exception(2)
        exc3 = Exception(3)
        exc4 = Exception(4)
        exc5 = Exception(5)
        try:
            with ExitStack() as stack:
                stack.callback(raise_nested, exc4, exc5)
                stack.callback(raise_nested, exc2, exc3)
                raise exc1
        except Exception as exc:
            self.assertIs(exc, exc5)
            if check_exception_chaining:
                self.assertIs(exc.__context__, exc4)
                self.assertIs(exc.__context__.__context__, exc3)
                self.assertIs(exc.__context__.__context__.__context__, exc2)
                self.assertIs(
                    exc.__context__.__context__.__context__.__context__, exc1)
                self.assertIsNone(
                    exc.__context__.__context__.__context__.__context__.__context__)

    def test_body_exception_suppress(self):
        def suppress_exc(*exc_details):
            return True
        try:
            with ExitStack() as stack:
                stack.push(suppress_exc)
                1 / 0
        except IndexError as exc:
            self.fail("Expected no exception, got IndexError")

    def test_exit_exception_chaining_suppress(self):
        with ExitStack() as stack:
            stack.push(lambda *exc: True)
            stack.push(lambda *exc: 1 / 0)
            stack.push(lambda *exc: {}[1])

    def test_excessive_nesting(self):
        # The original implementation would die with RecursionError here
        with ExitStack() as stack:
            for i in range(10000):
                stack.callback(int)

    def test_instance_bypass(self):
        class Example(object):
            pass
        cm = Example()
        cm.__exit__ = object()
        stack = ExitStack()
        self.assertRaises(AttributeError, stack.enter_context, cm)
        stack.push(cm)
        # self.assertIs(stack._exit_callbacks[-1], cm)
