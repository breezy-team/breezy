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

from cStringIO import StringIO
import os
import shlex

from bzrlib import (
    osutils,
    tests,
    )


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
    Output lines start with '>'.
    Error lines start with '2>'.
    """
    commands = []
    cmd_cur = None
    cmd_line = 1
    lineno = 0
    input, output, error = None, None, None
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
        elif line.startswith('2>'):
            if error is None:
                if cmd_cur is None:
                    raise SyntaxError('No command for that error',
                                      (file_name, lineno, 1, orig))
                error = []
            error.append(line[2:] + '\n')
            continue
        else:
            # Time to output the current command
            if cmd_cur is not None:
                commands.append((cmd_cur, input, output, error))
            # And start a new one
            cmd_cur = list(split(line))
            cmd_line = lineno
            input, output, error = None, None, None
    # Add the last seen command
    if cmd_cur is not None:
        commands.append((cmd_cur, input, output, error))
    return commands


class TestCaseWithScript(tests.TestCaseWithTransport):

    def setUp(self):
        super(TestCaseWithScript, self).setUp()
        self._vars = {}

    def run_script(self, text):
        for cmd, input, output, error in _script_to_commands(text):
            self.run_command(cmd, input, output, error)

    def _check_output(self, expected, actual):
        if expected is None:
            # Specifying None means: any output is accepted
            return
        str_expected = ''.join(expected)
        self.assertEquals(str_expected, actual)

    def run_command(self, cmd, input, output, error):
        mname = 'do_' + cmd[0]
        method = getattr(self, mname, None)
        if method is None:
            raise SyntaxError('Command not found "%s"' % (cmd[0],),
                              None, 1, ' '.join(cmd))
        if input is None:
            str_input = ''
        else:
            str_input = ''.join(input)
        actual_output, actual_error = method(str_input, cmd[1:])

        self._check_output(output, actual_output)
        self._check_output(error, actual_error)
        return actual_output, actual_error

    def do_bzr(self, input, args):
        out, err = self._run_bzr_core(args, retcode=None, encoding=None,
                                      stdin=input, working_dir=None)
        return out, err

    def do_cat(self, input, args):
        in_name = None
        out_name = None
        syntax_ok = False
        if not args:
            in_name = None
            out_name = None
            syntax_ok = True
        elif len(args) == 1:
            in_name = args[0]
            if in_name.startswith('>'):
                out_name = in_name[1:]
                in_name = None
            else:
                out_name = None
            syntax_ok = True
        elif len(args) == 2:
            in_name, out_name = args[0], args[1][1:]
            syntax_ok = args[1].startswith('>')
        if not syntax_ok:
            raise SyntaxError('Usage: cat [file1] [>file2]')
        if in_name is not None:
            infile = open(in_name, 'rb')
            try:
                input = infile.read()
            finally:
                infile.close()
        out = StringIO(input)
        output = out.getvalue()
        if out_name is not None:
            outfile = open(out_name, 'wb')
            try:
                outfile.write(output)
            finally:
                outfile.close()
            output = None
        return output, None

    def _ensure_in_jail(self, path):
        if not osutils.is_inside(self.test_dir, osutils.normalizepath(path)):
                raise ValueError('%s is not inside %s' % (path, self.test_dir))

    def do_cd(self, input, args):
        if len(args) > 1:
            raise SyntaxError('Usage: cd [dir]')
        if len(args) == 1:
            d = args[0]
            self._ensure_in_jail(d)
        else:
            d = self.test_dir
        os.chdir(d)
        return None, None

    def do_mkdir(self, input, args):
        if not args or len(args) != 1:
            raise SyntaxError('Usage: mkdir dir')
        d = args[0]
        self._ensure_in_jail(d)
        os.mkdir(d)
        return None, None

