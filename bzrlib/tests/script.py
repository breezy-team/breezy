# Copyright (C) 2009 Canonical Ltd
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

import shlex


def split(s):
    """Split a command line respecting quotes."""
    scanner = shlex.shlex(s)
    scanner.quotes = '\'"`'
    scanner.whitespace_split = True
    for t in list(scanner):
        # Strip the simple and double quotes since we don't care about them.
        # We leave the backquotes in place though since they have a different
        # semantic.
        if t[0] in  ('"', "'") and t[0] == t[-1]:
            yield t[1:-1]
        else:
            yield t


def _script_to_commands(text, file_name=None):
    """Turn a script into a list of commands with their associated IOs.

    Each command appears on a line by itself. It can be associated with an
    input that will feed it and an expected output.
    Comments starts with '#' until the end of line.
    Empty lines are ignored.
    Input and output are full lines terminated by a '\n'.
    Input lines start with '<'.
    Output lines start with '>' 
    """
    commands = []
    cmd_cur = None
    cmd_line = 1
    lineno = 0
    input = None
    output = None
    for line in text.split('\n'):
        lineno += 1
        # Keep a copy for error reporting
        orig = line
        comment =  line.find('#')
        if comment >= 0:
            # Delete comments
            line = line[0:comment]
            line = line.rstrip()
        if line == '':
            # Ignore empty lines
            continue
        if line.startswith('<'):
            if input is None:
                if cmd_cur is None:
                    raise SyntaxError('No command for that input',
                                      (file_name, lineno, 1, orig))
                input = []
            input.append(line[1:] + '\n')
            continue
        elif line.startswith('>'):
            if output is None:
                if cmd_cur is None:
                    raise SyntaxError('No command for that output',
                                      (file_name, lineno, 1, orig))
                output = []
            output.append(line[1:] + '\n')
            continue
        else:
            # Time to output the current command
            if cmd_cur is not None:
                commands.append((cmd_cur, input, output))
            # And start a new one
            cmd_cur = list(split(line))
            cmd_line = lineno
            input = None
            output = None
    # Add the last seen command
    if cmd_cur is not None:
        commands.append((cmd_cur, input, output))
    return commands



