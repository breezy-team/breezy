# Copyright (C) 2009, 2010 Canonical Ltd
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

"""A transport decorator that filters all paths that are passed to it."""

from .. import urlutils
from . import Server, Transport, register_transport, unregister_transport


class PathFilteringServer(Server):
    """Transport server for PathFilteringTransport.

    It holds the backing_transport and filter_func for PathFilteringTransports.
    All paths will be passed through filter_func before calling into the
    backing_transport.

    Note that paths returned from the backing transport are *not* altered in
    anyway.  So, depending on the filter_func, PathFilteringTransports might
    not conform to the usual expectations of Transport behaviour; e.g. 'name'
    in t.list_dir('dir') might not imply t.has('dir/name') is True!  A filter
    that merely prefixes a constant path segment will be essentially
    transparent, whereas a filter that does rot13 to paths will break
    expectations and probably cause confusing errors.  So choose your
    filter_func with care.
    """

    def __init__(self, backing_transport, filter_func):
        """Constructor.

        :param backing_transport: a transport
        :param filter_func: a callable that takes paths, and translates them
            into paths for use with the backing transport.
        """
        self.backing_transport = backing_transport
        self.filter_func = filter_func

    def _factory(self, url):
        return PathFilteringTransport(self, url)

    def get_url(self):
        """Return the URL scheme for this server."""
        return self.scheme

    def start_server(self):
        """Start the path filtering transport server.

        Creates a unique scheme and registers the transport factory.
        """
        self.scheme = "filtered-%d:///" % id(self)
        register_transport(self.scheme, self._factory)

    def stop_server(self):
        """Stop the path filtering transport server.

        Unregisters the transport factory.
        """
        unregister_transport(self.scheme, self._factory)


class PathFilteringTransport(Transport):
    """A PathFilteringTransport.

    Please see PathFilteringServer for details.
    """

    def __init__(self, server, base):
        """Initialize a PathFilteringTransport.

        Args:
            server: The PathFilteringServer instance.
            base: Base URL for the transport.
        """
        self.server = server
        if not base.endswith("/"):
            base += "/"
        Transport.__init__(self, base)
        self.base_path = self.base[len(self.server.scheme) - 1 :]
        self.scheme = self.server.scheme

    def _relpath_from_server_root(self, relpath):
        unfiltered_path = urlutils.combine_paths(self.base_path, relpath)
        if not unfiltered_path.startswith("/"):
            raise ValueError(unfiltered_path)
        return unfiltered_path[1:]

    def _filter(self, relpath):
        return self.server.filter_func(self._relpath_from_server_root(relpath))

    def _call(self, methodname, relpath, *args):
        """Helper for Transport methods of the form:
        operation(path, [other args ...]).
        """
        backing_method = getattr(self.server.backing_transport, methodname)
        return backing_method(self._filter(relpath), *args)

    # Transport methods
    def abspath(self, relpath):
        """Return the absolute URL for a relative path.

        Args:
            relpath: Relative path to convert.

        Returns:
            Absolute URL without path filtering applied.
        """
        # We do *not* want to filter at this point; e.g if the filter is
        # homedir expansion, self.base == 'this:///' and relpath == '~/foo',
        # then the abspath should be this:///~/foo (not this:///home/user/foo).
        # Instead filtering should happen when self's base is passed to the
        # backing.
        return self.scheme + self._relpath_from_server_root(relpath)

    def append_file(self, relpath, f, mode=None):
        """Append data to a file.

        Args:
            relpath: Relative path to the file.
            f: File-like object or bytes to append.
            mode: Optional file mode.

        Returns:
            Number of bytes appended.
        """
        return self._call("append_file", relpath, f, mode)

    def _can_roundtrip_unix_modebits(self):
        return self.server.backing_transport._can_roundtrip_unix_modebits()

    def clone(self, relpath):
        """Clone this transport with a new base path.

        Args:
            relpath: Relative path for the new base.

        Returns:
            New PathFilteringTransport instance.
        """
        return self.__class__(self.server, self.abspath(relpath))

    def delete(self, relpath):
        """Delete a file.

        Args:
            relpath: Relative path to the file to delete.
        """
        return self._call("delete", relpath)

    def delete_tree(self, relpath):
        """Delete a directory tree.

        Args:
            relpath: Relative path to the directory to delete.
        """
        return self._call("delete_tree", relpath)

    def external_url(self):
        """See breezy.transport.Transport.external_url."""
        # PathFilteringTransports, like MemoryTransport, depend on in-process
        # state and thus the base cannot simply be handed out.  See the base
        # class docstring for more details and possible directions. For now we
        # return the path-filtered URL.
        return self.server.backing_transport.external_url()

    def get(self, relpath):
        """Get the contents of a file.

        Args:
            relpath: Relative path to the file.

        Returns:
            File-like object containing the file contents.
        """
        return self._call("get", relpath)

    def has(self, relpath):
        """Check if a file or directory exists.

        Args:
            relpath: Relative path to check.

        Returns:
            True if the path exists, False otherwise.
        """
        return self._call("has", relpath)

    def is_readonly(self):
        """Check if the transport is read-only.

        Returns:
            True if read-only, False otherwise.
        """
        return self.server.backing_transport.is_readonly()

    def iter_files_recursive(self):
        """Iterate over all files in the transport recursively.

        Yields:
            Relative paths of all files.
        """
        backing_transport = self.server.backing_transport.clone(self._filter("."))
        return backing_transport.iter_files_recursive()

    def listable(self):
        """Check if the transport supports directory listing.

        Returns:
            True if listable, False otherwise.
        """
        return self.server.backing_transport.listable()

    def list_dir(self, relpath):
        """List the contents of a directory.

        Args:
            relpath: Relative path to the directory.

        Returns:
            List of directory entry names.
        """
        return self._call("list_dir", relpath)

    def lock_read(self, relpath):
        """Acquire a read lock on a file.

        Args:
            relpath: Relative path to the file.

        Returns:
            Lock object.
        """
        return self._call("lock_read", relpath)

    def lock_write(self, relpath):
        """Acquire a write lock on a file.

        Args:
            relpath: Relative path to the file.

        Returns:
            Lock object.
        """
        return self._call("lock_write", relpath)

    def mkdir(self, relpath, mode=None):
        """Create a directory.

        Args:
            relpath: Relative path for the new directory.
            mode: Optional file mode.
        """
        return self._call("mkdir", relpath, mode)

    def open_write_stream(self, relpath, mode=None):
        """Open a file for writing as a stream.

        Args:
            relpath: Relative path to the file.
            mode: Optional file mode.

        Returns:
            Writable file-like object.
        """
        return self._call("open_write_stream", relpath, mode)

    def put_file(self, relpath, f, mode=None):
        """Write data to a file.

        Args:
            relpath: Relative path to the file.
            f: File-like object or bytes to write.
            mode: Optional file mode.

        Returns:
            Number of bytes written.
        """
        return self._call("put_file", relpath, f, mode)

    def rename(self, rel_from, rel_to):
        """Rename a file or directory.

        Args:
            rel_from: Current relative path.
            rel_to: New relative path.
        """
        return self._call("rename", rel_from, self._filter(rel_to))

    def rmdir(self, relpath):
        """Remove an empty directory.

        Args:
            relpath: Relative path to the directory.
        """
        return self._call("rmdir", relpath)

    def stat(self, relpath):
        """Get file or directory statistics.

        Args:
            relpath: Relative path to the file or directory.

        Returns:
            Stat object with file information.
        """
        return self._call("stat", relpath)


def get_test_permutations():
    """Return the permutations to be used in testing."""
    from ..tests import test_server

    return [(PathFilteringTransport, test_server.TestingPathFilteringServer)]
