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
    void * realloc(void *, size_t)
    void free(void *)

cdef extern from "Python.h":
    struct _PyObject:
        pass
    ctypedef _PyObject PyObject
    PyObject *PySequence_Fast(object, char *) except NULL
    Py_ssize_t PySequence_Fast_GET_SIZE(PyObject *)
    PyObject *PySequence_Fast_GET_ITEM(PyObject *, Py_ssize_t)
    PyObject *PyList_GET_ITEM(object, Py_ssize_t)
    int PyList_Append(object, object) except -1
    long PyObject_Hash(PyObject *) except -1
    # We use PyObject_Cmp rather than PyObject_Compare because pyrex will check
    # if there is an exception *for* us.
    int PyObject_Cmp(PyObject *, PyObject *, int *result) except -1
    int PyObject_Not(PyObject *) except -1
    void Py_DECREF(PyObject *)
    void Py_INCREF(PyObject *)

cdef enum _raw_line_flags:
    INDEXED  = 0x01

cdef struct _raw_line:
    long hash              # Cached form of the hash for this entry
    Py_ssize_t hash_offset # The location in the hash table for this object
    Py_ssize_t next_line_index # Next line which is equivalent to this one
    int flags              # status flags
    PyObject *data         # Raw pointer to the original line


cdef struct _hash_bucket:
    Py_ssize_t line_index # First line in the left side for this bucket
    Py_ssize_t count      # Number of equivalent lines, DO we even need this?


cdef Py_ssize_t SENTINEL
SENTINEL = -1


cdef void *safe_malloc(size_t count) except NULL:
    cdef void *result
    result = malloc(count)
    if result == NULL:
        raise MemoryError('Failed to allocate %d bytes of memory' % (count,))
    return result


cdef void *safe_realloc(void * old, size_t count) except NULL:
    cdef void *result
    result = realloc(old, count)
    if result == NULL:
        raise MemoryError('Failed to reallocate to %d bytes of memory'
                          % (count,))
    return result


cdef int safe_free(void **val) except -1:
    assert val != NULL
    if val[0] != NULL:
        free(val[0])
        val[0] = NULL


cdef class EquivalenceTable:
    """This tracks equivalencies between lists of hashable objects.

    :ivar lines: The 'static' lines that will be preserved between runs.
    """

    cdef readonly object lines
    cdef readonly object _right_lines
    cdef Py_ssize_t _hashtable_size
    cdef Py_ssize_t _hashtable_bitmask
    cdef _hash_bucket *_hashtable
    cdef _raw_line *_raw_lines
    cdef Py_ssize_t _len_lines

    def __init__(self, lines):
        self.lines = list(lines)
        self._right_lines = None
        self._hashtable_size = 0
        self._hashtable = NULL
        self._raw_lines = NULL
        self._len_lines = 0
        self._lines_to_raw_lines(lines)
        self._build_hash_table()

    def __dealloc__(self):
        safe_free(<void**>&self._hashtable)
        safe_free(<void**>&self._raw_lines)

    cdef int _line_to_raw_line(self, PyObject *line, _raw_line *raw_line) except -1:
        """Convert a single PyObject into a raw line."""
        raw_line.hash = PyObject_Hash(line)
        raw_line.next_line_index = SENTINEL
        raw_line.hash_offset = SENTINEL
        raw_line.flags = INDEXED
        raw_line.data = line
        
    cdef int _lines_to_raw_lines(self, object lines) except -1:
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
            safe_free(<void**>&self._raw_lines)
            self._raw_lines = raw
            self._len_lines = count

            for i from 0 <= i < count:
                item = PySequence_Fast_GET_ITEM(seq, i)
                # NB: We don't Py_INCREF the data pointer, because we know we
                #     maintain a pointer to the item in self.lines or
                #     self._right_lines
                # TODO: Do we even need to track a data pointer here? It would
                #       be less memory, and we *could* just look it up in the
                #       appropriate line list.
                self._line_to_raw_line(item, &raw[i])
        finally:
            # TODO: Unfortunately, try/finally always generates a compiler
            #       warning about a possibly unused variable :(
            Py_DECREF(seq)
        return count

    cdef Py_ssize_t _compute_minimum_hash_size(self, Py_ssize_t needed):
        """Determine the smallest hash size that can reasonably fit the data.
        
        :param needed: The number of entries we might be inserting into
            the hash (assuming there are no duplicate lines.)
        :return: The number of hash table entries to use. This will always be a
            power of two.
        """
        cdef Py_ssize_t hash_size
        cdef Py_ssize_t min_size

        # TODO: Another alternative would be to actually count how full the
        #       hash-table is, and decide if we need to grow it based on
        #       density. That can take into account duplicated lines. Though if
        #       we compress well, there should be a minimal amount of
        #       duplicated lines in the output.

        # At the bare minimum, we could fit all entries into a 'needed'
        # size hash table. However, any collision would then have a long way to
        # traverse before it could find a 'free' slot.
        # So we set the minimum size to give us 33% empty slots.
        min_size = <Py_ssize_t>(needed * 1.5)
        hash_size = 1
        while hash_size < min_size:
            hash_size = hash_size << 1
        return hash_size

    def _py_compute_minimum_hash_size(self, needed):
        """Expose _compute_minimum_hash_size to python for testing."""
        return self._compute_minimum_hash_size(needed)

    cdef Py_ssize_t _compute_recommended_hash_size(self, Py_ssize_t needed):
        """Determine a reasonable hash size, assuming some room for growth.
        
        :param needed: The number of entries we might be inserting into
            the hash (assuming there are no duplicate lines.)
        :return: The number of hash table entries to use. This will always be a
            power of two.
        """
        cdef Py_ssize_t hash_size
        cdef Py_ssize_t min_size

        # We start off with a 8k hash (after doubling), because there isn't a
        # lot of reason to go smaller than that (this class isn't one you'll be
        # instantiating thousands of, and you are always likely to grow here.)
        hash_size = 4096
        while hash_size < needed:
            hash_size = hash_size << 1
        # And we always give at least 2x blank space
        hash_size = hash_size << 1
        return hash_size

    def _py_compute_recommended_hash_size(self, needed):
        """Expose _compute_recommended_hash_size to python for testing."""
        return self._compute_recommended_hash_size(needed)

    cdef int _build_hash_table(self) except -1:
        """Build the hash table 'from scratch'."""
        cdef Py_ssize_t hash_size
        cdef Py_ssize_t hash_bitmask
        cdef Py_ssize_t i
        cdef _raw_line *cur_line 
        cdef Py_ssize_t hash_offset
        cdef _hash_bucket *cur_bucket
        cdef _hash_bucket *new_hashtable

        # Hash size is a power of 2
        hash_size = self._compute_recommended_hash_size(self._len_lines)

        new_hashtable = <_hash_bucket*>safe_malloc(sizeof(_hash_bucket) *
                                                   hash_size)
        safe_free(<void**>&self._hashtable)
        self._hashtable = new_hashtable

        self._hashtable_size = hash_size
        for i from 0 <= i < hash_size:
            self._hashtable[i].line_index = SENTINEL
            self._hashtable[i].count = 0

        # Turn the hash size into a bitmask
        self._hashtable_bitmask = hash_size - 1

        # Iterate backwards, because it makes it easier to insert items into
        # the hash (you just change the head pointer, and everything else keeps
        # pointing to the same location).
        for i from self._len_lines > i >= 0:
            cur_line = self._raw_lines + i
            if not (cur_line.flags & INDEXED == INDEXED):
                continue
            hash_offset = self._find_hash_position(cur_line)

            # Point this line to the location in the hash table
            cur_line.hash_offset = hash_offset
            # And make this line the head of the hash table
            cur_bucket = self._hashtable + hash_offset
            cur_line.next_line_index = cur_bucket.line_index
            cur_bucket.line_index = i
            cur_bucket.count += 1

    cdef int _extend_raw_lines(self, object index) except -1:
        """Add the last N lines from self.lines into the raw_lines array."""
        cdef Py_ssize_t new_count
        cdef Py_ssize_t new_total_len
        cdef Py_ssize_t old_len
        cdef PyObject *item
        cdef PyObject *should_index
        cdef Py_ssize_t i
        cdef Py_ssize_t line_index
        cdef _raw_line *cur_line
        cdef PyObject *seq_index

        seq_index = PySequence_Fast(index, "expected a sequence for index")
        try:
            old_len = self._len_lines
            new_count = PySequence_Fast_GET_SIZE(seq_index) 
            new_total_len = new_count + self._len_lines
            self._raw_lines = <_raw_line*>safe_realloc(<void*>self._raw_lines,
                                    new_total_len * sizeof(_raw_line))
            self._len_lines = new_total_len
            # Now that we have enough space, start adding the new lines
            # into the array. These are done in forward order.
            for i from 0 <= i < new_count:
                line_index = i + old_len
                cur_line = self._raw_lines + line_index
                item = PyList_GET_ITEM(self.lines, line_index)
                self._line_to_raw_line(item, cur_line)
                should_index = PySequence_Fast_GET_ITEM(seq_index, i)
                if PyObject_Not(should_index):
                    cur_line.flags &= ~(<int>INDEXED)
        finally:
            Py_DECREF(seq_index)

    cdef int _extend_hash_table(self, Py_ssize_t count) except -1:
        """Add the last N entries in self.lines to the hash table.

        :param index: A sequence that declares whether each node should be
            INDEXED or not.
        """
        cdef Py_ssize_t line_index
        cdef Py_ssize_t start
        cdef _raw_line *cur_line
        cdef _raw_line *next_line
        cdef Py_ssize_t hash_offset
        cdef _hash_bucket *cur_bucket

        start = self._len_lines - count

        for line_index from start <= line_index < self._len_lines:
            cur_line = self._raw_lines + line_index
            if cur_line.flags & INDEXED != INDEXED:
                continue
            hash_offset = self._find_hash_position(cur_line)

            # Point this line to the location in the hash table
            cur_line.hash_offset = hash_offset

            # Make this line the tail of the hash table
            cur_bucket = self._hashtable + hash_offset
            cur_bucket.count += 1
            if cur_bucket.line_index == SENTINEL:
                cur_bucket.line_index = line_index
                continue
            # We need to track through the pointers and insert this at
            # the end
            next_line = self._raw_lines + cur_bucket.line_index
            while next_line.next_line_index != SENTINEL:
                next_line = self._raw_lines + next_line.next_line_index
            next_line.next_line_index = line_index

    cdef Py_ssize_t _find_hash_position(self, _raw_line *line) except -1:
        """Find the node in the hash which defines this line.

        Each bucket in the hash table points at exactly 1 equivalent line. If 2
        objects would collide, we just increment to the next bucket until we
        get to an empty bucket that is either empty or exactly matches this
        object.

        :return: The offset in the hash table for this entry
        """
        cdef Py_ssize_t location
        cdef _raw_line *ref_line
        cdef Py_ssize_t ref_index
        cdef int compare_result

        location = line.hash & self._hashtable_bitmask
        ref_index = self._hashtable[location].line_index
        while ref_index != SENTINEL:
            ref_line = self._raw_lines + ref_index
            if (ref_line.hash == line.hash):
                PyObject_Cmp(ref_line.data, line.data, &compare_result)
                if compare_result == 0:
                    break
            location = (location + 1) & self._hashtable_bitmask
            ref_index = self._hashtable[location].line_index
        return location

    def _py_find_hash_position(self, line):
        """Used only for testing.

        Return the location where this fits in the hash table
        """
        cdef _raw_line raw_line

        self._line_to_raw_line(<PyObject *>line, &raw_line)
        return self._find_hash_position(&raw_line)
        
    def _inspect_left_lines(self):
        """Used only for testing.

        :return: None if _raw_lines is NULL,
            else [(object, hash_val, hash_loc, next_val)] for each node in raw
                  lines.
        """
        cdef Py_ssize_t i

        if self._raw_lines == NULL:
            return None

        result = []
        for i from 0 <= i < self._len_lines:
            PyList_Append(result,
                          (<object>self._raw_lines[i].data,
                           self._raw_lines[i].hash,
                           self._raw_lines[i].hash_offset,
                           self._raw_lines[i].next_line_index,
                           ))
        return result

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
                PyList_Append(interesting,
                              (i, self._hashtable[i].line_index,
                               self._hashtable[i].count))
        return (self._hashtable_size, interesting)

    def get_matches(self, line):
        """Return the lines which match the line in right."""
        cdef Py_ssize_t count
        cdef Py_ssize_t i
        cdef Py_ssize_t *matches

        matches = NULL

        try:
            count = self.get_raw_matches(<PyObject *>line, &matches)
            if count == 0:
                return None
            result = []
            for i from 0 <= i < count:
                PyList_Append(result, matches[i])
        finally:
            safe_free(<void**>&matches)
        return result

    cdef Py_ssize_t get_raw_matches(self, PyObject *line,
                                    Py_ssize_t **matches) except -1:
        """Get all the possible entries that match the given location.

        :param line: A Python line which we want to match
        :param pos: The index position in _right_lines
        :param matches: A variable to hold an array containing all the matches.
            This will be allocated using malloc, and the caller is responsible
            to free it with free(). If there are no matches, no memory will be
            allocated.
        :retrun: The number of matched positions
        """
        cdef Py_ssize_t hash_offset
        cdef _raw_line raw_line
        cdef _hash_bucket cur_bucket
        cdef Py_ssize_t cur_line_idx
        cdef Py_ssize_t count
        cdef Py_ssize_t *local_matches

        self._line_to_raw_line(line, &raw_line)
        hash_offset = self._find_hash_position(&raw_line)
        cur_bucket = self._hashtable[hash_offset]
        cur_line_idx = cur_bucket.line_index
        if cur_line_idx == SENTINEL:
            return 0
        local_matches = <Py_ssize_t*>safe_malloc(sizeof(Py_ssize_t) *
                                                 (cur_bucket.count + 1))
        matches[0] = local_matches
        for count from 0 <= count < cur_bucket.count:
            assert cur_line_idx != SENTINEL
            local_matches[count] = cur_line_idx
            cur_line_idx = self._raw_lines[cur_line_idx].next_line_index
        return cur_bucket.count

    def _get_matching_lines(self):
        """Return a dictionary showing matching lines."""
        matching = {}
        for line in self.lines:
            matching[line] = self.get_matches(line)
        return matching

    def get_idx_matches(self, right_idx):
        """Return the left lines matching the right line at the given offset."""
        line = self._right_lines[right_idx]
        return self.get_matches(line)

    def extend_lines(self, lines, index):
        """Add more lines to the left-lines list.

        :param lines: A list of lines to add
        :param index: A True/False for each node to define if it should be
            indexed.
        """
        cdef Py_ssize_t orig_len
        cdef Py_ssize_t min_new_hash_size
        assert len(lines) == len(index)
        min_new_hash_size = self._compute_minimum_hash_size(len(self.lines) +
                                                            len(lines))
        orig_len = len(self.lines)
        self.lines.extend(lines)
        self._extend_raw_lines(index)
        if self._hashtable_size >= min_new_hash_size:
            # Just add the new lines, don't bother resizing the hash table
            self._extend_hash_table(len(index))
            return
        self._build_hash_table()

    def set_right_lines(self, lines):
        """Set the lines we will be matching against."""
        self._right_lines = lines


cdef Py_ssize_t intersect_sorted(Py_ssize_t *base, Py_ssize_t base_count,
                                 Py_ssize_t *new_values, Py_ssize_t new_count) except -1:
    """Intersect the base values with the new values.

    It is assumed that both base and new_values are sorted in ascending order,
    with no duplicates.

    The values in 'base' will be modified to only contain the entries that are
    in both base and new. If nothing matches, 'base' will not be modified

    :param base: An array of base values
    :param base_count: The length of the base array
    :param new_values: An array of values to compare to base, will be modified
        to only contain matching entries
    :param new_count: The number of new entries
    :return: The count of matching values
    """
    cdef Py_ssize_t *cur_base
    cdef Py_ssize_t *cur_new
    cdef Py_ssize_t *cur_out
    cdef Py_ssize_t count
    cdef Py_ssize_t *base_end
    cdef Py_ssize_t *new_end

    cur_base = base
    cur_out = base
    cur_new = new_values
    base_end = base + base_count
    new_end = new_values + new_count
    count = 0

    while cur_base < base_end and cur_new < new_end:
        if cur_base[0] == cur_new[0]:
            # This may be assigning to self.
            cur_out[0] = cur_base[0]
            count += 1
            cur_out = cur_out + 1
            # We matched, so move both pointers
            cur_base = cur_base + 1
            cur_new = cur_new + 1
        elif cur_base[0] < cur_new[0]:
            # cur_base is "behind" so increment it
            cur_base = cur_base + 1
        else:
            # cur_new must be "behind" move its pointer
            cur_new = cur_new + 1
    return count


cdef object array_as_list(Py_ssize_t *array, Py_ssize_t count):
    cdef int i
    lst = []
    for i from 0 <= i < count:
        lst.append(array[i])
    return lst


def _get_longest_match(equivalence_table, pos, max_pos, locations):
    """Get the longest possible match for the current position."""
    cdef EquivalenceTable eq
    cdef Py_ssize_t cpos
    cdef Py_ssize_t cmax_pos
    cdef Py_ssize_t *matches
    cdef Py_ssize_t match_count
    cdef PyObject *line
    cdef Py_ssize_t *copy_ends
    cdef Py_ssize_t copy_count
    cdef Py_ssize_t range_len
    cdef Py_ssize_t in_start
    cdef Py_ssize_t i
    cdef Py_ssize_t intersect_count

    eq = equivalence_table
    cpos = pos
    cmax_pos = max_pos
    range_start = pos
    range_len = 0
    matches = NULL
    match_count = 0
    copy_ends = NULL
    copy_count = 0

    # TODO: Handle when locations is not None
    while cpos < cmax_pos:
        # TODO: Instead of grabbing the full list of matches and then doing an
        #       intersection, use a helper that does the intersection
        #       as-it-goes.
        line = PyList_GET_ITEM(eq._right_lines, cpos)
        safe_free(<void**>&matches)
        match_count = eq.get_raw_matches(line, &matches)
        if match_count == 0:
            # No more matches, just return whatever we have, but we know that
            # this last position is not going to match anything
            cpos = cpos + 1
            break
        else:
            if copy_ends == NULL:
                # We are starting a new range, just steal the matches
                copy_ends = matches
                copy_count = match_count
                matches = NULL
                match_count = 0
                for i from 0 <= i < copy_count:
                    copy_ends[i] = copy_ends[i] + 1
                range_len = 1
            else:
                # We are currently in the middle of a match
                intersect_count = intersect_sorted(copy_ends, copy_count,
                                                   matches, match_count)
                if intersect_count == 0:
                    # But we are done with this match, we should be
                    # starting a new one, though. We will pass back 'locations'
                    # so that we don't have to do another lookup.
                    break
                else:
                    copy_count = intersect_count
                    # range continues, step the copy ends
                    for i from 0 <= i < copy_count:
                        copy_ends[i] = copy_ends[i] + 1
                    range_len = range_len + 1
                    safe_free(<void **>&matches)
                    match_count = 0
        cpos = cpos + 1
    if matches == NULL:
        # We consumed all of our matches
        locations = None
    else:
        locations = array_as_list(matches, match_count)
        safe_free(<void **>&matches)
    if copy_ends == NULL or copy_count == 0:
        # We never had a match
        return None, cpos, locations
    # Because copy_ends is always sorted, we know the 'min' is just the first
    # node
    in_start = copy_ends[0]
    safe_free(<void**>&copy_ends)
    return ((in_start - range_len), range_start, range_len), cpos, locations
