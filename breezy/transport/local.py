# Copyright (C) 2005-2012, 2016 Canonical Ltd
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

"""Transport for the local filesystem.

This is a fairly thin wrapper on regular file IO.
"""

import os

from .. import osutils, transport, urlutils


def file_stat(f, _lstat=os.lstat):
    try:
        return _lstat(f)
    except (FileNotFoundError, NotADirectoryError) as err:
        raise transport.NoSuchFile(f) from err


def file_kind(f, _lstat=os.lstat):
    stat_value = file_stat(f, _lstat)
    return osutils.file_kind_from_stat_mode(stat_value.st_mode)


from .._transport_rs.local import LocalTransport  # type:ignore


class EmulatedWin32LocalTransport(LocalTransport):  # type:ignore
    """Special transport for testing Win32 [UNC] paths on non-windows."""

    def __init__(self, base):
        if base[-1] != "/":
            base = base + "/"
        super(LocalTransport, self).__init__(base)
        self._local_base = urlutils._win32_local_path_from_url(base)

    def abspath(self, relpath):
        path = osutils._win32_normpath(
            osutils.pathjoin(self._local_base, urlutils.unescape(relpath))
        )
        return urlutils._win32_local_path_to_url(path)

    def clone(self, offset=None):
        """Return a new LocalTransport with root at self.base + offset
        Because the local filesystem does not require a connection,
        we can just return a new object.
        """
        if offset is None:
            return EmulatedWin32LocalTransport(self.base)
        else:
            abspath = self.abspath(offset)
            if abspath == "file://":
                # fix upwalk for UNC path
                # when clone from //HOST/path updir recursively
                # we should stop at least at //HOST part
                abspath = self.base
            return EmulatedWin32LocalTransport(abspath)


def get_test_permutations():
    """Return the permutations to be used in testing."""
    from ..tests import test_server

    return [
        (LocalTransport, test_server.LocalURLServer),
    ]
