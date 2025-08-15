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

# TODO: Could remember a bias towards whether a particular store is typically
# compressed or not.

"""Stores are the main data-storage mechanism for Bazaar.

A store is a simple write-once container indexed by a universally
unique ID.
"""

import os

from .... import transport as _mod_transport
from ....bzr import versionedfile
from ....errors import BzrError
from ....trace import mutter

######################################################################
# stores


class StoreError(Exception):
    """Exception raised for store-related errors.

    This exception is raised when there are problems with store operations
    such as adding, retrieving, or checking for the existence of files.
    """

    pass


class Store:
    """This class represents the abstract storage layout for saving information.

    Files can be added, but not modified once they are in.  Typically
    the hash is used as the name, or something else known to be unique,
    such as a UUID.
    """

    def __len__(self):
        """Return the number of files in the store.

        Returns:
            int: The number of files stored in this store.

        Raises:
            NotImplementedError: Must be implemented by subclasses.
        """
        raise NotImplementedError("Children should define their length")

    def get(self, fileid, suffix=None):
        """Returns a file reading from a particular entry.

        Args:
            fileid: The unique identifier for the file.
            suffix: Optional suffix to retrieve a specific variant of the file.

        Returns:
            File-like object for reading the file content.

        Raises:
            NotImplementedError: Must be implemented by subclasses.
            KeyError: If the file ID is not found in the store.
        """
        raise NotImplementedError

    def __iter__(self):
        """Iterate over all file IDs in the store.

        Yields:
            File IDs present in this store.

        Raises:
            NotImplementedError: Must be implemented by subclasses.
        """
        raise NotImplementedError

    def add(self, f, fileid):
        """Add a file object to the store accessible from the given fileid.

        Args:
            f: File-like object containing the data to store.
            fileid: The unique identifier for the file.

        Raises:
            NotImplementedError: Must be implemented by subclasses.
        """
        raise NotImplementedError(
            "Children of Store must define their method of adding entries."
        )

    def has_id(self, fileid, suffix=None):
        """Return True or False for the presence of fileid in the store.

        Args:
            fileid: The unique identifier to check for.
            suffix: Optional per-file suffix, e.g., for digital signature data.

        Returns:
            bool: True if the file exists in the store, False otherwise.

        Raises:
            NotImplementedError: Must be implemented by subclasses.
        """
        raise NotImplementedError

    def listable(self):
        """Return True if this store is able to be listed.

        Returns:
            bool: True if the store supports iteration over its contents.
        """
        return getattr(self, "__iter__", None) is not None


class TransportStore(Store):
    """A Store implementation that uses Breezy transports for file access.

    This class provides a Store implementation that uses Breezy's transport
    system for file operations, supporting various backends like local
    filesystems, HTTP, FTP, etc.
    """

    def add(self, f, fileid, suffix=None):
        """Add contents of a file into the store.

        Args:
            f: A file-like object containing the data to store.
            fileid: The unique identifier for the file.
            suffix: Optional suffix for storing multiple variants.

        Raises:
            BzrError: If the file ID already exists in the store.
        """
        mutter("add store entry %r", fileid)
        names = self._id_to_names(fileid, suffix)
        if self._transport.has_any(names):
            raise BzrError(
                f"store {self._transport.base!r} already contains id {fileid!r}"
            )

        # Most of the time, just adding the file will work
        # if we find a time where it fails, (because the dir
        # doesn't exist), then create the dir, and try again
        self._add(names[0], f)

    def _add(self, relpath, f):
        """Actually add the file to the given location.

        Args:
            relpath: Relative path where the file should be stored.
            f: File-like object containing the data to store.

        Raises:
            NotImplementedError: Must be overridden by subclasses.
        """
        raise NotImplementedError("children need to implement this function.")

    def _check_fileid(self, fileid):
        """Validate that a file ID is acceptable for storage.

        Args:
            fileid: The file ID to validate.

        Raises:
            TypeError: If fileid is not bytes.
            ValueError: If fileid contains invalid characters.
        """
        if not isinstance(fileid, bytes):
            raise TypeError(f"Fileids should be bytestrings: {type(fileid)} {fileid!r}")
        if b"\\" in fileid or b"/" in fileid:
            raise ValueError(f"invalid store id {fileid!r}")

    def _id_to_names(self, fileid, suffix):
        """Return the names in the expected order for compressed/uncompressed.

        Args:
            fileid: The file identifier.
            suffix: Optional suffix to append.

        Returns:
            Tuple[str, str]: File paths to try in order of preference.
        """
        if suffix is not None:
            fn = self._relpath(fileid, [suffix])
        else:
            fn = self._relpath(fileid)

        # FIXME RBC 20051128 this belongs in TextStore.
        fn_gz = fn + ".gz"
        if self._compressed:
            return fn_gz, fn
        else:
            return fn, fn_gz

    def has_id(self, fileid, suffix=None):
        """Check if the store contains a file with the given ID.

        Args:
            fileid: The file identifier to check.
            suffix: Optional suffix to check for.

        Returns:
            bool: True if the file exists in any expected format.
        """
        return self._transport.has_any(self._id_to_names(fileid, suffix))

    def _get_name(self, fileid, suffix=None):
        """Get the actual name of an existing file in the store.

        This is similar in spirit to 'has_id', but returns the actual
        filename that exists, allowing callers to know which format
        (compressed/uncompressed) is available.

        Args:
            fileid: The file identifier to look for.
            suffix: Optional suffix to check for.

        Returns:
            str or None: The actual filename if found, None otherwise.
        """
        for name in self._id_to_names(fileid, suffix=suffix):
            if self._transport.has(name):
                return name
        return None

    def _get(self, filename):
        """Return a vanilla file stream for clients to read from.

        This is the body of a template method on 'get', and should be
        implemented by subclasses to handle the actual file retrieval.

        Args:
            filename: The filename to retrieve.

        Returns:
            File-like object for reading the file content.

        Raises:
            NotImplementedError: Must be implemented by subclasses.
        """
        raise NotImplementedError

    def get(self, fileid, suffix=None):
        """Retrieve a file from the store.

        Args:
            fileid: The file identifier to retrieve.
            suffix: Optional suffix variant to retrieve.

        Returns:
            File-like object for reading the file content.

        Raises:
            KeyError: If the file ID is not found in the store.
        """
        names = self._id_to_names(fileid, suffix)
        for name in names:
            try:
                return self._get(name)
            except _mod_transport.NoSuchFile:
                pass
        raise KeyError(fileid)

    def __init__(
        self,
        a_transport,
        prefixed=False,
        compressed=False,
        dir_mode=None,
        file_mode=None,
        escaped=False,
    ):
        """Initialize a transport-based store.

        Args:
            a_transport: Transport to use for file operations.
            prefixed: If True, use hash-based directory prefixing.
            compressed: If True, prefer compressed files.
            dir_mode: File mode to use when creating directories.
            file_mode: File mode to use when creating files.
            escaped: If True, use escaped filenames for special characters.

        Raises:
            ValueError: If escaped is True but prefixed is False.
        """
        super().__init__()
        self._transport = a_transport
        self._prefixed = prefixed
        # FIXME RBC 20051128 this belongs in TextStore.
        self._compressed = compressed
        self._suffixes = set()
        self._escaped = escaped

        # It is okay for these to be None, it just means they
        # will just use the filesystem defaults
        self._dir_mode = dir_mode
        self._file_mode = file_mode
        # Create a key mapper to use
        if escaped and prefixed:
            self._mapper = versionedfile.HashEscapedPrefixMapper()
        elif not escaped and prefixed:
            self._mapper = versionedfile.HashPrefixMapper()
        elif self._escaped:
            raise ValueError(f"{self!r}: escaped unprefixed stores are not permitted.")
        else:
            self._mapper = versionedfile.PrefixMapper()

    def _iter_files_recursive(self):
        """Iterate through all files in the transport recursively.

        Yields:
            str: Relative paths of files in the store.
        """
        yield from self._transport.iter_files_recursive()

    def __iter__(self):
        """Iterate over all file IDs in the store.

        Yields:
            bytes: File IDs present in the store.
        """
        for relpath in self._iter_files_recursive():
            # worst case is one of each suffix.
            name = os.path.basename(relpath)
            if name.endswith(".gz"):
                name = name[:-3]
            skip = False
            for _count in range(len(self._suffixes)):
                for suffix in self._suffixes:
                    if name.endswith("." + suffix):
                        skip = True
            if not skip:
                yield self._mapper.unmap(name)[0]

    def __len__(self):
        """Return the number of files in the store.

        Returns:
            int: The count of files in the store.
        """
        return len(list(self.__iter__()))

    def _relpath(self, fileid, suffixes=None):
        """Calculate the relative path for a file ID.

        Args:
            fileid: The file identifier.
            suffixes: Optional list of suffixes to append.

        Returns:
            str: The relative path for the file.

        Raises:
            ValueError: If an unregistered suffix is used.
        """
        self._check_fileid(fileid)
        if suffixes:
            for suffix in suffixes:
                if suffix not in self._suffixes:
                    raise ValueError(f"Unregistered suffix {suffix!r}")
                self._check_fileid(suffix.encode("utf-8"))
        else:
            suffixes = []
        path = self._mapper.map((fileid,))
        full_path = ".".join([path] + suffixes)
        return full_path

    def __repr__(self):
        """Return a string representation of the store.

        Returns:
            str: String representation including the transport base.
        """
        if self._transport is None:
            return f"{self.__class__.__name__}(None)"
        else:
            return f"{self.__class__.__name__}({self._transport.base!r})"

    __str__ = __repr__

    def listable(self):
        """Return True if this store is able to be listed.

        Returns:
            bool: True if the underlying transport supports listing.
        """
        return self._transport.listable()

    def register_suffix(self, suffix):
        """Register a suffix as being expected in this store.

        Args:
            suffix: The suffix string to register.

        Raises:
            ValueError: If the suffix is 'gz' (reserved) or contains invalid characters.
        """
        self._check_fileid(suffix.encode("utf-8"))
        if suffix == "gz":
            raise ValueError('You cannot register the "gz" suffix.')
        self._suffixes.add(suffix)

    def total_size(self):
        """Return the total count and size of all files in the store.

        This is the (compressed) size stored on disk, not the size of
        the content after decompression.

        Returns:
            Tuple[int, int]: A tuple of (file_count, total_bytes).
        """
        total = 0
        count = 0
        for relpath in self._transport.iter_files_recursive():
            count += 1
            total += self._transport.stat(relpath).st_size

        return count, total
