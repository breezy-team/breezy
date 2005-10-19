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
An implementation the primary storage type CompressedTextStore.

This store keeps compressed versions of the full text. It does not
do any sort of delta compression.
"""

import gzip

import bzrlib.store
from bzrlib.trace import mutter
from bzrlib.errors import BzrError, FileExists

from StringIO import StringIO

class CompressedTextStore(bzrlib.store.TransportStore):
    """Store that holds files indexed by unique names.

    Files can be added, but not modified once they are in.  Typically
    the hash is used as the name, or something else known to be unique,
    such as a UUID.

    Files are stored gzip compressed, with no delta compression.

    >>> st = ScratchCompressedTextStore()

    >>> st.add(StringIO('hello'), 'aa')
    >>> 'aa' in st
    True
    >>> 'foo' in st
    False

    You are not allowed to add an id that is already present.

    Entries can be retrieved as files, which may then be read.

    >>> st.add(StringIO('goodbye'), '123123')
    >>> st.get('123123').read()
    'goodbye'
    """

    def _relpath(self, fileid, suffixes=[]):
        suffixes = suffixes + ['gz']
        return super(CompressedTextStore, self)._relpath(fileid, suffixes)

    def _add(self, fn, f):
        from cStringIO import StringIO
        from bzrlib.osutils import pumpfile
        
        if isinstance(f, basestring):
            f = StringIO(f)
            
        sio = StringIO()
        gf = gzip.GzipFile(mode='wb', fileobj=sio)
        # if pumpfile handles files that don't fit in ram,
        # so will this function
        if isinstance(f, basestring):
            gf.write(f)
        else:
            pumpfile(f, gf)
        gf.close()
        sio.seek(0)
        self._transport.put(fn, sio)

    def _copy_one(self, fileid, suffix, other, pb):
        if not (isinstance(other, CompressedTextStore)
            and other._prefixed == self._prefixed):
            return super(CompressedTextStore, self)._copy_one(fileid, suffix,
                                                              other, pb)
        if suffix is None or suffix == 'gz':
            path = self._relpath(fileid)
        else:
            path = self._relpath(fileid, [suffix])
        assert other._transport.copy_to([path], self._transport, pb=pb) == 1

    def __init__(self, transport, prefixed=False):
        super(CompressedTextStore, self).__init__(transport, prefixed)
        self.register_suffix('gz')

    def _get(self, filename):
        """Returns a file reading from a particular entry."""
        f = self._transport.get(filename)
        # gzip.GzipFile.read() requires a tell() function
        # but some transports return objects that cannot seek
        # so buffer them in a StringIO instead
        if hasattr(f, 'tell'):
            return gzip.GzipFile(mode='rb', fileobj=f)
        else:
            from cStringIO import StringIO
            sio = StringIO(f.read())
            return gzip.GzipFile(mode='rb', fileobj=sio)


def ScratchTextStore():
    return TextStore(ScratchTransport())
