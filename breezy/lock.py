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
import errno
import os
import sys
import warnings
from typing import Any, Optional

from . import debug, errors, osutils, trace
from .hooks import Hooks
from .i18n import gettext
from .transport import Transport

LockToken = bytes


class LockHooks(Hooks):
    def __init__(self):
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
    ) -> None: ...

    def create(self, mode: int): ...

    def break_lock(self) -> None: ...

    def leave_in_place(self) -> None: ...

    def dont_leave_in_place(self) -> None: ...

    def validate_token(self, token: Optional[LockToken]) -> None: ...

    def lock_write(self, token: Optional[LockToken]) -> Optional[LockToken]: ...

    def lock_read(self) -> None: ...

    def unlock(self) -> None: ...

    def peek(self) -> LockToken:
        raise NotImplementedError(self.peek)


class LockResult:
    """Result of an operation on a lock; passed to a hook."""

    def __init__(self, lock_url, details=None):
        """Create a lock result for lock with optional details about the lock."""
        self.lock_url = lock_url
        self.details = details

    def __eq__(self, other):
        return self.lock_url == other.lock_url and self.details == other.details

    def __repr__(self):
        return "{}({}, {})".format(self.__class__.__name__, self.lock_url, self.details)


class LogicalLockResult:
    """The result of a lock_read/lock_write/lock_tree_write call on lockables.

    :ivar unlock: A callable which will unlock the lock.
    """

    def __init__(self, unlock, token=None):
        self.unlock = unlock
        self.token = token

    def __repr__(self):
        return "LogicalLockResult({})".format(self.unlock)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
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
    if "unlock" in debug.debug_flags:
        warnings.warn("{!r} is already unlocked".format(locked_object), stacklevel=3)
    else:
        raise errors.LockNotHeld(locked_object)


try:
    import fcntl

    have_fcntl = True
except ModuleNotFoundError:
    have_fcntl = False

have_ctypes_win32 = False
if sys.platform == "win32":
    import msvcrt

    try:
        import ctypes

        have_ctypes_win32 = True
    except ImportError:
        pass


class _OSLock:
    def __init__(self):
        self.f = None
        self.filename = None

    def _open(self, filename, filemode):
        self.filename = osutils.realpath(filename)
        try:
            self.f = open(self.filename, filemode)
            return self.f
        except OSError as e:
            if e.errno in (errno.EACCES, errno.EPERM):
                raise errors.LockFailed(self.filename, str(e))
            if e.errno != errno.ENOENT:
                raise

            # maybe this is an old branch (before may 2005)
            trace.mutter("trying to create missing lock %r", self.filename)

            self.f = open(self.filename, "wb+")
            return self.f

    def _clear_f(self):
        """Clear the self.f attribute cleanly."""
        if self.f:
            self.f.close()
            self.f = None

    def unlock(self):
        raise NotImplementedError()


_lock_classes: list[tuple[str, Any, Any]] = []


if have_fcntl:

    class _fcntl_FileLock(_OSLock):
        def _unlock(self):
            fcntl.lockf(self.f, fcntl.LOCK_UN)
            self._clear_f()

    class _fcntl_WriteLock(_fcntl_FileLock):
        _open_locks: set[str] = set()

        def __init__(self, filename):
            super().__init__()
            # Check we can grab a lock before we actually open the file.
            self.filename = osutils.realpath(filename)
            if self.filename in _fcntl_WriteLock._open_locks:
                self._clear_f()
                raise errors.LockContention(self.filename)
            if self.filename in _fcntl_ReadLock._open_locks:
                if "strict_locks" in debug.debug_flags:
                    self._clear_f()
                    raise errors.LockContention(self.filename)
                else:
                    trace.mutter(
                        "Write lock taken w/ an open read lock on: {}".format(
                            self.filename
                        )
                    )

            self._open(self.filename, "rb+")
            # reserve a slot for this lock - even if the lockf call fails,
            # at this point unlock() will be called, because self.f is set.
            # TODO: make this fully threadsafe, if we decide we care.
            _fcntl_WriteLock._open_locks.add(self.filename)
            try:
                # LOCK_NB will cause IOError to be raised if we can't grab a
                # lock right away.
                fcntl.lockf(self.f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as e:
                if e.errno in (errno.EAGAIN, errno.EACCES):
                    # We couldn't grab the lock
                    self.unlock()
                # we should be more precise about whats a locking
                # error and whats a random-other error
                raise errors.LockContention(self.filename, e)

        def unlock(self):
            _fcntl_WriteLock._open_locks.remove(self.filename)
            self._unlock()

    class _fcntl_ReadLock(_fcntl_FileLock):
        _open_locks: dict[str, int] = {}

        def __init__(self, filename):
            super().__init__()
            self.filename = osutils.realpath(filename)
            if self.filename in _fcntl_WriteLock._open_locks:
                if "strict_locks" in debug.debug_flags:
                    # We raise before calling _open so we don't need to
                    # _clear_f
                    raise errors.LockContention(self.filename)
                else:
                    trace.mutter(
                        "Read lock taken w/ an open write lock on: {}".format(
                            self.filename
                        )
                    )
            _fcntl_ReadLock._open_locks.setdefault(self.filename, 0)
            _fcntl_ReadLock._open_locks[self.filename] += 1
            self._open(filename, "rb")
            try:
                # LOCK_NB will cause IOError to be raised if we can't grab a
                # lock right away.
                fcntl.lockf(self.f, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except OSError as e:
                # we should be more precise about whats a locking
                # error and whats a random-other error
                raise errors.LockContention(self.filename, e)

        def unlock(self):
            count = _fcntl_ReadLock._open_locks[self.filename]
            if count == 1:
                del _fcntl_ReadLock._open_locks[self.filename]
            else:
                _fcntl_ReadLock._open_locks[self.filename] = count - 1
            self._unlock()

        def temporary_write_lock(self):
            """Try to grab a write lock on the file.

            On platforms that support it, this will upgrade to a write lock
            without unlocking the file.
            Otherwise, this will release the read lock, and try to acquire a
            write lock.

            :return: A token which can be used to switch back to a read lock.
            """
            if self.filename in _fcntl_WriteLock._open_locks:
                raise AssertionError("file already locked: {!r}".format(self.filename))
            try:
                wlock = _fcntl_TemporaryWriteLock(self)
            except errors.LockError:
                # We didn't unlock, so we can just return 'self'
                return False, self
            return True, wlock

    class _fcntl_TemporaryWriteLock(_OSLock):
        """A token used when grabbing a temporary_write_lock.

        Call restore_read_lock() when you are done with the write lock.
        """

        def __init__(self, read_lock):
            super().__init__()
            self._read_lock = read_lock
            self.filename = read_lock.filename

            count = _fcntl_ReadLock._open_locks[self.filename]
            if count > 1:
                # Something else also has a read-lock, so we cannot grab a
                # write lock.
                raise errors.LockContention(self.filename)

            if self.filename in _fcntl_WriteLock._open_locks:
                raise AssertionError("file already locked: {!r}".format(self.filename))

            # See if we can open the file for writing. Another process might
            # have a read lock. We don't use self._open() because we don't want
            # to create the file if it exists. That would have already been
            # done by _fcntl_ReadLock
            try:
                new_f = open(self.filename, "rb+")
            except OSError as e:
                if e.errno in (errno.EACCES, errno.EPERM):
                    raise errors.LockFailed(self.filename, str(e))
                raise
            try:
                # LOCK_NB will cause IOError to be raised if we can't grab a
                # lock right away.
                fcntl.lockf(new_f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as e:
                # TODO: Raise a more specific error based on the type of error
                raise errors.LockContention(self.filename, e)
            _fcntl_WriteLock._open_locks.add(self.filename)

            self.f = new_f

        def restore_read_lock(self):
            """Restore the original ReadLock."""
            # For fcntl, since we never released the read lock, just release
            # the write lock, and return the original lock.
            fcntl.lockf(self.f, fcntl.LOCK_UN)
            self._clear_f()
            _fcntl_WriteLock._open_locks.remove(self.filename)
            # Avoid reference cycles
            read_lock = self._read_lock
            self._read_lock = None
            return read_lock

    _lock_classes.append(("fcntl", _fcntl_WriteLock, _fcntl_ReadLock))


if have_ctypes_win32:
    import ctypes
    from ctypes.wintypes import DWORD, LPWSTR

    LPSECURITY_ATTRIBUTES = ctypes.c_void_p  # used as NULL no need to declare
    HANDLE = ctypes.c_int  # rather than unsigned as in ctypes.wintypes
    _function_name = "CreateFileW"

    # CreateFile <http://msdn.microsoft.com/en-us/library/aa363858.aspx>
    _CreateFile = ctypes.WINFUNCTYPE(  # type: ignore
        HANDLE,  # return value
        LPWSTR,  # lpFileName
        DWORD,  # dwDesiredAccess
        DWORD,  # dwShareMode
        LPSECURITY_ATTRIBUTES,  # lpSecurityAttributes
        DWORD,  # dwCreationDisposition
        DWORD,  # dwFlagsAndAttributes
        HANDLE,  # hTemplateFile
    )((_function_name, ctypes.windll.kernel32))  # type: ignore

    INVALID_HANDLE_VALUE = -1

    GENERIC_READ = 0x80000000
    GENERIC_WRITE = 0x40000000
    FILE_SHARE_READ = 1
    OPEN_ALWAYS = 4
    FILE_ATTRIBUTE_NORMAL = 128

    ERROR_ACCESS_DENIED = 5
    ERROR_SHARING_VIOLATION = 32

    class _ctypes_FileLock(_OSLock):
        def _open(self, filename, access, share, cflags, pymode):
            self.filename = osutils.realpath(filename)
            handle = _CreateFile(
                filename, access, share, None, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, 0
            )
            if handle in (INVALID_HANDLE_VALUE, 0):
                e = ctypes.WinError()
                if e.args[0] == ERROR_ACCESS_DENIED:
                    raise errors.LockFailed(filename, e)
                if e.args[0] == ERROR_SHARING_VIOLATION:
                    raise errors.LockContention(filename, e)
                raise e
            fd = msvcrt.open_osfhandle(handle, cflags)
            self.f = os.fdopen(fd, pymode)
            return self.f

        def unlock(self):
            self._clear_f()

    class _ctypes_ReadLock(_ctypes_FileLock):
        def __init__(self, filename):
            super().__init__()
            self._open(filename, GENERIC_READ, FILE_SHARE_READ, os.O_RDONLY, "rb")

        def temporary_write_lock(self):
            """Try to grab a write lock on the file.

            On platforms that support it, this will upgrade to a write lock
            without unlocking the file.
            Otherwise, this will release the read lock, and try to acquire a
            write lock.

            :return: A token which can be used to switch back to a read lock.
            """
            # I can't find a way to upgrade a read lock to a write lock without
            # unlocking first. So here, we do just that.
            self.unlock()
            try:
                wlock = _ctypes_WriteLock(self.filename)
            except errors.LockError:
                return False, _ctypes_ReadLock(self.filename)
            return True, wlock

    class _ctypes_WriteLock(_ctypes_FileLock):
        def __init__(self, filename):
            super().__init__()
            self._open(filename, GENERIC_READ | GENERIC_WRITE, 0, os.O_RDWR, "rb+")

        def restore_read_lock(self):
            """Restore the original ReadLock."""
            # For win32 we had to completely let go of the original lock, so we
            # just unlock and create a new read lock.
            self.unlock()
            return _ctypes_ReadLock(self.filename)

    _lock_classes.append(("ctypes", _ctypes_WriteLock, _ctypes_ReadLock))


if len(_lock_classes) == 0:
    raise NotImplementedError(
        "We must have one of fcntl or ctypes available to support OS locking."
    )


# We default to using the first available lock class.
_lock_type, WriteLock, ReadLock = _lock_classes[0]


class _RelockDebugMixin:
    """Mixin support for -Drelock flag.

    Add this as a base class then call self._note_lock with 'r' or 'w' when
    acquiring a read- or write-lock.  If this object was previously locked (and
    locked the same way), and -Drelock is set, then this will trace.note a
    message about it.
    """

    _prev_lock = None

    def _note_lock(self, lock_type):
        if "relock" in debug.debug_flags and self._prev_lock == lock_type:
            if lock_type == "r":
                type_name = "read"
            else:
                type_name = "write"
            trace.note(gettext("{0!r} was {1} locked again"), self, type_name)
        self._prev_lock = lock_type


@contextlib.contextmanager
def write_locked(lockable):
    lockable.lock_write()
    try:
        yield lockable
    finally:
        lockable.unlock()
