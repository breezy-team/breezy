# Copyright (C) 2005, 2006, 2008, 2009, 2010 Canonical Ltd
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

"""Atomic file operations.

This module provides AtomicFile, a class for writing files atomically.
Changes are written to a temporary file and then atomically renamed to
the target filename, ensuring that readers never see a partially-written file.
"""

import os
import stat

from breezy import errors, osutils

# not forksafe - but we dont fork.
_pid = os.getpid()
_hostname = None


class AtomicFileAlreadyClosed(errors.PathError):
    """Raised when an operation is attempted on a closed AtomicFile."""
    _fmt = '"%(function)s" called on an AtomicFile after it was closed: "%(path)s"'

    def __init__(self, path, function):
        """Initialize AtomicFileAlreadyClosed.

        Args:
            path: The path of the file.
            function: The function that was called on the closed file.
        """
        errors.PathError.__init__(self, path=path, extra=None)
        self.function = function


class AtomicFile:
    """A file that does an atomic-rename to move into place.

    This also causes hardlinks to break when it's written out.

    Open this as for a regular file, then use commit() to move into
    place or abort() to cancel.
    """

    __slots__ = ["_fd", "realfilename", "tmpfilename"]

    def __init__(self, filename, mode="wb", new_mode=None):
        """Initialize an AtomicFile.

        Args:
            filename: The target filename.
            mode: The file mode ('wb' or 'wt').
            new_mode: Unix permissions for the new file (octal).
        """
        global _hostname

        self._fd = None

        if _hostname is None:
            _hostname = osutils.get_host_name()

        self.tmpfilename = "%s.%d.%s.%s.tmp" % (
            filename,
            _pid,
            _hostname,
            osutils.rand_chars(10),
        )

        self.realfilename = filename

        flags = os.O_EXCL | os.O_CREAT | os.O_WRONLY | osutils.O_NOINHERIT
        if mode == "wb":
            flags |= osutils.O_BINARY
        elif mode != "wt":
            raise ValueError(f"invalid AtomicFile mode {mode!r}")

        local_mode = new_mode if new_mode is not None else 438

        # Use a low level fd operation to avoid chmodding later.
        # This may not succeed, but it should help most of the time
        self._fd = os.open(self.tmpfilename, flags, local_mode)

        if new_mode is not None:
            # Because of umask issues, we may need to chmod anyway
            # the common case is that we won't, though.
            st = os.fstat(self._fd)
            if stat.S_IMODE(st.st_mode) != new_mode:
                osutils.chmod_if_possible(self.tmpfilename, new_mode)

    def __repr__(self):
        """Return a string representation of the AtomicFile.

        Returns:
            A string representation showing the target filename.
        """
        return f"{self.__class__.__name__}({self.realfilename!r})"

    def write(self, data):
        """Write some data to the file. Like file.write()."""
        return os.write(self._fd, data)

    def _close_tmpfile(self, func_name):
        """Close the local temp file in preparation for commit or abort."""
        if self._fd is None:
            raise AtomicFileAlreadyClosed(path=self.realfilename, function=func_name)
        fd = self._fd
        self._fd = None
        os.close(fd)

    def commit(self):
        """Close the file and move to final name."""
        self._close_tmpfile("commit")
        osutils.rename(self.tmpfilename, self.realfilename)

    def abort(self):
        """Discard temporary file without committing changes."""
        self._close_tmpfile("abort")
        os.remove(self.tmpfilename)

    def close(self):
        """Discard the file unless already committed."""
        if self._fd is not None:
            self.abort()

    def __enter__(self):
        """Enter the context manager.

        Returns:
            The AtomicFile instance.
        """
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit the context manager.

        If an exception occurred, abort the operation. Otherwise, commit.

        Args:
            exc_type: Exception type if an exception occurred.
            exc_val: Exception value if an exception occurred.
            exc_tb: Exception traceback if an exception occurred.

        Returns:
            False to propagate any exception.
        """
        if exc_type:
            self.abort()
            return False
        self.commit()
