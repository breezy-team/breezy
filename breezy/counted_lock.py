# Copyright (C) 2007, 2008 Canonical Ltd
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

"""Counted lock class."""

from . import errors


class CountedLock:
    """Decorator around a lock that makes it reentrant.

    This can be used with any object that provides a basic Lock interface,
    including LockDirs and OS file locks.

    :ivar _token: While a write lock is held, this is the token
        for it.
    """

    def __init__(self, real_lock):
        self._real_lock = real_lock
        self._lock_mode = None
        self._lock_count = 0

    def __repr__(self):
        return "{}({!r})".format(self.__class__.__name__, self._real_lock)

    def break_lock(self):
        self._real_lock.break_lock()
        self._lock_mode = None
        self._lock_count = 0

    def get_physical_lock_status(self):
        """Return physical lock status.

        Returns true if a lock is held on the transport. If no lock is held, or
        the underlying locking mechanism does not support querying lock
        status, false is returned.
        """
        try:
            return self._real_lock.peek() is not None
        except NotImplementedError:
            return False

    def is_locked(self):
        return self._lock_mode is not None

    def lock_read(self):
        """Acquire the lock in read mode.

        If the lock is already held in either read or write mode this
        increments the count and succeeds.  If the lock is not already held,
        it is taken in read mode.
        """
        if self._lock_mode:
            self._lock_count += 1
        else:
            self._real_lock.lock_read()
            self._lock_count = 1
            self._lock_mode = "r"

    def lock_write(self, token=None):
        """Acquire the lock in write mode.

        If the lock was originally acquired in read mode this will fail.

        :param token: If given and the lock is already held,
            then validate that we already hold the real
            lock with this token.

        :returns: The token from the underlying lock.
        """
        if self._lock_count == 0:
            self._token = self._real_lock.lock_write(token=token)
            self._lock_mode = "w"
            self._lock_count += 1
            return self._token
        elif self._lock_mode != "w":
            raise errors.ReadOnlyError(self)
        else:
            self._real_lock.validate_token(token)
            self._lock_count += 1
            return self._token

    def unlock(self):
        if self._lock_count == 0:
            raise errors.LockNotHeld(self)
        elif self._lock_count == 1:
            # these are decremented first; if we fail to unlock the most
            # reasonable assumption is that we still don't have the lock
            # anymore
            self._lock_mode = None
            self._lock_count -= 1
            self._real_lock.unlock()
        else:
            self._lock_count -= 1
