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

import os, tempfile, types, osutils, gzip, errno
from stat import ST_SIZE
from StringIO import StringIO
from bzrlib.trace import mutter
import bzrlib.ui

######################################################################
# stores

class StoreError(Exception):
    pass


class ImmutableStore(object):
    """Store that holds files indexed by unique names.

    Files can be added, but not modified once they are in.  Typically
    the hash is used as the name, or something else known to be unique,
    such as a UUID.

    >>> st = ImmutableScratchStore()

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
        self._basedir = basedir

    def _path(self, id):
        if '\\' in id or '/' in id:
            raise ValueError("invalid store id %r" % id)
        return os.path.join(self._basedir, id)

    def __repr__(self):
        return "%s(%r)" % (self.__class__.__name__, self._basedir)

    def add(self, f, fileid, compressed=True):
        """Add contents of a file into the store.

        f -- An open file, or file-like object."""
        # FIXME: Only works on files that will fit in memory
        
        from bzrlib.atomicfile import AtomicFile
        
        mutter("add store entry %r" % (fileid))
        if isinstance(f, types.StringTypes):
            content = f
        else:
            content = f.read()
            
        p = self._path(fileid)
        if os.access(p, os.F_OK) or os.access(p + '.gz', os.F_OK):
            from bzrlib.errors import bailout
            raise BzrError("store %r already contains id %r" % (self._basedir, fileid))

        fn = p
        if compressed:
            fn = fn + '.gz'
            
        af = AtomicFile(fn, 'wb')
        try:
            if compressed:
                gf = gzip.GzipFile(mode='wb', fileobj=af)
                gf.write(content)
                gf.close()
            else:
                af.write(content)
            af.commit()
        finally:
            af.close()


    def copy_multi(self, other, ids, permit_failure=False):
        """Copy texts for ids from other into self.

        If an id is present in self, it is skipped.  A count of copied
        ids is returned, which may be less than len(ids).
        """
        pb = bzrlib.ui.ui_factory.progress_bar()
        
        pb.update('preparing to copy')
        to_copy = [id for id in ids if id not in self]
        if isinstance(other, ImmutableStore):
            return self.copy_multi_immutable(other, to_copy, pb)
        count = 0
        for id in to_copy:
            count += 1
            pb.update('copy', count, len(to_copy))
            if not permit_failure:
                self.add(other[id], id)
            else:
                try:
                    entry = other[id]
                except IndexError:
                    failures.add(id)
                    continue
                self.add(entry, id)
                
        assert count == len(to_copy)
        pb.clear()
        return count


    def copy_multi_immutable(self, other, to_copy, pb, permit_failure=False):
        from shutil import copyfile
        count = 0
        failed = set()
        for id in to_copy:
            p = self._path(id)
            other_p = other._path(id)
            try:
                copyfile(other_p, p)
            except IOError, e:
                if e.errno == errno.ENOENT:
                    if not permit_failure:
                        copyfile(other_p+".gz", p+".gz")
                    else:
                        try:
                            copyfile(other_p+".gz", p+".gz")
                        except IOError, e:
                            if e.errno == errno.ENOENT:
                                failed.add(id)
                            else:
                                raise
                else:
                    raise
            
            count += 1
            pb.update('copy', count, len(to_copy))
        assert count == len(to_copy)
        pb.clear()
        return count, failed
    

    def __contains__(self, fileid):
        """"""
        p = self._path(fileid)
        return (os.access(p, os.R_OK)
                or os.access(p + '.gz', os.R_OK))

    # TODO: Guard against the same thing being stored twice, compressed and uncompresse

    def __iter__(self):
        for f in os.listdir(self._basedir):
            if f[-3:] == '.gz':
                # TODO: case-insensitive?
                yield f[:-3]
            else:
                yield f

    def __len__(self):
        return len(os.listdir(self._basedir))


    def __getitem__(self, fileid):
        """Returns a file reading from a particular entry."""
        p = self._path(fileid)
        try:
            return gzip.GzipFile(p + '.gz', 'rb')
        except IOError, e:
            if e.errno != errno.ENOENT:
                raise

        try:
            return file(p, 'rb')
        except IOError, e:
            if e.errno != errno.ENOENT:
                raise

        raise IndexError(fileid)


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




class ImmutableScratchStore(ImmutableStore):
    """Self-destructing test subclass of ImmutableStore.

    The Store only exists for the lifetime of the Python object.
 Obviously you should not put anything precious in it.
    """
    def __init__(self):
        ImmutableStore.__init__(self, tempfile.mkdtemp())

    def __del__(self):
        for f in os.listdir(self._basedir):
            fpath = os.path.join(self._basedir, f)
            # needed on windows, and maybe some other filesystems
            os.chmod(fpath, 0600)
            os.remove(fpath)
        os.rmdir(self._basedir)
        mutter("%r destroyed" % self)
