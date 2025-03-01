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

# TODO: Perhaps rather than mapping options and arguments back and
# forth, we should just pass in the whole argv, and allow
# ExternalCommands to handle it differently to internal commands?


import os

from .commands import Command


class ExternalCommand(Command):
    """Class to wrap external commands."""

    @classmethod
    def find_command(cls, cmd):
        import os.path

        bzrpath = os.environ.get("BZRPATH", "")

        for dir in bzrpath.split(os.pathsep):
            # Empty directories are not real paths
            if not dir:
                continue
            # This needs to be os.path.join() or windows cannot
            # find the batch file that you are wanting to execute
            path = os.path.join(dir, cmd)
            if os.path.isfile(path):
                return ExternalCommand(path)

        return None

    def __init__(self, path):
        self.path = path

    def name(self):
        return os.path.basename(self.path)

    def run(self, *args, **kwargs):
        raise NotImplementedError("should not be called on {!r}".format(self))

    def run_argv_aliases(self, argv, alias_argv=None):
        return os.spawnv(os.P_WAIT, self.path, [self.path] + argv)

    def help(self):
        m = "external command from {}\n\n".format(self.path)
        pipe = os.popen("{} --help".format(self.path))
        return m + pipe.read()
