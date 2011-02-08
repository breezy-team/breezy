# Copyright (C) 2010, 2011 Canonical Ltd
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

from bzrlib import (
    tests,
    thread,
    )


class TestThreadWithException(tests.TestCase):

    def test_start_and_join_smoke_test(self):
        def do_nothing():
            pass

        tt = thread.ThreadWithException(target=do_nothing)
        tt.start()
        tt.join()

    def test_exception_is_re_raised(self):
        class MyException(Exception):
            pass

        def raise_my_exception():
            raise MyException()

        tt = thread.ThreadWithException(target=raise_my_exception)
        tt.start()
        self.assertRaises(MyException, tt.join)

    def test_join_when_no_exception(self):
        resume = threading.Event()
        class MyException(Exception):
            pass

        def raise_my_exception():
            # Wait for the test to tell us to resume
            resume.wait()
            # Now we can raise
            raise MyException()

        tt = thread.ThreadWithException(target=raise_my_exception)
        tt.start()
        tt.join(timeout=0)
        self.assertIs(None, tt.exception)
        resume.set()
        self.assertRaises(MyException, tt.join)


