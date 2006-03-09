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

"""Transport for the local filesystem.

This is a fairly thin wrapper on regular file IO."""

import os
import shutil
from stat import ST_MODE, S_ISDIR, ST_SIZE
import tempfile
import urllib

from bzrlib.trace import mutter
from bzrlib.transport import Transport, Server
from bzrlib.osutils import abspath, realpath, normpath, pathjoin, rename


class LocalTransport(Transport):
    """This is the transport agent for local filesystem access."""

    def __init__(self, base):
        """Set the base path where files will be stored."""
        if base.startswith('file://'):
            base = base[7:]
        # realpath is incompatible with symlinks. When we traverse
        # up we might be able to normpath stuff. RBC 20051003
        base = normpath(abspath(base))
        if base[-1] != '/':
            base = base + '/'
        super(LocalTransport, self).__init__(base)

    def should_cache(self):
        return False

    def clone(self, offset=None):
        """Return a new LocalTransport with root at self.base + offset
        Because the local filesystem does not require a connection, 
        we can just return a new object.
        """
        if offset is None:
            return LocalTransport(self.base)
        else:
            return LocalTransport(self.abspath(offset))

    def abspath(self, relpath):
        """Return the full url to the given relative URL.
        This can be supplied with a string or a list
        """
        assert isinstance(relpath, basestring), (type(relpath), relpath)
        return pathjoin(self.base, urllib.unquote(relpath))

    def relpath(self, abspath):
        """Return the local path portion from a given absolute path.
        """
        from bzrlib.osutils import relpath
        if abspath is None:
            abspath = u'.'
        if abspath.endswith('/'):
            abspath = abspath[:-1]
        return relpath(self.base[:-1], abspath)

    def has(self, relpath):
        return os.access(self.abspath(relpath), os.F_OK)

    def get(self, relpath):
        """Get the file at the given relative path.

        :param relpath: The relative path to the file
        """
        try:
            path = self.abspath(relpath)
            return open(path, 'rb')
        except (IOError, OSError),e:
            self._translate_error(e, path)

    def put(self, relpath, f, mode=None):
        """Copy the file-like or string object into the location.

        :param relpath: Location to put the contents, relative to base.
        :param f:       File-like or string object.
        """
        from bzrlib.atomicfile import AtomicFile

        path = relpath
        try:
            path = self.abspath(relpath)
            fp = AtomicFile(path, 'wb', new_mode=mode)
        except (IOError, OSError),e:
            self._translate_error(e, path)
        try:
            self._pump(f, fp)
            fp.commit()
        finally:
            fp.close()

    def iter_files_recursive(self):
        """Iter the relative paths of files in the transports sub-tree."""
        queue = list(self.list_dir(u'.'))
        while queue:
            relpath = urllib.quote(queue.pop(0))
            st = self.stat(relpath)
            if S_ISDIR(st[ST_MODE]):
                for i, basename in enumerate(self.list_dir(relpath)):
                    queue.insert(i, relpath+'/'+basename)
            else:
                yield relpath

    def mkdir(self, relpath, mode=None):
        """Create a directory at the given path."""
        path = relpath
        try:
            path = self.abspath(relpath)
            os.mkdir(path)
            if mode is not None:
                os.chmod(path, mode)
        except (IOError, OSError),e:
            self._translate_error(e, path)

    def append(self, relpath, f):
        """Append the text in the file-like object into the final
        location.
        """
        try:
            fp = open(self.abspath(relpath), 'ab')
        except (IOError, OSError),e:
            self._translate_error(e, relpath)
        result = fp.tell()
        self._pump(f, fp)
        return result

    def copy(self, rel_from, rel_to):
        """Copy the item at rel_from to the location at rel_to"""
        import shutil
        path_from = self.abspath(rel_from)
        path_to = self.abspath(rel_to)
        try:
            shutil.copy(path_from, path_to)
        except (IOError, OSError),e:
            # TODO: What about path_to?
            self._translate_error(e, path_from)

    def rename(self, rel_from, rel_to):
        path_from = self.abspath(rel_from)
        try:
            # *don't* call bzrlib.osutils.rename, because we want to 
            # detect errors on rename
            os.rename(path_from, self.abspath(rel_to))
        except (IOError, OSError),e:
            # TODO: What about path_to?
            self._translate_error(e, path_from)

    def move(self, rel_from, rel_to):
        """Move the item at rel_from to the location at rel_to"""
        path_from = self.abspath(rel_from)
        path_to = self.abspath(rel_to)

        try:
            # this version will delete the destination if necessary
            rename(path_from, path_to)
        except (IOError, OSError),e:
            # TODO: What about path_to?
            self._translate_error(e, path_from)

    def delete(self, relpath):
        """Delete the item at relpath"""
        path = relpath
        try:
            path = self.abspath(relpath)
            os.remove(path)
        except (IOError, OSError),e:
            # TODO: What about path_to?
            self._translate_error(e, path)

    def copy_to(self, relpaths, other, mode=None, pb=None):
        """Copy a set of entries from self into another Transport.

        :param relpaths: A list/generator of entries to be copied.
        """
        if isinstance(other, LocalTransport):
            # Both from & to are on the local filesystem
            # Unfortunately, I can't think of anything faster than just
            # copying them across, one by one :(
            import shutil

            total = self._get_total(relpaths)
            count = 0
            for path in relpaths:
                self._update_pb(pb, 'copy-to', count, total)
                try:
                    mypath = self.abspath(path)
                    otherpath = other.abspath(path)
                    shutil.copy(mypath, otherpath)
                    if mode is not None:
                        os.chmod(otherpath, mode)
                except (IOError, OSError),e:
                    self._translate_error(e, path)
                count += 1
            return count
        else:
            return super(LocalTransport, self).copy_to(relpaths, other, mode=mode, pb=pb)

    def listable(self):
        """See Transport.listable."""
        return True

    def list_dir(self, relpath):
        """Return a list of all files at the given location.
        WARNING: many transports do not support this, so trying avoid using
        it if at all possible.
        """
        path = relpath
        try:
            path = self.abspath(relpath)
            return os.listdir(path)
        except (IOError, OSError),e:
            self._translate_error(e, path)

    def stat(self, relpath):
        """Return the stat information for a file.
        """
        path = relpath
        try:
            path = self.abspath(relpath)
            return os.stat(path)
        except (IOError, OSError),e:
            self._translate_error(e, path)

    def lock_read(self, relpath):
        """Lock the given file for shared (read) access.
        :return: A lock object, which should be passed to Transport.unlock()
        """
        from bzrlib.lock import ReadLock
        path = relpath
        try:
            path = self.abspath(relpath)
            return ReadLock(path)
        except (IOError, OSError), e:
            self._translate_error(e, path)

    def lock_write(self, relpath):
        """Lock the given file for exclusive (write) access.
        WARNING: many transports do not support this, so trying avoid using it

        :return: A lock object, which should be passed to Transport.unlock()
        """
        from bzrlib.lock import WriteLock
        return WriteLock(self.abspath(relpath))

    def rmdir(self, relpath):
        """See Transport.rmdir."""
        path = relpath
        try:
            path = self.abspath(relpath)
            os.rmdir(path)
        except (IOError, OSError),e:
            self._translate_error(e, path)


class ScratchTransport(LocalTransport):
    """A transport that works in a temporary dir and cleans up after itself.
    
    The dir only exists for the lifetime of the Python object.
    Obviously you should not put anything precious in it.
    """

    def __init__(self, base=None):
        if base is None:
            base = tempfile.mkdtemp()
        super(ScratchTransport, self).__init__(base)

    def __del__(self):
        shutil.rmtree(self.base, ignore_errors=True)
        mutter("%r destroyed" % self)


class LocalRelpathServer(Server):
    """A pretend server for local transports, using relpaths."""

    def get_url(self):
        """See Transport.Server.get_url."""
        return "."


class LocalAbspathServer(Server):
    """A pretend server for local transports, using absolute paths."""

    def get_url(self):
        """See Transport.Server.get_url."""
        return os.path.abspath("")


class LocalURLServer(Server):
    """A pretend server for local transports, using file:// urls."""

    def get_url(self):
        """See Transport.Server.get_url."""
        # FIXME: \ to / on windows
        return "file://%s" % os.path.abspath("")


def get_test_permutations():
    """Return the permutations to be used in testing."""
    return [(LocalTransport, LocalRelpathServer),
            (LocalTransport, LocalAbspathServer),
            (LocalTransport, LocalURLServer),
            ]
