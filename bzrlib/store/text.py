# Copyright (C) 2005 by Canonical Development Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""
A store that keeps the full text of every version.

This store keeps uncompressed versions of the full text. It does not
do any sort of delta compression.
"""

import os, tempfile

import bzrlib.store
from bzrlib.store import hash_prefix
from bzrlib.trace import mutter
from bzrlib.errors import BzrError

from cStringIO import StringIO


class TextStore(bzrlib.store.TransportStore):
    """Store that holds files indexed by unique names.

    Files can be added, but not modified once they are in.  Typically
    the hash is used as the name, or something else known to be unique,
    such as a UUID.

    Files are stored uncompressed, with no delta compression.
    """

    def _add(self, fn, f):
        self._transport.put(fn, f)

    def _get(self, fn):
        return self._transport.get(fn)

    def __iter__(self):
        for relpath, st in self._iter_relpaths():
            yield os.path.basename(relpath)


def ScratchTextStore():
    return TextStore(ScratchTransport())
