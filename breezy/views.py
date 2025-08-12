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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""View management.

Views are contained within a working tree and normally constructed
when first accessed. Clients should do, for example:

    tree.views.lookup_view()
"""

__docformat__ = "google"

import re

from . import errors, osutils, transport

_VIEWS_FORMAT_MARKER_RE = re.compile(b"Bazaar views format (\\d+)")
_VIEWS_FORMAT1_MARKER = b"Bazaar views format 1\n"


class NoSuchView(errors.BzrError):
    """A view does not exist."""

    _fmt = "No such view: %(view_name)s."

    def __init__(self, view_name):
        """Initialize NoSuchView exception.

        Args:
            view_name: Name of the view that was not found.
        """
        self.view_name = view_name


class ViewsNotSupported(errors.BzrError):
    """Views are not supported by a tree format."""

    _fmt = (
        "Views are not supported by %(tree)s;"
        " use 'brz upgrade' to change your tree to a later format."
    )

    def __init__(self, tree):
        """Initialize ViewsNotSupported exception.

        Args:
            tree: The tree that does not support views.
        """
        self.tree = tree


class FileOutsideView(errors.BzrError):
    """Exception raised when a file is outside the current view.

    This error occurs when trying to operate on a file that is not included
    in the currently active view.
    """

    _fmt = 'Specified file "%(file_name)s" is outside the current view: %(view_str)s'

    def __init__(self, file_name, view_files):
        """Initialize FileOutsideView exception.

        Args:
            file_name: Name of the file that is outside the view.
            view_files: List of files that are included in the current view.
        """
        self.file_name = file_name
        self.view_str = ", ".join(view_files)


class _Views:
    """Base class for View managers."""

    def supports_views(self):
        raise NotImplementedError(self.supports_views)


class PathBasedViews(_Views):
    r"""View storage in an unversioned tree control file.

    Views are stored in terms of paths relative to the tree root.

    The top line of the control file is a format marker in the format:

      Bazaar views format X

    where X is an integer number. After this top line, version 1 format is
    stored as follows:

     * optional name-values pairs in the format 'name=value'

     * optional view definitions, one per line in the format

       views:
       name file1 file2 ...
       name file1 file2 ...

    where the fields are separated by a nul character (\0). The views file
    is encoded in utf-8. The only supported keyword in version 1 is
    'current' which stores the name of the current view, if any.
    """

    def __init__(self, tree):
        """Initialize PathBasedViews manager.

        Args:
            tree: The working tree to manage views for.
        """
        self.tree = tree
        self._loaded = False
        self._current = None
        self._views = {}

    def supports_views(self):
        """Check if this view manager supports views.

        Returns:
            True, as PathBasedViews supports view storage.
        """
        return True

    def get_view_info(self):
        """Get the current view and dictionary of views.

        Returns: current, views where
          current = the name of the current view or None if no view is enabled
          views = a map from view name to list of files/directories
        """
        self._load_view_info()
        return self._current, self._views

    def set_view_info(self, current, views):
        """Set the current view and dictionary of views.

        Args:
          current: the name of the current view or None if no view is
              enabled
          views: a map from view name to list of files/directories
        """
        if current is not None and current not in views:
            raise NoSuchView(current)
        with self.tree.lock_write():
            self._current = current
            self._views = views
            self._save_view_info()

    def lookup_view(self, view_name=None):
        """Return the contents of a view.

        Args:
          view_Name: name of the view or None to lookup the current view

        Returns:
          the list of files/directories in the requested view
        """
        self._load_view_info()
        try:
            if view_name is None:
                if self._current:
                    view_name = self._current
                else:
                    return []
            return self._views[view_name]
        except KeyError as err:
            raise NoSuchView(view_name) from err

    def set_view(self, view_name, view_files, make_current=True):
        """Add or update a view definition.

        Args:
          view_name: the name of the view
          view_files: the list of files/directories in the view
          make_current: make this view the current one or not
        """
        with self.tree.lock_write():
            self._load_view_info()
            self._views[view_name] = view_files
            if make_current:
                self._current = view_name
            self._save_view_info()

    def delete_view(self, view_name):
        """Delete a view definition.

        If the view deleted is the current one, the current view is reset.
        """
        with self.tree.lock_write():
            self._load_view_info()
            try:
                del self._views[view_name]
            except KeyError as err:
                raise NoSuchView(view_name) from err
            if view_name == self._current:
                self._current = None
            self._save_view_info()

    def _save_view_info(self):
        """Save the current view and all view definitions.

        Be sure to have initialised self._current and self._views before
        calling this method.
        """
        with self.tree.lock_write():
            keywords = {} if self._current is None else {"current": self._current}
            self.tree._transport.put_bytes(
                "views", self._serialize_view_content(keywords, self._views)
            )

    def _load_view_info(self):
        """Load the current view and dictionary of view definitions."""
        if not self._loaded:
            with self.tree.lock_read():
                try:
                    view_content = self.tree._transport.get_bytes("views")
                except transport.NoSuchFile:
                    self._current, self._views = None, {}
                else:
                    keywords, self._views = self._deserialize_view_content(view_content)
                    self._current = keywords.get("current")
            self._loaded = True

    def _serialize_view_content(self, keywords, view_dict):
        """Convert view keywords and a view dictionary into a stream."""
        lines = [_VIEWS_FORMAT1_MARKER]
        for key in keywords:
            line = f"{key}={keywords[key]}\n"
            lines.append(line.encode("utf-8"))
        if view_dict:
            lines.append(b"views:\n")
            for view in sorted(view_dict):
                view_data = "{}\0{}\n".format(view, "\0".join(view_dict[view]))
                lines.append(view_data.encode("utf-8"))
        return b"".join(lines)

    def _deserialize_view_content(self, view_content):
        """Convert a stream into view keywords and a dictionary of views."""
        # as a special case to make initialization easy, an empty definition
        # maps to no current view and an empty view dictionary
        if view_content == b"":
            return {}, {}
        lines = view_content.splitlines()
        match = _VIEWS_FORMAT_MARKER_RE.match(lines[0])
        if not match:
            raise ValueError("format marker missing from top of views file")
        elif match.group(1) != b"1":
            raise ValueError(f"cannot decode views format {match.group(1)}")
        try:
            keywords = {}
            views = {}
            in_views = False
            for line in lines[1:]:
                text = line.decode("utf-8")
                if in_views:
                    parts = text.split("\0")
                    view = parts.pop(0)
                    views[view] = parts
                elif text == "views:":
                    in_views = True
                    continue
                elif text.find("=") >= 0:
                    # must be a name-value pair
                    keyword, value = text.split("=", 1)
                    keywords[keyword] = value
                else:
                    raise ValueError("failed to deserialize views line %s", text)
            return keywords, views
        except ValueError as e:
            raise ValueError(
                f"failed to deserialize views content {view_content!r}: {e}"
            ) from e


class DisabledViews(_Views):
    """View storage that refuses to store anything.

    This is used by older formats that can't store views.
    """

    def __init__(self, tree):
        """Initialize DisabledViews manager.

        Args:
            tree: The tree that does not support views.
        """
        self.tree = tree

    def supports_views(self):
        """Check if this view manager supports views.

        Returns:
            False, as DisabledViews does not support view storage.
        """
        return False

    def _not_supported(self, *a, **k):
        raise ViewsNotSupported(self.tree)

    get_view_info = _not_supported
    set_view_info = _not_supported
    lookup_view = _not_supported
    set_view = _not_supported
    delete_view = _not_supported


def view_display_str(view_files, encoding=None):
    """Get the display string for a list of view files.

    Args:
      view_files: the list of file names
      encoding: the encoding to display the files in
    """
    if encoding is None:
        return ", ".join(view_files)
    else:
        return ", ".join([v.encode(encoding, "replace") for v in view_files])


def check_path_in_view(tree, relpath):
    """If a working tree has a view enabled, check the path is within it."""
    if tree.supports_views():
        view_files = tree.views.lookup_view()
        if view_files and not osutils.is_inside_any(view_files, relpath):
            raise FileOutsideView(relpath, view_files)
