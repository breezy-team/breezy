
from bzrlib import branch

def get_gcindex(path):
    b = branch.Branch.open(path)
    b.lock_read()
    r = b.repository
    rev_id = b.last_revision()
    rev_key = (rev_id,)
    gcindex = r.revisions._index
    return b, rev_key, gcindex


def get_bindex(path):
    b = branch.Branch.open(path)
    b.lock_read()
    r = b.repository
    rev_id = b.last_revision()
    rev_key = (rev_id,)
    bindex = r.revisions._index._graph_index._indices[0]
    return b, rev_key, bindex


def ancestry_from_get_ancestry(path):
    b, rev_key, bindex = get_bindex(path)
    keys = set([rev_key])
    search_keys = set([rev_key])
    parent_map = {}
    generation = 0
    while search_keys:
        generation += 1
        missing_keys, search_keys = bindex.get_ancestry(search_keys, 0,
                                                        parent_map)
        # print '%4d\t%5d\t%5d' % (generation, len(search_keys),
        #                          len(parent_map))
    b.unlock()

def ancestry_from_get_parent_map(path):
    b, rev_key, gcindex = get_gcindex(path)
    search_keys = set([rev_key])
    parent_map = {}
    generation = 0
    while search_keys:
        next_parent_map = gcindex.get_parent_map(search_keys)
        next_parent_keys = set()
        map(next_parent_keys.update, next_parent_map.itervalues())
        parent_map.update(next_parent_map)
        next_parent_keys = next_parent_keys.difference(parent_map)
        generation += 1
        # print '%4d\t%5d\t%5d' % (generation, len(search_keys),
        #                          len(parent_map))
        search_keys = next_parent_keys
    b.unlock()
