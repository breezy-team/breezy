#!/usr/bin/env python
"""Convert a pack-0.92 repository into a 1.9 (btree) repository.

This works directly on the indices, rather than using the generic conversion
logic. After conversion, it will have backed up your old indices to
.bzr/repository/indices-gi. This is significantly faster than the generic 'bzr
upgrade' but it does not work for all repository formats (only pack format
repositories are supported).
"""


steps_to_revert = []
def add_revert_step(func, *args, **kwargs):
    steps_to_revert.append((func, args, kwargs))

def do_revert():
    print "** Reverting repository"
    for func, args, kwargs in reversed(steps_to_revert):
        func(*args, **kwargs)


def main(args):
    import optparse
    p = optparse.OptionParser(usage='%prog [options]\n' + __doc__)

    opts, args = p.parse_args(args)

    from bzrlib import ui, trace, repository
    from bzrlib.ui import text
    from bzrlib.repofmt import pack_repo
    ui.ui_factory = text.TextUIFactory()
    trace.enable_default_logging()

    trace.note('processing "."')

    fmt = getattr(pack_repo, 'RepositoryFormatKnitPack6', None)
    if fmt is None:
        trace.note("** Your bzrlib does not have RepositoryFormatPack6 (--1.9)")
        trace.note("   upgrade your bzrlib installation.")
        return

    r = repository.Repository.open('.')
    if isinstance(r._format, (pack_repo.RepositoryFormatKnitPack1, # 0.92
                              pack_repo.RepositoryFormatKnitPack5, # 1.6
                              )):
        fmt = pack_repo.RepositoryFormatKnitPack6
    elif isinstance(r._format, (pack_repo.RepositoryFormatKnitPack4, # rich-root-pack
                                pack_repo.RepositoryFormatKnitPack5RichRoot, # 1.6.1-rich-root
                               )):
        fmt = pack_repo.RepositoryFormatKnitPack6RichRoot
    elif isinstance(r._format, (pack_repo.RepositoryFormatKnitPack6, # 1.9
                                pack_repo.RepositoryFormatKnitPack6RichRoot, # 1.9-rich-root
                               )):
        trace.note("Repository is already upgraded to: %s", r._format)
        return
    else:
        trace.note("** Do not know how to upgrade a repository of format:")
        trace.note("   %s", (r._format,))
        return

    t = r._transport
    t.rename('format', 'format-gi')
    add_revert_step(t.rename, 'format-gi', 'format')
    t.put_bytes('format',
        'Bazaar Repository Upgrade to 1.9 (%s) in progress\n' % (fmt,))
    add_revert_step(t.delete, 'format')
    pb = ui.ui_factory.nested_progress_bar()
    try:
        do_upgrade(r, fmt, pb)
    except:
        do_revert()
        pb.finished()
        raise
    pb.finished()


def do_upgrade(r, fmt, pb):
    from bzrlib import errors, repository, transport, ui, index, btree_index
    from bzrlib.repofmt import pack_repo
    t = r._transport
    index_t = t.clone('indices')
    btree_index_t = t.clone('indices-btree')

    try:
      btree_index_t.mkdir('.')
    except errors.FileExists:
      pass

    names_to_sizes = {}
    files = index_t.list_dir('.')
    step_count = len(files)*2
    for idx, n in enumerate(files):
        gi = index.GraphIndex(index_t, n, index_t.stat(n).st_size)
        key_count = gi.key_count()
        msg = 'copying %s (%5d)' % (n, key_count)
        pb.update(msg, 2*idx, step_count)
        new_bi = btree_index.BTreeBuilder(gi.node_ref_lists, gi._key_length)
        new_bi.add_nodes(x[1:] for x in gi.iter_all_entries())
        pb.update(msg, 2*idx+1, step_count)
        size = btree_index_t.put_file(n, new_bi.finish())
        names_to_sizes[n] = size


    ext_to_offset = {'rix':0, 'iix':1, 'tix':2, 'six':3}
    base_to_sizes = {}
    for n, size in names_to_sizes.iteritems():
        base, ext = n.split('.')
        sizes = base_to_sizes.setdefault(base, [None, None, None, None])
        sizes[ext_to_offset[ext]] = size

    # We upgrade all index files, but all of them may not be referenced by
    # pack-names, so make sure to only include the referenced ones.
    pack_name_gi = index.GraphIndex(t, 'pack-names', None)
    pack_name_gi.key_count() # Parse the header
    pack_name_bi = btree_index.BTreeBuilder(pack_name_gi.node_ref_lists,
                                            pack_name_gi._key_length)
    for index, key, value in pack_name_gi.iter_all_entries():
        for x in base_to_sizes[key[0]]:
            assert x is not None
        new_value = ' '.join(map(str, base_to_sizes[key[0]]))
        pack_name_bi.add_node(key, new_value)

    t.put_file('pack-names-btree', pack_name_bi.finish())

    del r
    # While we swap everything out, block other clients.
    t.rename('pack-names', 'pack-names-gi')
    add_revert_step(t.rename, 'pack-names-gi', 'pack-names')
    t.rename('indices', 'indices-gi')
    add_revert_step(t.rename, 'indices-gi', 'indices')
    t.rename('pack-names-btree', 'pack-names')
    add_revert_step(t.rename, 'pack-names', 'pack-names-btree')
    t.rename('indices-btree', 'indices')
    add_revert_step(t.rename, 'indices', 'indices-btree')
    t.put_bytes('format', fmt().get_format_string())
    # format will be deleted by the earlier steps


if __name__ == '__main__':
    import sys
    main(sys.argv[1:])
