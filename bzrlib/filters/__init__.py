# Copyright (C) 2008 Canonical Ltd
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


"""Working tree content filtering support."""

import cStringIO
from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
from bzrlib import (
        osutils,
        )
""")


class ContentFilter(object):

    def __init__(self, reader, writer):
        """Create a filter that converts content while reading and writing.
 
        :param reader: function for converting external to internal content
        :param writer: function for converting internal to external content
        """
        self.reader = reader
        self.writer = writer


def filtered_input(f, filters):
    """Get an input file that converts external to internal content.
    
    :param f: the original input file
    :param filters: the stack of filters to apply
    :return: a file-like object
    """
    if filters:
        lines = f.readlines()
        for filter in filters:
            lines = filter.reader(lines)
        return cStringIO.cStringIO(''.join(lines))
    else:
        return f


def filtered_writelines(f, lines, filters):
    """Output lines to a file converting internal to external content.
    
    :param lines: an iterator containing the content to output
    :param filters: the stack of filters to apply
    """
    if filters:
        strings = list(lines)
        for filter in reversed(filters):
            strings = filter.writer(strings)
        lines = iter(strings)
    f.writelines(lines)


def sha_file_by_name(name):
    """Get sha of internal content given external content."""
    filters = filters_for_path(name)
    if filters:
        f = file(name, 'rb', buffering=65000)
        return osutils.sha_strings(filtered_input(f, filters))
    else:
        return osutils.sha_file_by_name(name)


def filters_for_path(path):
    """Return the stack of content filters for a path.
    
    Readers should be applied in first-to-last order.
    Writers should be applied in last-to-first order.
    """
    result = []
    # TODO: decide which filters to apply by consulting
    # the to-be-agreed sources, e.g.:
    # * config settings
    # * path pattern matching
    # * version properties
    # * filters registered by plugins.
    return result
