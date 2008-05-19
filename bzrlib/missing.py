# Copyright (C) 2005, 2006 Canonical Ltd
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

"""Display what revisions are missing in 'other' from 'this' and vice versa."""

from bzrlib import ui
from bzrlib.log import (
    LogRevision,
    )


def iter_log_revisions(revisions, revision_source, verbose):
    last_tree = revision_source.revision_tree(None)
    last_rev_id = None
    for revno, rev_id in revisions:
        rev = revision_source.get_revision(rev_id)
        if verbose:
            remote_tree = revision_source.revision_tree(rev_id)
            parent_rev_id = rev.parent_ids[0]
            if last_rev_id == parent_rev_id:
                parent_tree = last_tree
            else:
                parent_tree = revision_source.revision_tree(parent_rev_id)
            revision_tree = revision_source.revision_tree(rev_id)
            last_rev_id = rev_id
            last_tree = revision_tree
            delta = revision_tree.changes_from(parent_tree)
        else:
            delta = None
        yield LogRevision(rev, revno, delta=delta)


def find_unmerged(local_branch, remote_branch):
    progress = ui.ui_factory.nested_progress_bar()
    local_branch.lock_read()
    try:
        remote_branch.lock_read()
        try:
            # check for special case: both branches are equivalent
            if (local_branch.last_revision_info() ==
                remote_branch.last_revision_info()):
                return [], []
            local_rev_history, local_rev_history_map = \
                _get_history(local_branch, progress, "local", 0)
            remote_rev_history, remote_rev_history_map = \
                _get_history(remote_branch, progress, "remote", 1)
            result = _shortcut(local_rev_history, remote_rev_history)
            if result is not None:
                local_extra, remote_extra = result
                local_extra = sorted_revisions(local_extra, 
                                               local_rev_history_map)
                remote_extra = sorted_revisions(remote_extra, 
                                                remote_rev_history_map)
                return local_extra, remote_extra

            local_ancestry = _get_ancestry(local_branch.repository, progress, 
                                           "local", 2, local_rev_history)
            remote_ancestry = _get_ancestry(remote_branch.repository, progress,
                                            "remote", 3, remote_rev_history)
            progress.update('pondering', 4, 5)
            extras = local_ancestry.symmetric_difference(remote_ancestry) 
            local_extra = extras.intersection(set(local_rev_history))
            remote_extra = extras.intersection(set(remote_rev_history))
            local_extra = sorted_revisions(local_extra, local_rev_history_map)
            remote_extra = sorted_revisions(remote_extra, 
                                            remote_rev_history_map)
                    
        finally:
            remote_branch.unlock()
    finally:
        local_branch.unlock()
        progress.finished()
    return (local_extra, remote_extra)


def _enumerate_mainline(ancestry, graph, tip_revno, tip):
    """Enumerate the mainline revisions for these revisions.

    :param ancestry: A set of revisions that we care about
    :param graph: A Graph which lets us find the parents for a revision
    :param tip_revno: The revision number for the tip revision
    :param tip: The tip of mailine
    :return: [(revno, revision_id)] for all revisions in ancestry that
        left-hand parents from tip
    """
    if ancestry is None:
        return None
    if not ancestry: #Empty ancestry, no need to do any work
        return []

    # Optionally we could make 1 call to graph.get_parent_map with all
    # ancestors. However that will often check many more parents than we
    # actually need, and the Graph is likely to already have the parents cached
    # anyway.
    mainline = []
    cur = tip
    cur_revno = tip_revno
    while cur in ancestry:
        parent_map = graph.get_parent_map([cur])
        if cur not in parent_map:
            break # Ghost, we are done
        mainline.append((cur_revno, cur))
        cur = parent_map[cur]
        cur_revno -= 1
    mainline.reverse()
    return mainline


def find_unmerged_mainline_revisions(local_branch, remote_branch, restrict):
    """Find revisions from each side that have not been merged.

    Both branches should already be locked.

    :param local_branch: Compare the history of local_branch
    :param remote_branch: versus the history of remote_branch, and determine
        mainline revisions which have not been merged.
    :param restrict: ('all', 'local', 'remote') If 'all', we will return the
        unique revisions from both sides. If 'local', we will return None
        for the remote revisions, similarly if 'remote' we will return None for
        the local revisions.

    :return: A list of [(revno, revision_id)] for the mainline revisions on
        each side.
    """
    graph = local_branch.repository.get_graph(
                remote_branch.repository)
    local_revno, local_revision_id = local_branch.last_revision_info()
    remote_revno, remote_revision_id = remote_branch.last_revision_info()
    if local_revno == remote_revno and local_revision_id == remote_revision_id:
        # A simple shortcut when the tips are at the same point
        return [], []
    if restrict == 'remote':
        local_extra = None
        remote_extra = graph.find_unique_ancestors(
            remote_revision_id, [local_revision_id])
    elif restrict == 'local':
        remote_extra = None
        local_extra = graph.find_unique_ancestors(
            local_revision_id, [remote_revision_id])
    else:
        if restrict != 'all':
            raise ValueError('param restrict not one of "all", "local",'
                             ' "remote": %r' % (restrict,))
        local_extra, remote_extra = graph.find_difference(
            local_revision_id, remote_revision_id)
    # Now that we have unique ancestors, compute just the mainline, and
    # generate revnos for them.
    local_mainline = _enumerate_mainline(local_extra, graph, local_revno,
                                         local_revision_id)
    remote_mainline = _enumerate_mainline(remote_extra, graph, remote_revno,
                                          remote_revision_id)
    return local_mainline, remote_mainline


def _shortcut(local_rev_history, remote_rev_history):
    local_history = set(local_rev_history)
    remote_history = set(remote_rev_history)
    if len(local_rev_history) == 0:
        return set(), remote_history
    elif len(remote_rev_history) == 0:
        return local_history, set()
    elif local_rev_history[-1] in remote_history:
        return set(), _after(remote_rev_history, local_rev_history)
    elif remote_rev_history[-1] in local_history:
        return _after(local_rev_history, remote_rev_history), set()
    else:
        return None

def _after(larger_history, smaller_history):
    return set(larger_history[larger_history.index(smaller_history[-1])+1:])

def _get_history(branch, progress, label, step):
    progress.update('%s history' % label, step, 5)
    rev_history = branch.revision_history()
    rev_history_map = dict(
        [(rev, rev_history.index(rev) + 1)
         for rev in rev_history])
    return rev_history, rev_history_map

def _get_ancestry(repository, progress, label, step, rev_history):
    progress.update('%s ancestry' % label, step, 5)
    if len(rev_history) > 0:
        ancestry = set(repository.get_ancestry(rev_history[-1],
                       topo_sorted=False))
    else:
        ancestry = set()
    return ancestry
    

def sorted_revisions(revisions, history_map):
    revisions = [(history_map[r],r) for r in revisions]
    revisions.sort()
    return revisions
