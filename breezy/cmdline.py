# Copyright (C) 2010-2011 Canonical Ltd
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

"""Unicode-compatible command-line splitter for all platforms.

The user-visible behaviour of this module is described in
configuring_bazaar.txt.
"""

import re
from typing import Optional

_whitespace_match = re.compile("\\s", re.UNICODE).match


class _PushbackSequence:
    def __init__(self, orig) -> None:
        self._iter = iter(orig)
        self._pushback_buffer: list[str] = []

    def __next__(self):
        if len(self._pushback_buffer) > 0:
            return self._pushback_buffer.pop()
        else:
            return next(self._iter)

    next = __next__

    def pushback(self, char):
        self._pushback_buffer.append(char)

    def __iter__(self):
        return self


class _Whitespace:
    def process(self, next_char, context):
        if _whitespace_match(next_char):
            if len(context.token) > 0:
                return None
            else:
                return self
        elif next_char in context.allowed_quote_chars:
            context.quoted = True
            return _Quotes(next_char, self)
        elif next_char == "\\":
            return _Backslash(self)
        else:
            context.token.append(next_char)
            return _Word()


class _Quotes:
    def __init__(self, quote_char, exit_state):
        self.quote_char = quote_char
        self.exit_state = exit_state

    def process(self, next_char, context):
        if next_char == "\\":
            return _Backslash(self)
        elif next_char == self.quote_char:
            context.token.append("")
            return self.exit_state
        else:
            context.token.append(next_char)
            return self


class _Backslash:
    # See http://msdn.microsoft.com/en-us/library/bb776391(VS.85).aspx
    def __init__(self, exit_state):
        self.exit_state = exit_state
        self.count = 1

    def process(self, next_char, context):
        if next_char == "\\":
            self.count += 1
            return self
        elif next_char in context.allowed_quote_chars:
            # 2N backslashes followed by a quote are N backslashes
            context.token.append("\\" * (self.count // 2))
            # 2N+1 backslashes follwed by a quote are N backslashes followed by
            # the quote which should not be processed as the start or end of
            # the quoted arg
            if self.count % 2 == 1:
                # odd number of \ escapes the quote
                context.token.append(next_char)
            else:
                # let exit_state handle next_char
                context.seq.pushback(next_char)
            self.count = 0
            return self.exit_state
        else:
            # N backslashes not followed by a quote are just N backslashes
            if self.count > 0:
                context.token.append("\\" * self.count)
                self.count = 0
            # let exit_state handle next_char
            context.seq.pushback(next_char)
            return self.exit_state

    def finish(self, context):
        if self.count > 0:
            context.token.append("\\" * self.count)


class _Word:
    def process(self, next_char, context):
        if _whitespace_match(next_char):
            return None
        elif next_char in context.allowed_quote_chars:
            return _Quotes(next_char, self)
        elif next_char == "\\":
            return _Backslash(self)
        else:
            context.token.append(next_char)
            return self


class Splitter:
    def __init__(self, command_line, single_quotes_allowed):
        self.seq = _PushbackSequence(command_line)
        self.allowed_quote_chars = '"'
        if single_quotes_allowed:
            self.allowed_quote_chars += "'"

    def __iter__(self):
        return self

    def __next__(self):
        quoted, token = self._get_token()
        if token is None:
            raise StopIteration
        return quoted, token

    next = __next__

    def _get_token(self) -> tuple[bool, Optional[str]]:
        self.quoted = False
        self.token: list[str] = []
        state = _Whitespace()
        for next_char in self.seq:
            state = state.process(next_char, self)
            if state is None:
                break
        if state is not None and hasattr(state, "finish"):
            state.finish(self)
        result: Optional[str] = "".join(self.token)
        if not self.quoted and result == "":
            result = None
        return self.quoted, result


def split(unsplit, single_quotes_allowed=True):
    splitter = Splitter(unsplit, single_quotes_allowed=single_quotes_allowed)
    return [arg for quoted, arg in splitter]
