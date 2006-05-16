#!/usr/bin/env python
"""\
This contains the apply changset function for bzr
"""

import bzrlib
import os
import sys
from cStringIO import StringIO
import tempfile
import shutil

from bzrlib.xml5 import serializer_v5
from bzrlib.trace import mutter, warning
from bzrlib.revision import common_ancestor
from bzrlib.merge import merge_inner
from bzrlib.errors import BzrCommandError, RevisionAlreadyPresent
from bzrlib.diff import compare_trees
from bzrlib.osutils import sha_string, split_lines
import bzrlib.ui
from bzrlib.tree import EmptyTree


def _install_info(repository, cset_info, cset_tree):
    """Make sure that there is a text entry for each 
    file in the changeset.

    TODO: This might be supplanted by some sort of Commit() object, though
          some of the side-effects should not occur
    TODO: The latest code assumes that if you have the Revision information
          then you have to have everything else.
          So there may be no point in adding older revision information to
          the bottom of a changeset (though I would like to add them all
          as ghost revisions)
    """
    if not repository.has_revision(cset_info.target):
        rev = cset_info.real_revisions[-1]
        repository.lock_write()
        try:
            return install_revision(repository, rev, cset_tree)
        finally:
            repository.unlock()

def install_changeset(repository, changeset_reader):
    pb = bzrlib.ui.ui_factory.nested_progress_bar()
    try:
        real_revisions = changeset_reader.info.real_revisions
        for i, revision in enumerate(reversed(real_revisions)):
            pb.update("Install revisions",i, len(real_revisions))
            if repository.has_revision(revision.revision_id):
                continue
            cset_tree = changeset_reader.revision_tree(repository,
                                                       revision.revision_id)
            install_revision(repository, revision, cset_tree)
    finally:
        pb.finished()

def install_revision(repository, rev, cset_tree):
    # install the inventory
    # TODO: Figure out how to handle ghosted revisions
    present_parents = []
    parent_trees = {}
    for p_id in rev.parent_ids:
        if repository.has_revision(p_id):
            present_parents.append(p_id)
            parent_trees[p_id] = repository.revision_tree(p_id)
        else:
            parent_trees[p_id] = EmptyTree()

    inv = cset_tree.inventory
    
    # Add the texts that are not already present
    for path, ie in inv.iter_entries():
        w = repository.weave_store.get_weave_or_empty(ie.file_id,
                repository.get_transaction())
        if ie.revision not in w:
            text_parents = []
            for revision, tree in parent_trees.iteritems():
                if ie.file_id not in tree:
                    continue
                parent_id = tree.inventory[ie.file_id].revision
                if parent_id in text_parents:
                    continue
                text_parents.append(parent_id)
                    
            repository.weave_store.add_text(ie.file_id, 
                                            rev.revision_id,
            cset_tree.get_file(ie.file_id).readlines(),
            text_parents, repository.get_transaction())
    try:
        repository.add_inventory(rev.revision_id, inv, present_parents)
    except RevisionAlreadyPresent:
        pass
    repository.add_revision(rev.revision_id, rev, inv)

def apply_changeset(branch, from_file, reverse=False, auto_commit=False):
    """Read in a changeset from the given file, and apply it to
    the supplied branch.

    :return: True if the changeset was automatically committed to the
             ancestry, False otherwise.
    """
    import read_changeset

    if reverse:
        raise Exception('reverse not implemented yet')

    cset = read_changeset.read_changeset(from_file, branch.repository)

    return _apply_cset(branch, cset, reverse=reverse, auto_commit=auto_commit)
        
def _apply_cset(tree, cset, reverse=False, auto_commit=False):
    """Apply an in-memory changeset to a given branch.
    """

    cset_info, cset_tree = cset

    _install_info(tree.branch.repository, cset_info, cset_tree)

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
    if tree.last_revision() is None:
        base = None
    else:
        base = common_ancestor(tree.last_revision(), cset_info.target, 
                               tree.branch.repository)
    merge_inner(tree.branch, 
                tree.branch.repository.revision_tree(cset_info.target),
                tree.branch.repository.revision_tree(base), this_tree=tree)

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
        raise NotImplementedError('automatic committing has not been implemented after the changes')
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
        tree.add_pending_merge(cset_info.target)

    return auto_committed

