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
"""Implementation of Transport for the local filesystem.
"""

from bzrlib.transport import Transport, register_transport, \
    TransportError, NoSuchFile, FileExists
import os, errno

class LocalTransportError(TransportError):
    pass

class LocalTransport(Transport):
    """This is the transport agent for local filesystem access."""

    def __init__(self, base):
        """Set the base path where files will be stored."""
        if base.startswith('file://'):
            base = base[7:]
        # realpath is incompatible with symlinks. When we traverse
        # up we might be able to normpath stuff. RBC 20051003
        super(LocalTransport, self).__init__(
            os.path.normpath(os.path.abspath(base)))

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
        """Return the full url to the given relative path.
        This can be supplied with a string or a list
        """
        if isinstance(relpath, basestring):
            relpath = [relpath]
        return os.path.join(self.base, *relpath)

    def relpath(self, abspath):
        """Return the local path portion from a given absolute path.
        """
        from bzrlib.branch import _relpath
        return _relpath(self.base, abspath)

    def has(self, relpath):
        return os.access(self.abspath(relpath), os.F_OK)

    def get(self, relpath):
        """Get the file at the given relative path.

        :param relpath: The relative path to the file
        """
        try:
            path = self.abspath(relpath)
            return open(path, 'rb')
        except IOError,e:
            if e.errno == errno.ENOENT:
                raise NoSuchFile('File %r does not exist' % path, orig_error=e)
            raise LocalTransportError(orig_error=e)

    def get_partial(self, relpath, start, length=None):
        """Get just part of a file.

        :param relpath: Path to the file, relative to base
        :param start: The starting position to read from
        :param length: The length to read. A length of None indicates
                       read to the end of the file.
        :return: A file-like object containing at least the specified bytes.
                 Some implementations may return objects which can be read
                 past this length, but this is not guaranteed.
        """
        # LocalTransport.get_partial() doesn't care about the length
        # argument, because it is using a local file, and thus just
        # returns the file seek'ed to the appropriate location.
        try:
            path = self.abspath(relpath)
            f = open(path, 'rb')
            f.seek(start, 0)
            return f
        except IOError,e:
            if e.errno == errno.ENOENT:
                raise NoSuchFile('File %r does not exist' % path, orig_error=e)
            raise LocalTransportError(orig_error=e)

    def put(self, relpath, f):
        """Copy the file-like or string object into the location.

        :param relpath: Location to put the contents, relative to base.
        :param f:       File-like or string object.
        """
        from bzrlib.atomicfile import AtomicFile

        try:
            path = self.abspath(relpath)
            fp = AtomicFile(path, 'wb')
        except IOError, e:
            if e.errno == errno.ENOENT:
                raise NoSuchFile('File %r does not exist' % path, orig_error=e)
            raise LocalTransportError(orig_error=e)
        try:
            self._pump(f, fp)
            fp.commit()
        finally:
            fp.close()

    def mkdir(self, relpath):
        """Create a directory at the given path."""
        try:
            os.mkdir(self.abspath(relpath))
        except OSError,e:
            if e.errno == errno.EEXIST:
                raise FileExists(orig_error=e)
            elif e.errno == errno.ENOENT:
                raise NoSuchFile(orig_error=e)
            raise LocalTransportError(orig_error=e)

    def append(self, relpath, f):
        """Append the text in the file-like object into the final
        location.
        """
        fp = open(self.abspath(relpath), 'ab')
        self._pump(f, fp)

    def copy(self, rel_from, rel_to):
        """Copy the item at rel_from to the location at rel_to"""
        import shutil
        path_from = self.abspath(rel_from)
        path_to = self.abspath(rel_to)
        try:
            shutil.copy(path_from, path_to)
        except OSError,e:
            raise LocalTransportError(orig_error=e)

    def move(self, rel_from, rel_to):
        """Move the item at rel_from to the location at rel_to"""
        path_from = self.abspath(rel_from)
        path_to = self.abspath(rel_to)

        try:
            os.rename(path_from, path_to)
        except OSError,e:
            raise LocalTransportError(orig_error=e)

    def delete(self, relpath):
        """Delete the item at relpath"""
        try:
            os.remove(self.abspath(relpath))
        except OSError,e:
            raise LocalTransportError(orig_error=e)

    def copy_to(self, relpaths, other, pb=None):
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
                shutil.copy(self.abspath(path), other.abspath(path))
                count += 1
            return count
        else:
            return super(LocalTransport, self).copy_to(relpaths, other, pb=pb)


    def list_dir(self, relpath):
        """Return a list of all files at the given location.
        WARNING: many transports do not support this, so trying avoid using
        it if at all possible.
        """
        try:
            return os.listdir(self.abspath(relpath))
        except OSError,e:
            raise LocalTransportError(orig_error=e)

    def stat(self, relpath):
        """Return the stat information for a file.
        """
        try:
            return os.stat(self.abspath(relpath))
        except OSError,e:
            raise LocalTransportError(orig_error=e)

    def lock_read(self, relpath):
        """Lock the given file for shared (read) access.
        :return: A lock object, which should be passed to Transport.unlock()
        """
        from bzrlib.lock import ReadLock
        return ReadLock(self.abspath(relpath))

    def lock_write(self, relpath):
        """Lock the given file for exclusive (write) access.
        WARNING: many transports do not support this, so trying avoid using it

        :return: A lock object, which should be passed to Transport.unlock()
        """
        from bzrlib.lock import WriteLock
        return WriteLock(self.abspath(relpath))

# If nothing else matches, try the LocalTransport
register_transport(None, LocalTransport)
register_transport('file://', LocalTransport)
