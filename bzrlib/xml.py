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

"""XML externalization support."""

# "XML is like violence: if it doesn't solve your problem, you aren't
# using enough of it." -- various

# importing this module is fairly slow because it has to load several ElementTree bits
try:
    from util.cElementTree import ElementTree, SubElement, Element
except ImportError:
    from util.elementtree.ElementTree import ElementTree, SubElement, Element


def pack_xml(o, f):
    """Write object o to file f as XML.

    o must provide a to_element method.
    """
    ElementTree(o.to_element()).write(f, 'utf-8')
    f.write('\n')


def unpack_xml(cls, f):
    return cls.from_element(ElementTree().parse(f))
