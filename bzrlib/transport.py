#!/usr/bin/env python
"""\
This module contains the basic class handling transport of
information.
"""

protocol_handlers = {
}

class AsyncError(Exception):
    pass

class AsyncFile(object):
    """This will be returned from a Transport object,
    whenever an asyncronous get is requested.
    """
    _max_write_buffer = 8192

    def __init__(self):
        self.read_buffer = []
        self.write_buffer = []
        self._finalized = False

    def _total_len(self, buffer):
        count = 0
        for b in buffer:
            count += len(b)
        return count

    def finalize(self):
        """This will block until all data has been buffered for
        reading, or all data has been flushed for writing.
        Once this is called, you can no longer write more data.
        """
        raise NotImplementedError

    def can_read(self):
        """Can we read some data without blocking"""
        return len(self.read_buffer) > 0

    def can_write(self):
        """Can we write some more data out without blocking?"""
        return (not self._finalized \
                and self._total_len(self.write_buffer) < self._max_write_buffer)

    def write(self, chunk):
        if self._finalized:
            raise AsyncError('write attempted on finalized file.')
        self.write_buffer.append(chunk)

    def read(self, size=None):
        if size is None:
            return ''.join(self.read_buffer)
        else:
            out = ''
            while True:
                buf = self.read_buffer.pop(0)
                if len(buf) + len(out) < size:
                    out += buf
                else:
                    left = size - len(out)
                    out += buf[:left]
                    buf = buf[left:]
                    self.read_buffer.insert(0, buf)
                    return out


class Transport(object):
    """This class encapsulates methods for retrieving or putting a file
    from/to a storage location.

    Most functions have a _multi variant, which allows you to queue up
    multiple requests. They generally have a dumb base implementation 
    which just iterates over the arguments, but smart Transport
    implementations can do pipelining.
    """

    def __init__(self, base):
        self.base = base

    def _pump(self, from_file, to_file):
        """Most children will need to copy from one file-like 
        object or string to another one.
        This just gives them something easy to call.
        """
        if isinstance(from_file, basestring):
            to_file.write(basestring)
        else:
            from bzrlib.osutils import pumpfile
            pumpfile(from_file, to_file)

    def has(self, relpath):
        """Does the target location exist?"""
        raise NotImplementedError

    def get(self, relpath):
        """Get the file at the given relative path.
        """
        raise NotImplementedError

    def get_multi(self, relpaths):
        """Get a list of file-like objects, one for each entry in relpaths.

        :param relpaths: A list of relative paths.
        :return: A list of file-like objects.
        """
        files = []
        for relpath in relpaths:
            files.append(self.get(relpath))
        return files

    def put(self, relpath, f):
        """Copy the file-like or string object into the location.
        """
        raise NotImplementedError

    def put_multi(self, files):
        """Put a set of files or strings into the location.

        :param files: A list of tuples of relpath, file object [(path1, file1), (path2, file2),...]
        """
        for path, f in files:
            self.put(path, f)

    def append(self, relpath, f):
        """Append the text in the file-like or string object to 
        the supplied location.
        """
        raise NotImplementedError

    def append_multi(self, files):
        """Append the text in each file-like or string object to
        the supplied location.
        """
        for path, f in files:
            self.append(path, f)

    def copy(self, rel_from, rel_to):
        """Copy the item at rel_from to the location at rel_to"""
        raise NotImplementedError

    def copy_multi(self, relpaths):
        """Copy a bunch of entries.
        
        :param relpaths: A list of tuples of the form [(from, to), (from, to),...]
        """
        # This is the non-pipelined implementation, so that
        # implementors don't have to implement everything.
        for rel_from, rel_to in relpaths:
            self.copy(rel_from, rel_to)

    def move(self, rel_from, rel_to):
        """Move the item at rel_from to the location at rel_to"""
        raise NotImplementedError

    def move_multi(self, relpaths):
        """Move a bunch of entries.
        
        :param relpaths: A list of tuples of the form [(from1, to1), (from2, to2),...]
        """
        for rel_from, rel_to in relpaths:
            self.move(rel_from, rel_to)

    def move_multi_to(self, relpaths, rel_to):
        """Move a bunch of entries to a single location.
        This differs from move_multi in that you give a list of from, and
        a single destination, rather than multiple destinations.

        :param relpaths: A list of relative paths [from1, from2, from3, ...]
        :param rel_to: A directory where each entry should be placed.
        """
        # This is not implemented, because you need to do special tricks to
        # extract the basename, and add it to rel_to
        raise NotImplementedError

    def delete(self, relpath):
        """Delete the item at relpath"""
        raise NotImplementedError

    def delete_multi(self, relpaths):
        """Queue up a bunch of deletes to be done.
        """
        for relpath in relpaths:
            self.delete(relpath)

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
        raise NotImplementedError

def transport(base):
    for proto, klass in protocol_handlers.iteritems():
        if proto is not None and base.startswith(proto):
            return klass(base)
    # The default handler is the filesystem handler
    # which has a lookup of None
    return protocol_handlers[None](base)


# Local transport should always be initialized
import local_transport
