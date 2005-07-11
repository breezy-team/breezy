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
Stores are the main data-storage mechanism for Bazaar-NG.

A store is a simple write-once container indexed by a universally
unique ID.
"""

import os, tempfile, osutils, gzip, errno
from stat import ST_SIZE
from StringIO import StringIO
from trace import mutter

######################################################################
# stores

class StoreError(Exception):
    pass

class Storage(object):
    """This class represents the abstract storage layout for saving information.
    """
    def __init__(self, transport):
        self._transport = transport
        self._max_buffered_requests = 10

    def __repr__(self):
        return "%s(%r)" % (self.__class__.__name__, self._transport.base)

    __str__ == __repr__

    def __len__(self):
        raise NotImplementedError('Children should define their length')

    def __getitem__(self, fileid):
        """Returns a file reading from a particular entry."""
        raise NotImplementedError

    def __contains__(self, fileid):
        """"""
        raise NotImplementedError

    def __iter__(self):
        raise NotImplementedError

    def add(self, f, fileid):
        """Add a file object f to the store accessible from the given fileid"""
        raise NotImplementedError('Children of Storage must define their method of adding entries.')

    def copy_multi(self, other, ids):
        """Copy texts for ids from other into self.

        If an id is present in self, it is skipped.  A count of copied
        ids is returned, which may be less than len(ids).
        """
        from bzrlib.progress import ProgressBar
        pb = ProgressBar()
        pb.update('preparing to copy')
        to_copy = [fileid for fileid in ids if fileid not in self]
        return self._do_copy(other, to_copy, pb)

    def _do_copy(self, other, to_copy, pb):
        """This is the standard copying mechanism, just get them one at
        a time from remote, and store them locally.
        """
        count = 0
        buffered_requests = []
        for fileid in to_copy:
            buffered_requests.append((other[fileid], fileid))
            if len(buffered_requests) > self._max_buffered_requests:
                self.add(*buffered_requests.pop(0))
                count += 1
                pb.update('copy', count, len(to_copy))

        for req in buffered_requests:
            self.add(*req)
            count += 1
            pb.update('copy', count, len(to_copy))

        assert count == len(to_copy)
        pb.clear()
        return count



class CompressedTextStore(Storage):
    """Store that holds files indexed by unique names.

    Files can be added, but not modified once they are in.  Typically
    the hash is used as the name, or something else known to be unique,
    such as a UUID.

    Files are stored gzip compressed, with no delta compression.

    >>> st = ScratchFlatTextStore()

    >>> st.add(StringIO('hello'), 'aa')
    >>> 'aa' in st
    True
    >>> 'foo' in st
    False

    You are not allowed to add an id that is already present.

    Entries can be retrieved as files, which may then be read.

    >>> st.add(StringIO('goodbye'), '123123')
    >>> st['123123'].read()
    'goodbye'

    TODO: Atomic add by writing to a temporary file and renaming.

    In bzr 0.0.5 and earlier, files within the store were marked
    readonly on disk.  This is no longer done but existing stores need
    to be accomodated.
    """

    def __init__(self, basedir):
        super(CompressedTextStore, self).__init__(basedir)

    def _path(self, fileid):
        if '\\' in fileid or '/' in fileid:
            raise ValueError("invalid store id %r" % fileid)
        return self._transport.get_filename(fileid)

    def __repr__(self):
        return "%s(%r)" % (self.__class__.__name__, self._location)

    def add(self, f, fileid, compressed=True):
        """Add contents of a file into the store.

        f -- An open file, or file-like object."""
        # FIXME: Only works on files that will fit in memory
        
        from cStringIO import StringIO
        
        mutter("add store entry %r" % (fileid))
        if isinstance(f, basestring):
            content = f
        else:
            content = f.read()
            
        if self._transport.has(fileid) or self._transport.has(fileid + '.gz'):
            raise BzrError("store %r already contains id %r" % (self._location, fileid))

        fn = fileid
        if compressed:
            fn = fn + '.gz'
            
        sio = StringIO()
        if compressed:
            gf = gzip.GzipFile(mode='wb', fileobj=sio)
            gf.write(content)
            gf.close()
        else:
            sio.write(content)
        sio.seek(0)
        self._transport.put(fn, sio)

    def _do_copy(self, other, to_copy, pb):
        if isinstance(other, CompressedTextStore):
            return self._copy_multi_text(other, to_copy, pb)
        return super(CompressedTextStore, self)._do_copy(other, to_copy, pb)


    def _copy_multi_text(self, other, to_copy, pb):
        from shutil import copyfile
        count = 0
        for id in to_copy:
            p = self._path(id)
            other_p = other._path(id)
            try:
                copyfile(other_p, p)
            except IOError, e:
                if e.errno == errno.ENOENT:
                    copyfile(other_p+".gz", p+".gz")
                else:
                    raise
            
            count += 1
            pb.update('copy', count, len(to_copy))
        assert count == len(to_copy)
        pb.clear()
        return count
    

    def __contains__(self, fileid):
        """"""
        p = self._path(fileid)
        return (os.access(p, os.R_OK)
                or os.access(p + '.gz', os.R_OK))

    # TODO: Guard against the same thing being stored twice, compressed and uncompresse

    def __iter__(self):
        for f in os.listdir(self._location):
            if f[-3:] == '.gz':
                # TODO: case-insensitive?
                yield f[:-3]
            else:
                yield f

    def __len__(self):
        return len(os.listdir(self._location))

    def __getitem__(self, fileid):
        """Returns a file reading from a particular entry."""
        p = self._path(fileid)
        try:
            return gzip.GzipFile(p + '.gz', 'rb')
        except IOError, e:
            if e.errno == errno.ENOENT:
                return file(p, 'rb')
            else:
                raise e

    def total_size(self):
        """Return (count, bytes)

        This is the (compressed) size stored on disk, not the size of
        the content."""
        total = 0
        count = 0
        for fid in self:
            count += 1
            p = self._path(fid)
            try:
                total += os.stat(p)[ST_SIZE]
            except OSError:
                total += os.stat(p + '.gz')[ST_SIZE]
                
        return count, total




class ScratchFlatTextStore(CompressedTextStore):
    """Self-destructing test subclass of ImmutableStore.

    The Store only exists for the lifetime of the Python object.
    Obviously you should not put anything precious in it.
    """
    def __init__(self):
        super(ScratchFlatTextStore, self).__init__(tempfile.mkdtemp())

    def __del__(self):
        for f in os.listdir(self._location):
            fpath = os.path.join(self._location, f)
            # needed on windows, and maybe some other filesystems
            os.chmod(fpath, 0600)
            os.remove(fpath)
        os.rmdir(self._location)
        mutter("%r destroyed" % self)
