# Copyright (C) 2005 Canonical Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


"""Locking wrappers.

This only does local locking using OS locks for now.

This module causes two methods, lock() and unlock() to be defined in
any way that works on the current platform.

It is not specified whether these locks are reentrant (i.e. can be
taken repeatedly by a single process) or whether they exclude
different threads in a single process.  

Eventually we may need to use some kind of lock representation that
will work on a dumb filesystem without actual locking primitives."""


import sys, os

import bzrlib
from trace import mutter, note, warning

class LockError(Exception):
    """All exceptions from the lock/unlock functions should be from this exception class.
    They will be translated as necessary. The original exception is available as e.original_error
    """
    def __init__(self, e=None):
        self.original_error = e
        if e:
            Exception.__init__(self, e)
        else:
            Exception.__init__(self)

try:
    import fcntl
    LOCK_SH = fcntl.LOCK_SH
    LOCK_EX = fcntl.LOCK_EX
    LOCK_NB = fcntl.LOCK_NB
    def lock(f, flags):
        try:
            fcntl.flock(f, flags)
        except Exception, e:
            raise LockError(e)

    def unlock(f):
        try:
            fcntl.flock(f, fcntl.LOCK_UN)
        except Exception, e:
            raise LockError(e)

except ImportError:
    try:
        import win32con, win32file, pywintypes
        LOCK_SH = 0 # the default
        LOCK_EX = win32con.LOCKFILE_EXCLUSIVE_LOCK
        LOCK_NB = win32con.LOCKFILE_FAIL_IMMEDIATELY

        def lock(f, flags):
            try:
                if type(f) == file:
                    hfile = win32file._get_osfhandle(f.fileno())
                else:
                    hfile = win32file._get_osfhandle(f)
                overlapped = pywintypes.OVERLAPPED()
                win32file.LockFileEx(hfile, flags, 0, 0x7fff0000, overlapped)
            except Exception, e:
                raise LockError(e)

        def unlock(f):
            try:
                if type(f) == file:
                    hfile = win32file._get_osfhandle(f.fileno())
                else:
                    hfile = win32file._get_osfhandle(f)
                overlapped = pywintypes.OVERLAPPED()
                win32file.UnlockFileEx(hfile, 0, 0x7fff0000, overlapped)
            except Exception, e:
                raise LockError(e)
    except ImportError:
        try:
            import msvcrt
            # Unfortunately, msvcrt.locking() doesn't distinguish between
            # read locks and write locks. Also, the way the combinations
            # work to get non-blocking is not the same, so we
            # have to write extra special functions here.

            LOCK_SH = 1
            LOCK_EX = 2
            LOCK_NB = 4

            def lock(f, flags):
                try:
                    # Unfortunately, msvcrt.LK_RLCK is equivalent to msvcrt.LK_LOCK
                    # according to the comments, LK_RLCK is open the lock for writing.

                    # Unfortunately, msvcrt.locking() also has the side effect that it
                    # will only block for 10 seconds at most, and then it will throw an
                    # exception, this isn't terrible, though.
                    if type(f) == file:
                        fpos = f.tell()
                        fn = f.fileno()
                        f.seek(0)
                    else:
                        fn = f
                        fpos = os.lseek(fn, 0,0)
                        os.lseek(fn, 0,0)
                    
                    if flags & LOCK_SH:
                        if flags & LOCK_NB:
                            lock_mode = msvcrt.LK_NBLCK
                        else:
                            lock_mode = msvcrt.LK_LOCK
                    elif flags & LOCK_EX:
                        if flags & LOCK_NB:
                            lock_mode = msvcrt.LK_NBRLCK
                        else:
                            lock_mode = msvcrt.LK_RLCK
                    else:
                        raise ValueError('Invalid lock mode: %r' % flags)
                    try:
                        msvcrt.locking(fn, lock_mode, -1)
                    finally:
                        os.lseek(fn, fpos, 0)
                except Exception, e:
                    raise LockError(e)

            def unlock(f):
                try:
                    if type(f) == file:
                        fpos = f.tell()
                        fn = f.fileno()
                        f.seek(0)
                    else:
                        fn = f
                        fpos = os.lseek(fn, 0,0)
                        os.lseek(fn, 0,0)

                    try:
                        msvcrt.locking(fn, msvcrt.LK_UNLCK, -1)
                    finally:
                        os.lseek(fn, fpos, 0)
                except Exception, e:
                    raise LockError(e)
        except ImportError:
            from warnings import Warning
            
            warning("please write a locking method for platform %r" % sys.platform)

            # Creating no-op lock/unlock for now
            def lock(f, flags):
                pass
            def unlock(f):
                pass

