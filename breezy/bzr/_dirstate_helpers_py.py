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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Python implementations of Dirstate Helper functions."""

import binascii
import os
import struct

# We cannot import the dirstate module, because it loads this module
# All we really need is the IN_MEMORY_MODIFIED constant
from .dirstate import DirState, DirstateCorrupt


def pack_stat(st, _b64=binascii.b2a_base64, _pack=struct.Struct('>6L').pack):
    """Convert stat values into a packed representation

    Not all of the fields from the stat included are strictly needed, and by
    just encoding the mtime and mode a slight speed increase could be gained.
    However, using the pyrex version instead is a bigger win.
    """
    # base64 encoding always adds a final newline, so strip it off
    return _b64(_pack(st.st_size & 0xFFFFFFFF, int(st.st_mtime) & 0xFFFFFFFF,
                      int(st.st_ctime) & 0xFFFFFFFF, st.st_dev & 0xFFFFFFFF,
                      st.st_ino & 0xFFFFFFFF, st.st_mode))[:-1]


def _unpack_stat(packed_stat):
    """Turn a packed_stat back into the stat fields.

    This is meant as a debugging tool, should not be used in real code.
    """
    (st_size, st_mtime, st_ctime, st_dev, st_ino,
     st_mode) = struct.unpack('>6L', binascii.a2b_base64(packed_stat))
    return dict(st_size=st_size, st_mtime=st_mtime, st_ctime=st_ctime,
                st_dev=st_dev, st_ino=st_ino, st_mode=st_mode)


def _bisect_path_left(paths, path):
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
        if _lt_path_by_dirblock(cur, path):
            lo = mid + 1
        else:
            hi = mid
    return lo


def _bisect_path_right(paths, path):
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
        mid = (lo + hi) // 2
        # Grab the dirname for the current dirblock
        cur = paths[mid]
        if _lt_path_by_dirblock(path, cur):
            hi = mid
        else:
            lo = mid + 1
    return lo


def bisect_dirblock(dirblocks, dirname, lo=0, hi=None, cache={}):
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
        dirname_split = dirname.split(b'/')
        cache[dirname] = dirname_split
    while lo < hi:
        mid = (lo + hi) // 2
        # Grab the dirname for the current dirblock
        cur = dirblocks[mid][0]
        try:
            cur_split = cache[cur]
        except KeyError:
            cur_split = cur.split(b'/')
            cache[cur] = cur_split
        if cur_split < dirname_split:
            lo = mid + 1
        else:
            hi = mid
    return lo


def lt_by_dirs(path1, path2):
    """Compare two paths directory by directory.

    This is equivalent to doing::

       operator.lt(path1.split('/'), path2.split('/'))

    The idea is that you should compare path components separately. This
    differs from plain ``path1 < path2`` for paths like ``'a-b'`` and ``a/b``.
    "a-b" comes after "a" but would come before "a/b" lexically.

    :param path1: first path
    :param path2: second path
    :return: True if path1 comes first, otherwise False
    """
    if not isinstance(path1, bytes):
        raise TypeError("'path1' must be a byte string, not %s: %r"
                        % (type(path1), path1))
    if not isinstance(path2, bytes):
        raise TypeError("'path2' must be a byte string, not %s: %r"
                        % (type(path2), path2))
    return path1.split(b'/') < path2.split(b'/')


def _lt_path_by_dirblock(path1, path2):
    """Compare two paths based on what directory they are in.

    This generates a sort order, such that all children of a directory are
    sorted together, and grandchildren are in the same order as the
    children appear. But all grandchildren come after all children.

    :param path1: first path
    :param path2: the second path
    :return: True if path1 comes first, otherwise False
    """
    if not isinstance(path1, bytes):
        raise TypeError("'path1' must be a plain string, not %s: %r"
                        % (type(path1), path1))
    if not isinstance(path2, bytes):
        raise TypeError("'path2' must be a plain string, not %s: %r"
                        % (type(path2), path2))
    dirname1, basename1 = os.path.split(path1)
    key1 = (dirname1.split(b'/'), basename1)
    dirname2, basename2 = os.path.split(path2)
    key2 = (dirname2.split(b'/'), basename2)
    return key1 < key2


def _read_dirblocks(state):
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

    fields = text.split(b'\0')
    # Remove the last blank entry
    trailing = fields.pop()
    if trailing != b'':
        raise DirstateCorrupt(state,
                              'trailing garbage: %r' % (trailing,))
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
    if field_count - cur != expected_field_count:
        raise DirstateCorrupt(state,
                              'field count incorrect %s != %s, entry_size=%s, '
                              'num_entries=%s fields=%r' % (
                                  field_count - cur, expected_field_count, entry_size,
                                  state._num_entries, fields))

    if num_present_parents == 1:
        # Bind external functions to local names
        _int = int
        # We access all fields in order, so we can just iterate over
        # them. Grab an straight iterator over the fields. (We use an
        # iterator because we don't want to do a lot of additions, nor
        # do we want to do a lot of slicing)
        _iter = iter(fields)
        # Get a local reference to the compatible next method
        next = getattr(_iter, '__next__', None)
        if next is None:
            next = _iter.next
        # Move the iterator to the current position
        for x in range(cur):
            next()
        # The two blocks here are deliberate: the root block and the
        # contents-of-root block.
        state._dirblocks = [(b'', []), (b'', [])]
        current_block = state._dirblocks[0][1]
        current_dirname = b''
        append_entry = current_block.append
        for count in range(state._num_entries):
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
                     [(  # Current Tree
                         next(),                # minikind
                         next(),                # fingerprint
                         _int(next()),          # size
                         next() == b'y',        # executable
                         next(),                # packed_stat or revision_id
                     ),
                (  # Parent 1
                         next(),                # minikind
                         next(),                # fingerprint
                         _int(next()),          # size
                         next() == b'y',        # executable
                         next(),                # packed_stat or revision_id
                     ),
                ])
            trailing = next()
            if trailing != b'\n':
                raise ValueError("trailing garbage in dirstate: %r" % trailing)
            # append the entry to the current block
            append_entry(entry)
        state._split_root_dirblock_into_contents()
    else:
        fields_to_entry = state._get_fields_to_entry()
        entries = [fields_to_entry(fields[pos:pos + entry_size])
                   for pos in range(cur, field_count, entry_size)]
        state._entries_to_current_state(entries)
    # To convert from format 2  => format 3
    # state._dirblocks = sorted(state._dirblocks,
    #                          key=lambda blk:blk[0].split('/'))
    # To convert from format 3 => format 2
    # state._dirblocks = sorted(state._dirblocks)
    state._dirblock_state = DirState.IN_MEMORY_UNMODIFIED
