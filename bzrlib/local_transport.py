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

    def is_remote(self):
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
        from branch import _relpath
        return _relpath(self.base, abspath)

    def has(self, relpath):
        return os.access(self.abspath(relpath), os.F_OK)

    def get(self, relpath, decode=False):
        """Get the file at the given relative path.

        :param relpath: The relative path to the file
        :param decode:  If True, assume the file is utf-8 encoded and
                        decode it into Unicode
        """
        if decode:
            import codecs
            return codecs.open(self.abspath(relpath), 'rb',
                    encoding='utf-8', buffering=60000)
        else:
            return open(self.abspath(relpath), 'rb')

    def put(self, relpath, f, encode=False):
        """Copy the file-like or string object into the location.

        :param relpath: Location to put the contents, relative to base.
        :param f:       File-like or string object.
        :param encode:  If True, translate the contents into utf-8 encoded text.
        """
        from bzrlib.atomicfile import AtomicFile

        if encode:
            fp = AtomicFile(self.abspath(relpath), 'wb', encoding='utf-8')
        else:
            fp = AtomicFile(self.abspath(relpath), 'wb')
        try:
            self._pump(f, fp)
            fp.commit()
        finally:
            fp.close()

    def mkdir(self, relpath):
        """Create a directory at the given path."""
        os.mkdir(self.abspath(relpath))

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
protocol_handlers[None] = LocalTransport

