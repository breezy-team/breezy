# Copyright (C) 2010 Canonical Ltd
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

"""Command-line parser for all platforms."""

import re


_whitespace_match = re.compile(u'\s', re.UNICODE).match


class _PushbackSequence(object):
    def __init__(self, orig):
        self._iter = iter(orig)
        self._pushback_buffer = []
        
    def next(self):
        if len(self._pushback_buffer) > 0:
            return self._pushback_buffer.pop()
        else:
            return self._iter.next()
    
    def pushback(self, char):
        self._pushback_buffer.append(char)
        
    def __iter__(self):
        return self


class _Whitespace(object):
    def process(self, next_char, seq, context):
        if _whitespace_match(next_char):
            if len(context.token) > 0:
                return None
            else:
                return self
        elif (next_char == u'"'
              or (context.single_quotes_allowed and next_char == u"'")):
            context.quoted = True
            return _Quotes(next_char, self)
        elif next_char == u'\\':
            return _Backslash(self)
        else:
            context.token.append(next_char)
            return _Word()


class _Quotes(object):
    def __init__(self, quote_char, exit_state):
        self.quote_char = quote_char
        self.exit_state = exit_state

    def process(self, next_char, seq, context):
        if next_char == u'\\':
            return _Backslash(self)
        elif next_char == self.quote_char:
            return self.exit_state
        else:
            context.token.append(next_char)
            return self


class _Backslash(object):
    # See http://msdn.microsoft.com/en-us/library/bb776391(VS.85).aspx
    def __init__(self, exit_state):
        self.exit_state = exit_state
        self.count = 1
        
    def process(self, next_char, seq, context):
        if next_char == u'\\':
            self.count += 1
            return self
        elif next_char == u'"':
            # 2N backslashes followed by '"' are N backslashes
            context.token.append(u'\\' * (self.count/2))
            # 2N+1 backslashes follwed by '"' are N backslashes followed by '"'
            # which should not be processed as the start or end of quoted arg
            if self.count % 2 == 1:
                context.token.append(next_char) # odd number of '\' escapes the '"'
            else:
                seq.pushback(next_char) # let exit_state handle next_char
            self.count = 0
            return self.exit_state
        else:
            # N backslashes not followed by '"' are just N backslashes
            if self.count > 0:
                context.token.append(u'\\' * self.count)
                self.count = 0
            seq.pushback(next_char) # let exit_state handle next_char
            return self.exit_state
    
    def finish(self, context):
        if self.count > 0:
            context.token.append(u'\\' * self.count)


class _Word(object):
    def process(self, next_char, seq, context):
        if _whitespace_match(next_char):
            return None
        elif (next_char == u'"'
              or (context.single_quotes_allowed and next_char == u"'")):
            return _Quotes(next_char, self)
        elif next_char == u'\\':
            return _Backslash(self)
        else:
            context.token.append(next_char)
            return self


class Parser(object):
    def __init__(self, command_line, single_quotes_allowed=False):
        self._seq = _PushbackSequence(command_line)
        self.single_quotes_allowed = single_quotes_allowed
    
    def __iter__(self):
        return self
    
    def next(self):
        quoted, token = self._get_token()
        if token is None:
            raise StopIteration
        return quoted, token
    
    def _get_token(self):
        self.quoted = False
        self.token = []
        state = _Whitespace()
        for next_char in self._seq:
            state = state.process(next_char, self._seq, self)
            if state is None:
                break
        if not state is None and not getattr(state, 'finish', None) is None:
            state.finish(self)
        result = u''.join(self.token)
        if not self.quoted and result == '':
            result = None
        return self.quoted, result
