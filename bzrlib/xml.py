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


__copyright__ = "Copyright (C) 2005 Canonical Ltd."
__author__ = "Martin Pool <mbp@canonical.com>"

_ElementTree = None
def ElementTree(*args, **kwargs):
    global _ElementTree
    if _ElementTree is None:
        try:
            from cElementTree import ElementTree
        except ImportError:
            from elementtree.ElementTree import ElementTree
        _ElementTree = ElementTree
    return _ElementTree(*args, **kwargs)

_Element = None
def Element(*args, **kwargs):
    global _Element
    if _Element is None:
        try:
            from cElementTree import Element
        except ImportError:
            from elementtree.ElementTree import Element
        _Element = Element
    return _Element(*args, **kwargs)


_SubElement = None
def SubElement(*args, **kwargs):
    global _SubElement
    if _SubElement is None:
        try:
            from cElementTree import SubElement
        except ImportError:
            from elementtree.ElementTree import SubElement
        _SubElement = SubElement
    return _SubElement(*args, **kwargs)


import os, time
from trace import mutter

class XMLMixin:
    def to_element(self):
        raise Exception("XMLMixin.to_element must be overridden in concrete classes")
    
    def write_xml(self, f):
        ElementTree(self.to_element()).write(f, 'utf-8')
        f.write('\n')

    def read_xml(cls, f):
        return cls.from_element(ElementTree().parse(f))

    read_xml = classmethod(read_xml)

