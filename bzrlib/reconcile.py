# (C) 2005, 2006 Canonical Limited.
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

"""Reconcilers are able to fix some potential data errors in a branch."""


import bzrlib.branch
import bzrlib.errors as errors
import bzrlib.progress
from bzrlib.trace import mutter
from bzrlib.tsort import TopoSorter
import bzrlib.ui as ui


def reconcile(dir):
    """Reconcile the data in dir.

    Currently this is limited to a inventory 'reweave'.

    This is a convenience method, for using a Reconciler object.

    Directly using Reconciler is recommended for library users that
    desire fine grained control or analysis of the found issues.
    """
    reconciler = Reconciler(dir)
    reconciler.reconcile()


class Reconciler(object):
    """Reconcilers are used to reconcile existing data.

    Currently this is limited to a single repository, and consists
    of an inventory reweave with revision cross-checks.
    """

    def __init__(self, dir):
        self.bzrdir = dir

    def reconcile(self):
        """Perform reconciliation.
        
        After reconciliation the following attributes document found issues:
        inconsistent_parents: The number of revisions in the repository whose
                              ancestry was being reported incorrectly.
        garbage_inventories: The number of inventory objects without revisions
                             that were garbage collected.
        """
        self.pb = ui.ui_factory.progress_bar()
        self.repo = self.bzrdir.find_repository()
        self.repo.lock_write()
        try:
            self.pb.note('Reconciling repository %s',
                         self.repo.bzrdir.root_transport.base)
            self._reweave_inventory()
        finally:
            self.repo.unlock()
        self.pb.note('Reconciliation complete.')

    def _reweave_inventory(self):
        """Regenerate the inventory weave for the repository from scratch."""
        self.pb.update('Reading inventory data.')
        self.inventory = self.repo.get_inventory_weave()
        # the total set of revisions to process
        self.pending = set([file_id for file_id in self.repo.revision_store])

        # mapping from revision_id to parents
        self._rev_graph = {}
        # errors that we detect
        self.inconsistent_parents = 0
        # we need the revision id of each revision and its available parents list
        self._setup_steps(len(self.pending))
        for rev_id in self.pending:
            # put a revision into the graph.
            self._graph_revision(rev_id)
        # we gc unreferenced inventories too
        self.garbage_inventories = len(self.inventory.names()) \
                                   - len(self._rev_graph)

        if not self.inconsistent_parents and not self.garbage_inventories:
            self.pb.note('Inventory ok.')
            return
        self.pb.update('Backing up inventory...', 0, 0)
        self.repo.control_weaves.put_weave('inventory.backup',
                                           self.inventory,
                                           self.repo.get_transaction())
        self.pb.note('Backup Inventory created.')
        # asking for '' should never return a non-empty weave
        new_inventory = self.repo.control_weaves.get_weave_or_empty('',
            self.repo.get_transaction())

        # we have topological order of revisions and non ghost parents ready.
        self._setup_steps(len(self._rev_graph))
        for rev_id in TopoSorter(self._rev_graph.items()).iter_topo_order():
            parents = self._rev_graph[rev_id]
            # double check this really is in topological order.
            unavailable = [p for p in parents if p not in new_inventory]
            assert len(unavailable) == 0
            # this entry has all the non ghost parents in the inventory
            # file already.
            self._reweave_step('adding inventories')
            new_inventory.add(rev_id, parents, self.inventory.get(rev_id))

        # if this worked, the set of new_inventory.names should equal
        # self.pending
        assert set(new_inventory.names()) == self.pending
        self.pb.update('Writing weave')
        self.repo.control_weaves.put_weave('inventory',
                                           new_inventory,
                                           self.repo.get_transaction())
        self.inventory = None
        self.pb.note('Inventory regenerated.')

    def _setup_steps(self, new_total):
        """Setup the markers we need to control the progress bar."""
        self.total = new_total
        self.count = 0

    def _graph_revision(self, rev_id):
        """Load a revision into the revision graph."""
        # pick a random revision
        # analyse revision id rev_id and put it in the stack.
        self._reweave_step('loading revisions')
        rev = self.repo.get_revision(rev_id)
        assert rev.revision_id == rev_id
        parents = []
        for parent in rev.parent_ids:
            if parent in self.inventory:
                parents.append(parent)
            else:
                mutter('found ghost %s', parent)
        self._rev_graph[rev_id] = parents   
        if set(self.inventory.parent_names(rev_id)) != set(parents):
            self.inconsistent_parents += 1

    def _reweave_step(self, message):
        """Mark a single step of regeneration complete."""
        self.pb.update(message, self.count, self.total)
        self.count += 1
