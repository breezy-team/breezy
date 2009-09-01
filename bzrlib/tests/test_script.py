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


