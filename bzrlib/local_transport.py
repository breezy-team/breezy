#!/usr/bin/env python
"""\
An implementation of the Transport object for local
filesystem access.
"""

from bzrlib.transport import Transport, protocol_handlers
import os

class LocalTransport(Transport):
    """This is the transport agent for local filesystem access."""

    def __init__(self, base):
        """Set the base path where files will be stored."""
        from os.path import realpath
        super(LocalTransport, self).__init__(realpath(base))

    def clone(self, offset=None):
        """Return a new LocalTransport with root at self.base + offset
        Because the local filesystem does not require a connection, 
        we can just return a new object.
        """
        if offset is None:
            return LocalTransport(self.base)
        else:
            return LocalTransport(self.abspath(offset))

    def abspath(self, *args):
        """Return the full url to the given relative path.
        This can be supplied with multiple arguments
        """
        return os.path.join(self.base, *args)

    def has(self, relpath):
        return os.access(self.abspath(relpath), os.F_OK)

    def get(self, relpath):
        """Get the file at the given relative path.
        """
        return open(self.abspath(relpath), 'rb')

    def put(self, relpath, f):
        """Copy the file-like object into the location.
        """
        from bzrlib.atomicfile import AtomicFile

        fp = AtomicFile(self.abspath(relpath), 'wb')
        try:
            self._pump(f, fp)
            fp.commit()
        finally:
            fp.close()

    def mkdir(self, relpath):
        """Create a directory at the given path."""
        os.mkdir(self.abspath(relpath))

    def open(self, relpath, mode='wb'):
        """Open a remote file for writing.
        This may return a proxy object, which is written to locally, and
        then when the file is closed, it is uploaded using put()
        """
        return open(self.abspath(relpath), mode)

    def append(self, relpath, f):
        """Append the text in the file-like object into the final
        location.
        """
        fp = open(self.abspath(relpath), 'a+b')
        self._pump(f, fp)

    def copy(self, rel_from, rel_to):
        """Copy the item at rel_from to the location at rel_to"""
        import shutil
        path_from = self.abspath(rel_from)
        path_to = self.abspath(rel_to)
        shutil.copy(path_from, path_to)

    def move(self, rel_from, rel_to):
        """Move the item at rel_from to the location at rel_to"""
        path_from = self.abspath(rel_from)
        path_to = self.abspath(rel_to)

        os.rename(path_from, path_to)

    def delete(self, relpath):
        """Delete the item at relpath"""
        os.remove(self.abspath(relpath))

    def async_get(self, relpath):
        """Make a request for an file at the given location, but
        don't worry about actually getting it yet.

        :rtype: AsyncFile
        """
        raise NotImplementedError

    def list_dir(self, relpath):
        """Return a list of all files at the given location.
        WARNING: many transports do not support this, so trying avoid using
        it if at all possible.
        """
        return os.listdir(self.abspath(relpath))

    def stat(self, relpath):
        """Return the stat information for a file.
        """
        return os.stat(self.abspath(relpath))

# If nothing else matches, try the LocalTransport
protocol_handlers[None] = LocalTransport

