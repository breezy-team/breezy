#!/usr/bin/env python
"""\
This contains the apply changset function for bzr
"""

import bzrlib
import os

from bzrlib.trace import mutter, warning
from bzrlib.revision import common_ancestor

def _install_info(branch, cset_info, cset_tree):
    """Make sure that there is a text entry for each 
    file in the changeset.
    """
    from bzrlib.xml import serializer_v4
    from cStringIO import StringIO

    inv = cset_tree.inventory
    # First, install all required texts
    for path, ie in inv.iter_entries():
        if ie.text_id is not None and ie.text_id not in branch.text_store:
            branch.text_store.add(cset_tree.get_file(ie.file_id), ie.text_id)

    # Now install the final inventory
    if cset_info.target not in branch.inventory_store:
        # bzrlib.commit uses a temporary file, but store.add
        # reads in the entire file anyway
        if cset_info.target in branch.inventory_store:
            warning('Target inventory already exists in destination.')
        else:
            sio = StringIO()
            serializer_v4.write_inventory(inv, sio)
            branch.inventory_store.add(sio.getvalue(), cset_info.target)
            del sio

    # Now that we have installed the inventory and texts
    # install the revision entries.
    for rev in cset_info.real_revisions:
        if rev.revision_id not in branch.revision_store:
            sio = StringIO()
            serializer_v4.write_revision(rev, sio)
            branch.revision_store.add(sio.getvalue(), rev.revision_id)
            del sio

def merge_revs(branch, rev_base, rev_other,
        ignore_zero=False, check_clean=True):
    """This will merge the tree of rev_other into 
    the working tree of branch using the base given by rev_base.
    All the revision XML should be inside branch.
    """
    import tempfile, shutil
    from bzrlib.merge import merge_inner, MergeTree
    from bzrlib.errors import BzrCommandError

    tempdir = tempfile.mkdtemp(prefix='bzr-')
    try:
        if check_clean:
            from bzrlib.diff import compare_trees
            changes = compare_trees(branch.working_tree(), 
                                    branch.basis_tree(), False)

            if changes.has_changed():
                raise BzrCommandError("Working tree has uncommitted changes.")

        other_dir = os.path.join(tempdir, 'other')
        os.mkdir(other_dir)
        other_tree = MergeTree(branch.revision_tree(rev_other), other_dir)

        base_dir = os.path.join(tempdir, 'base')
        os.mkdir(base_dir)
        base_tree = MergeTree(branch.revision_tree(rev_base), base_dir)

        merge_inner(branch, other_tree, base_tree, tempdir,
            ignore_zero=ignore_zero)
    finally:
        shutil.rmtree(tempdir)

def apply_changeset(branch, from_file, reverse=False, auto_commit=False):
    """Read in a changeset from the given file, and apply it to
    the supplied branch.

    :return: True if the changeset was automatically committed to the
             ancestry, False otherwise.
    """
    import sys, read_changeset

    if reverse:
        raise Exception('reverse not implemented yet')

    cset = read_changeset.read_changeset(from_file, branch)

    return _apply_cset(branch, cset, reverse=reverse, auto_commit=auto_commit)
        
def _apply_cset(branch, cset, reverse=False, auto_commit=False):
    """Apply an in-memory changeset to a given branch.
    """

    cset_info, cset_tree = cset

    _install_info(branch, cset_info, cset_tree)

    # We could technically optimize more, by using the ChangesetTree
    # we already have in memory, but after installing revisions
    # this code can work the way merge should work in the
    # future.
    #
    # TODO:
    #   This shouldn't use the base of the changeset as the base
    #   for the merge, the merge code should pick the best merge
    #   based on the ancestry of both trees.
    #
    base = common_ancestor(branch.last_patch(), cset_info.target, branch)
    merge_revs(branch, base, cset_info.target)

    auto_committed = False
    
    # There are 2 cases where I am allowing automatic committing.
    # 1) If the final revision has a parent of the current last revision
    #    (branch.last_patch() in cset.target.parents)
    #    that means that the changeset target has already merged the current
    #    tree.
    # 2) A cset contains a list of revisions. If the first entry has a parent
    #    of branch.last_patch(), then we can start merging there, and add the
    #    rest of the revisions. But it gets better. Some of the entries in the
    #    list might already be in the revision list, so we keep going until
    #    we find the first revision *not* in the list. If it's parent is
    #    branch.last_patch(), then we can also append history from there.
    #    This second part is a little more controversial, because the cset
    #    probably does not include all of the inventories. So you would have
    #    entries in branch.revision_history() without an associated inventory.
    #    we could just explicitly disable this. But if we had the inventory
    #    entries available, it is what 'bzr merge' would do.
    #    If we disable this, the target will just show up as a pending_merge
    if auto_commit:
        # When merging, if the revision to be merged has a parent
        # of the current revision, then it can be installed
        # directly.
        #
        # TODO: 
        #   There is actually a slightly stronger statement
        #   whereby if the current revision is in the ancestry
        #   of the merged revisions, it doesn't need to be the
        #   immediate ancestry, but that requires searching
        #   a potentially branching history.
        #
        rh = branch.revision_history()
        revs_to_merge = None
        found_parent = False
        if len(rh) == 0 and len(cset_info.real_revisions[0].parents) == 0:
            found_parent = True
            revs_to_merge = cset_info.real_revisions
        else:
            for rev_num, rev in enumerate(cset_info.real_revisions):
                if rev.revision_id not in rh:
                    for parent in rev.parents:
                        if parent.revision_id == rh[-1]:
                            found_parent = True
                    if found_parent:
                        # All revisions up until now already
                        # existed in the target history
                        # and this last one is a child of the
                        # last entry in the history.
                        # so we can add the rest
                        revs_to_merge = cset_info.real_revisions[rev_num:]
                    # Even if we don't find anything, we need to
                    # stop here
                    break

        if found_parent:
            rev_ids = [r.revision_id for r in revs_to_merge]
            branch.append_revision(*rev_ids)
            auto_committed = True
        else:
            # We can also merge if the *last* revision has an
            # appropriate parent.
            target_has_parent = False
            target_rev = branch.get_revision(cset_info.target)
            lastrev_id = branch.last_patch()
            for parent in target_rev.parents:
                if parent.revision_id == lastrev_id:
                    target_has_parent = True

            if target_has_parent:
                branch.append_revision(target_rev.revision_id)
            else:
                print '** Could not auto-commit.'

    if not auto_committed:
        branch.add_pending_merge(cset_info.target)

    return auto_committed

