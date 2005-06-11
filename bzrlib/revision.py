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


class Revision(XMLMixin):
    """Single revision on a branch.

    Revisions may know their revision_hash, but only once they've been
    written out.  This is not stored because you cannot write the hash
    into the file it describes.

    TODO: Perhaps make predecessor be a child element, not an attribute?
    """
    def __init__(self, **args):
        self.inventory_id = None
        self.inventory_sha1 = None
        self.revision_id = None
        self.timestamp = None
        self.message = None
        self.timezone = None
        self.committer = None
        self.precursor = None
        self.precursor_sha1 = None
        self.__dict__.update(args)


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

        return root


    def from_element(cls, elt):
        # <changeset> is deprecated...
        if elt.tag not in ('revision', 'changeset'):
            raise BzrError("unexpected tag in revision file: %r" % elt)

        cs = cls(committer = elt.get('committer'),
                 timestamp = float(elt.get('timestamp')),
                 precursor = elt.get('precursor'),
                 precursor_sha1 = elt.get('precursor_sha1'),
                 revision_id = elt.get('revision_id'),
                 inventory_id = elt.get('inventory_id'),
                 inventory_sha1 = elt.get('inventory_sha1')
                 )

        v = elt.get('timezone')
        cs.timezone = v and int(v)

        cs.message = elt.findtext('message') # text of <message>
        return cs

    from_element = classmethod(from_element)

