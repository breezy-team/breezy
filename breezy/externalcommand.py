# Copyright (C) 2004, 2005 Canonical Ltd
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

"""Support for external commands in Breezy.

This module provides functionality to wrap external commands and execute them
as if they were internal Breezy commands.
"""

# TODO: Perhaps rather than mapping options and arguments back and
# forth, we should just pass in the whole argv, and allow
# ExternalCommands to handle it differently to internal commands?

import os

from ._cmd_rs import commands as _commands_rs
from .commands import Command


class ExternalCommand(Command):
    """Class to wrap external commands."""

    @classmethod
    def find_command(cls, cmd):
        """Find and return an external command if it exists.

        Args:
            cmd: The command name to search for.

        Returns:
            ExternalCommand instance if found, None otherwise.
        """
        # The command is constructed through cls, so a subclass gets instances
        # of itself.
        return _commands_rs.find_external_command(cls, cmd)

    def __init__(self, path):
        """Initialize an ExternalCommand instance.

        Args:
            path: The filesystem path to the external command.
        """
        super().__init__()
        self.path = path

    def name(self):
        """Return the command name.

        Returns:
            The base name of the command path.
        """
        return os.path.basename(self.path)

    def run(self, *args, **kwargs):
        """Run the external command.

        This method should not be called directly on ExternalCommand.

        Raises:
            NotImplementedError: Always, as this method should not be used.
        """
        raise NotImplementedError(f"should not be called on {self!r}")

    def run_argv_aliases(self, argv, alias_argv=None):
        """Execute the external command with given arguments.

        Args:
            argv: List of command-line arguments.
            alias_argv: Unused parameter for compatibility.

        Returns:
            The exit code of the external command, or the negated signal
            number if it was killed by a signal.
        """
        return _commands_rs.spawn_external_command(self.path, argv)

    def help(self):
        """Get help text for the external command.

        Returns:
            Help text from running the command with --help flag.
        """
        m = f"external command from {self.path}\n\n"
        return m + _commands_rs.external_command_help(self.path)
