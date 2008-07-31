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

"""View management.

Views are contained within a working tree and normally constructed 
when first accessed.  Clients should do, for example, ...

  tree.views.lookup_view()
"""


import re

from bzrlib import (
    errors,
    )


_VIEWS_FORMAT_MARKER_RE = re.compile(r'Bazaar views format (\d+)')
_VIEWS_FORMAT1_MARKER = "Bazaar views format 1\n"


class _Views(object):
    """Base class for View managers."""

    def supports_views(self):
        raise NotImplementedError(self.supports_views)


class PathBasedViews(_Views):
    """View storage in an unversioned tree control file.

    Views are stored in terms of paths relative to the tree root.

    The top line of the control file is a format marker in the format:

      Bazaar views format X

    where X is an integer number. Version 1 format is stored as follows:

     * the line after the format marker holds the name of the current view

     * subsequent lines hold view definitions, one per line is the format

       name file1 file2 ...

    where the fields are separated by a nul character (\0). The views file
    is encoded in utf-8.
    """

    def __init__(self, tree):
        self.tree = tree
        self._loaded = False
        self._current = None
        self._views = {}

    def supports_views(self):
        return True

    def get_view_info(self):
        """Get the current view and dictionary of views.

        :return: current, views where
          current = the name of the current view or None if no view is enabled
          views = a map from view name to list of files/directories
        """
        self._load_view_info()
        return self._current, self._views

    def set_view_info(self, current, views):
        """Set the current view and dictionary of views.

        :param current: the name of the current view or None if no view is
          enabled
        :param views: a map from view name to list of files/directories
        """
        if current is not None and current not in views:
            raise errors.NoSuchView(current)
        self.tree.lock_write()
        try:
            self._current = current
            self._views = views
            self._save_view_info()
        finally:
            self.tree.unlock()

    def lookup_view(self, view_name=None):
        """Return the contents of a view.
        
        :param view_Name: name of the view or None to lookup the current view
        :return: the list of files/directories in the requested view
        """
        self._load_view_info()
        try:
            if view_name is None:
                if self._current:
                    view_name = self._current
                else:
                    return []
            return self._views[view_name]
        except KeyError:
            raise errors.NoSuchView(view_name)

    def set_view(self, view_name, view_files, make_current=True):
        """Add or update a view definition.
        
        :param view_name: the name of the view
        :param view_files: the list of files/directories in the view
        :param make_current: make this view the current one or not
        """
        self.tree.lock_write()
        try:
            self._load_view_info()
            self._views[view_name] = view_files
            if make_current:
                self._current = view_name
            self._save_view_info()
        finally:
            self.tree.unlock()

    def delete_view(self, view_name):
        """Delete a view definition.

        If the view deleted is the current one, the current view is reset.
        """
        self.tree.lock_write()
        try:
            self._load_view_info()
            try:
                del self._views[view_name]
            except KeyError:
                raise errors.NoSuchView(view_name)
            if view_name == self._current:
                self._current = None
            self._save_view_info()
        finally:
            self.tree.unlock()

    def _save_view_info(self):
        """Save the current view and all view definitions.

        Be sure to have initialised self._current and self._views before
        calling this method.
        """
        self.tree.lock_write()
        try:
            self.tree._transport.put_bytes('views',
                self._serialize_view_content(self._current, self._views))
        finally:
            self.tree.unlock()

    def _load_view_info(self):
        """Load the current view and dictionary of view definitions."""
        if not self._loaded:
            self.tree.lock_read()
            try:
                try:
                    view_content = self.tree._transport.get_bytes('views')
                except errors.NoSuchFile, e:
                    self._current, self._views = None, {}
                else:
                    self._current, self._views = \
                        self._deserialize_view_content(view_content)
            finally:
                self.tree.unlock()
            self._loaded = True

    def _serialize_view_content(self, current, view_dict):
        """Convert a current view and view dictionary into a stream."""
        lines = [_VIEWS_FORMAT1_MARKER]
        if current is None:
            lines.append("\n")
        else:
            lines.append((current + "\n").encode('utf-8'))
        for view in sorted(view_dict):
            view_data = "%s\0%s\n" % (view, "\0".join(view_dict[view]))
            lines.append(view_data.encode('utf-8'))
        return "".join(lines)

    def _deserialize_view_content(self, view_content):
        """Convert a stream into a current view and dictionary of views."""
        # as a special case to make initialization easy, an empty definition
        # maps to no current view and an empty view dictionary
        if view_content == '':
            return None, {}
        lines = view_content.splitlines()
        match = _VIEWS_FORMAT_MARKER_RE.match(lines[0])
        if not match:
            raise ValueError(
                "format marker missing from top of views file")
        elif match.group(1) != '1':
            raise ValueError(
                "cannot decode views format %s" % match.group(1))
        try:
            current = lines[1].decode('utf-8')
            if current == '':
                current = None
            views = {}
            for line in lines[2:]:
                parts = line.decode('utf-8').split('\0')
                view = parts.pop(0)
                views[view] = parts
            return current, views
        except ValueError, e:
            raise ValueError("failed to deserialize views content %r: %s"
                % (view_content, e))


class DisabledViews(_Views):
    """View storage that refuses to store anything.

    This is used by older formats that can't store views.
    """

    def __init__(self, tree):
        self.tree = tree

    def supports_views(self):
        return False

    def _not_supported(self, *a, **k):
        raise errors.ViewsNotSupported(self.tree)

    get_view_info = _not_supported
    set_view_info = _not_supported
    lookup_view = _not_supported
    set_view = _not_supported
    delete_view = _not_supported
