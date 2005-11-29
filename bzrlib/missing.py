"""\
A plugin for displaying what revisions are in 'other' but not in local.
"""
from bzrlib.ui import ui_factory
def show_missing(br_local, br_remote, verbose=False, quiet=False):
    """Show the revisions which exist in br_remote, that 
    do not exist in br_local.
    """
    from bzrlib.log import show_one_log
    import sys
    local_history = br_local.revision_history()
    remote_history = br_remote.revision_history()
    if local_history == remote_history:
        if not quiet:
            print 'Trees are identical.'
        return 0
    if local_history[:len(remote_history)] == remote_history:
        # Local is not missing anything from remote, so consider it
        # up-to-date
        if not quiet:
            print 'Local tree has all of remote revisions (remote is missing local)'
        return 0
    if quiet:
        return 1

    # Check for divergence
    common_idx = min(len(local_history), len(remote_history)) - 1
    if common_idx >= 0 and local_history[common_idx] != remote_history[common_idx]:
        print 'Trees have diverged'

    local_rev_set = set(local_history)

    # Find the last common revision between the two trees
    revno = 0
    for revno, (local_rev, remote_rev) in enumerate(zip(local_history, remote_history)):
        if local_rev != remote_rev:
            break

    missing_remote = []
    for rno, rev_id in enumerate(remote_history[revno:]):
        # This assumes that you can have a revision in the
        # local history, which does not have the same ancestry
        # as the remote ancestry.
        # This may or may not be possible.
        # In the future this should also checked for merged revisions.
        if rev_id not in local_rev_set:
            missing_remote.append((rno+revno+1, rev_id))

    print 'Missing %d revisions' %  len(missing_remote)
    print

    if verbose:
        from bzrlib.diff import compare_trees
        from bzrlib.tree import EmptyTree
        show_ids = True
        last_tree = EmptyTree
        last_rev_id = None
    else:
        show_ids = False
    for revno, rev_id in missing_remote:
        rev = br_remote.get_revision(rev_id)
        if verbose:
            parent_rev_id = rev.parent_ids[0]
            if last_rev_id == parent_rev_id:
                parent_tree = last_tree
            else:
                parent_tree = br_remote.revision_tree(parent_rev_id)
            revision_tree = br_remote.revision_tree(rev_id)
            last_rev_id = rev_id
            last_tree = revision_tree
            delta = compare_trees(revision_tree, parent_tree)
        else:
            delta = None

        show_one_log(revno, rev, delta, verbose, sys.stdout, 'original')
    return 1


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
        return set(), set(remote_rev_history[remote_rev_history.index(local_rev_history[-1])+1:])
    elif remote_rev_history[-1] in local_history:
        return set(local_rev_history[local_rev_history.index(remote_rev_history[-1])+1:]), set()
    else:
        return None


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
