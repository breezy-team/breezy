# Copyright (C) 2025 Breezy Contributors
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

"""OS utilities for bzrformats using only standard library."""

import hashlib
import logging
import os
import shutil
import unicodedata


def split(path):
    """Split a pathname into directory and basename parts.

    This is a replacement for breezy.osutils.split that uses os.path.split.
    """
    if isinstance(path, bytes):
        return os.path.split(path)
    else:
        # For unicode strings, encode to UTF-8, split, then decode
        encoded = path.encode("utf-8")
        dirname, basename = os.path.split(encoded)
        return dirname.decode("utf-8"), basename.decode("utf-8")


def pathjoin(*args):
    """Join paths together.

    This is a replacement for breezy.osutils.pathjoin that uses os.path.join.
    """
    if not args:
        return b"" if isinstance(args[0], bytes) else ""

    # Check if we're dealing with bytes or strings
    if isinstance(args[0], bytes):
        return os.path.join(*args)
    else:
        # For unicode strings, encode to UTF-8, join, then decode
        encoded_args = [arg.encode("utf-8") for arg in args]
        result = os.path.join(*encoded_args)
        return result.decode("utf-8")


def pumpfile(from_file, to_file, buffer_size=65536):
    """Copy data from one file-like object to another.

    This is a replacement for breezy.osutils.pumpfile using shutil.copyfileobj.
    Returns the number of bytes copied.
    """
    initial_pos = to_file.tell() if hasattr(to_file, "tell") else 0
    shutil.copyfileobj(from_file, to_file, buffer_size)
    if hasattr(to_file, "tell"):
        return to_file.tell() - initial_pos
    else:
        # If we can't tell the position, we can't return accurate byte count
        return 0


def chunks_to_lines(chunks):
    """Convert chunks to lines.

    This is a replacement for breezy.osutils.chunks_to_lines.
    """
    if not chunks:
        return []

    # Join all chunks
    data = b"".join(chunks)

    # Split into lines, keeping line endings
    lines = []
    start = 0
    for i, byte in enumerate(data):
        if byte == ord(b"\n"):
            lines.append(data[start : i + 1])
            start = i + 1

    # Add remaining data if any
    if start < len(data):
        lines.append(data[start:])

    return lines


def normalized_filename(filename):
    """Return the normalized form of a filename.

    This is a simplified replacement for breezy.osutils.normalized_filename.
    Returns (normalized_name, can_access) tuple.
    """
    if isinstance(filename, bytes):
        # For bytes, try to decode as UTF-8 first
        try:
            unicode_filename = filename.decode("utf-8")
        except UnicodeDecodeError:
            # If it's not valid UTF-8, return as-is
            return filename, True
    else:
        unicode_filename = filename

    # Normalize using NFC (Canonical Decomposition, followed by Canonical Composition)
    normalized = unicodedata.normalize("NFC", unicode_filename)

    if isinstance(filename, bytes):
        try:
            return normalized.encode("utf-8"), True
        except UnicodeEncodeError:
            return filename, True
    else:
        return normalized, True


def failed_to_load_extension(exception):
    """Log a message about a failed extension load.

    This is a replacement for breezy.osutils.failed_to_load_extension.
    """
    logging.debug("Failed to load extension: %s", exception)


def fdatasync(fileno):
    """Flush file contents to disk, not metadata.

    This is a replacement for breezy.osutils.fdatasync.
    """
    try:
        os.fdatasync(fileno)
    except AttributeError:
        # fdatasync is not available on all platforms (e.g., Windows)
        # Fall back to fsync which is more widely available
        os.fsync(fileno)


def splitpath(path):
    """Split a path into a list of components.

    This is a replacement for breezy.osutils.splitpath.
    """
    if isinstance(path, bytes):
        if path.startswith(b"/"):
            path = path[1:]
        if not path:
            return []
        return path.split(b"/")
    else:
        if path.startswith("/"):
            path = path[1:]
        if not path:
            return []
        return path.split("/")


def file_kind_from_stat_mode(mode):
    """Return the file kind based on the stat mode.

    This is a replacement for breezy.osutils.file_kind_from_stat_mode.
    """
    import stat

    if stat.S_ISREG(mode):
        return "file"
    elif stat.S_ISDIR(mode):
        return "directory"
    elif stat.S_ISLNK(mode):
        return "symlink"
    elif stat.S_ISFIFO(mode):
        return "fifo"
    elif stat.S_ISSOCK(mode):
        return "socket"
    elif stat.S_ISCHR(mode):
        return "chardev"
    elif stat.S_ISBLK(mode):
        return "block"
    else:
        return "unknown"


def contains_whitespace(s):
    """Return True if the string contains whitespace characters.

    This is a replacement for breezy.osutils.contains_whitespace.
    """
    # Check for common whitespace characters
    if isinstance(s, bytes):
        return any(c in s for c in b" \t\n\r\v\f")
    else:
        return any(c in s for c in " \t\n\r\v\f")


def sha_strings(strings):
    """Return the sha1 of concatenated strings.

    This is a replacement for breezy.osutils.sha_strings.
    """
    sha = hashlib.sha1()  # noqa: S324
    for string in strings:
        if isinstance(string, str):
            # Convert unicode strings to bytes using UTF-8
            string = string.encode("utf-8")
        sha.update(string)
    return sha.hexdigest().encode("ascii")


def sha_string(string):
    """Return the sha1 of a single string.

    This is a replacement for breezy.osutils.sha_string.
    """
    if isinstance(string, str):
        # Convert unicode strings to bytes using UTF-8
        string = string.encode("utf-8")
    sha = hashlib.sha1()  # noqa: S324
    sha.update(string)
    return sha.hexdigest().encode("ascii")


def dirname(path):
    """Return the directory part of a path.

    This is a replacement for breezy.osutils.dirname.
    """
    if isinstance(path, bytes):
        return os.path.dirname(path)
    else:
        # For unicode strings, encode to UTF-8, get dirname, then decode
        encoded = path.encode("utf-8")
        result = os.path.dirname(encoded)
        return result.decode("utf-8")


def basename(path):
    """Return the basename part of a path.

    This is a replacement for breezy.osutils.basename.
    """
    if isinstance(path, bytes):
        return os.path.basename(path)
    else:
        # For unicode strings, encode to UTF-8, get basename, then decode
        encoded = path.encode("utf-8")
        result = os.path.basename(encoded)
        return result.decode("utf-8")


def chunks_to_lines_iter(chunks_iter):
    """Convert an iterator of chunks to an iterator of lines.

    This is a replacement for breezy.osutils.chunks_to_lines_iter.
    """
    buffer = b""
    for chunk in chunks_iter:
        buffer += chunk
        while b"\n" in buffer:
            line, buffer = buffer.split(b"\n", 1)
            yield line + b"\n"

    # Yield any remaining data as the last line (without newline)
    if buffer:
        yield buffer
