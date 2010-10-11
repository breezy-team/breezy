# Copyright (C) 2009, 2010 Canonical Ltd
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


from bzrlib import (
    commands,
    osutils,
    tests,
    trace,
    ui,
    )
from bzrlib.tests import script


class TestSyntax(tests.TestCase):

    def test_comment_is_ignored(self):
        self.assertEquals([], script._script_to_commands('#comment\n'))

    def test_comment_multiple_lines(self):
        self.assertEquals([
            (['bar'], None, None, None),
            ],
            script._script_to_commands("""
            # this comment is ignored
            # so is this
            # no we run bar
            $ bar
            """))

    def test_trim_blank_lines(self):
        """Blank lines are respected, but trimmed at the start and end.

        Python triple-quoted syntax is going to give stubby/empty blank lines 
        right at the start and the end.  These are cut off so that callers don't 
        need special syntax to avoid them.

        However we do want to be able to match commands that emit blank lines.
        """
        self.assertEquals([
            (['bar'], None, '\n', None),
            ],
            script._script_to_commands("""
            $bar

            """))

    def test_simple_command(self):
        self.assertEquals([(['cd', 'trunk'], None, None, None)],
                           script._script_to_commands('$ cd trunk'))

    def test_command_with_single_quoted_param(self):
        story = """$ bzr commit -m 'two words'"""
        self.assertEquals([(['bzr', 'commit', '-m', "'two words'"],
                            None, None, None)],
                           script._script_to_commands(story))

    def test_command_with_double_quoted_param(self):
        story = """$ bzr commit -m "two words" """
        self.assertEquals([(['bzr', 'commit', '-m', '"two words"'],
                            None, None, None)],
                           script._script_to_commands(story))

    def test_command_with_input(self):
        self.assertEquals(
            [(['cat', '>file'], 'content\n', None, None)],
            script._script_to_commands('$ cat >file\n<content\n'))

    def test_indented(self):
        # scripts are commonly given indented within the test source code, and
        # common indentation is stripped off
        story = """
            $ bzr add
            adding file
            adding file2
            """
        self.assertEquals([(['bzr', 'add'], None,
                            'adding file\nadding file2\n', None)],
                          script._script_to_commands(story))

    def test_command_with_output(self):
        story = """
$ bzr add
adding file
adding file2
"""
        self.assertEquals([(['bzr', 'add'], None,
                            'adding file\nadding file2\n', None)],
                          script._script_to_commands(story))

    def test_command_with_error(self):
        story = """
$ bzr branch foo
2>bzr: ERROR: Not a branch: "foo"
"""
        self.assertEquals([(['bzr', 'branch', 'foo'],
                            None, None, 'bzr: ERROR: Not a branch: "foo"\n')],
                          script._script_to_commands(story))

    def test_input_without_command(self):
        self.assertRaises(SyntaxError, script._script_to_commands, '<input')

    def test_output_without_command(self):
        self.assertRaises(SyntaxError, script._script_to_commands, '>input')

    def test_command_with_backquotes(self):
        story = """
$ foo = `bzr file-id toto`
"""
        self.assertEquals([(['foo', '=', '`bzr file-id toto`'],
                            None, None, None)],
                          script._script_to_commands(story))


class TestRedirections(tests.TestCase):

    def _check(self, in_name, out_name, out_mode, remaining, args):
        self.assertEqual(script._scan_redirection_options(args),
                         (in_name, out_name, out_mode, remaining))

    def test_no_redirection(self):
        self._check(None, None, None, [], [])
        self._check(None, None, None, ['foo', 'bar'], ['foo', 'bar'])

    def test_input_redirection(self):
        self._check('foo', None, None, [], ['<foo'])
        self._check('foo', None, None, ['bar'], ['bar', '<foo'])
        self._check('foo', None, None, ['bar'], ['bar', '<', 'foo'])
        self._check('foo', None, None, ['bar'], ['<foo', 'bar'])
        self._check('foo', None, None, ['bar', 'baz'], ['bar', '<foo', 'baz'])

    def test_output_redirection(self):
        self._check(None, 'foo', 'wb+', [], ['>foo'])
        self._check(None, 'foo', 'wb+', ['bar'], ['bar', '>foo'])
        self._check(None, 'foo', 'wb+', ['bar'], ['bar', '>', 'foo'])
        self._check(None, 'foo', 'ab+', [], ['>>foo'])
        self._check(None, 'foo', 'ab+', ['bar'], ['bar', '>>foo'])
        self._check(None, 'foo', 'ab+', ['bar'], ['bar', '>>', 'foo'])

    def test_redirection_syntax_errors(self):
        self._check('', None, None, [], ['<'])
        self._check(None, '', 'wb+', [], ['>'])
        self._check(None, '', 'ab+', [], ['>>'])
        self._check('>', '', 'ab+', [], ['<', '>', '>>'])



class TestExecution(script.TestCaseWithTransportAndScript):

    def test_unknown_command(self):
        self.assertRaises(SyntaxError, self.run_script, 'foo')

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
$ bzr not-a-command
"""
        self.assertRaises(AssertionError, self.run_script, story)

    def test_continue_on_expected_error(self):
        story = """
$ bzr not-a-command
2>..."not-a-command"
"""
        self.run_script(story)

    def test_continue_on_error_output(self):
        # The status matters, not the output
        story = """
$ bzr init
$ cat >file
<Hello
$ bzr add file
$ bzr commit -m 'adding file'
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
$ bzr not-a-command
2>..."not-a-command"
"""
        self.run_script(story)

        story = """
$ bzr branch not-a-branch
2>bzr: ERROR: Not a branch...not-a-branch/".
"""
        self.run_script(story)


class TestArgumentProcessing(script.TestCaseWithTransportAndScript):

    def test_globing(self):
        self.run_script("""
$ echo cat >cat
$ echo dog >dog
$ cat *
cat
dog
""")

    def test_quoted_globbing(self):
        self.run_script("""
$ echo cat >cat
$ cat '*'
2>*: No such file or directory
""")

    def test_quotes_removal(self):
        self.run_script("""
$ echo 'cat' "dog" '"chicken"' "'dragon'"
cat dog "chicken" 'dragon'
""")

    def test_verbosity_isolated(self):
        """Global verbosity is isolated from commands run in scripts.
        """
        # see also 656694; we should get rid of global verbosity
        self.run_script("""
        $ bzr init --quiet a
        """)
        self.assertEquals(trace.is_quiet(), False)


class TestCat(script.TestCaseWithTransportAndScript):

    def test_cat_usage(self):
        self.assertRaises(SyntaxError, self.run_script, 'cat foo <bar')

    def test_cat_input_to_output(self):
        retcode, out, err = self.run_command(['cat'],
                                             'content\n', 'content\n', None)
        self.assertEquals('content\n', out)
        self.assertEquals(None, err)

    def test_cat_file_to_output(self):
        self.build_tree_contents([('file', 'content\n')])
        retcode, out, err = self.run_command(['cat', 'file'],
                                             None, 'content\n', None)
        self.assertEquals('content\n', out)
        self.assertEquals(None, err)

    def test_cat_input_to_file(self):
        retcode, out, err = self.run_command(['cat', '>file'],
                                             'content\n', None, None)
        self.assertFileEqual('content\n', 'file')
        self.assertEquals(None, out)
        self.assertEquals(None, err)
        retcode, out, err = self.run_command(['cat', '>>file'],
                                             'more\n', None, None)
        self.assertFileEqual('content\nmore\n', 'file')
        self.assertEquals(None, out)
        self.assertEquals(None, err)

    def test_cat_file_to_file(self):
        self.build_tree_contents([('file', 'content\n')])
        retcode, out, err = self.run_command(['cat', 'file', '>file2'],
                                             None, None, None)
        self.assertFileEqual('content\n', 'file2')

    def test_cat_files_to_file(self):
        self.build_tree_contents([('cat', 'cat\n')])
        self.build_tree_contents([('dog', 'dog\n')])
        retcode, out, err = self.run_command(['cat', 'cat', 'dog', '>file'],
                                             None, None, None)
        self.assertFileEqual('cat\ndog\n', 'file')

    def test_cat_bogus_input_file(self):
        self.run_script("""
$ cat <file
2>file: No such file or directory
""")

    def test_cat_bogus_output_file(self):
        self.run_script("""
$ cat >
2>: No such file or directory
""")

    def test_echo_bogus_output_file(self):
        # We need a backing file sysytem for that test so it can't be in
        # TestEcho
        self.run_script("""
$ echo >
2>: No such file or directory
""")


class TestMkdir(script.TestCaseWithTransportAndScript):

    def test_mkdir_usage(self):
        self.assertRaises(SyntaxError, self.run_script, '$ mkdir')
        self.assertRaises(SyntaxError, self.run_script, '$ mkdir foo bar')

    def test_mkdir_jailed(self):
        self.assertRaises(ValueError, self.run_script, '$ mkdir /out-of-jail')
        self.assertRaises(ValueError, self.run_script, '$ mkdir ../out-of-jail')

    def test_mkdir_in_jail(self):
        self.run_script("""
$ mkdir dir
$ cd dir
$ mkdir ../dir2
$ cd ..
""")
        self.failUnlessExists('dir')
        self.failUnlessExists('dir2')


class TestCd(script.TestCaseWithTransportAndScript):

    def test_cd_usage(self):
        self.assertRaises(SyntaxError, self.run_script, '$ cd foo bar')

    def test_cd_out_of_jail(self):
        self.assertRaises(ValueError, self.run_script, '$ cd /out-of-jail')
        self.assertRaises(ValueError, self.run_script, '$ cd ..')

    def test_cd_dir_and_back_home(self):
        self.assertEquals(self.test_dir, osutils.getcwd())
        self.run_script("""
$ mkdir dir
$ cd dir
""")
        self.assertEquals(osutils.pathjoin(self.test_dir, 'dir'),
                          osutils.getcwd())

        self.run_script('$ cd')
        self.assertEquals(self.test_dir, osutils.getcwd())


class TestBzr(script.TestCaseWithTransportAndScript):

    def test_bzr_smoke(self):
        self.run_script('$ bzr init branch')
        self.failUnlessExists('branch')


class TestEcho(script.TestCaseWithMemoryTransportAndScript):

    def test_echo_usage(self):
        story = """
$ echo foo
<bar
"""
        self.assertRaises(SyntaxError, self.run_script, story)

    def test_echo_input(self):
        self.assertRaises(SyntaxError, self.run_script, """
            $ echo <foo
            """)

    def test_echo_to_output(self):
        retcode, out, err = self.run_command(['echo'], None, '\n', None)
        self.assertEquals('\n', out)
        self.assertEquals(None, err)

    def test_echo_some_to_output(self):
        retcode, out, err = self.run_command(['echo', 'hello'],
                                             None, 'hello\n', None)
        self.assertEquals('hello\n', out)
        self.assertEquals(None, err)

    def test_echo_more_output(self):
        retcode, out, err = self.run_command(
            ['echo', 'hello', 'happy', 'world'],
            None, 'hello happy world\n', None)
        self.assertEquals('hello happy world\n', out)
        self.assertEquals(None, err)

    def test_echo_appended(self):
        retcode, out, err = self.run_command(['echo', 'hello', '>file'],
                                             None, None, None)
        self.assertEquals(None, out)
        self.assertEquals(None, err)
        self.assertFileEqual('hello\n', 'file')
        retcode, out, err = self.run_command(['echo', 'happy', '>>file'],
                                             None, None, None)
        self.assertEquals(None, out)
        self.assertEquals(None, err)
        self.assertFileEqual('hello\nhappy\n', 'file')

    def test_empty_line_in_output_is_respected(self):
        self.run_script("""
            $ echo

            $ echo bar
            bar
            """)


class TestRm(script.TestCaseWithTransportAndScript):

    def test_rm_usage(self):
        self.assertRaises(SyntaxError, self.run_script, '$ rm')
        self.assertRaises(SyntaxError, self.run_script, '$ rm -ff foo')

    def test_rm_file(self):
        self.run_script('$ echo content >file')
        self.failUnlessExists('file')
        self.run_script('$ rm file')
        self.failIfExists('file')

    def test_rm_file_force(self):
        self.failIfExists('file')
        self.run_script('$ rm -f file')
        self.failIfExists('file')

    def test_rm_files(self):
        self.run_script("""
$ echo content >file
$ echo content >file2
""")
        self.failUnlessExists('file2')
        self.run_script('$ rm file file2')
        self.failIfExists('file2')

    def test_rm_dir(self):
        self.run_script('$ mkdir dir')
        self.failUnlessExists('dir')
        self.run_script("""
$ rm dir
2>rm: cannot remove 'dir': Is a directory
""")
        self.failUnlessExists('dir')

    def test_rm_dir_recursive(self):
        self.run_script("""
$ mkdir dir
$ rm -r dir
""")
        self.failIfExists('dir')


class TestMv(script.TestCaseWithTransportAndScript):

    def test_usage(self):
        self.assertRaises(SyntaxError, self.run_script, '$ mv')
        self.assertRaises(SyntaxError, self.run_script, '$ mv f')
        self.assertRaises(SyntaxError, self.run_script, '$ mv f1 f2 f3')

    def test_move_file(self):
        self.run_script('$ echo content >file')
        self.failUnlessExists('file')
        self.run_script('$ mv file new_name')
        self.failIfExists('file')
        self.failUnlessExists('new_name')

    def test_move_unknown_file(self):
        self.assertRaises(AssertionError,
                          self.run_script, '$ mv unknown does-not-exist')

    def test_move_dir(self):
        self.run_script("""
$ mkdir dir
$ echo content >dir/file
""")
        self.run_script('$ mv dir new_name')
        self.failIfExists('dir')
        self.failUnlessExists('new_name')
        self.failUnlessExists('new_name/file')

    def test_move_file_into_dir(self):
        self.run_script("""
$ mkdir dir
$ echo content > file
""")
        self.run_script('$ mv file dir')
        self.failUnlessExists('dir')
        self.failIfExists('file')
        self.failUnlessExists('dir/file')


class cmd_test_confirm(commands.Command):

    def run(self):
        if ui.ui_factory.get_boolean(
            'Really do it',
            # 'bzrlib.tests.test_script.confirm',
            # {}
            ):
            self.outf.write('Do it!\n')
        else:
            print 'ok, no'


class TestUserInteraction(script.TestCaseWithMemoryTransportAndScript):

    def test_confirm_action(self):
        """You can write tests that demonstrate user confirmation.
        
        Specifically, ScriptRunner does't care if the output line for the prompt
        isn't terminated by a newline from the program; it's implicitly terminated 
        by the input.
        """
        commands.builtin_command_registry.register(cmd_test_confirm)
        self.addCleanup(commands.builtin_command_registry.remove, 'test-confirm')
        self.run_script("""
            $ bzr test-confirm
            2>Really do it? [y/n]: 
            <yes
            Do it!
            $ bzr test-confirm
            2>Really do it? [y/n]: 
            <no
            ok, no
            """)

