#! /usr/bin/env python

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

"""XML externalization support."""

# "XML is like violence: if it doesn't solve your problem, you aren't
# using enough of it." -- various

# importing this module is fairly slow because it has to load several
# ElementTree bits

from bzrlib.trace import mutter, warning

try:
    from cElementTree import (ElementTree, SubElement, Element,
                              XMLTreeBuilder, fromstring, tostring)
except ImportError:
    from warnings import warn
    warn('using slower ElementTree; consider installing cElementTree')
    from util.elementtree.ElementTree import (ElementTree, SubElement,
                                              Element, XMLTreeBuilder,
                                              fromstring, tostring)

from bzrlib.inventory import ROOT_ID, Inventory, InventoryEntry
from bzrlib.revision import Revision, RevisionReference        
from bzrlib.errors import BzrError


class Serializer(object):
    """Abstract object serialize/deserialize"""
    def write_inventory(self, inv, f):
        """Write inventory to a file"""
        elt = self._pack_inventory(inv)
        self._write_element(elt, f)

    def write_inventory_to_string(self, inv):
        return tostring(self._pack_inventory(inv))

    def read_inventory_from_string(self, xml_string):
        return self._unpack_inventory(fromstring(xml_string))

    def read_inventory(self, f):
        return self._unpack_inventory(self._read_element(f))

    def write_revision(self, rev, f):
        self._write_element(self._pack_revision(rev), f)

    def write_revision_to_string(self, rev):
        return tostring(self._pack_revision(rev), f)

    def read_revision(self, f):
        return self._unpack_revision(self._read_element(f))

    def read_revision_from_string(self, xml_string):
        return self._unpack_revision(fromstring(xml_string))

    def _write_element(self, elt, f):
        ElementTree(elt).write(f, 'utf-8')
        f.write('\n')

    def _read_element(self, f):
        return ElementTree().parse(f)

