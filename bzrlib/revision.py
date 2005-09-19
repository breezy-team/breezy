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


import bzrlib.errors


class Revision(object):
    """Single revision on a branch.

    Revisions may know their revision_hash, but only once they've been
    written out.  This is not stored because you cannot write the hash
    into the file it describes.

    After bzr 0.0.5 revisions are allowed to have multiple parents.

    parent_ids
        List of parent revision_ids
    """
    inventory_id = None
    inventory_sha1 = None
    revision_id = None
    timestamp = None
    message = None
    timezone = None
    committer = None
    
    def __init__(self, **args):
        self.__dict__.update(args)
        self.parent_ids = []
        self.parent_sha1s = []


    def __repr__(self):
        return "<Revision id %s>" % self.revision_id

    def __eq__(self, other):
        if not isinstance(other, Revision):
            return False
        return (self.inventory_id == other.inventory_id
                and self.inventory_sha1 == other.inventory_sha1
                and self.revision_id == other.revision_id
                and self.timestamp == other.timestamp
                and self.message == other.message
                and self.timezone == other.timezone
                and self.committer == other.committer)

    def __ne__(self, other):
        return not self.__eq__(other)

        

REVISION_ID_RE = None

def validate_revision_id(rid):
    """Check rid is syntactically valid for a revision id."""
    global REVISION_ID_RE
    if not REVISION_ID_RE:
        import re
        REVISION_ID_RE = re.compile('[\w.-]+@[\w.-]+--?\d+--?[0-9a-f]+\Z')

    if not REVISION_ID_RE.match(rid):
        raise ValueError("malformed revision-id %r" % rid)


def is_ancestor(revision_id, candidate_id, branch):
    """Return true if candidate_id is an ancestor of revision_id.

    A false negative will be returned if any intermediate descendent of
    candidate_id is not present in any of the revision_sources.
    
    revisions_source is an object supporting a get_revision operation that
    behaves like Branch's.
    """
    return candidate_id in branch.get_ancestry(revision_id)


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


def common_ancestor(revision_a, revision_b, revision_source):
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
    [rev_source.get_revision(r) for r in (ancestor_id, rev_id)]
    if ancestor_id == rev_id:
        return []
    def historical_lines(line):
        """Return a tuple of historical/non_historical lines, for sorting.
        The non_historical count is negative, since non_historical lines are
        a bad thing.
        """
        good_count = 0
        bad_count = 0
        for revision in line:
            if revision in revision_history:
                good_count += 1
            else:
                bad_count -= 1
        return good_count, bad_count
    active = [[rev_id]]
    successful_lines = []
    while len(active) > 0:
        new_active = []
        for line in active:
            for parent in rev_source.get_revision(line[-1]).parent_ids:
                line_copy = line[:]
                if parent == ancestor_id:
                    successful_lines.append(line_copy)
                else:
                    line_copy.append(parent)
                    new_active.append(line_copy)
        active = new_active
    if len(successful_lines) == 0:
        raise bzrlib.errors.NotAncestor(rev_id, ancestor_id)
    for line in successful_lines:
        line.reverse()
    if revision_history is not None:
        by_historical_lines = []
        for line in successful_lines:
            count = historical_lines(line)
            by_historical_lines.append((count, line))
        by_historical_lines.sort()
        if by_historical_lines[-1][0][0] > 0:
            return by_historical_lines[-1][1]
    assert len(successful_lines)
    successful_lines.sort(cmp, len)
    return successful_lines[-1]
