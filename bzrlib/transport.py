#!/usr/bin/env python
"""\
This module contains the basic class handling transport of
information.
"""

from bzrlib.trace import mutter
from bzrlib.errors import BzrError

_protocol_handlers = {
}

def register_transport(prefix, klass, override=True):
    global _protocol_handlers

    if _protocol_handlers.has_key(prefix):
        if override:
            mutter('overriding transport: %s => %s' % (prefix, klass.__name__))
            _protocol_handlers[prefix] = klass
    else:
        mutter('registering transport: %s => %s' % (prefix, klass.__name__))
        _protocol_handlers[prefix] = klass

class TransportError(BzrError):
    """All errors thrown by Transport implementations should derive
    from this class.
    """
    def __init__(self, msg=None, orig_error=None):
        if msg is None and orig_error is not None:
            msg = str(orig_error)
        BzrError.__init__(self, msg)
        self.msg = msg
        self.orig_error = orig_error

class AsyncError(TransportError):
    pass

# A set of semi-meaningful errors which can be thrown
class TransportNotPossible(TransportError):
    """This is for transports where a specific function is explicitly not
    possible. Such as pushing files to an HTTP server.
    """
    pass

class NonRelativePath(TransportError):
    """An absolute path was supplied, that could not be decoded into
    a relative path.
    """
    pass

class NoSuchFile(TransportError, IOError):
    """A get() was issued for a file that doesn't exist."""
    def __init__(self, msg=None, orig_error=None):
        import errno
        TransportError.__init__(self, msg=msg, orig_error=orig_error)
        IOError.__init__(self, errno.ENOENT, self.msg)

class FileExists(TransportError, OSError):
    """An operation was attempted, which would overwrite an entry,
    but overwritting is not supported.

    mkdir() can throw this, but put() just overwites existing files.
    """
    def __init__(self, msg=None, orig_error=None):
        import errno
        TransportError.__init__(self, msg=msg, orig_error=orig_error)
        OSError.__init__(self, errno.EEXIST, self.msg)

class PermissionDenied(TransportError):
    """An operation cannot succeed because of a lack of permissions."""
    pass

class ConnectionReset(TransportError):
    """The connection has been closed."""
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
    """

    def __init__(self, base):
        super(Transport, self).__init__()
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

    def get(self, relpath):
        """Get the file at the given relative path.

        :param relpath: The relative path to the file
        """
        raise NotImplementedError

    def get_multi(self, relpaths, pb=None):
        """Get a list of file-like objects, one for each entry in relpaths.

        :param relpaths: A list of relative paths.
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
            yield self.get(relpath)
            count += 1

    def put(self, relpath, f):
        """Copy the file-like or string object into the location.

        :param relpath: Location to put the contents, relative to base.
        :param f:       File-like or string object.
        """
        raise NotImplementedError

    def put_multi(self, files, pb=None):
        """Put a set of files or strings into the location.

        :param files: A list of tuples of relpath, file object [(path1, file1), (path2, file2),...]
        :param pb:  An optional ProgressBar for indicating percent done.
        :return: The number of files copied.
        """
        def put(relpath, f):
            self.put(relpath, f)
        return self._iterate_over(files, put, pb, 'put', expand=True)

    def mkdir(self, relpath):
        """Create a directory at the given path."""
        raise NotImplementedError

    def mkdir_multi(self, relpaths, pb=None):
        """Create a group of directories"""
        return self._iterate_over(relpaths, self.mkdir, pb, 'mkdir', expand=False)

    def append(self, relpath, f):
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
            other.put(path, self.get(path))

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
    global _protocol_handlers
    if base is None:
        base = '.'
    for proto, klass in _protocol_handlers.iteritems():
        if proto is not None and base.startswith(proto):
            return klass(base)
    # The default handler is the filesystem handler
    # which has a lookup of None
    return _protocol_handlers[None](base)

def transport_test(tester, t, readonly=False):
    """Test a transport object. Basically, it assumes that the
    Transport object is connected to the current working directory.
    So that whatever is done through the transport, should show
    up in the working directory, and vice-versa.

    This also tests to make sure that the functions work with both
    generators and lists (assuming iter(list) is effectively a generator)
    """
    import tempfile, os
    from local_transport import LocalTransport

    # Test has
    files = ['a', 'b', 'e', 'g']
    tester.build_tree(files)
    tester.assertEqual(t.has('a'), True)
    tester.assertEqual(t.has('c'), False)
    tester.assertEqual(list(t.has_multi(['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'])),
            [True, True, False, False, True, False, True, False])
    tester.assertEqual(list(t.has_multi(iter(['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h']))),
            [True, True, False, False, True, False, True, False])

    # Test get
    tester.assertEqual(t.get('a').read(), open('a').read())
    content_f = t.get_multi(files)
    for path,f in zip(files, content_f):
        tester.assertEqual(open(path).read(), f.read())

    content_f = t.get_multi(iter(files))
    for path,f in zip(files, content_f):
        tester.assertEqual(open(path).read(), f.read())

    tester.assertRaises(NoSuchFile, t.get, 'c')
    try:
        files = list(t.get_multi(['a', 'b', 'c']))
    except NoSuchFile:
        pass
    else:
        tester.fail('Failed to raise NoSuchFile for missing file in get_multi')
    try:
        files = list(t.get_multi(iter(['a', 'b', 'c', 'e'])))
    except NoSuchFile:
        pass
    else:
        tester.fail('Failed to raise NoSuchFile for missing file in get_multi')

    # Test put
    if readonly:
        open('c', 'wb').write('some text for c\n')
    else:
        t.put('c', 'some text for c\n')
    tester.assert_(os.path.exists('c'))
    tester.assertEqual(open('c').read(), 'some text for c\n')
    tester.assertEqual(t.get('c').read(), 'some text for c\n')
    # Make sure 'has' is updated
    tester.assertEqual(list(t.has_multi(['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'])),
            [True, True, True, False, True, False, True, False])
    if readonly:
        open('a', 'wb').write('new\ncontents for\na\n')
        open('d', 'wb').write('contents\nfor d\n')
    else:
        # Put also replaces contents
        tester.assertEqual(t.put_multi([('a', 'new\ncontents for\na\n'),
                                      ('d', 'contents\nfor d\n')]),
                         2)
    tester.assertEqual(list(t.has_multi(['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'])),
            [True, True, True, True, True, False, True, False])
    tester.assertEqual(open('a').read(), 'new\ncontents for\na\n')
    tester.assertEqual(open('d').read(), 'contents\nfor d\n')

    if readonly:
        open('a', 'wb').write('diff\ncontents for\na\n')
        open('d', 'wb').write('another contents\nfor d\n')
    else:
        tester.assertEqual(
            t.put_multi(iter([('a', 'diff\ncontents for\na\n'),
                              ('d', 'another contents\nfor d\n')]))
                         , 2)
    tester.assertEqual(open('a').read(), 'diff\ncontents for\na\n')
    tester.assertEqual(open('d').read(), 'another contents\nfor d\n')

    if not readonly:
        tester.assertRaises(NoSuchFile, t.put, 'path/doesnt/exist/c', 'contents')

    # Test mkdir
    os.mkdir('dir_a')
    tester.assertEqual(t.has('dir_a'), True)
    tester.assertEqual(t.has('dir_b'), False)

    if readonly:
        os.mkdir('dir_b')
    else:
        t.mkdir('dir_b')
    tester.assertEqual(t.has('dir_b'), True)
    tester.assert_(os.path.isdir('dir_b'))

    if readonly:
        os.mkdir('dir_c')
        os.mkdir('dir_d')
    else:
        t.mkdir_multi(['dir_c', 'dir_d'])
    tester.assertEqual(list(t.has_multi(['dir_a', 'dir_b', 'dir_c', 'dir_d', 'dir_e', 'dir_b'])),
            [True, True, True, True, False, True])
    for d in ['dir_a', 'dir_b', 'dir_c', 'dir_d']:
        tester.assert_(os.path.isdir(d))

    if not readonly:
        tester.assertRaises(NoSuchFile, t.mkdir, 'path/doesnt/exist')
        tester.assertRaises(FileExists, t.mkdir, 'dir_a') # Creating a directory again should fail

    # Make sure the transport recognizes when a
    # directory is created by other means
    # Caching Transports will fail, because dir_e was already seen not
    # to exist. So instead, we will search for a new directory
    #os.mkdir('dir_e')
    #if not readonly:
    #    tester.assertRaises(FileExists, t.mkdir, 'dir_e')

    os.mkdir('dir_f')
    if not readonly:
        tester.assertRaises(FileExists, t.mkdir, 'dir_f')

    # Test get/put in sub-directories
    if readonly:
        open('dir_a/a', 'wb').write('contents of dir_a/a')
        open('dir_b/b', 'wb').write('contents of dir_b/b')
    else:
        tester.assertEqual(
            t.put_multi([('dir_a/a', 'contents of dir_a/a'),
                         ('dir_b/b', 'contents of dir_b/b')])
                      , 2)
    for f in ('dir_a/a', 'dir_b/b'):
        tester.assertEqual(t.get(f).read(), open(f).read())

    # Test copy_to
    dtmp = tempfile.mkdtemp(dir='.', prefix='test-transport-')
    dtmp_base = os.path.basename(dtmp)
    local_t = LocalTransport(dtmp)

    files = ['a', 'b', 'c', 'd']
    t.copy_to(files, local_t)
    for f in files:
        tester.assertEquals(open(f).read(), open(os.path.join(dtmp_base, f)).read())

    # TODO: Test append
    # TODO: Make sure all entries support file-like objects as well as strings.

# Local transport should always be initialized
import local_transport
