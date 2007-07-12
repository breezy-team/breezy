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

"""Helper functions for DirState.

This is the python implementation for DirState functions.
"""

from bzrlib.dirstate import DirState


cdef extern from *:
    ctypedef int size_t


cdef extern from "stdlib.h":
    unsigned long int strtoul(char *nptr, char **endptr, int base)


cdef extern from "Python.h":
    int PyList_Append(object lst, object item) except -1
    void *PyList_GetItem_object_void "PyList_GET_ITEM" (object lst, int index)
    int PyList_CheckExact(object)

    void *PyTuple_GetItem_void_void "PyTuple_GET_ITEM" (void* tpl, int index)

    char *PyString_AsString(object p)
    char *PyString_AS_STRING_void "PyString_AS_STRING" (void *p)
    object PyString_FromString(char *)
    object PyString_FromStringAndSize(char *, int)
    int PyString_Size(object p)
    int PyString_GET_SIZE_void "PyString_GET_SIZE" (void *p)
    int PyString_CheckExact(object p)


cdef extern from "string.h":
    int strncmp(char *s1, char *s2, int len)
    void *memchr(void *s, int c, size_t len)
    int memcmp(void *b1, void *b2, size_t len)
    # ??? memrchr is a GNU extension :(
    # void *memrchr(void *s, int c, size_t len)


cdef void* _my_memrchr(void *s, int c, size_t n):
    # memrchr seems to be a GNU extension, so we have to implement it ourselves
    # We semi-cheat, and just call memchr repeatedly until we run out of path.
    # And then return the last match.
    cdef void *pos
    cdef void *end
    cdef void *last_pos

    last_pos = NULL
    end = <void*>((<char*>s) + n)
    pos = memchr(s, c, n)
    while pos != NULL and pos < end:
        last_pos = pos
        pos = memchr(pos+1, c, end-pos)
    return last_pos


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
    return found - _s


cdef int _cmp_by_dirs(char *path1, int size1, char *path2, int size2):
    cdef char *cur1
    cdef char *cur2
    cdef char *end1
    cdef char *end2
    cdef int *cur_int1
    cdef int *cur_int2
    cdef int *end_int1
    cdef int *end_int2

    if path1 == path2:
        return 0

    cur_int1 = <int*>path1
    cur_int2 = <int*>path2
    end_int1 = <int*>(path1 + size1 - (size1%4))
    end_int2 = <int*>(path2 + size2 - (size2%4))
    end1 = path1+size1
    end2 = path2+size2

    # Use 32-bit comparisons for the matching portion of the string.
    # Almost all CPU's are faster at loading and comparing 32-bit integers,
    # than they are at 8-bit integers.
    # TODO: jam 2007-05-07 Do we need to change this so we always start at an
    #       integer offset in memory? I seem to remember that being done in
    #       some C libraries for strcmp()
    while cur_int1 < end_int1 and cur_int2 < end_int2:
        if cur_int1[0] != cur_int2[0]:
            break
        cur_int1 = cur_int1 + 1
        cur_int2 = cur_int2 + 1

    cur1 = <char*>cur_int1
    cur2 = <char*>cur_int2

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
    :return: positive number if ``path1`` comes first,
        0 if paths are equal,
        and negative number if ``path2`` sorts first
    """
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
    :return: positive number if ``path1`` comes first,
        0 if paths are equal
        and a negative number if ``path2`` sorts first
    """
    return _cmp_path_by_dirblock(PyString_AsString(path1),
                                 PyString_Size(path1),
                                 PyString_AsString(path2),
                                 PyString_Size(path2))


cdef int _cmp_path_by_dirblock(char *path1, int path1_len,
                               char *path2, int path2_len):
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


cdef object _pystr(char *s, int length):
    if s == NULL:
        if length == 0:
            return ''
        else:
            return None
    else:
        return PyString_FromStringAndSize(s, length)


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
    cdef char *path_str
    cdef int path_size
    cdef char *cur_str
    cdef int cur_size
    cdef void *cur

    if not PyList_CheckExact(paths):
        raise TypeError('you must pass a python list for paths')
    if not PyString_CheckExact(path):
        raise TypeError('you must pass a string for path')

    _hi = len(paths)
    _lo = 0

    path_str = PyString_AsString(path)
    path_size = PyString_Size(path)

    while _lo < _hi:
        _mid = (_lo + _hi) / 2
        cur = PyList_GetItem_object_void(paths, _mid)
        cur_str = PyString_AS_STRING_void(cur)
        cur_size = PyString_GET_SIZE_void(cur)
        if _cmp_path_by_dirblock(cur_str, cur_size, path_str, path_size) < 0:
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
    cdef char *path_str
    cdef int path_size
    cdef char *cur_str
    cdef int cur_size
    cdef void *cur

    if not PyList_CheckExact(paths):
        raise TypeError('you must pass a python list for paths')
    if not PyString_CheckExact(path):
        raise TypeError('you must pass a string for path')

    _hi = len(paths)
    _lo = 0

    path_str = PyString_AsString(path)
    path_size = PyString_Size(path)

    while _lo < _hi:
        _mid = (_lo + _hi) / 2
        cur = PyList_GetItem_object_void(paths, _mid)
        cur_str = PyString_AS_STRING_void(cur)
        cur_size = PyString_GET_SIZE_void(cur)
        if _cmp_path_by_dirblock(path_str, path_size, cur_str, cur_size) < 0:
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
    cdef char *dirname_str
    cdef int dirname_size
    cdef char *cur_str
    cdef int cur_size
    cdef void *cur

    if hi is None:
        _hi = len(dirblocks)
    else:
        _hi = hi

    if not PyList_CheckExact(dirblocks):
        raise TypeError('you must pass a python list for dirblocks')
    _lo = lo
    if not PyString_CheckExact(dirname):
        raise TypeError('you must pass a string for dirname')
    dirname_str = PyString_AsString(dirname)
    dirname_size = PyString_Size(dirname)

    while _lo < _hi:
        _mid = (_lo + _hi) / 2
        # Grab the dirname for the current dirblock
        # cur = dirblocks[_mid][0]
        cur = PyTuple_GetItem_void_void(
                PyList_GetItem_object_void(dirblocks, _mid), 0)
        cur_str = PyString_AS_STRING_void(cur)
        cur_size = PyString_GET_SIZE_void(cur)
        if _cmp_by_dirs(cur_str, cur_size, dirname_str, dirname_size) < 0:
            _lo = _mid + 1
        else:
            _hi = _mid
    return _lo


cdef class Reader:
    """Maintain the current location, and return fields as you parse them."""

    cdef object text # The overall string object
    cdef char *text_str # Pointer to the beginning of text
    cdef int text_size # Length of text

    cdef char *end_str # End of text
    cdef char *cur # Pointer to the current record
    cdef char *next # Pointer to the end of this record

    def __new__(self, text):
        self.text = text
        self.text_str = PyString_AsString(text)
        self.text_size = PyString_Size(text)
        self.end_str = self.text_str + self.text_size
        self.cur = self.text_str

    cdef char *get_next(self, int *size):
        """Return a pointer to the start of the next field."""
        cdef char *next
        next = self.cur
        self.cur = <char*>memchr(next, c'\0', self.end_str-next)
        size[0] = self.cur - next
        self.cur = self.cur + 1
        return next

    cdef object get_next_str(self):
        """Get the next field as a Python string."""
        cdef int size
        cdef char *next
        next = self.get_next(&size)
        return PyString_FromStringAndSize(next, size)

    def init(self):
        """Get the pointer ready"""
        cdef char *first
        cdef int size
        # The first field should be an empty string left over from the Header
        first = self.get_next(&size)
        if first[0] != c'\0' and size == 0:
            raise AssertionError('First character should be null not: %s'
                                 % (first,))

    def get_all_fields(self):
        """Get a list of all fields"""
        self.init()
        fields = []
        while self.cur < self.end_str:
            PyList_Append(fields, self.get_next_str())
        return fields

    cdef object _get_entry(self, int num_trees, void **p_current_dirname,
                           int *new_block):
        cdef object path_name_file_id_key
        cdef char *entry_size_str
        cdef unsigned long int entry_size
        cdef char* executable_str
        cdef int is_executable
        cdef char* dirname_str
        cdef char* trailing
        cdef int cur_size
        cdef int i
        cdef object minikind
        cdef object fingerprint
        cdef object info

        dirname_str = self.get_next(&cur_size)
        if strncmp(dirname_str,
                  PyString_AS_STRING_void(p_current_dirname[0]),
                  cur_size+1) != 0:
            dirname = PyString_FromStringAndSize(dirname_str, cur_size)
            p_current_dirname[0] = <void*>dirname
            new_block[0] = 1
        else:
            new_block[0] = 0
        path_name_file_id_key = (<object>p_current_dirname[0],
                                 self.get_next_str(),
                                 self.get_next_str(),
                                )

        trees = []
        for i from 0 <= i < num_trees:
            minikind = self.get_next_str()
            fingerprint = self.get_next_str()
            entry_size_str = self.get_next(&cur_size)
            entry_size = strtoul(entry_size_str, NULL, 10)
            executable_str = self.get_next(&cur_size)
            is_executable = (executable_str[0] == c'y')
            info = self.get_next_str()
            PyList_Append(trees, (
                minikind,     # minikind
                fingerprint,  # fingerprint
                entry_size,   # size
                is_executable,# executable
                info,         # packed_stat or revision_id
            ))

        ret = (path_name_file_id_key, trees)
        # Ignore the trailing newline
        trailing = self.get_next(&cur_size)
        if cur_size != 1 or trailing[0] != c'\n':
            raise AssertionError(
                'Bad parse, we expected to end on \\n, not: %d %s: %s'
                % (cur_size, PyString_FromString(trailing), ret))
        return ret

    def _parse_dirblocks(self, state):
        """Parse all dirblocks in the state file."""
        cdef int num_trees
        cdef object current_block
        cdef object entry
        cdef void * current_dirname
        cdef int new_block
        cdef int expected_entry_count
        cdef int entry_count

        num_trees = state._num_present_parents() + 1
        expected_entry_count = state._num_entries

        # Ignore the first record
        self.init()

        current_block = []
        state._dirblocks = [('', current_block), ('', [])]
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
        while self.cur < self.end_str:
            entry = self._get_entry(num_trees, &current_dirname, &new_block)
            if new_block:
                # new block - different dirname
                current_block = []
                PyList_Append(state._dirblocks,
                              (<object>current_dirname, current_block))
            PyList_Append(current_block, entry)
            entry_count = entry_count + 1
        if entry_count != expected_entry_count:
            raise AssertionError('We read the wrong number of entries.'
                    ' We expected to read %s, but read %s'
                    % (expected_entry_count, entry_count))
        state._split_root_dirblock_into_contents()


def _read_dirblocks_c(state):
    """Read in the dirblocks for the given DirState object.

    This is tightly bound to the DirState internal representation. It should be
    thought of as a member function, which is only separated out so that we can
    re-write it in pyrex.

    :param state: A DirState object.
    :return: None
    """
    state._state_file.seek(state._end_of_header)
    text = state._state_file.read()
    # TODO: check the crc checksums. crc_measured = zlib.crc32(text)

    reader = Reader(text)

    reader._parse_dirblocks(state)
    state._dirblock_state = DirState.IN_MEMORY_UNMODIFIED
