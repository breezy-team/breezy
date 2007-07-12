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

"""Python implementations of Dirstate Helper functions."""

import os

from bzrlib import (
    dirstate,
    )


def bisect_path_left_py(paths, path):
    """Return the index where to insert path into paths.

    This uses the dirblock sorting. So all children in a directory come before
    the children of children. For example::

        a/
          b/
            c
          d/
            e
          b-c
          d-e
        a-a
        a=c

    Will be sorted as::

        a
        a-a
        a=c
        a/b
        a/b-c
        a/d
        a/d-e
        a/b/c
        a/d/e

    :param paths: A list of paths to search through
    :param path: A single path to insert
    :return: An offset where 'path' can be inserted.
    :seealso: bisect.bisect_left
    """
    hi = len(paths)
    lo = 0
    while lo < hi:
        mid = (lo + hi) // 2
        # Grab the dirname for the current dirblock
        cur = paths[mid]
        if cmp_path_by_dirblock_py(cur, path) < 0:
            lo = mid + 1
        else:
            hi = mid
    return lo


def bisect_path_right_py(paths, path):
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
    hi = len(paths)
    lo = 0
    while lo < hi:
        mid = (lo+hi)//2
        # Grab the dirname for the current dirblock
        cur = paths[mid]
        if cmp_path_by_dirblock_py(path, cur) < 0:
            hi = mid
        else:
            lo = mid + 1
    return lo


def bisect_dirblock_py(dirblocks, dirname, lo=0, hi=None, cache={}):
    """Return the index where to insert dirname into the dirblocks.

    The return value idx is such that all directories blocks in dirblock[:idx]
    have names < dirname, and all blocks in dirblock[idx:] have names >=
    dirname.

    Optional args lo (default 0) and hi (default len(dirblocks)) bound the
    slice of a to be searched.
    """
    if hi is None:
        hi = len(dirblocks)
    try:
        dirname_split = cache[dirname]
    except KeyError:
        dirname_split = dirname.split('/')
        cache[dirname] = dirname_split
    while lo < hi:
        mid = (lo + hi) // 2
        # Grab the dirname for the current dirblock
        cur = dirblocks[mid][0]
        try:
            cur_split = cache[cur]
        except KeyError:
            cur_split = cur.split('/')
            cache[cur] = cur_split
        if cur_split < dirname_split: lo = mid + 1
        else: hi = mid
    return lo


def _read_dirblocks_py(state):
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

    fields = text.split('\0')
    # Remove the last blank entry
    trailing = fields.pop()
    assert trailing == ''
    # consider turning fields into a tuple.

    # skip the first field which is the trailing null from the header.
    cur = 1
    # Each line now has an extra '\n' field which is not used
    # so we just skip over it
    # entry size:
    #  3 fields for the key
    #  + number of fields per tree_data (5) * tree count
    #  + newline
    num_present_parents = state._num_present_parents()
    tree_count = 1 + num_present_parents
    entry_size = state._fields_per_entry()
    expected_field_count = entry_size * state._num_entries
    field_count = len(fields)
    # this checks our adjustment, and also catches file too short.
    assert field_count - cur == expected_field_count, \
        'field count incorrect %s != %s, entry_size=%s, '\
        'num_entries=%s fields=%r' % (
            field_count - cur, expected_field_count, entry_size,
            state._num_entries, fields)

    if num_present_parents == 1:
        # Bind external functions to local names
        _int = int
        # We access all fields in order, so we can just iterate over
        # them. Grab an straight iterator over the fields. (We use an
        # iterator because we don't want to do a lot of additions, nor
        # do we want to do a lot of slicing)
        next = iter(fields).next
        # Move the iterator to the current position
        for x in xrange(cur):
            next()
        # The two blocks here are deliberate: the root block and the
        # contents-of-root block.
        state._dirblocks = [('', []), ('', [])]
        current_block = state._dirblocks[0][1]
        current_dirname = ''
        append_entry = current_block.append
        for count in xrange(state._num_entries):
            dirname = next()
            name = next()
            file_id = next()
            if dirname != current_dirname:
                # new block - different dirname
                current_block = []
                current_dirname = dirname
                state._dirblocks.append((current_dirname, current_block))
                append_entry = current_block.append
            # we know current_dirname == dirname, so re-use it to avoid
            # creating new strings
            entry = ((current_dirname, name, file_id),
                     [(# Current Tree
                         next(),                # minikind
                         next(),                # fingerprint
                         _int(next()),          # size
                         next() == 'y',         # executable
                         next(),                # packed_stat or revision_id
                     ),
                     ( # Parent 1
                         next(),                # minikind
                         next(),                # fingerprint
                         _int(next()),          # size
                         next() == 'y',         # executable
                         next(),                # packed_stat or revision_id
                     ),
                     ])
            trailing = next()
            assert trailing == '\n'
            # append the entry to the current block
            append_entry(entry)
        state._split_root_dirblock_into_contents()
    else:
        fields_to_entry = state._get_fields_to_entry()
        entries = [fields_to_entry(fields[pos:pos+entry_size])
                   for pos in xrange(cur, field_count, entry_size)]
        state._entries_to_current_state(entries)
    # To convert from format 2  => format 3
    # state._dirblocks = sorted(state._dirblocks,
    #                          key=lambda blk:blk[0].split('/'))
    # To convert from format 3 => format 2
    # state._dirblocks = sorted(state._dirblocks)
    state._dirblock_state = dirstate.DirState.IN_MEMORY_UNMODIFIED


def cmp_by_dirs_py(path1, path2):
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
    return cmp(path1.split('/'), path2.split('/'))


def cmp_path_by_dirblock_py(path1, path2):
    """Compare two paths based on what directory they are in.

    This generates a sort order, such that all children of a directory are
    sorted together, and grandchildren are in the same order as the
    children appear. But all grandchildren come after all children.

    :param path1: first path
    :param path2: the second path
    :return: positive number if ``path1`` comes first,
        0 if paths are equal
        and a negative number if ``path2`` sorts first
    """
    dirname1, basename1 = os.path.split(path1)
    key1 = (dirname1.split('/'), basename1)
    dirname2, basename2 = os.path.split(path2)
    key2 = (dirname2.split('/'), basename2)
    return cmp(key1, key2)
