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


"""Working tree content filtering support.

Filters have the following signatures::

    read_filter(chunks) -> chunks
    write_filter(chunks, context) -> chunks

where:

 * chunks is an iterator over a sequence of 8-bit utf-8 strings

 * context is an optional object (possibly None) providing filters access
   to interesting information, e.g. the relative path of the file.

Note that context is currently only supported for write filters.
"""


import cStringIO
from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
from bzrlib import (
    errors,
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


class ContentFilterContext(object):
    """Object providing information that filters can use.
    
    In the future, this is likely to be expanded to include
    details like the Revision when this file was last updated.
    """

    def __init__(self, relpath=None):
        """Create a context.

        :param relpath: the relative path or None if this context doesn't
           support that information.
        """
        self._relpath = relpath

    def relpath(self):
        """Relative path of file to tree-root."""
        if self._relpath is None:
            raise NotImplementedError(self.relpath)
        else:
            return self._relpath


def filtered_input_file(f, filters):
    """Get an input file that converts external to internal content.
    
    :param f: the original input file
    :param filters: the stack of filters to apply
    :return: a file-like object
    """
    if filters:
        chunks = [f.read()]
        for filter in filters:
            if filter.reader is not None:
                chunks = filter.reader(chunks)
        return cStringIO.StringIO(''.join(chunks))
    else:
        return f


def filtered_output_lines(chunks, filters, context=None):
    """Convert output lines from internal to external format.
    
    :param chunks: an iterator containing the original content
    :param filters: the stack of filters to apply
    :param context: a ContentFilterContext object passed to
        each filter
    :return: an iterator containing the content to output
    """
    if filters:
        for filter in reversed(filters):
            if filter.writer is not None:
                chunks = filter.writer(chunks, context)
    return chunks


def sha_file_by_name(name, filters):
    """Get sha of internal content given external content.
    
    :param name: path to file
    :param filters: the stack of filters to apply
    """
    if filters:
        f = open(name, 'rb', 65000)
        return osutils.sha_strings(filtered_input_file(f, filters))
    else:
        return osutils.sha_file_by_name(name)


# The registry of filter stacks indexed by name.
# (This variable should be treated as private to this module as its
# implementation may well change in the future.)
_filter_stacks_registry = {}


# Cache of preferences -> stack
_stack_cache = {}


def register_filter_stack_map(name, stack_map):
    """Register the filter stacks to use for various preference values.

    :param name: the preference/filter-stack name
    :param stack_map: a dictionary where
      the keys are preference values to match and
      the values are the matching stack of filters for each
    """
    if _filter_stacks_registry.has_key(name):
        raise errors.BzrError(
            "filter stack for %s already installed" % name)
    _filter_stacks_registry[name] = stack_map


def _get_registered_names():
    """Get the list of names with filters registered."""
    # Note: We may want to intelligently order these later.
    # If so, the register_ fn will need to support an optional priority.
    return _filter_stacks_registry.keys()


def _get_filter_stack_for(preferences):
    """Get the filter stack given a sequence of preferences.
    
    :param preferences: a sequence of (name,value) tuples where
      name is the preference name and
      value is the key into the filter stack map regsitered
      for that preference.
    """
    if preferences is None:
        return []
    stack = _stack_cache.get(preferences)
    if stack is not None:
        return stack
    stack = []
    for k, v in preferences:
        stacks_by_values = _filter_stacks_registry.get(k)
        if stacks_by_values is not None:
            items = stacks_by_values.get(v)
            if items:
                stack.extend(items)
    _stack_cache[preferences] = stack
    return stack


def _reset_registry(value=None):
    """Reset the filter stack registry.

    This function is provided to aid testing. The expected usage is::

      old = _reset_registry()
      # run tests
      _reset_registry(old)

    :param value: the value to set the registry to or None for an empty one.
    :return: the existing value before it reset.
    """
    global _filter_stacks_registry
    original = _filter_stacks_registry.copy()
    if value is None:
        _filter_stacks_registry.clear()
    else:
        _filter_stacks_registry = value
    _stack_cache.clear()
    return original
