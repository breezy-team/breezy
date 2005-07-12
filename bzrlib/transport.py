#!/usr/bin/env python
"""\
This module contains the basic class handling transport of
information.
"""

protocol_handlers = {
}

class AsyncError(Exception):
    pass

class TransportNotPossibleError(Exception):
    """This is for transports where a specific function is explicitly not
    possible. Such as pushing files to an HTTP server.
    """
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
    In general implementations should support having a generator or a list
    as an argument (ie always iterate, never index)

    TODO: Worry about file encodings. For instance bzr control files should
          all be encoded in utf-8, but read as local encoding.

    TODO: Consider adding a lock/unlock functions.
    """

    def __init__(self, base):
        self.base = base

    def clone(self, offset=None):
        """Return a new Transport object, cloned from the current location,
        using a subdirectory. This allows connections to be pooled,
        rather than a new one needed for each subdir.
        """
        raise NotImplementedError

    def should_cache(self):
        """Return True if the data pulled across should be cached locally.
        """
        return False

    def _pump(self, from_file, to_file):
        """Most children will need to copy from one file-like 
        object or string to another one.
        This just gives them something easy to call.
        """
        if isinstance(from_file, basestring):
            to_file.write(from_file)
        else:
            from bzrlib.osutils import pumpfile
            pumpfile(from_file, to_file)

    def _get_total(self, multi):
        """Try to figure out how many entries are in multi,
        but if not possible, return None.
        """
        try:
            return len(multi)
        except TypeError: # We can't tell how many, because relpaths is a generator
            return None

    def _update_pb(self, pb, msg, count, total):
        """Update the progress bar based on the current count
        and total available, total may be None if it was
        not possible to determine.
        """
        if pb is None:
            return
        if total is None:
            pb.update(msg, count, count+1)
        else:
            pb.update(msg, count, total)

    def _iterate_over(self, multi, func, pb, msg, expand=True):
        """Iterate over all entries in multi, passing them to func,
        and update the progress bar as you go along.

        :param expand:  If True, the entries will be passed to the function
                        by expanding the tuple. If False, it will be passed
                        as a single parameter.
        """
        total = self._get_total(multi)
        count = 0
        for entry in multi:
            self._update_pb(pb, msg, count, total)
            if expand:
                func(*entry)
            else:
                func(entry)
            count += 1
        return count

    def abspath(self, relpath):
        """Return the full url to the given relative path.
        This can be supplied with a string or a list
        """
        raise NotImplementedError

    def relpath(self, abspath):
        """Return the local path portion from a given absolute path.
        """
        raise NotImplementedError

    def has(self, relpath):
        """Does the target location exist?"""
        raise NotImplementedError

    def has_multi(self, relpaths, pb=None):
        """Return True/False for each entry in relpaths"""
        total = self._get_total(relpaths)
        count = 0
        for relpath in relpaths:
            self._update_pb(pb, 'has', count, total)
            yield self.has(relpath)
            count += 1

    def get(self, relpath, decode=False):
        """Get the file at the given relative path.

        :param relpath: The relative path to the file
        :param decode:  If True, assume the file is utf-8 encoded and
                        decode it into Unicode
        """
        raise NotImplementedError

    def get_multi(self, relpaths, decode=False, pb=None):
        """Get a list of file-like objects, one for each entry in relpaths.

        :param relpaths: A list of relative paths.
        :param decode:  If True, assume the file is utf-8 encoded and
                        decode it into Unicode
        :param pb:  An optional ProgressBar for indicating percent done.
        :return: A list or generator of file-like objects
        """
        # TODO: Consider having this actually buffer the requests,
        # in the default mode, it probably won't give worse performance,
        # and all children wouldn't have to implement buffering
        total = self._get_total(relpaths)
        count = 0
        for relpath in relpaths:
            self._update_pb(pb, 'get', count, total)
            yield self.get(relpath, decode=decode)
            count += 1

    def put(self, relpath, f, encode=False):
        """Copy the file-like or string object into the location.

        :param relpath: Location to put the contents, relative to base.
        :param f:       File-like or string object.
        :param encode:  If True, translate the contents into utf-8 encoded text.
        """
        raise NotImplementedError

    def put_multi(self, files, encode=False, pb=None):
        """Put a set of files or strings into the location.

        :param files: A list of tuples of relpath, file object [(path1, file1), (path2, file2),...]
        :param pb:  An optional ProgressBar for indicating percent done.
        :return: The number of files copied.
        """
        def put(relpath, f):
            self.put(relpath, f, encode=encode)
        return self._iterate_over(files, put, pb, 'put', expand=True)

    def mkdir(self, relpath):
        """Create a directory at the given path."""
        raise NotImplementedError

    def append(self, relpath, f, encode=False):
        """Append the text in the file-like or string object to 
        the supplied location.
        """
        raise NotImplementedError

    def append_multi(self, files):
        """Append the text in each file-like or string object to
        the supplied location.

        :param files: A set of (path, f) entries
        :param pb:  An optional ProgressBar for indicating percent done.
        """
        return self._iterate_over(files, self.append, pb, 'append', expand=True)

    def copy(self, rel_from, rel_to):
        """Copy the item at rel_from to the location at rel_to"""
        raise NotImplementedError

    def copy_multi(self, relpaths, pb=None):
        """Copy a bunch of entries.
        
        :param relpaths: A list of tuples of the form [(from, to), (from, to),...]
        """
        # This is the non-pipelined implementation, so that
        # implementors don't have to implement everything.
        return self._iterate_over(relpaths, self.copy, pb, 'copy', expand=True)

    def copy_to(self, relpaths, other, pb=None):
        """Copy a set of entries from self into another Transport.

        :param relpaths: A list/generator of entries to be copied.
        """
        # The dummy implementation just does a simple get + put
        def copy_entry(path):
            other.put(path, self.get(path, decode=False), encode=False)

        return self._iterate_over(relpaths, copy_entry, pb, 'copy_to', expand=False)


    def move(self, rel_from, rel_to):
        """Move the item at rel_from to the location at rel_to"""
        raise NotImplementedError

    def move_multi(self, relpaths, pb=None):
        """Move a bunch of entries.
        
        :param relpaths: A list of tuples of the form [(from1, to1), (from2, to2),...]
        """
        return self._iterate_over(relpaths, self.move, pb, 'move', expand=True)

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

    def delete_multi(self, relpaths, pb=None):
        """Queue up a bunch of deletes to be done.
        """
        return self._iterate_over(relpaths, self.delete, pb, 'delete', expand=False)

    def stat(self, relpath):
        """Return the stat information for a file.
        WARNING: This may not be implementable for all protocols, so use
        sparingly.
        """
        raise NotImplementedError

    def stat_multi(self, relpaths, pb=None):
        """Stat multiple files and return the information.
        """
        #TODO:  Is it worth making this a generator instead of a
        #       returning a list?
        stats = []
        def gather(path):
            stats.append(self.stat(path))

        count = self._iterate_over(relpaths, gather, pb, 'stat', expand=False)
        return stats


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

    def lock_read(self, relpath):
        """Lock the given file for shared (read) access.
        WARNING: many transports do not support this, so trying avoid using it

        :return: A lock object, which should contain an unlock() function.
        """
        raise NotImplementedError

    def lock_write(self, relpath):
        """Lock the given file for exclusive (write) access.
        WARNING: many transports do not support this, so trying avoid using it

        :return: A lock object, which should contain an unlock() function.
        """
        raise NotImplementedError


def transport(base):
    if base is None:
        base = '.'
    for proto, klass in protocol_handlers.iteritems():
        if proto is not None and base.startswith(proto):
            return klass(base)
    # The default handler is the filesystem handler
    # which has a lookup of None
    return protocol_handlers[None](base)


# Local transport should always be initialized
import local_transport
