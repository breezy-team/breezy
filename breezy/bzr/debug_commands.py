# Copyright (C) 2005-2012 Canonical Ltd
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

"""Debug commands for the bzr formats."""

from bzrformats.errors import NotVersionedError

from .. import osutils
from ..commands import Command, display_command
from ..workingtree import WorkingTree


class cmd_file_id(Command):
    """Command to print file_id of a file or directory."""

    __doc__ = """Print file_id of a particular file or directory.

    The file_id is assigned when the file is first added and remains the
    same through all revisions where the file exists, even when it is
    moved or renamed.
    """

    hidden = True
    _see_also = ["inventory", "ls"]
    takes_args = ["filename"]

    @display_command
    def run(self, filename):
        """Execute the file_id command."""
        tree, relpath = WorkingTree.open_containing(filename)
        file_id = tree.path2id(relpath)
        if file_id is None:
            raise NotVersionedError(filename)
        else:
            self.outf.write(file_id.decode("utf-8") + "\n")


class cmd_file_path(Command):
    """Command to print path of file_ids to a file or directory."""

    __doc__ = """Print path of file_ids to a file or directory.

    This prints one line for each directory down to the target,
    starting at the branch root.
    """

    hidden = True
    takes_args = ["filename"]

    @display_command
    def run(self, filename):
        """Execute the file_path command."""
        tree, relpath = WorkingTree.open_containing(filename)
        fid = tree.path2id(relpath)
        if fid is None:
            raise NotVersionedError(filename)
        segments = osutils.splitpath(relpath)
        for pos in range(1, len(segments) + 1):
            path = osutils.joinpath(segments[:pos])
            self.outf.write(f"{tree.path2id(path)}\n")
