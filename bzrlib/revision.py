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




from xml import XMLMixin

try:
    from cElementTree import Element, ElementTree, SubElement
except ImportError:
    from elementtree.ElementTree import Element, ElementTree, SubElement

from errors import BzrError


class RevisionReference:
    """
    Reference to a stored revision.

    Includes the revision_id and revision_sha1.
    """
    revision_id = None
    revision_sha1 = None
    def __init__(self, revision_id, revision_sha1):
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
                


class Revision(XMLMixin):
    """Single revision on a branch.

    Revisions may know their revision_hash, but only once they've been
    written out.  This is not stored because you cannot write the hash
    into the file it describes.

    After bzr 0.0.5 revisions are allowed to have multiple parents.
    To support old clients this is written out in a slightly redundant
    form: the first parent as the predecessor.  This will eventually
    be dropped.

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

    def _get_precursor(self):
        from warnings import warn
        warn("Revision.precursor is deprecated", stacklevel=2)
        if self.parents:
            return self.parents[0].revision_id
        else:
            return None


    def _get_precursor_sha1(self):
        from warnings import warn
        warn("Revision.precursor_sha1 is deprecated", stacklevel=2)
        if self.parents:
            return self.parents[0].revision_sha1
        else:
            return None    


    def _fail(self):
        raise Exception("can't assign to precursor anymore")


    precursor = property(_get_precursor, _fail, _fail)
    precursor_sha1 = property(_get_precursor_sha1, _fail, _fail)



    def __repr__(self):
        return "<Revision id %s>" % self.revision_id

        
    def to_element(self):
        root = Element('revision',
                       committer = self.committer,
                       timestamp = '%.9f' % self.timestamp,
                       revision_id = self.revision_id,
                       inventory_id = self.inventory_id,
                       inventory_sha1 = self.inventory_sha1,
                       )
        if self.timezone:
            root.set('timezone', str(self.timezone))
        if self.precursor:
            root.set('precursor', self.precursor)
            if self.precursor_sha1:
                root.set('precursor_sha1', self.precursor_sha1)
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
        raise BzrError("unexpected tag in revision file: %r" % elt)

    rev = Revision(committer = elt.get('committer'),
                   timestamp = float(elt.get('timestamp')),
                   revision_id = elt.get('revision_id'),
                   inventory_id = elt.get('inventory_id'),
                   inventory_sha1 = elt.get('inventory_sha1')
                   )

    precursor = elt.get('precursor')
    precursor_sha1 = elt.get('precursor_sha1')

    pelts = elt.find('parents')

    if precursor:
        # revisions written prior to 0.0.5 have a single precursor
        # give as an attribute
        rev_ref = RevisionReference(precursor, precursor_sha1)
        rev.parents.append(rev_ref)
    elif pelts:
        for p in pelts:
            assert p.tag == 'revision_ref', \
                   "bad parent node tag %r" % p.tag
            rev_ref = RevisionReference(p.get('revision_id'),
                                        p.get('revision_sha1'))
            rev.parents.append(rev_ref)

    v = elt.get('timezone')
    rev.timezone = v and int(v)

    rev.message = elt.findtext('message') # text of <message>
    return rev
