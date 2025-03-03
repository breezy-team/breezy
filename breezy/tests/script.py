# Copyright (C) 2009, 2010, 2011 Canonical Ltd
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

See developers/testing.html for more explanations.
"""

import doctest
import errno
import glob
import logging
import os
import shlex
import textwrap

from .. import osutils, tests
from ..tests import ui_testing


def split(s):
    """Split a command line respecting quotes."""
    scanner = shlex.shlex(s)
    scanner.quotes = "'\"`"
    scanner.whitespace_split = True
    yield from list(scanner)


def _script_to_commands(text, file_name=None):
    r"""Turn a script into a list of commands with their associated IOs.

    Each command appears on a line by itself starting with '$ '. It can be
    associated with an input that will feed it and an expected output.

    Comments starts with '#' until the end of line.
    Empty lines are ignored.

    Input and output are full lines terminated by a '\n'.

    Input lines start with '<'.
    Output lines start with nothing.
    Error lines start with '2>'.

    :return: A sequence of ([args], input, output, errors), where the args are
        split in to words, and the input, output, and errors are just strings,
        typically containing newlines.
    """
    commands = []

    def add_command(cmd, input, output, error):
        if cmd is not None:
            if input is not None:
                input = "".join(input)
            if output is not None:
                output = "".join(output)
            if error is not None:
                error = "".join(error)
            commands.append((cmd, input, output, error))

    cmd_cur = None
    lineno = 0
    input, output, error = None, None, None
    text = textwrap.dedent(text)
    lines = text.split("\n")
    # to make use of triple-quoted strings easier, we ignore a blank line
    # right at the start and right at the end; the rest are meaningful
    if lines and lines[0] == "":
        del lines[0]
    if lines and lines[-1] == "":
        del lines[-1]
    for line in lines:
        lineno += 1
        # Keep a copy for error reporting
        orig = line
        comment = line.find("#")
        if comment >= 0:
            # Delete comments
            # NB: this syntax means comments are allowed inside output, which
            # may be confusing...
            line = line[0:comment]
            line = line.rstrip()
            if line == "":
                continue
        if line.startswith("$"):
            # Time to output the current command
            add_command(cmd_cur, input, output, error)
            # And start a new one
            cmd_cur = list(split(line[1:]))
            input, output, error = None, None, None
        elif line.startswith("<"):
            if input is None:
                if cmd_cur is None:
                    raise SyntaxError(
                        "No command for that input", (file_name, lineno, 1, orig)
                    )
                input = []
            input.append(line[1:] + "\n")
        elif line.startswith("2>"):
            if error is None:
                if cmd_cur is None:
                    raise SyntaxError(
                        "No command for that error", (file_name, lineno, 1, orig)
                    )
                error = []
            error.append(line[2:] + "\n")
        else:
            # can happen if the first line is not recognized as a command, eg
            # if the prompt has leading whitespace
            if output is None:
                if cmd_cur is None:
                    raise SyntaxError(
                        "No command for line {!r}".format(line),
                        (file_name, lineno, 1, orig),
                    )
                output = []
            output.append(line + "\n")
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
        if name == "":
            try:
                name = args.pop(0)
            except IndexError:
                # We leave the error handling to higher levels, an empty name
                # can't be legal.
                name = ""
        return name

    remaining = []
    in_name = None
    out_name, out_mode = None, None
    while args:
        arg = args.pop(0)
        if arg.startswith("<"):
            in_name = redirected_file_name("<", arg[1:], args)
        elif arg.startswith(">>"):
            out_name = redirected_file_name(">>", arg[2:], args)
            out_mode = "a+"
        elif arg.startswith(
            ">",
        ):
            out_name = redirected_file_name(">", arg[1:], args)
            out_mode = "w+"
        else:
            remaining.append(arg)
    return in_name, out_name, out_mode, remaining


class ScriptRunner:
    """Run a shell-like script from a test.

    Can be used as:

    from breezy.tests import script

    ...

        def test_bug_nnnnn(self):
            sr = script.ScriptRunner()
            sr.run_script(self, '''
            $ brz init
            $ brz do-this
            # Boom, error
            ''')
    """

    def __init__(self):
        self.output_checker = doctest.OutputChecker()
        self.check_options = doctest.ELLIPSIS

    def run_script(self, test_case, text, null_output_matches_anything=False):
        """Run a shell-like script as a test.

        :param test_case: A TestCase instance that should provide the fail(),
            assertEqualDiff and _run_bzr_core() methods as well as a 'test_dir'
            attribute used as a jail root.

        :param text: A shell-like script (see _script_to_commands for syntax).

        :param null_output_matches_anything: For commands with no specified
            output, ignore any output that does happen, including output on
            standard error.
        """
        self.null_output_matches_anything = null_output_matches_anything
        for cmd, input, output, error in _script_to_commands(text):
            self.run_command(test_case, cmd, input, output, error)

    def run_command(self, test_case, cmd, input, output, error):
        mname = "do_" + cmd[0]
        method = getattr(self, mname, None)
        if method is None:
            raise SyntaxError(
                'Command not found "{}"'.format(cmd[0]), (None, 1, 1, " ".join(cmd))
            )
        if input is None:
            str_input = ""
        else:
            str_input = "".join(input)
        args = list(self._pre_process_args(cmd[1:]))
        retcode, actual_output, actual_error = method(test_case, str_input, args)

        try:
            self._check_output(output, actual_output, test_case)
        except AssertionError as e:
            raise AssertionError(str(e) + " in stdout of command {}".format(cmd))
        try:
            self._check_output(error, actual_error, test_case)
        except AssertionError as e:
            raise AssertionError(
                str(e) + " in stderr of running command {}".format(cmd)
            )
        if retcode and not error and actual_error:
            test_case.fail(
                "In \n\t{}\nUnexpected error: {}".format(" ".join(cmd), actual_error)
            )
        return retcode, actual_output, actual_error

    def _check_output(self, expected, actual, test_case):
        if not actual:
            if expected is None:
                return
            elif expected == "...\n":
                return
            else:
                test_case.fail(
                    "expected output: {!r}, but found nothing".format(expected)
                )

        null_output_matches_anything = getattr(
            self, "null_output_matches_anything", False
        )
        if null_output_matches_anything and expected is None:
            return

        expected = expected or ""
        matching = self.output_checker.check_output(
            expected, actual, self.check_options
        )
        if not matching:
            # Note that we can't use output_checker.output_difference() here
            # because... the API is broken ('expected' must be a doctest
            # specific object of which a 'want' attribute will be our
            # 'expected' parameter. So we just fallback to our good old
            # assertEqualDiff since we know there *are* differences and the
            # output should be decently readable.
            #
            # As a special case, we allow output that's missing a final
            # newline to match an expected string that does have one, so that
            # we can match a prompt printed on one line, then input given on
            # the next line.
            if expected == actual + "\n":
                pass
            else:
                test_case.assertEqualDiff(expected, actual)

    def _pre_process_args(self, args):
        for arg in args:
            # Strip the simple and double quotes since we don't care about
            # them.  We leave the backquotes in place though since they have a
            # different semantic.
            if arg[0] in ('"', "'") and arg[0] == arg[-1]:
                yield arg[1:-1]
            else:
                if glob.has_magic(arg):
                    matches = glob.glob(arg)
                    if matches:
                        # We care more about order stability than performance
                        # here
                        matches.sort()
                        yield from matches
                else:
                    yield arg

    def _read_input(self, input, in_name):
        if in_name is not None:
            infile = open(in_name)
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

    def do_brz(self, test_case, input, args):
        encoding = osutils.get_user_encoding()
        stdout = ui_testing.StringIOWithEncoding()
        stderr = ui_testing.StringIOWithEncoding()
        stdout.encoding = stderr.encoding = encoding
        handler = logging.StreamHandler(stderr)
        handler.setLevel(logging.INFO)

        logger = logging.getLogger("")
        logger.addHandler(handler)
        try:
            retcode = test_case._run_bzr_core(
                args,
                encoding=encoding,
                stdin=input,
                stdout=stdout,
                stderr=stderr,
                working_dir=None,
            )
        finally:
            logger.removeHandler(handler)

        return retcode, stdout.getvalue(), stderr.getvalue()

    def do_cat(self, test_case, input, args):
        (in_name, out_name, out_mode, args) = _scan_redirection_options(args)
        if args and in_name is not None:
            raise SyntaxError("Specify a file OR use redirection")

        inputs = []
        if input:
            inputs.append(input)
        input_names = args
        if in_name:
            args.append(in_name)
        for in_name in input_names:
            try:
                inputs.append(self._read_input(None, in_name))
            except OSError as e:
                # Some filenames are illegal on Windows and generate EINVAL
                # rather than just saying the filename doesn't exist
                if e.errno in (errno.ENOENT, errno.EINVAL):
                    return (1, None, "{}: No such file or directory\n".format(in_name))
                raise
        # Basically cat copy input to output
        output = "".join(inputs)
        # Handle output redirections
        try:
            output = self._write_output(output, out_name, out_mode)
        except OSError as e:
            # If out_name cannot be created, we may get 'ENOENT', however if
            # out_name is something like '', we can get EINVAL
            if e.errno in (errno.ENOENT, errno.EINVAL):
                return 1, None, "{}: No such file or directory\n".format(out_name)
            raise
        return 0, output, None

    def do_echo(self, test_case, input, args):
        (in_name, out_name, out_mode, args) = _scan_redirection_options(args)
        if input or in_name:
            raise SyntaxError("echo doesn't read from stdin")
        if args:
            input = " ".join(args)
        # Always append a \n'
        input += "\n"
        # Process output
        output = input
        # Handle output redirections
        try:
            output = self._write_output(output, out_name, out_mode)
        except OSError as e:
            if e.errno in (errno.ENOENT, errno.EINVAL):
                return 1, None, "{}: No such file or directory\n".format(out_name)
            raise
        return 0, output, None

    def _get_jail_root(self, test_case):
        return test_case.test_dir

    def _ensure_in_jail(self, test_case, path):
        jail_root = self._get_jail_root(test_case)
        if not osutils.is_inside(jail_root, osutils.normalizepath(path)):
            raise ValueError("{} is not inside {}".format(path, jail_root))

    def do_cd(self, test_case, input, args):
        if len(args) > 1:
            raise SyntaxError("Usage: cd [dir]")
        if len(args) == 1:
            d = args[0]
            self._ensure_in_jail(test_case, d)
        else:
            # The test "home" directory is the root of its jail
            d = self._get_jail_root(test_case)
        os.chdir(d)
        return 0, None, None

    def do_mkdir(self, test_case, input, args):
        if not args or len(args) != 1:
            raise SyntaxError("Usage: mkdir dir")
        d = args[0]
        self._ensure_in_jail(test_case, d)
        os.mkdir(d)
        return 0, None, None

    def do_rm(self, test_case, input, args):
        err = None

        def error(msg, path):
            return "rm: cannot remove '{}': {}\n".format(path, msg)

        force, recursive = False, False
        opts = None
        if args and args[0][0] == "-":
            opts = args.pop(0)[1:]
            if "f" in opts:
                force = True
                opts = opts.replace("f", "", 1)
            if "r" in opts:
                recursive = True
                opts = opts.replace("r", "", 1)
        if not args or opts:
            raise SyntaxError("Usage: rm [-fr] path+")
        for p in args:
            self._ensure_in_jail(test_case, p)
            # FIXME: Should we put that in osutils ?
            try:
                os.remove(p)
            except OSError as e:
                # Various OSes raises different exceptions (linux: EISDIR,
                #   win32: EACCES, OSX: EPERM) when invoked on a directory
                if e.errno in (errno.EISDIR, errno.EPERM, errno.EACCES):
                    if recursive:
                        osutils.rmtree(p)
                    else:
                        err = error("Is a directory", p)
                        break
                elif e.errno == errno.ENOENT:
                    if not force:
                        err = error("No such file or directory", p)
                        break
                else:
                    raise
        if err:
            retcode = 1
        else:
            retcode = 0
        return retcode, None, err

    def do_mv(self, test_case, input, args):
        err = None

        def error(msg, src, dst):
            return "mv: cannot move {} to {}: {}\n".format(src, dst, msg)

        if not args or len(args) != 2:
            raise SyntaxError("Usage: mv path1 path2")
        src, dst = args
        try:
            real_dst = dst
            if os.path.isdir(dst):
                real_dst = os.path.join(dst, os.path.basename(src))
            os.rename(src, real_dst)
        except OSError as e:
            if e.errno == errno.ENOENT:
                err = error("No such file or directory", src, dst)
            else:
                raise
        if err:
            retcode = 1
        else:
            retcode = 0
        return retcode, None, err


class TestCaseWithMemoryTransportAndScript(tests.TestCaseWithMemoryTransport):
    """Helper class to experiment shell-like test and memory fs.

    This not intended to be used outside of experiments in implementing memoy
    based file systems and evolving bzr so that test can use only memory based
    resources.
    """

    def setUp(self):
        super().setUp()
        self.script_runner = ScriptRunner()
        # FIXME: See shelf_ui.Shelver._char_based. This allow using shelve in
        # scripts while providing a line-based input (better solution in
        # progress). -- vila 2011-09-28
        self.overrideEnv("INSIDE_EMACS", "1")

    def run_script(self, script, null_output_matches_anything=False):
        return self.script_runner.run_script(
            self, script, null_output_matches_anything=null_output_matches_anything
        )

    def run_command(self, cmd, input, output, error):
        return self.script_runner.run_command(self, cmd, input, output, error)


class TestCaseWithTransportAndScript(tests.TestCaseWithTransport):
    """Helper class to quickly define shell-like tests.

    Can be used as:

    from breezy.tests import script


    class TestBug(script.TestCaseWithTransportAndScript):

        def test_bug_nnnnn(self):
            self.run_script('''
            $ brz init
            $ brz do-this
            # Boom, error
            ''')
    """

    def setUp(self):
        super().setUp()
        self.script_runner = ScriptRunner()
        # FIXME: See shelf_ui.Shelver._char_based. This allow using shelve in
        # scripts while providing a line-based input (better solution in
        # progress). -- vila 2011-09-28
        self.overrideEnv("INSIDE_EMACS", "1")

    def run_script(self, script, null_output_matches_anything=False):
        return self.script_runner.run_script(
            self, script, null_output_matches_anything=null_output_matches_anything
        )

    def run_command(self, cmd, input, output, error):
        return self.script_runner.run_command(self, cmd, input, output, error)


def run_script(test_case, script_string, null_output_matches_anything=False):
    """Run the given script within a testcase."""
    return ScriptRunner().run_script(
        test_case,
        script_string,
        null_output_matches_anything=null_output_matches_anything,
    )
