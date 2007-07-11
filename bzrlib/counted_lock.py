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

"""Counted lock class"""


from bzrlib.errors import (
    LockError,
    ReadOnlyError,
    )


# TODO: Pass through lock tokens on lock_write and read, and return them...
#
# TODO: Allow upgrading read locks to write?  Conceptually difficult.


class CountedLock(object):
    """Decorator around a lock that makes it reentrant.

    This can be used with any object that provides a basic Lock interface,
    including LockDirs and OS file locks.
    """

    def __init__(self, real_lock):
        self._real_lock = real_lock
        self._lock_mode = None
        self._lock_count = 0

    def break_lock(self):
        self._real_lock.break_lock()
        self._lock_mode = None
        self._lock_count = 0

    def is_locked(self):
        return self._lock_mode is not None

    def lock_read(self):
        """Acquire the lock in read mode.

        If the lock is already held in either read or write mode this
        increments the count and succeeds.  If the lock is not already held,
        it is taken in read mode.
        """
        if self._lock_mode:
            assert self._lock_mode in ('r', 'w'), \
                   "invalid lock mode %r" % self._lock_mode
            self._lock_count += 1
        else:
            assert self._lock_count == 0
            self._real_lock.lock_read()
            self._lock_count = 1
            self._lock_mode = 'r'

    def lock_write(self):
        """Acquire the lock in write mode.

        If the lock was originally acquired in read mode this will fail.
        """
        if self._lock_count == 0:
            assert self._lock_mode is None
            self._real_lock.lock_write()
            self._lock_mode = 'w'
        elif self._lock_mode != 'w':
            raise ReadOnlyError(self)
        self._lock_count += 1

    def unlock(self):
        if self._lock_count == 0:
            raise LockError("%s not locked" % (self,))
        elif self._lock_count == 1:
            self._real_lock.unlock()
            self._lock_mode = None
        self._lock_count -= 1
