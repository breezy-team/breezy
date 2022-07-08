# Copyright (C) 2008 Canonical Ltd
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

"""The python implementation of chunks_to_lines"""


def chunks_to_lines(chunks):
    """Re-split chunks into simple lines.

    Each entry in the result should contain a single newline at the end. Except
    for the last entry which may not have a final newline. If chunks is already
    a simple list of lines, we return it directly.

    :param chunks: An list/tuple of strings. If chunks is already a list of
        lines, then we will return it as-is.
    :return: A list of strings.
    """
    # Optimize for a very common case when chunks are already lines
    last_no_newline = False
    for chunk in chunks:
        if last_no_newline:
            # Only the last chunk is allowed to not have a trailing newline
            # Getting here means the last chunk didn't have a newline, and we
            # have a chunk following it
            break
        if not chunk:
            # Empty strings are never valid lines
            break
        elif b'\n' in chunk[:-1]:
            # This chunk has an extra '\n', so we will have to split it
            break
        elif chunk[-1:] != b'\n':
            # This chunk does not have a trailing newline
            last_no_newline = True
    else:
        # All of the lines (but possibly the last) have a single newline at the
        # end of the string.
        # For the last one, we allow it to not have a trailing newline, but it
        # is not allowed to be an empty string.
        return chunks

    # These aren't simple lines, just join and split again.
    from breezy import osutils
    return osutils._split_lines(b''.join(chunks))
