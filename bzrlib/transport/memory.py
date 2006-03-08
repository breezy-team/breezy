# Copyright (C) 2005, 2006 Canonical Ltd

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

"""Implementation of Transport that uses memory for its storage.

The contents of the transport will be lost when the object is discarded,
so this is primarily useful for testing.
"""

from copy import copy
import os
import errno
import re
from stat import *
from cStringIO import StringIO

from bzrlib.trace import mutter
from bzrlib.errors import TransportError, NoSuchFile, FileExists, LockError
from bzrlib.transport import Transport, register_transport, Server

class MemoryStat(object):

    def __init__(self, size, is_dir, perms):
        self.st_size = size
        if perms is None:
            perms = 0644
        if not is_dir:
            self.st_mode = S_IFREG | perms
        else:
            self.st_mode = S_IFDIR | perms


class MemoryTransport(Transport):
    """This is an in memory file system for transient data storage."""

    def __init__(self, url=""):
        """Set the 'base' path where files will be stored."""
        if url == "":
            url = "memory:/"
        if url[-1] != '/':
            url = url + '/'
        super(MemoryTransport, self).__init__(url)
        self._cwd = url[url.find(':') + 1:]
        # dictionaries from absolute path to file mode
        self._dirs = {}
        self._files = {}
        self._locks = {}

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
        result._locks = self._locks
        return result

    def abspath(self, relpath):
        """See Transport.abspath()."""
        return self.base[:-1] + self._abspath(relpath)[len(self._cwd) - 1:]

    def append(self, relpath, f):
        """See Transport.append()."""
        _abspath = self._abspath(relpath)
        self._check_parent(_abspath)
        orig_content, orig_mode = self._files.get(_abspath, ("", None))
        self._files[_abspath] = (orig_content + f.read(), orig_mode)
        return len(orig_content)

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
        return StringIO(self._files[_abspath][0])

    def put(self, relpath, f, mode=None):
        """See Transport.put()."""
        _abspath = self._abspath(relpath)
        self._check_parent(_abspath)
        self._files[_abspath] = (f.read(), mode)

    def mkdir(self, relpath, mode=None):
        """See Transport.mkdir()."""
        _abspath = self._abspath(relpath)
        self._check_parent(_abspath)
        if _abspath in self._dirs:
            raise FileExists(relpath)
        self._dirs[_abspath]=mode

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
                len(path) > len(_abspath) and
                path[len(_abspath)] == '/'):
                result.append(path[len(_abspath) + 1:])
        return result

    def rename(self, rel_from, rel_to):
        """Rename a file or directory; fail if the destination exists"""
        abs_from = self._abspath(rel_from)
        abs_to = self._abspath(rel_to)
        def replace(x):
            if x == abs_from:
                x = abs_to
            elif x.startswith(abs_from + '/'):
                x = abs_to + x[len(abs_from):]
            return x
        def do_renames(container):
            for path in container:
                new_path = replace(path)
                if new_path != path:
                    if new_path in container:
                        raise FileExists(new_path)
                    container[new_path] = container[path]
                    del container[path]
        do_renames(self._files)
        do_renames(self._dirs)
    
    def rmdir(self, relpath):
        """See Transport.rmdir."""
        _abspath = self._abspath(relpath)
        if _abspath in self._files:
            self._translate_error(IOError(errno.ENOTDIR, relpath), relpath)
        for path in self._files:
            if path.startswith(_abspath):
                self._translate_error(IOError(errno.ENOTEMPTY, relpath),
                                      relpath)
        for path in self._dirs:
            if path.startswith(_abspath) and path != _abspath:
                self._translate_error(IOError(errno.ENOTEMPTY, relpath), relpath)
        if not _abspath in self._dirs:
            raise NoSuchFile(relpath)
        del self._dirs[_abspath]

    def stat(self, relpath):
        """See Transport.stat()."""
        _abspath = self._abspath(relpath)
        if _abspath in self._files:
            return MemoryStat(len(self._files[_abspath][0]), False, 
                              self._files[_abspath][1])
        elif _abspath == '':
            return MemoryStat(0, True, None)
        elif _abspath in self._dirs:
            return MemoryStat(0, True, self._dirs[_abspath])
        else:
            raise NoSuchFile(_abspath)

    def lock_read(self, relpath):
        """See Transport.lock_read()."""
        return _MemoryLock(self._abspath(relpath), self)

    def lock_write(self, relpath):
        """See Transport.lock_write()."""
        return _MemoryLock(self._abspath(relpath), self)

    def _abspath(self, relpath):
        """Generate an internal absolute path."""
        if relpath.find('..') != -1:
            raise AssertionError('relpath contains ..')
        if relpath == '.':
            return self._cwd[:-1]
        if relpath.endswith('/'):
            relpath = relpath[:-1]
        if relpath.startswith('./'):
            relpath = relpath[2:]
        return self._cwd + relpath


class _MemoryLock(object):
    """This makes a lock."""

    def __init__(self, path, transport):
        assert isinstance(transport, MemoryTransport)
        self.path = path
        self.transport = transport
        if self.path in self.transport._locks:
            raise LockError('File %r already locked' % (self.path,))
        self.transport._locks[self.path] = self

    def __del__(self):
        # Should this warn, or actually try to cleanup?
        if self.transport:
            warn("MemoryLock %r not explicitly unlocked" % (self.path,))
            self.unlock()

    def unlock(self):
        del self.transport._locks[self.path]
        self.transport = None


class MemoryServer(Server):
    """Server for the MemoryTransport for testing with."""

    def setUp(self):
        """See bzrlib.transport.Server.setUp."""
        self._dirs = {}
        self._files = {}
        self._locks = {}
        self._scheme = "memory+%s:" % id(self)
        def memory_factory(url):
            result = MemoryTransport(url)
            result._dirs = self._dirs
            result._files = self._files
            result._locks = self._locks
            return result
        register_transport(self._scheme, memory_factory)

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
