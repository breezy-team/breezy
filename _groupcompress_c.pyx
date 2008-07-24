# Copyright (C) 2008 Canonical Limited.
# 
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as published
# by the Free Software Foundation.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301 USA
# 

"""Compiled extensions for doing compression."""

cdef extern from *:
    ctypedef unsigned long size_t
    void * malloc(size_t)
    void free(void *)

cdef extern from "Python.h":
    struct _PyObject:
        pass
    ctypedef _PyObject PyObject
    PyObject *PySequence_Fast(object, char *) except NULL
    Py_ssize_t PySequence_Fast_GET_SIZE(PyObject *)
    PyObject *PySequence_Fast_GET_ITEM(PyObject *, Py_ssize_t)
    long PyObject_Hash(PyObject *) except -1
    void Py_DECREF(PyObject *)
    void Py_INCREF(PyObject *)


cdef struct _raw_line:
    long hash   # Cached form of the hash for this entry
    int next    # Next line which is equivalent to this one
    PyObject *data   # Raw pointer to the original line


cdef struct _hash_bucket:
    int line_index # First line in the left side for this bucket
    int count      # Number of equivalent lines, DO we even need this?


cdef int SENTINEL
SENTINEL = -1


cdef void *safe_malloc(size_t count) except NULL:
    cdef void *result
    result = malloc(count)
    if result == NULL:
        raise MemoryError('Failed to allocate %d bytes of memory' % (count,))
    return result


cdef class EquivalenceTable:
    """This tracks equivalencies between lists of hashable objects.

    :ivar lines: The 'static' lines that will be preserved between runs.
    """

    cdef readonly object lines
    cdef readonly object _right_lines
    cdef object _matching_lines
    cdef int _hashtable_size
    cdef int _hashtable_bitmask
    cdef _hash_bucket *_hashtable
    cdef _raw_line *_raw_left_lines
    cdef Py_ssize_t _len_left_lines
    cdef _raw_line *_raw_right_lines
    cdef Py_ssize_t _len_right_lines

    def __init__(self, lines):
        self.lines = lines
        self._len_left_lines = len(lines)
        self._right_lines = None
        self._len_right_lines = 0
        self._hashtable_size = 0
        self._hashtable = NULL
        self._raw_left_lines = NULL
        self._raw_right_lines = NULL
        self._lines_to_raw_lines(lines, &self._raw_left_lines)
        self._generate_matching_lines()

    def __dealloc__(self):
        if self._hashtable != NULL:
            free(self._hashtable)
            self._hashtable = NULL
        if self._raw_left_lines != NULL:
            free(self._raw_left_lines)
            self._raw_left_lines = NULL
        if self._raw_right_lines != NULL:
            free(self._raw_right_lines)
            self._raw_right_lines = NULL

    cdef int _lines_to_raw_lines(self, object lines,
                                 _raw_line **raw_lines) except -1:
        """Load a sequence of objects into the _raw_line format"""
        cdef Py_ssize_t count, i
        cdef PyObject *seq
        cdef PyObject *item
        cdef _raw_line *raw

        # Do we want to use PySequence_Fast, or just assume that it is a list
        # Also, do we need to decref the return value?
        # http://www.python.org/doc/current/api/sequence.html
        seq = PySequence_Fast(lines, "expected a sequence")
        try:
            count = PySequence_Fast_GET_SIZE(seq)
            if count == 0:
                return 0
            raw = <_raw_line*>safe_malloc(count * sizeof(_raw_line))
            # This should set _raw_left/right_lines, which means that we should
            # automatically clean it up during __dealloc__
            raw_lines[0] = raw

            for i from 0 <= i < count:
                item = PySequence_Fast_GET_ITEM(seq, i)
                # NB: We don't Py_INCREF the data pointer, because we know we
                #     maintain a pointer to the item in self.lines or
                #     self._right_lines
                # TODO: Do we even need to track a data pointer here? It would
                #       be less memory, and we *could* just look it up in the
                #       appropriate line list.
                raw[i].data = item
                raw[i].hash = PyObject_Hash(item)
                raw[i].next = SENTINEL
        finally:
            # TODO: Unfortunately, try/finally always generates a compiler
            #       warning about a possibly unused variable :(
            Py_DECREF(seq)
        return count

    cdef Py_ssize_t _compute_minimum_hash_size(self, Py_ssize_t needed_lines):
        """Determine the smallest hash size that can fit the data.
        
        :param needed_lines: The number of entries we might be inserting into
            the hash (assuming there are no duplicate lines.)
        :return: The number of hash table entries to use. This will always be a
            power of two.
        """
        # TODO: We probably actually want to have 2 values, one indicating an
        #       acceptable "minimum" size (which is at least as many as input
        #       lines as they could all be unique, and we would like some space
        #       to avoid collisions),
        #       And a "recommended" size, which gives us some extra space
        #       because we expect to have to grow from time to time, and don't
        #       want to have to rebuild the entire hash table each time.
        #       (so initialize with "recommended" but grow if we reach
        #       "minimum")
        cdef Py_ssize_t hash_size

        hash_size = 1
        while hash_size < needed_lines:
            hash_size = hash_size << 1
        return hash_size

    def _py_compute_minimum_hash_size(self, needed_lines):
        """Expose _compute_minimum_hash_size to python for testing."""
        return self._compute_minimum_hash_size(needed_lines)

    cdef int _build_hash_table(self) except -1:
        cdef Py_ssize_t hash_size
        cdef Py_ssize_t hash_bitmask
        cdef Py_ssize_t i

        # Hash size is a power of 2
        hash_size = self._compute_hash_size(self._len_left_lines)

        if self._hashtable != NULL:
            free(self._hashtable)
            self._hashtable = NULL
        self._hashtable = <_hash_bucket*>safe_malloc(sizeof(_hash_bucket) *
                                                     hash_size)
        for i from 0 <= i < hash_size:
            self._hashtable[i].line_index = SENTINEL
            self._hashtable[i].count = 0

        # Turn the hash size into a bitmask
        self._hashtable_bitmask = hash_size - 1

        # Iterate backwards, because it makes it easier to insert items into
        # the hash (you just change the head pointer, and everything else keeps
        # pointing to the same location).
        for i from self._len_left_lines > i >= 0:
            self._find_equivalence_offset(&self._raw_left_lines[i])

    cdef int _find_equivalence_offset(self, _raw_line *line):
        """Find the node in the hash which defines this line.

        Each bucket in the hash table points at exactly 1 equivalent line. If 2
        objects would collide, we just increment to the next bucket.
        """
        
    def _inspect_hash_table(self):
        """Used only for testing.

        This iterates the hash table, and returns 'interesting' entries.
        :return: (total_size, [(offset, line_index, count)] for entries that
            are not empty.
        """
        cdef int i

        interesting = []
        for i from 0 <= i < self._hashtable_size:
            if self._hashtable[i].line_index != SENTINEL:
                interesting.append((i, self._hashtable[i].line_index,
                                    self._hashtable[i].count))
        return (self._hashtable_size, interesting)

    def _generate_matching_lines(self):
        matches = {}
        for idx, line in enumerate(self.lines):
            matches.setdefault(line, []).append(idx)
        self._matching_lines = matches

    def _update_matching_lines(self, new_lines, index):
        matches = self._matching_lines
        start_idx = len(self.lines)
        for idx, do_index in enumerate(index):
            if not do_index:
                continue
            matches.setdefault(new_lines[idx], []).append(start_idx + idx)

    def get_matches(self, line):
        """Return the lines which match the line in right."""
        try:
            return self._matching_lines[line]
        except KeyError:
            return None

    def _get_matching_lines(self):
        """Return a dictionary showing matching lines."""
        matching = {}
        for line in self.lines:
            matching[line] = self.get_matches(line)
        return matching

    def get_idx_matches(self, right_idx):
        """Return the left lines matching the right line at the given offset."""
        line = self._right_lines[right_idx]
        try:
            return self._matching_lines[line]
        except KeyError:
            return None

    def extend_lines(self, lines, index):
        """Add more lines to the left-lines list.

        :param lines: A list of lines to add
        :param index: A True/False for each node to define if it should be
            indexed.
        """
        self._update_matching_lines(lines, index)
        self.lines.extend(lines)

    def set_right_lines(self, lines):
        """Set the lines we will be matching against."""
        self._right_lines = lines
