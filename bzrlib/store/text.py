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
from bzrlib.errors import BzrError, FileExists

from cStringIO import StringIO
from stat import ST_SIZE


class TextStore(bzrlib.store.TransportStore):
    """Store that holds files indexed by unique names.

    Files can be added, but not modified once they are in.  Typically
    the hash is used as the name, or something else known to be unique,
    such as a UUID.

    Files are stored uncompressed, with no delta compression.
    """

    def __init__(self, transport, prefixed=False):
        super(TextStore, self).__init__(transport)
        self._prefixed = prefixed

    def _check_fileid(self, fileid):
        if not isinstance(fileid, basestring):
            raise TypeError('Fileids should be a string type: %s %r' % (type(fileid), fileid))
        if '\\' in fileid or '/' in fileid:
            raise ValueError("invalid store id %r" % fileid)

    def _relpath(self, fileid):
        self._check_fileid(fileid)
        if self._prefixed:
            return hash_prefix(fileid) + fileid
        else:
            return fileid

    def add(self, f, fileid):
        """Add contents of a file into the store.

        f -- A file-like object, or string
        """
        mutter("add store entry %r" % (fileid))
            
        fn = self._relpath(fileid)
        if self._transport.has(fn):
            raise BzrError("store %r already contains id %r" % (self._transport.base, fileid))

        if self._prefixed:
            try:
                self._transport.mkdir(hash_prefix(fileid))
            except FileExists:
                pass

        self._transport.put(fn, f)

    def __contains__(self, fileid):
        """"""
        fn = self._relpath(fileid)
        return self._transport.has(fn)

    def has(self, fileids, pb=None):
        """Return True/False for each entry in fileids.

        :param fileids: A List or generator yielding file ids.
        :return: A generator or list returning True/False for each entry.
        """
        relpaths = (self._relpath(fid) for fid in fileids)
        return self._transport.has_multi(relpaths, pb=pb)

    def get(self, fileids, permit_failure=False, pb=None):
        """Return a set of files, one for each requested entry.
        
        TODO: Write some tests to make sure that permit_failure is
              handled correctly.

        TODO: What should the exception be for a missing file?
              KeyError, or NoSuchFile?
        """

        # This next code gets a bit hairy because it can allow
        # to not request a file which doesn't seem to exist.
        # Also, the same fileid may be requested twice, so we
        # can't just build up a map.
        rel_paths = [self._relpath(fid) for fid in fileids]
        is_requested = []

        if permit_failure:
            existing_paths = []
            for path, has in zip(rel_paths,
                    self._transport.has_multi(rel_paths)):
                if has:
                    existing_paths.append(path)
                    is_requested.append(True)
                else:
                    is_requested.append(False)
            #mutter('Retrieving %s out of %s' % (existing_paths, rel_paths))
        else:
            #mutter('Retrieving all %s' % (rel_paths, ))
            existing_paths = rel_paths
            is_requested = [True for x in rel_paths]

        count = 0
        for f in self._transport.get_multi(existing_paths, pb=pb):
            assert count < len(is_requested)
            while not is_requested[count]:
                yield None
                count += 1
            yield f
            count += 1

        while count < len(is_requested):
            yield None
            count += 1

    def __iter__(self):
        for relpath, st in self._iter_relpaths():
            yield os.path.basename(relpath)

    def __len__(self):
        return len(list(self._iter_relpath()))

    def total_size(self):
        """Return (count, bytes)

        This is the (compressed) size stored on disk, not the size of
        the content."""
        total = 0
        count = 0
        for relpath, st in self._iter_relpaths():
            count += 1
            total += st[ST_SIZE]
                
        return count, total


class ScratchTextStore(TextStore):
    """Self-destructing test subclass of TextStore.

    The Store only exists for the lifetime of the Python object.
    Obviously you should not put anything precious in it.
    """
    def __init__(self):
        from transport import transport
        super(ScratchTextStore, self).__init__(transport(tempfile.mkdtemp()))

    def __del__(self):
        self._transport.delete_multi(self._transport.list_dir('.'))
        os.rmdir(self._transport.base)
        mutter("%r destroyed" % self)

