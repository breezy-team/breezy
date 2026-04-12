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


def pumpfile(from_file, to_file, read_length=-1, buff_size=32768):
    """Copy bytes from from_file to to_file, optionally limiting total length.

    Args:
        from_file: File-like object to read from.
        to_file: File-like object to write to.
        read_length: Total number of bytes to copy. -1 (the default) means
            copy to EOF.
        buff_size: Size of each individual read.

    Returns:
        The total number of bytes copied.
    """
    written = 0
    if read_length is not None and read_length >= 0:
        # Read exactly read_length bytes total, in buff_size chunks.
        bytes_left = read_length
        while bytes_left > 0:
            chunk = from_file.read(min(buff_size, bytes_left))
            if not chunk:
                break
            to_file.write(chunk)
            bytes_left -= len(chunk)
            written += len(chunk)
    else:
        while True:
            chunk = from_file.read(buff_size)
            if not chunk:
                break
            to_file.write(chunk)
            written += len(chunk)
    return written


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


def fancy_rename(old, new, rename_func, unlink_func):
    """A fancy rename, when you don't have atomic rename.

    :param old: The old path, to rename from
    :param new: The new path, to rename to
    :param rename_func: The potentially non-atomic rename function
    :param unlink_func: A way to delete the target file if the full rename
        succeeds
    """
    import time
    from dromedary.errors import NoSuchFile

    # sftp rename doesn't allow overwriting, so play tricks:
    base = os.path.basename(new)
    dirname = os.path.dirname(new)
    tmp_name = "tmp.%s.%.9f.%d.%s" % (base, time.time(), os.getpid(), rand_chars(10))
    tmp_name = pathjoin(dirname, tmp_name)

    # Rename the file out of the way, but keep track if it didn't exist
    file_existed = False
    try:
        rename_func(new, tmp_name)
    except NoSuchFile:
        pass
    except (FileNotFoundError, NotADirectoryError):
        pass
    except OSError:
        # paramiko SFTP rename raises IOError with errno=None on failure.
        raise
    except Exception as e:
        if getattr(e, "errno", None) is None or e.errno not in (
            errno.ENOENT,
            errno.ENOTDIR,
        ):
            raise
    else:
        file_existed = True

    success = False
    try:
        rename_func(old, new)
        success = True
    except FileNotFoundError:
        # source and target may be aliases of each other on a
        # case-insensitive filesystem
        if file_existed and old.lower() == new.lower():
            pass
        else:
            raise
    finally:
        if file_existed:
            if success:
                unlink_func(tmp_name)
            else:
                rename_func(tmp_name, new)


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


def getcwd():
    """Return the current working directory as a unicode string."""
    return os.getcwd()


def abspath(path):
    """Return the absolute version of a path."""
    return os.path.abspath(path)


def get_umask():
    """Return the current umask."""
    umask = os.umask(0)
    os.umask(umask)
    return umask


def supports_symlinks(path=None):
    """Return True if the filesystem supports symlinks."""
    return getattr(os, "symlink", None) is not None


def get_user_encoding():
    """Return the encoding used for user-facing text."""
    return get_terminal_encoding()


def _posix_normpath(path):
    return os.path.normpath(path)


normpath = os.path.normpath
split = os.path.split
MIN_ABS_PATHLENGTH = 3 if sys.platform == "win32" else 1


def _win32_abspath(path):
    return os.path.abspath(path)


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
