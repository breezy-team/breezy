"""\
This contains functionality for installing changesets into repositories
"""

import bzrlib.ui
from bzrlib.progress import ProgressPhase
from bzrlib.merge import Merger
from bzrlib.repository import install_revision


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


def merge_changeset(reader, tree, check_clean, merge_type, 
                    reprocess, show_base):
    """Merge a changeset's revision into the current tree."""
    pb = bzrlib.ui.ui_factory.nested_progress_bar()
    try:
        pp = ProgressPhase("Merge phase", 6, pb)
        pp.next_phase()
        install_changeset(tree.branch.repository, reader)
        merger = Merger(tree.branch, this_tree=tree, pb=pb)
        merger.pp = pp
        merger.pp.next_phase()
        merger.check_basis(check_clean, require_commits=False)
        merger.other_rev_id = reader.info.target
        merger.other_tree = merger.revision_tree(reader.info.target)
        merger.other_basis = reader.info.target
        merger.pp.next_phase()
        merger.find_base()
        if merger.base_rev_id == merger.other_rev_id:
            note("Nothing to do.")
            return 0
        merger.merge_type = merge_type
        merger.show_base = show_base
        merger.reprocess = reprocess
        conflicts = merger.do_merge()
        merger.set_pending()
    finally:
        pb.clear()
    return conflicts
