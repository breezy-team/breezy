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
        self.assertEquals([(['cat', '>file'], ['content\n'], None, None)],
                           script._script_to_commands('cat >file\n<content\n'))

    def test_command_with_output(self):
        story = """
bzr add
>adding file
"""
        self.assertEquals([(['bzr', 'add'], None, ['adding file\n'], None)],
                          script._script_to_commands(story))

    def test_command_with_error(self):
        story = """
bzr branch foo
2>bzr: ERROR: Not a branch: "foo"
"""
        self.assertEquals([(['bzr', 'branch', 'foo'],
                            None, None, ['bzr: ERROR: Not a branch: "foo"\n'])],
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


class TestScriptExecution(script.TestCaseWithScript):

    def test_unknown_command(self):
        self.assertRaises(SyntaxError, self.run_script, 'foo')


class TestCat(script.TestCaseWithScript):

    def test_cat_usage(self):
        self.assertRaises(SyntaxError, self.run_script, 'cat foo bar baz')

    def test_cat_input_to_output(self):
        out, err = self.run_command(['cat'], ['content\n'], ['content\n'], None)

    def test_cat_file_to_output(self):
        self.build_tree_contents([('file', 'content\n')])
        out, err = self.run_command(['cat', 'file'], None, ['content\n'], None)

    def test_cat_input_to_file(self):
        out, err = self.run_command(['cat', '>file'], ['content\n'], None, None)
        self.assertFileEqual('content\n', 'file')

    def test_cat_file_to_file(self):
        self.build_tree_contents([('file', 'content\n')])
        out, err = self.run_command(['cat', 'file', '>file2'], None, None, None)
        self.assertFileEqual('content\n', 'file2')


class TestMkdir(script.TestCaseWithScript):

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


class TestCd(script.TestCaseWithScript):

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
