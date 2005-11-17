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
from bzrlib.graph import node_distances, select_farthest, all_descendants
from bzrlib.osutils import contains_whitespace

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
        self.__dict__.update(args)
        self.parent_ids = []
        self.parent_sha1s = []

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


def is_ancestor(revision_id, candidate_id, branch):
    """Return true if candidate_id is an ancestor of revision_id.

    A false negative will be returned if any intermediate descendent of
    candidate_id is not present in any of the revision_sources.
    
    revisions_source is an object supporting a get_revision operation that
    behaves like Branch's.
    """
    return candidate_id in branch.storage.get_ancestry(revision_id)


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


def old_common_ancestor(revision_a, revision_b, revision_source):
    """Find the ancestor common to both revisions that is closest to both.
    """
    from bzrlib.trace import mutter
    a_ancestors = find_present_ancestors(revision_a, revision_source)
    b_ancestors = find_present_ancestors(revision_b, revision_source)
    a_intersection = []
    b_intersection = []
    # a_order is used as a tie-breaker when two equally-good bases are found
    for revision, (a_order, a_distance) in a_ancestors.iteritems():
        if b_ancestors.has_key(revision):
            a_intersection.append((a_distance, a_order, revision))
            b_intersection.append((b_ancestors[revision][1], a_order, revision))
    mutter("a intersection: %r" % a_intersection)
    mutter("b intersection: %r" % b_intersection)

    a_closest = __get_closest(a_intersection)
    if len(a_closest) == 0:
        return None
    b_closest = __get_closest(b_intersection)
    assert len(b_closest) != 0
    mutter ("a_closest %r" % a_closest)
    mutter ("b_closest %r" % b_closest)
    if a_closest[0] in b_closest:
        return a_closest[0]
    elif b_closest[0] in a_closest:
        return b_closest[0]
    else:
        raise bzrlib.errors.AmbiguousBase((a_closest[0], b_closest[0]))
    return a_closest[0]

def revision_graph(revision, revision_source):
    """Produce a graph of the ancestry of the specified revision.
    Return root, ancestors map, descendants map

    TODO: Produce graphs with the NULL revision as root, so that we can find
    a common even when trees are not branches don't represent a single line
    of descent.
    RBC: 20051024: note that when we have two partial histories, this may not
         be possible. But if we are willing to pretend :)... sure.
    """
    ancestors = {}
    descendants = {}
    lines = [revision]
    root = None
    descendants[revision] = {}
    while len(lines) > 0:
        new_lines = set()
        for line in lines:
            if line == NULL_REVISION:
                parents = []
                root = NULL_REVISION
            else:
                try:
                    rev = revision_source.get_revision(line)
                    parents = list(rev.parent_ids)
                    if len(parents) == 0:
                        parents = [NULL_REVISION]
                except bzrlib.errors.NoSuchRevision:
                    if line == revision:
                        raise
                    parents = None
            if parents is not None:
                for parent in parents:
                    if parent not in ancestors:
                        new_lines.add(parent)
                    if parent not in descendants:
                        descendants[parent] = {}
                    descendants[parent][line] = 1
            if parents is not None:
                ancestors[line] = set(parents)
        lines = new_lines
    if root is None:
        # The history for revision becomes inaccessible without
        # actually hitting a no-parents revision. This then
        # makes these asserts below trigger. So, if root is None
        # determine the actual root by walking the accessible tree
        # and then stash NULL_REVISION at the end.
        root = NULL_REVISION
        descendants[root] = {}
        # for every revision, check we can access at least
        # one parent, if we cant, add NULL_REVISION and
        # a link
        for rev in ancestors:
            if len(ancestors[rev]) == 0:
                raise RuntimeError('unreachable code ?!')
            ok = False
            for parent in ancestors[rev]:
                if parent in ancestors:
                    ok = True
            if ok:
                continue
            descendants[root][rev] = 1
            ancestors[rev].add(root)
        ancestors[root] = set()
    assert root not in descendants[root]
    assert root not in ancestors[root]
    return root, ancestors, descendants


def combined_graph(revision_a, revision_b, revision_source):
    """Produce a combined ancestry graph.
    Return graph root, ancestors map, descendants map, set of common nodes"""
    root, ancestors, descendants = revision_graph(revision_a, revision_source)
    root_b, ancestors_b, descendants_b = revision_graph(revision_b, 
                                                        revision_source)
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


def common_ancestor(revision_a, revision_b, revision_source):
    try:
        root, ancestors, descendants, common = \
            combined_graph(revision_a, revision_b, revision_source)
    except bzrlib.errors.NoCommonRoot:
        raise bzrlib.errors.NoCommonAncestor(revision_a, revision_b)
        
    distances = node_distances (descendants, ancestors, root)
    farthest = select_farthest(distances, common)
    if farthest is None or farthest == NULL_REVISION:
        raise bzrlib.errors.NoCommonAncestor(revision_a, revision_b)
    return farthest


class MultipleRevisionSources(object):
    """Proxy that looks in multiple branches for revisions."""
    def __init__(self, *args):
        object.__init__(self)
        assert len(args) != 0
        self._revision_sources = args

    def get_revision(self, revision_id):
        for source in self._revision_sources:
            try:
                return source.get_revision(revision_id)
            except bzrlib.errors.NoSuchRevision, e:
                pass
        raise e

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
