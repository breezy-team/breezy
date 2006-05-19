"""\
This contains functionality for installing changesets into repositories
"""

from bzrlib.errors import RevisionAlreadyPresent
from bzrlib.tree import EmptyTree
import bzrlib.ui


def install_changeset(repository, changeset_reader):
    pb = bzrlib.ui.ui_factory.nested_progress_bar()
    repository.lock_write()
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
        repository.unlock()
        pb.finished()


def install_revision(repository, rev, cset_tree):
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
                    
            vfile = repository.weave_store.get_weave_or_empty(ie.file_id, 
                repository.get_transaction())
            lines = cset_tree.get_file(ie.file_id).readlines()
            vfile.add_lines(rev.revision_id, text_parents, lines)
    try:
        # install the inventory
        repository.add_inventory(rev.revision_id, inv, present_parents)
    except RevisionAlreadyPresent:
        pass
    repository.add_revision(rev.revision_id, rev, inv)
