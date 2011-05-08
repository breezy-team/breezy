# Copyright (C) 2011 Canonical Ltd
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


# UTextWrapper._handle_long_word, UTextWrapper._wrap_chunks,
# wrap and fill is copied from Python's textwrap module
# (under PSF license) and modified for support CJK.

import sys
import textwrap
from unicodedata import east_asian_width as _eawidth

from bzrlib import osutils

__all__ = ["UTextWrapper", "fill", "wrap"]

def _unicode_char_width(uc):
    """Return width of character `uc`.

    :param:     uc      Single unicode character.
    """
    # 'A' means width of the character is not be able to determine.
    # We assume that it's width is 2 because longer wrap may over
    # terminal width but shorter wrap may be acceptable.
    return (_eawidth(uc) in 'FWA' and 2) or 1

def _width(s):
    """Returns width for s.
    
    When s is unicode, take care of east asian width.
    When s is bytes, treat all byte is single width character.

    NOTE: Supporting byte string should be removed with Python 3.
    """
    if isinstance(s, str):
        return len(s)
    assert isinstance(s, unicode)
    return sum(_unicode_char_width(c) for c in s)

def _cut(s, width):
    """Returns head and rest of s. (head+rest == s)

    Head is large as long as _width(head) <= width.
    """
    if isinstance(s, str):
        return s[:width], s[width:]
    assert isinstance(s, unicode)
    w = 0
    charwidth = _unicode_char_width
    for pos, c in enumerate(s):
        w += charwidth(c)
        if w > width:
            return s[:pos], s[pos:]
    return s, u''


class UTextWrapper(textwrap.TextWrapper):
    """
    Extend TextWrapper for Unicode.

    This textwrapper handles east asian double width and split word
    even if !break_long_words when word contains double width
    characters.
    """

    def __init__(self, width=None, **kwargs):
        if width is None:
            width = (osutils.terminal_width() or
                        osutils.default_terminal_width) - 1
        # No drop_whitespace param before Python 2.6 it was always dropped
        if sys.version_info < (2, 6):
            self.drop_whitespace = kwargs.pop("drop_whitespace", True)
            if not self.drop_whitespace:
                raise ValueError("TextWrapper version must drop whitespace")
        textwrap.TextWrapper.__init__(self, width, **kwargs)

    def _handle_long_word(self, chunks, cur_line, cur_len, width):
        # Figure out when indent is larger than the specified width, and make
        # sure at least one character is stripped off on every pass
        if width < 2:
            space_left = chunks[-1] and _width(chunks[-1][0]) or 1
        else:
            space_left = width - cur_len

        # If we're allowed to break long words, then do so: put as much
        # of the next chunk onto the current line as will fit.
        if self.break_long_words:
            head, rest = _cut(chunks[-1], space_left)
            cur_line.append(head)
            if rest:
                chunks[-1] = rest
            else:
                del chunks[-1]

        # Otherwise, we have to preserve the long word intact.  Only add
        # it to the current line if there's nothing already there --
        # that minimizes how much we violate the width constraint.
        elif not cur_line:
            cur_line.append(chunks.pop())

        # If we're not allowed to break long words, and there's already
        # text on the current line, do nothing.  Next time through the
        # main loop of _wrap_chunks(), we'll wind up here again, but
        # cur_len will be zero, so the next line will be entirely
        # devoted to the long word that we can't handle right now.

    def _wrap_chunks(self, chunks):
        lines = []
        if self.width <= 0:
            raise ValueError("invalid width %r (must be > 0)" % self.width)

        # Arrange in reverse order so items can be efficiently popped
        # from a stack of chucks.
        chunks.reverse()

        while chunks:

            # Start the list of chunks that will make up the current line.
            # cur_len is just the length of all the chunks in cur_line.
            cur_line = []
            cur_len = 0

            # Figure out which static string will prefix this line.
            if lines:
                indent = self.subsequent_indent
            else:
                indent = self.initial_indent

            # Maximum width for this line.
            width = self.width - len(indent)

            # First chunk on line is whitespace -- drop it, unless this
            # is the very beginning of the text (ie. no lines started yet).
            if self.drop_whitespace and chunks[-1].strip() == '' and lines:
                del chunks[-1]

            while chunks:
                # Use _width instead of len for east asian width
                # l = len(chunks[-1])
                l = _width(chunks[-1])

                # Can at least squeeze this chunk onto the current line.
                if cur_len + l <= width:
                    cur_line.append(chunks.pop())
                    cur_len += l

                # Nope, this line is full.
                else:
                    break

            # The current line is full, and the next chunk is too big to
            # fit on *any* line (not just this one).
            if chunks and _width(chunks[-1]) > width:
                self._handle_long_word(chunks, cur_line, cur_len, width)

            # If the last chunk on this line is all whitespace, drop it.
            if self.drop_whitespace and cur_line and cur_line[-1].strip() == '':
                del cur_line[-1]

            # Convert current line back to a string and store it in list
            # of all lines (return value).
            if cur_line:
                lines.append(indent + ''.join(cur_line))

        return lines

    def _split(self, text):
        chunks = textwrap.TextWrapper._split(self, unicode(text))
        cjk_split_chunks = []
        for chunk in chunks:
            assert chunk # TextWrapper._split removes empty chunk
            prev_pos = 0
            for pos, char in enumerate(chunk):
                # Treats all asian character are line breakable.
                # But it is not true because line breaking is
                # prohibited around some characters.
                # See UAX # 14 "UNICODE LINE BREAKING ALGORITHM"
                if _eawidth(char) in 'FWA':
                    if prev_pos < pos:
                        cjk_split_chunks.append(chunk[prev_pos:pos])
                    cjk_split_chunks.append(char)
                    prev_pos = pos+1
            if prev_pos < len(chunk):
                cjk_split_chunks.append(chunk[prev_pos:])
        return cjk_split_chunks

    def wrap(self, text):
        # ensure text is unicode
        return textwrap.TextWrapper.wrap(self, unicode(text))

# -- Convenience interface ---------------------------------------------

def wrap(text, width=None, **kwargs):
    """Wrap a single paragraph of text, returning a list of wrapped lines.

    Reformat the single paragraph in 'text' so it fits in lines of no
    more than 'width' columns, and return a list of wrapped lines.  By
    default, tabs in 'text' are expanded with string.expandtabs(), and
    all other whitespace characters (including newline) are converted to
    space.  See TextWrapper class for available keyword args to customize
    wrapping behaviour.
    """
    return UTextWrapper(width=width, **kwargs).wrap(text)

def fill(text, width=None, **kwargs):
    """Fill a single paragraph of text, returning a new string.

    Reformat the single paragraph in 'text' to fit in lines of no more
    than 'width' columns, and return a new string containing the entire
    wrapped paragraph.  As with wrap(), tabs are expanded and other
    whitespace characters converted to space.  See TextWrapper class for
    available keyword args to customize wrapping behaviour.
    """
    return UTextWrapper(width=width, **kwargs).fill(text)

