# Copyright (C) 2010-2011 Canonical Ltd
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

"""Command to find inventories/revisions that reference a CHK."""

from ... import controldir
from ...commands import Command


class cmd_chk_used_by(Command):
    """Find the inventories/revisions that reference a CHK."""

    __doc__ = """Find the inventories/revisions that reference a CHK."""

    hidden = True
    takes_args = ["key*"]
    takes_options = ["directory"]

    def run(self, key_list, directory="."):
        """Execute the chk-used-by command.

        Args:
            key_list: List of CHK keys to search for.
            directory: Directory containing the repository to search.
        """
        key_list = [(k,) for k in key_list]
        if len(key_list) > 1:
            key_list = frozenset(key_list)
        bd, _relpath = controldir.ControlDir.open_containing(directory)
        repo = bd.find_repository()
        self.add_cleanup(repo.lock_read().unlock)
        inv_vf = repo.inventories
        all_invs = [k[-1] for k in inv_vf.keys()]
        # print len(all_invs)
        for inv in repo.iter_inventories(all_invs):
            if inv.id_to_entry.key() in key_list:
                self.outf.write(
                    f"id_to_entry of {inv.revision_id} -> {inv.id_to_entry.key()}\n"
                )
            if inv.parent_id_basename_to_file_id.key() in key_list:
                self.outf.write(
                    f"parent_id_basename_to_file_id of {inv.revision_id} -> {inv.parent_id_basename_to_file_id.key()}\n"
                )
