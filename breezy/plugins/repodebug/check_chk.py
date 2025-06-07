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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Check each CHK page to make sure it is in 'canonical' form."""

from bzrformats import chk_map, groupcompress

from ... import commands, controldir, trace, transport, ui


class cmd_check_chk(commands.Command):
    """Check the CHK pages for canonical form."""

    hidden = True
    takes_options = ["directory", "revision"]

    def run(self, directory=".", revision=None):
        wt, branch, relpath = controldir.ControlDir.open_containing_tree_or_branch(
            directory
        )
        factory = groupcompress.make_pack_factory(False, False, 1)
        t = transport.get_transport("memory:///")
        vf = factory(t)
        self.add_cleanup(branch.lock_read().unlock)
        repo = branch.repository
        if revision is None or len(revision) == 0:
            inv_keys = repo.inventories.keys()
            inv_ids = [k[-1] for k in inv_keys]
        elif len(revision) == 1:
            inv_ids = [revision[0].as_revision_id(branch)]
        elif len(revision) == 2:
            g = repo.get_graph()
            r1 = revision[0].as_revision_id(branch)
            r2 = revision[1].as_revision_id(branch)
            inv_ids = g.find_unique_ancestors(r2, [r1])
        with ui.ui_factory.nested_progress_bar() as pb:
            for idx, inv in enumerate(repo.iter_inventories(inv_ids)):
                pb.update("checking", idx, len(inv_ids))
                d = dict(inv.id_to_entry.iteritems())
                test_key = chk_map.CHKMap.from_dict(
                    vf,
                    d,
                    maximum_size=inv.id_to_entry._root_node._maximum_size,
                    key_width=inv.id_to_entry._root_node._key_width,
                    search_key_func=inv.id_to_entry._search_key_func,
                )
                if inv.id_to_entry.key() != test_key:
                    trace.warning(f"Failed for id_to_entry inv: {inv.revision_id}")
                pid = inv.parent_id_basename_to_file_id
                d = dict(pid.iteritems())
                test_key = chk_map.CHKMap.from_dict(
                    vf,
                    d,
                    maximum_size=pid._root_node._maximum_size,
                    key_width=pid._root_node._key_width,
                    search_key_func=pid._search_key_func,
                )
                if pid.key() != test_key:
                    trace.warning(
                        f"Failed for parent_id_to_basename inv: {inv.revision_id}"
                    )
