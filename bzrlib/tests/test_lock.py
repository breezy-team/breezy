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

"""Tests for OS Locks."""



from bzrlib import (
    lock,
    errors,
    tests,
    )


def load_tests(standard_tests, module, loader):
    """Parameterize tests for all versions of groupcompress."""
    scenarios = []
    for name, write_lock, read_lock in lock._lock_classes:
        scenarios.append((name, {'write_lock': write_lock,
                                 'read_lock': read_lock}))
    suite = loader.suiteClass()
    result = tests.multiply_tests(standard_tests, scenarios, suite)
    return result


class TestOSLock(tests.TestCaseInTempDir):

    # Set by load_tests
    read_lock = None
    write_lock = None

    def test_create_read_lock(self):
        self.build_tree(['a-lock-file'])
        lock = self.read_lock('a-lock-file')
        lock.unlock()

    def test_create_write_lock(self):
        self.build_tree(['a-lock-file'])
        lock = self.write_lock('a-lock-file')
        lock.unlock()

    def test_write_locks_are_exclusive(self):
        self.build_tree(['a-lock-file'])
        lock = self.write_lock('a-lock-file')
        try:
            self.assertRaises(errors.LockContention,
                              self.write_lock, 'a-lock-file')
        finally:
            lock.unlock()
