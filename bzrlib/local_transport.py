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

    def _join(self, relpath):
        return os.path.join(self.base, relpath)

    def has(self, relpath):
        return os.access(self._join(relpath), os.F_OK)

    def get(self, relpath):
        """Get the file at the given relative path.
        """
        return open(self._join(relpath), 'rb')

    def put(self, relpath, f):
        """Copy the file-like object into the location.
        """
        from bzrlib.atomicfile import AtomicFile

        fp = AtomicFile(self._join(relpath), 'wb')
        self._pump(f, fp)
        fp.commit()

    def append(self, relpath, f):
        """Append the text in the file-like object into the final
        location.
        """
        fp = open(self._join(relpath), 'a+b')
        self._pump(f, fp)

    def copy(self, rel_from, rel_to):
        """Copy the item at rel_from to the location at rel_to"""
        import shutil
        path_from = self._join(rel_from)
        path_to = self._join(rel_to)
        shutil.copy(path_from, path_to)

    def move(self, rel_from, rel_to):
        """Move the item at rel_from to the location at rel_to"""
        path_from = self._join(rel_from)
        path_to = self._join(rel_to)

        os.rename(path_from, path_to)

    def delete(self, relpath):
        """Delete the item at relpath"""
        os.remove(self._join(relpath))

    def async_get(self, relpath):
        """Make a request for an file at the given location, but
        don't worry about actually getting it yet.

        :rtype: AsyncFile
        """
        raise NotImplementedError

# If nothing else matches, try the LocalTransport
protocol_handlers[None] = LocalTransport

