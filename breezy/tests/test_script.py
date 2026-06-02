# Copyright (C) 2009, 2010, 2011, 2016 Canonical Ltd
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


from breezy import commands, osutils, tests, trace, ui
from breezy.tests import script


class TestSyntax(tests.TestCase):
    def test_comment_is_ignored(self):
        self.assertEqual([], script._script_to_commands("#comment\n"))

    def test_comment_multiple_lines(self):
        self.assertEqual(
            [
                (["bar"], None, None, None),
            ],
            script._script_to_commands(
                """
            # this comment is ignored
            # so is this
            # no we run bar
            $ bar
            """
            ),
        )

    def test_trim_blank_lines(self):
        """Blank lines are respected, but trimmed at the start and end.

        Python triple-quoted syntax is going to give stubby/empty blank lines
        right at the start and the end.  These are cut off so that callers don't
        need special syntax to avoid them.

        However we do want to be able to match commands that emit blank lines.
        """
        self.assertEqual(
            [
                (["bar"], None, "\n", None),
            ],
            script._script_to_commands(
                """
            $bar

            """
            ),
        )

    def test_simple_command(self):
        self.assertEqual(
            [(["cd", "trunk"], None, None, None)],
            script._script_to_commands("$ cd trunk"),
        )

    def test_command_with_single_quoted_param(self):
        story = """$ brz commit -m 'two words'"""
        self.assertEqual(
            [(["brz", "commit", "-m", "'two words'"], None, None, None)],
            script._script_to_commands(story),
        )

    def test_command_with_double_quoted_param(self):
        story = """$ brz commit -m "two words" """
        self.assertEqual(
            [(["brz", "commit", "-m", '"two words"'], None, None, None)],
            script._script_to_commands(story),
        )

    def test_command_with_input(self):
        self.assertEqual(
            [(["cat", ">file"], "content\n", None, None)],
            script._script_to_commands("$ cat >file\n<content\n"),
        )

    def test_indented(self):
        # scripts are commonly given indented within the test source code, and
        # common indentation is stripped off
        story = """
            $ brz add
            adding file
            adding file2
            """
        self.assertEqual(
            [(["brz", "add"], None, "adding file\nadding file2\n", None)],
            script._script_to_commands(story),
        )

    def test_command_with_output(self):
        story = """
$ brz add
adding file
adding file2
"""
        self.assertEqual(
            [(["brz", "add"], None, "adding file\nadding file2\n", None)],
            script._script_to_commands(story),
        )

    def test_command_with_error(self):
        story = """
$ brz branch foo
2>brz: ERROR: Not a branch: "foo"
"""
        self.assertEqual(
            [
                (
                    ["brz", "branch", "foo"],
                    None,
                    None,
                    'brz: ERROR: Not a branch: "foo"\n',
                )
            ],
            script._script_to_commands(story),
        )

    def test_input_without_command(self):
        self.assertRaises(SyntaxError, script._script_to_commands, "<input")

    def test_output_without_command(self):
        self.assertRaises(SyntaxError, script._script_to_commands, ">input")

    def test_command_with_backquotes(self):
        story = """
$ foo = `brz file-id toto`
"""
        self.assertEqual(
            [(["foo", "=", "`brz file-id toto`"], None, None, None)],
            script._script_to_commands(story),
        )


class TestRedirections(tests.TestCase):
    def _check(self, in_name, out_name, out_mode, remaining, args):
        self.assertEqual(
            script._scan_redirection_options(args),
            (in_name, out_name, out_mode, remaining),
        )

    def test_no_redirection(self):
        self._check(None, None, None, [], [])
        self._check(None, None, None, ["foo", "bar"], ["foo", "bar"])

    def test_input_redirection(self):
        self._check("foo", None, None, [], ["<foo"])
        self._check("foo", None, None, ["bar"], ["bar", "<foo"])
        self._check("foo", None, None, ["bar"], ["bar", "<", "foo"])
        self._check("foo", None, None, ["bar"], ["<foo", "bar"])
        self._check("foo", None, None, ["bar", "baz"], ["bar", "<foo", "baz"])

    def test_output_redirection(self):
        self._check(None, "foo", "w+", [], [">foo"])
        self._check(None, "foo", "w+", ["bar"], ["bar", ">foo"])
        self._check(None, "foo", "w+", ["bar"], ["bar", ">", "foo"])
        self._check(None, "foo", "a+", [], [">>foo"])
        self._check(None, "foo", "a+", ["bar"], ["bar", ">>foo"])
        self._check(None, "foo", "a+", ["bar"], ["bar", ">>", "foo"])

    def test_redirection_syntax_errors(self):
        self._check("", None, None, [], ["<"])
        self._check(None, "", "w+", [], [">"])
        self._check(None, "", "a+", [], [">>"])
        self._check(">", "", "a+", [], ["<", ">", ">>"])


class TestExecution(script.TestCaseWithTransportAndScript):
    def test_unknown_command(self):
        """A clear error is reported for commands that aren't recognised.

        Testing the attributes of the SyntaxError instance is equivalent to
        using traceback.format_exception_only and comparing with:
          File "<string>", line 1
            foo --frob
            ^
        SyntaxError: Command not found "foo"
        """
        e = self.assertRaises(SyntaxError, self.run_script, "$ foo --frob")
        self.assertContainsRe(e.msg, "not found.*foo")
        self.assertEqual(e.text, "foo --frob")

    def test_blank_output_mismatches_output(self):
        """If you give output, the output must actually be blank.

        See <https://bugs.launchpad.net/bzr/+bug/637830>: previously blank
        output was a wildcard.  Now you must say ... if you want that.
        """
        self.assertRaises(
            AssertionError,
            self.run_script,
            """
            $ echo foo
            """,
        )

    def test_null_output_matches_option(self):
        """If you want null output to be a wild card, you can pass
        null_output_matches_anything to run_script.
        """
        self.run_script(
            """
            $ echo foo
            """,
            null_output_matches_anything=True,
        )

    def test_ellipsis_everything(self):
        """A simple ellipsis matches everything."""
        self.run_script(
            """
        $ echo foo
        ...
        """
        )

    def test_ellipsis_matches_empty(self):
        self.run_script(
            """
        $ cd .
        ...
        """
        )

    def test_stops_on_unexpected_output(self):
        story = """
$ mkdir dir
$ cd dir
The cd command ouputs nothing
"""
        self.assertRaises(AssertionError, self.run_script, story)

    def test_stops_on_unexpected_error(self):
        story = """
$ cat
<Hello
$ brz not-a-command
"""
        self.assertRaises(AssertionError, self.run_script, story)

    def test_continue_on_expected_error(self):
        story = """
$ brz not-a-command
2>..."not-a-command"
"""
        self.run_script(story)

    def test_continue_on_error_output(self):
        # The status matters, not the output
        story = """
$ brz init
...
$ cat >file
<Hello
$ brz add file
...
$ brz commit -m 'adding file'
2>...
"""
        self.run_script(story)

    def test_ellipsis_output(self):
        story = """
$ cat
<first line
<second line
<last line
first line
...
last line
"""
        self.run_script(story)
        story = """
$ brz not-a-command
2>..."not-a-command"
"""
        self.run_script(story)

        story = """
$ brz branch not-a-branch
2>brz: ERROR: Not a branch...not-a-branch/".
"""
        self.run_script(story)


class TestArgumentProcessing(script.TestCaseWithTransportAndScript):
    def test_globing(self):
        self.run_script(
            """
$ echo cat >cat
$ echo dog >dog
$ cat *
cat
dog
"""
        )

    def test_quoted_globbing(self):
        self.run_script(
            """
$ echo cat >cat
$ cat '*'
2>*: No such file or directory
"""
        )

    def test_quotes_removal(self):
        self.run_script(
            """
$ echo 'cat' "dog" '"chicken"' "'dragon'"
cat dog "chicken" 'dragon'
"""
        )

    def test_verbosity_isolated(self):
        """Global verbosity is isolated from commands run in scripts."""
        # see also 656694; we should get rid of global verbosity
        self.run_script(
            """
        $ brz init --quiet a
        """
        )
        self.assertEqual(trace.is_quiet(), False)


class TestCat(script.TestCaseWithTransportAndScript):
    def test_cat_usage(self):
        self.assertRaises(SyntaxError, self.run_script, "cat foo <bar")

    def test_cat_input_to_output(self):
        _retcode, out, err = self.run_command(["cat"], "content\n", "content\n", None)
        self.assertEqual("content\n", out)
        self.assertEqual(None, err)

    def test_cat_file_to_output(self):
        self.build_tree_contents([("file", b"content\n")])
        _retcode, out, err = self.run_command(["cat", "file"], None, "content\n", None)
        self.assertEqual("content\n", out)
        self.assertEqual(None, err)

    def test_cat_input_to_file(self):
        _retcode, out, err = self.run_command(["cat", ">file"], "content\n", None, None)
        self.assertFileEqual("content\n", "file")
        self.assertEqual(None, out)
        self.assertEqual(None, err)
        _retcode, out, err = self.run_command(["cat", ">>file"], "more\n", None, None)
        self.assertFileEqual("content\nmore\n", "file")
        self.assertEqual(None, out)
        self.assertEqual(None, err)

    def test_cat_file_to_file(self):
        self.build_tree_contents([("file", b"content\n")])
        _retcode, _out, _err = self.run_command(
            ["cat", "file", ">file2"], None, None, None
        )
        self.assertFileEqual(b"content\n", "file2")

    def test_cat_files_to_file(self):
        self.build_tree_contents([("cat", b"cat\n")])
        self.build_tree_contents([("dog", b"dog\n")])
        _retcode, _out, _err = self.run_command(
            ["cat", "cat", "dog", ">file"], None, None, None
        )
        self.assertFileEqual(b"cat\ndog\n", "file")

    def test_cat_bogus_input_file(self):
        self.run_script(
            """
$ cat <file
2>file: No such file or directory
"""
        )

    def test_cat_bogus_output_file(self):
        self.run_script(
            """
$ cat >
2>: No such file or directory
"""
        )

    def test_echo_bogus_output_file(self):
        # We need a backing file sysytem for that test so it can't be in
        # TestEcho
        self.run_script(
            """
$ echo >
2>: No such file or directory
"""
        )


class TestMkdir(script.TestCaseWithTransportAndScript):
    def test_mkdir_usage(self):
        self.assertRaises(SyntaxError, self.run_script, "$ mkdir")
        self.assertRaises(SyntaxError, self.run_script, "$ mkdir foo bar")

    def test_mkdir_jailed(self):
        self.assertRaises(ValueError, self.run_script, "$ mkdir /out-of-jail")
        self.assertRaises(ValueError, self.run_script, "$ mkdir ../out-of-jail")

    def test_mkdir_in_jail(self):
        self.run_script(
            """
$ mkdir dir
$ cd dir
$ mkdir ../dir2
$ cd ..
"""
        )
        self.assertPathExists("dir")
        self.assertPathExists("dir2")


class TestCd(script.TestCaseWithTransportAndScript):
    def test_cd_usage(self):
        self.assertRaises(SyntaxError, self.run_script, "$ cd foo bar")

    def test_cd_out_of_jail(self):
        self.assertRaises(ValueError, self.run_script, "$ cd /out-of-jail")
        self.assertRaises(ValueError, self.run_script, "$ cd ..")

    def test_cd_dir_and_back_home(self):
        self.assertEqual(self.test_dir, osutils.getcwd())
        self.run_script(
            """
$ mkdir dir
$ cd dir
"""
        )
        self.assertEqual(osutils.pathjoin(self.test_dir, "dir"), osutils.getcwd())

        self.run_script("$ cd")
        self.assertEqual(self.test_dir, osutils.getcwd())


class TestBrz(script.TestCaseWithTransportAndScript):
    def test_brz_smoke(self):
        self.run_script(
            """
            $ brz init branch
            Created a standalone tree (format: ...)
            """
        )
        self.assertPathExists("branch")


class TestEcho(script.TestCaseWithMemoryTransportAndScript):
    def test_echo_usage(self):
        story = """
$ echo foo
<bar
"""
        self.assertRaises(SyntaxError, self.run_script, story)

    def test_echo_input(self):
        self.assertRaises(
            SyntaxError,
            self.run_script,
            """
            $ echo <foo
            """,
        )

    def test_echo_to_output(self):
        _retcode, out, err = self.run_command(["echo"], None, "\n", None)
        self.assertEqual("\n", out)
        self.assertEqual(None, err)

    def test_echo_some_to_output(self):
        _retcode, out, err = self.run_command(["echo", "hello"], None, "hello\n", None)
        self.assertEqual("hello\n", out)
        self.assertEqual(None, err)

    def test_echo_more_output(self):
        _retcode, out, err = self.run_command(
            ["echo", "hello", "happy", "world"], None, "hello happy world\n", None
        )
        self.assertEqual("hello happy world\n", out)
        self.assertEqual(None, err)

    def test_echo_appended(self):
        _retcode, out, err = self.run_command(
            ["echo", "hello", ">file"], None, None, None
        )
        self.assertEqual(None, out)
        self.assertEqual(None, err)
        self.assertFileEqual(b"hello\n", "file")
        _retcode, out, err = self.run_command(
            ["echo", "happy", ">>file"], None, None, None
        )
        self.assertEqual(None, out)
        self.assertEqual(None, err)
        self.assertFileEqual(b"hello\nhappy\n", "file")

    def test_empty_line_in_output_is_respected(self):
        self.run_script(
            """
            $ echo

            $ echo bar
            bar
            """
        )


class TestRm(script.TestCaseWithTransportAndScript):
    def test_rm_usage(self):
        self.assertRaises(SyntaxError, self.run_script, "$ rm")
        self.assertRaises(SyntaxError, self.run_script, "$ rm -ff foo")

    def test_rm_file(self):
        self.run_script("$ echo content >file")
        self.assertPathExists("file")
        self.run_script("$ rm file")
        self.assertPathDoesNotExist("file")

    def test_rm_file_force(self):
        self.assertPathDoesNotExist("file")
        self.run_script("$ rm -f file")
        self.assertPathDoesNotExist("file")

    def test_rm_files(self):
        self.run_script(
            """
$ echo content >file
$ echo content >file2
"""
        )
        self.assertPathExists("file2")
        self.run_script("$ rm file file2")
        self.assertPathDoesNotExist("file2")

    def test_rm_dir(self):
        self.run_script("$ mkdir dir")
        self.assertPathExists("dir")
        self.run_script(
            """
$ rm dir
2>rm: cannot remove 'dir': Is a directory
"""
        )
        self.assertPathExists("dir")

    def test_rm_dir_recursive(self):
        self.run_script(
            """
$ mkdir dir
$ rm -r dir
"""
        )
        self.assertPathDoesNotExist("dir")


class TestMv(script.TestCaseWithTransportAndScript):
    def test_usage(self):
        self.assertRaises(SyntaxError, self.run_script, "$ mv")
        self.assertRaises(SyntaxError, self.run_script, "$ mv f")
        self.assertRaises(SyntaxError, self.run_script, "$ mv f1 f2 f3")

    def test_move_file(self):
        self.run_script("$ echo content >file")
        self.assertPathExists("file")
        self.run_script("$ mv file new_name")
        self.assertPathDoesNotExist("file")
        self.assertPathExists("new_name")

    def test_move_unknown_file(self):
        self.assertRaises(
            AssertionError, self.run_script, "$ mv unknown does-not-exist"
        )

    def test_move_dir(self):
        self.run_script(
            """
$ mkdir dir
$ echo content >dir/file
"""
        )
        self.run_script("$ mv dir new_name")
        self.assertPathDoesNotExist("dir")
        self.assertPathExists("new_name")
        self.assertPathExists("new_name/file")

    def test_move_file_into_dir(self):
        self.run_script(
            """
$ mkdir dir
$ echo content > file
"""
        )
        self.run_script("$ mv file dir")
        self.assertPathExists("dir")
        self.assertPathDoesNotExist("file")
        self.assertPathExists("dir/file")


class cmd_test_confirm(commands.Command):
    def run(self):
        if ui.ui_factory.get_boolean(
            "Really do it",
            # 'breezy.tests.test_script.confirm',
            # {}
        ):
            self.outf.write("Do it!\n")
        else:
            print("ok, no")


class TestUserInteraction(script.TestCaseWithMemoryTransportAndScript):
    def test_confirm_action(self):
        """You can write tests that demonstrate user confirmation.

        Specifically, ScriptRunner does't care if the output line for the
        prompt isn't terminated by a newline from the program; it's implicitly
        terminated by the input.
        """
        commands.builtin_command_registry.register(cmd_test_confirm)
        self.addCleanup(commands.builtin_command_registry.remove, "test-confirm")
        self.run_script(
            """
            $ brz test-confirm
            2>Really do it? ([y]es, [n]o): yes
            <y
            Do it!
            $ brz test-confirm
            2>Really do it? ([y]es, [n]o): no
            <n
            ok, no
            """
        )


class TestShelve(script.TestCaseWithTransportAndScript):
    def setUp(self):
        super().setUp()
        self.run_script(
            """
            $ brz init test
            Created a standalone tree (format: 2a)
            $ cd test
            $ echo foo > file
            $ brz add
            adding file
            $ brz commit -m 'file added'
            2>Committing to:...test/
            2>added file
            2>Committed revision 1.
            $ echo bar > file
            """
        )

    def test_shelve(self):
        self.run_script(
            """
            $ brz shelve -m 'shelve bar'
            2>Shelve? ([y]es, [N]o, [f]inish, [q]uit): yes
            <y
            2>Selected changes:
            2> M  file
            2>Shelve 1 change(s)? ([y]es, [N]o, [f]inish, [q]uit): yes
            <y
            2>Changes shelved with id "1".
            """,
            null_output_matches_anything=True,
        )
        self.run_script(
            """
            $ brz shelve --list
              1: shelve bar
            """
        )

    def test_dont_shelve(self):
        # We intentionally provide no input here to test EOF
        self.run_script(
            (
                "$ brz shelve -m 'shelve bar'\n"
                "2>Shelve? ([y]es, [N]o, [f]inish, [q]uit): \n"
                "2>No changes to shelve.\n"
            ),
            null_output_matches_anything=True,
        )
        self.run_script(
            """
            $ brz st
            modified:
              file
            """
        )
