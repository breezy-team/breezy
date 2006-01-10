# Copyright (C) 2005 Canonical Ltd

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
"""Implementation of Transport that uses memory for its storage."""

import os
import errno
from cStringIO import StringIO

from bzrlib.trace import mutter
from bzrlib.errors import TransportError, NoSuchFile, FileExists
from bzrlib.transport import Transport

class MemoryStat(object):

    def __init__(self, size):
        self.st_size = size


class MemoryTransport(Transport):
    """This is the transport agent for local filesystem access."""

    def __init__(self):
        """Set the 'base' path where files will be stored."""
        super(MemoryTransport, self).__init__('in-memory:')
        self._dirs = set()
        self._files = {}

    def clone(self, offset=None):
        """See Transport.clone()."""
        return self

    def abspath(self, relpath):
        """See Transport.abspath()."""
        return self.base + relpath

    def append(self, relpath, f):
        """See Transport.append()."""
        self._check_parent(relpath)
        self._files[relpath] = self._files.get(relpath, "") + f.read()

    def _check_parent(self, relpath):
        dir = os.path.dirname(relpath)
        if dir != '':
            if not dir in self._dirs:
                raise NoSuchFile(relpath)

    def has(self, relpath):
        """See Transport.has()."""
        return relpath in self._files

    def get(self, relpath):
        """See Transport.get()."""
        if not relpath in self._files:
            raise NoSuchFile(relpath)
        return StringIO(self._files[relpath])

    def put(self, relpath, f, mode=None):
        """See Transport.put()."""
        self._check_parent(relpath)
        self._files[relpath] = f.read()

    def mkdir(self, relpath, mode=None):
        """See Transport.mkdir()."""
        self._check_parent(relpath)
        if relpath in self._dirs:
            raise FileExists(relpath)
        self._dirs.add(relpath)

    def listable(self):
        """See Transport.listable."""
        return True

    def iter_files_recursive(self):
        return iter(self._files)
    
#    def list_dir(self, relpath):
#    TODO if needed
    
    def stat(self, relpath):
        """See Transport.stat()."""
        return MemoryStat(len(self._files[relpath]))

#    def lock_read(self, relpath):
#   TODO if needed
#
#    def lock_write(self, relpath):
#   TODO if needed
