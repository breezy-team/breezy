# Copyright (C) 2006 Canonical Ltd
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

"""Fake transport with some restrictions of Windows VFAT filesystems.

VFAT on Windows has several restrictions that are not present on unix
filesystems, which are imposed by this transport.

VFAT is strictly 8-bit using codepages to represent non-ascii characters.
This implementation currently doesn't model the codepage but just insists
on only ascii characters being written.

Restrictions imposed by this transport:

 * filenames are squashed to lowercase
 * filenames containing non-ascii characters are not allowed
 * filenames containing the characters "@<>" are not allowed
   (there should be more?)

Some other restrictions are not implemented yet, but possibly could be:

 * open files can't be deleted or renamed
 * directories containing open files can't be renamed
 * special device names (NUL, LPT, ...) are not allowed

"""

import re

from . import decorator

# TODO: It might be nice if these hooks were available in a more general way
# on all paths passed in to the Transport, so that we didn't have to hook
# every single method.

# TODO: Perhaps don't inherit from TransportDecorator so that methods
# which are not implemented here fail by default?


class FakeVFATTransportDecorator(decorator.TransportDecorator):
    """A decorator that can convert any transport to be readonly.

    This is requested via the 'vfat+' prefix to get_transport().

    This is intended only for use in testing and doesn't implement every
    method very well yet.

    This transport is typically layered on a local or memory transport
    which actually stored the files.
    """

    def _can_roundtrip_unix_modebits(self):
        """See Transport._can_roundtrip_unix_modebits()."""
        return False

    @classmethod
    def _get_url_prefix(self):
        """Readonly transport decorators are invoked via 'vfat+'."""
        return "vfat+"

    def _squash_name(self, name):
        """Return vfat-squashed filename.

        The name is returned as it will be stored on disk.  This raises an
        error if there are invalid characters in the name.
        """
        if re.search(r"[?*:;<>]", name):
            raise ValueError(f"illegal characters for VFAT filename: {name!r}")
        return name.lower()

    def get(self, relpath):
        """Get a file from the transport.

        Args:
            relpath: Relative path to the file.

        Returns:
            File-like object for reading.
        """
        return self._decorated.get(self._squash_name(relpath))

    def mkdir(self, relpath, mode=None):
        """Create a directory.

        Args:
            relpath: Relative path of directory to create.
            mode: Permissions mode (ignored, always uses 0o755).

        Returns:
            Result from decorated transport's mkdir.
        """
        return self._decorated.mkdir(self._squash_name(relpath), 0o755)

    def has(self, relpath):
        """Check if a path exists.

        Args:
            relpath: Relative path to check.

        Returns:
            bool: True if the path exists.
        """
        return self._decorated.has(self._squash_name(relpath))

    def _readv(self, relpath, offsets):
        return self._decorated.readv(self._squash_name(relpath), offsets)

    def put_file(self, relpath, f, mode=None):
        """Write a file to the transport.

        Args:
            relpath: Relative path where to write the file.
            f: File-like object to read from.
            mode: Permissions mode for the file.

        Returns:
            Result from decorated transport's put_file.
        """
        return self._decorated.put_file(self._squash_name(relpath), f, mode)


def get_test_permutations():
    """Return the permutations to be used in testing."""
    from breezy.tests import test_server

    return [
        (FakeVFATTransportDecorator, test_server.FakeVFATServer),
    ]
