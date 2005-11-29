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
    local_branch.lock_read()
    try:
        remote_branch.lock_read()
        try:
            progress = ui_factory.progress_bar()
            progress.update('local history', 0, 5)
            local_rev_history = local_branch.revision_history()
            local_rev_history_map = dict(
                [(rev, local_rev_history.index(rev))
                 for rev in local_rev_history])
            progress.update('local ancestry', 1, 5)
            local_ancestry = set(local_branch.get_ancestry(
                local_rev_history[-1]))
            progress.update('remote history', 2, 5)
            remote_rev_history = remote_branch.revision_history()
            remote_rev_history_map = dict(
                [(rev, remote_rev_history.index(rev))
                 for rev in remote_rev_history])
            progress.update('remote ancestry', 3, 5)
            remote_ancestry = set(remote_branch.get_ancestry(
                remote_rev_history[-1]))
            progress.update('pondering', 4, 5)
            extras = local_ancestry.symmetric_difference(remote_ancestry) 
            local_extra = extras.intersection(set(local_rev_history))
            remote_extra = extras.intersection(set(remote_rev_history))
            progress.clear()
            local_extra = sorted_revisions(local_extra, local_rev_history_map)
            remote_extra = sorted_revisions(remote_extra, 
                                            remote_rev_history_map)
                    
        finally:
            remote_branch.unlock()
    finally:
        local_branch.unlock()
    return (local_extra, remote_extra)

def sorted_revisions(revisions, history_map):
    revisions = [(history_map[r],r) for r in revisions]
    revisions.sort()
    return revisions
