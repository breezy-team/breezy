#!/usr/bin/env python
"""\
An implementation of the Transport object for local
filesystem access.
"""

from bzrlib.transport import Transport, register_transport, TransportError
import os

class LocalTransportError(TransportError):
    pass

class LocalTransport(Transport):
    """This is the transport agent for local filesystem access."""

    def __init__(self, base):
        """Set the base path where files will be stored."""
        from os.path import realpath
        super(LocalTransport, self).__init__(realpath(base))

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
        try:
            if decode:
                import codecs
                return codecs.open(self.abspath(relpath), 'rb',
                        encoding='utf-8', buffering=60000)
            else:
                return open(self.abspath(relpath), 'rb')
        except IOError,e:
            raise LocalTransportError(e)

    def put(self, relpath, f, encode=False):
        """Copy the file-like or string object into the location.

        :param relpath: Location to put the contents, relative to base.
        :param f:       File-like or string object.
        :param encode:  If True, translate the contents into utf-8 encoded text.
        """
        from bzrlib.atomicfile import AtomicFile

        try:
            if encode:
                fp = AtomicFile(self.abspath(relpath), 'wb', encoding='utf-8')
            else:
                fp = AtomicFile(self.abspath(relpath), 'wb')
        except IOError, e:
            raise LocalTransportError(e)
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
            raise LocalTransportError(e)

    def append(self, relpath, f, encode=False):
        """Append the text in the file-like object into the final
        location.
        """
        if encode:
            fp = codecs.open(self.abspath(relpath), 'ab',
                    encoding='utf-8', buffering=60000)
        else:
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
            raise LocalTransportError(e)

    def move(self, rel_from, rel_to):
        """Move the item at rel_from to the location at rel_to"""
        path_from = self.abspath(rel_from)
        path_to = self.abspath(rel_to)

        try:
            os.rename(path_from, path_to)
        except OSError,e:
            raise LocalTransportError(e)

    def delete(self, relpath):
        """Delete the item at relpath"""
        try:
            os.remove(self.abspath(relpath))
        except OSError,e:
            raise LocalTransportError(e)

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
        try:
            return os.listdir(self.abspath(relpath))
        except OSError,e:
            raise LocalTransportError(e)

    def stat(self, relpath):
        """Return the stat information for a file.
        """
        try:
            return os.stat(self.abspath(relpath))
        except OSError,e:
            raise LocalTransportError(e)

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
