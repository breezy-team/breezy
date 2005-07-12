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
    _transport = None
    _max_buffered_requests = 10

    def __init__(self, transport):
        from transport import Transport
        assert isinstance(transport, Transport)
        self._transport = transport

    def __repr__(self):
        if self._transport is None:
            return "%s(None)" % (self.__class__.__name__)
        else:
            return "%s(%r)" % (self.__class__.__name__, self._transport.base)

    __str__ = __repr__

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

    def add(self, fileid, f):
        """Add a file object f to the store accessible from the given fileid"""
        raise NotImplementedError('Children of Storage must define their method of adding entries.')

    def add_multi(self, entries):
        """Add a series of file-like or string objects to the store with the given
        identities.
        
        :param entries: A list of tuples of id,file pairs [(id1, file1), (id2, file2), ...]
                        This could also be a generator yielding (id,file) pairs.
        """
        for fileid, f in entries:
            self.add(fileid, f)

    def copy_multi(self, other, ids):
        """Copy texts for ids from other into self.

        If an id is present in self, it is skipped.  A count of copied
        ids is returned, which may be less than len(ids).

        :param other: Another Storage object
        :param ids: A list of entry ids to be copied
        :return: The number of entries copied
        """
        from bzrlib.progress import ProgressBar
        pb = ProgressBar()
        pb.update('preparing to copy')
        to_copy = [fileid for fileid in ids if fileid not in self]
        return self._do_copy(other, to_copy, pb)

    def _do_copy(self, other, to_copy, pb):
        """This is the standard copying mechanism, just get them one at
        a time from remote, and store them locally.

        :param other: Another Storage object
        :param to_copy: A list of entry ids to copy
        :param pb: A ProgressBar object to display completion status.
        :return: The number of entries copied.
        """
        # This should be updated to use add_multi() rather than
        # the current methods of buffering requests.
        # One question, is it faster to queue up 1-10 and then copy 1-10
        # then queue up 11-20, copy 11-20
        # or to queue up 1-10, copy 1, queue 11, copy 2, etc?
        # sort of pipeline versus batch.

        # We can't use self._transport.copy_to because we don't know
        # whether the local tree is in the same format as other
        def buffer_requests():
            count = 0
            buffered_requests = []
            for fileid in to_copy:
                buffered_requests.append((fileid, other[fileid]))
                if len(buffered_requests) > self._max_buffered_requests:
                    yield buffered_requests.pop(0)
                    count += 1
                    pb.update('copy', count, len(to_copy))

            for req in buffered_requests:
                yield req
                count += 1
                pb.update('copy', count, len(to_copy))

            assert count == len(to_copy)

        self.add_multi(buffer_requests())

        pb.clear()
        return len(to_copy)

class CompressedTextStore(Storage):
    """Store that holds files indexed by unique names.

    Files can be added, but not modified once they are in.  Typically
    the hash is used as the name, or something else known to be unique,
    such as a UUID.

    Files are stored gzip compressed, with no delta compression.

    >>> st = ScratchCompressedTextStore()

    >>> st.add('aa', StringIO('hello'))
    >>> 'aa' in st
    True
    >>> 'foo' in st
    False

    You are not allowed to add an id that is already present.

    Entries can be retrieved as files, which may then be read.

    >>> st.add('123123', StringIO('goodbye'))
    >>> st['123123'].read()
    'goodbye'

    TODO: Atomic add by writing to a temporary file and renaming.

    In bzr 0.0.5 and earlier, files within the store were marked
    readonly on disk.  This is no longer done but existing stores need
    to be accomodated.
    """

    def __init__(self, basedir):
        super(CompressedTextStore, self).__init__(basedir)

    def _check_fileid(self, fileid):
        if '\\' in fileid or '/' in fileid:
            raise ValueError("invalid store id %r" % fileid)

    def _relpath(self, fileid):
        self._check_fileid(fileid)
        return fileid + '.gz'

    def add(self, fileid, f):
        """Add contents of a file into the store.

        f -- An open file, or file-like object."""
        # TODO: implement an add_multi which can do some of it's
        #       own piplelining, and possible take advantage of
        #       transport.put_multi(). The problem is that
        #       entries potentially need to be compressed as they
        #       are received, which implies translation, which
        #       means it isn't as straightforward as we would like.
        from cStringIO import StringIO
        from bzrlib.osutils import pumpfile
        
        mutter("add store entry %r" % (fileid))
        if isinstance(f, basestring):
            f = StringIO(f)
            
        fn = self._relpath(fileid)
        if self._transport.has(fn):
            raise BzrError("store %r already contains id %r" % (self._transport.base, fileid))


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

    def _do_copy(self, other, to_copy, pb):
        if isinstance(other, CompressedTextStore):
            return self._copy_multi_text(other, to_copy, pb)
        return super(CompressedTextStore, self)._do_copy(other, to_copy, pb)

    def _copy_multi_text(self, other, to_copy, pb):
        # Because of _transport, we can no longer assume
        # that they are on the same filesystem, we can, however
        # assume that we only need to copy the exact bytes,
        # we don't need to process the files.

        paths = [self._relpath(fileid) for fileid in to_copy]
        count = other._transport.copy_to(paths, self._transport, pb=pb)
        assert count == len(to_copy)
        pb.clear()
        return count

    def __contains__(self, fileid):
        """"""
        fn = self._relpath(fileid)
        return self._transport.has(fn)

    # TODO: Guard against the same thing being stored twice, compressed and uncompresse

    def __iter__(self):
        # TODO: case-insensitive?
        for f in self._transport.list_dir('.'):
            if f[-3:] == '.gz':
                yield f[:-3]
            else:
                yield f

    def __len__(self):
        return len([f for f in self._transport.list_dir('.')])

    def __getitem__(self, fileid):
        """Returns a file reading from a particular entry."""
        fn = self._relpath(fileid)
        f = self._transport.get(fn)

        # gzip.GzipFile.read() requires a tell() function
        # but some transports return objects that cannot seek
        # so buffer them in a StringIO instead
        if hasattr(f, 'tell'):
            return gzip.GzipFile(mode='rb', fileobj=f)
        else:
            from cStringIO import StringIO
            sio = StringIO(f.read())
            return gzip.GzipFile(mode='rb', fileobj=sio)
            

    def total_size(self):
        """Return (count, bytes)

        This is the (compressed) size stored on disk, not the size of
        the content."""
        total = 0
        count = 0
        relpaths = [self._relpath(fid) for fid in self]
        for st in self._transport.stat_multi(relpaths):
            count += 1
            total += st[ST_SIZE]
                
        return count, total

class ScratchCompressedTextStore(CompressedTextStore):
    """Self-destructing test subclass of CompressedTextStore.

    The Store only exists for the lifetime of the Python object.
    Obviously you should not put anything precious in it.
    """
    def __init__(self):
        from transport import transport
        super(ScratchCompressedTextStore, self).__init__(transport(tempfile.mkdtemp()))

    def __del__(self):
        self._transport.delete_multi(self._transport.list_dir('.'))
        os.rmdir(self._transport.base)
        mutter("%r destroyed" % self)

