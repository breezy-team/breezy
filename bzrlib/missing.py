"""\
A plugin for displaying what revisions are in 'other' but not in local.
"""
from bzrlib.ui import ui_factory
def iter_log_data(revisions, revision_source, verbose):
    from bzrlib.diff import compare_trees
    from bzrlib.tree import EmptyTree
    last_tree = EmptyTree
    last_rev_id = None
    for revno, rev_id in revisions:
        rev = revision_source.get_revision(rev_id)
        if verbose:
            parent_rev_id = rev.parent_ids[0]
            if last_rev_id == parent_rev_id:
                parent_tree = last_tree
            else:
                parent_tree = revision_source.revision_tree(parent_rev_id)
            revision_tree = revision_source.revision_tree(rev_id)
            last_rev_id = rev_id
            last_tree = revision_tree
            delta = compare_trees(revision_tree, parent_tree)
        else:
            delta = None
        yield revno, rev, delta


def find_unmerged(local_branch, remote_branch):
    progress = ui_factory.progress_bar()
    local_branch.lock_read()
    try:
        remote_branch.lock_read()
        try:
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

            local_ancestry = _get_ancestry(local_branch, progress, "local",
                                           2, local_rev_history)
            remote_ancestry = _get_ancestry(remote_branch, progress, "remote",
                                            3, remote_rev_history)
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
        progress.clear()
    return (local_extra, remote_extra)

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

def _get_ancestry(branch, progress, label, step, rev_history):
    progress.update('%s ancestry' % label, step, 5)
    if len(rev_history) > 0:
        ancestry = set(branch.get_ancestry(rev_history[-1]))
    else:
        ancestry = set()
    return ancestry
    

def sorted_revisions(revisions, history_map):
    revisions = [(history_map[r],r) for r in revisions]
    revisions.sort()
    return revisions
