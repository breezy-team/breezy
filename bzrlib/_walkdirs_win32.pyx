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
    cdef struct FINDFILE:
        int low
        int high

    cdef struct _HANDLE:
        pass
    ctypedef _HANDLE *HANDLE
    ctypedef unsigned int DWORD
    ctypedef unsigned short WCHAR
    cdef struct _FILETIME:
        pass
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

    cdef DWORD FILE_ATTRIBUTE_DIRECTORY

    cdef int GetLastError()


cdef extern from "Python.h":
    WCHAR *PyUnicode_AS_UNICODE(object)
    Py_ssize_t PyUnicode_GET_SIZE(object)


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

    def set_stuff(self):
        (attrib, ctime, atime, wtime, size_high, size_low,
         res0, res1, name, alt_name) = win32_find_data_record
        self.st_ctime = int(ctime)
        self.st_mtime = int(wtime)
        self.st_atime = int(atime)
        self.st_size = (size_high * 1<<32) + size_low

        mode_bits = 0100666 # writeable file, the most common
        if (win32file.FILE_ATTRIBUTE_READONLY & attrib ==
            win32file.FILE_ATTRIBUTE_READONLY):
            mode_bits ^= 0222 # remove writable bits
        if (win32file.FILE_ATTRIBUTE_DIRECTORY & attrib ==
            win32file.FILE_ATTRIBUTE_DIRECTORY):
            # Remove the FILE bit, set the DIR bit, and set the EXEC bits
            mode_bits ^= 0140111
        self.st_mode = mode_bits

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
    cdef object _directory
    cdef object _file

    cdef object _pending
    cdef object _last_dirblock

    def __init__(self, top, prefix=""):
        self._top = top
        self._prefix = prefix

        self._utf8_encode = codecs.getencoder('utf8')
        self._directory = osutils._directory_kind
        self._file = osutils._formats[stat.S_IFREG]

        self._pending = [(osutils.safe_utf8(prefix), None, None, None,
                          osutils.safe_unicode(top))]
        self._last_dirblock = None

    def __iter__(self):
        return self

    def _get_files_in(self, directory):
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
                if (search_data.cFileName[0] == c'.'
                    and (search_data.cFileName[1] == c'\0'
                         or (search_data.cFileName[1] == c'.'
                             and search_data.cFileName[2] == c'\0'))):
                    result = FindNextFileW(hFindFile, &search_data)
                    continue
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
                if d[2] == _directory:
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

        dirblock = self._get_files_in(top_slash)
        dirblock.sort(key=operator.itemgetter(1))
        self._last_dirblock = dirblock
        return (relroot, top), dirblock


def _walkdirs_utf8_win32_find_file(top, prefix=""):
    """Implement a version of walkdirs_utf8 for win32.

    This uses the find files api to both list the files and to stat them.
    """
    cdef WIN32_FIND_DATAW find_data

    _utf8_encode = codecs.getencoder('utf8')

    # WIN32_FIND_DATA object looks like:
    # (FILE_ATTRIBUTES, createTime, accessTime, writeTime, nFileSizeHigh,
    #  nFileSizeLow, reserved0, reserved1, name, alternateFilename)
    _directory = osutils._directory_kind
    _file = osutils._formats[stat.S_IFREG]

    # Possible attributes:
    DIRECTORY = FILE_ATTRIBUTE_DIRECTORY

    pending = [(osutils.safe_utf8(prefix), None, None, None,
                osutils.safe_unicode(top))]
    while pending:
        relroot, _, _, _, top = pending.pop()
        if relroot:
            relprefix = relroot + '/'
        else:
            relprefix = ''
        top_slash = top + '/'
        top_star = top_slash + '*'

        dirblock = []
        append = dirblock.append
        for record in FindFilesIterator(top_star):
            name = record[-2]
            if name in ('.', '..'):
                continue
            attrib = record[0]
            statvalue = osutils._Win32Stat(record)
            name_utf8 = _utf8_encode(name)[0]
            abspath = top_slash + name
            if DIRECTORY & attrib == DIRECTORY:
                kind = _directory
            else:
                kind = _file
            append((relprefix + name_utf8, name_utf8, kind, statvalue, abspath))
        dirblock.sort(key=operator.itemgetter(1))
        yield (relroot, top), dirblock

        # push the user specified dirs from dirblock
        for d in reversed(dirblock):
            if d[2] == _directory:
                pending.append(d)

