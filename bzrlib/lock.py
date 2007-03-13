# Copyright (C) 2005, 2006, 2007 Canonical Ltd
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

import errno
import os
import sys

from bzrlib import errors
from bzrlib.errors import LockError, LockContention
from bzrlib.osutils import realpath
from bzrlib.trace import mutter


class _base_Lock(object):

    def __init__(self):
        self.f = None

    def _open(self, filename, filemode):
        try:
            self.f = open(filename, filemode)
            return self.f
        except IOError, e:
            if e.errno in (errno.EACCES, errno.EPERM):
                raise errors.ReadOnlyLockError(e)
            if e.errno != errno.ENOENT:
                raise

            # maybe this is an old branch (before may 2005)
            mutter("trying to create missing branch lock %r", filename)
            
            self.f = open(filename, 'wb+')
            return self.f

    def _clear_f(self):
        """Clear the self.f attribute cleanly."""
        if self.f:
            self.f.close()
            self.f = None

    def __del__(self):
        if self.f:
            from warnings import warn
            warn("lock on %r not released" % self.f)
            self.unlock()
            
    def unlock(self):
        raise NotImplementedError()


have_ctypes = have_pywin32 = have_fcntl = False
try:
    import fcntl
    have_fcntl = True
except ImportError:
    try:
        import win32con, win32file, pywintypes, winerror, msvcrt
        have_pywin32 = True
    except ImportError:
        try:
            import ctypes, msvcrt
            have_ctypes = True
        except ImportError:
            raise NotImplementedError("please write a locking method "
                                      "for platform %r" % sys.platform)


if have_fcntl:
    LOCK_SH = fcntl.LOCK_SH
    LOCK_NB = fcntl.LOCK_NB
    lock_EX = fcntl.LOCK_EX


    class _fcntl_FileLock(_base_Lock):

        def _unlock(self):
            fcntl.lockf(self.f, fcntl.LOCK_UN)
            self._clear_f()


    class _fcntl_WriteLock(_fcntl_FileLock):

        _open_locks = set()

        def __init__(self, filename):
            # standard IO errors get exposed directly.
            super(_fcntl_WriteLock, self).__init__()
            self.filename = realpath(filename)
            if (self.filename in _fcntl_WriteLock._open_locks
                or self.filename in _fcntl_ReadLock._open_locks):
                self._clear_f()
                raise errors.LockContention(self.filename)

            self._open(filename, 'rb+')
            # reserve a slot for this lock - even if the lockf call fails,
            # at thisi point unlock() will be called, because self.f is set.
            # TODO: make this fully threadsafe, if we decide we care.
            _fcntl_WriteLock._open_locks.add(self.filename)
            try:
                # LOCK_NB will cause IOError to be raised if we can't grab a
                # lock right away.
                fcntl.lockf(self.f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except IOError, e:
                if e.errno in (errno.EAGAIN, errno.EACCES):
                    # We couldn't grab the lock
                    self.unlock()
                # we should be more precise about whats a locking
                # error and whats a random-other error
                raise errors.LockError(e)

        def unlock(self):
            _fcntl_WriteLock._open_locks.remove(self.filename)
            self._unlock()


    class _fcntl_ReadLock(_fcntl_FileLock):

        _open_locks = {}

        def __init__(self, filename):
            super(_fcntl_ReadLock, self).__init__()
            self.filename = realpath(filename)
            if self.filename in _fcntl_WriteLock._open_locks:
                raise errors.LockContention(self.filename)
            _fcntl_ReadLock._open_locks.setdefault(self.filename, 0)
            _fcntl_ReadLock._open_locks[self.filename] += 1
            self._open(filename, 'rb')
            try:
                # LOCK_NB will cause IOError to be raised if we can't grab a
                # lock right away.
                fcntl.lockf(self.f, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except IOError, e:
                # we should be more precise about whats a locking
                # error and whats a random-other error
                raise errors.LockError(e)

        def unlock(self):
            count = _fcntl_ReadLock._open_locks[self.filename]
            if count == 1:
                del _fcntl_ReadLock._open_locks[self.filename]
            else:
                _fcntl_ReadLock._open_locks[self.filename] = count - 1
            self._unlock()


    WriteLock = _fcntl_WriteLock
    ReadLock = _fcntl_ReadLock

elif have_pywin32:
    LOCK_SH = 0 # the default
    LOCK_EX = win32con.LOCKFILE_EXCLUSIVE_LOCK
    LOCK_NB = win32con.LOCKFILE_FAIL_IMMEDIATELY


    class _w32c_FileLock(_base_Lock):

        def _lock(self, filename, openmode, lockmode):
            self._open(filename, openmode)

            self.hfile = msvcrt.get_osfhandle(self.f.fileno())
            overlapped = pywintypes.OVERLAPPED()
            try:
                win32file.LockFileEx(self.hfile, lockmode, 0, 0x7fff0000,
                                     overlapped)
            except pywintypes.error, e:
                self._clear_f()
                if e.args[0] in (winerror.ERROR_LOCK_VIOLATION,):
                    raise errors.LockContention(filename)
                ## import pdb; pdb.set_trace()
                raise
            except Exception, e:
                self._clear_f()
                raise LockError(e)

        def unlock(self):
            overlapped = pywintypes.OVERLAPPED()
            try:
                win32file.UnlockFileEx(self.hfile, 0, 0x7fff0000, overlapped)
                self._clear_f()
            except Exception, e:
                raise LockError(e)


    class _w32c_ReadLock(_w32c_FileLock):
        def __init__(self, filename):
            super(_w32c_ReadLock, self).__init__()
            self._lock(filename, 'rb', LOCK_SH + LOCK_NB)

    class _w32c_WriteLock(_w32c_FileLock):
        def __init__(self, filename):
            super(_w32c_WriteLock, self).__init__()
            self._lock(filename, 'rb+', LOCK_EX + LOCK_NB)

    WriteLock = _w32c_WriteLock
    ReadLock = _w32c_ReadLock
else:
    assert have_ctypes, "We should have ctypes installed"
    # These constants were copied from the win32con.py module.
    LOCKFILE_FAIL_IMMEDIATELY = 1
    LOCKFILE_EXCLUSIVE_LOCK = 2
    # Constant taken from winerror.py module
    ERROR_LOCK_VIOLATION = 33

    LOCK_SH = 0
    LOCK_EX = LOCKFILE_EXCLUSIVE_LOCK
    LOCK_NB = LOCKFILE_FAIL_IMMEDIATELY
    _LockFileEx = ctypes.windll.kernel32.LockFileEx
    _UnlockFileEx = ctypes.windll.kernel32.UnlockFileEx
    _GetLastError = ctypes.windll.kernel32.GetLastError

    ### Define the OVERLAPPED structure.
    #   http://msdn2.microsoft.com/en-us/library/ms684342.aspx
    # typedef struct _OVERLAPPED {
    #   ULONG_PTR Internal;
    #   ULONG_PTR InternalHigh;
    #   union {
    #     struct {
    #       DWORD Offset;
    #       DWORD OffsetHigh;
    #     };
    #     PVOID Pointer;
    #   };
    #   HANDLE hEvent;
    # } OVERLAPPED, 

    class _inner_struct(ctypes.Structure):
        _fields_ = [('Offset', ctypes.c_uint), # DWORD
                    ('OffsetHigh', ctypes.c_uint), # DWORD
                   ]

    class _inner_union(ctypes.Union):
        _fields_  = [('anon_struct', _inner_struct), # struct
                     ('Pointer', ctypes.c_void_p), # PVOID
                    ]

    class OVERLAPPED(ctypes.Structure):
        _fields_ = [('Internal', ctypes.c_void_p), # ULONG_PTR
                    ('InternalHigh', ctypes.c_void_p), # ULONG_PTR
                    ('_inner_union', _inner_union),
                    ('hEvent', ctypes.c_void_p), # HANDLE
                   ]

    class _ctypes_FileLock(_base_Lock):

        def _lock(self, filename, openmode, lockmode):
            self._open(filename, openmode)

            self.hfile = msvcrt.get_osfhandle(self.f.fileno())
            overlapped = OVERLAPPED()
            p_overlapped = ctypes.pointer(overlapped)
            result = _LockFileEx(self.hfile, # HANDLE hFile
                                 lockmode,   # DWORD dwFlags
                                 0,          # DWORD dwReserved
                                 0x7fffffff, # DWORD nNumberOfBytesToLockLow
                                 0x00000000, # DWORD nNumberOfBytesToLockHigh
                                 p_overlapped, # lpOverlapped
                                )
            if result == 0:
                self._clear_f()
                last_err = _GetLastError()
                if last_err in (ERROR_LOCK_VIOLATION,):
                    raise errors.LockContention(filename)
                raise errors.LockError('Unknown locking error: %s'
                                       % (last_err,))

        def unlock(self):
            overlapped = OVERLAPPED()
            p_overlapped = ctypes.pointer(overlapped)
            result = _UnlockFileEx(self.hfile, # HANDLE hFile
                                   0,          # DWORD dwReserved
                                   0x7fffffff, # DWORD nNumberOfBytesToLockLow
                                   0x00000000, # DWORD nNumberOfBytesToLockHigh
                                   p_overlapped, # lpOverlapped
                                  )
            self._clear_f()
            if result == 0:
                self._clear_f()
                last_err = _GetLastError()
                raise errors.LockError('Unknown unlocking error: %s'
                                       % (last_err,))


    class _ctypes_ReadLock(_ctypes_FileLock):
        def __init__(self, filename):
            super(_ctypes_ReadLock, self).__init__()
            self._lock(filename, 'rb', LOCK_SH + LOCK_NB)

    class _ctypes_WriteLock(_ctypes_FileLock):
        def __init__(self, filename):
            super(_ctypes_WriteLock, self).__init__()
            self._lock(filename, 'rb+', LOCK_EX + LOCK_NB)

    WriteLock = _ctypes_WriteLock
    ReadLock = _ctypes_ReadLock

