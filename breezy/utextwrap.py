# Copyright (C) 2011 Canonical Ltd
#
# UTextWrapper._handle_long_word, UTextWrapper._wrap_chunks,
# UTextWrapper._fix_sentence_endings, wrap and fill is copied from Python's
# textwrap module (under PSF license) and modified for support CJK.
# Original Copyright for these functions:
#
# Copyright (C) 1999-2001 Gregory P. Ward.
# Copyright (C) 2002, 2003 Python Software Foundation.
#
# Written by Greg Ward <gward@python.net>
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

import sys
import textwrap
from unicodedata import east_asian_width as _eawidth

from . import osutils

__all__ = ["UTextWrapper", "fill", "wrap"]


class UTextWrapper(textwrap.TextWrapper):
    """Extend TextWrapper for Unicode.

    This textwrapper handles east asian double width and split word
    even if !break_long_words when word contains double width
    characters.

    :param ambiguous_width: (keyword argument) width for character when
                            unicodedata.east_asian_width(c) == 'A'
                            (default: 1)

    Limitations:
    * expand_tabs doesn't fixed. It uses len() for calculating width
      of string on left of TAB.
    * Handles one codeunit as a single character having 1 or 2 width.
      This is not correct when there are surrogate pairs, combined
      characters or zero-width characters.
    * Treats all asian character are line breakable. But it is not
      true because line breaking is prohibited around some characters.
      (For example, breaking before punctation mark is prohibited.)
      See UAX # 14 "UNICODE LINE BREAKING ALGORITHM"
    """

    def __init__(self, width=None, **kwargs):
        if width is None:
            width = (osutils.terminal_width() or osutils.default_terminal_width) - 1

        ambi_width = kwargs.pop("ambiguous_width", 1)
        if ambi_width == 1:
            self._east_asian_doublewidth = "FW"
        elif ambi_width == 2:
            self._east_asian_doublewidth = "FWA"
        else:
            raise ValueError("ambiguous_width should be 1 or 2")

        self.max_lines = kwargs.get("max_lines")
        textwrap.TextWrapper.__init__(self, width, **kwargs)

    def _unicode_char_width(self, uc):
        """Return width of character `uc`.

        :param:     uc      Single unicode character.
        """
        # 'A' means width of the character is not be able to determine.
        # We assume that it's width is 2 because longer wrap may over
        # terminal width but shorter wrap may be acceptable.
        return (_eawidth(uc) in self._east_asian_doublewidth and 2) or 1

    def _width(self, s):
        """Returns width for s.

        When s is unicode, take care of east asian width.
        When s is bytes, treat all byte is single width character.
        """
        charwidth = self._unicode_char_width
        return sum(charwidth(c) for c in s)

    def _cut(self, s, width):
        """Returns head and rest of s. (head+rest == s).

        Head is large as long as _width(head) <= width.
        """
        w = 0
        charwidth = self._unicode_char_width
        for pos, c in enumerate(s):
            w += charwidth(c)
            if w > width:
                return s[:pos], s[pos:]
        return s, ""

    def _fix_sentence_endings(self, chunks):
        r"""_fix_sentence_endings(chunks : [string]).

        Correct for sentence endings buried in 'chunks'.  Eg. when the
        original text contains "... foo.\nBar ...", munge_whitespace()
        and split() will convert that to [..., "foo.", " ", "Bar", ...]
        which has one too few spaces; this method simply changes the one
        space to two.

        Note: This function is copied from textwrap.TextWrap and modified
        to use unicode always.
        """
        i = 0
        L = len(chunks) - 1
        patsearch = self.sentence_end_re.search
        while i < L:
            if chunks[i + 1] == " " and patsearch(chunks[i]):
                chunks[i + 1] = "  "
                i += 2
            else:
                i += 1

    def _handle_long_word(self, chunks, cur_line, cur_len, width):
        # Figure out when indent is larger than the specified width, and make
        # sure at least one character is stripped off on every pass
        if width < 2:
            space_left = (chunks[-1] and self._width(chunks[-1][0])) or 1
        else:
            space_left = width - cur_len

        # If we're allowed to break long words, then do so: put as much
        # of the next chunk onto the current line as will fit.
        if self.break_long_words:
            head, rest = self._cut(chunks[-1], space_left)
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
            raise ValueError("invalid width {!r} (must be > 0)".format(self.width))
        if self.max_lines is not None:
            if self.max_lines > 1:
                indent = self.subsequent_indent
            else:
                indent = self.initial_indent
            if (
                self._width(indent) + self._width(self.placeholder.lstrip())
                > self.width
            ):
                raise ValueError("placeholder too large for max width")

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
            if self.drop_whitespace and chunks[-1].strip() == "" and lines:
                del chunks[-1]

            while chunks:
                # Use _width instead of len for east asian width
                l = self._width(chunks[-1])

                # Can at least squeeze this chunk onto the current line.
                if cur_len + l <= width:
                    cur_line.append(chunks.pop())
                    cur_len += l

                # Nope, this line is full.
                else:
                    break

            # The current line is full, and the next chunk is too big to
            # fit on *any* line (not just this one).
            if chunks and self._width(chunks[-1]) > width:
                self._handle_long_word(chunks, cur_line, cur_len, width)
                cur_len = sum(map(len, cur_line))

            # If the last chunk on this line is all whitespace, drop it.
            # Python 3.13+ uses a while loop to drop multiple trailing whitespace chunks
            # Python < 3.13 uses an if statement to drop only one trailing whitespace chunk
            if sys.version_info >= (3, 13):
                while self.drop_whitespace and cur_line and cur_line[-1].strip() == "":
                    cur_len -= len(cur_line[-1])
                    del cur_line[-1]
            else:
                if self.drop_whitespace and cur_line and cur_line[-1].strip() == "":
                    cur_len -= len(cur_line[-1])
                    del cur_line[-1]

            # Convert current line back to a string and store it in list
            # of all lines (return value).
            if cur_line:
                if (
                    self.max_lines is None
                    or len(lines) + 1 < self.max_lines
                    or (
                        (
                            not chunks
                            or (
                                self.drop_whitespace
                                and len(chunks) == 1
                                and not chunks[0].strip()
                            )
                        )
                        and cur_len <= width
                    )
                ):
                    # Convert current line back to a string and store it in
                    # list of all lines (return value).
                    lines.append(indent + "".join(cur_line))
                else:
                    while cur_line:
                        if (
                            cur_line[-1].strip()
                            and cur_len + self._width(self.placeholder) <= width
                        ):
                            cur_line.append(self.placeholder)
                            lines.append(indent + "".join(cur_line))
                            break
                        cur_len -= self._width(cur_line[-1])
                        del cur_line[-1]
                    else:
                        if lines:
                            prev_line = lines[-1].rstrip()
                            if (
                                self._width(prev_line) + self._width(self.placeholder)
                                <= self.width
                            ):
                                lines[-1] = prev_line + self.placeholder
                                break
                        lines.append(indent + self.placeholder.lstrip())
                    break

        return lines

    def _split(self, text):
        chunks = textwrap.TextWrapper._split(self, osutils.safe_unicode(text))
        cjk_split_chunks = []
        for chunk in chunks:
            prev_pos = 0
            for pos, char in enumerate(chunk):
                if self._unicode_char_width(char) == 2:
                    if prev_pos < pos:
                        cjk_split_chunks.append(chunk[prev_pos:pos])
                    cjk_split_chunks.append(char)
                    prev_pos = pos + 1
            if prev_pos < len(chunk):
                cjk_split_chunks.append(chunk[prev_pos:])
        return cjk_split_chunks

    def wrap(self, text):
        # ensure text is unicode
        return textwrap.TextWrapper.wrap(self, osutils.safe_unicode(text))


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
