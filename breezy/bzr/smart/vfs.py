# Copyright (C) 2006-2010 Canonical Ltd
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

"""VFS operations for the smart server.

This module defines the smart server methods that are low-level file operations
-- i.e. methods that operate directly on files and directories, rather than
higher-level concepts like branches and revisions.

These methods, plus 'hello' and 'get_bundle', are version 1 of the smart server
protocol, as implemented in bzr 0.11 and later.
"""

import os

from ... import urlutils
from . import request


def _deserialise_optional_mode(mode):
    """Deserialise an optional file mode from the protocol.

    Args:
        mode: A bytes object representing the mode, or empty bytes for None.

    Returns:
        An integer file mode, or None if the mode parameter was empty.

    Note:
        XXX: FIXME this should be on the protocol object. Later protocol versions
        might serialise modes differently.
    """
    if mode == b"":
        return None
    else:
        return int(mode)


def vfs_enabled():
    """Is the VFS enabled ?

    the VFS is disabled when the BRZ_NO_SMART_VFS environment variable is set.

    :return: ``True`` if it is enabled.
    """
    return "BRZ_NO_SMART_VFS" not in os.environ


class VfsRequest(request.SmartServerRequest):
    """Base class for VFS requests.

    VFS requests are disabled if vfs_enabled() returns False.
    """

    def _check_enabled(self):
        """Check if VFS requests are enabled.

        Raises:
            DisabledMethod: If VFS requests are disabled via BRZ_NO_SMART_VFS.
        """
        if not vfs_enabled():
            raise request.DisabledMethod(self.__class__.__name__)

    def translate_client_path(self, relpath):
        """Translate a client-side relative path to a server-side path.

        VFS requests are made with escaped paths so the escaping done in
        SmartServerRequest.translate_client_path leads to double escaping.
        Remove it here -- the fact that the result is still escaped means
        that the str() will not fail on valid input.

        Args:
            relpath: The relative path from the client.

        Returns:
            A string path suitable for use on the server side.
        """
        x = request.SmartServerRequest.translate_client_path(self, relpath)
        return str(urlutils.unescape(x))


class HasRequest(VfsRequest):
    """Smart server request to check if a file exists."""

    def do(self, relpath):
        """Check if a file exists at the given path.

        Args:
            relpath: Relative path to check for existence.

        Returns:
            SuccessfulSmartServerResponse with 'yes' or 'no'.
        """
        relpath = self.translate_client_path(relpath)
        r = (self._backing_transport.has(relpath) and b"yes") or b"no"
        return request.SuccessfulSmartServerResponse((r,))


class GetRequest(VfsRequest):
    """Smart server request to read the contents of a file."""

    def do(self, relpath):
        """Get the contents of a file.

        Args:
            relpath: Relative path to the file to read.

        Returns:
            SuccessfulSmartServerResponse with the file contents as body.
        """
        relpath = self.translate_client_path(relpath)
        backing_bytes = self._backing_transport.get_bytes(relpath)
        return request.SuccessfulSmartServerResponse((b"ok",), backing_bytes)


class AppendRequest(VfsRequest):
    """Smart server request to append data to a file."""

    def do(self, relpath, mode):
        """Prepare to append data to a file.

        Args:
            relpath: Relative path to the file to append to.
            mode: File mode as bytes, or empty bytes for default.
        """
        relpath = self.translate_client_path(relpath)
        self._relpath = relpath
        self._mode = _deserialise_optional_mode(mode)

    def do_body(self, body_bytes):
        """Append the body bytes to the file.

        Args:
            body_bytes: The bytes to append to the file.

        Returns:
            SuccessfulSmartServerResponse with the old file length.
        """
        old_length = self._backing_transport.append_bytes(
            self._relpath, body_bytes, self._mode
        )
        return request.SuccessfulSmartServerResponse(
            (b"appended", str(old_length).encode("ascii"))
        )


class DeleteRequest(VfsRequest):
    """Smart server request to delete a file."""

    def do(self, relpath):
        """Delete a file at the given path.

        Args:
            relpath: Relative path to the file to delete.

        Returns:
            SuccessfulSmartServerResponse indicating success.
        """
        relpath = self.translate_client_path(relpath)
        self._backing_transport.delete(relpath)
        return request.SuccessfulSmartServerResponse((b"ok",))


class IterFilesRecursiveRequest(VfsRequest):
    """Smart server request to recursively list all files in a directory."""

    def do(self, relpath):
        """Recursively list all files in a directory.

        Args:
            relpath: Relative path to the directory to list.

        Returns:
            SuccessfulSmartServerResponse with all filenames.
        """
        if not relpath.endswith(b"/"):
            relpath += b"/"
        relpath = self.translate_client_path(relpath)
        transport = self._backing_transport.clone(relpath)
        filenames = transport.iter_files_recursive()
        return request.SuccessfulSmartServerResponse((b"names",) + tuple(filenames))


class ListDirRequest(VfsRequest):
    """Smart server request to list the contents of a directory."""

    def do(self, relpath):
        """List the contents of a directory.

        Args:
            relpath: Relative path to the directory to list.

        Returns:
            SuccessfulSmartServerResponse with directory contents.
        """
        if not relpath.endswith(b"/"):
            relpath += b"/"
        relpath = self.translate_client_path(relpath)
        filenames = self._backing_transport.list_dir(relpath)
        return request.SuccessfulSmartServerResponse(
            (b"names",) + tuple([filename.encode("utf-8") for filename in filenames])
        )


class MkdirRequest(VfsRequest):
    """Smart server request to create a directory."""

    def do(self, relpath, mode):
        """Create a directory at the given path.

        Args:
            relpath: Relative path where to create the directory.
            mode: Directory mode as bytes, or empty bytes for default.

        Returns:
            SuccessfulSmartServerResponse indicating success.
        """
        relpath = self.translate_client_path(relpath)
        self._backing_transport.mkdir(relpath, _deserialise_optional_mode(mode))
        return request.SuccessfulSmartServerResponse((b"ok",))


class MoveRequest(VfsRequest):
    """Smart server request to move a file or directory."""

    def do(self, rel_from, rel_to):
        """Move a file or directory from one path to another.

        Args:
            rel_from: Relative source path.
            rel_to: Relative destination path.

        Returns:
            SuccessfulSmartServerResponse indicating success.
        """
        rel_from = self.translate_client_path(rel_from)
        rel_to = self.translate_client_path(rel_to)
        self._backing_transport.move(rel_from, rel_to)
        return request.SuccessfulSmartServerResponse((b"ok",))


class PutRequest(VfsRequest):
    """Smart server request to write data to a file (atomically)."""

    def do(self, relpath, mode):
        """Prepare to write data to a file.

        Args:
            relpath: Relative path to the file to write.
            mode: File mode as bytes, or empty bytes for default.
        """
        relpath = self.translate_client_path(relpath)
        self._relpath = relpath
        self._mode = _deserialise_optional_mode(mode)

    def do_body(self, body_bytes):
        """Write the body bytes to the file atomically.

        Args:
            body_bytes: The bytes to write to the file.

        Returns:
            SuccessfulSmartServerResponse indicating success.
        """
        self._backing_transport.put_bytes(self._relpath, body_bytes, self._mode)
        return request.SuccessfulSmartServerResponse((b"ok",))


class PutNonAtomicRequest(VfsRequest):
    """Smart server request to write data to a file (non-atomically)."""

    def do(self, relpath, mode, create_parent, dir_mode):
        """Prepare to write data to a file non-atomically.

        Args:
            relpath: Relative path to the file to write.
            mode: File mode as bytes, or empty bytes for default.
            create_parent: b'T' to create parent directories, b'F' otherwise.
            dir_mode: Directory mode as bytes, or empty bytes for default.
        """
        relpath = self.translate_client_path(relpath)
        self._relpath = relpath
        self._dir_mode = _deserialise_optional_mode(dir_mode)
        self._mode = _deserialise_optional_mode(mode)
        # a boolean would be nicer XXX
        self._create_parent = create_parent == b"T"

    def do_body(self, body_bytes):
        """Write the body bytes to the file non-atomically.

        Args:
            body_bytes: The bytes to write to the file.

        Returns:
            SuccessfulSmartServerResponse indicating success.
        """
        self._backing_transport.put_bytes_non_atomic(
            self._relpath,
            body_bytes,
            mode=self._mode,
            create_parent_dir=self._create_parent,
            dir_mode=self._dir_mode,
        )
        return request.SuccessfulSmartServerResponse((b"ok",))


class ReadvRequest(VfsRequest):
    """Smart server request to read multiple ranges from a file."""

    def do(self, relpath):
        """Prepare to read multiple ranges from a file.

        Args:
            relpath: Relative path to the file to read from.
        """
        relpath = self.translate_client_path(relpath)
        self._relpath = relpath

    def do_body(self, body_bytes):
        """Accept offsets for a readv request.

        Args:
            body_bytes: Body containing offset,length pairs separated by newlines.

        Returns:
            SuccessfulSmartServerResponse with concatenated read data.
        """
        offsets = self._deserialise_offsets(body_bytes)
        backing_bytes = b"".join(
            bytes
            for offset, bytes in self._backing_transport.readv(self._relpath, offsets)
        )
        return request.SuccessfulSmartServerResponse((b"readv",), backing_bytes)

    def _deserialise_offsets(self, text):
        """Deserialise offset,length pairs from text.

        Args:
            text: Text containing offset,length pairs separated by newlines.

        Returns:
            List of (offset, length) tuples.

        Note:
            XXX: FIXME this should be on the protocol object.
        """
        offsets = []
        for line in text.split(b"\n"):
            if not line:
                continue
            start, length = line.split(b",")
            offsets.append((int(start), int(length)))
        return offsets


class RenameRequest(VfsRequest):
    """Smart server request to rename a file or directory."""

    def do(self, rel_from, rel_to):
        """Rename a file or directory from one path to another.

        Args:
            rel_from: Relative source path.
            rel_to: Relative destination path.

        Returns:
            SuccessfulSmartServerResponse indicating success.
        """
        rel_from = self.translate_client_path(rel_from)
        rel_to = self.translate_client_path(rel_to)
        self._backing_transport.rename(rel_from, rel_to)
        return request.SuccessfulSmartServerResponse((b"ok",))


class RmdirRequest(VfsRequest):
    """Smart server request to remove a directory."""

    def do(self, relpath):
        """Remove a directory at the given path.

        Args:
            relpath: Relative path to the directory to remove.

        Returns:
            SuccessfulSmartServerResponse indicating success.
        """
        relpath = self.translate_client_path(relpath)
        self._backing_transport.rmdir(relpath)
        return request.SuccessfulSmartServerResponse((b"ok",))


class StatRequest(VfsRequest):
    """Smart server request to get file/directory statistics."""

    def do(self, relpath):
        """Get statistics for a file or directory.

        Args:
            relpath: Relative path to the file or directory to stat.

        Returns:
            SuccessfulSmartServerResponse with size and mode information.
        """
        if not relpath.endswith(b"/"):
            relpath += b"/"
        relpath = self.translate_client_path(relpath)
        stat = self._backing_transport.stat(relpath)
        return request.SuccessfulSmartServerResponse(
            (
                b"stat",
                str(stat.st_size).encode("ascii"),
                oct(stat.st_mode).encode("ascii"),
            )
        )
