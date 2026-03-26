#!/usr/bin/env python3
# Copyright (C) 2005-2024 Canonical Ltd
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

"""Operating system utilities for dromedary transport layer."""

import errno
import fcntl
import os
import random
import stat
import string
import sys


def pumpfile(from_file, to_file, read_length=-1):
    """Copy data from one file to another.

    This is similar to shutil.copyfileobj, but allows control over
    the read length.

    Args:
        from_file: File-like object to read from
        to_file: File-like object to write to
        read_length: Size of chunks to read at a time, -1 for default
    """
    if read_length == -1:
        # Default chunk size
        read_length = 65536

    while True:
        data = from_file.read(read_length)
        if not data:
            break
        to_file.write(data)


def pump_string_file(string, to_file, segment_size=8192):
    """Write a string to a file efficiently.

    Args:
        string: String or bytes to write
        to_file: File-like object to write to
        segment_size: Size of chunks to write
    """
    if isinstance(string, str):
        string = string.encode("utf-8")

    offset = 0
    while offset < len(string):
        segment = string[offset : offset + segment_size]
        to_file.write(segment)
        offset += len(segment)


def fancy_rename(old, new):
    """Rename a file, handling cross-platform issues.

    On Unix, this is an atomic operation. On Windows, it handles
    the case where the target file already exists.

    Args:
        old: Source filename
        new: Target filename
    """
    try:
        os.rename(old, new)
    except OSError as e:
        if sys.platform == "win32" and e.errno == errno.EEXIST:
            # On Windows, rename doesn't overwrite existing files
            os.unlink(new)
            os.rename(old, new)
        else:
            raise


def fdatasync(fileno):
    """Force data to be written to disk.

    Args:
        fileno: File descriptor or file object with fileno() method
    """
    if hasattr(fileno, "fileno"):
        fileno = fileno.fileno()

    if hasattr(os, "fdatasync"):
        os.fdatasync(fileno)
    elif hasattr(os, "fsync"):
        os.fsync(fileno)
    # If neither is available, do nothing (some platforms don't support this)


def file_kind_from_stat_mode(stat_mode):
    """Determine file type from stat mode bits.

    Args:
        stat_mode: Mode from os.stat()

    Returns:
        String describing file type: 'file', 'directory', 'symlink'
    """
    if stat.S_ISREG(stat_mode):
        return "file"
    elif stat.S_ISDIR(stat_mode):
        return "directory"
    elif stat.S_ISLNK(stat_mode):
        return "symlink"
    elif stat.S_ISCHR(stat_mode):
        return "chardev"
    elif stat.S_ISBLK(stat_mode):
        return "block"
    elif stat.S_ISFIFO(stat_mode):
        return "fifo"
    elif stat.S_ISSOCK(stat_mode):
        return "socket"
    else:
        return "unknown"


def set_fd_cloexec(fd):
    """Set the close-on-exec flag for a file descriptor.

    Args:
        fd: File descriptor or file object with fileno() method
    """
    if hasattr(fd, "fileno"):
        fd = fd.fileno()

    if hasattr(fcntl, "FD_CLOEXEC"):
        flags = fcntl.fcntl(fd, fcntl.F_GETFD)
        fcntl.fcntl(fd, fcntl.F_SETFD, flags | fcntl.FD_CLOEXEC)


def rand_chars(n):
    """Generate random characters.

    Args:
        n: Number of characters to generate

    Returns:
        String of random alphanumeric characters
    """
    chars = string.ascii_letters + string.digits
    return "".join(random.choice(chars) for _ in range(n))  # noqa: S311


def splitpath(path):
    """Split a path into components.

    Args:
        path: Path to split

    Returns:
        List of path components
    """
    if not path or path == "/":
        return []

    # Remove leading slash for consistent behavior
    if path.startswith("/"):
        path = path[1:]

    # Remove trailing slash
    if path.endswith("/"):
        path = path[:-1]

    if not path:
        return []

    return path.split("/")


def pathjoin(*args):
    """Join path components, handling various edge cases.

    Args:
        *args: Path components to join

    Returns:
        Joined path
    """
    if not args:
        return ""

    # Filter out empty components
    components = [arg for arg in args if arg and arg != "."]

    if not components:
        return ""

    # Join with forward slashes (transport paths use forward slashes)
    result = "/".join(components)

    # Handle absolute paths
    if args[0].startswith("/"):
        result = "/" + result

    return result


def get_terminal_encoding():
    """Get the terminal's character encoding.

    Returns:
        String name of encoding, defaults to 'utf-8'
    """
    import locale

    # Try to get the terminal encoding
    encoding = None

    if hasattr(sys.stdout, "encoding") and sys.stdout.encoding:
        encoding = sys.stdout.encoding

    if not encoding:
        try:
            encoding = locale.getpreferredencoding()
        except Exception:
            pass

    if not encoding:
        encoding = "utf-8"  # Safe default

    return encoding


def _win32_normpath(path):
    """Normalize a Windows path.
    
    This is used on Windows to normalize path separators and handle
    drive letters properly.
    
    Args:
        path: Path to normalize
        
    Returns:
        Normalized path string
    """
    if sys.platform == "win32":
        # On Windows, normalize path separators and handle drive letters
        import os.path
        return os.path.normpath(path).replace('\\', '/')
    else:
        # On non-Windows, just return the path as-is
        return path
