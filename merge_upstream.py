from bzrlib.plugins.bzrtools.upstream_import import import_tar

def merge_upstream(tree, source, old_revision):

    current_revision = tree.last_revision()
    revno, rev_id = old_revision.in_branch(tree.branch)
    tree.revert([], tree.branch.repository.revision_tree(rev_id))
    tar_input = open(source, 'rb')
    import_tar(tree, tar_input)
    tree.set_parent_ids([rev_id])
    tree.branch.set_last_revision_info(revno, rev_id)
    tree.commit('import upstream from %s' % file)
    tree.merge_from_branch(tree.branch, to_revision=current_revision)
    
