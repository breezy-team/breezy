# Copyright (C) 2005, 2006 Canonical Ltd

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
from stat import *
import sys
from unittest import TestSuite
import urllib

from bzrlib.trace import mutter, warning
import bzrlib.errors as errors
from bzrlib.errors import DependencyNotPresent
from bzrlib.symbol_versioning import *

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
        warn("register_transport(override) is deprecated")
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

    def _translate_error(self, e, path, raise_generic=True):
        """Translate an IOError or OSError into an appropriate bzr error.

        This handles things like ENOENT, ENOTDIR, EEXIST, and EACCESS
        """
        if hasattr(e, 'errno'):
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
        This can be supplied with a string or a list

        XXX: Robert Collins 20051016 - is this really needed in the public
             interface ?
        """
        raise NotImplementedError(self.abspath)

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

    def has(self, relpath):
        """Does the file relpath exist?
        
        Note that some transports MAY allow querying on directories, but this
        is not part of the protocol.  In other words, the results of 
        t.has("a_directory_name") are undefined."
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

        :param relpath: The relative path to the file
        """
        raise NotImplementedError(self.get)

    def readv(self, relpath, offsets):
        """Get parts of the file at the given relative path.

        :offsets: A list of (offset, size) tuples.
        :return: A list or generator of (offset, data) tuples
        """
        def do_combined_read(combined_offsets):
            total_size = 0
            for offset, size in combined_offsets:
                total_size += size
            mutter('readv coalesced %d reads.', len(combined_offsets))
            offset = combined_offsets[0][0]
            fp.seek(offset)
            data = fp.read(total_size)
            pos = 0
            for offset, size in combined_offsets:
                yield offset, data[pos:pos + size]
                pos += size

        if not len(offsets):
            return
        fp = self.get(relpath)
        pending_offsets = deque(offsets)
        combined_offsets = []
        while len(pending_offsets):
            offset, size = pending_offsets.popleft()
            if not combined_offsets:
                combined_offsets = [[offset, size]]
            else:
                if (len (combined_offsets) < 50 and
                    combined_offsets[-1][0] + combined_offsets[-1][1] == offset):
                    # combatible offset:
                    combined_offsets.append([offset, size])
                else:
                    # incompatible, or over the threshold issue a read and yield
                    pending_offsets.appendleft((offset, size))
                    for result in do_combined_read(combined_offsets):
                        yield result
                    combined_offsets = []
        # whatever is left is a single coalesced request
        if len(combined_offsets):
            for result in do_combined_read(combined_offsets):
                yield result

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

    def put(self, relpath, f, mode=None):
        """Copy the file-like or string object into the location.

        :param relpath: Location to put the contents, relative to base.
        :param f:       File-like or string object.
        :param mode: The mode for the newly created file, 
                     None means just use the default
        """
        raise NotImplementedError(self.put)

    def put_multi(self, files, mode=None, pb=None):
        """Put a set of files into the location.

        :param files: A list of tuples of relpath, file object [(path1, file1), (path2, file2),...]
        :param pb:  An optional ProgressBar for indicating percent done.
        :param mode: The mode for the newly created files
        :return: The number of files copied.
        """
        def put(path, f):
            self.put(path, f, mode=mode)
        return len(self._iterate_over(files, put, pb, 'put', expand=True))

    def mkdir(self, relpath, mode=None):
        """Create a directory at the given path."""
        raise NotImplementedError(self.mkdir)

    def mkdir_multi(self, relpaths, mode=None, pb=None):
        """Create a group of directories"""
        def mkdir(path):
            self.mkdir(path, mode=mode)
        return len(self._iterate_over(relpaths, mkdir, pb, 'mkdir', expand=False))

    def append(self, relpath, f):
        """Append the text in the file-like or string object to 
        the supplied location.

        returns the length of f before the content was written to it.
        """
        raise NotImplementedError(self.append)

    def append_multi(self, files, pb=None):
        """Append the text in each file-like or string object to
        the supplied location.

        :param files: A set of (path, f) entries
        :param pb:  An optional ProgressBar for indicating percent done.
        """
        return self._iterate_over(files, self.append, pb, 'append', expand=True)

    def copy(self, rel_from, rel_to):
        """Copy the item at rel_from to the location at rel_to.
        
        Override this for efficiency if a specific transport can do it 
        faster than this default implementation.
        """
        self.put(rel_to, self.get(rel_from))

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
            other.put(path, self.get(path), mode=mode)

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
        raise errors.TransportNotPossible("This transport has not "
                                          "implemented list_dir "
                                          "(but must claim to be listable "
                                          "to trigger this error).")

    def lock_read(self, relpath):
        """Lock the given file for shared (read) access.
        WARNING: many transports do not support this, so trying avoid using it

        :return: A lock object, which should contain an unlock() function.
        """
        raise NotImplementedError(self.lock_read)

    def lock_write(self, relpath):
        """Lock the given file for exclusive (write) access.
        WARNING: many transports do not support this, so trying avoid using it

        :return: A lock object, which should contain an unlock() function.
        """
        raise NotImplementedError(self.lock_write)

    def is_readonly(self):
        """Return true if this connection cannot be written to."""
        return False


def get_transport(base):
    """Open a transport to access a URL or directory.

    base is either a URL or a directory name.  
    """
    # TODO: give a better error if base looks like a url but there's no
    # handler for the scheme?
    global _protocol_handlers
    if base is None:
        base = u'.'
    else:
        base = unicode(base)
    for proto, factory_list in _protocol_handlers.iteritems():
        if proto is not None and base.startswith(proto):
            t = _try_transport_factories(base, factory_list)
            if t:
                return t
    # The default handler is the filesystem handler, stored as protocol None
    return _try_transport_factories(base, _protocol_handlers[None])


def _try_transport_factories(base, factory_list):
    for factory in factory_list:
        try:
            return factory(base)
        except DependencyNotPresent, e:
            mutter("failed to instantiate transport %r for %r: %r" %
                    (factory, base, e))
            continue
    return None


def urlescape(relpath):
    """Escape relpath to be a valid url."""
    if isinstance(relpath, unicode):
        relpath = relpath.encode('utf-8')
    return urllib.quote(relpath)


def urlunescape(relpath):
    """Unescape relpath from url format."""
    return urllib.unquote(relpath)
    # TODO de-utf8 it last. relpath = utf8relpath.decode('utf8')


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
        if not hasattr(module, 'get_test_permutations'):
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
register_lazy_transport('memory:/', 'bzrlib.transport.memory', 'MemoryTransport')
register_lazy_transport('readonly+', 'bzrlib.transport.readonly', 'ReadonlyTransportDecorator')
register_lazy_transport('fakenfs+', 'bzrlib.transport.fakenfs', 'FakeNFSTransportDecorator')
register_lazy_transport('vfat+', 
                        'bzrlib.transport.fakevfat',
                        'FakeVFATTransportDecorator')
