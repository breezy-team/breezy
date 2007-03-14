# Copyright (C) 2007 Canonical Ltd
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

"""OS Lock implementation tests for bzr.

These test the conformance of all the lock variations to the expected API.
"""

from copy import deepcopy

from bzrlib import (
    lock,
    tests,
    )


class TestCaseWithLock(tests.TestCaseWithTransport):

    write_lock = None
    read_lock = None


class LockTestProviderAdapter(object):
    """A tool to generate a suite testing multiple lock formats at once.

    This is done by copying the test once for each lock and injecting the
    read_lock and write_lock classes.
    They are also given a new test id.
    """

    def __init__(self, lock_classes):
        self._lock_classes = lock_classes

    def _clone_test(self, test, write_lock, read_lock, variation):
        """Clone test for adaption."""
        new_test = deepcopy(test)
        new_test.write_lock = write_lock
        new_test.read_lock = read_lock
        def make_new_test_id():
            new_id = "%s(%s)" % (test.id(), variation)
            return lambda: new_id
        new_test.id = make_new_test_id()
        return new_test

    def adapt(self, test):
        result = tests.TestSuite()
        for name, write_lock, read_lock in self._lock_classes:
            new_test = self._clone_test(test, write_lock, read_lock, name)
            result.addTest(new_test)
        return result


def test_suite():
    result = tests.TestSuite()
    test_lock_implementations = [
        'bzrlib.tests.per_lock.test_lock',
        ]
    adapter = LockTestProviderAdapter(lock._lock_classes)
    loader = tests.TestLoader()
    tests.adapt_modules(test_lock_implementations, adapter, loader, result)
    return result
