# Copyright (C) 2007 Canonical Ltd
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Unit tests for the bzrlib.help module."""

from cStringIO import StringIO

from bzrlib import (
    commands,
    help,
    tests,
    )


class TestCommandHelp(tests.TestCase):
    """Tests for help on commands."""

    def test_command_help_includes_see_also(self):
        class cmd_WithSeeAlso(commands.Command):
            """A sample command."""
            _see_also = ['foo', 'bar']
        cmd = cmd_WithSeeAlso()
        helpfile = StringIO()
        help.help_on_command_object(cmd, 'cmd_sample', helpfile)
        self.assertEqual('usage: bzr WithSeeAlso\n'
            '\n'
            'A sample command.\n'
            '\n'
            'Options:\n'
            '  -h, --help  show help message\n'
            '\n'
            'See also: bar, foo\n',
            helpfile.getvalue())
