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

"""Plugin to fix some potential data errors in a branch.

This makes sure that the inventory weave's DAG of ancestry is correct so that
attempts to fetch the branch over http, or certain merge operations cope
correctly.

This is most likely needed if you have used fetch-ghosts from bzrlib to
resolve ghosts after a baz (or otherwise) import and you get bizarre behaviour
when either exporting over http or when merging from other translated branches.
"""


import os


import bzrlib.branch
import bzrlib.progress
from bzrlib.trace import mutter
import bzrlib.ui as ui
from bzrlib.weavefile import write_weave_v5 as w5



def reconcile(dir):
    """Reconcile the data in dir.

    Currently this is limited to a inventory 'reweave'.

    This is a convenience method, and the public api, for using a 
    Reconciler object.
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
        """Actually perform the reconciliation."""
        self.pb = ui.ui_factory.progress_bar()
        self.repo = self.bzrdir.open_repository()
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
        self.repo.control_weaves.put_weave('inventory.backup',
                                           self.inventory,
                                           self.repo.get_transaction())
        self.pb.note('Backup Inventory created.')
        # asking for '' should never return a non-empty weave
        new_inventory = self.repo.control_weaves.get_weave_or_empty('',
            self.repo.get_transaction())

        # the total set of revisions to process
        self.pending = set([file_id for file_id in self.repo.revision_store])
        # the current line of history being processed.
        # once we add in per inventory root ids this will involve a single
        # pass within the revision knit at that point.
        # this contains (revision_id, not_ghost_parents) tuples.
        self._rev_stack = []
        # total steps = 1 read per revision + one insert into the inventory
        self.total = len(self.pending) * 2
        self.count = 0

        # outer loop to ensure we hit every revision
        while self.pending:
            self._stack_revision()
            # now we have one revision on the todo stack.
            # try to process the tip of the stack and if we cant
            # insert it yet queue the revision ids we need to be
            # able to add it. Rinse and repeat until the stack is
            # empty and then we grab another pending revision if
            # there are any
            while len(self._rev_stack):
                rev_id, parents = self._rev_stack[-1]
                unavailable = [p for p in parents if p not in new_inventory]
                if len(unavailable) == 0:
                    # this entry can be popped off.
                    self.pb.update('regenerating', self.count, self.total)
                    self.count += 1
                    new_inventory.add(rev_id, parents, self.inventory.get(rev_id))
                    self._rev_stack.pop()
                else:
                    # push the needed parents onto the stack
                    for parent in unavailable:
                        self._stack_revision(parent)
        self.pb.update('Writing weave')
        self.repo.control_weaves.put_weave('inventory',
                                           new_inventory,
                                           self.repo.get_transaction())
        self.inventory = None
        self.pb.note('Inventory regenerated.')

    def _stack_revision(self, rev_id=None):
        """Add rev_id to the pending revision stack."""
        if rev_id is None:
            # pick a random revision
            rev_id = self.pending.pop()
        self.pb.update('regenerating', self.count, self.total)
        self.count += 1
        rev = self.repo.get_revision(rev_id)
        assert rev.revision_id == rev_id
        parents = []
        for parent in rev.parent_ids:
            if parent in self.inventory:
                parents.append(parent)
            else:
                mutter('found ghost %s', parent)
        self._rev_stack.append((rev_id, parents))

