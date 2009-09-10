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


from bzrlib import (
    osutils,
    tests,
    )
from bzrlib.tests import script


class TestScriptSyntax(tests.TestCase):

    def test_comment_is_ignored(self):
        self.assertEquals([], script._script_to_commands('#comment\n'))

    def test_empty_line_is_ignored(self):
        self.assertEquals([], script._script_to_commands('\n'))

    def test_simple_command(self):
        self.assertEquals([(['cd', 'trunk'], None, None, None)],
                           script._script_to_commands('cd trunk'))

    def test_command_with_single_quoted_param(self):
        story = """bzr commit -m 'two words'"""
        self.assertEquals([(['bzr', 'commit', '-m', 'two words'],
                            None, None, None)],
                           script._script_to_commands(story))

    def test_command_with_double_quoted_param(self):
        story = """bzr commit -m "two words" """
        self.assertEquals([(['bzr', 'commit', '-m', 'two words'],
                            None, None, None)],
                           script._script_to_commands(story))

    def test_command_with_input(self):
        self.assertEquals([(['cat', '>file'], 'content\n', None, None)],
                           script._script_to_commands('cat >file\n<content\n'))

    def test_command_with_output(self):
        story = """
bzr add
>adding file
>adding file2
"""
        self.assertEquals([(['bzr', 'add'], None,
                            'adding file\nadding file2\n', None)],
                          script._script_to_commands(story))

    def test_command_with_error(self):
        story = """
bzr branch foo
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
foo = `bzr file-id toto`
"""
        self.assertEquals([(['foo', '=', '`bzr file-id toto`'],
                            None, None, None)],
                          script._script_to_commands(story))


class TestScriptExecution(script.TestCaseWithTransportAndScript):

    def test_unknown_command(self):
        self.assertRaises(SyntaxError, self.run_script, 'foo')

    def test_stops_on_unexpected_output(self):
        story = """
mkdir dir
cd dir
>The cd command ouputs nothing
"""
        self.assertRaises(AssertionError, self.run_script, story)


    def test_stops_on_unexpected_error(self):
        story = """
cat
<Hello
bzr not-a-command
"""
        self.assertRaises(AssertionError, self.run_script, story)

    def test_continue_on_expected_error(self):
        story = """
bzr not-a-command
2>..."not-a-command"
"""
        self.run_script(story)

    def test_continue_on_error_output(self):
        # The status matters, not the output
        story = """
bzr init
cat >file
<Hello
bzr add file
bzr commit -m 'adding file'
"""
        self.run_script(story)

    def test_ellipsis_output(self):
        story = """
cat
<first line
<second line
<last line
>first line
>...
>last line
"""
        self.run_script(story)
        story = """
bzr not-a-command
2>..."not-a-command"
"""
        self.run_script(story)

        story = """
bzr branch not-a-branch
2>bzr: ERROR: Not a branch...not-a-branch/".
"""
        self.run_script(story)


class TestCat(script.TestCaseWithTransportAndScript):

    def test_cat_usage(self):
        self.assertRaises(SyntaxError, self.run_script, 'cat foo bar baz')
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


class TestMkdir(script.TestCaseWithTransportAndScript):

    def test_mkdir_usage(self):
        self.assertRaises(SyntaxError, self.run_script, 'mkdir')
        self.assertRaises(SyntaxError, self.run_script, 'mkdir foo bar')

    def test_mkdir_jailed(self):
        self.assertRaises(ValueError, self.run_script, 'mkdir /out-of-jail')
        self.assertRaises(ValueError, self.run_script, 'mkdir ../out-of-jail')

    def test_mkdir_in_jail(self):
        self.run_script("""
mkdir dir
cd dir
mkdir ../dir2
cd ..
""")
        self.failUnlessExists('dir')
        self.failUnlessExists('dir2')


class TestCd(script.TestCaseWithTransportAndScript):

    def test_cd_usage(self):
        self.assertRaises(SyntaxError, self.run_script, 'cd foo bar')

    def test_cd_out_of_jail(self):
        self.assertRaises(ValueError, self.run_script, 'cd /out-of-jail')
        self.assertRaises(ValueError, self.run_script, 'cd ..')

    def test_cd_dir_and_back_home(self):
        self.assertEquals(self.test_dir, osutils.getcwd())
        self.run_script("""
mkdir dir
cd dir
""")
        self.assertEquals(osutils.pathjoin(self.test_dir, 'dir'),
                          osutils.getcwd())

        self.run_script('cd')
        self.assertEquals(self.test_dir, osutils.getcwd())


class TestBzr(script.TestCaseWithTransportAndScript):

    def test_bzr_smoke(self):
        self.run_script('bzr init branch')
        self.failUnlessExists('branch')


class TestEcho(script.TestCaseWithMemoryTransportAndScript):

    def test_echo_usage(self):
        story = """
echo foo
<bar
"""
        self.assertRaises(SyntaxError, self.run_script, story)

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
            None, 'hellohappyworld\n', None)
        self.assertEquals('hellohappyworld\n', out)
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


class TestRm(script.TestCaseWithTransportAndScript):

    def test_rm_usage(self):
        self.assertRaises(SyntaxError, self.run_script, 'rm')
        self.assertRaises(SyntaxError, self.run_script, 'rm -ff foo')

    def test_rm_file(self):
        self.run_script('echo content >file')
        self.failUnlessExists('file')
        self.run_script('rm file')
        self.failIfExists('file')

    def test_rm_file_force(self):
        self.failIfExists('file')
        self.run_script('rm -f file')
        self.failIfExists('file')

    def test_rm_files(self):
        self.run_script("""
echo content >file
echo content >file2
""")
        self.failUnlessExists('file2')
        self.run_script('rm file file2')
        self.failIfExists('file2')

    def test_rm_dir(self):
        self.run_script('mkdir dir')
        self.failUnlessExists('dir')
        self.run_script("""
rm dir
2>rm: cannot remove 'dir': Is a directory
""")
        self.failUnlessExists('dir')

    def test_rm_dir_recursive(self):
        self.run_script("""
mkdir dir
rm -r dir
""")
        self.failIfExists('dir')
