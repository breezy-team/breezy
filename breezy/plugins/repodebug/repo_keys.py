# Copyright (C) 2011 Canonical Ltd
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

"""Repository debugging command for dumping versioned file keys.

This module provides a command to inspect and dump the keys stored in a
repository's versioned files, which is useful for debugging repository
internals.
"""

from ... import controldir
from ...commands import Command


class cmd_repo_keys(Command):
    """Dump the keys in a repository's versioned file.

    e.g.::

        bzr repokeys . texts
    """

    hidden = True
    takes_args = ["repo_location", "versioned_file"]

    def run(self, repo_location, versioned_file):
        """Execute the repo-keys command.

        Args:
            repo_location: Path to the repository location.
            versioned_file: Name of the versioned file attribute in the repository
                (e.g., 'texts', 'inventories', 'revisions').
        """
        repo = controldir.ControlDir.open(repo_location).open_repository()
        with repo.lock_read():
            vf = getattr(repo, versioned_file)
            for key in sorted(vf.keys()):
                self.outf.write(repr(key) + "\n")
