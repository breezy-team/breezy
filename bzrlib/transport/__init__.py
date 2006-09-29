# Copyright (C) 2005, 2006 Canonical Ltd
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

import errno
from collections import deque
from copy import deepcopy
from cStringIO import StringIO
import re
from stat import S_ISDIR
import sys
from unittest import TestSuite
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
from bzrlib.errors import DependencyNotPresent
from bzrlib.osutils import pumpfile
from bzrlib.symbol_versioning import (
        deprecated_passed,
        deprecated_method,
        deprecated_function,
        DEPRECATED_PARAMETER,
        zero_eight,
        zero_eleven,
        )
from bzrlib.trace import mutter, warning

# {prefix: [transport_classes]}
# Transports are inserted onto the list LIFO and tried in order; as a result
# transports provided by plugins are tried first, which is usually what we
# want.
_protocol_handlers = {
}

def register_transport(prefix, klass, override=DEPRECATED_PARAMETER):
    """Register a transport that can be used to open URLs

    Normally you should use register_lazy_transport, which defers loading the
    implementation until it's actually used, and so avoids pulling in possibly
    large implementation libraries.
    """
    # Note that this code runs very early in library setup -- trace may not be
    # working, etc.
    global _protocol_handlers
    if deprecated_passed(override):
        warnings.warn("register_transport(override) is deprecated")
    _protocol_handlers.setdefault(prefix, []).insert(0, klass)


def register_lazy_transport(scheme, module, classname):
    """Register lazy-loaded transport class.

    When opening a URL with the given scheme, load the module and then
    instantiate the particular class.  

    If the module raises DependencyNotPresent when it's imported, it is
    skipped and another implementation of the protocol is tried.  This is
    intended to be used when the implementation depends on an external
    implementation that may not be present.  If any other error is raised, it
    propagates up and the attempt to open the url fails.
    """
    # TODO: If no implementation of a protocol is available because of missing
    # dependencies, we should perhaps show the message about what dependency
    # was missing.
    def _loader(base):
        mod = __import__(module, globals(), locals(), [classname])
        klass = getattr(mod, classname)
        return klass(base)
    _loader.module = module
    register_transport(scheme, _loader)


def _get_protocol_handlers():
    """Return a dictionary of {urlprefix: [factory]}"""
    return _protocol_handlers


def _set_protocol_handlers(new_handlers):
    """Replace the current protocol handlers dictionary.

    WARNING this will remove all build in protocols. Use with care.
    """
    global _protocol_handlers
    _protocol_handlers = new_handlers


def _clear_protocol_handlers():
    global _protocol_handlers
    _protocol_handlers = {}


def _get_transport_modules():
    """Return a list of the modules providing transports."""
    modules = set()
    for prefix, factory_list in _protocol_handlers.items():
        for factory in factory_list:
            if factory.__module__ == "bzrlib.transport":
                # this is a lazy load transport, because no real ones
                # are directlry in bzrlib.transport
                modules.add(factory.module)
            else:
                modules.add(factory.__module__)
    result = list(modules)
    result.sort()
    return result


def register_urlparse_netloc_protocol(protocol):
    """Ensure that protocol is setup to be used with urlparse netloc parsing."""
    if protocol not in urlparse.uses_netloc:
        urlparse.uses_netloc.append(protocol)


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

    def read(self, count=-1):
        """Raise ReadError."""
        raise errors.ReadError(self._path)


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

    def should_cache(self):
        """Return True if the data pulled across should be cached locally.
        """
        return False

    def _pump(self, from_file, to_file):
        """Most children will need to copy from one file-like 
        object or string to another one.
        This just gives them something easy to call.
        """
        assert not isinstance(from_file, basestring), \
            '_pump should only be called on files not %s' % (type(from_file,))
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

            >>> t = Transport('/')
            >>> t._combine_paths('/home/sarah', 'project/foo')
            '/home/sarah/project/foo'
            >>> t._combine_paths('/home/sarah', '../../etc')
            '/etc'

        :param base_path: urlencoded path for the transport root; typically a 
             URL but need not contain scheme/host/etc.
        :param relpath: relative url string for relative part of remote path.
        :return: urlencoded string for final path.
        """
        # FIXME: share the common code across more transports; variants of
        # this likely occur in http and sftp too.
        #
        # TODO: Also need to consider handling of ~, which might vary between
        # transports?
        if not isinstance(relpath, str):
            raise errors.InvalidURL("not a valid url: %r" % relpath)
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
        return path

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
        # TODO: jam 20060426 Should this raise NotLocalUrl instead?
        raise errors.TransportNotPossible('This is not a LocalTransport,'
            ' so there is no local representation for a path')

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

        :raises NoSmartServer: if no smart server client is available.
        """
        raise errors.NoSmartServer(self.base)

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
        :return: yield _CoalescedOffset objects, which have members for wher
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

    @deprecated_method(zero_eleven)
    def put(self, relpath, f, mode=None):
        """Copy the file-like object into the location.

        :param relpath: Location to put the contents, relative to base.
        :param f:       File-like object.
        :param mode: The mode for the newly created file, 
                     None means just use the default
        """
        if isinstance(f, str):
            return self.put_bytes(relpath, f, mode=mode)
        else:
            return self.put_file(relpath, f, mode=mode)

    def put_bytes(self, relpath, bytes, mode=None):
        """Atomically put the supplied bytes into the given location.

        :param relpath: The location to put the contents, relative to the
            transport base.
        :param bytes: A bytestring of data.
        :param mode: Create the file with the given mode.
        :return: None
        """
        assert isinstance(bytes, str), \
            'bytes must be a plain string, not %s' % type(bytes)
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
        assert isinstance(bytes, str), \
            'bytes must be a plain string, not %s' % type(bytes)
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

    @deprecated_method(zero_eleven)
    def put_multi(self, files, mode=None, pb=None):
        """Put a set of files into the location.

        :param files: A list of tuples of relpath, file object [(path1, file1), (path2, file2),...]
        :param pb:  An optional ProgressBar for indicating percent done.
        :param mode: The mode for the newly created files
        :return: The number of files copied.
        """
        def _put(path, f):
            if isinstance(f, str):
                self.put_bytes(path, f, mode=mode)
            else:
                self.put_file(path, f, mode=mode)
        return len(self._iterate_over(files, _put, pb, 'put', expand=True))

    def mkdir(self, relpath, mode=None):
        """Create a directory at the given path."""
        raise NotImplementedError(self.mkdir)

    def mkdir_multi(self, relpaths, mode=None, pb=None):
        """Create a group of directories"""
        def mkdir(path):
            self.mkdir(path, mode=mode)
        return len(self._iterate_over(relpaths, mkdir, pb, 'mkdir', expand=False))

    @deprecated_method(zero_eleven)
    def append(self, relpath, f, mode=None):
        """Append the text in the file-like object to the supplied location.

        returns the length of relpath before the content was written to it.
        
        If the file does not exist, it is created with the supplied mode.
        """
        return self.append_file(relpath, f, mode=mode)

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


# jam 20060426 For compatibility we copy the functions here
# TODO: The should be marked as deprecated
urlescape = urlutils.escape
urlunescape = urlutils.unescape
_urlRE = re.compile(r'^(?P<proto>[^:/\\]+)://(?P<path>.*)$')


def get_transport(base):
    """Open a transport to access a URL or directory.

    base is either a URL or a directory name.  
    """
    # TODO: give a better error if base looks like a url but there's no
    # handler for the scheme?
    global _protocol_handlers
    if base is None:
        base = '.'

    last_err = None

    def convert_path_to_url(base, error_str):
        m = _urlRE.match(base)
        if m:
            # This looks like a URL, but we weren't able to 
            # instantiate it as such raise an appropriate error
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
    
    for proto, factory_list in _protocol_handlers.iteritems():
        if proto is not None and base.startswith(proto):
            t, last_err = _try_transport_factories(base, factory_list)
            if t:
                return t

    # We tried all the different protocols, now try one last time
    # as a local protocol
    base = convert_path_to_url(base, 'Unsupported protocol: %s')

    # The default handler is the filesystem handler, stored as protocol None
    return _try_transport_factories(base, _protocol_handlers[None])[0]


def _try_transport_factories(base, factory_list):
    last_err = None
    for factory in factory_list:
        try:
            return factory(base), None
        except DependencyNotPresent, e:
            mutter("failed to instantiate transport %r for %r: %r" %
                    (factory, base, e))
            last_err = e
            continue
    return None, last_err


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
        """Return a url for this protocol, that will fail to connect."""
        raise NotImplementedError


class TransportTestProviderAdapter(object):
    """A tool to generate a suite testing all transports for a single test.

    This is done by copying the test once for each transport and injecting
    the transport_class and transport_server classes into each copy. Each copy
    is also given a new id() to make it easy to identify.
    """

    def adapt(self, test):
        result = TestSuite()
        for klass, server_factory in self._test_permutations():
            new_test = deepcopy(test)
            new_test.transport_class = klass
            new_test.transport_server = server_factory
            def make_new_test_id():
                new_id = "%s(%s)" % (new_test.id(), server_factory.__name__)
                return lambda: new_id
            new_test.id = make_new_test_id()
            result.addTest(new_test)
        return result

    def get_transport_test_permutations(self, module):
        """Get the permutations module wants to have tested."""
        if getattr(module, 'get_test_permutations', None) is None:
            warning("transport module %s doesn't provide get_test_permutations()"
                    % module.__name__)
            return []
        return module.get_test_permutations()

    def _test_permutations(self):
        """Return a list of the klass, server_factory pairs to test."""
        result = []
        for module in _get_transport_modules():
            try:
                result.extend(self.get_transport_test_permutations(reduce(getattr, 
                    (module).split('.')[1:],
                     __import__(module))))
            except errors.DependencyNotPresent, e:
                # Continue even if a dependency prevents us 
                # from running this test
                pass
        return result


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
register_lazy_transport(None, 'bzrlib.transport.local', 'LocalTransport')
register_lazy_transport('file://', 'bzrlib.transport.local', 'LocalTransport')
register_lazy_transport('sftp://', 'bzrlib.transport.sftp', 'SFTPTransport')
register_lazy_transport('http+urllib://', 'bzrlib.transport.http._urllib',
                        'HttpTransport_urllib')
register_lazy_transport('https+urllib://', 'bzrlib.transport.http._urllib',
                        'HttpTransport_urllib')
register_lazy_transport('http+pycurl://', 'bzrlib.transport.http._pycurl',
                        'PyCurlTransport')
register_lazy_transport('https+pycurl://', 'bzrlib.transport.http._pycurl',
                        'PyCurlTransport')
register_lazy_transport('http://', 'bzrlib.transport.http._urllib',
                        'HttpTransport_urllib')
register_lazy_transport('https://', 'bzrlib.transport.http._urllib',
                        'HttpTransport_urllib')
register_lazy_transport('http://', 'bzrlib.transport.http._pycurl', 'PyCurlTransport')
register_lazy_transport('https://', 'bzrlib.transport.http._pycurl', 'PyCurlTransport')
register_lazy_transport('ftp://', 'bzrlib.transport.ftp', 'FtpTransport')
register_lazy_transport('aftp://', 'bzrlib.transport.ftp', 'FtpTransport')
register_lazy_transport('memory://', 'bzrlib.transport.memory', 'MemoryTransport')
register_lazy_transport('readonly+', 'bzrlib.transport.readonly', 'ReadonlyTransportDecorator')
register_lazy_transport('fakenfs+', 'bzrlib.transport.fakenfs', 'FakeNFSTransportDecorator')
register_lazy_transport('vfat+',
                        'bzrlib.transport.fakevfat',
                        'FakeVFATTransportDecorator')
register_lazy_transport('bzr://',
                        'bzrlib.transport.smart',
                        'SmartTCPTransport')
register_lazy_transport('bzr+ssh://',
                        'bzrlib.transport.smart',
                        'SmartSSHTransport')
