#! /usr/bin/env python
# -*- coding: UTF-8 -*-

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

"""Stores are the main data-storage mechanism for Bazaar-NG.

A store is a simple write-once container indexed by a universally
unique ID, which is typically the SHA-1 of the content."""

__copyright__ = "Copyright (C) 2005 Canonical Ltd."
__author__ = "Martin Pool <mbp@canonical.com>"

import os, tempfile, types, osutils
from stat import ST_SIZE
from StringIO import StringIO
from trace import mutter


######################################################################
# stores

class StoreError(Exception):
    pass


class ImmutableStore:
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

    :todo: Atomic add by writing to a temporary file and renaming.

    :todo: Perhaps automatically transform to/from XML in a method?
           Would just need to tell the constructor what class to
           use...

    :todo: Even within a simple disk store like this, we could
           gzip the files.  But since many are less than one disk
           block, that might not help a lot.

    """

    def __init__(self, basedir):
        """ImmutableStore constructor."""
        self._basedir = basedir

    def _path(self, id):
        return os.path.join(self._basedir, id)

    def __repr__(self):
        return "%s(%r)" % (self.__class__.__name__, self._basedir)

    def add(self, f, fileid):
        """Add contents of a file into the store.

        :param f: An open file, or file-like object."""
        # FIXME: Only works on smallish files
        # TODO: Can be optimized by copying at the same time as
        # computing the sum.
        mutter("add store entry %r" % (fileid))
        if isinstance(f, types.StringTypes):
            content = f
        else:
            content = f.read()
        if fileid not in self:
            filename = self._path(fileid)
            f = file(filename, 'wb')
            f.write(content)
            ## f.flush()
            ## os.fsync(f.fileno())
            f.close()
            osutils.make_readonly(filename)


    def __contains__(self, fileid):
        """"""
        return os.access(self._path(fileid), os.R_OK)


    def __iter__(self):
        return iter(os.listdir(self._basedir))

    def __len__(self):
        return len(os.listdir(self._basedir))

    def __getitem__(self, fileid):
        """Returns a file reading from a particular entry."""
        return file(self._path(fileid), 'rb')

    def total_size(self):
        """Return (count, bytes)"""
        total = 0
        count = 0
        for fid in self:
            count += 1
            total += os.stat(self._path(fid))[ST_SIZE]
        return count, total

    def delete_all(self):
        for fileid in self:
            self.delete(fileid)

    def delete(self, fileid):
        """Remove nominated store entry.

        Most stores will be add-only."""
        filename = self._path(fileid)
        ## osutils.make_writable(filename)
        os.remove(filename)

    def destroy(self):
        """Remove store; only allowed if it is empty."""
        os.rmdir(self._basedir)
        mutter("%r destroyed" % self)



class ImmutableScratchStore(ImmutableStore):
    """Self-destructing test subclass of ImmutableStore.

    The Store only exists for the lifetime of the Python object.
    Obviously you should not put anything precious in it.
    """
    def __init__(self):
        ImmutableStore.__init__(self, tempfile.mkdtemp())

    def __del__(self):
        self.delete_all()
        self.destroy()
