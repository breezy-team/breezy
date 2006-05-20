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
    mutter('WARNING: using slower ElementTree; consider installing cElementTree'
           " and make sure it's on your PYTHONPATH")
    from util.elementtree.ElementTree import (ElementTree, SubElement,
                                              Element, XMLTreeBuilder,
                                              fromstring, tostring)

from bzrlib.errors import BzrError


class Serializer(object):
    """Abstract object serialize/deserialize"""
    def write_inventory(self, inv, f):
        """Write inventory to a file"""
        elt = self._pack_inventory(inv)
        self._write_element(elt, f)

    def write_inventory_to_string(self, inv):
        return tostring(self._pack_inventory(inv)) + '\n'

    def read_inventory_from_string(self, xml_string):
        return self._unpack_inventory(fromstring(xml_string))

    def read_inventory(self, f):
        return self._unpack_inventory(self._read_element(f))

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


# before in bench_add_kernel_like
# 10831        10824   9384.4890   1847.5270   elementtree.ElementTree:662(_write)
#+10824            0   9295.0140   1761.0460   +elementtree.ElementTree:662(_write)
#+32471            0   4585.8950   1331.2060   +elementtree.ElementTree:812(_escape_attrib)
#after switching to text.replace rather than string.replace.
# 10831        10824   7486.1120   1832.2340   elementtree.ElementTree:662(_write)
#+10824            0   7397.3120   1745.6300   +elementtree.ElementTree:662(_write)
#+32471            0   2762.3760   1300.3990   +bzrlib.xml_serializer:85(_escape_attrib)

 
import elementtree.ElementTree
import re
escape_re = re.compile("&'\"<>")
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

escape_cdata_re = re.compile("&<>")
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
