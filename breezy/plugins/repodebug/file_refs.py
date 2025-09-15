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

"""Command for finding file references in repository inventories."""

from ... import commands, controldir, errors


class cmd_file_refs(commands.Command):
    """Find the inventories that reference a particular version of a text."""

    __doc__ = """Find the inventories that reference a particular version of a text."""

    hidden = True
    takes_args = ["file_id", "rev_id"]
    takes_options = ["directory"]

    def run(self, file_id, rev_id, directory="."):
        """Execute the file_refs command.

        Args:
            file_id: File ID to search for.
            rev_id: Revision ID to search for.
            directory: Working directory (defaults to current directory).
        """
        file_id = file_id.encode()
        rev_id = rev_id.encode()
        bd, _relpath = controldir.ControlDir.open_containing(directory)
        repo = bd.find_repository()
        self.add_cleanup(repo.lock_read().unlock)
        inv_vf = repo.inventories
        all_invs = [k[-1] for k in inv_vf.keys()]
        # print len(all_invs)
        for inv in repo.iter_inventories(all_invs, "unordered"):
            try:
                entry = inv.get_entry(file_id)
            except errors.NoSuchId:
                # This file doesn't even appear in this inv.
                continue
            if entry.revision == rev_id:
                self.outf.write(inv.revision_id + b"\n")
