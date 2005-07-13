#!/usr/bin/env python
"""\
This contains the apply changset function for bzr
"""

import bzrlib
import os

from bzrlib.trace import mutter, warning

def _install_info(branch, cset_info, cset_tree, cset_inv):
    """Make sure that there is a text entry for each 
    file in the changeset.
    """
    from bzrlib.xml import pack_xml
    from cStringIO import StringIO

    # First, install all required texts
    for file_id, text_id in cset_info.text_ids.iteritems():
        if text_id not in branch.text_store:
            branch.text_store.add(cset_tree.get_file(file_id), text_id)

    # Now install the final inventory
    if cset_info.target not in branch.inventory_store:
        # bzrlib.commit uses a temporary file, but store.add
        # reads in the entire file anyway
        if cset_info.target in branch.inventory_store:
            warning('Target inventory already exists in destination.')
        else:
            sio = StringIO()
            pack_xml(cset_inv, sio)
            branch.inventory_store.add(sio.getvalue(), cset_info.target)
            del sio

    # Now that we have installed the inventory and texts
    # install the revision entries.
    for rev in cset_info.real_revisions:
        if rev.revision_id not in branch.revision_store:
            sio = StringIO()
            pack_xml(rev, sio)
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
    """
    import sys, read_changeset

    if reverse:
        raise Exception('reverse not implemented yet')

    cset = read_changeset.read_changeset(from_file, branch)

    _apply_cset(branch, cset, reverse=reverse, auto_commit=auto_commit)
        
def _apply_cset(branch, cset, reverse=False, auto_commit=False):
    """Apply an in-memory changeset to a given branch.
    """

    cset_info, cset_tree, cset_inv = cset

    _install_info(branch, cset_info, cset_tree, cset_inv)

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
    merge_revs(branch, cset_info.base, cset_info.target)

    if auto_commit:
        from bzrlib.commit import commit

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

