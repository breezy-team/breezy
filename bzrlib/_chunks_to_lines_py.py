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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""The python implementation of chunks_to_lines"""


def chunks_to_lines(chunks):
    """Ensure that chunks is split cleanly into lines.

    Each entry in the result should contain a single newline at the end. Except
    for the last entry which may not have a final newline.

    :param chunks: An list/tuple of strings. If chunks is already a list of
        lines, then we will return it as-is.
    :return: A list of strings.
    """
    # Optimize for a very common case when chunks are already lines
    def fail():
        raise IndexError
    try:
        # This is a bit ugly, but is the fastest way to check if all of the
        # chunks are individual lines.
        # You can't use function calls like .count(), .index(), or endswith()
        # because they incur too much python overhead.
        # It works because
        #   if chunk is an empty string, it will raise IndexError, which will
        #       be caught.
        #   if chunk doesn't end with '\n' then we hit fail()
        #   if there is more than one '\n' then we hit fail()
        # timing shows this loop to take 2.58ms rather than 3.18ms for
        # split_lines(''.join(chunks))
        # Further, it means we get to preserve the original lines, rather than
        # expanding memory
        if not chunks:
            return chunks
        [(chunk[-1] == '\n' and '\n' not in chunk[:-1]) or fail()
         for chunk in chunks[:-1]]
        last = chunks[-1]
        if last and '\n' not in last[:-1]:
            return chunks
    except IndexError:
        pass
    from bzrlib.osutils import split_lines
    return split_lines(''.join(chunks))
