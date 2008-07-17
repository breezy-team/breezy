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
    ctypedef unsigned int DWORD
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

    cdef int GetLastError()

    # Wide character functions
    DWORD wcslen(WCHAR *)


cdef extern from "Python.h":
    WCHAR *PyUnicode_AS_UNICODE(object)
    Py_ssize_t PyUnicode_GET_SIZE(object)
    object PyUnicode_FromUnicode(WCHAR *, Py_ssize_t)


import codecs
import operator
import stat

from bzrlib import osutils


class _Win32Stat(object):
    """Represent a 'stat' result generated from WIN32_FIND_DATA"""

    __slots__ = ['st_mode', 'st_ctime', 'st_mtime', 'st_atime',
                 'st_size']

    # os.stat always returns 0, so we hard code it here
    st_dev = 0
    st_ino = 0

    def __init__(self):
        """Create a new Stat object, based on the WIN32_FIND_DATA tuple"""
        pass

    def __repr__(self):
        """Repr is the same as a Stat object.

        (mode, ino, dev, nlink, uid, gid, size, atime, mtime, ctime)
        """
        return repr((self.st_mode, 0, 0, 0, 0, 0, self.st_size, self.st_atime,
                     self.st_mtime, self.st_ctime))



cdef class Win32Finder:
    """A class which encapsulates the search of files in a given directory"""

    cdef object _top
    cdef object _prefix

    cdef object _utf8_encode
    cdef object _directory_kind
    cdef object _file_kind

    cdef object _pending
    cdef object _last_dirblock

    def __init__(self, top, prefix=""):
        self._top = top
        self._prefix = prefix

        self._utf8_encode = codecs.getencoder('utf8')
        self._directory_kind = osutils._directory_kind
        self._file_kind = osutils._formats[stat.S_IFREG]

        self._pending = [(osutils.safe_utf8(prefix), None, None, None,
                          osutils.safe_unicode(top))]
        self._last_dirblock = None

    def __iter__(self):
        return self

    cdef object _get_name(self, WIN32_FIND_DATAW *data):
        """Extract the Unicode name for this file/dir."""
        name_unicode = PyUnicode_FromUnicode(data.cFileName,
                                             wcslen(data.cFileName))
        return name_unicode

    cdef int _get_mode_bits(self, WIN32_FIND_DATAW *data):
        cdef int mode_bits

        mode_bits = 0100666 # writeable file, the most common
        if data.dwFileAttributes & FILE_ATTRIBUTE_READONLY == FILE_ATTRIBUTE_READONLY:
            mode_bits ^= 0222 # remove the write bits
        if data.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY == FILE_ATTRIBUTE_DIRECTORY:
            # Remove the FILE bit, set the DIR bit, and set the EXEC bits
            mode_bits ^= 0140111
        return mode_bits

    cdef object _get_size(self, WIN32_FIND_DATAW *data):
        return long(data.nFileSizeLow) + (long(data.nFileSizeHigh) << 32)

    cdef object _get_stat_value(self, WIN32_FIND_DATAW *data):
        """Get the filename and the stat information."""
        statvalue = _Win32Stat()
        statvalue.st_mode = self._get_mode_bits(data)
        # TODO: Convert the filetimes
        statvalue.st_ctime = self._ftime_to_timestamp(&data.ftCreationTime)
        statvalue.st_atime = self._ftime_to_timestamp(&data.ftLastAccessTime)
        statvalue.st_mtime = self._ftime_to_timestamp(&data.ftLastWriteTime)
        statvalue.st_size = self._get_size(data)
        return statvalue

    cdef object _get_kind(self, WIN32_FIND_DATAW *data):
        if data.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY:
            return self._directory_kind
        return self._file_kind

    cdef int _should_skip(self, WIN32_FIND_DATAW *data):
        """Is this '.' or '..' so we should skip it?"""
        if (data.cFileName[0] != c'.'):
            return False
        if data.cFileName[1] == c'\0':
            return True
        if data.cFileName[1] == c'.' and data.cFileName[2] == c'\0':
            return True
        return False

    cdef double _ftime_to_timestamp(self, FILETIME *ft):
        """Convert from a FILETIME struct into a floating point timestamp.

        The fields of a FILETIME structure are the hi and lo part
        of a 64-bit value expressed in 100 nanosecond units.
        1e7 is one second in such units; 1e-7 the inverse.
        429.4967296 is 2**32 / 1e7 or 2**32 * 1e-7.
        It also uses the epoch 1601-01-01 rather than 1970-01-01
        (taken from posixmodule.c)
        """
        # cdef double secs_between_epochs = 11644473600
        return ((ft.dwHighDateTime * 429.4967296 + ft.dwLowDateTime * 1e-7)
                - 11644473600.0)

    def _get_files_in(self, directory, relprefix):
        cdef WIN32_FIND_DATAW search_data
        cdef HANDLE hFindFile
        cdef int last_err
        cdef WCHAR *query
        cdef int result

        top_star = directory + '*'

        dirblock = []
        append = dirblock.append

        query = PyUnicode_AS_UNICODE(top_star)
        hFindFile = FindFirstFileW(query, &search_data)
        if hFindFile == INVALID_HANDLE_VALUE:
            # Raise an exception? This path doesn't seem to exist
            last_err = GetLastError()
            # Could be last_err == ERROR_FILE_NOT_FOUND
            return []

        try:
            result = 1
            while result:
                # Skip '.' and '..'
                if self._should_skip(&search_data):
                    result = FindNextFileW(hFindFile, &search_data)
                    continue
                name_unicode = self._get_name(&search_data)
                name_utf8 = self._utf8_encode(name_unicode)[0]
                relpath = relprefix + name_utf8
                abspath = directory + name_unicode
                append((relpath, name_utf8, 
                        self._get_kind(&search_data),
                        self._get_stat_value(&search_data),
                        abspath))

                result = FindNextFileW(hFindFile, &search_data)
        finally:
            result = FindClose(hFindFile)
            if result == 0:
                last_err = GetLastError()
                pass
        return dirblock

        # for record in FindFilesIterator(top_star):
        #     name = record[-2]
        #     if name in ('.', '..'):
        #         continue
        #     attrib = record[0]
        #     statvalue = osutils._Win32Stat(record)
        #     name_utf8 = _utf8_encode(name)[0]
        #     abspath = top_slash + name
        #     if DIRECTORY & attrib == DIRECTORY:
        #         kind = _directory
        #     else:
        #         kind = _file
        #     append((relprefix + name_utf8, name_utf8, kind, statvalue, abspath))

    def __next__(self):
        if self._last_dirblock is not None:
            # push the entries left in the dirblock onto the pending queue
            # we do this here, because we allow the user to modified the
            # queue before the next iteration
            for d in reversed(self._last_dirblock):
                if d[2] == self._directory_kind:
                    self._pending.append(d)

        if not self._pending:
            raise StopIteration()
        relroot, _, _, _, top = self._pending.pop()
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
