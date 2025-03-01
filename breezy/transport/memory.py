# Copyright (C) 2005-2011, 2016 Canonical Ltd
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Implementation of Transport that uses memory for its storage.

The contents of the transport will be lost when the object is discarded,
so this is primarily useful for testing.
"""

import errno
import itertools
import os
from io import BytesIO
from stat import S_IFDIR, S_IFLNK, S_IFREG, S_ISDIR

from .. import transport, urlutils
from ..errors import InProcessTransport, LockError
from ..transport import (
    AppendBasedFileStream,
    FileExists,
    LateReadError,
    NoSuchFile,
    _file_streams,
)


class MemoryStat:
    def __init__(self, size, kind, perms=None):
        self.st_size = size
        if not S_ISDIR(kind):
            if perms is None:
                perms = 0o644
            self.st_mode = kind | perms
        else:
            if perms is None:
                perms = 0o755
            self.st_mode = kind | perms


class MemoryTransport(transport.Transport):
    """This is an in memory file system for transient data storage."""

    def __init__(self, url=""):
        """Set the 'base' path where files will be stored."""
        if url == "":
            url = "memory:///"
        if url[-1] != "/":
            url = url + "/"
        super().__init__(url)
        split = url.find(":") + 3
        self._scheme = url[:split]
        self._cwd = url[split:]
        # dictionaries from absolute path to file mode
        self._dirs = {"/": None}
        self._symlinks = {}
        self._files = {}
        self._locks = {}

    def clone(self, offset=None):
        """See Transport.clone()."""
        path = urlutils.URL._combine_paths(self._cwd, offset)
        if len(path) == 0 or path[-1] != "/":
            path += "/"
        url = self._scheme + path
        result = self.__class__(url)
        result._dirs = self._dirs
        result._symlinks = self._symlinks
        result._files = self._files
        result._locks = self._locks
        return result

    def abspath(self, relpath):
        """See Transport.abspath()."""
        # while a little slow, this is sufficiently fast to not matter in our
        # current environment - XXX RBC 20060404 move the clone '..' handling
        # into here and call abspath from clone
        temp_t = self.clone(relpath)
        if temp_t.base.count("/") == 3:
            return temp_t.base
        else:
            return temp_t.base[:-1]

    def append_file(self, relpath, f, mode=None):
        """See Transport.append_file()."""
        _abspath = self._resolve_symlinks(relpath)
        self._check_parent(_abspath)
        orig_content, orig_mode = self._files.get(_abspath, (b"", None))
        if mode is None:
            mode = orig_mode
        self._files[_abspath] = (orig_content + f.read(), mode)
        return len(orig_content)

    def _check_parent(self, _abspath):
        dir = os.path.dirname(_abspath)
        if dir != "/":
            if dir not in self._dirs:
                raise NoSuchFile(_abspath)

    def has(self, relpath):
        """See Transport.has()."""
        _abspath = self._abspath(relpath)
        for container in (self._files, self._dirs, self._symlinks):
            if _abspath in container.keys():
                return True
        return False

    def delete(self, relpath):
        """See Transport.delete()."""
        _abspath = self._abspath(relpath)
        if _abspath in self._files:
            del self._files[_abspath]
        elif _abspath in self._symlinks:
            del self._symlinks[_abspath]
        else:
            raise NoSuchFile(relpath)

    def external_url(self):
        """See breezy.transport.Transport.external_url."""
        # MemoryTransport's are only accessible in-process
        # so we raise here
        raise InProcessTransport(self)

    def get(self, relpath):
        """See Transport.get()."""
        _abspath = self._resolve_symlinks(relpath)
        if _abspath not in self._files:
            if _abspath in self._dirs:
                return LateReadError(relpath)
            else:
                raise NoSuchFile(relpath)
        return BytesIO(self._files[_abspath][0])

    def put_file(self, relpath, f, mode=None):
        """See Transport.put_file()."""
        _abspath = self._resolve_symlinks(relpath)
        self._check_parent(_abspath)
        raw_bytes = f.read()
        self._files[_abspath] = (raw_bytes, mode)
        return len(raw_bytes)

    def symlink(self, source, link_name):
        """Create a symlink pointing to source named link_name."""
        _abspath = self._abspath(link_name)
        self._check_parent(_abspath)
        self._symlinks[_abspath] = source.split("/")

    def mkdir(self, relpath, mode=None):
        """See Transport.mkdir()."""
        _abspath = self._resolve_symlinks(relpath)
        self._check_parent(_abspath)
        if _abspath in self._dirs:
            raise FileExists(relpath)
        self._dirs[_abspath] = mode

    def open_write_stream(self, relpath, mode=None):
        """See Transport.open_write_stream."""
        self.put_bytes(relpath, b"", mode)
        result = AppendBasedFileStream(self, relpath)
        _file_streams[self.abspath(relpath)] = result
        return result

    def listable(self):
        """See Transport.listable."""
        return True

    def iter_files_recursive(self):
        for file in itertools.chain(self._files, self._symlinks):
            if file.startswith(self._cwd):
                yield urlutils.escape(file[len(self._cwd) :])

    def list_dir(self, relpath):
        """See Transport.list_dir()."""
        _abspath = self._resolve_symlinks(relpath)
        if _abspath != "/" and _abspath not in self._dirs:
            raise NoSuchFile(relpath)
        result = []

        if not _abspath.endswith("/"):
            _abspath += "/"

        for path_group in self._files, self._dirs, self._symlinks:
            for path in path_group:
                if path.startswith(_abspath):
                    trailing = path[len(_abspath) :]
                    if trailing and "/" not in trailing:
                        result.append(urlutils.escape(trailing))
        return result

    def rename(self, rel_from, rel_to):
        """Rename a file or directory; fail if the destination exists"""
        abs_from = self._resolve_symlinks(rel_from)
        abs_to = self._resolve_symlinks(rel_to)

        def replace(x):
            if x == abs_from:
                x = abs_to
            elif x.startswith(abs_from + "/"):
                x = abs_to + x[len(abs_from) :]
            return x

        def do_renames(container):
            renames = []
            for path in container:
                new_path = replace(path)
                if new_path != path:
                    if new_path in container:
                        raise FileExists(new_path)
                    renames.append((path, new_path))
            for path, new_path in renames:
                container[new_path] = container[path]
                del container[path]

        # If we modify the existing dicts, we're not atomic anymore and may
        # fail differently depending on dict order. So work on copy, fail on
        # error on only replace dicts if all goes well.
        renamed_files = self._files.copy()
        renamed_symlinks = self._symlinks.copy()
        renamed_dirs = self._dirs.copy()
        do_renames(renamed_files)
        do_renames(renamed_symlinks)
        do_renames(renamed_dirs)
        # We may have been cloned so modify in place
        self._files.clear()
        self._files.update(renamed_files)
        self._symlinks.clear()
        self._symlinks.update(renamed_symlinks)
        self._dirs.clear()
        self._dirs.update(renamed_dirs)

    def rmdir(self, relpath):
        """See Transport.rmdir."""
        _abspath = self._resolve_symlinks(relpath)
        if _abspath in self._files:
            self._translate_error(OSError(errno.ENOTDIR, relpath), relpath)
        for path in itertools.chain(self._files, self._symlinks):
            if path.startswith(_abspath + "/"):
                self._translate_error(OSError(errno.ENOTEMPTY, relpath), relpath)
        for path in self._dirs:
            if path.startswith(_abspath + "/") and path != _abspath:
                self._translate_error(OSError(errno.ENOTEMPTY, relpath), relpath)
        if _abspath not in self._dirs:
            raise NoSuchFile(relpath)
        del self._dirs[_abspath]

    def stat(self, relpath):
        """See Transport.stat()."""
        _abspath = self._abspath(relpath)
        if _abspath in self._files.keys():
            return MemoryStat(
                len(self._files[_abspath][0]), S_IFREG, self._files[_abspath][1]
            )
        elif _abspath in self._dirs.keys():
            return MemoryStat(0, S_IFDIR, self._dirs[_abspath])
        elif _abspath in self._symlinks.keys():
            return MemoryStat(0, S_IFLNK)
        else:
            raise NoSuchFile(_abspath)

    def lock_read(self, relpath):
        """See Transport.lock_read()."""
        return _MemoryLock(self._abspath(relpath), self)

    def lock_write(self, relpath):
        """See Transport.lock_write()."""
        return _MemoryLock(self._abspath(relpath), self)

    def _resolve_symlinks(self, relpath):
        path = self._abspath(relpath)
        while path in self._symlinks.keys():
            path = self._symlinks[path]
        return path

    def _abspath(self, relpath):
        """Generate an internal absolute path."""
        relpath = urlutils.unescape(relpath)
        if relpath[:1] == "/":
            return relpath
        cwd_parts = self._cwd.split("/")
        rel_parts = relpath.split("/")
        r = []
        for i in cwd_parts + rel_parts:
            if i == "..":
                if not r:
                    raise ValueError(
                        "illegal relpath %r under %r" % (relpath, self._cwd)
                    )
                r = r[:-1]
            elif i == "." or i == "":
                pass
            else:
                r.append(i)
                r = self._symlinks.get("/".join(r), r)
        return "/" + "/".join(r)

    def readlink(self, link_name):
        _abspath = self._abspath(link_name)
        try:
            return "/".join(self._symlinks[_abspath])
        except KeyError:
            raise NoSuchFile(link_name)


class _MemoryLock:
    """This makes a lock."""

    def __init__(self, path, transport):
        self.path = path
        self.transport = transport
        if self.path in self.transport._locks:
            raise LockError("File {!r} already locked".format(self.path))
        self.transport._locks[self.path] = self

    def unlock(self):
        del self.transport._locks[self.path]
        self.transport = None


class MemoryServer(transport.Server):
    """Server for the MemoryTransport for testing with."""

    def start_server(self):
        self._dirs = {"/": None}
        self._files = {}
        self._symlinks = {}
        self._locks = {}
        self._scheme = "memory+%s:///" % id(self)

        def memory_factory(url):
            from . import memory

            result = memory.MemoryTransport(url)
            result._dirs = self._dirs
            result._files = self._files
            result._symlinks = self._symlinks
            result._locks = self._locks
            return result

        self._memory_factory = memory_factory
        transport.register_transport(self._scheme, self._memory_factory)

    def stop_server(self):
        # unregister this server
        transport.unregister_transport(self._scheme, self._memory_factory)

    def get_url(self):
        """See breezy.transport.Server.get_url."""
        return self._scheme

    def get_bogus_url(self):
        raise NotImplementedError


def get_test_permutations():
    """Return the permutations to be used in testing."""
    return [
        (MemoryTransport, MemoryServer),
    ]
