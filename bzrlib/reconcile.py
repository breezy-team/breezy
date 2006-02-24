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


import bzrlib.branch
import bzrlib.errors as errors
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


def topological_sort(graph):
    """Topological sort a graph.

    graph -- sequence of pairs of node->parents_list.

    The result is a list of node names, such that all parents come before
    their children.

    Nodes at the same depth are returned in sorted order.

    node identifiers can be any hashable object, and are typically strings.
    """
    sorter = TopoSorter()
    sorter.sort(graph)
    return sorter._work_queue


class TopoSorter(object):

    def sort(self, graph):
        # the total set of revisions to process
        self._rev_graph = dict(graph)
        ### if debugging:
        # self._original_graph = dict(graph)
        
        # the current line of history being processed.
        # once we add in per inventory root ids this will involve a single
        # pass within the revision knit at that point.
        # these contain respectively the revision id in the call stack
        self._rev_stack = []
        # a set of the revisions on the stack, for cycle detection
        self._rev_set = set()
        # and the not_ghost_parents.
        self._pending_stack = []
        # actual queue to reinsert. This is a single pass queue we can use to 
        # regenerate the inventory versioned file, and holds
        # (rev_id, non_ghost_parents) entries
        self._work_queue = []
        # this is a set for fast lookups of queued revisions
        self._work_set = set()
        # total steps = 1 read per revision + one insert into the inventory

        # now we do a depth first search of the revision graph until its empty.
        # this gives us a topological order across all revisions in 
        # self._all_revisions.
        # This is flattened to avoid deep recursion:
        # At each step in the call graph we need to know which parent we are on.
        # we do this by having three variables for each stack frame:
        # revision_id being descended into (self._rev_stack)
        # current queue of parents to descend into 
        #   (self._pending_stack)
        # putting all the parents into a pending list, left to 
        # right and processing the right most one each time. The same parent
        # may occur at multiple places in the stack - thats fine. We check its
        # not in the output before processing. However revisions cannot
        # appear twice.
        # the algorithm is roughly:
        # for revision, parents in _rev_graph.items():
        #   if revision in self._all_revisions:
        #     continue
        #   add_revision_parents(revision, parents)
        #  def add_revision_parents(revision, parents)
        #    fpr parent in parents:
        #       add_revision_parents(parent, parent.parents)
        #   self._all_revisions.append(revision)
        #   self._all_revision_parents.appent(parents)
        # however we tune this to visit fragmens of the graph
        # and not double-visit entries.
        # nevertheless the output is a 
        # self._work_queue of revisions, nonghost parents in 
        # topological order and
        # a self._work_set which is a complete set of revisions.
        while self._rev_graph:
            rev_id, parents = self._rev_graph.iteritems().next()
            # rev_id
            self._stack_revision(rev_id, parents)
            while self._rev_stack:
                # loop until this call completes.
                parents_to_visit = self._pending_stack[-1]
                # if all parents are done, the revision is done
                if not parents_to_visit:
                    # append the revision to the topo sorted list
                    self._unstack_revision()
                else:
                    while self._pending_stack[-1]:
                        # recurse depth first into a single parent 
                        next_rev_id = self._pending_stack[-1].pop()
                        if next_rev_id in self._work_set:
                            # this parent was completed by a child on the
                            # call stack. skip it.
                            continue
                        # push it into the call stack
                        self._stack_revision(next_rev_id, self._rev_graph[next_rev_id])
                        # and do not continue processing parents until this 'call' 
                        # has recursed.
                        break
            
                # we are now recursing down a call stack.
                # its a width first search which 

###        Useful if fiddling with this code.
###        # cross check
###        for index in range(len(self._work_queue)):
###            rev = self._work_queue[index]
###            for left_index in range(index):
###                if rev in self.original_graph[self._work_queue[left_index]]:
###                    print "revision in parent list of earlier revision"
###                    import pdb;pdb.set_trace()

    def _stack_revision(self, rev_id, parents):
        """Add rev_id to the pending revision stack."""
        # detect cycles:
        if rev_id in self._rev_set:
            # we only supply the revisions that led to the cycle. This isn't
            # minimal though... but it is usually a subset of the entire graph
            # and easier to debug.
            raise errors.GraphCycleError(self._rev_set)

        self._rev_stack.append(rev_id)
        self._rev_set.add(rev_id)
        self._pending_stack.append(list(parents))

    def _unstack_revision(self):
        """A revision has been completed.

        The revision is added to the work queue, and the data for
        it popped from the call stack.
        """
        rev_id = self._rev_stack.pop()
        self._rev_set.remove(rev_id)
        self._pending_stack.pop()
        self._work_queue.append(rev_id)
        self._work_set.add(rev_id)
        # and remove it from the rev graph as its now complete
        self._rev_graph.pop(rev_id)


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

        # total steps = 1 read per revision + one insert into the inventory
        self.total = len(self.pending) * 2
        self.count = 0

        # mapping from revision_id to parents
        self._rev_graph = {}
        # we need the revision id of each revision and its available parents list
        for rev_id in self.pending:
            # put a revision into the graph.
            self._graph_revision(rev_id)

        ordered_rev_ids = topological_sort(self._rev_graph.items())
        self._work_queue = [(rev_id, self._rev_graph[rev_id]) for 
                            rev_id in ordered_rev_ids]

        # we have topological order of revisions and non ghost parents ready.
        while self._work_queue:
            rev_id, parents = self._work_queue.pop(0)
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

    def _reweave_step(self, message):
        """Mark a single step of regeneration complete."""
        self.pb.update(message, self.count, self.total)
        self.count += 1
