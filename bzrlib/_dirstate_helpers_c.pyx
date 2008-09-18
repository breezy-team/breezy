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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Helper functions for DirState.

This is the python implementation for DirState functions.
"""

import binascii
import bisect
import errno
import os
import stat

from bzrlib import cache_utf8, errors, osutils
from bzrlib.dirstate import DirState, pack_stat
from bzrlib.osutils import pathjoin, splitpath


# This is the Windows equivalent of ENOTDIR
# It is defined in pywin32.winerror, but we don't want a strong dependency for
# just an error code.
# XXX: Perhaps we could get it from a windows header ?
cdef int ERROR_PATH_NOT_FOUND
ERROR_PATH_NOT_FOUND = 3
cdef int ERROR_DIRECTORY
ERROR_DIRECTORY = 267

# Give Pyrex some function definitions for it to understand.
# All of these are just hints to Pyrex, so that it can try to convert python
# objects into similar C objects. (such as PyInt => int).
# In anything defined 'cdef extern from XXX' the real C header will be
# imported, and the real definition will be used from there. So these are just
# hints, and do not need to match exactly to the C definitions.

cdef extern from *:
    ctypedef unsigned long size_t

cdef extern from "_dirstate_helpers_c.h":
    ctypedef int intptr_t


cdef extern from "arpa/inet.h":
    unsigned long htonl(unsigned long)


cdef extern from "stdlib.h":
    unsigned long int strtoul(char *nptr, char **endptr, int base)

cdef extern from "stdio.h":
    void printf(char *format, ...)

cdef extern from 'sys/stat.h':
    int S_ISDIR(int mode)
    int S_ISREG(int mode)
    int S_ISLNK(int mode)
    int S_IXUSR

# These functions allow us access to a bit of the 'bare metal' of python
# objects, rather than going through the object abstraction. (For example,
# PyList_Append, rather than getting the 'append' attribute of the object, and
# creating a tuple, and then using PyCallObject).
# Functions that return (or take) a void* are meant to grab a C PyObject*. This
# differs from the Pyrex 'object'. If you declare a variable as 'object' Pyrex
# will automatically Py_INCREF and Py_DECREF when appropriate. But for some
# inner loops, we don't need to do that at all, as the reference only lasts for
# a very short time.
cdef extern from "Python.h":
    ctypedef int Py_ssize_t
    ctypedef struct PyObject:
        pass
    int PyList_Append(object lst, object item) except -1
    void *PyList_GetItem_object_void "PyList_GET_ITEM" (object lst, int index)
    void *PyList_GetItem_void_void "PyList_GET_ITEM" (void * lst, int index)
    int PyList_CheckExact(object)

    void *PyTuple_GetItem_void_void "PyTuple_GET_ITEM" (void* tpl, int index)
    object PyTuple_GetItem_void_object "PyTuple_GET_ITEM" (void* tpl, int index)

    char *PyString_AsString(object p)
    char *PyString_AsString_obj "PyString_AsString" (PyObject *string)
    char *PyString_AS_STRING_void "PyString_AS_STRING" (void *p)
    object PyString_FromString(char *)
    object PyString_FromStringAndSize(char *, Py_ssize_t)
    int PyString_Size(object p)
    int PyString_GET_SIZE_void "PyString_GET_SIZE" (void *p)
    int PyString_CheckExact(object p)
    void Py_INCREF(object o)
    void Py_DECREF(object o)


cdef extern from "string.h":
    int strncmp(char *s1, char *s2, int len)
    void *memchr(void *s, int c, size_t len)
    int memcmp(void *b1, void *b2, size_t len)
    # ??? memrchr is a GNU extension :(
    # void *memrchr(void *s, int c, size_t len)


cdef void* _my_memrchr(void *s, int c, size_t n):
    # memrchr seems to be a GNU extension, so we have to implement it ourselves
    cdef char *pos
    cdef char *start

    start = <char*>s
    pos = start + n - 1
    while pos >= start:
        if pos[0] == c:
            return <void*>pos
        pos = pos - 1
    return NULL


def _py_memrchr(s, c):
    """Just to expose _my_memrchr for testing.

    :param s: The Python string to search
    :param c: The character to search for
    :return: The offset to the last instance of 'c' in s
    """
    cdef void *_s
    cdef void *found
    cdef int length
    cdef char *_c

    _s = PyString_AsString(s)
    length = PyString_Size(s)

    _c = PyString_AsString(c)
    assert PyString_Size(c) == 1,\
        'Must be a single character string, not %s' % (c,)
    found = _my_memrchr(_s, _c[0], length)
    if found == NULL:
        return None
    return <char*>found - <char*>_s

cdef object safe_string_from_size(char *s, Py_ssize_t size):
    if size < 0:
        # XXX: On 64-bit machines the <int> cast causes a C compiler warning.
        raise AssertionError(
            'tried to create a string with an invalid size: %d @0x%x'
            % (size, <int>s))
    return PyString_FromStringAndSize(s, size)


cdef int _is_aligned(void *ptr):
    """Is this pointer aligned to an integer size offset?

    :return: 1 if this pointer is aligned, 0 otherwise.
    """
    return ((<intptr_t>ptr) & ((sizeof(int))-1)) == 0


cdef int _cmp_by_dirs(char *path1, int size1, char *path2, int size2):
    cdef unsigned char *cur1
    cdef unsigned char *cur2
    cdef unsigned char *end1
    cdef unsigned char *end2
    cdef int *cur_int1
    cdef int *cur_int2
    cdef int *end_int1
    cdef int *end_int2

    if path1 == path2 and size1 == size2:
        return 0

    end1 = <unsigned char*>path1+size1
    end2 = <unsigned char*>path2+size2

    # Use 32-bit comparisons for the matching portion of the string.
    # Almost all CPU's are faster at loading and comparing 32-bit integers,
    # than they are at 8-bit integers.
    # 99% of the time, these will be aligned, but in case they aren't just skip
    # this loop
    if _is_aligned(path1) and _is_aligned(path2):
        cur_int1 = <int*>path1
        cur_int2 = <int*>path2
        end_int1 = <int*>(path1 + size1 - (size1 % sizeof(int)))
        end_int2 = <int*>(path2 + size2 - (size2 % sizeof(int)))

        while cur_int1 < end_int1 and cur_int2 < end_int2:
            if cur_int1[0] != cur_int2[0]:
                break
            cur_int1 = cur_int1 + 1
            cur_int2 = cur_int2 + 1

        cur1 = <unsigned char*>cur_int1
        cur2 = <unsigned char*>cur_int2
    else:
        cur1 = <unsigned char*>path1
        cur2 = <unsigned char*>path2

    while cur1 < end1 and cur2 < end2:
        if cur1[0] == cur2[0]:
            # This character matches, just go to the next one
            cur1 = cur1 + 1
            cur2 = cur2 + 1
            continue
        # The current characters do not match
        if cur1[0] == c'/':
            return -1 # Reached the end of path1 segment first
        elif cur2[0] == c'/':
            return 1 # Reached the end of path2 segment first
        elif cur1[0] < cur2[0]:
            return -1
        else:
            return 1

    # We reached the end of at least one of the strings
    if cur1 < end1:
        return 1 # Not at the end of cur1, must be at the end of cur2
    if cur2 < end2:
        return -1 # At the end of cur1, but not at cur2
    # We reached the end of both strings
    return 0


def cmp_by_dirs_c(path1, path2):
    """Compare two paths directory by directory.

    This is equivalent to doing::

       cmp(path1.split('/'), path2.split('/'))

    The idea is that you should compare path components separately. This
    differs from plain ``cmp(path1, path2)`` for paths like ``'a-b'`` and
    ``a/b``. "a-b" comes after "a" but would come before "a/b" lexically.

    :param path1: first path
    :param path2: second path
    :return: negative number if ``path1`` comes first,
        0 if paths are equal,
        and positive number if ``path2`` sorts first
    """
    if not PyString_CheckExact(path1):
        raise TypeError("'path1' must be a plain string, not %s: %r"
                        % (type(path1), path1))
    if not PyString_CheckExact(path2):
        raise TypeError("'path2' must be a plain string, not %s: %r"
                        % (type(path2), path2))
    return _cmp_by_dirs(PyString_AsString(path1),
                        PyString_Size(path1),
                        PyString_AsString(path2),
                        PyString_Size(path2))


def _cmp_path_by_dirblock_c(path1, path2):
    """Compare two paths based on what directory they are in.

    This generates a sort order, such that all children of a directory are
    sorted together, and grandchildren are in the same order as the
    children appear. But all grandchildren come after all children.

    In other words, all entries in a directory are sorted together, and
    directorys are sorted in cmp_by_dirs order.

    :param path1: first path
    :param path2: the second path
    :return: negative number if ``path1`` comes first,
        0 if paths are equal
        and a positive number if ``path2`` sorts first
    """
    if not PyString_CheckExact(path1):
        raise TypeError("'path1' must be a plain string, not %s: %r"
                        % (type(path1), path1))
    if not PyString_CheckExact(path2):
        raise TypeError("'path2' must be a plain string, not %s: %r"
                        % (type(path2), path2))
    return _cmp_path_by_dirblock(PyString_AsString(path1),
                                 PyString_Size(path1),
                                 PyString_AsString(path2),
                                 PyString_Size(path2))


cdef int _cmp_path_by_dirblock(char *path1, int path1_len,
                               char *path2, int path2_len):
    """Compare two paths by what directory they are in.

    see ``_cmp_path_by_dirblock_c`` for details.
    """
    cdef char *dirname1
    cdef int dirname1_len
    cdef char *dirname2
    cdef int dirname2_len
    cdef char *basename1
    cdef int basename1_len
    cdef char *basename2
    cdef int basename2_len
    cdef int cur_len
    cdef int cmp_val

    if path1_len == 0 and path2_len == 0:
        return 0

    if path1 == path2 and path1_len == path2_len:
        return 0

    if path1_len == 0:
        return -1

    if path2_len == 0:
        return 1

    basename1 = <char*>_my_memrchr(path1, c'/', path1_len)

    if basename1 == NULL:
        basename1 = path1
        basename1_len = path1_len
        dirname1 = ''
        dirname1_len = 0
    else:
        dirname1 = path1
        dirname1_len = basename1 - path1
        basename1 = basename1 + 1
        basename1_len = path1_len - dirname1_len - 1

    basename2 = <char*>_my_memrchr(path2, c'/', path2_len)

    if basename2 == NULL:
        basename2 = path2
        basename2_len = path2_len
        dirname2 = ''
        dirname2_len = 0
    else:
        dirname2 = path2
        dirname2_len = basename2 - path2
        basename2 = basename2 + 1
        basename2_len = path2_len - dirname2_len - 1

    cmp_val = _cmp_by_dirs(dirname1, dirname1_len,
                           dirname2, dirname2_len)
    if cmp_val != 0:
        return cmp_val

    cur_len = basename1_len
    if basename2_len < basename1_len:
        cur_len = basename2_len

    cmp_val = memcmp(basename1, basename2, cur_len)
    if cmp_val != 0:
        return cmp_val
    if basename1_len == basename2_len:
        return 0
    if basename1_len < basename2_len:
        return -1
    return 1


def _bisect_path_left_c(paths, path):
    """Return the index where to insert path into paths.

    This uses a path-wise comparison so we get::
        a
        a-b
        a=b
        a/b
    Rather than::
        a
        a-b
        a/b
        a=b
    :param paths: A list of paths to search through
    :param path: A single path to insert
    :return: An offset where 'path' can be inserted.
    :seealso: bisect.bisect_left
    """
    cdef int _lo
    cdef int _hi
    cdef int _mid
    cdef char *path_cstr
    cdef int path_size
    cdef char *cur_cstr
    cdef int cur_size
    cdef void *cur

    if not PyList_CheckExact(paths):
        raise TypeError("you must pass a python list for 'paths' not: %s %r"
                        % (type(paths), paths))
    if not PyString_CheckExact(path):
        raise TypeError("you must pass a string for 'path' not: %s %r"
                        % (type(path), path))

    _hi = len(paths)
    _lo = 0

    path_cstr = PyString_AsString(path)
    path_size = PyString_Size(path)

    while _lo < _hi:
        _mid = (_lo + _hi) / 2
        cur = PyList_GetItem_object_void(paths, _mid)
        cur_cstr = PyString_AS_STRING_void(cur)
        cur_size = PyString_GET_SIZE_void(cur)
        if _cmp_path_by_dirblock(cur_cstr, cur_size, path_cstr, path_size) < 0:
            _lo = _mid + 1
        else:
            _hi = _mid
    return _lo


def _bisect_path_right_c(paths, path):
    """Return the index where to insert path into paths.

    This uses a path-wise comparison so we get::
        a
        a-b
        a=b
        a/b
    Rather than::
        a
        a-b
        a/b
        a=b
    :param paths: A list of paths to search through
    :param path: A single path to insert
    :return: An offset where 'path' can be inserted.
    :seealso: bisect.bisect_right
    """
    cdef int _lo
    cdef int _hi
    cdef int _mid
    cdef char *path_cstr
    cdef int path_size
    cdef char *cur_cstr
    cdef int cur_size
    cdef void *cur

    if not PyList_CheckExact(paths):
        raise TypeError("you must pass a python list for 'paths' not: %s %r"
                        % (type(paths), paths))
    if not PyString_CheckExact(path):
        raise TypeError("you must pass a string for 'path' not: %s %r"
                        % (type(path), path))

    _hi = len(paths)
    _lo = 0

    path_cstr = PyString_AsString(path)
    path_size = PyString_Size(path)

    while _lo < _hi:
        _mid = (_lo + _hi) / 2
        cur = PyList_GetItem_object_void(paths, _mid)
        cur_cstr = PyString_AS_STRING_void(cur)
        cur_size = PyString_GET_SIZE_void(cur)
        if _cmp_path_by_dirblock(path_cstr, path_size, cur_cstr, cur_size) < 0:
            _hi = _mid
        else:
            _lo = _mid + 1
    return _lo


def bisect_dirblock_c(dirblocks, dirname, lo=0, hi=None, cache=None):
    """Return the index where to insert dirname into the dirblocks.

    The return value idx is such that all directories blocks in dirblock[:idx]
    have names < dirname, and all blocks in dirblock[idx:] have names >=
    dirname.

    Optional args lo (default 0) and hi (default len(dirblocks)) bound the
    slice of a to be searched.
    """
    cdef int _lo
    cdef int _hi
    cdef int _mid
    cdef char *dirname_cstr
    cdef int dirname_size
    cdef char *cur_cstr
    cdef int cur_size
    cdef void *cur

    if not PyList_CheckExact(dirblocks):
        raise TypeError("you must pass a python list for 'dirblocks' not: %s %r"
                        % (type(dirblocks), dirblocks))
    if not PyString_CheckExact(dirname):
        raise TypeError("you must pass a string for dirname not: %s %r"
                        % (type(dirname), dirname))
    if hi is None:
        _hi = len(dirblocks)
    else:
        _hi = hi

    _lo = lo
    dirname_cstr = PyString_AsString(dirname)
    dirname_size = PyString_Size(dirname)

    while _lo < _hi:
        _mid = (_lo + _hi) / 2
        # Grab the dirname for the current dirblock
        # cur = dirblocks[_mid][0]
        cur = PyTuple_GetItem_void_void(
                PyList_GetItem_object_void(dirblocks, _mid), 0)
        cur_cstr = PyString_AS_STRING_void(cur)
        cur_size = PyString_GET_SIZE_void(cur)
        if _cmp_by_dirs(cur_cstr, cur_size, dirname_cstr, dirname_size) < 0:
            _lo = _mid + 1
        else:
            _hi = _mid
    return _lo


cdef class Reader:
    """Maintain the current location, and return fields as you parse them."""

    cdef object state # The DirState object
    cdef object text # The overall string object
    cdef char *text_cstr # Pointer to the beginning of text
    cdef int text_size # Length of text

    cdef char *end_cstr # End of text
    cdef char *cur_cstr # Pointer to the current record
    cdef char *next # Pointer to the end of this record

    def __init__(self, text, state):
        self.state = state
        self.text = text
        self.text_cstr = PyString_AsString(text)
        self.text_size = PyString_Size(text)
        self.end_cstr = self.text_cstr + self.text_size
        self.cur_cstr = self.text_cstr

    cdef char *get_next(self, int *size) except NULL:
        """Return a pointer to the start of the next field."""
        cdef char *next
        cdef Py_ssize_t extra_len

        if self.cur_cstr == NULL:
            raise AssertionError('get_next() called when cur_str is NULL')
        elif self.cur_cstr >= self.end_cstr:
            raise AssertionError('get_next() called when there are no chars'
                                 ' left')
        next = self.cur_cstr
        self.cur_cstr = <char*>memchr(next, c'\0', self.end_cstr - next)
        if self.cur_cstr == NULL:
            extra_len = self.end_cstr - next
            raise errors.DirstateCorrupt(self.state,
                'failed to find trailing NULL (\\0).'
                ' Trailing garbage: %r'
                % safe_string_from_size(next, extra_len))
        size[0] = self.cur_cstr - next
        self.cur_cstr = self.cur_cstr + 1
        return next

    cdef object get_next_str(self):
        """Get the next field as a Python string."""
        cdef int size
        cdef char *next
        next = self.get_next(&size)
        return safe_string_from_size(next, size)

    cdef int _init(self) except -1:
        """Get the pointer ready.

        This assumes that the dirstate header has already been read, and we
        already have the dirblock string loaded into memory.
        This just initializes our memory pointers, etc for parsing of the
        dirblock string.
        """
        cdef char *first
        cdef int size
        # The first field should be an empty string left over from the Header
        first = self.get_next(&size)
        if first[0] != c'\0' and size == 0:
            raise AssertionError('First character should be null not: %s'
                                 % (first,))
        return 0

    cdef object _get_entry(self, int num_trees, void **p_current_dirname,
                           int *new_block):
        """Extract the next entry.

        This parses the next entry based on the current location in
        ``self.cur_cstr``.
        Each entry can be considered a "row" in the total table. And each row
        has a fixed number of columns. It is generally broken up into "key"
        columns, then "current" columns, and then "parent" columns.

        :param num_trees: How many parent trees need to be parsed
        :param p_current_dirname: A pointer to the current PyString
            representing the directory name.
            We pass this in as a void * so that pyrex doesn't have to
            increment/decrement the PyObject reference counter for each
            _get_entry call.
            We use a pointer so that _get_entry can update it with the new
            value.
        :param new_block: This is to let the caller know that it needs to
            create a new directory block to store the next entry.
        """
        cdef object path_name_file_id_key
        cdef char *entry_size_cstr
        cdef unsigned long int entry_size
        cdef char* executable_cstr
        cdef int is_executable
        cdef char* dirname_cstr
        cdef char* trailing
        cdef int cur_size
        cdef int i
        cdef object minikind
        cdef object fingerprint
        cdef object info

        # Read the 'key' information (dirname, name, file_id)
        dirname_cstr = self.get_next(&cur_size)
        # Check to see if we have started a new directory block.
        # If so, then we need to create a new dirname PyString, so that it can
        # be used in all of the tuples. This saves time and memory, by re-using
        # the same object repeatedly.

        # Do the cheap 'length of string' check first. If the string is a
        # different length, then we *have* to be a different directory.
        if (cur_size != PyString_GET_SIZE_void(p_current_dirname[0])
            or strncmp(dirname_cstr,
                       # Extract the char* from our current dirname string.  We
                       # know it is a PyString, so we can use
                       # PyString_AS_STRING, we use the _void version because
                       # we are tricking Pyrex by using a void* rather than an
                       # <object>
                       PyString_AS_STRING_void(p_current_dirname[0]),
                       cur_size+1) != 0):
            dirname = safe_string_from_size(dirname_cstr, cur_size)
            p_current_dirname[0] = <void*>dirname
            new_block[0] = 1
        else:
            new_block[0] = 0

        # Build up the key that will be used.
        # By using <object>(void *) Pyrex will automatically handle the
        # Py_INCREF that we need.
        path_name_file_id_key = (<object>p_current_dirname[0],
                                 self.get_next_str(),
                                 self.get_next_str(),
                                )

        # Parse all of the per-tree information. current has the information in
        # the same location as parent trees. The only difference is that 'info'
        # is a 'packed_stat' for current, while it is a 'revision_id' for
        # parent trees.
        # minikind, fingerprint, and info will be returned as regular python
        # strings
        # entry_size and is_executable will be parsed into a python Long and
        # python Boolean, respectively.
        # TODO: jam 20070718 Consider changin the entry_size conversion to
        #       prefer python Int when possible. They are generally faster to
        #       work with, and it will be rare that we have a file >2GB.
        #       Especially since this code is pretty much fixed at a max of
        #       4GB.
        trees = []
        for i from 0 <= i < num_trees:
            minikind = self.get_next_str()
            fingerprint = self.get_next_str()
            entry_size_cstr = self.get_next(&cur_size)
            entry_size = strtoul(entry_size_cstr, NULL, 10)
            executable_cstr = self.get_next(&cur_size)
            is_executable = (executable_cstr[0] == c'y')
            info = self.get_next_str()
            PyList_Append(trees, (
                minikind,     # minikind
                fingerprint,  # fingerprint
                entry_size,   # size
                is_executable,# executable
                info,         # packed_stat or revision_id
            ))

        # The returned tuple is (key, [trees])
        ret = (path_name_file_id_key, trees)
        # Ignore the trailing newline, but assert that it does exist, this
        # ensures that we always finish parsing a line on an end-of-entry
        # marker.
        trailing = self.get_next(&cur_size)
        if cur_size != 1 or trailing[0] != c'\n':
            raise errors.DirstateCorrupt(self.state,
                'Bad parse, we expected to end on \\n, not: %d %s: %s'
                % (cur_size, safe_string_from_size(trailing, cur_size),
                   ret))
        return ret

    def _parse_dirblocks(self):
        """Parse all dirblocks in the state file."""
        cdef int num_trees
        cdef object current_block
        cdef object entry
        cdef void * current_dirname
        cdef int new_block
        cdef int expected_entry_count
        cdef int entry_count

        num_trees = self.state._num_present_parents() + 1
        expected_entry_count = self.state._num_entries

        # Ignore the first record
        self._init()

        current_block = []
        dirblocks = [('', current_block), ('', [])]
        self.state._dirblocks = dirblocks
        obj = ''
        current_dirname = <void*>obj
        new_block = 0
        entry_count = 0

        # TODO: jam 2007-05-07 Consider pre-allocating some space for the
        #       members, and then growing and shrinking from there. If most
        #       directories have close to 10 entries in them, it would save a
        #       few mallocs if we default our list size to something
        #       reasonable. Or we could malloc it to something large (100 or
        #       so), and then truncate. That would give us a malloc + realloc,
        #       rather than lots of reallocs.
        while self.cur_cstr < self.end_cstr:
            entry = self._get_entry(num_trees, &current_dirname, &new_block)
            if new_block:
                # new block - different dirname
                current_block = []
                PyList_Append(dirblocks,
                              (<object>current_dirname, current_block))
            PyList_Append(current_block, entry)
            entry_count = entry_count + 1
        if entry_count != expected_entry_count:
            raise errors.DirstateCorrupt(self.state,
                    'We read the wrong number of entries.'
                    ' We expected to read %s, but read %s'
                    % (expected_entry_count, entry_count))
        self.state._split_root_dirblock_into_contents()


def _read_dirblocks_c(state):
    """Read in the dirblocks for the given DirState object.

    This is tightly bound to the DirState internal representation. It should be
    thought of as a member function, which is only separated out so that we can
    re-write it in pyrex.

    :param state: A DirState object.
    :return: None
    :postcondition: The dirblocks will be loaded into the appropriate fields in
        the DirState object.
    """
    state._state_file.seek(state._end_of_header)
    text = state._state_file.read()
    # TODO: check the crc checksums. crc_measured = zlib.crc32(text)

    reader = Reader(text, state)

    reader._parse_dirblocks()
    state._dirblock_state = DirState.IN_MEMORY_UNMODIFIED


cdef int minikind_from_mode(int mode):
    # in order of frequency:
    if S_ISREG(mode):
        return c"f"
    if S_ISDIR(mode):
        return c"d"
    if S_ISLNK(mode):
        return c"l"
    return 0


#cdef object _encode
_encode = binascii.b2a_base64

from struct import pack
cdef _pack_stat(stat_value):
    """return a string representing the stat value's key fields.

    :param stat_value: A stat oject with st_size, st_mtime, st_ctime, st_dev,
        st_ino and st_mode fields.
    """
    cdef char result[6*4] # 6 long ints
    cdef int *aliased
    aliased = <int *>result
    aliased[0] = htonl(stat_value.st_size)
    aliased[1] = htonl(int(stat_value.st_mtime))
    aliased[2] = htonl(int(stat_value.st_ctime))
    aliased[3] = htonl(stat_value.st_dev)
    aliased[4] = htonl(stat_value.st_ino & 0xFFFFFFFF)
    aliased[5] = htonl(stat_value.st_mode)
    packed = PyString_FromStringAndSize(result, 6*4)
    return _encode(packed)[:-1]


def update_entry(self, entry, abspath, stat_value):
    """Update the entry based on what is actually on disk.

    :param entry: This is the dirblock entry for the file in question.
    :param abspath: The path on disk for this file.
    :param stat_value: (optional) if we already have done a stat on the
        file, re-use it.
    :return: The sha1 hexdigest of the file (40 bytes) or link target of a
            symlink.
    """
    return _update_entry(self, entry, abspath, stat_value)


cdef _update_entry(self, entry, abspath, stat_value):
    """Update the entry based on what is actually on disk.

    :param entry: This is the dirblock entry for the file in question.
    :param abspath: The path on disk for this file.
    :param stat_value: (optional) if we already have done a stat on the
        file, re-use it.
    :return: The sha1 hexdigest of the file (40 bytes) or link target of a
            symlink.
    """
    # TODO - require pyrex 0.8, then use a pyd file to define access to the _st
    # mode of the compiled stat objects.
    cdef int minikind, saved_minikind
    cdef void * details
    # pyrex 0.9.7 would allow cdef list details_list, and direct access rather
    # than PyList_GetItem_void_void below
    minikind = minikind_from_mode(stat_value.st_mode)
    if 0 == minikind:
        return None
    packed_stat = _pack_stat(stat_value)
    details = PyList_GetItem_void_void(PyTuple_GetItem_void_void(<void *>entry, 1), 0)
    saved_minikind = PyString_AsString_obj(<PyObject *>PyTuple_GetItem_void_void(details, 0))[0]
    saved_link_or_sha1 = PyTuple_GetItem_void_object(details, 1)
    saved_file_size = PyTuple_GetItem_void_object(details, 2)
    saved_executable = PyTuple_GetItem_void_object(details, 3)
    saved_packed_stat = PyTuple_GetItem_void_object(details, 4)
    # Deal with pyrex decrefing the objects
    Py_INCREF(saved_link_or_sha1)
    Py_INCREF(saved_file_size)
    Py_INCREF(saved_executable)
    Py_INCREF(saved_packed_stat)
    #(saved_minikind, saved_link_or_sha1, saved_file_size,
    # saved_executable, saved_packed_stat) = entry[1][0]

    if (minikind == saved_minikind
        and packed_stat == saved_packed_stat):
        # The stat hasn't changed since we saved, so we can re-use the
        # saved sha hash.
        if minikind == c'd':
            return None

        # size should also be in packed_stat
        if saved_file_size == stat_value.st_size:
            return saved_link_or_sha1

    # If we have gotten this far, that means that we need to actually
    # process this entry.
    link_or_sha1 = None
    if minikind == c'f':
        link_or_sha1 = self._sha1_file(abspath)
        executable = self._is_executable(stat_value.st_mode,
                                         saved_executable)
        if self._cutoff_time is None:
            self._sha_cutoff_time()
        if (stat_value.st_mtime < self._cutoff_time
            and stat_value.st_ctime < self._cutoff_time):
            entry[1][0] = ('f', link_or_sha1, stat_value.st_size,
                           executable, packed_stat)
        else:
            entry[1][0] = ('f', '', stat_value.st_size,
                           executable, DirState.NULLSTAT)
    elif minikind == c'd':
        link_or_sha1 = None
        entry[1][0] = ('d', '', 0, False, packed_stat)
        if saved_minikind != c'd':
            # This changed from something into a directory. Make sure we
            # have a directory block for it. This doesn't happen very
            # often, so this doesn't have to be super fast.
            block_index, entry_index, dir_present, file_present = \
                self._get_block_entry_index(entry[0][0], entry[0][1], 0)
            self._ensure_block(block_index, entry_index,
                               osutils.pathjoin(entry[0][0], entry[0][1]))
    elif minikind == c'l':
        link_or_sha1 = self._read_link(abspath, saved_link_or_sha1)
        if self._cutoff_time is None:
            self._sha_cutoff_time()
        if (stat_value.st_mtime < self._cutoff_time
            and stat_value.st_ctime < self._cutoff_time):
            entry[1][0] = ('l', link_or_sha1, stat_value.st_size,
                           False, packed_stat)
        else:
            entry[1][0] = ('l', '', stat_value.st_size,
                           False, DirState.NULLSTAT)
    self._dirblock_state = DirState.IN_MEMORY_MODIFIED
    return link_or_sha1


cdef char _minikind_from_string(object string):
    """Convert a python string to a char."""
    return PyString_AsString(string)[0]


cdef object _kind_absent
cdef object _kind_file
cdef object _kind_directory
cdef object _kind_symlink
cdef object _kind_relocated
cdef object _kind_tree_reference
_kind_absent = "absent"
_kind_file = "file"
_kind_directory = "directory"
_kind_symlink = "symlink"
_kind_relocated = "relocated"
_kind_tree_reference = "tree-reference"


cdef object _minikind_to_kind(char minikind):
    """Create a string kind for minikind."""
    cdef char _minikind[1]
    if minikind == c'f':
        return _kind_file
    elif minikind == c'd':
        return _kind_directory
    elif minikind == c'a':
        return _kind_absent
    elif minikind == c'r':
        return _kind_relocated
    elif minikind == c'l':
        return _kind_symlink
    elif minikind == c't':
        return _kind_tree_reference
    _minikind[0] = minikind
    raise KeyError(PyString_FromStringAndSize(_minikind, 1))


cdef int _versioned_minikind(char minikind):
    """Return non-zero if minikind is in fltd"""
    return (minikind == c'f' or
            minikind == c'd' or
            minikind == c'l' or
            minikind == c't')


cdef class ProcessEntryC:

    cdef object old_dirname_to_file_id # dict
    cdef object new_dirname_to_file_id # dict
    cdef readonly object uninteresting
    cdef object last_source_parent
    cdef object last_target_parent
    cdef object include_unchanged
    cdef object use_filesystem_for_exec
    cdef object utf8_decode
    cdef readonly object searched_specific_files
    cdef object search_specific_files
    cdef object state
    # Current iteration variables:
    cdef object current_root
    cdef object current_root_unicode
    cdef object root_entries
    cdef int root_entries_pos, root_entries_len
    cdef object root_abspath
    cdef int path_handled
    cdef int source_index, target_index
    cdef int want_unversioned
    cdef object tree
    cdef object dir_iterator
    cdef int block_index
    cdef object current_block
    cdef int current_block_pos
    cdef object current_dir_info
    cdef object root_dir_info
    cdef int path_index
    cdef object bisect_left

    def __init__(self, include_unchanged, use_filesystem_for_exec,
        search_specific_files, state, source_index, target_index,
        want_unversioned, tree):
        self.old_dirname_to_file_id = {}
        self.new_dirname_to_file_id = {}
        # Just a sentry, so that _process_entry can say that this
        # record is handled, but isn't interesting to process (unchanged)
        self.uninteresting = object()
        # Using a list so that we can access the values and change them in
        # nested scope. Each one is [path, file_id, entry]
        self.last_source_parent = [None, None]
        self.last_target_parent = [None, None]
        self.include_unchanged = include_unchanged
        self.use_filesystem_for_exec = use_filesystem_for_exec
        self.utf8_decode = cache_utf8._utf8_decode
        # for all search_indexs in each path at or under each element of
        # search_specific_files, if the detail is relocated: add the id, and add the
        # relocated path as one to search if its not searched already. If the
        # detail is not relocated, add the id.
        self.searched_specific_files = set()
        self.search_specific_files = search_specific_files
        self.state = state
        self.current_root = None
        self.current_root_unicode = None
        self.root_entries = None
        self.root_entries_pos = 0
        self.root_entries_len = 0
        self.root_abspath = None
        if source_index is None:
            self.source_index = -1
        else:
            self.source_index = source_index
        self.target_index = target_index
        self.want_unversioned = want_unversioned
        self.tree = tree
        self.dir_iterator = None
        self.block_index = -1
        self.current_block = None
        self.current_block_pos = -1
        self.current_dir_info = None
        self.path_index = 0
        self.root_dir_info = None
        self.bisect_left = bisect.bisect_left

    def _process_entry(self, entry, path_info):
        """Compare an entry and real disk to generate delta information.

        :param path_info: top_relpath, basename, kind, lstat, abspath for
            the path of entry. If None, then the path is considered absent.
            (Perhaps we should pass in a concrete entry for this ?)
            Basename is returned as a utf8 string because we expect this
            tuple will be ignored, and don't want to take the time to
            decode.
        :return: None if these don't match
                 A tuple of information about the change, or
                 the object 'uninteresting' if these match, but are
                 basically identical.
        """
        cdef char target_minikind
        cdef char source_minikind
        cdef object file_id
        cdef int content_change
        cdef object details_list
        file_id = None
        details_list = entry[1]
        if -1 == self.source_index:
            source_details = DirState.NULL_PARENT_DETAILS
        else:
            source_details = details_list[self.source_index]
        target_details = details_list[self.target_index]
        target_minikind = _minikind_from_string(target_details[0])
        if path_info is not None and _versioned_minikind(target_minikind):
            if self.target_index != 0:
                raise AssertionError("Unsupported target index %d" % target_index)
            link_or_sha1 = _update_entry(self.state, entry, path_info[4], path_info[3])
            # The entry may have been modified by update_entry
            target_details = details_list[self.target_index]
            target_minikind = _minikind_from_string(target_details[0])
        else:
            link_or_sha1 = None
        # the rest of this function is 0.3 seconds on 50K paths, or
        # 0.000006 seconds per call.
        source_minikind = _minikind_from_string(source_details[0])
        if ((_versioned_minikind(source_minikind) or source_minikind == c'r')
            and _versioned_minikind(target_minikind)):
            # claimed content in both: diff
            #   r    | fdlt   |      | add source to search, add id path move and perform
            #        |        |      | diff check on source-target
            #   r    | fdlt   |  a   | dangling file that was present in the basis.
            #        |        |      | ???
            if source_minikind != c'r':
                old_dirname = entry[0][0]
                old_basename = entry[0][1]
                old_path = path = None
            else:
                # add the source to the search path to find any children it
                # has.  TODO ? : only add if it is a container ?
                if not osutils.is_inside_any(self.searched_specific_files,
                                             source_details[1]):
                    self.search_specific_files.add(source_details[1])
                # generate the old path; this is needed for stating later
                # as well.
                old_path = source_details[1]
                old_dirname, old_basename = os.path.split(old_path)
                path = pathjoin(entry[0][0], entry[0][1])
                old_entry = self.state._get_entry(self.source_index,
                                             path_utf8=old_path)
                # update the source details variable to be the real
                # location.
                if old_entry == (None, None):
                    raise errors.CorruptDirstate(self.state._filename,
                        "entry '%s/%s' is considered renamed from %r"
                        " but source does not exist\n"
                        "entry: %s" % (entry[0][0], entry[0][1], old_path, entry))
                source_details = old_entry[1][self.source_index]
                source_minikind = _minikind_from_string(source_details[0])
            if path_info is None:
                # the file is missing on disk, show as removed.
                content_change = 1
                target_kind = None
                target_exec = False
            else:
                # source and target are both versioned and disk file is present.
                target_kind = path_info[2]
                if target_kind == 'directory':
                    if path is None:
                        old_path = path = pathjoin(old_dirname, old_basename)
                    file_id = entry[0][2]
                    self.new_dirname_to_file_id[path] = file_id
                    if source_minikind != c'd':
                        content_change = 1
                    else:
                        # directories have no fingerprint
                        content_change = 0
                    target_exec = False
                elif target_kind == 'file':
                    if source_minikind != c'f':
                        content_change = 1
                    else:
                        # We could check the size, but we already have the
                        # sha1 hash.
                        content_change = (link_or_sha1 != source_details[1])
                    # Target details is updated at update_entry time
                    if self.use_filesystem_for_exec:
                        # We don't need S_ISREG here, because we are sure
                        # we are dealing with a file.
                        target_exec = bool(S_IXUSR & path_info[3].st_mode)
                    else:
                        target_exec = target_details[3]
                elif target_kind == 'symlink':
                    if source_minikind != c'l':
                        content_change = 1
                    else:
                        content_change = (link_or_sha1 != source_details[1])
                    target_exec = False
                elif target_kind == 'tree-reference':
                    if source_minikind != c't':
                        content_change = 1
                    else:
                        content_change = 0
                    target_exec = False
                else:
                    raise Exception, "unknown kind %s" % path_info[2]
            if source_minikind == c'd':
                if path is None:
                    old_path = path = pathjoin(old_dirname, old_basename)
                if file_id is None:
                    file_id = entry[0][2]
                self.old_dirname_to_file_id[old_path] = file_id
            # parent id is the entry for the path in the target tree
            if old_dirname == self.last_source_parent[0]:
                source_parent_id = self.last_source_parent[1]
            else:
                try:
                    source_parent_id = self.old_dirname_to_file_id[old_dirname]
                except KeyError:
                    source_parent_entry = self.state._get_entry(self.source_index,
                                                           path_utf8=old_dirname)
                    source_parent_id = source_parent_entry[0][2]
                if source_parent_id == entry[0][2]:
                    # This is the root, so the parent is None
                    source_parent_id = None
                else:
                    self.last_source_parent[0] = old_dirname
                    self.last_source_parent[1] = source_parent_id
            new_dirname = entry[0][0]
            if new_dirname == self.last_target_parent[0]:
                target_parent_id = self.last_target_parent[1]
            else:
                try:
                    target_parent_id = self.new_dirname_to_file_id[new_dirname]
                except KeyError:
                    # TODO: We don't always need to do the lookup, because the
                    #       parent entry will be the same as the source entry.
                    target_parent_entry = self.state._get_entry(self.target_index,
                                                           path_utf8=new_dirname)
                    if target_parent_entry == (None, None):
                        raise AssertionError(
                            "Could not find target parent in wt: %s\nparent of: %s"
                            % (new_dirname, entry))
                    target_parent_id = target_parent_entry[0][2]
                if target_parent_id == entry[0][2]:
                    # This is the root, so the parent is None
                    target_parent_id = None
                else:
                    self.last_target_parent[0] = new_dirname
                    self.last_target_parent[1] = target_parent_id

            source_exec = source_details[3]
            if (self.include_unchanged
                or content_change
                or source_parent_id != target_parent_id
                or old_basename != entry[0][1]
                or source_exec != target_exec
                ):
                if old_path is None:
                    path = pathjoin(old_dirname, old_basename)
                    old_path = path
                    old_path_u = self.utf8_decode(old_path)[0]
                    path_u = old_path_u
                else:
                    old_path_u = self.utf8_decode(old_path)[0]
                    if old_path == path:
                        path_u = old_path_u
                    else:
                        path_u = self.utf8_decode(path)[0]
                source_kind = _minikind_to_kind(source_minikind)
                return (entry[0][2],
                       (old_path_u, path_u),
                       content_change,
                       (True, True),
                       (source_parent_id, target_parent_id),
                       (self.utf8_decode(old_basename)[0], self.utf8_decode(entry[0][1])[0]),
                       (source_kind, target_kind),
                       (source_exec, target_exec))
            else:
                return self.uninteresting
        elif source_minikind == c'a' and _versioned_minikind(target_minikind):
            # looks like a new file
            path = pathjoin(entry[0][0], entry[0][1])
            # parent id is the entry for the path in the target tree
            # TODO: these are the same for an entire directory: cache em.
            parent_id = self.state._get_entry(self.target_index,
                                         path_utf8=entry[0][0])[0][2]
            if parent_id == entry[0][2]:
                parent_id = None
            if path_info is not None:
                # Present on disk:
                if self.use_filesystem_for_exec:
                    # We need S_ISREG here, because we aren't sure if this
                    # is a file or not.
                    target_exec = bool(
                        S_ISREG(path_info[3].st_mode)
                        and S_IXUSR & path_info[3].st_mode)
                else:
                    target_exec = target_details[3]
                return (entry[0][2],
                       (None, self.utf8_decode(path)[0]),
                       True,
                       (False, True),
                       (None, parent_id),
                       (None, self.utf8_decode(entry[0][1])[0]),
                       (None, path_info[2]),
                       (None, target_exec))
            else:
                # Its a missing file, report it as such.
                return (entry[0][2],
                       (None, self.utf8_decode(path)[0]),
                       False,
                       (False, True),
                       (None, parent_id),
                       (None, self.utf8_decode(entry[0][1])[0]),
                       (None, None),
                       (None, False))
        elif _versioned_minikind(source_minikind) and target_minikind == c'a':
            # unversioned, possibly, or possibly not deleted: we dont care.
            # if its still on disk, *and* theres no other entry at this
            # path [we dont know this in this routine at the moment -
            # perhaps we should change this - then it would be an unknown.
            old_path = pathjoin(entry[0][0], entry[0][1])
            # parent id is the entry for the path in the target tree
            parent_id = self.state._get_entry(self.source_index, path_utf8=entry[0][0])[0][2]
            if parent_id == entry[0][2]:
                parent_id = None
            return (entry[0][2],
                   (self.utf8_decode(old_path)[0], None),
                   True,
                   (True, False),
                   (parent_id, None),
                   (self.utf8_decode(entry[0][1])[0], None),
                   (_minikind_to_kind(source_minikind), None),
                   (source_details[3], None))
        elif _versioned_minikind(source_minikind) and target_minikind == c'r':
            # a rename; could be a true rename, or a rename inherited from
            # a renamed parent. TODO: handle this efficiently. Its not
            # common case to rename dirs though, so a correct but slow
            # implementation will do.
            if not osutils.is_inside_any(self.searched_specific_files, target_details[1]):
                self.search_specific_files.add(target_details[1])
        elif ((source_minikind == c'r' or source_minikind == c'a') and
              (target_minikind == c'r' or target_minikind == c'a')):
            # neither of the selected trees contain this file,
            # so skip over it. This is not currently directly tested, but
            # is indirectly via test_too_much.TestCommands.test_conflicts.
            pass
        else:
            raise AssertionError("don't know how to compare "
                "source_minikind=%r, target_minikind=%r"
                % (source_minikind, target_minikind))
            ## import pdb;pdb.set_trace()
        return None

    def __iter__(self):
        return self

    def iter_changes(self):
        return self

    cdef void _update_current_block(self):
        if (self.block_index < len(self.state._dirblocks) and
            osutils.is_inside(self.current_root, self.state._dirblocks[self.block_index][0])):
            self.current_block = self.state._dirblocks[self.block_index]
            self.current_block_pos = 0
        else:
            self.current_block = None

    def __next__(self):
        # Simple thunk to allow tail recursion without pyrex confusion
        return self._iter_next()

    cdef _iter_next(self):
        """Iterate over the changes."""
        # This function single steps through an iterator. As such while loops
        # are often exited by 'return' - the code is structured so that the
        # next call into the function will return to the same while loop. Note
        # that all flow control needed to re-reach that step is reexecuted,
        # which can be a performance problem. It has not yet been tuned to
        # minimise this; a state machine is probably the simplest restructuring
        # to both minimise this overhead and make the code considerably more
        # understandable.

        # sketch: 
        # compare source_index and target_index at or under each element of search_specific_files.
        # follow the following comparison table. Note that we only want to do diff operations when
        # the target is fdl because thats when the walkdirs logic will have exposed the pathinfo 
        # for the target.
        # cases:
        # 
        # Source | Target | disk | action
        #   r    | fdlt   |      | add source to search, add id path move and perform
        #        |        |      | diff check on source-target
        #   r    | fdlt   |  a   | dangling file that was present in the basis. 
        #        |        |      | ???
        #   r    |  a     |      | add source to search
        #   r    |  a     |  a   | 
        #   r    |  r     |      | this path is present in a non-examined tree, skip.
        #   r    |  r     |  a   | this path is present in a non-examined tree, skip.
        #   a    | fdlt   |      | add new id
        #   a    | fdlt   |  a   | dangling locally added file, skip
        #   a    |  a     |      | not present in either tree, skip
        #   a    |  a     |  a   | not present in any tree, skip
        #   a    |  r     |      | not present in either tree at this path, skip as it
        #        |        |      | may not be selected by the users list of paths.
        #   a    |  r     |  a   | not present in either tree at this path, skip as it
        #        |        |      | may not be selected by the users list of paths.
        #  fdlt  | fdlt   |      | content in both: diff them
        #  fdlt  | fdlt   |  a   | deleted locally, but not unversioned - show as deleted ?
        #  fdlt  |  a     |      | unversioned: output deleted id for now
        #  fdlt  |  a     |  a   | unversioned and deleted: output deleted id
        #  fdlt  |  r     |      | relocated in this tree, so add target to search.
        #        |        |      | Dont diff, we will see an r,fd; pair when we reach
        #        |        |      | this id at the other path.
        #  fdlt  |  r     |  a   | relocated in this tree, so add target to search.
        #        |        |      | Dont diff, we will see an r,fd; pair when we reach
        #        |        |      | this id at the other path.

        # TODO: jam 20070516 - Avoid the _get_entry lookup overhead by
        #       keeping a cache of directories that we have seen.
        cdef object current_dirname, current_blockname
        cdef char * current_dirname_c, * current_blockname_c
        _process_entry = self._process_entry
        uninteresting = self.uninteresting
        searched_specific_files = self.searched_specific_files
        # Are we walking a root?
        while self.root_entries_pos < self.root_entries_len:
            entry = self.root_entries[self.root_entries_pos]
            self.root_entries_pos = self.root_entries_pos + 1
            result = _process_entry(entry, self.root_dir_info)
            if result is not None and result is not self.uninteresting:
                return result
        # Have we finished the prior root, or never started one ?
        if self.current_root is None:
            # TODO: the pending list should be lexically sorted?  the
            # interface doesn't require it.
            try:
                self.current_root = self.search_specific_files.pop()
            except KeyError:
                raise StopIteration()
            self.current_root_unicode = self.current_root.decode('utf8')
            self.searched_specific_files.add(self.current_root)
            # process the entries for this containing directory: the rest will be
            # found by their parents recursively.
            self.root_entries = self.state._entries_for_path(self.current_root)
            self.root_entries_len = len(self.root_entries)
            self.root_abspath = self.tree.abspath(self.current_root_unicode)
            try:
                root_stat = os.lstat(self.root_abspath)
            except OSError, e:
                if e.errno == errno.ENOENT:
                    # the path does not exist: let _process_entry know that.
                    self.root_dir_info = None
                else:
                    # some other random error: hand it up.
                    raise
            else:
                self.root_dir_info = ('', self.current_root,
                    osutils.file_kind_from_stat_mode(root_stat.st_mode), root_stat,
                    self.root_abspath)
                if self.root_dir_info[2] == 'directory':
                    if self.tree._directory_is_tree_reference(
                        self.current_root_unicode):
                        self.root_dir_info = self.root_dir_info[:2] + \
                            ('tree-reference',) + self.root_dir_info[3:]
            if not self.root_entries and not self.root_dir_info:
                # this specified path is not present at all, skip it.
                # (tail recursion, can do a loop once the full structure is
                # known).
                return self._iter_next()
            self.path_handled = 0
            self.root_entries_pos = 0
            # XXX Clarity: This loop is duplicated a out the self.current_root
            # is None guard above: if we return from it, it completes there
            # (and the following if block cannot trigger because
            # self.path_handled must be true, so the if block is not
            # duplicated.
            while self.root_entries_pos < self.root_entries_len:
                entry = self.root_entries[self.root_entries_pos]
                self.root_entries_pos = self.root_entries_pos + 1
                result = _process_entry(entry, self.root_dir_info)
                if result is not None:
                    self.path_handled = -1
                    if result is not self.uninteresting:
                        return result
            # handle unversioned specified paths:
            if self.want_unversioned and not self.path_handled and self.root_dir_info:
                new_executable = bool(
                    stat.S_ISREG(self.root_dir_info[3].st_mode)
                    and stat.S_IEXEC & self.root_dir_info[3].st_mode)
                return (None,
                       (None, self.current_root_unicode),
                       True,
                       (False, False),
                       (None, None),
                       (None, splitpath(self.current_root_unicode)[-1]),
                       (None, self.root_dir_info[2]),
                       (None, new_executable)
                      )
            # If we reach here, the outer flow continues, which enters into the
            # per-root setup logic.
        if self.current_dir_info is None and self.current_block is None:
            # setup iteration of this root:
            if self.root_dir_info and self.root_dir_info[2] == 'tree-reference':
                self.current_dir_info = None
            else:
                self.dir_iterator = osutils._walkdirs_utf8(self.root_abspath,
                    prefix=self.current_root)
                self.path_index = 0
                try:
                    self.current_dir_info = self.dir_iterator.next()
                except OSError, e:
                    # there may be directories in the inventory even though
                    # this path is not a file on disk: so mark it as end of
                    # iterator
                    if e.errno in (errno.ENOENT, errno.ENOTDIR, errno.EINVAL):
                        self.current_dir_info = None
                    elif sys.platform == 'win32':
                        # on win32, python2.4 has e.errno == ERROR_DIRECTORY, but
                        # python 2.5 has e.errno == EINVAL,
                        #            and e.winerror == ERROR_DIRECTORY
                        try:
                            e_winerror = e.winerror
                        except AttributeError:
                            e_winerror = None
                        win_errors = (ERROR_DIRECTORY, ERROR_PATH_NOT_FOUND)
                        if (e.errno in win_errors or e_winerror in win_errors):
                            self.current_dir_info = None
                        else:
                            # Will this really raise the right exception ?
                            raise
                    else:
                        raise
                else:
                    if self.current_dir_info[0][0] == '':
                        # remove .bzr from iteration
                        bzr_index = self.bisect_left(self.current_dir_info[1], ('.bzr',))
                        if self.current_dir_info[1][bzr_index][0] != '.bzr':
                            raise AssertionError()
                        del self.current_dir_info[1][bzr_index]
            initial_key = (self.current_root, '', '')
            self.block_index, _ = self.state._find_block_index_from_key(initial_key)
            if self.block_index == 0:
                # we have processed the total root already, but because the
                # initial key matched it we should skip it here.
                self.block_index = self.block_index + 1
            self._update_current_block()
        # walk until both the directory listing and the versioned metadata
        # are exhausted. 
        while (self.current_dir_info is not None
            or self.current_block is not None):
            if (self.current_dir_info and self.current_block
                and self.current_dir_info[0][0] != self.current_block[0]):
                # Work around pyrex broken heuristic - current_dirname has
                # the same scope as current_dirname_c
                current_dirname = self.current_dir_info[0][0]
                current_dirname_c = PyString_AS_STRING_void(
                    <void *>current_dirname)
                current_blockname = self.current_block[0]
                current_blockname_c = PyString_AS_STRING_void(
                    <void *>current_blockname)
                # In the python generator we evaluate this if block once per
                # dir+block; because we reenter in the pyrex version its being
                # evaluated once per path: we could cache the result before
                # doing the while loop and probably save time.
                if _cmp_by_dirs(current_dirname_c,
                    PyString_Size(current_dirname),
                    current_blockname_c,
                    PyString_Size(current_blockname)) < 0:
                    # filesystem data refers to paths not covered by the
                    # dirblock.  this has two possibilities:
                    # A) it is versioned but empty, so there is no block for it
                    # B) it is not versioned.

                    # if (A) then we need to recurse into it to check for
                    # new unknown files or directories.
                    # if (B) then we should ignore it, because we don't
                    # recurse into unknown directories.
                    # We are doing a loop
                    while self.path_index < len(self.current_dir_info[1]):
                        current_path_info = self.current_dir_info[1][self.path_index]
                        # dont descend into this unversioned path if it is
                        # a dir
                        if current_path_info[2] in ('directory',
                                                    'tree-reference'):
                            del self.current_dir_info[1][self.path_index]
                            self.path_index = self.path_index - 1
                        self.path_index = self.path_index + 1
                        if self.want_unversioned:
                            if current_path_info[2] == 'directory':
                                if self.tree._directory_is_tree_reference(
                                    self.utf8_decode(current_path_info[0])[0]):
                                    current_path_info = current_path_info[:2] + \
                                        ('tree-reference',) + current_path_info[3:]
                            new_executable = bool(
                                stat.S_ISREG(current_path_info[3].st_mode)
                                and stat.S_IEXEC & current_path_info[3].st_mode)
                            return (None,
                                (None, self.utf8_decode(current_path_info[0])[0]),
                                True,
                                (False, False),
                                (None, None),
                                (None, self.utf8_decode(current_path_info[1])[0]),
                                (None, current_path_info[2]),
                                (None, new_executable))
                    # This dir info has been handled, go to the next
                    self.path_index = 0
                    try:
                        self.current_dir_info = self.dir_iterator.next()
                    except StopIteration:
                        self.current_dir_info = None
                else: #(dircmp > 0)
                    # We have a dirblock entry for this location, but there
                    # is no filesystem path for this. This is most likely
                    # because a directory was removed from the disk.
                    # We don't have to report the missing directory,
                    # because that should have already been handled, but we
                    # need to handle all of the files that are contained
                    # within.
                    while self.current_block_pos < len(self.current_block[1]):
                        current_entry = self.current_block[1][self.current_block_pos]
                        self.current_block_pos = self.current_block_pos + 1
                        # entry referring to file not present on disk.
                        # advance the entry only, after processing.
                        result = _process_entry(current_entry, None)
                        if result is not None:
                            if result is not self.uninteresting:
                                return result
                    self.block_index = self.block_index + 1
                    self._update_current_block()
                continue # next loop-on-block/dir
            # current_dir_info and current_block refer to the same directory.
            advance_entry = True
            advance_path = True
            # Assign local variables for current path and entry:
            if (self.current_block and
                self.current_block_pos < len(self.current_block[1])):
                current_entry = self.current_block[1][self.current_block_pos]
            else:
                current_entry = None
            if (self.current_dir_info and
                self.path_index < len(self.current_dir_info[1])):
                current_path_info = self.current_dir_info[1][self.path_index]
                if current_path_info[2] == 'directory':
                    if self.tree._directory_is_tree_reference(
                        self.utf8_decode(current_path_info[0])[0]):
                        current_path_info = current_path_info[:2] + \
                            ('tree-reference',) + current_path_info[3:]
            else:
                current_path_info = None
            self.path_handled = 0
            while (current_entry is not None or current_path_info is not None):
                result = None
                if current_entry is None:
                    # unversioned -  the check for path_handled when the path
                    # is advanced will yield this path if needed.
                    pass
                elif current_path_info is None:
                    # no path is fine: the per entry code will handle it.
                    result = _process_entry(current_entry, current_path_info)
                    if result is not None:
                        if result is self.uninteresting:
                            result = None
                elif (current_entry[0][1] != current_path_info[1]
                      or current_entry[1][self.target_index][0] in 'ar'):
                    # The current path on disk doesn't match the dirblock
                    # record. Either the dirblock is marked as absent, or
                    # the file on disk is not present at all in the
                    # dirblock. Either way, report about the dirblock
                    # entry, and let other code handle the filesystem one.

                    # Compare the basename for these files to determine
                    # which comes first
                    if current_path_info[1] < current_entry[0][1]:
                        # extra file on disk: pass for now, but only
                        # increment the path, not the entry
                        advance_entry = False
                    else:
                        # entry referring to file not present on disk.
                        # advance the entry only, after processing.
                        result = _process_entry(current_entry, None)
                        if result is not None:
                            if result is self.uninteresting:
                                result = None
                        advance_path = False
                else:
                    result = _process_entry(current_entry, current_path_info)
                    if result is not None:
                        self.path_handled = -1
                        if result is self.uninteresting:
                            result = None
                # >- loop control
                # >- entry
                if advance_entry and current_entry is not None:
                    self.current_block_pos = self.current_block_pos + 1
                    if self.current_block_pos < len(self.current_block[1]):
                        current_entry = self.current_block[1][self.current_block_pos]
                    else:
                        current_entry = None
                else:
                    advance_entry = True # reset the advance flaga
                # >- path
                if advance_path and current_path_info is not None:
                    if not self.path_handled:
                        # unversioned in all regards
                        if self.want_unversioned:
                            new_executable = bool(
                                stat.S_ISREG(current_path_info[3].st_mode)
                                and stat.S_IEXEC & current_path_info[3].st_mode)
                            try:
                                relpath_unicode = self.utf8_decode(current_path_info[0])[0]
                            except UnicodeDecodeError:
                                raise errors.BadFilenameEncoding(
                                    current_path_info[0], osutils._fs_enc)
                            if result is not None:
                                raise AssertionError(
                                    "result is not None: %r" % result)
                            result = (None,
                                (None, relpath_unicode),
                                True,
                                (False, False),
                                (None, None),
                                (None, self.utf8_decode(current_path_info[1])[0]),
                                (None, current_path_info[2]),
                                (None, new_executable))
                        # dont descend into this unversioned path if it is
                        # a dir
                        if current_path_info[2] in ('directory'):
                            del self.current_dir_info[1][self.path_index]
                            self.path_index = self.path_index - 1
                    # dont descend the disk iterator into any tree 
                    # paths.
                    if current_path_info[2] == 'tree-reference':
                        del self.current_dir_info[1][self.path_index]
                        self.path_index = self.path_index - 1
                    self.path_index = self.path_index + 1
                    if self.path_index < len(self.current_dir_info[1]):
                        current_path_info = self.current_dir_info[1][self.path_index]
                        if current_path_info[2] == 'directory':
                            if self.tree._directory_is_tree_reference(
                                current_path_info[0].decode('utf8')):
                                current_path_info = current_path_info[:2] + \
                                    ('tree-reference',) + current_path_info[3:]
                    else:
                        current_path_info = None
                    self.path_handled = 0
                else:
                    advance_path = True # reset the advance flag.
                if result is not None:
                    # Found a result on this pass, yield it
                    return result
            if self.current_block is not None:
                self.block_index = self.block_index + 1
                self._update_current_block()
            if self.current_dir_info is not None:
                self.path_index = 0
                try:
                    self.current_dir_info = self.dir_iterator.next()
                except StopIteration:
                    self.current_dir_info = None
        if len(self.search_specific_files):
            # More supplied paths to process
            self.current_root = None
            return self._iter_next()
        raise StopIteration()
