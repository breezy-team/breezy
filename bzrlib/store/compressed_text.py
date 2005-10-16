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

import os, tempfile, gzip

import bzrlib.store
from bzrlib.store import hash_prefix
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

    def _do_copy(self, other, to_copy, pb, permit_failure=False):
        if isinstance(other, CompressedTextStore):
            return self._copy_multi_text(other, to_copy, pb,
                    permit_failure=permit_failure)
        return super(CompressedTextStore, self)._do_copy(other, to_copy,
                pb, permit_failure=permit_failure)

    def _copy_multi_text(self, other, to_copy, pb,
            permit_failure=False):
        # Because of _transport, we can no longer assume
        # that they are on the same filesystem, we can, however
        # assume that we only need to copy the exact bytes,
        # we don't need to process the files.

        failed = set()
        if permit_failure:
            new_to_copy = set()
            for fileid, has in zip(to_copy, other.has(to_copy)):
                if has:
                    new_to_copy.add(fileid)
                else:
                    failed.add(fileid)
            to_copy = new_to_copy
            #mutter('_copy_multi_text copying %s, failed %s' % (to_copy, failed))

        paths = [self._relpath(fileid) for fileid in to_copy]
        count = other._transport.copy_to(paths, self._transport, pb=pb)
        assert count == len(to_copy)
        return count, failed

    def has(self, fileids, pb=None):
        """Return True/False for each entry in fileids.

        :param fileids: A List or generator yielding file ids.
        :return: A generator or list returning True/False for each entry.
        """
        relpaths = (self._relpath(fid) for fid in fileids)
        return self._transport.has_multi(relpaths, pb=pb)

    def __iter__(self):
        for relpath, st in self._iter_relpaths():
            if relpath.endswith(".gz"):
                yield os.path.basename(relpath)[:-3]
            else:
                yield os.path.basename(relpath)

    def __len__(self):
        return len(list(self._iter_relpath()))

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


class ScratchCompressedTextStore(CompressedTextStore):
    """Self-destructing test subclass of CompressedTextStore.

    The Store only exists for the lifetime of the Python object.
    Obviously you should not put anything precious in it.
    """
    def __init__(self):
        from transport import transport
        t = transport(tempfile.mkdtemp())
        super(ScratchCompressedTextStore, self).__init__(t)

    def __del__(self):
        self._transport.delete_multi(self._transport.list_dir('.'))
        os.rmdir(self._transport.base)
        mutter("%r destroyed" % self)

