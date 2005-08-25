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


class RevisionReference(object):
    """
    Reference to a stored revision.

    Includes the revision_id and revision_sha1.
    """
    revision_id = None
    revision_sha1 = None
    def __init__(self, revision_id, revision_sha1=None):
        if revision_id == None \
           or isinstance(revision_id, basestring):
            self.revision_id = revision_id
        else:
            raise ValueError('bad revision_id %r' % revision_id)

        if revision_sha1 != None:
            if isinstance(revision_sha1, basestring) \
               and len(revision_sha1) == 40:
                self.revision_sha1 = revision_sha1
            else:
                raise ValueError('bad revision_sha1 %r' % revision_sha1)
                


class Revision(object):
    """Single revision on a branch.

    Revisions may know their revision_hash, but only once they've been
    written out.  This is not stored because you cannot write the hash
    into the file it describes.

    After bzr 0.0.5 revisions are allowed to have multiple parents.

    parents
        List of parent revisions, each is a RevisionReference.
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
        self.parents = []


    def __repr__(self):
        return "<Revision id %s>" % self.revision_id

        
    def to_element(self):
        from bzrlib.xml import Element, SubElement
        
        root = Element('revision',
                       committer = self.committer,
                       timestamp = '%.9f' % self.timestamp,
                       revision_id = self.revision_id,
                       inventory_id = self.inventory_id,
                       inventory_sha1 = self.inventory_sha1,
                       )
        if self.timezone:
            root.set('timezone', str(self.timezone))
        root.text = '\n'
        
        msg = SubElement(root, 'message')
        msg.text = self.message
        msg.tail = '\n'

        if self.parents:
            pelts = SubElement(root, 'parents')
            pelts.tail = pelts.text = '\n'
            for rr in self.parents:
                assert isinstance(rr, RevisionReference)
                p = SubElement(pelts, 'revision_ref')
                p.tail = '\n'
                assert rr.revision_id
                p.set('revision_id', rr.revision_id)
                if rr.revision_sha1:
                    p.set('revision_sha1', rr.revision_sha1)

        return root


    def from_element(cls, elt):
        return unpack_revision(elt)

    from_element = classmethod(from_element)



def unpack_revision(elt):
    """Convert XML element into Revision object."""
    # <changeset> is deprecated...
    if elt.tag not in ('revision', 'changeset'):
        raise bzrlib.errors.BzrError("unexpected tag in revision file: %r" % elt)

    rev = Revision(committer = elt.get('committer'),
                   timestamp = float(elt.get('timestamp')),
                   revision_id = elt.get('revision_id'),
                   inventory_id = elt.get('inventory_id'),
                   inventory_sha1 = elt.get('inventory_sha1')
                   )

    precursor = elt.get('precursor')
    precursor_sha1 = elt.get('precursor_sha1')

    pelts = elt.find('parents')

    if pelts:
        for p in pelts:
            assert p.tag == 'revision_ref', \
                   "bad parent node tag %r" % p.tag
            rev_ref = RevisionReference(p.get('revision_id'),
                                        p.get('revision_sha1'))
            rev.parents.append(rev_ref)

        if precursor:
            # must be consistent
            prec_parent = rev.parents[0].revision_id
            assert prec_parent == precursor
    elif precursor:
        # revisions written prior to 0.0.5 have a single precursor
        # give as an attribute
        rev_ref = RevisionReference(precursor, precursor_sha1)
        rev.parents.append(rev_ref)

    v = elt.get('timezone')
    rev.timezone = v and int(v)

    rev.message = elt.findtext('message') # text of <message>
    return rev



REVISION_ID_RE = None

def validate_revision_id(rid):
    """Check rid is syntactically valid for a revision id."""
    global REVISION_ID_RE
    if not REVISION_ID_RE:
        import re
        REVISION_ID_RE = re.compile('[\w.-]+@[\w.-]+--?\d+--?[0-9a-f]+\Z')

    if not REVISION_ID_RE.match(rid):
        raise ValueError("malformed revision-id %r" % rid)

def is_ancestor(revision_id, candidate_id, revision_source):
    """Return true if candidate_id is an ancestor of revision_id.
    A false negative will be returned if any intermediate descendent of
    candidate_id is not present in any of the revision_sources.
    
    revisions_source is an object supporting a get_revision operation that
    behaves like Branch's.
    """

    for ancestor_id, distance in iter_ancestors(revision_id, revision_source):
        if ancestor_id == candidate_id:
            return True
    return False

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
            new_ancestors.extend([p.revision_id for p in revision.parents])
        ancestors = new_ancestors
        distance += 1


def find_present_ancestors(revision_id, revision_source):
    found_ancestors = {}
    count = 0
    anc_iter = enumerate(iter_ancestors(revision_id, revision_source,
                         only_present=True))
    for anc_order, (anc_id, anc_distance) in anc_iter:
        if not found_ancestors.has_key(anc_id):
            found_ancestors[anc_id] = (anc_order, anc_distance)
    return found_ancestors
    
class AmbiguousBase(bzrlib.errors.BzrError):
    def __init__(self, bases):
        msg = "The correct base is unclear, becase %s are all equally close" %\
            ", ".join(bases)
        bzrlib.errors.BzrError.__init__(self, msg)
        self.bases = bases

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
    def get_closest(intersection):
        intersection.sort()
        matches = [] 
        for entry in intersection:
            if entry[0] == intersection[0][0]:
                matches.append(entry[2])
        return matches

    a_closest = get_closest(a_intersection)
    if len(a_closest) == 0:
        return None
    b_closest = get_closest(b_intersection)
    assert len(b_closest) != 0
    mutter ("a_closest %r" % a_closest)
    mutter ("b_closest %r" % b_closest)
    if a_closest[0] in b_closest:
        return a_closest[0]
    elif b_closest[0] in a_closest:
        return b_closest[0]
    else:
        raise AmbiguousBase((a_closest[0], b_closest[0]))
    return a_closest[0]

class MultipleRevisionSources(object):
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
