# Copyright (C) 2007-2010 Canonical Ltd
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
#
# cython: language_level=3

"""Helper functions for DirState.

This is the python implementation for DirState functions.
"""

import binascii
import bisect
import codecs
import errno
import os
import stat
import sys

from .. import errors, osutils
from ..osutils import (is_inside, is_inside_any, parent_directories, pathjoin,
                       splitpath)
from .dirstate import DirState, DirstateCorrupt
from .inventorytree import InventoryTreeChange

from cpython.tuple cimport PyTuple_New, PyTuple_SET_ITEM


# This is the Windows equivalent of ENOTDIR
# It is defined in pywin32.winerror, but we don't want a strong dependency for
# just an error code.
# XXX: Perhaps we could get it from a windows header ?
cdef int ERROR_PATH_NOT_FOUND
ERROR_PATH_NOT_FOUND = 3
cdef int ERROR_DIRECTORY
ERROR_DIRECTORY = 267

cdef extern from "python-compat.h":
    unsigned long htonl(unsigned long)

# Give Pyrex some function definitions for it to understand.
# All of these are just hints to Pyrex, so that it can try to convert python
# objects into similar C objects. (such as PyInt => int).
# In anything defined 'cdef extern from XXX' the real C header will be
# imported, and the real definition will be used from there. So these are just
# hints, and do not need to match exactly to the C definitions.

cdef extern from *:
    ctypedef unsigned long size_t

cdef extern from "_dirstate_helpers_pyx.h":
    ctypedef int intptr_t


cdef extern from "stdlib.h":
    unsigned long int strtoul(char *nptr, char **endptr, int base)


cdef extern from 'sys/stat.h':
    int S_ISDIR(int mode)
    int S_ISREG(int mode)
    # On win32, this actually comes from "python-compat.h"
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
# Note that the C API GetItem calls borrow references, so pyrex does the wrong
# thing if you declare e.g. object PyList_GetItem(object lst, int index) - you
# need to manually Py_INCREF yourself.
cdef extern from "Python.h":
    ctypedef int Py_ssize_t
    ctypedef struct PyObject:
        pass
    int PyList_Append(object lst, object item) except -1
    void *PyList_GetItem_object_void "PyList_GET_ITEM" (object lst, int index)
    void *PyList_GetItem_void_void "PyList_GET_ITEM" (void * lst, int index)
    object PyList_GET_ITEM(object lst, Py_ssize_t index)
    int PyList_CheckExact(object)
    Py_ssize_t PyList_GET_SIZE (object p)

    void *PyTuple_GetItem_void_void "PyTuple_GET_ITEM" (void* tpl, int index)
    object PyTuple_GetItem_void_object "PyTuple_GET_ITEM" (void* tpl, int index)
    object PyTuple_GET_ITEM(object tpl, Py_ssize_t index)

    unsigned long PyInt_AsUnsignedLongMask(object number) except? -1

    char *PyBytes_AsString(object p)
    char *PyBytes_AsString_obj "PyBytes_AsString" (PyObject *string)
    char *PyBytes_AS_STRING_void "PyBytes_AS_STRING" (void *p)
    int PyBytes_AsStringAndSize(object str, char **buffer, Py_ssize_t *length) except -1
    object PyBytes_FromString(char *)
    object PyBytes_FromStringAndSize(char *, Py_ssize_t)
    int PyBytes_Size(object p)
    int PyBytes_GET_SIZE_void "PyBytes_GET_SIZE" (void *p)
    int PyBytes_CheckExact(object p)
    int PyFloat_Check(object p)
    double PyFloat_AsDouble(object p)
    int PyLong_Check(object p)
    void Py_INCREF(object o)
    void Py_DECREF(object o)


cdef extern from "string.h":
    int strncmp(char *s1, char *s2, int len)
    void *memchr(void *s, int c, size_t len)
    int memcmp(void *b1, void *b2, size_t len)

from ._str_helpers cimport _my_memrchr, safe_string_from_size


cdef int _is_aligned(void *ptr): # cannot_raise
    """Is this pointer aligned to an integer size offset?

    :return: 1 if this pointer is aligned, 0 otherwise.
    """
    return ((<intptr_t>ptr) & ((sizeof(int))-1)) == 0


cdef int _cmp_by_dirs(char *path1, int size1, char *path2, int size2): # cannot_raise
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
        if cur1[0] == b'/':
            return -1 # Reached the end of path1 segment first
        elif cur2[0] == b'/':
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
        self.text_cstr = PyBytes_AsString(text)
        self.text_size = PyBytes_Size(text)
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
        self.cur_cstr = <char*>memchr(next, b'\0', self.end_cstr - next)
        if self.cur_cstr == NULL:
            extra_len = self.end_cstr - next
            raise DirstateCorrupt(self.state,
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
        if first[0] != b'\0' and size == 0:
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
        :param p_current_dirname: A pointer to the current PyBytes
            representing the directory name.
            We pass this in as a void * so that pyrex doesn't have to
            increment/decrement the PyObject reference counter for each
            _get_entry call.
            We use a pointer so that _get_entry can update it with the new
            value.
        :param new_block: This is to let the caller know that it needs to
            create a new directory block to store the next entry.
        """
        cdef tuple path_name_file_id_key
        cdef tuple tmp
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
        # If so, then we need to create a new dirname PyBytes, so that it can
        # be used in all of the tuples. This saves time and memory, by re-using
        # the same object repeatedly.

        # Do the cheap 'length of string' check first. If the string is a
        # different length, then we *have* to be a different directory.
        if (cur_size != PyBytes_GET_SIZE_void(p_current_dirname[0])
            or strncmp(dirname_cstr,
                       # Extract the char* from our current dirname string.  We
                       # know it is a PyBytes, so we can use
                       # PyBytes_AS_STRING, we use the _void version because
                       # we are tricking Pyrex by using a void* rather than an
                       # <object>
                       PyBytes_AS_STRING_void(p_current_dirname[0]),
                       cur_size+1) != 0):
            dirname = safe_string_from_size(dirname_cstr, cur_size)
            p_current_dirname[0] = <void*>dirname
            new_block[0] = 1
        else:
            new_block[0] = 0

        # Build up the key that will be used.
        # By using <object>(void *) Pyrex will automatically handle the
        # Py_INCREF that we need.
        cur_dirname = <object>p_current_dirname[0]
        tmp = PyTuple_New(3)
        Py_INCREF(cur_dirname); PyTuple_SET_ITEM(tmp, 0, cur_dirname)
        cur_basename = self.get_next_str()
        cur_file_id = self.get_next_str()
        Py_INCREF(cur_basename); PyTuple_SET_ITEM(tmp, 1, cur_basename)
        Py_INCREF(cur_file_id); PyTuple_SET_ITEM(tmp, 2, cur_file_id)
        path_name_file_id_key = tmp

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
            is_executable = (executable_cstr[0] == b'y')
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
        if cur_size != 1 or not trailing.startswith(b'\n'):
            raise DirstateCorrupt(self.state,
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
        dirblocks = [(b'', current_block), (b'', [])]
        self.state._dirblocks = dirblocks
        obj = b''
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
            raise DirstateCorrupt(self.state,
                    'We read the wrong number of entries.'
                    ' We expected to read %s, but read %s'
                    % (expected_entry_count, entry_count))
        self.state._split_root_dirblock_into_contents()


def _read_dirblocks(state):
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


cdef int minikind_from_mode(int mode): # cannot_raise
    # in order of frequency:
    if S_ISREG(mode):
        return c"f"
    if S_ISDIR(mode):
        return c"d"
    if S_ISLNK(mode):
        return c"l"
    return 0


_encode = binascii.b2a_base64


cdef unsigned long _time_to_unsigned(object t):  # cannot_raise
    if PyFloat_Check(t):
        t = t.__int__()
    return PyInt_AsUnsignedLongMask(t)


cdef _pack_stat(stat_value):
    """return a string representing the stat value's key fields.

    :param stat_value: A stat oject with st_size, st_mtime, st_ctime, st_dev,
        st_ino and st_mode fields.
    """
    cdef char result[6*4] # 6 long ints
    cdef int *aliased
    aliased = <int *>result
    aliased[0] = htonl(PyInt_AsUnsignedLongMask(stat_value.st_size))
    # mtime and ctime will often be floats but get converted to PyInt within
    aliased[1] = htonl(_time_to_unsigned(stat_value.st_mtime))
    aliased[2] = htonl(_time_to_unsigned(stat_value.st_ctime))
    aliased[3] = htonl(PyInt_AsUnsignedLongMask(stat_value.st_dev))
    aliased[4] = htonl(PyInt_AsUnsignedLongMask(stat_value.st_ino))
    aliased[5] = htonl(PyInt_AsUnsignedLongMask(stat_value.st_mode))
    packed = PyBytes_FromStringAndSize(result, 6*4)
    return _encode(packed)[:-1]


cpdef update_entry(self, entry, abspath, stat_value):
    """Update the entry based on what is actually on disk.

    This function only calculates the sha if it needs to - if the entry is
    uncachable, or clearly different to the first parent's entry, no sha
    is calculated, and None is returned.

    :param self: The dirstate object this is operating on.
    :param entry: This is the dirblock entry for the file in question.
    :param abspath: The path on disk for this file.
    :param stat_value: The stat value done on the path.
    :return: None, or The sha1 hexdigest of the file (40 bytes) or link
        target of a symlink.
    """
    # TODO - require pyrex 0.9.8, then use a pyd file to define access to the
    # _st mode of the compiled stat objects.
    cdef int minikind, saved_minikind
    cdef void * details
    cdef int worth_saving
    minikind = minikind_from_mode(stat_value.st_mode)
    if 0 == minikind:
        return None
    packed_stat = _pack_stat(stat_value)
    details = PyList_GetItem_void_void(PyTuple_GetItem_void_void(<void *>entry, 1), 0)
    saved_minikind = PyBytes_AsString_obj(<PyObject *>PyTuple_GetItem_void_void(details, 0))[0]
    if minikind == b'd' and saved_minikind == b't':
        minikind = b't'
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
        if minikind == b'd':
            return None

        # size should also be in packed_stat
        if saved_file_size == stat_value.st_size:
            return saved_link_or_sha1

    # If we have gotten this far, that means that we need to actually
    # process this entry.
    link_or_sha1 = None
    worth_saving = 1
    if minikind == b'f':
        executable = self._is_executable(stat_value.st_mode,
                                         saved_executable)
        if self._cutoff_time is None:
            self._sha_cutoff_time()
        if (stat_value.st_mtime < self._cutoff_time
            and stat_value.st_ctime < self._cutoff_time
            and len(entry[1]) > 1
            and entry[1][1][0] != b'a'):
                # Could check for size changes for further optimised
                # avoidance of sha1's. However the most prominent case of
                # over-shaing is during initial add, which this catches.
            link_or_sha1 = self._sha1_file(abspath)
            entry[1][0] = (b'f', link_or_sha1, stat_value.st_size,
                           executable, packed_stat)
        else:
            # This file is not worth caching the sha1. Either it is too new, or
            # it is newly added. Regardless, the only things we are changing
            # are derived from the stat, and so are not worth caching. So we do
            # *not* set the IN_MEMORY_MODIFIED flag. (But we'll save the
            # updated values if there is *other* data worth saving.)
            entry[1][0] = (b'f', b'', stat_value.st_size, executable,
                           DirState.NULLSTAT)
            worth_saving = 0
    elif minikind == b'd':
        entry[1][0] = (b'd', b'', 0, False, packed_stat)
        if saved_minikind != b'd':
            # This changed from something into a directory. Make sure we
            # have a directory block for it. This doesn't happen very
            # often, so this doesn't have to be super fast.
            block_index, entry_index, dir_present, file_present = \
                self._get_block_entry_index(entry[0][0], entry[0][1], 0)
            self._ensure_block(block_index, entry_index,
                               pathjoin(entry[0][0], entry[0][1]))
        else:
            # Any changes are derived trivially from the stat object, not worth
            # re-writing a dirstate for just this
            worth_saving = 0
    elif minikind == b'l':
        if saved_minikind == b'l':
            # If the object hasn't changed kind, it isn't worth saving the
            # dirstate just for a symlink. The default is 'fast symlinks' which
            # save the target in the inode entry, rather than separately. So to
            # stat, we've already read everything off disk.
            worth_saving = 0
        link_or_sha1 = self._read_link(abspath, saved_link_or_sha1)
        if self._cutoff_time is None:
            self._sha_cutoff_time()
        if (stat_value.st_mtime < self._cutoff_time
            and stat_value.st_ctime < self._cutoff_time):
            entry[1][0] = (b'l', link_or_sha1, stat_value.st_size,
                           False, packed_stat)
        else:
            entry[1][0] = (b'l', b'', stat_value.st_size,
                           False, DirState.NULLSTAT)
    if worth_saving:
        # Note, even though _mark_modified will only set
        # IN_MEMORY_HASH_MODIFIED, it still isn't worth 
        self._mark_modified([entry])
    return link_or_sha1


# TODO: Do we want to worry about exceptions here?
cdef char _minikind_from_string(object string) except? -1:
    """Convert a python string to a char."""
    return PyBytes_AsString(string)[0]


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
    if minikind == b'f':
        return _kind_file
    elif minikind == b'd':
        return _kind_directory
    elif minikind == b'a':
        return _kind_absent
    elif minikind == b'r':
        return _kind_relocated
    elif minikind == b'l':
        return _kind_symlink
    elif minikind == b't':
        return _kind_tree_reference
    _minikind[0] = minikind
    raise KeyError(PyBytes_FromStringAndSize(_minikind, 1))


cdef int _versioned_minikind(char minikind): # cannot_raise
    """Return non-zero if minikind is in fltd"""
    return (minikind == b'f' or
            minikind == b'd' or
            minikind == b'l' or
            minikind == b't')


cdef utf8_decode(path: bytes):
    return codecs.utf_8_decode(path, 'surrogateescape')[0]


cdef class ProcessEntryC:

    cdef int doing_consistency_expansion
    cdef object old_dirname_to_file_id # dict
    cdef object new_dirname_to_file_id # dict
    cdef object last_source_parent
    cdef object last_target_parent
    cdef int include_unchanged
    cdef int partial
    cdef object use_filesystem_for_exec
    cdef object utf8_decode
    cdef readonly object searched_specific_files
    cdef readonly object searched_exact_paths
    cdef object search_specific_files
    # The parents up to the root of the paths we are searching.
    # After all normal paths are returned, these specific items are returned.
    cdef object search_specific_file_parents
    cdef object state
    # Current iteration variables:
    cdef object current_root
    cdef object current_root_unicode
    cdef object root_entries
    cdef int root_entries_pos, root_entries_len
    cdef object root_abspath
    cdef int source_index, target_index
    cdef int want_unversioned
    cdef object tree
    cdef object dir_iterator
    cdef int block_index
    cdef object current_block
    cdef int current_block_pos
    cdef object current_block_list
    cdef object current_dir_info
    cdef object current_dir_list
    cdef object _pending_consistent_entries # list
    cdef int path_index
    cdef object root_dir_info
    cdef object bisect_left
    cdef object pathjoin
    cdef object fstat
    # A set of the ids we've output when doing partial output.
    cdef object seen_ids
    cdef object sha_file

    def __init__(self, include_unchanged, use_filesystem_for_exec,
        search_specific_files, state, source_index, target_index,
        want_unversioned, tree):
        self.doing_consistency_expansion = 0
        self.old_dirname_to_file_id = {}
        self.new_dirname_to_file_id = {}
        # Are we doing a partial iter_changes?
        self.partial = set(['']).__ne__(search_specific_files)
        # Using a list so that we can access the values and change them in
        # nested scope. Each one is [path, file_id, entry]
        self.last_source_parent = [None, None]
        self.last_target_parent = [None, None]
        if include_unchanged is None:
            self.include_unchanged = False
        else:
            self.include_unchanged = int(include_unchanged)
        self.use_filesystem_for_exec = use_filesystem_for_exec
        # for all search_indexs in each path at or under each element of
        # search_specific_files, if the detail is relocated: add the id, and
        # add the relocated path as one to search if its not searched already.
        # If the detail is not relocated, add the id.
        self.searched_specific_files = set()
        # When we search exact paths without expanding downwards, we record
        # that here.
        self.searched_exact_paths = set()
        self.search_specific_files = search_specific_files
        # The parents up to the root of the paths we are searching.
        # After all normal paths are returned, these specific items are returned.
        self.search_specific_file_parents = set()
        # The ids we've sent out in the delta.
        self.seen_ids = set()
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
        self.current_block_list = None
        self.current_block_pos = -1
        self.current_dir_info = None
        self.current_dir_list = None
        self._pending_consistent_entries = []
        self.path_index = 0
        self.root_dir_info = None
        self.bisect_left = bisect.bisect_left
        self.pathjoin = osutils.pathjoin
        self.fstat = os.fstat
        self.sha_file = osutils.sha_file
        if target_index != 0:
            # A lot of code in here depends on target_index == 0
            raise errors.BzrError('unsupported target index')

    cdef _process_entry(self, entry, path_info):
        """Compare an entry and real disk to generate delta information.

        :param path_info: top_relpath, basename, kind, lstat, abspath for
            the path of entry. If None, then the path is considered absent in 
            the target (Perhaps we should pass in a concrete entry for this ?)
            Basename is returned as a utf8 string because we expect this
            tuple will be ignored, and don't want to take the time to
            decode.
        :return: (iter_changes_result, changed). If the entry has not been
            handled then changed is None. Otherwise it is False if no content
            or metadata changes have occured, and True if any content or
            metadata change has occurred. If self.include_unchanged is True then
            if changed is not None, iter_changes_result will always be a result
            tuple. Otherwise, iter_changes_result is None unless changed is
            True.
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
                raise AssertionError("Unsupported target index %d" %
                                     self.target_index)
            link_or_sha1 = update_entry(self.state, entry, path_info[4], path_info[3])
            # The entry may have been modified by update_entry
            target_details = details_list[self.target_index]
            target_minikind = _minikind_from_string(target_details[0])
        else:
            link_or_sha1 = None
        # the rest of this function is 0.3 seconds on 50K paths, or
        # 0.000006 seconds per call.
        source_minikind = _minikind_from_string(source_details[0])
        if ((_versioned_minikind(source_minikind) or source_minikind == b'r')
            and _versioned_minikind(target_minikind)):
            # claimed content in both: diff
            #   r    | fdlt   |      | add source to search, add id path move and perform
            #        |        |      | diff check on source-target
            #   r    | fdlt   |  a   | dangling file that was present in the basis.
            #        |        |      | ???
            if source_minikind != b'r':
                old_dirname = entry[0][0]
                old_basename = entry[0][1]
                old_path = path = None
            else:
                # add the source to the search path to find any children it
                # has.  TODO ? : only add if it is a container ?
                if (not self.doing_consistency_expansion and 
                    not is_inside_any(self.searched_specific_files,
                                             source_details[1])):
                    self.search_specific_files.add(source_details[1])
                    # expanding from a user requested path, parent expansion
                    # for delta consistency happens later.
                # generate the old path; this is needed for stating later
                # as well.
                old_path = source_details[1]
                old_dirname, old_basename = os.path.split(old_path)
                path = self.pathjoin(entry[0][0], entry[0][1])
                old_entry = self.state._get_entry(self.source_index,
                                             path_utf8=old_path)
                # update the source details variable to be the real
                # location.
                if old_entry == (None, None):
                    raise DirstateCorrupt(self.state._filename,
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
                        old_path = path = self.pathjoin(old_dirname, old_basename)
                    file_id = entry[0][2]
                    self.new_dirname_to_file_id[path] = file_id
                    if source_minikind != b'd':
                        content_change = 1
                    else:
                        # directories have no fingerprint
                        content_change = 0
                    target_exec = False
                elif target_kind == 'file':
                    if source_minikind != b'f':
                        content_change = 1
                    else:
                        # Check the sha. We can't just rely on the size as
                        # content filtering may mean differ sizes actually
                        # map to the same content
                        if link_or_sha1 is None:
                            # Stat cache miss:
                            statvalue, link_or_sha1 = \
                                self.state._sha1_provider.stat_and_sha1(
                                path_info[4])
                            self.state._observed_sha1(entry, link_or_sha1,
                                statvalue)
                        content_change = (link_or_sha1 != source_details[1])
                    # Target details is updated at update_entry time
                    if self.use_filesystem_for_exec:
                        # We don't need S_ISREG here, because we are sure
                        # we are dealing with a file.
                        target_exec = bool(S_IXUSR & path_info[3].st_mode)
                    else:
                        target_exec = target_details[3]
                elif target_kind == 'symlink':
                    if source_minikind != b'l':
                        content_change = 1
                    else:
                        content_change = (link_or_sha1 != source_details[1])
                    target_exec = False
                elif target_kind == 'tree-reference':
                    if source_minikind != b't':
                        content_change = 1
                    else:
                        content_change = 0
                    target_exec = False
                else:
                    if path is None:
                        path = self.pathjoin(old_dirname, old_basename)
                    raise errors.BadFileKindError(path, path_info[2])
            if source_minikind == b'd':
                if path is None:
                    old_path = path = self.pathjoin(old_dirname, old_basename)
                if file_id is None:
                    file_id = entry[0][2]
                self.old_dirname_to_file_id[old_path] = file_id
            # parent id is the entry for the path in the target tree
            if old_basename and old_dirname == self.last_source_parent[0]:
                # use a cached hit for non-root source entries.
                source_parent_id = self.last_source_parent[1]
            else:
                try:
                    source_parent_id = self.old_dirname_to_file_id[old_dirname]
                except KeyError, _:
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
            if entry[0][1] and new_dirname == self.last_target_parent[0]:
                # use a cached hit for non-root target entries.
                target_parent_id = self.last_target_parent[1]
            else:
                try:
                    target_parent_id = self.new_dirname_to_file_id[new_dirname]
                except KeyError, _:
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
            changed = (content_change
                or source_parent_id != target_parent_id
                or old_basename != entry[0][1]
                or source_exec != target_exec
                )
            if not changed and not self.include_unchanged:
                return None, False
            else:
                if old_path is None:
                    path = self.pathjoin(old_dirname, old_basename)
                    old_path = path
                    old_path_u = utf8_decode(old_path)
                    path_u = old_path_u
                else:
                    old_path_u = utf8_decode(old_path)
                    if old_path == path:
                        path_u = old_path_u
                    else:
                        path_u = utf8_decode(path)
                source_kind = _minikind_to_kind(source_minikind)
                return InventoryTreeChange(entry[0][2],
                       (old_path_u, path_u),
                       content_change,
                       (True, True),
                       (source_parent_id, target_parent_id),
                       (utf8_decode(old_basename), utf8_decode(entry[0][1])),
                       (source_kind, target_kind),
                       (source_exec, target_exec)), changed
        elif source_minikind == b'a' and _versioned_minikind(target_minikind):
            # looks like a new file
            path = self.pathjoin(entry[0][0], entry[0][1])
            # parent id is the entry for the path in the target tree
            # TODO: these are the same for an entire directory: cache em.
            parent_entry = self.state._get_entry(self.target_index,
                                                 path_utf8=entry[0][0])
            if parent_entry is None:
                raise DirstateCorrupt(self.state,
                    "We could not find the parent entry in index %d"
                    " for the entry: %s"
                    % (self.target_index, entry[0]))
            parent_id = parent_entry[0][2]
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
                return InventoryTreeChange(entry[0][2],
                       (None, utf8_decode(path)),
                       True,
                       (False, True),
                       (None, parent_id),
                       (None, utf8_decode(entry[0][1])),
                       (None, path_info[2]),
                       (None, target_exec)), True
            else:
                # Its a missing file, report it as such.
                return InventoryTreeChange(entry[0][2],
                       (None, utf8_decode(path)),
                       False,
                       (False, True),
                       (None, parent_id),
                       (None, utf8_decode(entry[0][1])),
                       (None, None),
                       (None, False)), True
        elif _versioned_minikind(source_minikind) and target_minikind == b'a':
            # unversioned, possibly, or possibly not deleted: we dont care.
            # if its still on disk, *and* theres no other entry at this
            # path [we dont know this in this routine at the moment -
            # perhaps we should change this - then it would be an unknown.
            old_path = self.pathjoin(entry[0][0], entry[0][1])
            # parent id is the entry for the path in the target tree
            parent_id = self.state._get_entry(self.source_index, path_utf8=entry[0][0])[0][2]
            if parent_id == entry[0][2]:
                parent_id = None
            return InventoryTreeChange(
                   entry[0][2],
                   (utf8_decode(old_path), None),
                   True,
                   (True, False),
                   (parent_id, None),
                   (utf8_decode(entry[0][1]), None),
                   (_minikind_to_kind(source_minikind), None),
                   (source_details[3], None)), True
        elif _versioned_minikind(source_minikind) and target_minikind == b'r':
            # a rename; could be a true rename, or a rename inherited from
            # a renamed parent. TODO: handle this efficiently. Its not
            # common case to rename dirs though, so a correct but slow
            # implementation will do.
            if (not self.doing_consistency_expansion and 
                not is_inside_any(self.searched_specific_files,
                    target_details[1])):
                self.search_specific_files.add(target_details[1])
                # We don't expand the specific files parents list here as
                # the path is absent in target and won't create a delta with
                # missing parent.
        elif ((source_minikind == b'r' or source_minikind == b'a') and
              (target_minikind == b'r' or target_minikind == b'a')):
            # neither of the selected trees contain this path,
            # so skip over it. This is not currently directly tested, but
            # is indirectly via test_too_much.TestCommands.test_conflicts.
            pass
        else:
            raise AssertionError("don't know how to compare "
                "source_minikind=%r, target_minikind=%r"
                % (source_minikind, target_minikind))
            ## import pdb;pdb.set_trace()
        return None, None

    def __iter__(self):
        return self

    def iter_changes(self):
        return self

    cdef int _gather_result_for_consistency(self, result) except -1:
        """Check a result we will yield to make sure we are consistent later.
        
        This gathers result's parents into a set to output later.

        :param result: A result tuple.
        """
        if not self.partial or not result.file_id:
            return 0
        self.seen_ids.add(result.file_id)
        new_path = result.path[1]
        if new_path:
            # Not the root and not a delete: queue up the parents of the path.
            self.search_specific_file_parents.update(
                [p.encode('utf-8') for p in osutils.parent_directories(new_path)])
            # Add the root directory which parent_directories does not
            # provide.
            self.search_specific_file_parents.add(b'')
        return 0

    cdef int _update_current_block(self) except -1:
        if (self.block_index < len(self.state._dirblocks) and
            is_inside(self.current_root, self.state._dirblocks[self.block_index][0])):
            self.current_block = self.state._dirblocks[self.block_index]
            self.current_block_list = self.current_block[1]
            self.current_block_pos = 0
        else:
            self.current_block = None
            self.current_block_list = None
        return 0

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
        cdef char * current_dirname_c
        cdef char * current_blockname_c
        cdef int advance_entry, advance_path
        cdef int path_handled
        searched_specific_files = self.searched_specific_files
        # Are we walking a root?
        while self.root_entries_pos < self.root_entries_len:
            entry = self.root_entries[self.root_entries_pos]
            self.root_entries_pos = self.root_entries_pos + 1
            result, changed = self._process_entry(entry, self.root_dir_info)
            if changed is not None:
                if changed:
                    self._gather_result_for_consistency(result)
                if changed or self.include_unchanged:
                    return result
        # Have we finished the prior root, or never started one ?
        if self.current_root is None:
            # TODO: the pending list should be lexically sorted?  the
            # interface doesn't require it.
            try:
                self.current_root = self.search_specific_files.pop()
            except KeyError, _:
                raise StopIteration()
            self.searched_specific_files.add(self.current_root)
            # process the entries for this containing directory: the rest will be
            # found by their parents recursively.
            self.root_entries = self.state._entries_for_path(self.current_root)
            self.root_entries_len = len(self.root_entries)
            self.current_root_unicode = self.current_root.decode('utf8')
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
                self.root_dir_info = (b'', self.current_root,
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
            path_handled = 0
            self.root_entries_pos = 0
            # XXX Clarity: This loop is duplicated a out the self.current_root
            # is None guard above: if we return from it, it completes there
            # (and the following if block cannot trigger because
            # path_handled must be true, so the if block is not # duplicated.
            while self.root_entries_pos < self.root_entries_len:
                entry = self.root_entries[self.root_entries_pos]
                self.root_entries_pos = self.root_entries_pos + 1
                result, changed = self._process_entry(entry, self.root_dir_info)
                if changed is not None:
                    path_handled = -1
                    if changed:
                        self._gather_result_for_consistency(result)
                    if changed or self.include_unchanged:
                        return result
            # handle unversioned specified paths:
            if self.want_unversioned and not path_handled and self.root_dir_info:
                new_executable = bool(
                    stat.S_ISREG(self.root_dir_info[3].st_mode)
                    and stat.S_IEXEC & self.root_dir_info[3].st_mode)
                return InventoryTreeChange(
                       None,
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
        if (self.current_dir_info is None and self.current_block is None and not
            self.doing_consistency_expansion):
            # setup iteration of this root:
            self.current_dir_list = None
            if self.root_dir_info and self.root_dir_info[2] == 'tree-reference':
                self.current_dir_info = None
            else:
                self.dir_iterator = osutils._walkdirs_utf8(self.root_abspath,
                    prefix=self.current_root)
                self.path_index = 0
                try:
                    self.current_dir_info = next(self.dir_iterator)
                    self.current_dir_list = self.current_dir_info[1]
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
                        except AttributeError, _:
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
                    if self.current_dir_info[0][0] == b'':
                        # remove .bzr from iteration
                        bzr_index = self.bisect_left(self.current_dir_list, (b'.bzr',))
                        if self.current_dir_list[bzr_index][0] != b'.bzr':
                            raise AssertionError()
                        del self.current_dir_list[bzr_index]
            initial_key = (self.current_root, b'', b'')
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
            # Uncommon case - a missing directory or an unversioned directory:
            if (self.current_dir_info and self.current_block
                and self.current_dir_info[0][0] != self.current_block[0]):
                # Work around pyrex broken heuristic - current_dirname has
                # the same scope as current_dirname_c
                current_dirname = self.current_dir_info[0][0]
                current_dirname_c = PyBytes_AS_STRING_void(
                    <void *>current_dirname)
                current_blockname = self.current_block[0]
                current_blockname_c = PyBytes_AS_STRING_void(
                    <void *>current_blockname)
                # In the python generator we evaluate this if block once per
                # dir+block; because we reenter in the pyrex version its being
                # evaluated once per path: we could cache the result before
                # doing the while loop and probably save time.
                if _cmp_by_dirs(current_dirname_c,
                    PyBytes_Size(current_dirname),
                    current_blockname_c,
                    PyBytes_Size(current_blockname)) < 0:
                    # filesystem data refers to paths not covered by the
                    # dirblock.  this has two possibilities:
                    # A) it is versioned but empty, so there is no block for it
                    # B) it is not versioned.

                    # if (A) then we need to recurse into it to check for
                    # new unknown files or directories.
                    # if (B) then we should ignore it, because we don't
                    # recurse into unknown directories.
                    # We are doing a loop
                    while self.path_index < len(self.current_dir_list):
                        current_path_info = self.current_dir_list[self.path_index]
                        # dont descend into this unversioned path if it is
                        # a dir
                        if current_path_info[2] in ('directory',
                                                    'tree-reference'):
                            del self.current_dir_list[self.path_index]
                            self.path_index = self.path_index - 1
                        self.path_index = self.path_index + 1
                        if self.want_unversioned:
                            if current_path_info[2] == 'directory':
                                if self.tree._directory_is_tree_reference(
                                    utf8_decode(current_path_info[0])):
                                    current_path_info = current_path_info[:2] + \
                                        ('tree-reference',) + current_path_info[3:]
                            new_executable = bool(
                                stat.S_ISREG(current_path_info[3].st_mode)
                                and stat.S_IEXEC & current_path_info[3].st_mode)
                            return InventoryTreeChange(
                                None,
                                (None, utf8_decode(current_path_info[0])),
                                True,
                                (False, False),
                                (None, None),
                                (None, utf8_decode(current_path_info[1])),
                                (None, current_path_info[2]),
                                (None, new_executable))
                    # This dir info has been handled, go to the next
                    self.path_index = 0
                    self.current_dir_list = None
                    try:
                        self.current_dir_info = next(self.dir_iterator)
                        self.current_dir_list = self.current_dir_info[1]
                    except StopIteration, _:
                        self.current_dir_info = None
                else: #(dircmp > 0)
                    # We have a dirblock entry for this location, but there
                    # is no filesystem path for this. This is most likely
                    # because a directory was removed from the disk.
                    # We don't have to report the missing directory,
                    # because that should have already been handled, but we
                    # need to handle all of the files that are contained
                    # within.
                    while self.current_block_pos < len(self.current_block_list):
                        current_entry = self.current_block_list[self.current_block_pos]
                        self.current_block_pos = self.current_block_pos + 1
                        # entry referring to file not present on disk.
                        # advance the entry only, after processing.
                        result, changed = self._process_entry(current_entry, None)
                        if changed is not None:
                            if changed:
                                self._gather_result_for_consistency(result)
                            if changed or self.include_unchanged:
                                return result
                    self.block_index = self.block_index + 1
                    self._update_current_block()
                continue # next loop-on-block/dir
            result = self._loop_one_block()
            if result is not None:
                return result
        if len(self.search_specific_files):
            # More supplied paths to process
            self.current_root = None
            return self._iter_next()
        # Start expanding more conservatively, adding paths the user may not
        # have intended but required for consistent deltas.
        self.doing_consistency_expansion = 1
        if not self._pending_consistent_entries:
            self._pending_consistent_entries = self._next_consistent_entries()
        while self._pending_consistent_entries:
            result, changed = self._pending_consistent_entries.pop()
            if changed is not None:
                return result
        raise StopIteration()

    cdef object _maybe_tree_ref(self, current_path_info):
        if self.tree._directory_is_tree_reference(
            utf8_decode(current_path_info[0])):
            return current_path_info[:2] + \
                ('tree-reference',) + current_path_info[3:]
        else:
            return current_path_info

    cdef object _loop_one_block(self):
            # current_dir_info and current_block refer to the same directory -
            # this is the common case code.
            # Assign local variables for current path and entry:
            cdef object current_entry
            cdef object current_path_info
            cdef int path_handled
            cdef char minikind
            cdef int cmp_result
            # cdef char * temp_str
            # cdef Py_ssize_t temp_str_length
            # PyBytes_AsStringAndSize(disk_kind, &temp_str, &temp_str_length)
            # if not strncmp(temp_str, "directory", temp_str_length):
            if (self.current_block is not None and
                self.current_block_pos < PyList_GET_SIZE(self.current_block_list)):
                current_entry = PyList_GET_ITEM(self.current_block_list,
                    self.current_block_pos)
                # accomodate pyrex
                Py_INCREF(current_entry)
            else:
                current_entry = None
            if (self.current_dir_info is not None and
                self.path_index < PyList_GET_SIZE(self.current_dir_list)):
                current_path_info = PyList_GET_ITEM(self.current_dir_list,
                    self.path_index)
                # accomodate pyrex
                Py_INCREF(current_path_info)
                disk_kind = PyTuple_GET_ITEM(current_path_info, 2)
                # accomodate pyrex
                Py_INCREF(disk_kind)
                if disk_kind == "directory":
                    current_path_info = self._maybe_tree_ref(current_path_info)
            else:
                current_path_info = None
            while (current_entry is not None or current_path_info is not None):
                advance_entry = -1
                advance_path = -1
                result = None
                changed = None
                path_handled = 0
                if current_entry is None:
                    # unversioned -  the check for path_handled when the path
                    # is advanced will yield this path if needed.
                    pass
                elif current_path_info is None:
                    # no path is fine: the per entry code will handle it.
                    result, changed = self._process_entry(current_entry,
                        current_path_info)
                else:
                    minikind = _minikind_from_string(
                        current_entry[1][self.target_index][0])
                    cmp_result = ((current_path_info[1] > current_entry[0][1]) -
                                  (current_path_info[1] < current_entry[0][1]))
                    if (cmp_result or minikind == b'a' or minikind == b'r'):
                        # The current path on disk doesn't match the dirblock
                        # record. Either the dirblock record is marked as
                        # absent/renamed, or the file on disk is not present at all
                        # in the dirblock. Either way, report about the dirblock
                        # entry, and let other code handle the filesystem one.

                        # Compare the basename for these files to determine
                        # which comes first
                        if cmp_result < 0:
                            # extra file on disk: pass for now, but only
                            # increment the path, not the entry
                            advance_entry = 0
                        else:
                            # entry referring to file not present on disk.
                            # advance the entry only, after processing.
                            result, changed = self._process_entry(current_entry,
                                None)
                            advance_path = 0
                    else:
                        # paths are the same,and the dirstate entry is not
                        # absent or renamed.
                        result, changed = self._process_entry(current_entry,
                            current_path_info)
                        if changed is not None:
                            path_handled = -1
                            if not changed and not self.include_unchanged:
                                changed = None
                # >- loop control starts here:
                # >- entry
                if advance_entry and current_entry is not None:
                    self.current_block_pos = self.current_block_pos + 1
                    if self.current_block_pos < PyList_GET_SIZE(self.current_block_list):
                        current_entry = self.current_block_list[self.current_block_pos]
                    else:
                        current_entry = None
                # >- path
                if advance_path and current_path_info is not None:
                    if not path_handled:
                        # unversioned in all regards
                        if self.want_unversioned:
                            new_executable = bool(
                                stat.S_ISREG(current_path_info[3].st_mode)
                                and stat.S_IEXEC & current_path_info[3].st_mode)
                            relpath_unicode = utf8_decode(current_path_info[0])
                            if changed is not None:
                                raise AssertionError(
                                    "result is not None: %r" % result)
                            result = InventoryTreeChange(
                                None,
                                (None, relpath_unicode),
                                True,
                                (False, False),
                                (None, None),
                                (None, utf8_decode(current_path_info[1])),
                                (None, current_path_info[2]),
                                (None, new_executable))
                            changed = True
                        # dont descend into this unversioned path if it is
                        # a dir
                        if current_path_info[2] in ('directory'):
                            del self.current_dir_list[self.path_index]
                            self.path_index = self.path_index - 1
                    # dont descend the disk iterator into any tree 
                    # paths.
                    if current_path_info[2] == 'tree-reference':
                        del self.current_dir_list[self.path_index]
                        self.path_index = self.path_index - 1
                    self.path_index = self.path_index + 1
                    if self.path_index < len(self.current_dir_list):
                        current_path_info = self.current_dir_list[self.path_index]
                        if current_path_info[2] == 'directory':
                            current_path_info = self._maybe_tree_ref(
                                current_path_info)
                    else:
                        current_path_info = None
                if changed is not None:
                    # Found a result on this pass, yield it
                    if changed:
                        self._gather_result_for_consistency(result)
                    if changed or self.include_unchanged:
                        return result
            if self.current_block is not None:
                self.block_index = self.block_index + 1
                self._update_current_block()
            if self.current_dir_info is not None:
                self.path_index = 0
                self.current_dir_list = None
                try:
                    self.current_dir_info = next(self.dir_iterator)
                    self.current_dir_list = self.current_dir_info[1]
                except StopIteration, _:
                    self.current_dir_info = None

    cdef object _next_consistent_entries(self):
        """Grabs the next specific file parent case to consider.

        :return: A list of the results, each of which is as for _process_entry.
        """
        results = []
        while self.search_specific_file_parents:
            # Process the parent directories for the paths we were iterating.
            # Even in extremely large trees this should be modest, so currently
            # no attempt is made to optimise.
            path_utf8 = self.search_specific_file_parents.pop()
            if path_utf8 in self.searched_exact_paths:
                # We've examined this path.
                continue
            if is_inside_any(self.searched_specific_files, path_utf8):
                # We've examined this path.
                continue
            path_entries = self.state._entries_for_path(path_utf8)
            # We need either one or two entries. If the path in
            # self.target_index has moved (so the entry in source_index is in
            # 'ar') then we need to also look for the entry for this path in
            # self.source_index, to output the appropriate delete-or-rename.
            selected_entries = []
            found_item = False
            for candidate_entry in path_entries:
                # Find entries present in target at this path:
                if candidate_entry[1][self.target_index][0] not in (b'a', b'r'):
                    found_item = True
                    selected_entries.append(candidate_entry)
                # Find entries present in source at this path:
                elif (self.source_index is not None and
                    candidate_entry[1][self.source_index][0] not in (b'a', b'r')):
                    found_item = True
                    if candidate_entry[1][self.target_index][0] == b'a':
                        # Deleted, emit it here.
                        selected_entries.append(candidate_entry)
                    else:
                        # renamed, emit it when we process the directory it
                        # ended up at.
                        self.search_specific_file_parents.add(
                            candidate_entry[1][self.target_index][1])
            if not found_item:
                raise AssertionError(
                    "Missing entry for specific path parent %r, %r" % (
                    path_utf8, path_entries))
            path_info = self._path_info(path_utf8, path_utf8.decode('utf8'))
            for entry in selected_entries:
                if entry[0][2] in self.seen_ids:
                    continue
                result, changed = self._process_entry(entry, path_info)
                if changed is None:
                    raise AssertionError(
                        "Got entry<->path mismatch for specific path "
                        "%r entry %r path_info %r " % (
                        path_utf8, entry, path_info))
                # Only include changes - we're outside the users requested
                # expansion.
                if changed:
                    self._gather_result_for_consistency(result)
                    if (result.kind[0] == 'directory' and
                        result.kind[1] != 'directory'):
                        # This stopped being a directory, the old children have
                        # to be included.
                        if entry[1][self.source_index][0] == b'r':
                            # renamed, take the source path
                            entry_path_utf8 = entry[1][self.source_index][1]
                        else:
                            entry_path_utf8 = path_utf8
                        initial_key = (entry_path_utf8, b'', b'')
                        block_index, _ = self.state._find_block_index_from_key(
                            initial_key)
                        if block_index == 0:
                            # The children of the root are in block index 1.
                            block_index = block_index + 1
                        current_block = None
                        if block_index < len(self.state._dirblocks):
                            current_block = self.state._dirblocks[block_index]
                            if not is_inside(
                                entry_path_utf8, current_block[0]):
                                # No entries for this directory at all.
                                current_block = None
                        if current_block is not None:
                            for entry in current_block[1]:
                                if entry[1][self.source_index][0] in (b'a', b'r'):
                                    # Not in the source tree, so doesn't have to be
                                    # included.
                                    continue
                                # Path of the entry itself.
                                self.search_specific_file_parents.add(
                                    self.pathjoin(*entry[0][:2]))
                if changed or self.include_unchanged:
                    results.append((result, changed))
            self.searched_exact_paths.add(path_utf8)
        return results

    cdef object _path_info(self, utf8_path, unicode_path):
        """Generate path_info for unicode_path.

        :return: None if unicode_path does not exist, or a path_info tuple.
        """
        abspath = self.tree.abspath(unicode_path)
        try:
            stat = os.lstat(abspath)
        except OSError, e:
            if e.errno == errno.ENOENT:
                # the path does not exist.
                return None
            else:
                raise
        utf8_basename = utf8_path.rsplit(b'/', 1)[-1]
        dir_info = (utf8_path, utf8_basename,
            osutils.file_kind_from_stat_mode(stat.st_mode), stat,
            abspath)
        if dir_info[2] == 'directory':
            if self.tree._directory_is_tree_reference(
                unicode_path):
                self.root_dir_info = self.root_dir_info[:2] + \
                    ('tree-reference',) + self.root_dir_info[3:]
        return dir_info
