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


__all__ = ['reconcile', 'Reconciler', 'RepoReconciler']


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
    """Reconcilers are used to reconcile existing data."""

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
        self.pb = ui.ui_factory.nested_progress_bar()
        try:
            self._reconcile()
        finally:
            self.pb.finished()

    def _reconcile(self):
        """Helper function for performing reconciliation."""
        self.repo = self.bzrdir.find_repository()
        self.pb.note('Reconciling repository %s',
                     self.repo.bzrdir.root_transport.base)
        repo_reconciler = RepoReconciler(self.repo)
        repo_reconciler.reconcile()
        self.inconsistent_parents = repo_reconciler.inconsistent_parents
        self.garbage_inventories = repo_reconciler.garbage_inventories
        self.pb.note('Reconciliation complete.')


class RepoReconciler(object):
    """Reconciler that reconciles a repository.

    Currently this consists of an inventory reweave with revision cross-checks.
    """

    def __init__(self, repo):
        self.repo = repo

    def reconcile(self):
        """Perform reconciliation.
        
        After reconciliation the following attributes document found issues:
        inconsistent_parents: The number of revisions in the repository whose
                              ancestry was being reported incorrectly.
        garbage_inventories: The number of inventory objects without revisions
                             that were garbage collected.
        """
        self.repo.lock_write()
        try:
            self.pb = ui.ui_factory.nested_progress_bar()
            try:
                self._reweave_inventory()
            finally:
                self.pb.finished()
        finally:
            self.repo.unlock()

    def _reweave_inventory(self):
        """Regenerate the inventory weave for the repository from scratch."""
        transaction = self.repo.get_transaction()
        self.pb.update('Reading inventory data.')
        self.inventory = self.repo.get_inventory_weave()
        # the total set of revisions to process
        self.pending = set([rev_id for rev_id in self.repo._revision_store.all_revision_ids(transaction)])

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
        self.garbage_inventories = len(self.inventory.versions()) \
                                   - len(self._rev_graph)

        if not self.inconsistent_parents and not self.garbage_inventories:
            self.pb.note('Inventory ok.')
            return
        self.pb.update('Backing up inventory...', 0, 0)
        self.repo.control_weaves.copy(self.inventory, 'inventory.backup', self.repo.get_transaction())
        self.pb.note('Backup Inventory created.')
        # asking for '' should never return a non-empty weave
        new_inventory = self.repo.control_weaves.get_empty('inventory.new',
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
            new_inventory.add_lines(rev_id, parents, self.inventory.get_lines(rev_id))

        # if this worked, the set of new_inventory.names should equal
        # self.pending
        assert set(new_inventory.versions()) == self.pending
        self.pb.update('Writing weave')
        self.repo.control_weaves.copy(new_inventory, 'inventory', self.repo.get_transaction())
        self.repo.control_weaves.delete('inventory.new', self.repo.get_transaction())
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
        rev = self.repo.get_revision_reconcile(rev_id)
        assert rev.revision_id == rev_id
        parents = []
        for parent in rev.parent_ids:
            if self._parent_is_available(parent):
                parents.append(parent)
            else:
                mutter('found ghost %s', parent)
        self._rev_graph[rev_id] = parents   
        if set(self.inventory.get_parents(rev_id)) != set(parents):
            self.inconsistent_parents += 1

    def _parent_is_available(self, parent):
        """True if parent is a fully available revision

        A fully available revision has a inventory and a revision object in the
        repository.
        """
        return (parent in self._rev_graph or 
                (parent in self.inventory and self.repo.has_revision(parent)))

    def _reweave_step(self, message):
        """Mark a single step of regeneration complete."""
        self.pb.update(message, self.count, self.total)
        self.count += 1
