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

"""Helper functions for Walkdirs on win32."""


cdef extern from "_walkdirs_win32.h":
    cdef struct _HANDLE:
        pass
    ctypedef _HANDLE *HANDLE
    ctypedef unsigned long DWORD
    ctypedef long long __int64
    ctypedef unsigned short WCHAR
    cdef struct _FILETIME:
        DWORD dwHighDateTime
        DWORD dwLowDateTime
    ctypedef _FILETIME FILETIME

    cdef struct _WIN32_FIND_DATAW:
        DWORD dwFileAttributes
        FILETIME ftCreationTime
        FILETIME ftLastAccessTime
        FILETIME ftLastWriteTime
        DWORD nFileSizeHigh
        DWORD nFileSizeLow
        # Some reserved stuff here
        WCHAR cFileName[260] # MAX_PATH
        WCHAR cAlternateFilename[14]

    # We have to use the typedef trick, otherwise pyrex uses:
    #  struct WIN32_FIND_DATAW
    # which fails due to 'incomplete type'
    ctypedef _WIN32_FIND_DATAW WIN32_FIND_DATAW

    cdef HANDLE INVALID_HANDLE_VALUE
    cdef HANDLE FindFirstFileW(WCHAR *path, WIN32_FIND_DATAW *data)
    cdef int FindNextFileW(HANDLE search, WIN32_FIND_DATAW *data)
    cdef int FindClose(HANDLE search)

    cdef DWORD FILE_ATTRIBUTE_READONLY
    cdef DWORD FILE_ATTRIBUTE_DIRECTORY
    cdef int ERROR_NO_MORE_FILES

    cdef int GetLastError()

    # Wide character functions
    DWORD wcslen(WCHAR *)


cdef extern from "Python.h":
    WCHAR *PyUnicode_AS_UNICODE(object)
    Py_ssize_t PyUnicode_GET_SIZE(object)
    object PyUnicode_FromUnicode(WCHAR *, Py_ssize_t)
    int PyList_Append(object, object) except -1
    object PyUnicode_AsUTF8String(object)


import operator
import stat

from bzrlib import osutils


cdef class _Win32Stat:
    """Represent a 'stat' result generated from WIN32_FIND_DATA"""

    cdef readonly int st_mode
    cdef readonly double st_ctime
    cdef readonly double st_mtime
    cdef readonly double st_atime
    cdef readonly __int64 st_size

    # os.stat always returns 0, so we hard code it here
    cdef readonly int st_dev
    cdef readonly int st_ino

    def __repr__(self):
        """Repr is the same as a Stat object.

        (mode, ino, dev, nlink, uid, gid, size, atime, mtime, ctime)
        """
        return repr((self.st_mode, 0, 0, 0, 0, 0, self.st_size, self.st_atime,
                     self.st_mtime, self.st_ctime))


cdef object _get_name(WIN32_FIND_DATAW *data):
    """Extract the Unicode name for this file/dir."""
    return PyUnicode_FromUnicode(data.cFileName,
                                 wcslen(data.cFileName))


cdef int _get_mode_bits(WIN32_FIND_DATAW *data):
    cdef int mode_bits

    mode_bits = 0100666 # writeable file, the most common
    if data.dwFileAttributes & FILE_ATTRIBUTE_READONLY == FILE_ATTRIBUTE_READONLY:
        mode_bits ^= 0222 # remove the write bits
    if data.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY == FILE_ATTRIBUTE_DIRECTORY:
        # Remove the FILE bit, set the DIR bit, and set the EXEC bits
        mode_bits ^= 0140111
    return mode_bits


cdef __int64 _get_size(WIN32_FIND_DATAW *data):
    # Pyrex casts a DWORD into a PyLong anyway, so it is safe to do << 32
    # on a DWORD
    return ((<__int64>data.nFileSizeHigh) << 32) + data.nFileSizeLow


cdef double _ftime_to_timestamp(FILETIME *ft):
    """Convert from a FILETIME struct into a floating point timestamp.

    The fields of a FILETIME structure are the hi and lo part
    of a 64-bit value expressed in 100 nanosecond units.
    1e7 is one second in such units; 1e-7 the inverse.
    429.4967296 is 2**32 / 1e7 or 2**32 * 1e-7.
    It also uses the epoch 1601-01-01 rather than 1970-01-01
    (taken from posixmodule.c)
    """
    cdef __int64 val
    # NB: This gives slightly different results versus casting to a 64-bit
    #     integer and doing integer math before casting into a floating
    #     point number. But the difference is in the sub millisecond range,
    #     which doesn't seem critical here.
    # secs between epochs: 11,644,473,600
    val = ((<__int64>ft.dwHighDateTime) << 32) + ft.dwLowDateTime
    return (val * 1.0e-7) - 11644473600.0


cdef int _should_skip(WIN32_FIND_DATAW *data):
    """Is this '.' or '..' so we should skip it?"""
    if (data.cFileName[0] != c'.'):
        return 0
    if data.cFileName[1] == c'\0':
        return 1
    if data.cFileName[1] == c'.' and data.cFileName[2] == c'\0':
        return 1
    return 0


cdef class Win32Finder:
    """A class which encapsulates the search of files in a given directory"""

    cdef object _top
    cdef object _prefix

    cdef object _directory_kind
    cdef object _file_kind

    cdef object _pending
    cdef object _last_dirblock

    def __init__(self, top, prefix=""):
        self._top = top
        self._prefix = prefix

        self._directory_kind = osutils._directory_kind
        self._file_kind = osutils._formats[stat.S_IFREG]

        self._pending = [(osutils.safe_utf8(prefix), osutils.safe_unicode(top))]
        self._last_dirblock = None

    def __iter__(self):
        return self

    cdef _Win32Stat _get_stat_value(self, WIN32_FIND_DATAW *data):
        """Get the filename and the stat information."""
        cdef _Win32Stat statvalue

        statvalue = _Win32Stat()
        statvalue.st_mode = _get_mode_bits(data)
        statvalue.st_ctime = _ftime_to_timestamp(&data.ftCreationTime)
        statvalue.st_mtime = _ftime_to_timestamp(&data.ftLastWriteTime)
        statvalue.st_atime = _ftime_to_timestamp(&data.ftLastAccessTime)
        statvalue.st_size = _get_size(data)
        statvalue.st_ino = 0
        statvalue.st_dev = 0
        return statvalue

    cdef object _get_kind(self, WIN32_FIND_DATAW *data):
        if data.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY:
            return self._directory_kind
        return self._file_kind

    def _get_files_in(self, directory, relprefix):
        cdef WIN32_FIND_DATAW search_data
        cdef HANDLE hFindFile
        cdef int last_err
        cdef WCHAR *query
        cdef int result

        top_star = directory + '*'

        dirblock = []

        query = PyUnicode_AS_UNICODE(top_star)
        hFindFile = FindFirstFileW(query, &search_data)
        if hFindFile == INVALID_HANDLE_VALUE:
            # Raise an exception? This path doesn't seem to exist
            raise WindowsError(GetLastError(), top_star)

        try:
            result = 1
            while result:
                # Skip '.' and '..'
                if _should_skip(&search_data):
                    result = FindNextFileW(hFindFile, &search_data)
                    continue
                name_unicode = self._get_name(&search_data)
                name_utf8 = PyUnicode_AsUTF8String(name_unicode)
                relpath = relprefix + name_utf8
                abspath = directory + name_unicode
                PyList_Append(dirblock, 
                    (relpath, name_utf8, 
                     self._get_kind(&search_data),
                     self._get_stat_value(&search_data),
                     abspath))

                result = FindNextFileW(hFindFile, &search_data)
            # FindNextFileW sets GetLastError() == ERROR_NO_MORE_FILES when it
            # actually finishes. If we have anything else, then we have a
            # genuine problem
            last_err = GetLastError()
            if last_err != ERROR_NO_MORE_FILES:
                raise WindowsError(last_err)
        finally:
            result = FindClose(hFindFile)
            if result == 0:
                last_err = GetLastError()
                pass
        return dirblock

    cdef _update_pending(self):
        """If we had a result before, add the subdirs to pending."""
        if self._last_dirblock is not None:
            # push the entries left in the dirblock onto the pending queue
            # we do this here, because we allow the user to modified the
            # queue before the next iteration
            for d in reversed(self._last_dirblock):
                if d[2] == self._directory_kind:
                    self._pending.append((d[0], d[-1]))
            self._last_dirblock = None
        
    def __next__(self):
        self._update_pending()
        if not self._pending:
            raise StopIteration()
        relroot, top = self._pending.pop()
        # NB: At the moment Pyrex doesn't support Unicode literals, which means
        # that all of these string literals are going to be upcasted to Unicode
        # at runtime... :(
        # Maybe we could use unicode(x) during __init__?
        if relroot:
            relprefix = relroot + '/'
        else:
            relprefix = ''
        top_slash = top + '/'

        dirblock = self._get_files_in(top_slash, relprefix)
        dirblock.sort(key=operator.itemgetter(1))
        self._last_dirblock = dirblock
        return (relroot, top), dirblock


def _walkdirs_utf8_win32_find_file(top, prefix=""):
    """Implement a version of walkdirs_utf8 for win32.

    This uses the find files api to both list the files and to stat them.
    """
    return Win32Finder(top, prefix=prefix)
