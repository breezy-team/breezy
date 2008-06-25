# Copyright (C) 2005, 2006 Canonical Ltd
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""XML externalization support."""

# "XML is like violence: if it doesn't solve your problem, you aren't
# using enough of it." -- various

# importing this module is fairly slow because it has to load several
# ElementTree bits

from bzrlib import registry
from bzrlib.trace import mutter, warning

try:
    try:
        # it's in this package in python2.5
        from xml.etree.cElementTree import (ElementTree, SubElement, Element,
            XMLTreeBuilder, fromstring, tostring)
        import xml.etree as elementtree
    except ImportError:
        from cElementTree import (ElementTree, SubElement, Element,
                                  XMLTreeBuilder, fromstring, tostring)
        import elementtree.ElementTree
    ParseError = SyntaxError
except ImportError:
    mutter('WARNING: using slower ElementTree; consider installing cElementTree'
           " and make sure it's on your PYTHONPATH")
    # this copy is shipped with bzr
    from util.elementtree.ElementTree import (ElementTree, SubElement,
                                              Element, XMLTreeBuilder,
                                              fromstring, tostring)
    import util.elementtree as elementtree
    from xml.parsers.expat import ExpatError as ParseError

from bzrlib import errors


class Serializer(object):
    """Abstract object serialize/deserialize"""

    def write_inventory(self, inv, f):
        """Write inventory to a file"""
        raise NotImplementedError(self.write_inventory)

    def write_inventory_to_string(self, inv):
        raise NotImplementedError(self.write_inventory_to_string)

    def read_inventory_from_string(self, xml_string, revision_id=None):
        """Read xml_string into an inventory object.

        :param xml_string: The xml to read.
        :param revision_id: If not-None, the expected revision id of the
            inventory. Some serialisers use this to set the results' root
            revision. This should be supplied for deserialising all
            from-repository inventories so that xml5 inventories that were
            serialised without a revision identifier can be given the right
            revision id (but not for working tree inventories where users can
            edit the data without triggering checksum errors or anything).
        """
        try:
            return self._unpack_inventory(fromstring(xml_string), revision_id)
        except ParseError, e:
            raise errors.UnexpectedInventoryFormat(e)

    def read_inventory(self, f, revision_id=None):
        try:
            return self._unpack_inventory(self._read_element(f),
                revision_id=None)
        except ParseError, e:
            raise errors.UnexpectedInventoryFormat(e)

    def write_revision(self, rev, f):
        self._write_element(self._pack_revision(rev), f)

    def write_revision_to_string(self, rev):
        return tostring(self._pack_revision(rev)) + '\n'

    def read_revision(self, f):
        return self._unpack_revision(self._read_element(f))

    def read_revision_from_string(self, xml_string):
        return self._unpack_revision(fromstring(xml_string))

    def _write_element(self, elt, f):
        ElementTree(elt).write(f, 'utf-8')
        f.write('\n')

    def _read_element(self, f):
        return ElementTree().parse(f)


# performance tuning for elementree's serialiser. This should be
# sent upstream - RBC 20060523.
# the functions here are patched into elementtree at runtime.
import re
escape_re = re.compile("[&'\"<>]")
escape_map = {
    "&":'&amp;',
    "'":"&apos;", # FIXME: overkill
    "\"":"&quot;",
    "<":"&lt;",
    ">":"&gt;",
    }
def _escape_replace(match, map=escape_map):
    return map[match.group()]
 
def _escape_attrib(text, encoding=None, replace=None):
    # escape attribute value
    try:
        if encoding:
            try:
                text = elementtree.ElementTree._encode(text, encoding)
            except UnicodeError:
                return elementtree.ElementTree._encode_entity(text)
        if replace is None:
            return escape_re.sub(_escape_replace, text)
        else:
            text = replace(text, "&", "&amp;")
            text = replace(text, "'", "&apos;") # FIXME: overkill
            text = replace(text, "\"", "&quot;")
            text = replace(text, "<", "&lt;")
            text = replace(text, ">", "&gt;")
            return text
    except (TypeError, AttributeError):
        elementtree.ElementTree._raise_serialization_error(text)

elementtree.ElementTree._escape_attrib = _escape_attrib

escape_cdata_re = re.compile("[&<>]")
escape_cdata_map = {
    "&":'&amp;',
    "<":"&lt;",
    ">":"&gt;",
    }
def _escape_cdata_replace(match, map=escape_cdata_map):
    return map[match.group()]
 
def _escape_cdata(text, encoding=None, replace=None):
    # escape character data
    try:
        if encoding:
            try:
                text = elementtree.ElementTree._encode(text, encoding)
            except UnicodeError:
                return elementtree.ElementTree._encode_entity(text)
        if replace is None:
            return escape_cdata_re.sub(_escape_cdata_replace, text)
        else:
            text = replace(text, "&", "&amp;")
            text = replace(text, "<", "&lt;")
            text = replace(text, ">", "&gt;")
            return text
    except (TypeError, AttributeError):
        elementtree.ElementTree._raise_serialization_error(text)

elementtree.ElementTree._escape_cdata = _escape_cdata


class SerializerRegistry(registry.Registry):
    """Registry for serializer objects"""


format_registry = SerializerRegistry()
format_registry.register_lazy('4', 'bzrlib.xml4', 'serializer_v4')
format_registry.register_lazy('5', 'bzrlib.xml5', 'serializer_v5')
format_registry.register_lazy('6', 'bzrlib.xml6', 'serializer_v6')
format_registry.register_lazy('7', 'bzrlib.xml7', 'serializer_v7')
format_registry.register_lazy('8', 'bzrlib.xml8', 'serializer_v8')
