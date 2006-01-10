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

from copy import copy
import os
import errno
from stat import *
from cStringIO import StringIO

from bzrlib.trace import mutter
from bzrlib.errors import TransportError, NoSuchFile, FileExists
from bzrlib.transport import Transport, register_transport, Server

class MemoryStat(object):

    def __init__(self, size, is_dir):
        self.st_size = size
        if not is_dir:
            self.st_mode = S_IFREG
        else:
            self.st_mode = S_IFDIR


class MemoryTransport(Transport):
    """This is the transport agent for local filesystem access."""

    def __init__(self, url=""):
        """Set the 'base' path where files will be stored."""
        if url == "":
            url = "memory:/"
        if url[-1] != '/':
            url = url + '/'
        super(MemoryTransport, self).__init__(url)
        self._cwd = url[url.find(':') + 1:]
        self._dirs = set()
        self._files = {}

    def clone(self, offset=None):
        """See Transport.clone()."""
        if offset is None:
            return copy(self)
        segments = offset.split('/')
        cwdsegments = self._cwd.split('/')[:-1]
        while len(segments):
            segment = segments.pop(0)
            if segment == '.':
                continue
            if segment == '..':
                if len(cwdsegments) > 1:
                    cwdsegments.pop()
                continue
            cwdsegments.append(segment)
        url = self.base[:self.base.find(':') + 1] + '/'.join(cwdsegments) + '/'
        result = MemoryTransport(url)
        result._dirs = self._dirs
        result._files = self._files
        return result

    def abspath(self, relpath):
        """See Transport.abspath()."""
        return self.base[:-1] + self._abspath(relpath)

    def append(self, relpath, f):
        """See Transport.append()."""
        _abspath = self._abspath(relpath)
        self._check_parent(_abspath)
        self._files[_abspath] = self._files.get(_abspath, "") + f.read()

    def _check_parent(self, _abspath):
        dir = os.path.dirname(_abspath)
        if dir != '/':
            if not dir in self._dirs:
                raise NoSuchFile(_abspath)

    def has(self, relpath):
        """See Transport.has()."""
        _abspath = self._abspath(relpath)
        return _abspath in self._files or _abspath in self._dirs

    def delete(self, relpath):
        """See Transport.delete()."""
        _abspath = self._abspath(relpath)
        if not _abspath in self._files:
            raise NoSuchFile(relpath)
        del self._files[_abspath]

    def get(self, relpath):
        """See Transport.get()."""
        _abspath = self._abspath(relpath)
        if not _abspath in self._files:
            raise NoSuchFile(relpath)
        return StringIO(self._files[_abspath])

    def put(self, relpath, f, mode=None):
        """See Transport.put()."""
        _abspath = self._abspath(relpath)
        self._check_parent(_abspath)
        self._files[_abspath] = f.read()

    def mkdir(self, relpath, mode=None):
        """See Transport.mkdir()."""
        _abspath = self._abspath(relpath)
        self._check_parent(_abspath)
        if _abspath in self._dirs:
            raise FileExists(relpath)
        self._dirs.add(_abspath)

    def listable(self):
        """See Transport.listable."""
        return True

    def iter_files_recursive(self):
        for file in self._files:
            if file.startswith(self._cwd):
                yield file[len(self._cwd):]
    
    def list_dir(self, relpath):
        """See Transport.list_dir()."""
        _abspath = self._abspath(relpath)
        if _abspath != '/' and _abspath not in self._dirs:
            raise NoSuchFile(relpath)
        result = []
        for path in self._files:
            if (path.startswith(_abspath) and 
                path[len(_abspath) + 1:].find('/') == -1 and
                len(path) > len(_abspath)):
                result.append(path[len(_abspath) + 1:])
        for path in self._dirs:
            if (path.startswith(_abspath) and 
                path[len(_abspath) + 1:].find('/') == -1 and
                len(path) > len(_abspath)):
                result.append(path[len(_abspath) + 1:])
        return result
    
    def stat(self, relpath):
        """See Transport.stat()."""
        _abspath = self._abspath(relpath)
        if _abspath in self._files:
            return MemoryStat(len(self._files[_abspath]), False)
        elif _abspath in self._dirs or _abspath == '':
            return MemoryStat(0, True)
        else:
            raise NoSuchFile(relpath)

#    def lock_read(self, relpath):
#   TODO if needed
#
#    def lock_write(self, relpath):
#   TODO if needed

    def _abspath(self, relpath):
        """Generate an internal absolute path."""
        if relpath.find('..') != -1:
            raise AssertionError('relpath contains ..')
        if relpath == '.':
            return self._cwd[:-1]
        if relpath.endswith('/'):
            relpath = relpath[:-1]
        return self._cwd + relpath


class MemoryServer(Server):
    """Server for the MemoryTransport for testing with."""

    def setUp(self):
        """See bzrlib.transport.Server.setUp."""
        self._scheme = "memory+%s:" % id(self)
        register_transport(self._scheme, MemoryTransport)

    def tearDown(self):
        """See bzrlib.transport.Server.tearDown."""
        # unregister this server

    def get_url(self):
        """See bzrlib.transport.Server.get_url."""
        return self._scheme


def get_test_permutations():
    """Return the permutations to be used in testing."""
    return [(MemoryTransport, MemoryServer),
            ]
