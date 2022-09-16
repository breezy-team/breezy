# Copyright (C) 2011, 2016 Canonical Ltd
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

import threading

from .. import (
    cethread,
    tests,
    )


class TestCatchingExceptionThread(tests.TestCase):

    def test_start_and_join_smoke_test(self):
        def do_nothing():
            pass

        tt = cethread.CatchingExceptionThread(target=do_nothing)
        tt.start()
        tt.join()

    def test_exception_is_re_raised(self):
        class MyException(Exception):
            pass

        def raise_my_exception():
            raise MyException()

        tt = cethread.CatchingExceptionThread(target=raise_my_exception)
        tt.start()
        self.assertRaises(MyException, tt.join)

    def test_join_around_exception(self):
        resume = threading.Event()

        class MyException(Exception):
            pass

        def raise_my_exception():
            # Wait for the test to tell us to resume
            resume.wait()
            # Now we can raise
            raise MyException()

        tt = cethread.CatchingExceptionThread(target=raise_my_exception)
        tt.start()
        tt.join(timeout=0)
        self.assertIs(None, tt.exception)
        resume.set()
        self.assertRaises(MyException, tt.join)

    def test_sync_event(self):
        control = threading.Event()
        in_thread = threading.Event()

        class MyException(Exception):
            pass

        def raise_my_exception():
            # Wait for the test to tell us to resume
            control.wait()
            # Now we can raise
            raise MyException()

        tt = cethread.CatchingExceptionThread(target=raise_my_exception,
                                              sync_event=in_thread)
        tt.start()
        tt.join(timeout=0)
        self.assertIs(None, tt.exception)
        self.assertIs(in_thread, tt.sync_event)
        control.set()
        self.assertRaises(MyException, tt.join)
        self.assertEqual(True, tt.sync_event.is_set())

    def test_switch_and_set(self):
        """Caller can precisely control a thread."""
        control1 = threading.Event()
        control2 = threading.Event()
        control3 = threading.Event()

        class TestThread(cethread.CatchingExceptionThread):

            def __init__(self):
                super(TestThread, self).__init__(target=self.step_by_step)
                self.current_step = 'starting'
                self.step1 = threading.Event()
                self.set_sync_event(self.step1)
                self.step2 = threading.Event()
                self.final = threading.Event()

            def step_by_step(self):
                control1.wait()
                self.current_step = 'step1'
                self.switch_and_set(self.step2)
                control2.wait()
                self.current_step = 'step2'
                self.switch_and_set(self.final)
                control3.wait()
                self.current_step = 'done'

        tt = TestThread()
        tt.start()
        self.assertEqual('starting', tt.current_step)
        control1.set()
        tt.step1.wait()
        self.assertEqual('step1', tt.current_step)
        control2.set()
        tt.step2.wait()
        self.assertEqual('step2', tt.current_step)
        control3.set()
        # We don't wait on tt.final
        tt.join()
        self.assertEqual('done', tt.current_step)

    def test_exception_while_switch_and_set(self):
        control1 = threading.Event()

        class MyException(Exception):
            pass

        class TestThread(cethread.CatchingExceptionThread):

            def __init__(self, *args, **kwargs):
                self.step1 = threading.Event()
                self.step2 = threading.Event()
                super(TestThread, self).__init__(target=self.step_by_step,
                                                 sync_event=self.step1)
                self.current_step = 'starting'
                self.set_sync_event(self.step1)

            def step_by_step(self):
                control1.wait()
                self.current_step = 'step1'
                self.switch_and_set(self.step2)

            def set_sync_event(self, event):
                # We force an exception while trying to set step2
                if event is self.step2:
                    raise MyException()
                super(TestThread, self).set_sync_event(event)

        tt = TestThread()
        tt.start()
        self.assertEqual('starting', tt.current_step)
        control1.set()
        # We now wait on step1 which will be set when catching the exception
        tt.step1.wait()
        self.assertRaises(MyException, tt.pending_exception)
        self.assertIs(tt.step1, tt.sync_event)
        self.assertTrue(tt.step1.is_set())
