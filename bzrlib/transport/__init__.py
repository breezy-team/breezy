# Copyright (C) 2005, 2006, 2007 Canonical Ltd
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Transport is an abstraction layer to handle file access.

The abstraction is to allow access from the local filesystem, as well
as remote (such as http or sftp).

Transports are constructed from a string, being a URL or (as a degenerate
case) a local filesystem path.  This is typically the top directory of
a bzrdir, repository, or similar object we are interested in working with.
The Transport returned has methods to read, write and manipulate files within
it.
"""

from cStringIO import StringIO
import re
import sys

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
import errno
from collections import deque
from stat import S_ISDIR
import unittest
import urllib
import urlparse
import warnings

import bzrlib
from bzrlib import (
    errors,
    osutils,
    symbol_versioning,
    urlutils,
    )
""")

from bzrlib.symbol_versioning import (
        deprecated_passed,
        deprecated_method,
        deprecated_function,
        DEPRECATED_PARAMETER,
        zero_eight,
        zero_eleven,
        zero_ninety,
        )
from bzrlib.trace import (
    note,
    mutter,
    warning,
    )
from bzrlib import registry


# a dictionary of open file streams. Keys are absolute paths, values are
# transport defined.
_file_streams = {}


def _get_protocol_handlers():
    """Return a dictionary of {urlprefix: [factory]}"""
    return transport_list_registry


def _set_protocol_handlers(new_handlers):
    """Replace the current protocol handlers dictionary.

    WARNING this will remove all build in protocols. Use with care.
    """
    global transport_list_registry
    transport_list_registry = new_handlers


def _clear_protocol_handlers():
    global transport_list_registry
    transport_list_registry = TransportListRegistry()


def _get_transport_modules():
    """Return a list of the modules providing transports."""
    modules = set()
    for prefix, factory_list in transport_list_registry.iteritems():
        for factory in factory_list:
            if hasattr(factory, "_module_name"):
                modules.add(factory._module_name)
            else:
                modules.add(factory._obj.__module__)
    # Add chroot directly, because there is not handler registered for it.
    modules.add('bzrlib.transport.chroot')
    result = list(modules)
    result.sort()
    return result


class TransportListRegistry(registry.Registry):
    """A registry which simplifies tracking available Transports.

    A registration of a new protocol requires two step:
    1) register the prefix with the function register_transport( )
    2) register the protocol provider with the function
    register_transport_provider( ) ( and the "lazy" variant )

    This is needed because:
    a) a single provider can support multple protcol ( like the ftp
    provider which supports both the ftp:// and the aftp:// protocols )
    b) a single protocol can have multiple providers ( like the http://
    protocol which is supported by both the urllib and pycurl provider )
    """

    def register_transport_provider(self, key, obj):
        self.get(key).insert(0, registry._ObjectGetter(obj))

    def register_lazy_transport_provider(self, key, module_name, member_name):
        self.get(key).insert(0, 
                registry._LazyObjectGetter(module_name, member_name))

    def register_transport(self, key, help=None, info=None):
        self.register(key, [], help, info)

    def set_default_transport(self, key=None):
        """Return either 'key' or the default key if key is None"""
        self._default_key = key


transport_list_registry = TransportListRegistry( )


def register_transport_proto(prefix, help=None, info=None):
    transport_list_registry.register_transport(prefix, help, info)


def register_lazy_transport(prefix, module, classname):
    if not prefix in transport_list_registry:
        register_transport_proto(prefix)
    transport_list_registry.register_lazy_transport_provider(prefix, module, classname)


def register_transport(prefix, klass, override=DEPRECATED_PARAMETER):
    if not prefix in transport_list_registry:
        register_transport_proto(prefix)
    transport_list_registry.register_transport_provider(prefix, klass)


def register_urlparse_netloc_protocol(protocol):
    """Ensure that protocol is setup to be used with urlparse netloc parsing."""
    if protocol not in urlparse.uses_netloc:
        urlparse.uses_netloc.append(protocol)


def _unregister_urlparse_netloc_protocol(protocol):
    """Remove protocol from urlparse netloc parsing.

    Except for tests, you should never use that function. Using it with 'http',
    for example, will break all http transports.
    """
    if protocol in urlparse.uses_netloc:
        urlparse.uses_netloc.remove(protocol)


def unregister_transport(scheme, factory):
    """Unregister a transport."""
    l = transport_list_registry.get(scheme)
    for i in l:
        o = i.get_obj( )
        if o == factory:
            transport_list_registry.get(scheme).remove(i)
            break
    if len(l) == 0:
        transport_list_registry.remove(scheme)



@deprecated_function(zero_ninety)
def split_url(url):
    # TODO: jam 20060606 urls should only be ascii, or they should raise InvalidURL
    if isinstance(url, unicode):
        url = url.encode('utf-8')
    (scheme, netloc, path, params,
     query, fragment) = urlparse.urlparse(url, allow_fragments=False)
    username = password = host = port = None
    if '@' in netloc:
        username, host = netloc.split('@', 1)
        if ':' in username:
            username, password = username.split(':', 1)
            password = urllib.unquote(password)
        username = urllib.unquote(username)
    else:
        host = netloc

    if ':' in host:
        host, port = host.rsplit(':', 1)
        try:
            port = int(port)
        except ValueError:
            # TODO: Should this be ConnectionError?
            raise errors.TransportError(
                'invalid port number %s in url:\n%s' % (port, url))
    host = urllib.unquote(host)

    path = urllib.unquote(path)

    return (scheme, username, password, host, port, path)


class _CoalescedOffset(object):
    """A data container for keeping track of coalesced offsets."""

    __slots__ = ['start', 'length', 'ranges']

    def __init__(self, start, length, ranges):
        self.start = start
        self.length = length
        self.ranges = ranges

    def __cmp__(self, other):
        return cmp((self.start, self.length, self.ranges),
                   (other.start, other.length, other.ranges))


class LateReadError(object):
    """A helper for transports which pretends to be a readable file.

    When read() is called, errors.ReadError is raised.
    """

    def __init__(self, path):
        self._path = path

    def close(self):
        """a no-op - do nothing."""

    def _fail(self):
        """Raise ReadError."""
        raise errors.ReadError(self._path)

    def __iter__(self):
        self._fail()

    def read(self, count=-1):
        self._fail()

    def readlines(self):
        self._fail()


class FileStream(object):
    """Base class for FileStreams."""

    def __init__(self, transport, relpath):
        """Create a FileStream for relpath on transport."""
        self.transport = transport
        self.relpath = relpath

    def _close(self):
        """A hook point for subclasses that need to take action on close."""

    def close(self):
        self._close()
        del _file_streams[self.transport.abspath(self.relpath)]


class FileFileStream(FileStream):
    """A file stream object returned by open_write_stream.
    
    This version uses a file like object to perform writes.
    """

    def __init__(self, transport, relpath, file_handle):
        FileStream.__init__(self, transport, relpath)
        self.file_handle = file_handle

    def _close(self):
        self.file_handle.close()

    def write(self, bytes):
        self.file_handle.write(bytes)


class AppendBasedFileStream(FileStream):
    """A file stream object returned by open_write_stream.
    
    This version uses append on a transport to perform writes.
    """

    def write(self, bytes):
        self.transport.append_bytes(self.relpath, bytes)


class Transport(object):
    """This class encapsulates methods for retrieving or putting a file
    from/to a storage location.

    Most functions have a _multi variant, which allows you to queue up
    multiple requests. They generally have a dumb base implementation 
    which just iterates over the arguments, but smart Transport
    implementations can do pipelining.
    In general implementations should support having a generator or a list
    as an argument (ie always iterate, never index)

    :ivar base: Base URL for the transport; should always end in a slash.
    """

    # implementations can override this if it is more efficient
    # for them to combine larger read chunks together
    _max_readv_combine = 50
    # It is better to read this much more data in order, rather
    # than doing another seek. Even for the local filesystem,
    # there is a benefit in just reading.
    # TODO: jam 20060714 Do some real benchmarking to figure out
    #       where the biggest benefit between combining reads and
    #       and seeking is. Consider a runtime auto-tune.
    _bytes_to_read_before_seek = 0

    def __init__(self, base):
        super(Transport, self).__init__()
        self.base = base

    def _translate_error(self, e, path, raise_generic=True):
        """Translate an IOError or OSError into an appropriate bzr error.

        This handles things like ENOENT, ENOTDIR, EEXIST, and EACCESS
        """
        if getattr(e, 'errno', None) is not None:
            if e.errno in (errno.ENOENT, errno.ENOTDIR):
                raise errors.NoSuchFile(path, extra=e)
            # I would rather use errno.EFOO, but there doesn't seem to be
            # any matching for 267
            # This is the error when doing a listdir on a file:
            # WindowsError: [Errno 267] The directory name is invalid
            if sys.platform == 'win32' and e.errno in (errno.ESRCH, 267):
                raise errors.NoSuchFile(path, extra=e)
            if e.errno == errno.EEXIST:
                raise errors.FileExists(path, extra=e)
            if e.errno == errno.EACCES:
                raise errors.PermissionDenied(path, extra=e)
            if e.errno == errno.ENOTEMPTY:
                raise errors.DirectoryNotEmpty(path, extra=e)
            if e.errno == errno.EBUSY:
                raise errors.ResourceBusy(path, extra=e)
        if raise_generic:
            raise errors.TransportError(orig_error=e)

    def clone(self, offset=None):
        """Return a new Transport object, cloned from the current location,
        using a subdirectory or parent directory. This allows connections 
        to be pooled, rather than a new one needed for each subdir.
        """
        raise NotImplementedError(self.clone)

    def close_file_stream(self, relpath):
        """Close a file stream at relpath.

        :raises: NoSuchFile if there is no open file stream for relpath.
        :seealso: open_file_stream.
        :return: None
        """
        raise NotImplementedError(self.close_file_stream)

    def ensure_base(self):
        """Ensure that the directory this transport references exists.

        This will create a directory if it doesn't exist.
        :return: True if the directory was created, False otherwise.
        """
        # The default implementation just uses "Easier to ask for forgiveness
        # than permission". We attempt to create the directory, and just
        # suppress a FileExists exception.
        try:
            self.mkdir('.')
        except errors.FileExists:
            return False
        else:
            return True

    def external_url(self):
        """Return a URL for self that can be given to an external process.

        There is no guarantee that the URL can be accessed from a different
        machine - e.g. file:/// urls are only usable on the local machine,
        sftp:/// urls when the server is only bound to localhost are only
        usable from localhost etc.

        NOTE: This method may remove security wrappers (e.g. on chroot
        transports) and thus should *only* be used when the result will not
        be used to obtain a new transport within bzrlib. Ideally chroot
        transports would know enough to cause the external url to be the exact
        one used that caused the chrooting in the first place, but that is not
        currently the case.

        :return: A URL that can be given to another process.
        :raises InProcessTransport: If the transport is one that cannot be
            accessed out of the current process (e.g. a MemoryTransport)
            then InProcessTransport is raised.
        """
        raise NotImplementedError(self.external_url)

    def _pump(self, from_file, to_file):
        """Most children will need to copy from one file-like 
        object or string to another one.
        This just gives them something easy to call.
        """
        assert not isinstance(from_file, basestring), \
            '_pump should only be called on files not %s' % (type(from_file,))
        osutils.pumpfile(from_file, to_file)

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
        result = []
        count = 0
        for entry in multi:
            self._update_pb(pb, msg, count, total)
            if expand:
                result.append(func(*entry))
            else:
                result.append(func(entry))
            count += 1
        return tuple(result)

    def abspath(self, relpath):
        """Return the full url to the given relative path.

        :param relpath: a string of a relative path
        """

        # XXX: Robert Collins 20051016 - is this really needed in the public
        # interface ?
        raise NotImplementedError(self.abspath)

    def _combine_paths(self, base_path, relpath):
        """Transform a Transport-relative path to a remote absolute path.

        This does not handle substitution of ~ but does handle '..' and '.'
        components.

        Examples::

            t._combine_paths('/home/sarah', 'project/foo')
                => '/home/sarah/project/foo'
            t._combine_paths('/home/sarah', '../../etc')
                => '/etc'
            t._combine_paths('/home/sarah', '/etc')
                => '/etc'

        :param base_path: urlencoded path for the transport root; typically a 
             URL but need not contain scheme/host/etc.
        :param relpath: relative url string for relative part of remote path.
        :return: urlencoded string for final path.
        """
        if not isinstance(relpath, str):
            raise errors.InvalidURL(relpath)
        if relpath.startswith('/'):
            base_parts = []
        else:
            base_parts = base_path.split('/')
        if len(base_parts) > 0 and base_parts[-1] == '':
            base_parts = base_parts[:-1]
        for p in relpath.split('/'):
            if p == '..':
                if len(base_parts) == 0:
                    # In most filesystems, a request for the parent
                    # of root, just returns root.
                    continue
                base_parts.pop()
            elif p == '.':
                continue # No-op
            elif p != '':
                base_parts.append(p)
        path = '/'.join(base_parts)
        if not path.startswith('/'):
            path = '/' + path
        return path

    def recommended_page_size(self):
        """Return the recommended page size for this transport.

        This is potentially different for every path in a given namespace.
        For example, local transports might use an operating system call to 
        get the block size for a given path, which can vary due to mount
        points.

        :return: The page size in bytes.
        """
        return 4 * 1024

    def relpath(self, abspath):
        """Return the local path portion from a given absolute path.

        This default implementation is not suitable for filesystems with
        aliasing, such as that given by symlinks, where a path may not 
        start with our base, but still be a relpath once aliasing is 
        resolved.
        """
        # TODO: This might want to use bzrlib.osutils.relpath
        #       but we have to watch out because of the prefix issues
        if not (abspath == self.base[:-1] or abspath.startswith(self.base)):
            raise errors.PathNotChild(abspath, self.base)
        pl = len(self.base)
        return abspath[pl:].strip('/')

    def local_abspath(self, relpath):
        """Return the absolute path on the local filesystem.

        This function will only be defined for Transports which have a
        physical local filesystem representation.
        """
        raise errors.NotLocalUrl(self.abspath(relpath))


    def has(self, relpath):
        """Does the file relpath exist?
        
        Note that some transports MAY allow querying on directories, but this
        is not part of the protocol.  In other words, the results of 
        t.has("a_directory_name") are undefined.

        :rtype: bool
        """
        raise NotImplementedError(self.has)

    def has_multi(self, relpaths, pb=None):
        """Return True/False for each entry in relpaths"""
        total = self._get_total(relpaths)
        count = 0
        for relpath in relpaths:
            self._update_pb(pb, 'has', count, total)
            yield self.has(relpath)
            count += 1

    def has_any(self, relpaths):
        """Return True if any of the paths exist."""
        for relpath in relpaths:
            if self.has(relpath):
                return True
        return False

    def iter_files_recursive(self):
        """Iter the relative paths of files in the transports sub-tree.

        *NOTE*: This only lists *files*, not subdirectories!
        
        As with other listing functions, only some transports implement this,.
        you may check via is_listable to determine if it will.
        """
        raise errors.TransportNotPossible("This transport has not "
                                          "implemented iter_files_recursive "
                                          "(but must claim to be listable "
                                          "to trigger this error).")

    def get(self, relpath):
        """Get the file at the given relative path.

        This may fail in a number of ways:
         - HTTP servers may return content for a directory. (unexpected
           content failure)
         - FTP servers may indicate NoSuchFile for a directory.
         - SFTP servers may give a file handle for a directory that will
           fail on read().

        For correct use of the interface, be sure to catch errors.PathError
        when calling it and catch errors.ReadError when reading from the
        returned object.

        :param relpath: The relative path to the file
        :rtype: File-like object.
        """
        raise NotImplementedError(self.get)

    def get_bytes(self, relpath):
        """Get a raw string of the bytes for a file at the given location.

        :param relpath: The relative path to the file
        """
        return self.get(relpath).read()

    def get_smart_client(self):
        """Return a smart client for this transport if possible.

        A smart client doesn't imply the presence of a smart server: it implies
        that the smart protocol can be tunnelled via this transport.

        :raises NoSmartServer: if no smart server client is available.
        """
        raise errors.NoSmartServer(self.base)

    def get_smart_medium(self):
        """Return a smart client medium for this transport if possible.

        A smart medium doesn't imply the presence of a smart server: it implies
        that the smart protocol can be tunnelled via this transport.

        :raises NoSmartMedium: if no smart server medium is available.
        """
        raise errors.NoSmartMedium(self)

    def get_shared_medium(self):
        """Return a smart client shared medium for this transport if possible.

        A smart medium doesn't imply the presence of a smart server: it implies
        that the smart protocol can be tunnelled via this transport.

        :raises NoSmartMedium: if no smart server medium is available.
        """
        raise errors.NoSmartMedium(self)

    def readv(self, relpath, offsets):
        """Get parts of the file at the given relative path.

        :offsets: A list of (offset, size) tuples.
        :return: A list or generator of (offset, data) tuples
        """
        if not offsets:
            return

        fp = self.get(relpath)
        return self._seek_and_read(fp, offsets, relpath)

    def _seek_and_read(self, fp, offsets, relpath='<unknown>'):
        """An implementation of readv that uses fp.seek and fp.read.

        This uses _coalesce_offsets to issue larger reads and fewer seeks.

        :param fp: A file-like object that supports seek() and read(size)
        :param offsets: A list of offsets to be read from the given file.
        :return: yield (pos, data) tuples for each request
        """
        # We are going to iterate multiple times, we need a list
        offsets = list(offsets)
        sorted_offsets = sorted(offsets)

        # turn the list of offsets into a stack
        offset_stack = iter(offsets)
        cur_offset_and_size = offset_stack.next()
        coalesced = self._coalesce_offsets(sorted_offsets,
                               limit=self._max_readv_combine,
                               fudge_factor=self._bytes_to_read_before_seek)

        # Cache the results, but only until they have been fulfilled
        data_map = {}
        for c_offset in coalesced:
            # TODO: jam 20060724 it might be faster to not issue seek if 
            #       we are already at the right location. This should be
            #       benchmarked.
            fp.seek(c_offset.start)
            data = fp.read(c_offset.length)
            if len(data) < c_offset.length:
                raise errors.ShortReadvError(relpath, c_offset.start,
                            c_offset.length, actual=len(data))
            for suboffset, subsize in c_offset.ranges:
                key = (c_offset.start+suboffset, subsize)
                data_map[key] = data[suboffset:suboffset+subsize]

            # Now that we've read some data, see if we can yield anything back
            while cur_offset_and_size in data_map:
                this_data = data_map.pop(cur_offset_and_size)
                yield cur_offset_and_size[0], this_data
                cur_offset_and_size = offset_stack.next()

    @staticmethod
    def _coalesce_offsets(offsets, limit, fudge_factor):
        """Yield coalesced offsets.

        With a long list of neighboring requests, combine them
        into a single large request, while retaining the original
        offsets.
        Turns  [(15, 10), (25, 10)] => [(15, 20, [(0, 10), (10, 10)])]

        :param offsets: A list of (start, length) pairs
        :param limit: Only combine a maximum of this many pairs
                      Some transports penalize multiple reads more than
                      others, and sometimes it is better to return early.
                      0 means no limit
        :param fudge_factor: All transports have some level of 'it is
                better to read some more data and throw it away rather 
                than seek', so collapse if we are 'close enough'
        :return: yield _CoalescedOffset objects, which have members for where
                to start, how much to read, and how to split those 
                chunks back up
        """
        last_end = None
        cur = _CoalescedOffset(None, None, [])

        for start, size in offsets:
            end = start + size
            if (last_end is not None 
                and start <= last_end + fudge_factor
                and start >= cur.start
                and (limit <= 0 or len(cur.ranges) < limit)):
                cur.length = end - cur.start
                cur.ranges.append((start-cur.start, size))
            else:
                if cur.start is not None:
                    yield cur
                cur = _CoalescedOffset(start, size, [(0, size)])
            last_end = end

        if cur.start is not None:
            yield cur

        return

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

    def put_bytes(self, relpath, bytes, mode=None):
        """Atomically put the supplied bytes into the given location.

        :param relpath: The location to put the contents, relative to the
            transport base.
        :param bytes: A bytestring of data.
        :param mode: Create the file with the given mode.
        :return: None
        """
        if not isinstance(bytes, str):
            raise AssertionError(
                'bytes must be a plain string, not %s' % type(bytes))
        return self.put_file(relpath, StringIO(bytes), mode=mode)

    def put_bytes_non_atomic(self, relpath, bytes, mode=None,
                             create_parent_dir=False,
                             dir_mode=None):
        """Copy the string into the target location.

        This function is not strictly safe to use. See 
        Transport.put_bytes_non_atomic for more information.

        :param relpath: The remote location to put the contents.
        :param bytes:   A string object containing the raw bytes to write into
                        the target file.
        :param mode:    Possible access permissions for new file.
                        None means do not set remote permissions.
        :param create_parent_dir: If we cannot create the target file because
                        the parent directory does not exist, go ahead and
                        create it, and then try again.
        :param dir_mode: Possible access permissions for new directories.
        """
        if not isinstance(bytes, str):
            raise AssertionError(
                'bytes must be a plain string, not %s' % type(bytes))
        self.put_file_non_atomic(relpath, StringIO(bytes), mode=mode,
                                 create_parent_dir=create_parent_dir,
                                 dir_mode=dir_mode)

    def put_file(self, relpath, f, mode=None):
        """Copy the file-like object into the location.

        :param relpath: Location to put the contents, relative to base.
        :param f:       File-like object.
        :param mode: The mode for the newly created file,
                     None means just use the default.
        """
        # We would like to mark this as NotImplemented, but most likely
        # transports have defined it in terms of the old api.
        symbol_versioning.warn('Transport %s should implement put_file,'
                               ' rather than implementing put() as of'
                               ' version 0.11.'
                               % (self.__class__.__name__,),
                               DeprecationWarning)
        return self.put(relpath, f, mode=mode)
        #raise NotImplementedError(self.put_file)

    def put_file_non_atomic(self, relpath, f, mode=None,
                            create_parent_dir=False,
                            dir_mode=None):
        """Copy the file-like object into the target location.

        This function is not strictly safe to use. It is only meant to
        be used when you already know that the target does not exist.
        It is not safe, because it will open and truncate the remote
        file. So there may be a time when the file has invalid contents.

        :param relpath: The remote location to put the contents.
        :param f:       File-like object.
        :param mode:    Possible access permissions for new file.
                        None means do not set remote permissions.
        :param create_parent_dir: If we cannot create the target file because
                        the parent directory does not exist, go ahead and
                        create it, and then try again.
        :param dir_mode: Possible access permissions for new directories.
        """
        # Default implementation just does an atomic put.
        try:
            return self.put_file(relpath, f, mode=mode)
        except errors.NoSuchFile:
            if not create_parent_dir:
                raise
            parent_dir = osutils.dirname(relpath)
            if parent_dir:
                self.mkdir(parent_dir, mode=dir_mode)
                return self.put_file(relpath, f, mode=mode)

    def mkdir(self, relpath, mode=None):
        """Create a directory at the given path."""
        raise NotImplementedError(self.mkdir)

    def mkdir_multi(self, relpaths, mode=None, pb=None):
        """Create a group of directories"""
        def mkdir(path):
            self.mkdir(path, mode=mode)
        return len(self._iterate_over(relpaths, mkdir, pb, 'mkdir', expand=False))

    def open_write_stream(self, relpath, mode=None):
        """Open a writable file stream at relpath.

        A file stream is a file like object with a write() method that accepts
        bytes to write.. Buffering may occur internally until the stream is
        closed with stream.close().  Calls to readv or the get_* methods will
        be synchronised with any internal buffering that may be present.

        :param relpath: The relative path to the file.
        :param mode: The mode for the newly created file, 
                     None means just use the default
        :return: A FileStream. FileStream objects have two methods, write() and
            close(). There is no guarantee that data is committed to the file
            if close() has not been called (even if get() is called on the same
            path).
        """
        raise NotImplementedError(self.open_write_stream)

    def append_file(self, relpath, f, mode=None):
        """Append bytes from a file-like object to a file at relpath.

        The file is created if it does not already exist.

        :param f: a file-like object of the bytes to append.
        :param mode: Unix mode for newly created files.  This is not used for
            existing files.

        :returns: the length of relpath before the content was written to it.
        """
        symbol_versioning.warn('Transport %s should implement append_file,'
                               ' rather than implementing append() as of'
                               ' version 0.11.'
                               % (self.__class__.__name__,),
                               DeprecationWarning)
        return self.append(relpath, f, mode=mode)

    def append_bytes(self, relpath, bytes, mode=None):
        """Append bytes to a file at relpath.

        The file is created if it does not already exist.

        :type f: str
        :param f: a string of the bytes to append.
        :param mode: Unix mode for newly created files.  This is not used for
            existing files.

        :returns: the length of relpath before the content was written to it.
        """
        assert isinstance(bytes, str), \
            'bytes must be a plain string, not %s' % type(bytes)
        return self.append_file(relpath, StringIO(bytes), mode=mode)

    def append_multi(self, files, pb=None):
        """Append the text in each file-like or string object to
        the supplied location.

        :param files: A set of (path, f) entries
        :param pb:  An optional ProgressBar for indicating percent done.
        """
        return self._iterate_over(files, self.append_file, pb, 'append', expand=True)

    def copy(self, rel_from, rel_to):
        """Copy the item at rel_from to the location at rel_to.
        
        Override this for efficiency if a specific transport can do it 
        faster than this default implementation.
        """
        self.put_file(rel_to, self.get(rel_from))

    def copy_multi(self, relpaths, pb=None):
        """Copy a bunch of entries.
        
        :param relpaths: A list of tuples of the form [(from, to), (from, to),...]
        """
        # This is the non-pipelined implementation, so that
        # implementors don't have to implement everything.
        return self._iterate_over(relpaths, self.copy, pb, 'copy', expand=True)

    def copy_to(self, relpaths, other, mode=None, pb=None):
        """Copy a set of entries from self into another Transport.

        :param relpaths: A list/generator of entries to be copied.
        :param mode: This is the target mode for the newly created files
        TODO: This interface needs to be updated so that the target location
              can be different from the source location.
        """
        # The dummy implementation just does a simple get + put
        def copy_entry(path):
            other.put_file(path, self.get(path), mode=mode)

        return len(self._iterate_over(relpaths, copy_entry, pb, 'copy_to', expand=False))

    def copy_tree(self, from_relpath, to_relpath):
        """Copy a subtree from one relpath to another.

        If a faster implementation is available, specific transports should 
        implement it.
        """
        source = self.clone(from_relpath)
        self.mkdir(to_relpath)
        target = self.clone(to_relpath)
        files = []
        directories = ['.']
        while directories:
            dir = directories.pop()
            if dir != '.':
                target.mkdir(dir)
            for path in source.list_dir(dir):
                path = dir + '/' + path
                stat = source.stat(path)
                if S_ISDIR(stat.st_mode):
                    directories.append(path)
                else:
                    files.append(path)
        source.copy_to(files, target)

    def rename(self, rel_from, rel_to):
        """Rename a file or directory.

        This *must* fail if the destination is a nonempty directory - it must
        not automatically remove it.  It should raise DirectoryNotEmpty, or
        some other PathError if the case can't be specifically detected.

        If the destination is an empty directory or a file this function may
        either fail or succeed, depending on the underlying transport.  It
        should not attempt to remove the destination if overwriting is not the
        native transport behaviour.  If at all possible the transport should
        ensure that the rename either completes or not, without leaving the
        destination deleted and the new file not moved in place.

        This is intended mainly for use in implementing LockDir.
        """
        # transports may need to override this
        raise NotImplementedError(self.rename)

    def move(self, rel_from, rel_to):
        """Move the item at rel_from to the location at rel_to.

        The destination is deleted if possible, even if it's a non-empty
        directory tree.
        
        If a transport can directly implement this it is suggested that
        it do so for efficiency.
        """
        if S_ISDIR(self.stat(rel_from).st_mode):
            self.copy_tree(rel_from, rel_to)
            self.delete_tree(rel_from)
        else:
            self.copy(rel_from, rel_to)
            self.delete(rel_from)

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
        raise NotImplementedError(self.move_multi_to)

    def delete(self, relpath):
        """Delete the item at relpath"""
        raise NotImplementedError(self.delete)

    def delete_multi(self, relpaths, pb=None):
        """Queue up a bunch of deletes to be done.
        """
        return self._iterate_over(relpaths, self.delete, pb, 'delete', expand=False)

    def delete_tree(self, relpath):
        """Delete an entire tree. This may require a listable transport."""
        subtree = self.clone(relpath)
        files = []
        directories = ['.']
        pending_rmdirs = []
        while directories:
            dir = directories.pop()
            if dir != '.':
                pending_rmdirs.append(dir)
            for path in subtree.list_dir(dir):
                path = dir + '/' + path
                stat = subtree.stat(path)
                if S_ISDIR(stat.st_mode):
                    directories.append(path)
                else:
                    files.append(path)
        subtree.delete_multi(files)
        pending_rmdirs.reverse()
        for dir in pending_rmdirs:
            subtree.rmdir(dir)
        self.rmdir(relpath)

    def __repr__(self):
        return "<%s.%s url=%s>" % (self.__module__, self.__class__.__name__, self.base)

    def stat(self, relpath):
        """Return the stat information for a file.
        WARNING: This may not be implementable for all protocols, so use
        sparingly.
        NOTE: This returns an object with fields such as 'st_size'. It MAY
        or MAY NOT return the literal result of an os.stat() call, so all
        access should be via named fields.
        ALSO NOTE: Stats of directories may not be supported on some 
        transports.
        """
        raise NotImplementedError(self.stat)

    def rmdir(self, relpath):
        """Remove a directory at the given path."""
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

    def listable(self):
        """Return True if this store supports listing."""
        raise NotImplementedError(self.listable)

    def list_dir(self, relpath):
        """Return a list of all files at the given location.
        WARNING: many transports do not support this, so trying avoid using
        it if at all possible.
        """
        raise errors.TransportNotPossible("Transport %r has not "
                                          "implemented list_dir "
                                          "(but must claim to be listable "
                                          "to trigger this error)."
                                          % (self))

    def lock_read(self, relpath):
        """Lock the given file for shared (read) access.

        WARNING: many transports do not support this, so trying avoid using it.
        These methods may be removed in the future.

        Transports may raise TransportNotPossible if OS-level locks cannot be
        taken over this transport.  

        :return: A lock object, which should contain an unlock() function.
        """
        raise errors.TransportNotPossible("transport locks not supported on %s" % self)

    def lock_write(self, relpath):
        """Lock the given file for exclusive (write) access.

        WARNING: many transports do not support this, so trying avoid using it.
        These methods may be removed in the future.

        Transports may raise TransportNotPossible if OS-level locks cannot be
        taken over this transport.

        :return: A lock object, which should contain an unlock() function.
        """
        raise errors.TransportNotPossible("transport locks not supported on %s" % self)

    def is_readonly(self):
        """Return true if this connection cannot be written to."""
        return False

    def _can_roundtrip_unix_modebits(self):
        """Return true if this transport can store and retrieve unix modebits.

        (For example, 0700 to make a directory owner-private.)
        
        Note: most callers will not want to switch on this, but should rather 
        just try and set permissions and let them be either stored or not.
        This is intended mainly for the use of the test suite.
        
        Warning: this is not guaranteed to be accurate as sometimes we can't 
        be sure: for example with vfat mounted on unix, or a windows sftp
        server."""
        # TODO: Perhaps return a e.g. TransportCharacteristics that can answer
        # several questions about the transport.
        return False

    def _reuse_for(self, other_base):
        # This is really needed for ConnectedTransport only, but it's easier to
        # have Transport refuses to be reused than testing that the reuse
        # should be asked to ConnectedTransport only.
        return None


class _SharedConnection(object):
    """A connection shared between several transports."""

    def __init__(self, connection=None, credentials=None):
        """Constructor.

        :param connection: An opaque object specific to each transport.

        :param credentials: An opaque object containing the credentials used to
            create the connection.
        """
        self.connection = connection
        self.credentials = credentials


class ConnectedTransport(Transport):
    """A transport connected to a remote server.

    This class provide the basis to implement transports that need to connect
    to a remote server.

    Host and credentials are available as private attributes, cloning preserves
    them and share the underlying, protocol specific, connection.
    """

    def __init__(self, base, _from_transport=None):
        """Constructor.

        The caller should ensure that _from_transport points at the same host
        as the new base.

        :param base: transport root URL

        :param _from_transport: optional transport to build from. The built
            transport will share the connection with this transport.
        """
        if not base.endswith('/'):
            base += '/'
        (self._scheme,
         self._user, self._password,
         self._host, self._port,
         self._path) = self._split_url(base)
        if _from_transport is not None:
            # Copy the password as it does not appear in base and will be lost
            # otherwise. It can appear in the _split_url above if the user
            # provided it on the command line. Otherwise, daughter classes will
            # prompt the user for one when appropriate.
            self._password = _from_transport._password

        base = self._unsplit_url(self._scheme,
                                 self._user, self._password,
                                 self._host, self._port,
                                 self._path)

        super(ConnectedTransport, self).__init__(base)
        if _from_transport is None:
            self._shared_connection = _SharedConnection()
        else:
            self._shared_connection = _from_transport._shared_connection

    def clone(self, offset=None):
        """Return a new transport with root at self.base + offset

        We leave the daughter classes take advantage of the hint
        that it's a cloning not a raw creation.
        """
        if offset is None:
            return self.__class__(self.base, _from_transport=self)
        else:
            return self.__class__(self.abspath(offset), _from_transport=self)

    @staticmethod
    def _split_url(url):
        """
        Extract the server address, the credentials and the path from the url.

        user, password, host and path should be quoted if they contain reserved
        chars.

        :param url: an quoted url

        :return: (scheme, user, password, host, port, path) tuple, all fields
            are unquoted.
        """
        if isinstance(url, unicode):
            raise errors.InvalidURL('should be ascii:\n%r' % url)
        url = url.encode('utf-8')
        (scheme, netloc, path, params,
         query, fragment) = urlparse.urlparse(url, allow_fragments=False)
        user = password = host = port = None
        if '@' in netloc:
            user, host = netloc.split('@', 1)
            if ':' in user:
                user, password = user.split(':', 1)
                password = urllib.unquote(password)
            user = urllib.unquote(user)
        else:
            host = netloc

        if ':' in host:
            host, port = host.rsplit(':', 1)
            try:
                port = int(port)
            except ValueError:
                raise errors.InvalidURL('invalid port number %s in url:\n%s' %
                                        (port, url))
        host = urllib.unquote(host)
        path = urllib.unquote(path)

        return (scheme, user, password, host, port, path)

    @staticmethod
    def _unsplit_url(scheme, user, password, host, port, path):
        """
        Build the full URL for the given already URL encoded path.

        user, password, host and path will be quoted if they contain reserved
        chars.

        :param scheme: protocol

        :param user: login

        :param password: associated password

        :param host: the server address

        :param port: the associated port

        :param path: the absolute path on the server

        :return: The corresponding URL.
        """
        netloc = urllib.quote(host)
        if user is not None:
            # Note that we don't put the password back even if we
            # have one so that it doesn't get accidentally
            # exposed.
            netloc = '%s@%s' % (urllib.quote(user), netloc)
        if port is not None:
            netloc = '%s:%d' % (netloc, port)
        path = urllib.quote(path)
        return urlparse.urlunparse((scheme, netloc, path, None, None, None))

    def relpath(self, abspath):
        """Return the local path portion from a given absolute path"""
        scheme, user, password, host, port, path = self._split_url(abspath)
        error = []
        if (scheme != self._scheme):
            error.append('scheme mismatch')
        if (user != self._user):
            error.append('user name mismatch')
        if (host != self._host):
            error.append('host mismatch')
        if (port != self._port):
            error.append('port mismatch')
        if not (path == self._path[:-1] or path.startswith(self._path)):
            error.append('path mismatch')
        if error:
            extra = ', '.join(error)
            raise errors.PathNotChild(abspath, self.base, extra=extra)
        pl = len(self._path)
        return path[pl:].strip('/')

    def abspath(self, relpath):
        """Return the full url to the given relative path.
        
        :param relpath: the relative path urlencoded

        :returns: the Unicode version of the absolute path for relpath.
        """
        relative = urlutils.unescape(relpath).encode('utf-8')
        path = self._combine_paths(self._path, relative)
        return self._unsplit_url(self._scheme, self._user, self._password,
                                 self._host, self._port,
                                 path)

    def _remote_path(self, relpath):
        """Return the absolute path part of the url to the given relative path.

        This is the path that the remote server expect to receive in the
        requests, daughter classes should redefine this method if needed and
        use the result to build their requests.

        :param relpath: the path relative to the transport base urlencoded.

        :return: the absolute Unicode path on the server,
        """
        relative = urlutils.unescape(relpath).encode('utf-8')
        remote_path = self._combine_paths(self._path, relative)
        return remote_path

    def _get_shared_connection(self):
        """Get the object shared amongst cloned transports.

        This should be used only by classes that needs to extend the sharing
        with other objects than tramsports.

        Use _get_connection to get the connection itself.
        """
        return self._shared_connection

    def _set_connection(self, connection, credentials=None):
        """Record a newly created connection with its associated credentials.

        Note: To ensure that connection is still shared after a temporary
        failure and a new one needs to be created, daughter classes should
        always call this method to set the connection and do so each time a new
        connection is created.

        :param connection: An opaque object representing the connection used by
            the daughter class.

        :param credentials: An opaque object representing the credentials
            needed to create the connection.
        """
        self._shared_connection.connection = connection
        self._shared_connection.credentials = credentials

    def _get_connection(self):
        """Returns the transport specific connection object."""
        return self._shared_connection.connection

    def _get_credentials(self):
        """Returns the credentials used to establish the connection."""
        return self._shared_connection.credentials

    def _update_credentials(self, credentials):
        """Update the credentials of the current connection.

        Some protocols can renegociate the credentials within a connection,
        this method allows daughter classes to share updated credentials.
        
        :param credentials: the updated credentials.
        """
        # We don't want to call _set_connection here as we are only updating
        # the credentials not creating a new connection.
        self._shared_connection.credentials = credentials

    def _reuse_for(self, other_base):
        """Returns a transport sharing the same connection if possible.

        Note: we share the connection if the expected credentials are the
        same: (host, port, user). Some protocols may disagree and redefine the
        criteria in daughter classes.

        Note: we don't compare the passwords here because other_base may have
        been obtained from an existing transport.base which do not mention the
        password.

        :param other_base: the URL we want to share the connection with.

        :return: A new transport or None if the connection cannot be shared.
        """
        (scheme, user, password, host, port, path) = self._split_url(other_base)
        transport = None
        # Don't compare passwords, they may be absent from other_base or from
        # self and they don't carry more information than user anyway.
        if (scheme == self._scheme
            and user == self._user
            and host == self._host
            and port == self._port):
            if not path.endswith('/'):
                # This normally occurs at __init__ time, but it's easier to do
                # it now to avoid creating two transports for the same base.
                path += '/'
            if self._path  == path:
                # shortcut, it's really the same transport
                return self
            # We don't call clone here because the intent is different: we
            # build a new transport on a different base (which may be totally
            # unrelated) but we share the connection.
            transport = self.__class__(other_base, _from_transport=self)
        return transport


@deprecated_function(zero_ninety)
def urlescape(relpath):
    urlutils.escape(relpath)


@deprecated_function(zero_ninety)
def urlunescape(url):
    urlutils.unescape(url)

# We try to recognize an url lazily (ignoring user, password, etc)
_urlRE = re.compile(r'^(?P<proto>[^:/\\]+)://(?P<rest>.*)$')

def get_transport(base, possible_transports=None):
    """Open a transport to access a URL or directory.

    :param base: either a URL or a directory name.

    :param transports: optional reusable transports list. If not None, created
        transports will be added to the list.

    :return: A new transport optionally sharing its connection with one of
        possible_transports.
    """
    if base is None:
        base = '.'
    last_err = None

    def convert_path_to_url(base, error_str):
        m = _urlRE.match(base)
        if m:
            # This looks like a URL, but we weren't able to 
            # instantiate it as such raise an appropriate error
            # FIXME: we have a 'error_str' unused and we use last_err below
            raise errors.UnsupportedProtocol(base, last_err)
        # This doesn't look like a protocol, consider it a local path
        new_base = urlutils.local_path_to_url(base)
        # mutter('converting os path %r => url %s', base, new_base)
        return new_base

    # Catch any URLs which are passing Unicode rather than ASCII
    try:
        base = base.encode('ascii')
    except UnicodeError:
        # Only local paths can be Unicode
        base = convert_path_to_url(base,
            'URLs must be properly escaped (protocol: %s)')

    transport = None
    if possible_transports is not None:
        for t in possible_transports:
            t_same_connection = t._reuse_for(base)
            if t_same_connection is not None:
                # Add only new transports
                if t_same_connection not in possible_transports:
                    possible_transports.append(t_same_connection)
                return t_same_connection

    for proto, factory_list in transport_list_registry.iteritems():
        if proto is not None and base.startswith(proto):
            transport, last_err = _try_transport_factories(base, factory_list)
            if transport:
                if possible_transports is not None:
                    assert transport not in possible_transports
                    possible_transports.append(transport)
                return transport

    # We tried all the different protocols, now try one last time
    # as a local protocol
    base = convert_path_to_url(base, 'Unsupported protocol: %s')

    # The default handler is the filesystem handler, stored as protocol None
    factory_list = transport_list_registry.get(None)
    transport, last_err = _try_transport_factories(base, factory_list)

    return transport


def _try_transport_factories(base, factory_list):
    last_err = None
    for factory in factory_list:
        try:
            return factory.get_obj()(base), None
        except errors.DependencyNotPresent, e:
            mutter("failed to instantiate transport %r for %r: %r" %
                    (factory, base, e))
            last_err = e
            continue
    return None, last_err


def do_catching_redirections(action, transport, redirected):
    """Execute an action with given transport catching redirections.

    This is a facility provided for callers needing to follow redirections
    silently. The silence is relative: it is the caller responsability to
    inform the user about each redirection or only inform the user of a user
    via the exception parameter.

    :param action: A callable, what the caller want to do while catching
                  redirections.
    :param transport: The initial transport used.
    :param redirected: A callable receiving the redirected transport and the 
                  RedirectRequested exception.

    :return: Whatever 'action' returns
    """
    MAX_REDIRECTIONS = 8

    # If a loop occurs, there is little we can do. So we don't try to detect
    # them, just getting out if too much redirections occurs. The solution
    # is outside: where the loop is defined.
    for redirections in range(MAX_REDIRECTIONS):
        try:
            return action(transport)
        except errors.RedirectRequested, e:
            redirection_notice = '%s is%s redirected to %s' % (
                e.source, e.permanently, e.target)
            transport = redirected(transport, e, redirection_notice)
    else:
        # Loop exited without resolving redirect ? Either the
        # user has kept a very very very old reference or a loop
        # occurred in the redirections.  Nothing we can cure here:
        # tell the user. Note that as the user has been informed
        # about each redirection (it is the caller responsibility
        # to do that in redirected via the provided
        # redirection_notice). The caller may provide more
        # information if needed (like what file or directory we
        # were trying to act upon when the redirection loop
        # occurred).
        raise errors.TooManyRedirections


class Server(object):
    """A Transport Server.
    
    The Server interface provides a server for a given transport. We use
    these servers as loopback testing tools. For any given transport the
    Servers it provides must either allow writing, or serve the contents
    of os.getcwdu() at the time setUp is called.
    
    Note that these are real servers - they must implement all the things
    that we want bzr transports to take advantage of.
    """

    def setUp(self):
        """Setup the server to service requests."""

    def tearDown(self):
        """Remove the server and cleanup any resources it owns."""

    def get_url(self):
        """Return a url for this server.
        
        If the transport does not represent a disk directory (i.e. it is 
        a database like svn, or a memory only transport, it should return
        a connection to a newly established resource for this Server.
        Otherwise it should return a url that will provide access to the path
        that was os.getcwdu() when setUp() was called.
        
        Subsequent calls will return the same resource.
        """
        raise NotImplementedError

    def get_bogus_url(self):
        """Return a url for this protocol, that will fail to connect.
        
        This may raise NotImplementedError to indicate that this server cannot
        provide bogus urls.
        """
        raise NotImplementedError


class TransportLogger(object):
    """Adapt a transport to get clear logging data on api calls.
    
    Feel free to extend to log whatever calls are of interest.
    """

    def __init__(self, adapted):
        self._adapted = adapted
        self._calls = []

    def get(self, name):
        self._calls.append((name,))
        return self._adapted.get(name)

    def __getattr__(self, name):
        """Thunk all undefined access through to self._adapted."""
        # raise AttributeError, name 
        return getattr(self._adapted, name)

    def readv(self, name, offsets):
        self._calls.append((name, offsets))
        return self._adapted.readv(name, offsets)


# None is the default transport, for things with no url scheme
register_transport_proto('file://',
            help="Access using the standard filesystem (default)")
register_lazy_transport('file://', 'bzrlib.transport.local', 'LocalTransport')
transport_list_registry.set_default_transport("file://")

register_transport_proto('sftp://',
            help="Access using SFTP (most SSH servers provide SFTP).")
register_lazy_transport('sftp://', 'bzrlib.transport.sftp', 'SFTPTransport')
# Decorated http transport
register_transport_proto('http+urllib://',
#                help="Read-only access of branches exported on the web."
            )
register_lazy_transport('http+urllib://', 'bzrlib.transport.http._urllib',
                        'HttpTransport_urllib')
register_transport_proto('https+urllib://',
#                help="Read-only access of branches exported on the web using SSL."
            )
register_lazy_transport('https+urllib://', 'bzrlib.transport.http._urllib',
                        'HttpTransport_urllib')
register_transport_proto('http+pycurl://',
#                help="Read-only access of branches exported on the web."
            )
register_lazy_transport('http+pycurl://', 'bzrlib.transport.http._pycurl',
                        'PyCurlTransport')
register_transport_proto('https+pycurl://',
#                help="Read-only access of branches exported on the web using SSL."
            )
register_lazy_transport('https+pycurl://', 'bzrlib.transport.http._pycurl',
                        'PyCurlTransport')
# Default http transports (last declared wins (if it can be imported))
register_transport_proto('http://',
            help="Read-only access of branches exported on the web.")
register_transport_proto('https://',
            help="Read-only access of branches exported on the web using SSL.")
register_lazy_transport('http://', 'bzrlib.transport.http._urllib',
                        'HttpTransport_urllib')
register_lazy_transport('https://', 'bzrlib.transport.http._urllib',
                        'HttpTransport_urllib')
register_lazy_transport('http://', 'bzrlib.transport.http._pycurl', 'PyCurlTransport')
register_lazy_transport('https://', 'bzrlib.transport.http._pycurl', 'PyCurlTransport')

register_transport_proto('ftp://',
            help="Access using passive FTP.")
register_lazy_transport('ftp://', 'bzrlib.transport.ftp', 'FtpTransport')
register_transport_proto('aftp://',
            help="Access using active FTP.")
register_lazy_transport('aftp://', 'bzrlib.transport.ftp', 'FtpTransport')

register_transport_proto('memory://')
register_lazy_transport('memory://', 'bzrlib.transport.memory', 'MemoryTransport')
register_transport_proto('chroot+')

register_transport_proto('readonly+',
#              help="This modifier converts any transport to be readonly."
            )
register_lazy_transport('readonly+', 'bzrlib.transport.readonly', 'ReadonlyTransportDecorator')

register_transport_proto('fakenfs+')
register_lazy_transport('fakenfs+', 'bzrlib.transport.fakenfs', 'FakeNFSTransportDecorator')

register_transport_proto('unlistable+')
register_lazy_transport('unlistable+', 'bzrlib.transport.unlistable', 'UnlistableTransportDecorator')

register_transport_proto('brokenrename+')
register_lazy_transport('brokenrename+', 'bzrlib.transport.brokenrename',
        'BrokenRenameTransportDecorator')

register_transport_proto('vfat+')
register_lazy_transport('vfat+',
                        'bzrlib.transport.fakevfat',
                        'FakeVFATTransportDecorator')
register_transport_proto('bzr://',
            help="Fast access using the Bazaar smart server.")

register_lazy_transport('bzr://',
                        'bzrlib.transport.remote',
                        'RemoteTCPTransport')
register_transport_proto('bzr+http://',
#                help="Fast access using the Bazaar smart server over HTTP."
             )
register_lazy_transport('bzr+http://',
                        'bzrlib.transport.remote',
                        'RemoteHTTPTransport')
register_transport_proto('bzr+ssh://',
            help="Fast access using the Bazaar smart server over SSH.")
register_lazy_transport('bzr+ssh://',
                        'bzrlib.transport.remote',
                        'RemoteSSHTransport')
