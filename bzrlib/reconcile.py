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
                self._reconcile_steps()
            finally:
                self.pb.finished()
        finally:
            self.repo.unlock()

    def _reconcile_steps(self):
        """Perform the steps to reconcile this repository."""
        self._reweave_inventory()

    def _reweave_inventory(self):
        """Regenerate the inventory weave for the repository from scratch."""
        # local because its really a wart we want to hide
        from bzrlib.weave import WeaveFile, Weave
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
        self._check_garbage_inventories()
        if not self.inconsistent_parents and not self.garbage_inventories:
            self.pb.note('Inventory ok.')
            return
        self.pb.update('Backing up inventory...', 0, 0)
        self.repo.control_weaves.copy(self.inventory, 'inventory.backup', self.repo.get_transaction())
        self.pb.note('Backup Inventory created.')
        # asking for '' should never return a non-empty weave
        new_inventory_vf = self.repo.control_weaves.get_empty('inventory.new',
            self.repo.get_transaction())

        # we have topological order of revisions and non ghost parents ready.
        self._setup_steps(len(self._rev_graph))
        for rev_id in TopoSorter(self._rev_graph.items()).iter_topo_order():
            parents = self._rev_graph[rev_id]
            # double check this really is in topological order.
            unavailable = [p for p in parents if p not in new_inventory_vf]
            assert len(unavailable) == 0
            # this entry has all the non ghost parents in the inventory
            # file already.
            self._reweave_step('adding inventories')
            if isinstance(new_inventory_vf, WeaveFile):
                # It's really a WeaveFile, but we call straight into the
                # Weave's add method to disable the auto-write-out behaviour.
                new_inventory_vf._check_write_ok()
                Weave._add_lines(new_inventory_vf, rev_id, parents, self.inventory.get_lines(rev_id),
                                 None)
            else:
                new_inventory_vf.add_lines(rev_id, parents, self.inventory.get_lines(rev_id))

        if isinstance(new_inventory_vf, WeaveFile):
            new_inventory_vf._save()
        # if this worked, the set of new_inventory_vf.names should equal
        # self.pending
        assert set(new_inventory_vf.versions()) == self.pending
        self.pb.update('Writing weave')
        self.repo.control_weaves.copy(new_inventory_vf, 'inventory', self.repo.get_transaction())
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
            mutter('Inconsistent inventory parents: id {%s} '
                   'inventory claims %r, '
                   'available parents are %r, '
                   'unavailable parents are %r',
                   rev_id, 
                   set(self.inventory.get_parents(rev_id)),
                   set(parents),
                   set(rev.parent_ids).difference(set(parents)))

    def _check_garbage_inventories(self):
        """Check for garbage inventories which we cannot trust

        We cant trust them because their pre-requisite file data may not
        be present - all we know is that their revision was not installed.
        """
        inventories = set(self.inventory.versions())
        revisions = set(self._rev_graph.keys())
        garbage = inventories.difference(revisions)
        self.garbage_inventories = len(garbage)
        for revision_id in garbage:
            mutter('Garbage inventory {%s} found.', revision_id)

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


class KnitReconciler(RepoReconciler):
    """Reconciler that reconciles a knit format repository.

    This will detect garbage inventories and remove them.

    Inconsistent parentage is checked for in the revision weave.
    """

    def _reconcile_steps(self):
        """Perform the steps to reconcile this repository."""
        self._load_indexes()
        # knits never suffer this
        self.inconsistent_parents = 0
        self._gc_inventory()

    def _load_indexes(self):
        """Load indexes for the reconciliation."""
        self.transaction = self.repo.get_transaction()
        self.pb.update('Reading indexes.', 0, 2)
        self.inventory = self.repo.get_inventory_weave()
        self.pb.update('Reading indexes.', 1, 2)
        self.revisions = self.repo._revision_store.get_revision_file(self.transaction)
        self.pb.update('Reading indexes.', 2, 2)

    def _gc_inventory(self):
        """Remove inventories that are not referenced from the revision store."""
        self.pb.update('Checking unused inventories.', 0, 1)
        self._check_garbage_inventories()
        self.pb.update('Checking unused inventories.', 1, 3)
        if not self.garbage_inventories:
            self.pb.note('Inventory ok.')
            return
        self.pb.update('Backing up inventory...', 0, 0)
        self.repo.control_weaves.copy(self.inventory, 'inventory.backup', self.transaction)
        self.pb.note('Backup Inventory created.')
        # asking for '' should never return a non-empty weave
        new_inventory_vf = self.repo.control_weaves.get_empty('inventory.new',
            self.transaction)

        # we have topological order of revisions and non ghost parents ready.
        self._setup_steps(len(self.revisions))
        for rev_id in TopoSorter(self.revisions.get_graph().items()).iter_topo_order():
            parents = self.revisions.get_parents(rev_id)
            # double check this really is in topological order.
            unavailable = [p for p in parents if p not in new_inventory_vf]
            assert len(unavailable) == 0
            # this entry has all the non ghost parents in the inventory
            # file already.
            self._reweave_step('adding inventories')
            # ugly but needed, weaves are just way tooooo slow else.
            new_inventory_vf.add_lines(rev_id, parents, self.inventory.get_lines(rev_id))

        # if this worked, the set of new_inventory_vf.names should equal
        # self.pending
        assert set(new_inventory_vf.versions()) == set(self.revisions.versions())
        self.pb.update('Writing weave')
        self.repo.control_weaves.copy(new_inventory_vf, 'inventory', self.transaction)
        self.repo.control_weaves.delete('inventory.new', self.transaction)
        self.inventory = None
        self.pb.note('Inventory regenerated.')

    def _reinsert_revisions(self):
        """Correct the revision history for revisions in the revision knit."""
        # the total set of revisions to process
        self.pending = set(self.revisions.versions())

        # mapping from revision_id to parents
        self._rev_graph = {}
        # errors that we detect
        self.inconsistent_parents = 0
        # we need the revision id of each revision and its available parents list
        self._setup_steps(len(self.pending))
        for rev_id in self.pending:
            # put a revision into the graph.
            self._graph_revision(rev_id)

        if not self.inconsistent_parents:
            self.pb.note('Revision history accurate.')
            return
        self._setup_steps(len(self._rev_graph))
        for rev_id, parents in self._rev_graph.items():
            if parents != self.revisions.get_parents(rev_id):
                self.revisions.fix_parents(rev_id, parents)
            self._reweave_step('Fixing parents')
        self.pb.note('Ancestry corrected.')

    def _graph_revision(self, rev_id):
        """Load a revision into the revision graph."""
        # pick a random revision
        # analyse revision id rev_id and put it in the stack.
        self._reweave_step('loading revisions')
        rev = self.repo._revision_store.get_revision(rev_id, self.transaction)
        assert rev.revision_id == rev_id
        parents = []
        for parent in rev.parent_ids:
            if self.revisions.has_version(parent):
                parents.append(parent)
            else:
                mutter('found ghost %s', parent)
        self._rev_graph[rev_id] = parents   
        if set(self.inventory.get_parents(rev_id)) != set(parents):
            self.inconsistent_parents += 1
            mutter('Inconsistent inventory parents: id {%s} '
                   'inventory claims %r, '
                   'available parents are %r, '
                   'unavailable parents are %r',
                   rev_id, 
                   set(self.inventory.get_parents(rev_id)),
                   set(parents),
                   set(rev.parent_ids).difference(set(parents)))

    def _check_garbage_inventories(self):
        """Check for garbage inventories which we cannot trust

        We cant trust them because their pre-requisite file data may not
        be present - all we know is that their revision was not installed.
        """
        inventories = set(self.inventory.versions())
        revisions = set(self.revisions.versions())
        garbage = inventories.difference(revisions)
        self.garbage_inventories = len(garbage)
        for revision_id in garbage:
            mutter('Garbage inventory {%s} found.', revision_id)
