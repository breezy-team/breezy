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

"""A store that keeps the full text of every version.

This store keeps uncompressed versions of the full text. It does not
do any sort of delta compression.
"""

import gzip
import os
from io import BytesIO

from .... import osutils
from ....transport import FileExists, NoSuchFile
from . import TransportStore


class TextStore(TransportStore):
    """Store that holds files indexed by unique names.

    Files can be added, but not modified once they are in.  Typically
    the hash is used as the name, or something else known to be unique,
    such as a UUID.

    Files are stored uncompressed, with no delta compression.
    """

    def _add_compressed(self, fn, f):
        if isinstance(f, bytes):
            f = BytesIO(f)

        sio = BytesIO()
        gf = gzip.GzipFile(mode="wb", fileobj=sio)
        # if pumpfile handles files that don't fit in ram,
        # so will this function
        osutils.pumpfile(f, gf)
        gf.close()
        sio.seek(0)
        self._try_put(fn, sio)

    def _add(self, fn, f):
        if self._compressed:
            self._add_compressed(fn, f)
        else:
            self._try_put(fn, f)

    def _try_put(self, fn, f):
        try:
            self._transport.put_file(fn, f, mode=self._file_mode)
        except NoSuchFile:
            if not self._prefixed:
                raise
            try:
                self._transport.mkdir(os.path.dirname(fn), mode=self._dir_mode)
            except FileExists:
                pass
            self._transport.put_file(fn, f, mode=self._file_mode)

    def _get(self, fn):
        if fn.endswith(".gz"):
            return self._get_compressed(fn)
        else:
            return self._transport.get(fn)

    def _get_compressed(self, filename):
        """Returns a file reading from a particular entry."""
        f = self._transport.get(filename)
        # gzip.GzipFile.read() requires a tell() function
        # but some transports return objects that cannot seek
        # so buffer them in a BytesIO instead
        if getattr(f, "tell", None) is not None:
            return gzip.GzipFile(mode="rb", fileobj=f)
        try:
            sio = BytesIO(f.read())
            return gzip.GzipFile(mode="rb", fileobj=sio)
        finally:
            f.close()
