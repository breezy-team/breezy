# Copyright (C) 2005-2010 Canonical Ltd
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

"""Locking using OS file locks or file existence.

Note: This method of locking is generally deprecated in favour of LockDir, but
is used to lock local WorkingTrees, and by some old formats.  It's accessed
through Transport.lock_read(), etc.

This module causes two methods, lock() and unlock() to be defined in
any way that works on the current platform.

It is not specified whether these locks are reentrant (i.e. can be
taken repeatedly by a single process) or whether they exclude
different threads in a single process.  That reentrancy is provided by
LockableFiles.

This defines two classes: ReadLock and WriteLock, which can be
implemented in different ways on different platforms.  Both have an
unlock() method.
"""

import contextlib
import warnings
from typing import Optional

from . import _transport_rs, debug, errors, trace
from .hooks import Hooks
from .i18n import gettext
from .transport import Transport

have_fcntl = True


def ReadLock(path):
    """Create a read lock for the given path.

    Args:
        path: Path to create the read lock for.

    Returns:
        A read lock instance.
    """
    return _transport_rs.ReadLock(path, "strict_locks" in debug.debug_flags)


def WriteLock(path):
    """Create a write lock for the given path.

    Args:
        path: Path to create the write lock for.

    Returns:
        A write lock instance.
    """
    return _transport_rs.WriteLock(path, "strict_locks" in debug.debug_flags)


LockToken = bytes


class LockHooks(Hooks):
    """Hook registry for lock-related operations.

    Provides hooks for lock acquisition, release, and breaking events.
    """

    def __init__(self):
        """Initialize the lock hooks registry."""
        Hooks.__init__(self, "breezy.lock", "Lock.hooks")
        self.add_hook(
            "lock_acquired",
            "Called with a breezy.lock.LockResult when a physical lock is acquired.",
            (1, 8),
        )
        self.add_hook(
            "lock_released",
            "Called with a breezy.lock.LockResult when a physical lock is released.",
            (1, 8),
        )
        self.add_hook(
            "lock_broken",
            "Called with a breezy.lock.LockResult when a physical lock is broken.",
            (1, 15),
        )


class Lock:
    """Base class for locks.

    :cvar hooks: Hook dictionary for operations on locks.
    """

    hooks = LockHooks()

    def __init__(
        self, transport: Transport, path: str, file_modebits: int, dir_modebits: int
    ) -> None:
        """Initialize the lock.

        Args:
            transport: Transport to use for lock operations.
            path: Path within the transport for the lock.
            file_modebits: Mode bits for lock files.
            dir_modebits: Mode bits for lock directories.
        """
        ...

    def create(self, mode: int):
        """Create the lock with the specified mode.

        Args:
            mode: File mode for the lock.
        """
        ...

    def break_lock(self) -> None:
        """Break an existing lock, if any."""
        ...

    def leave_in_place(self) -> None:
        """Configure the lock to be left in place when released."""
        ...

    def dont_leave_in_place(self) -> None:
        """Configure the lock to be removed when released."""
        ...

    def validate_token(self, token: Optional[LockToken]) -> None:
        """Validate a lock token.

        Args:
            token: Token to validate, or None.
        """
        ...

    def lock_write(self, token: Optional[LockToken]) -> Optional[LockToken]:
        """Acquire a write lock.

        Args:
            token: Optional lock token from a previous lock.

        Returns:
            Lock token for this lock, or None.
        """
        ...

    def lock_read(self) -> None:
        """Acquire a read lock."""
        ...

    def unlock(self) -> None:
        """Release the lock."""
        ...

    def peek(self) -> LockToken:
        """Look at the current lock state without acquiring it.

        Returns:
            Current lock token.
        """
        raise NotImplementedError(self.peek)


class LockResult:
    """Result of an operation on a lock; passed to a hook."""

    def __init__(self, lock_url, details=None):
        """Create a lock result for lock with optional details about the lock."""
        self.lock_url = lock_url
        self.details = details

    def __eq__(self, other):
        """Compare with another LockResult.

        Args:
            other: Other LockResult to compare with.

        Returns:
            True if the lock results are equal.
        """
        return self.lock_url == other.lock_url and self.details == other.details

    def __repr__(self):
        """Return string representation for debugging.

        Returns:
            String representation of this LockResult.
        """
        return f"{self.__class__.__name__}({self.lock_url}, {self.details})"


class LogicalLockResult:
    """The result of a lock_read/lock_write/lock_tree_write call on lockables.

    :ivar unlock: A callable which will unlock the lock.
    """

    def __init__(self, unlock, token=None):
        """Initialize the logical lock result.

        Args:
            unlock: Callable to unlock this lock.
            token: Optional lock token.
        """
        self.unlock = unlock
        self.token = token

    def __repr__(self):
        """Return string representation for debugging.

        Returns:
            String representation of this LogicalLockResult.
        """
        return f"LogicalLockResult({self.unlock})"

    def __enter__(self):
        """Enter the runtime context for the lock.

        Returns:
            This LogicalLockResult instance.
        """
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit the runtime context and unlock.

        Args:
            exc_type: Exception type, if any.
            exc_val: Exception value, if any.
            exc_tb: Exception traceback, if any.

        Returns:
            False to propagate any exception.
        """
        # If there was an error raised, prefer the original one
        try:
            self.unlock()
        except BaseException:
            if exc_type is None:
                raise
        return False


def cant_unlock_not_held(locked_object):
    """An attempt to unlock failed because the object was not locked.

    This provides a policy point from which we can generate either a warning or
    an exception.
    """
    # This is typically masking some other error and called from a finally
    # block, so it's useful to have the option not to generate a new error
    # here.  You can use -Werror to make it fatal.  It should possibly also
    # raise LockNotHeld.
    if debug.debug_flag_enabled("unlock"):
        warnings.warn(f"{locked_object!r} is already unlocked", stacklevel=3)
    else:
        raise errors.LockNotHeld(locked_object)


class _RelockDebugMixin:
    """Mixin support for -Drelock flag.

    Add this as a base class then call self._note_lock with 'r' or 'w' when
    acquiring a read- or write-lock.  If this object was previously locked (and
    locked the same way), and -Drelock is set, then this will trace.note a
    message about it.
    """

    _prev_lock = None

    def _note_lock(self, lock_type):
        if debug.debug_flag_enabled("relock") and self._prev_lock == lock_type:
            type_name = "read" if lock_type == "r" else "write"
            trace.note(gettext("{0!r} was {1} locked again"), self, type_name)
        self._prev_lock = lock_type


@contextlib.contextmanager
def write_locked(lockable):
    """Context manager for write-locking a lockable object.

    Args:
        lockable: Object that supports lock_write() and unlock() methods.

    Yields:
        The locked object.
    """
    lockable.lock_write()
    try:
        yield lockable
    finally:
        lockable.unlock()


_lock_classes = [("default", WriteLock, ReadLock)]
