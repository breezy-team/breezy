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

from ... import controldir
from ...bzr import static_tuple
from ...commands import Command


class cmd_chk_used_by(Command):
    __doc__ = """Find the inventories/revisions that reference a CHK."""

    hidden = True
    takes_args = ["key*"]
    takes_options = ["directory"]

    def run(self, key_list, directory="."):
        key_list = [static_tuple.StaticTuple(k) for k in key_list]
        if len(key_list) > 1:
            key_list = frozenset(key_list)
        bd, relpath = controldir.ControlDir.open_containing(directory)
        repo = bd.find_repository()
        self.add_cleanup(repo.lock_read().unlock)
        inv_vf = repo.inventories
        all_invs = [k[-1] for k in inv_vf.keys()]
        # print len(all_invs)
        for inv in repo.iter_inventories(all_invs):
            if inv.id_to_entry.key() in key_list:
                self.outf.write(
                    "id_to_entry of {} -> {}\n".format(
                        inv.revision_id,
                        inv.id_to_entry.key(),
                    )
                )
            if inv.parent_id_basename_to_file_id.key() in key_list:
                self.outf.write(
                    "parent_id_basename_to_file_id of {} -> {}\n".format(
                        inv.revision_id,
                        inv.parent_id_basename_to_file_id.key(),
                    )
                )
