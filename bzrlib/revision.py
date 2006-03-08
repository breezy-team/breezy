# (C) 2005 Canonical

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

# TODO: Some kind of command-line display of revision properties: 
# perhaps show them in log -v and allow them as options to the commit command.


import bzrlib.errors
import bzrlib.errors as errors
from bzrlib.graph import node_distances, select_farthest, all_descendants, Graph
from bzrlib.osutils import contains_whitespace
from bzrlib.progress import DummyProgress

NULL_REVISION="null:"

class Revision(object):
    """Single revision on a branch.

    Revisions may know their revision_hash, but only once they've been
    written out.  This is not stored because you cannot write the hash
    into the file it describes.

    After bzr 0.0.5 revisions are allowed to have multiple parents.

    parent_ids
        List of parent revision_ids

    properties
        Dictionary of revision properties.  These are attached to the
        revision as extra metadata.  The name must be a single 
        word; the value can be an arbitrary string.
    """
    
    def __init__(self, revision_id, properties=None, **args):
        self.revision_id = revision_id
        self.properties = properties or {}
        self._check_properties()
        self.parent_ids = []
        self.parent_sha1s = []
        self.__dict__.update(args)

    def __repr__(self):
        return "<Revision id %s>" % self.revision_id

    def __eq__(self, other):
        if not isinstance(other, Revision):
            return False
        # FIXME: rbc 20050930 parent_ids are not being compared
        return (
                self.inventory_sha1 == other.inventory_sha1
                and self.revision_id == other.revision_id
                and self.timestamp == other.timestamp
                and self.message == other.message
                and self.timezone == other.timezone
                and self.committer == other.committer
                and self.properties == other.properties)

    def __ne__(self, other):
        return not self.__eq__(other)

    def _check_properties(self):
        """Verify that all revision properties are OK.
        """
        for name, value in self.properties.iteritems():
            if not isinstance(name, basestring) or contains_whitespace(name):
                raise ValueError("invalid property name %r" % name)
            if not isinstance(value, basestring):
                raise ValueError("invalid property value %r for %r" % 
                                 (name, value))

    def get_history(self, repository):
        """Return the canonical line-of-history for this revision.

        If ghosts are present this may differ in result from a ghost-free
        repository.
        """
        current_revision = self
        reversed_result = []
        while current_revision is not None:
            reversed_result.append(current_revision.revision_id)
            if not len (current_revision.parent_ids):
                reversed_result.append(None)
                current_revision = None
            else:
                next_revision_id = current_revision.parent_ids[0]
                current_revision = repository.get_revision(next_revision_id)
        reversed_result.reverse()
        return reversed_result


def is_ancestor(revision_id, candidate_id, branch):
    """Return true if candidate_id is an ancestor of revision_id.

    A false negative will be returned if any intermediate descendent of
    candidate_id is not present in any of the revision_sources.
    
    revisions_source is an object supporting a get_revision operation that
    behaves like Branch's.
    """
    return candidate_id in branch.repository.get_ancestry(revision_id)


def iter_ancestors(revision_id, revision_source, only_present=False):
    ancestors = (revision_id,)
    distance = 0
    while len(ancestors) > 0:
        new_ancestors = []
        for ancestor in ancestors:
            if not only_present:
                yield ancestor, distance
            try:
                revision = revision_source.get_revision(ancestor)
            except bzrlib.errors.NoSuchRevision, e:
                if e.revision == revision_id:
                    raise 
                else:
                    continue
            if only_present:
                yield ancestor, distance
            new_ancestors.extend(revision.parent_ids)
        ancestors = new_ancestors
        distance += 1


def find_present_ancestors(revision_id, revision_source):
    """Return the ancestors of a revision present in a branch.

    It's possible that a branch won't have the complete ancestry of
    one of its revisions.  

    """
    found_ancestors = {}
    anc_iter = enumerate(iter_ancestors(revision_id, revision_source,
                         only_present=True))
    for anc_order, (anc_id, anc_distance) in anc_iter:
        if not found_ancestors.has_key(anc_id):
            found_ancestors[anc_id] = (anc_order, anc_distance)
    return found_ancestors
    

def __get_closest(intersection):
    intersection.sort()
    matches = [] 
    for entry in intersection:
        if entry[0] == intersection[0][0]:
            matches.append(entry[2])
    return matches


def revision_graph(revision, revision_source):
    """Produce a graph of the ancestry of the specified revision.
    
    :return: root, ancestors map, descendants map
    """
    revision_source.lock_read()
    try:
        return _revision_graph(revision, revision_source)
    finally:
        revision_source.unlock()


def _revision_graph(revision, revision_source):
    """See revision_graph."""
    from bzrlib.tsort import topo_sort
    graph = revision_source.get_revision_graph(revision)
    # mark all no-parent revisions as being NULL_REVISION parentage.
    for node, parents in graph.items():
        if len(parents) == 0:
            graph[node] = [NULL_REVISION]
    # add NULL_REVISION to the graph
    graph[NULL_REVISION] = []

    # pick a root. If there are multiple roots
    # this could pick a random one.
    topo_order = topo_sort(graph.items())
    root = topo_order[0]

    ancestors = {}
    descendants = {}

    # map the descendants of the graph.
    # and setup our set based return graph.
    for node in graph.keys():
        descendants[node] = {}
    for node, parents in graph.items():
        for parent in parents:
            descendants[parent][node] = 1
        ancestors[node] = set(parents)

    assert root not in descendants[root]
    assert root not in ancestors[root]
    return root, ancestors, descendants


def combined_graph(revision_a, revision_b, revision_source):
    """Produce a combined ancestry graph.
    Return graph root, ancestors map, descendants map, set of common nodes"""
    root, ancestors, descendants = revision_graph(
        revision_a, revision_source)
    root_b, ancestors_b, descendants_b = revision_graph(
        revision_b, revision_source)
    if root != root_b:
        raise bzrlib.errors.NoCommonRoot(revision_a, revision_b)
    common = set()
    for node, node_anc in ancestors_b.iteritems():
        if node in ancestors:
            common.add(node)
        else:
            ancestors[node] = set()
        ancestors[node].update(node_anc)
    for node, node_dec in descendants_b.iteritems():
        if node not in descendants:
            descendants[node] = {}
        descendants[node].update(node_dec)
    return root, ancestors, descendants, common


def common_ancestor(revision_a, revision_b, revision_source, 
                    pb=DummyProgress()):
    if None in (revision_a, revision_b):
        return None
    # trivial optimisation
    if revision_a == revision_b:
        return revision_a
    try:
        try:
            pb.update('Picking ancestor', 1, 3)
            graph = revision_source.get_revision_graph_with_ghosts(
                [revision_a, revision_b])
            # convert to a NULL_REVISION based graph.
            ancestors = graph.get_ancestors()
            descendants = graph.get_descendants()
            common = set(graph.get_ancestry(revision_a)).intersection(
                     set(graph.get_ancestry(revision_b)))
            descendants[NULL_REVISION] = {}
            ancestors[NULL_REVISION] = []
            for root in graph.roots:
                descendants[NULL_REVISION][root] = 1
                ancestors[root].append(NULL_REVISION)
            if len(graph.roots) == 0:
                # no reachable roots - not handled yet.
                raise bzrlib.errors.NoCommonAncestor(revision_a, revision_b)
            root = NULL_REVISION
            common.add(NULL_REVISION)
        except bzrlib.errors.NoCommonRoot:
            raise bzrlib.errors.NoCommonAncestor(revision_a, revision_b)
            
        pb.update('Picking ancestor', 2, 3)
        distances = node_distances (descendants, ancestors, root)
        pb.update('Picking ancestor', 3, 2)
        farthest = select_farthest(distances, common)
        if farthest is None or farthest == NULL_REVISION:
            raise bzrlib.errors.NoCommonAncestor(revision_a, revision_b)
    finally:
        pb.clear()
    return farthest


class MultipleRevisionSources(object):
    """Proxy that looks in multiple branches for revisions."""
    def __init__(self, *args):
        object.__init__(self)
        assert len(args) != 0
        self._revision_sources = args

    def revision_parents(self, revision_id):
        for source in self._revision_sources:
            try:
                return source.revision_parents(revision_id)
            except (errors.WeaveRevisionNotPresent, errors.NoSuchRevision), e:
                pass
        raise e

    def get_revision(self, revision_id):
        for source in self._revision_sources:
            try:
                return source.get_revision(revision_id)
            except bzrlib.errors.NoSuchRevision, e:
                pass
        raise e

    def get_revision_graph(self, revision_id):
        # we could probe incrementally until the pending
        # ghosts list stop growing, but its cheaper for now
        # to just ask for the complete graph for each repository.
        graphs = []
        for source in self._revision_sources:
            ghost_graph = source.get_revision_graph_with_ghosts()
            graphs.append(ghost_graph)
        absent = 0
        for graph in graphs:
            if not revision_id in graph.get_ancestors():
                absent += 1
        if absent == len(graphs):
            raise errors.NoSuchRevision(self._revision_sources[0], revision_id)

        # combine the graphs
        result = {}
        pending = set([revision_id])
        def find_parents(node_id):
            """find the parents for node_id."""
            for graph in graphs:
                ancestors = graph.get_ancestors()
                try:
                    return ancestors[node_id]
                except KeyError:
                    pass
            raise errors.NoSuchRevision(self._revision_sources[0], node_id)
        while len(pending):
            # all the graphs should have identical parent lists
            node_id = pending.pop()
            try:
                result[node_id] = find_parents(node_id)
                for parent_node in result[node_id]:
                    if not parent_node in result:
                        pending.add(parent_node)
            except errors.NoSuchRevision:
                # ghost, ignore it.
                pass
        return result

    def get_revision_graph_with_ghosts(self, revision_ids):
        # query all the sources for their entire graphs 
        # and then build a combined graph for just
        # revision_ids.
        graphs = []
        for source in self._revision_sources:
            ghost_graph = source.get_revision_graph_with_ghosts()
            graphs.append(ghost_graph.get_ancestors())
        for revision_id in revision_ids:
            absent = 0
            for graph in graphs:
                    if not revision_id in graph:
                        absent += 1
            if absent == len(graphs):
                raise errors.NoSuchRevision(self._revision_sources[0],
                                            revision_id)

        # combine the graphs
        result = Graph()
        pending = set(revision_ids)
        done = set()
        def find_parents(node_id):
            """find the parents for node_id."""
            for graph in graphs:
                try:
                    return graph[node_id]
                except KeyError:
                    pass
            raise errors.NoSuchRevision(self._revision_sources[0], node_id)
        while len(pending):
            # all the graphs should have identical parent lists
            node_id = pending.pop()
            try:
                parents = find_parents(node_id)
                for parent_node in parents:
                    # queued or done? 
                    if (parent_node not in pending and
                        parent_node not in done):
                        # no, queue
                        pending.add(parent_node)
                result.add_node(node_id, parents)
                done.add(node_id)
            except errors.NoSuchRevision:
                # ghost
                result.add_ghost(node_id)
                continue
        return result

    def lock_read(self):
        for source in self._revision_sources:
            source.lock_read()

    def unlock(self):
        for source in self._revision_sources:
            source.unlock()


def get_intervening_revisions(ancestor_id, rev_id, rev_source, 
                              revision_history=None):
    """Find the longest line of descent from maybe_ancestor to revision.
    Revision history is followed where possible.

    If ancestor_id == rev_id, list will be empty.
    Otherwise, rev_id will be the last entry.  ancestor_id will never appear.
    If ancestor_id is not an ancestor, NotAncestor will be thrown
    """
    root, ancestors, descendants = revision_graph(rev_id, rev_source)
    if len(descendants) == 0:
        raise NoSuchRevision(rev_source, rev_id)
    if ancestor_id not in descendants:
        rev_source.get_revision(ancestor_id)
        raise bzrlib.errors.NotAncestor(rev_id, ancestor_id)
    root_descendants = all_descendants(descendants, ancestor_id)
    root_descendants.add(ancestor_id)
    if rev_id not in root_descendants:
        raise bzrlib.errors.NotAncestor(rev_id, ancestor_id)
    distances = node_distances(descendants, ancestors, ancestor_id,
                               root_descendants=root_descendants)

    def best_ancestor(rev_id):
        best = None
        for anc_id in ancestors[rev_id]:
            try:
                distance = distances[anc_id]
            except KeyError:
                continue
            if revision_history is not None and anc_id in revision_history:
                return anc_id
            elif best is None or distance > best[1]:
                best = (anc_id, distance)
        return best[0]

    next = rev_id
    path = []
    while next != ancestor_id:
        path.append(next)
        next = best_ancestor(next)
    path.reverse()
    return path
