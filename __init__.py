# Copyright (C) 2010 Canonical Ltd
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

"""Check each CHK page to make sure it is in 'canonical' form.

"""

from bzrlib import (
    commands,
    errors,
    )


class cmd_check_chk(commands.Command):
    """Check the CHK pages for canonical form.
    """

    takes_args = []
    takes_options = ['directory']

    def run(self, directory='.'):
        from bzrlib import (
            bzrdir,
            chk_map,
            groupcompress,
            transport,
            ui,
            )
        # TODO: Some way to restrict the revisions we check
        wt, branch, relpath = bzrdir.BzrDir.open_containing_tree_or_branch(
            directory)
        factory = groupcompress.make_pack_factory(False, False, 1)
        t = transport.get_transport('memory:///')
        vf = factory(t)
        self.add_cleanup(branch.lock_read().unlock)
        repo = branch.repository
        inv_keys = repo.inventories.keys()
        pb = ui.ui_factory.nested_progress_bar()
        self.add_cleanup(pb.finished)
        inv_ids = [k[-1] for k in inv_keys]
        for idx, inv in enumerate(repo.iter_inventories(inv_ids)):
            pb.update('checking', idx, len(inv_ids))
            id_to_entry = inv.id_to_entry
            d = dict(inv.id_to_entry.iteritems())
            test_key = chk_map.CHKMap.from_dict(vf, d,
                maximum_size=inv.id_to_entry._root_node._maximum_size,
                key_width=1,
                search_key_func=inv.id_to_entry._search_key_func)
            if inv.id_to_entry.key() != test_key:
                trace.warning('Failed for inv: %s' % (inv.revision_id,))

commands.register_command(cmd_check_chk)


def load_tests(standard_tests, module, loader):
    standard_tests.addTests(loader.loadTestsFromModuleNames(
        [__name__ + '.' + x for x in [
    ]]))
    return standard_tests
