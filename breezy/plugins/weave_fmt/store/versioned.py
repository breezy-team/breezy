"""Versioned file store implementation for the weave format.

This module provides VersionedFileStore, which manages collections of versioned
files (typically weaves) stored through Breezy's transport system. It handles
multiple versions of files with their complete history and inter-revision
relationships.
"""

# Copyright (C) 2005, 2006 Canonical Ltd
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

# XXX: Some consideration of the problems that might occur if there are
# files whose id differs only in case.  That should probably be forbidden.

import os

from .... import osutils
from .... import transport as _mod_transport
from . import TransportStore


class VersionedFileStore(TransportStore):
    """Collection of many versioned files accessible through a transport.

    This store manages multiple versioned files (typically weaves) that are
    stored using a transport backend. Each versioned file can contain multiple
    revisions with their history and relationships.
    """

    # TODO: Rather than passing versionedfile_kwargs, perhaps pass in a
    # transport factory callable?
    def __init__(
        self,
        transport,
        prefixed=False,
        precious=False,
        dir_mode=None,
        file_mode=None,
        versionedfile_class=None,
        versionedfile_kwargs=None,
        escaped=False,
    ):
        """Initialize a versioned file store.

        Args:
            transport: Transport to use for file operations.
            prefixed: If True, use hash-based directory prefixing.
            precious: If True, versioned files should not be deleted carelessly.
            dir_mode: File mode to use when creating directories.
            file_mode: File mode to use when creating files.
            versionedfile_class: Class to use for creating versioned files.
            versionedfile_kwargs: Additional keyword arguments for versioned files.
            escaped: If True, use escaped filenames for special characters.
        """
        super().__init__(
            transport,
            dir_mode=dir_mode,
            file_mode=file_mode,
            prefixed=prefixed,
            compressed=False,
            escaped=escaped,
        )
        self._precious = precious
        self._versionedfile_class = versionedfile_class
        self._versionedfile_kwargs = versionedfile_kwargs or {}
        # Used for passing get_scope to versioned file constructors;
        self.get_scope = None

    def filename(self, file_id):
        """Return the path relative to the transport root for a file ID.

        Args:
            file_id: The file identifier to get the path for.

        Returns:
            str: The relative path for the file.
        """
        return self._relpath(file_id)

    def __iter__(self):
        """Iterate over all file IDs in the versioned file store.

        Yields:
            bytes: File IDs present in the store, discovered by examining
                files with known versioned file suffixes.
        """
        suffixes = self._versionedfile_class.get_suffixes()
        ids = set()
        for relpath in self._iter_files_recursive():
            for suffix in suffixes:
                if relpath.endswith(suffix):
                    # TODO: use standard remove_suffix function
                    escaped_id = os.path.basename(relpath[: -len(suffix)])
                    file_id = self._mapper.unmap(escaped_id)[0]
                    if file_id not in ids:
                        ids.add(file_id)
                        yield file_id
                    break  # only one suffix can match

    def has_id(self, file_id):
        """Check if all required files for a versioned file ID exist.

        Args:
            file_id: The file identifier to check for.

        Returns:
            bool: True if all required files exist for the versioned file.
        """
        suffixes = self._versionedfile_class.get_suffixes()
        filename = self.filename(file_id)
        return all(self._transport.has(filename + suffix) for suffix in suffixes)

    def get_empty(self, file_id, transaction):
        """Get an empty versioned file, deleting any existing one first.

        Args:
            file_id: The file identifier to create an empty versioned file for.
            transaction: The transaction context for the operation.

        Returns:
            VersionedFile: A new empty versioned file instance.
        """
        if self.has_id(file_id):
            self.delete(file_id, transaction)
        return self.get_weave_or_empty(file_id, transaction)

    def delete(self, file_id, transaction):
        """Remove all files associated with a file ID from the store.

        Args:
            file_id: The file identifier to remove.
            transaction: The transaction context for the operation.
        """
        suffixes = self._versionedfile_class.get_suffixes()
        filename = self.filename(file_id)
        for suffix in suffixes:
            self._transport.delete(filename + suffix)

    def _get(self, file_id):
        """Get a file stream for reading a versioned file.

        Args:
            file_id: The file identifier to retrieve.

        Returns:
            File-like object for reading the file content.
        """
        return self._transport.get(self.filename(file_id))

    def _put(self, file_id, f):
        """Put a file stream into the store for a given file ID.

        Args:
            file_id: The file identifier to store under.
            f: File-like object containing data to store.

        Returns:
            The result of the transport put operation.

        Raises:
            _mod_transport.NoSuchFile: If the directory doesn't exist and
                the store is not configured for prefixing.
        """
        fn = self.filename(file_id)
        try:
            return self._transport.put_file(fn, f, mode=self._file_mode)
        except _mod_transport.NoSuchFile:
            if not self._prefixed:
                raise
            self._transport.mkdir(os.path.dirname(fn), mode=self._dir_mode)
            return self._transport.put_file(fn, f, mode=self._file_mode)

    def get_weave(self, file_id, transaction, _filename=None):
        """Return the VersionedFile for a given file ID.

        Args:
            file_id: The file identifier to retrieve the versioned file for.
            transaction: The transaction context for the operation.
            _filename: Optional filename that would be returned from self.filename
                for file_id. This is used to reduce duplicate filename calculations
                when using 'get_weave_or_empty'. FOR INTERNAL USE ONLY.

        Returns:
            VersionedFile: The versioned file instance for the given file ID.
        """
        if _filename is None:
            _filename = self.filename(file_id)
        if transaction.writeable():
            w = self._versionedfile_class(
                _filename,
                self._transport,
                self._file_mode,
                get_scope=self.get_scope,
                **self._versionedfile_kwargs,
            )
        else:
            w = self._versionedfile_class(
                _filename,
                self._transport,
                self._file_mode,
                create=False,
                access_mode="r",
                get_scope=self.get_scope,
                **self._versionedfile_kwargs,
            )
        return w

    def _make_new_versionedfile(
        self, file_id, transaction, known_missing=False, _filename=None
    ):
        """Create a new versioned file in the store.

        Args:
            file_id: The file identifier for the new versioned file.
            transaction: The transaction context for the operation.
            known_missing: If True, skip the existence check since we know
                the file doesn't exist.
            _filename: Optional filename that would be returned from self.filename
                for file_id. This is used to reduce duplicate filename calculations
                when using 'get_weave_or_empty'. FOR INTERNAL USE ONLY.

        Returns:
            VersionedFile: A new empty versioned file instance.
        """
        if not known_missing and self.has_id(file_id):
            self.delete(file_id, transaction)
        if _filename is None:
            _filename = self.filename(file_id)
        try:
            # we try without making the directory first because thats optimising
            # for the common case.
            weave = self._versionedfile_class(
                _filename,
                self._transport,
                self._file_mode,
                create=True,
                get_scope=self.get_scope,
                **self._versionedfile_kwargs,
            )
        except _mod_transport.NoSuchFile:
            if not self._prefixed:
                # unexpected error - NoSuchFile is expected to be raised on a
                # missing dir only and that only occurs when we are prefixed.
                raise
            dirname = osutils.dirname(_filename)
            self._transport.mkdir(dirname, mode=self._dir_mode)
            weave = self._versionedfile_class(
                _filename,
                self._transport,
                self._file_mode,
                create=True,
                get_scope=self.get_scope,
                **self._versionedfile_kwargs,
            )
        return weave

    def get_weave_or_empty(self, file_id, transaction):
        """Return a versioned file, or create an empty one if it doesn't exist.

        This method is optimized for cases where we need to access many
        versioned files and want to avoid repeated filename calculations.

        Args:
            file_id: The file identifier to retrieve or create.
            transaction: The transaction context for the operation.

        Returns:
            VersionedFile: The existing or newly created versioned file instance.
        """
        # This is typically used from 'commit' and 'fetch/push/pull' where
        # we scan across many versioned files once. As such the small overhead
        # of calculating the filename before doing a cache lookup is more than
        # compensated for by not calculating the filename when making new
        # versioned files.
        _filename = self.filename(file_id)
        try:
            return self.get_weave(file_id, transaction, _filename=_filename)
        except _mod_transport.NoSuchFile:
            weave = self._make_new_versionedfile(
                file_id, transaction, known_missing=True, _filename=_filename
            )
            return weave

    def _put_weave(self, file_id, weave, transaction):
        """Store a versioned file by copying all records from another.

        This method is preserved for upgrades-to-weaves to use.

        Args:
            file_id: The file identifier for the new versioned file.
            weave: The source versioned file to copy records from.
            transaction: The transaction context for the operation.
        """
        myweave = self._make_new_versionedfile(file_id, transaction)
        myweave.insert_record_stream(
            weave.get_record_stream(
                [(version,) for version in weave.versions()], "topological", False
            )
        )

    def total_size(self):
        """Return the total count and size, adjusted for versioned file suffixes.

        Returns:
            Tuple[float, int]: A tuple of (adjusted_file_count, total_bytes).
                The file count is divided by the number of suffixes since each
                versioned file consists of multiple physical files.
        """
        count, bytes = super().total_size()
        return (count / len(self._versionedfile_class.get_suffixes())), bytes
