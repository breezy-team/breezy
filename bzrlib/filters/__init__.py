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

A filter consists of a read converter, write converter pair.
The content in the working tree is called the convenience format
while the content actually stored in called the canonical format.
The read converter produces canonical content from convenience
content while the writer goes the other way.

Converters have the following signatures::

    read_converter(chunks) -> chunks
    write_converter(chunks, context) -> chunks

where:

 * chunks is an iterator over a sequence of byte strings

 * context is an optional ContentFilterContent object (possibly None)
   providing converters access to interesting information, e.g. the
   relative path of the file.

Note that context is currently only supported for write converters.
"""


import cStringIO, sha
from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
from bzrlib import (
    errors,
    osutils,
    registry,
    )
""")


class ContentFilter(object):

    def __init__(self, reader, writer):
        """Create a filter that converts content while reading and writing.
 
        :param reader: function for converting convenience to canonical content
        :param writer: function for converting canonical to convenience content
        """
        self.reader = reader
        self.writer = writer

    def __repr__(self):
        return "reader: %s, writer: %s" % (self.reader,self.writer)


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


def filtered_output_bytes(chunks, filters, context=None):
    """Convert byte chunks from internal to external format.
    
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


def internal_size_sha_file_byname(name, filters):
    """Get size and sha of internal content given external content.
    
    :param name: path to file
    :param filters: the stack of filters to apply
    """
    f = open(name, 'rb', 65000)
    try:
        if filters:
            f = filtered_input_file(f, filters)
        size = 0
        s = sha.new()
        BUFSIZE = 128<<10
        while True:
            b = f.read(BUFSIZE)
            if not b:
                break
            size += len(b)
            s.update(b)
        return size, s.hexdigest()
    finally:
        f.close()


# The registry of filter stacks indexed by name.
# See register_filter_stack_map for details on the registered values.
_filter_stacks_registry = registry.Registry()


# Cache of preferences -> stack
# TODO: make this per branch (say) rather than global
_stack_cache = {}


def register_filter_stack_map(name, stack_map):
    """Register the filter stacks to use for various preference values.

    :param name: the preference/filter-stack name
    :param stack_map: a dictionary where
      the keys are preference values to match and
      the values are the matching stack of filters for each
    """
    if name in _filter_stacks_registry:
        raise errors.BzrError(
            "filter stack for %s already installed" % name)
    _filter_stacks_registry.register(name, stack_map)


def _get_registered_names():
    """Get the list of names with filters registered."""
    # Note: We may want to intelligently order these later.
    # If so, the register_ fn will need to support an optional priority.
    return _filter_stacks_registry.keys()


def _get_filter_stack_for(preferences):
    """Get the filter stack given a sequence of preferences.
    
    :param preferences: a sequence of (name,value) tuples where
      name is the preference name and
      value is the key into the filter stack map registered
      for that preference.
    """
    if preferences is None:
        return []
    stack = _stack_cache.get(preferences)
    if stack is not None:
        return stack
    stack = []
    for k, v in preferences:
        try:
            stacks_by_values = _filter_stacks_registry.get(k)
        except KeyError:
            # Some preferences may not have associated filters
            continue
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
    original = _filter_stacks_registry
    if value is None:
        _filter_stacks_registry = registry.Registry()
    else:
        _filter_stacks_registry = value
    _stack_cache.clear()
    return original
