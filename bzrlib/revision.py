#! /usr/bin/env python
# -*- coding: UTF-8 -*-

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
from ElementTree import Element, ElementTree, SubElement

class Revision(XMLMixin):
    """Single revision on a branch.

    Revisions may know their revision_hash, but only once they've been
    written out.  This is not stored because you cannot write the hash
    into the file it describes.

    :todo: Perhaps make predecessor be a child element, not an attribute?
    """
    def __init__(self, **args):
        self.inventory_id = None
        self.revision_id = None
        self.timestamp = None
        self.message = None
        self.__dict__.update(args)


    def __repr__(self):
        if self.revision_id:
            return "<Revision id %s>" % self.revision_id

        
    def to_element(self):
        root = Element('changeset',
                       committer = self.committer,
                       timestamp = '%f' % self.timestamp,
                       revision_id = self.revision_id,
                       inventory_id = self.inventory_id)
        if self.precursor:
            root.set('precursor', self.precursor)
        root.text = '\n'
        
        msg = SubElement(root, 'message')
        msg.text = self.message
        msg.tail = '\n'

        return root

    def from_element(cls, root):
        cs = cls(committer = root.get('committer'),
                 timestamp = float(root.get('timestamp')),
                 precursor = root.get('precursor'),
                 revision_id = root.get('revision_id'),
                 inventory_id = root.get('inventory_id'))

        cs.message = root.findtext('message') # text of <message>
        return cs

    from_element = classmethod(from_element)

