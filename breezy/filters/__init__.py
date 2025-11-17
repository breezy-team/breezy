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

__docformat__ = "google"

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


from collections.abc import Callable
from io import BytesIO

from .. import osutils, registry


class ContentFilter:
    def __init__(self, reader, writer):
        """Create a filter that converts content while reading and writing.

        Args:
          reader: function for converting convenience to canonical content
          writer: function for converting canonical to convenience content
        """
        self.reader = reader
        self.writer = writer

    def __repr__(self):
        return "reader: {}, writer: {}".format(self.reader, self.writer)


Preferences = list[tuple[str, str]]
Stack = list[ContentFilter]


class ContentFilterContext:
    """Object providing information that filters can use."""

    def __init__(self, relpath=None, tree=None):
        """Create a context.

        Args:
          relpath: the relative path or None if this context doesn't
           support that information.
          tree: the Tree providing this file or None if this context
           doesn't support that information.
        """
        self._relpath = relpath
        self._tree = tree
        # Cached values
        self._revision_id = None
        self._revision = None

    def relpath(self):
        """Relative path of file to tree-root."""
        return self._relpath

    def source_tree(self):
        """Source Tree object."""
        return self._tree

    def revision_id(self):
        """Id of revision that last changed this file."""
        if self._revision_id is None:
            if self._tree is not None:
                self._revision_id = self._tree.get_file_revision(self._relpath)
        return self._revision_id

    def revision(self):
        """Revision this variation of the file was introduced in."""
        if self._revision is None:
            rev_id = self.revision_id()
            if rev_id is not None:
                repo = getattr(self._tree, "_repository", None)
                if repo is None:
                    repo = self._tree.branch.repository
                self._revision = repo.get_revision(rev_id)
        return self._revision


def filtered_input_file(f, filters):
    """Get an input file that converts external to internal content.

    Args:
      f: the original input file
      filters: the stack of filters to apply

    Returns: a file-like object, size
    """
    chunks = [f.read()]
    for filter in filters:
        if filter.reader is not None:
            chunks = filter.reader(chunks)
    text = b"".join(chunks)
    return BytesIO(text), len(text)


def filtered_output_bytes(chunks, filters, context=None):
    """Convert byte chunks from internal to external format.

    Args:
      chunks: an iterator containing the original content
      filters: the stack of filters to apply
      context: a ContentFilterContext object passed to
        each filter

    Returns: an iterator containing the content to output
    """
    if filters:
        for filter in reversed(filters):
            if filter.writer is not None:
                chunks = filter.writer(chunks, context)
    return chunks


def internal_size_sha_file_byname(name, filters):
    """Get size and sha of internal content given external content.

    Args:
      name: path to file
      filters: the stack of filters to apply
    """
    with open(name, "rb", 65000) as f:
        if filters:
            f, size = filtered_input_file(f, filters)
        return osutils.size_sha_file(f)


class FilteredStat:
    def __init__(self, base, st_size=None):
        self.st_mode = base.st_mode
        self.st_size = st_size or base.st_size
        self.st_mtime = base.st_mtime
        self.st_ctime = base.st_ctime


# The registry of filter stacks indexed by name.
filter_stacks_registry = registry.Registry[str, Callable[[str], list[ContentFilter]]]()


# Cache of preferences -> stack
# TODO: make this per branch (say) rather than global
_stack_cache: dict[Preferences, Stack] = {}


def _get_registered_names():
    """Get the list of names with filters registered."""
    # Note: We may want to intelligently order these later.
    # If so, the register_ fn will need to support an optional priority.
    return filter_stacks_registry.keys()


def _get_filter_stack_for(preferences: Preferences) -> Stack:
    """Get the filter stack given a sequence of preferences.

    Args:
      preferences: a sequence of (name,value) tuples where
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

    Args:
      value: the value to set the registry to or None for an empty one.

    Returns:
      the existing value before it reset.
    """
    global filter_stacks_registry
    original = filter_stacks_registry
    if value is None:
        filter_stacks_registry = registry.Registry()
    else:
        filter_stacks_registry = value
    _stack_cache.clear()
    return original


filter_stacks_registry.register_lazy("eol", "breezy.filters.eol", "eol_lookup")
