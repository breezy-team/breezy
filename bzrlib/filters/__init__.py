# Copyright (C) 2008, 2009, 2011 Canonical Ltd
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

"""Working tree content filtering support.

A filter consists of a read converter, write converter pair.
The content in the working tree is called the convenience format
while the content actually stored is called the canonical format.
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

from __future__ import absolute_import

from cStringIO import StringIO
from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
from bzrlib import (
    config,
    errors,
    osutils,
    registry,
    )
""")
from bzrlib.symbol_versioning import (
    deprecated_function,
    deprecated_in,
    )


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
    """Object providing information that filters can use."""

    def __init__(self, relpath=None, tree=None, entry=None):
        """Create a context.

        :param relpath: the relative path or None if this context doesn't
           support that information.
        :param tree: the Tree providing this file or None if this context
           doesn't support that information.
        :param entry: the InventoryEntry object if it is already known or
           None if it should be derived if possible
        """
        self._relpath = relpath
        self._tree = tree
        self._entry = entry
        # Cached values
        self._revision_id = None
        self._revision = None

    def relpath(self):
        """Relative path of file to tree-root."""
        return self._relpath

    def source_tree(self):
        """Source Tree object."""
        return self._tree

    def file_id(self):
        """File-id of file."""
        if self._entry is not None:
            return self._entry.file_id
        elif self._tree is None:
            return None
        else:
            return self._tree.path2id(self._relpath)

    def revision_id(self):
        """Id of revision that last changed this file."""
        if self._revision_id is None:
            if self._entry is not None:
                self._revision_id = self._entry.revision
            elif self._tree is not None:
                file_id = self._tree.path2id(self._relpath)
                self._entry = self._tree.inventory[file_id]
                self._revision_id = self._entry.revision
        return self._revision_id

    def revision(self):
        """Revision this variation of the file was introduced in."""
        if self._revision is None:
            rev_id = self.revision_id()
            if rev_id is not None:
                repo = getattr(self._tree, '_repository', None)
                if repo is None:
                    repo = self._tree.branch.repository
                self._revision = repo.get_revision(rev_id)
        return self._revision


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
        return StringIO(''.join(chunks))
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
        return osutils.size_sha_file(f)
    finally:
        f.close()


# The registry of filter stacks indexed by name.
filter_stacks_registry = registry.Registry()


# Cache of preferences -> stack
# TODO: make this per branch (say) rather than global
_stack_cache = {}


# XXX: This function doesn't have any tests. JRV 2012-03-29
@deprecated_function(deprecated_in((2, 6, 0)))
def register_filter_stack_map(name, stack_map_lookup):
    """Register the filter stacks to use for various preference values.

    :param name: the preference/filter-stack name
    :param stack_map_lookup: a callable where
      the parameter is the preference value to match and
      the result is the matching stack of filters to use,
      or None if none.
    """
    filter_stacks_registry.register(name, stack_map_lookup)


# XXX: This function doesn't have any tests. JRV 2012-03-29
@deprecated_function(deprecated_in((2, 6, 0)))
def lazy_register_filter_stack_map(name, module_name, member_name):
    """Lazily register the filter stacks to use for various preference values.

    :param name: the preference/filter-stack name
    :param module_name: The python path to the module of the filter stack map.
    :param member_name: The name of the stack_map_lookup callable
      in the module.
    """
    filter_stacks_registry.register_lazy(name, module_name, member_name)


def _get_registered_names():
    """Get the list of names with filters registered."""
    # Note: We may want to intelligently order these later.
    # If so, the register_ fn will need to support an optional priority.
    return filter_stacks_registry.keys()


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
        if v is None:
            continue
        try:
            stack_map_lookup = filter_stacks_registry.get(k)
        except KeyError:
            # Some preferences may not have associated filters
            continue
        items = stack_map_lookup(v)
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
    global filter_stacks_registry
    original = filter_stacks_registry
    if value is None:
        filter_stacks_registry = registry.Registry()
    else:
        filter_stacks_registry = value
    _stack_cache.clear()
    return original


filter_stacks_registry.register_lazy('eol', 'bzrlib.filters.eol', 'eol_lookup')
