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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""XML externalization support."""

# "XML is like violence: if it doesn't solve your problem, you aren't
# using enough of it." -- various

# importing this module is fairly slow because it has to load several
# ElementTree bits

from bzrlib.serializer import Serializer
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


class XMLSerializer(Serializer):
    """Abstract XML object serialize/deserialize"""

    squashes_xml_invalid_characters = True

    def read_inventory_from_string(self, xml_string, revision_id=None,
                                   entry_cache=None):
        """Read xml_string into an inventory object.

        :param xml_string: The xml to read.
        :param revision_id: If not-None, the expected revision id of the
            inventory. Some serialisers use this to set the results' root
            revision. This should be supplied for deserialising all
            from-repository inventories so that xml5 inventories that were
            serialised without a revision identifier can be given the right
            revision id (but not for working tree inventories where users can
            edit the data without triggering checksum errors or anything).
        :param entry_cache: An optional cache of InventoryEntry objects. If
            supplied we will look up entries via (file_id, revision_id) which
            should map to a valid InventoryEntry (File/Directory/etc) object.
        """
        try:
            return self._unpack_inventory(fromstring(xml_string), revision_id,
                                          entry_cache=entry_cache)
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


def escape_invalid_chars(message):
    """Escape the XML-invalid characters in a commit message.

    :param message: Commit message to escape
    :return: tuple with escaped message and number of characters escaped
    """
    if message is None:
        return None, 0
    # Python strings can include characters that can't be
    # represented in well-formed XML; escape characters that
    # aren't listed in the XML specification
    # (http://www.w3.org/TR/REC-xml/#NT-Char).
    return re.subn(u'[^\x09\x0A\x0D\u0020-\uD7FF\uE000-\uFFFD]+',
            lambda match: match.group(0).encode('unicode_escape'),
            message)
