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
"""Shell-like test scripts.

This allows users to write tests in a syntax very close to a shell session,
using a restricted and limited set of commands that should be enough to mimic
most of the behaviours.

A script is a set of commands, each command is composed of:
- one mandatory command line,
- one optional set of input lines to feed the command,
- one optional set of output expected lines,
- one optional set of error expected lines.

The optional lines starts with a special string (mnemonic: shell redirection):
- '<' for input,
- '>' for output,
- '2>' for errors,

The execution stops as soon as an expected output or an expected error is not
matched. 

When no output is specified, any ouput from the command is accepted
and let the execution continue. 

If an error occurs and no expected error is specified, the execution stops.

An error is defined by a returned status different from zero, not by the
presence of text on the error stream.

The matching is done on a full string comparison basis unless '...' is used, in
which case expected output/errors can be lees precise.

Examples:

The following will succeeds only if 'bzr add' outputs 'adding file'.

  bzr add file
  >adding file

If you want the command to succeed for any output, just use:

  bzr add file

The following will stop with an error:

  bzr not-a-command

If you want it to succeed, use:

  bzr not-a-command
  2> bzr: ERROR: unknown command "not-a-command"

You can use ellipsis (...) to replace any piece of text you don't want to be
matched exactly:

  bzr branch not-a-branch
  2>bzr: ERROR: Not a branch...not-a-branch/".


This can be used to ignore entire lines too:

cat
<first line
<second line
<third line
<fourth line
<last line
>first line
>...
>last line

You can check the content of a file with cat:

  cat <file
  >expected content

You can also check the existence of a file with cat, the following will fail if
the file doesn't exist:

  cat file

"""

import doctest
import errno
import os
import shlex
from cStringIO import StringIO

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

    def add_command(cmd, input, output, error):
        if cmd is not None:
            if input is not None:
                input = ''.join(input)
            if output is not None:
                output = ''.join(output)
            if error is not None:
                error = ''.join(error)
            commands.append((cmd, input, output, error))

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
            add_command(cmd_cur, input, output, error)
            # And start a new one
            cmd_cur = list(split(line))
            cmd_line = lineno
            input, output, error = None, None, None
    # Add the last seen command
    add_command(cmd_cur, input, output, error)
    return commands


def _scan_redirection_options(args):
    """Recognize and process input and output redirections.

    :param args: The command line arguments

    :return: A tuple containing: 
        - The file name redirected from or None
        - The file name redirected to or None
        - The mode to open the output file or None
        - The reamining arguments
    """
    def redirected_file_name(direction, name, args):
        if name == '':
            try:
                name = args.pop(0)
            except IndexError:
                # We leave the error handling to higher levels, an empty name
                # can't be legal.
                name = ''
        return name

    remaining = []
    in_name = None
    out_name, out_mode = None, None
    while args:
        arg = args.pop(0)
        if arg.startswith('<'):
            in_name = redirected_file_name('<', arg[1:], args)
        elif arg.startswith('>>'):
            out_name = redirected_file_name('>>', arg[2:], args)
            out_mode = 'ab+'
        elif arg.startswith('>',):
            out_name = redirected_file_name('>', arg[1:], args)
            out_mode = 'wb+'
        else:
            remaining.append(arg)
    return in_name, out_name, out_mode, remaining


class ScriptRunner(object):

    def __init__(self, test_case):
        self.test_case = test_case
        self.output_checker = doctest.OutputChecker()
        self.check_options = doctest.ELLIPSIS

    def run_script(self, text):
        for cmd, input, output, error in _script_to_commands(text):
            self.run_command(cmd, input, output, error)

    def _check_output(self, expected, actual):
        if expected is None:
            # Specifying None means: any output is accepted
            return
        if actual is None:
            self.test_case.fail('Unexpected: %s' % actual)
        matching = self.output_checker.check_output(
            expected, actual, self.check_options)
        if not matching:
            # Note that we can't use output_checker.output_difference() here
            # because... the API is broken ('expected' must be a doctest
            # specific object of which a 'want' attribute will be our
            # 'expected' parameter. So we just fallback to our good old
            # assertEqualDiff since we know there *are* differences and the
            # output should be decently readable.
            self.test_case.assertEqualDiff(expected, actual)

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
        retcode, actual_output, actual_error = method(str_input, cmd[1:])

        self._check_output(output, actual_output)
        self._check_output(error, actual_error)
        if retcode and not error and actual_error:
            self.test_case.fail('In \n\t%s\nUnexpected error: %s'
                                % (' '.join(cmd), actual_error))
        return retcode, actual_output, actual_error

    def _read_input(self, input, in_name):
        if in_name is not None:
            infile = open(in_name, 'rb')
            try:
                # Command redirection takes precedence over provided input
                input = infile.read()
            finally:
                infile.close()
        return input

    def _write_output(self, output, out_name, out_mode):
        if out_name is not None:
            outfile = open(out_name, out_mode)
            try:
                outfile.write(output)
            finally:
                outfile.close()
            output = None
        return output

    def do_bzr(self, input, args):
        retcode, out, err = self.test_case._run_bzr_core(
            args, retcode=None, encoding=None, stdin=input, working_dir=None)
        return retcode, out, err

    def do_cat(self, input, args):
        (in_name, out_name, out_mode, args) = _scan_redirection_options(args)
        if len(args) > 1:
            raise SyntaxError('Usage: cat [file1]')
        if args:
            if in_name is not None:
                raise SyntaxError('Specify a file OR use redirection')
            in_name = args[0]
        try:
            input = self._read_input(input, in_name)
        except IOError, e:
            if e.errno == errno.ENOENT:
                return 1, None, '%s: No such file or directory\n' % (in_name,)
        # Basically cat copy input to output
        output = input
        # Handle output redirections
        try:
            output = self._write_output(output, out_name, out_mode)
        except IOError, e:
            if e.errno == errno.ENOENT:
                return 1, None, '%s: No such file or directory\n' % (out_name,)
        return 0, output, None

    def do_echo(self, input, args):
        (in_name, out_name, out_mode, args) = _scan_redirection_options(args)
        if input and args:
                raise SyntaxError('Specify parameters OR use redirection')
        if args:
            input = ''.join(args)
        try:
            input = self._read_input(input, in_name)
        except IOError, e:
            if e.errno == errno.ENOENT:
                return 1, None, '%s: No such file or directory\n' % (in_name,)
        # Always append a \n'
        input += '\n'
        # Process output
        output = input
        # Handle output redirections
        try:
            output = self._write_output(output, out_name, out_mode)
        except IOError, e:
            if e.errno == errno.ENOENT:
                return 1, None, '%s: No such file or directory\n' % (out_name,)
        return 0, output, None

    def _ensure_in_jail(self, path):
        jail_root = self.test_case.get_jail_root()
        if not osutils.is_inside(jail_root, osutils.normalizepath(path)):
            raise ValueError('%s is not inside %s' % (path, jail_root))

    def do_cd(self, input, args):
        if len(args) > 1:
            raise SyntaxError('Usage: cd [dir]')
        if len(args) == 1:
            d = args[0]
            self._ensure_in_jail(d)
        else:
            d = self.test_case.get_jail_root()
        os.chdir(d)
        return 0, None, None

    def do_mkdir(self, input, args):
        if not args or len(args) != 1:
            raise SyntaxError('Usage: mkdir dir')
        d = args[0]
        self._ensure_in_jail(d)
        os.mkdir(d)
        return 0, None, None

    def do_rm(self, input, args):
        err = None

        def error(msg, path):
            return  "rm: cannot remove '%s': %s\n" % (path, msg)

        force, recursive = False, False
        opts = None
        if args and args[0][0] == '-':
            opts = args.pop(0)[1:]
            if 'f' in opts:
                force = True
                opts = opts.replace('f', '', 1)
            if 'r' in opts:
                recursive = True
                opts = opts.replace('r', '', 1)
        if not args or opts:
            raise SyntaxError('Usage: rm [-fr] path+')
        for p in args:
            self._ensure_in_jail(p)
            # FIXME: Should we put that in osutils ?
            try:
                os.remove(p)
            except OSError, e:
                if e.errno == errno.EISDIR:
                    if recursive:
                        osutils.rmtree(p)
                    else:
                        err = error('Is a directory', p)
                        break
                elif e.errno == errno.ENOENT:
                    if not force:
                        err =  error('No such file or directory', p)
                        break
                else:
                    raise
        if err:
            retcode = 1
        else:
            retcode = 0
        return retcode, None, err


class TestCaseWithMemoryTransportAndScript(tests.TestCaseWithMemoryTransport):

    def setUp(self):
        super(TestCaseWithMemoryTransportAndScript, self).setUp()
        self.script_runner = ScriptRunner(self)
        # Break the circular dependency
        def break_dependency():
            self.script_runner = None
        self.addCleanup(break_dependency)

    def get_jail_root(self):
        raise NotImplementedError(self.get_jail_root)

    def run_script(self, script):
        return self.script_runner.run_script(script)

    def run_command(self, cmd, input, output, error):
        return self.script_runner.run_command(cmd, input, output, error)


class TestCaseWithTransportAndScript(tests.TestCaseWithTransport):

    def setUp(self):
        super(TestCaseWithTransportAndScript, self).setUp()
        self.script_runner = ScriptRunner(self)
        # Break the circular dependency
        def break_dependency():
            self.script_runner = None
        self.addCleanup(break_dependency)

    def get_jail_root(self):
        return self.test_dir

    def run_script(self, script):
        return self.script_runner.run_script(script)

    def run_command(self, cmd, input, output, error):
        return self.script_runner.run_command(cmd, input, output, error)
