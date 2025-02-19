# Copyright (C) 2005-2012, 2016 Canonical Ltd
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

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
import sys
from io import BytesIO
from stat import S_ISDIR
from typing import Any, Callable, Dict, TypeVar

from .. import errors, hooks, osutils, registry, ui, urlutils
from ..trace import mutter

# a dictionary of open file streams. Keys are absolute paths, values are
# transport defined.
_file_streams: Dict[str, Any] = {}


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
    for prefix, factory_list in transport_list_registry.items():
        for factory in factory_list:
            modules.add(factory.get_module())
    # Add chroot and pathfilter directly, because there is no handler
    # registered for it.
    modules.add("breezy.transport.chroot")
    modules.add("breezy.transport.pathfilter")
    result = sorted(modules)
    return result


class UnusableRedirect(errors.BzrError):
    _fmt = "Unable to follow redirect from %(source)s to %(target)s: %(reason)s."

    def __init__(self, source, target, reason):
        super().__init__(source=source, target=target, reason=reason)


class UnsupportedProtocol(errors.PathError):
    _fmt = 'Unsupported protocol for url "%(path)s"%(extra)s'

    def __init__(self, url, extra=""):
        errors.PathError.__init__(self, url, extra=extra)


class NoSuchFile(errors.PathError):
    _fmt = "No such file: %(path)r%(extra)s"


class FileExists(errors.PathError):
    _fmt = "File exists: %(path)r%(extra)s"


class TransportListRegistry(registry.Registry):
    """A registry which simplifies tracking available Transports.

    A registration of a new protocol requires two steps:
    1) register the prefix with the function register_transport( )
    2) register the protocol provider with the function
    register_transport_provider( ) ( and the "lazy" variant )

    This is needed because:
    a) a single provider can support multiple protocols (like the ftp
    provider which supports both the ftp:// and the aftp:// protocols)
    b) a single protocol can have multiple providers (like the http://
    protocol which was supported by both the urllib and pycurl providers)
    """

    def register_transport_provider(self, key, obj):
        self.get(key).insert(0, registry._ObjectGetter(obj))

    def register_lazy_transport_provider(self, key, module_name, member_name):
        self.get(key).insert(0, registry._LazyObjectGetter(module_name, member_name))

    def register_transport(self, key, help=None):
        self.register(key, [], help)


transport_list_registry = TransportListRegistry()


def register_transport_proto(prefix, help=None, info=None, register_netloc=False):
    transport_list_registry.register_transport(prefix, help)
    if register_netloc:
        if not prefix.endswith("://"):
            raise ValueError(prefix)
        register_urlparse_netloc_protocol(prefix[:-3])


def register_lazy_transport(prefix, module, classname):
    if prefix not in transport_list_registry:
        register_transport_proto(prefix)
    transport_list_registry.register_lazy_transport_provider(prefix, module, classname)


def register_transport(prefix, klass):
    if prefix not in transport_list_registry:
        register_transport_proto(prefix)
    transport_list_registry.register_transport_provider(prefix, klass)


def register_urlparse_netloc_protocol(protocol):
    """Ensure that protocol is setup to be used with urlparse netloc parsing."""
    if protocol not in urlutils.urlparse.uses_netloc:
        urlutils.urlparse.uses_netloc.append(protocol)


def _unregister_urlparse_netloc_protocol(protocol):
    """Remove protocol from urlparse netloc parsing.

    Except for tests, you should never use that function. Using it with 'http',
    for example, will break all http transports.
    """
    if protocol in urlutils.urlparse.uses_netloc:
        urlutils.urlparse.uses_netloc.remove(protocol)


def unregister_transport(scheme, factory):
    """Unregister a transport."""
    l = transport_list_registry.get(scheme)
    for i in l:
        o = i.get_obj()
        if o == factory:
            transport_list_registry.get(scheme).remove(i)
            break
    if len(l) == 0:
        transport_list_registry.remove(scheme)


class _CoalescedOffset:
    """A data container for keeping track of coalesced offsets."""

    __slots__ = ["length", "ranges", "start"]

    def __init__(self, start, length, ranges):
        self.start = start
        self.length = length
        self.ranges = ranges

    def __lt__(self, other):
        return (self.start, self.length, self.ranges) < (
            other.start,
            other.length,
            other.ranges,
        )

    def __eq__(self, other):
        return (self.start, self.length, self.ranges) == (
            other.start,
            other.length,
            other.ranges,
        )

    def __repr__(self):
        return "{}({!r}, {!r}, {!r})".format(
            self.__class__.__name__, self.start, self.length, self.ranges
        )


class LateReadError:
    """A helper for transports which pretends to be a readable file.

    When read() is called, errors.ReadError is raised.
    """

    def __init__(self, path):
        self._path = path

    def close(self):
        """A no-op - do nothing."""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # If there was an error raised, prefer the original one
        try:
            self.close()
        except:
            if exc_type is None:
                raise
        return False

    def _fail(self):
        """Raise ReadError."""
        raise errors.ReadError(self._path)

    def __iter__(self):
        self._fail()

    def read(self, count=-1):
        self._fail()

    def readlines(self):
        self._fail()


class FileStream:
    """Base class for FileStreams."""

    def __init__(self, transport, relpath):
        """Create a FileStream for relpath on transport."""
        self.transport = transport
        self.relpath = relpath

    def _close(self):
        """A hook point for subclasses that need to take action on close."""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, exc_tb):
        self.close()
        return False

    def close(self, want_fdatasync=False):
        if want_fdatasync:
            try:
                self.fdatasync()
            except errors.TransportNotPossible:
                pass
        self._close()
        del _file_streams[self.transport.abspath(self.relpath)]

    def fdatasync(self):
        """Force data out to physical disk if possible.

        :raises TransportNotPossible: If this transport has no way to
            flush to disk.
        """
        raise errors.TransportNotPossible("{} cannot fdatasync".format(self.transport))


class FileFileStream(FileStream):
    """A file stream object returned by open_write_stream.

    This version uses a file like object to perform writes.
    """

    def __init__(self, transport, relpath, file_handle):
        FileStream.__init__(self, transport, relpath)
        self.file_handle = file_handle

    def _close(self):
        self.file_handle.close()

    def fdatasync(self):
        """Force data out to physical disk if possible."""
        self.file_handle.flush()
        try:
            fileno = self.file_handle.fileno()
        except AttributeError:
            raise errors.TransportNotPossible()
        osutils.fdatasync(fileno)

    def write(self, bytes):
        osutils.pump_string_file(bytes, self.file_handle)


class AppendBasedFileStream(FileStream):
    """A file stream object returned by open_write_stream.

    This version uses append on a transport to perform writes.
    """

    def write(self, bytes):
        self.transport.append_bytes(self.relpath, bytes)


class TransportHooks(hooks.Hooks):
    """Mapping of hook names to registered callbacks for transport hooks"""

    def __init__(self):
        super().__init__()
        self.add_hook(
            "post_connect",
            "Called after a new connection is established or a reconnect "
            "occurs. The sole argument passed is either the connected "
            "transport or smart medium instance.",
            (2, 5),
        )


class Transport:
    """This class encapsulates methods for retrieving or putting a file
    from/to a storage location.

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

    hooks = TransportHooks()

    base: str

    def __init__(self, base):
        super().__init__()
        self.base = base
        (self._raw_base, self._segment_parameters) = urlutils.split_segment_parameters(
            base
        )

    def _translate_error(self, e, path, raise_generic=True):
        """Translate an IOError or OSError into an appropriate bzr error.

        This handles things like ENOENT, ENOTDIR, EEXIST, and EACCESS
        """
        if getattr(e, "errno", None) is not None:
            if e.errno in (errno.ENOENT, errno.ENOTDIR):
                raise NoSuchFile(path, extra=e)
            elif e.errno == errno.EINVAL:
                mutter("EINVAL returned on path {}: {!r}".format(path, e))
                raise NoSuchFile(path, extra=e)
            # I would rather use errno.EFOO, but there doesn't seem to be
            # any matching for 267
            # This is the error when doing a listdir on a file:
            # WindowsError: [Errno 267] The directory name is invalid
            if sys.platform == "win32" and e.errno in (errno.ESRCH, 267):
                raise NoSuchFile(path, extra=e)
            if e.errno == errno.EEXIST:
                raise FileExists(path, extra=e)
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

    def create_prefix(self, mode=None):
        """Create all the directories leading down to self.base."""
        cur_transport = self
        needed = [cur_transport]
        # Recurse upwards until we can create a directory successfully
        while True:
            new_transport = cur_transport.clone("..")
            if new_transport.base == cur_transport.base:
                raise errors.CommandError(
                    "Failed to create path prefix for %s." % cur_transport.base
                )
            try:
                new_transport.mkdir(".", mode=mode)
            except NoSuchFile:
                needed.append(new_transport)
                cur_transport = new_transport
            except FileExists:
                break
            else:
                break
        # Now we only need to create child directories
        while needed:
            cur_transport = needed.pop()
            cur_transport.ensure_base(mode=mode)

    def ensure_base(self, mode=None):
        """Ensure that the directory this transport references exists.

        This will create a directory if it doesn't exist.
        :return: True if the directory was created, False otherwise.
        """
        # The default implementation just uses "Easier to ask for forgiveness
        # than permission". We attempt to create the directory, and just
        # suppress FileExists and PermissionDenied (for Windows) exceptions.
        try:
            self.mkdir(".", mode=mode)
        except (FileExists, errors.PermissionDenied):
            return False
        except errors.TransportNotPossible:
            if self.has("."):
                return False
            raise
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
        be used to obtain a new transport within breezy. Ideally chroot
        transports would know enough to cause the external url to be the exact
        one used that caused the chrooting in the first place, but that is not
        currently the case.

        :return: A URL that can be given to another process.
        :raises InProcessTransport: If the transport is one that cannot be
            accessed out of the current process (e.g. a MemoryTransport)
            then InProcessTransport is raised.
        """
        raise NotImplementedError(self.external_url)

    def get_segment_parameters(self):
        """Return the segment parameters for the top segment of the URL."""
        return self._segment_parameters

    def set_segment_parameter(self, name, value):
        """Set a segment parameter.

        Args:
          name: Segment parameter name (urlencoded string)
          value: Segment parameter value (urlencoded string)
        """
        if value is None:
            try:
                del self._segment_parameters[name]
            except KeyError:
                pass
        else:
            self._segment_parameters[name] = value
        self.base = urlutils.join_segment_parameters(
            self._raw_base, self._segment_parameters
        )

    def _pump(self, from_file, to_file):
        """Most children will need to copy from one file-like
        object or string to another one.
        This just gives them something easy to call.
        """
        return osutils.pumpfile(from_file, to_file)

    def _get_total(self, multi):
        """Try to figure out how many entries are in multi,
        but if not possible, return None.
        """
        try:
            return len(multi)
        except TypeError:  # We can't tell how many, because relpaths is a generator
            return None

    def _report_activity(self, bytes, direction):
        """Notify that this transport has activity.

        Implementations should call this from all methods that actually do IO.
        Be careful that it's not called twice, if one method is implemented on
        top of another.

        Args:
          bytes: Number of bytes read or written.
          direction: 'read' or 'write' or None.
        """
        ui.ui_factory.report_transport_activity(self, bytes, direction)

    def _update_pb(self, pb, msg, count, total):
        """Update the progress bar based on the current count
        and total available, total may be None if it was
        not possible to determine.
        """
        if pb is None:
            return
        if total is None:
            pb.update(msg, count, count + 1)
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
        # TODO: This might want to use breezy.osutils.relpath
        #       but we have to watch out because of the prefix issues
        if not (abspath == self.base[:-1] or abspath.startswith(self.base)):
            raise errors.PathNotChild(abspath, self.base)
        pl = len(self.base)
        return abspath[pl:].strip("/")

    def local_abspath(self, relpath):
        """Return the absolute path on the local filesystem.

        This function will only be defined for Transports which have a
        physical local filesystem representation.

        :raises errors.NotLocalUrl: When no local path representation is
            available.
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
        you may check via listable() to determine if it will.
        """
        raise errors.TransportNotPossible(
            "This transport has not "
            "implemented iter_files_recursive "
            "(but must claim to be listable "
            "to trigger this error)."
        )

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
        f = self.get(relpath)
        try:
            return f.read()
        finally:
            f.close()

    def get_smart_medium(self):
        """Return a smart client medium for this transport if possible.

        A smart medium doesn't imply the presence of a smart server: it implies
        that the smart protocol can be tunnelled via this transport.

        :raises NoSmartMedium: if no smart server medium is available.
        """
        raise errors.NoSmartMedium(self)

    def readv(self, relpath, offsets, adjust_for_latency=False, upper_limit=None):
        """Get parts of the file at the given relative path.

        Args:
          relpath: The path to read data from.
          offsets: A list of (offset, size) tuples.
          adjust_for_latency: Adjust the requested offsets to accomodate
            transport latency. This may re-order the offsets, expand them to
            grab adjacent data when there is likely a high cost to requesting
            data relative to delivering it.
          upper_limit: When adjust_for_latency is True setting upper_limit
            allows the caller to tell the transport about the length of the
            file, so that requests are not issued for ranges beyond the end of
            the file. This matters because some servers and/or transports error
            in such a case rather than just satisfying the available ranges.
            upper_limit should always be provided when adjust_for_latency is
            True, and should be the size of the file in bytes.
        Returns: A list or generator of (offset, data) tuples
        """
        if adjust_for_latency:
            # Design note: We may wish to have different algorithms for the
            # expansion of the offsets per-transport. E.g. for local disk to
            # use page-aligned expansion. If that is the case consider the
            # following structure:
            #  - a test that transport.readv uses self._offset_expander or some
            #    similar attribute, to do the expansion
            #  - a test for each transport that it has some known-good offset
            #    expander
            #  - unit tests for each offset expander
            #  - a set of tests for the offset expander interface, giving
            #    baseline behaviour (which the current transport
            #    adjust_for_latency tests could be repurposed to).
            offsets = self._sort_expand_and_combine(offsets, upper_limit)
        return self._readv(relpath, offsets)

    def _readv(self, relpath, offsets):
        """Get parts of the file at the given relative path.

        :param relpath: The path to read.
        :param offsets: A list of (offset, size) tuples.
        :return: A list or generator of (offset, data) tuples
        """
        if not offsets:
            return

        fp = self.get(relpath)
        return self._seek_and_read(fp, offsets, relpath)

    def _seek_and_read(self, fp, offsets, relpath="<unknown>"):
        """An implementation of readv that uses fp.seek and fp.read.

        This uses _coalesce_offsets to issue larger reads and fewer seeks.

        :param fp: A file-like object that supports seek() and read(size).
            Note that implementations are allowed to call .close() on this file
            handle, so don't trust that you can use it for other work.
        :param offsets: A list of offsets to be read from the given file.
        :return: yield (pos, data) tuples for each request
        """
        # We are going to iterate multiple times, we need a list
        offsets = list(offsets)
        sorted_offsets = sorted(offsets)

        # turn the list of offsets into a stack
        offset_stack = iter(offsets)
        cur_offset_and_size = next(offset_stack)
        coalesced = self._coalesce_offsets(
            sorted_offsets,
            limit=self._max_readv_combine,
            fudge_factor=self._bytes_to_read_before_seek,
        )

        # Cache the results, but only until they have been fulfilled
        data_map = {}
        try:
            for c_offset in coalesced:
                # TODO: jam 20060724 it might be faster to not issue seek if
                #       we are already at the right location. This should be
                #       benchmarked.
                fp.seek(c_offset.start)
                data = fp.read(c_offset.length)
                if len(data) < c_offset.length:
                    raise errors.ShortReadvError(
                        relpath, c_offset.start, c_offset.length, actual=len(data)
                    )
                for suboffset, subsize in c_offset.ranges:
                    key = (c_offset.start + suboffset, subsize)
                    data_map[key] = data[suboffset : suboffset + subsize]

                # Now that we've read some data, see if we can yield anything back
                while cur_offset_and_size in data_map:
                    this_data = data_map.pop(cur_offset_and_size)
                    this_offset = cur_offset_and_size[0]
                    try:
                        cur_offset_and_size = next(offset_stack)
                    except StopIteration:
                        fp.close()
                        cur_offset_and_size = None
                    yield this_offset, this_data
        finally:
            fp.close()

    def _sort_expand_and_combine(self, offsets, upper_limit):
        """Helper for readv.

        :param offsets: A readv vector - (offset, length) tuples.
        :param upper_limit: The highest byte offset that may be requested.
        :return: A readv vector that will read all the regions requested by
            offsets, in start-to-end order, with no duplicated regions,
            expanded by the transports recommended page size.
        """
        offsets = sorted(offsets)
        # short circuit empty requests
        if len(offsets) == 0:

            def empty_yielder():
                # Quick thunk to stop this function becoming a generator
                # itself, rather we return a generator that has nothing to
                # yield.
                if False:
                    yield None

            return empty_yielder()
        # expand by page size at either end
        maximum_expansion = self.recommended_page_size()
        new_offsets = []
        for offset, length in offsets:
            expansion = maximum_expansion - length
            if expansion < 0:
                # we're asking for more than the minimum read anyway.
                expansion = 0
            reduction = expansion // 2
            new_offset = offset - reduction
            new_length = length + expansion
            if new_offset < 0:
                # don't ask for anything < 0
                new_offset = 0
            if upper_limit is not None and new_offset + new_length > upper_limit:
                new_length = upper_limit - new_offset
            new_offsets.append((new_offset, new_length))
        # combine the expanded offsets
        offsets = []
        current_offset, current_length = new_offsets[0]
        current_finish = current_length + current_offset
        for offset, length in new_offsets[1:]:
            finish = offset + length
            if offset > current_finish:
                # there is a gap, output the current accumulator and start
                # a new one for the region we're examining.
                offsets.append((current_offset, current_length))
                current_offset = offset
                current_length = length
                current_finish = finish
                continue
            if finish > current_finish:
                # extend the current accumulator to the end of the region
                # we're examining.
                current_finish = finish
                current_length = finish - current_offset
        offsets.append((current_offset, current_length))
        return offsets

    @staticmethod
    def _coalesce_offsets(offsets, limit=0, fudge_factor=0, max_size=0):
        """Yield coalesced offsets.

        With a long list of neighboring requests, combine them
        into a single large request, while retaining the original
        offsets.
        Turns  [(15, 10), (25, 10)] => [(15, 20, [(0, 10), (10, 10)])]
        Note that overlapping requests are not permitted. (So [(15, 10), (20,
        10)] will raise a ValueError.) This is because the data we access never
        overlaps, and it allows callers to trust that we only need any byte of
        data for 1 request (so nothing needs to be buffered to fulfill a second
        request.)

        :param offsets: A list of (start, length) pairs
        :param limit: Only combine a maximum of this many pairs Some transports
                penalize multiple reads more than others, and sometimes it is
                better to return early.
                0 means no limit
        :param fudge_factor: All transports have some level of 'it is
                better to read some more data and throw it away rather
                than seek', so collapse if we are 'close enough'
        :param max_size: Create coalesced offsets no bigger than this size.
                When a single offset is bigger than 'max_size', it will keep
                its size and be alone in the coalesced offset.
                0 means no maximum size.
        :return: return a list of _CoalescedOffset objects, which have members
            for where to start, how much to read, and how to split those chunks
            back up
        """
        last_end = None
        cur = _CoalescedOffset(None, None, [])
        coalesced_offsets = []

        if max_size <= 0:
            # 'unlimited', but we actually take this to mean 100MB buffer limit
            max_size = 100 * 1024 * 1024

        for start, size in offsets:
            end = start + size
            if (
                last_end is not None
                and start <= last_end + fudge_factor
                and start >= cur.start
                and (limit <= 0 or len(cur.ranges) < limit)
                and (max_size <= 0 or end - cur.start <= max_size)
            ):
                if start < last_end:
                    raise ValueError(
                        "Overlapping range not allowed:"
                        " last range ended at %s, new one starts at %s"
                        % (last_end, start)
                    )
                cur.length = end - cur.start
                cur.ranges.append((start - cur.start, size))
            else:
                if cur.start is not None:
                    coalesced_offsets.append(cur)
                cur = _CoalescedOffset(start, size, [(0, size)])
            last_end = end

        if cur.start is not None:
            coalesced_offsets.append(cur)
        return coalesced_offsets

    def put_bytes(self, relpath: str, raw_bytes: bytes, mode=None):
        """Atomically put the supplied bytes into the given location.

        :param relpath: The location to put the contents, relative to the
            transport base.
        :param raw_bytes: A bytestring of data.
        :param mode: Create the file with the given mode.
        :return: None
        """
        if not isinstance(raw_bytes, bytes):
            raise TypeError(
                "raw_bytes must be a plain string, not %s" % type(raw_bytes)
            )
        return self.put_file(relpath, BytesIO(raw_bytes), mode=mode)

    def put_bytes_non_atomic(
        self,
        relpath,
        raw_bytes: bytes,
        mode=None,
        create_parent_dir=False,
        dir_mode=None,
    ):
        """Copy the string into the target location.

        This function is not strictly safe to use. See
        Transport.put_bytes_non_atomic for more information.

        :param relpath: The remote location to put the contents.
        :param raw_bytes:   A string object containing the raw bytes to write
                        into the target file.
        :param mode:    Possible access permissions for new file.
                        None means do not set remote permissions.
        :param create_parent_dir: If we cannot create the target file because
                        the parent directory does not exist, go ahead and
                        create it, and then try again.
        :param dir_mode: Possible access permissions for new directories.
        """
        if not isinstance(raw_bytes, bytes):
            raise TypeError(
                "raw_bytes must be a plain string, not %s" % type(raw_bytes)
            )
        self.put_file_non_atomic(
            relpath,
            BytesIO(raw_bytes),
            mode=mode,
            create_parent_dir=create_parent_dir,
            dir_mode=dir_mode,
        )

    def put_file(self, relpath, f, mode=None):
        """Copy the file-like object into the location.

        :param relpath: Location to put the contents, relative to base.
        :param f:       File-like object.
        :param mode: The mode for the newly created file,
                     None means just use the default.
        :return: The length of the file that was written.
        """
        raise NotImplementedError(self.put_file)

    def put_file_non_atomic(
        self, relpath, f, mode=None, create_parent_dir=False, dir_mode=None
    ):
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
        except NoSuchFile:
            if not create_parent_dir:
                raise
            parent_dir = osutils.dirname(relpath)
            if parent_dir:
                self.mkdir(parent_dir, mode=dir_mode)
                return self.put_file(relpath, f, mode=mode)

    def mkdir(self, relpath, mode=None):
        """Create a directory at the given path."""
        raise NotImplementedError(self.mkdir)

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
        raise NotImplementedError(self.append_file)

    def append_bytes(self, relpath, data, mode=None):
        """Append bytes to a file at relpath.

        The file is created if it does not already exist.

        :param relpath: The relative path to the file.
        :param data: a string of the bytes to append.
        :param mode: Unix mode for newly created files.  This is not used for
            existing files.

        :returns: the length of relpath before the content was written to it.
        """
        if not isinstance(data, bytes):
            raise TypeError("bytes must be a plain string, not %s" % type(data))
        return self.append_file(relpath, BytesIO(data), mode=mode)

    def copy(self, rel_from, rel_to):
        """Copy the item at rel_from to the location at rel_to.

        Override this for efficiency if a specific transport can do it
        faster than this default implementation.
        """
        with self.get(rel_from) as f:
            self.put_file(rel_to, f)

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

        return len(
            self._iterate_over(relpaths, copy_entry, pb, "copy_to", expand=False)
        )

    def copy_tree(self, from_relpath, to_relpath):
        """Copy a subtree from one relpath to another.

        If a faster implementation is available, specific transports should
        implement it.
        """
        source = self.clone(from_relpath)
        target = self.clone(to_relpath)

        # create target directory with the same rwx bits as source.
        # use mask to ensure that bits other than rwx are ignored.
        stat = self.stat(from_relpath)
        target.mkdir(".", stat.st_mode & 0o777)
        source.copy_tree_to_transport(target)

    def copy_tree_to_transport(self, to_transport):
        """Copy a subtree from one transport to another.

        self.base is used as the source tree root, and to_transport.base
        is used as the target.  to_transport.base must exist (and be a
        directory).
        """
        files = []
        directories = ["."]
        while directories:
            dir = directories.pop()
            if dir != ".":
                to_transport.mkdir(dir)
            for path in self.list_dir(dir):
                path = dir + "/" + path
                stat = self.stat(path)
                if S_ISDIR(stat.st_mode):
                    directories.append(path)
                else:
                    files.append(path)
        self.copy_to(files, to_transport)

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

    def delete(self, relpath):
        """Delete the item at relpath"""
        raise NotImplementedError(self.delete)

    def delete_tree(self, relpath):
        """Delete an entire tree. This may require a listable transport."""
        subtree = self.clone(relpath)
        files = []
        directories = ["."]
        pending_rmdirs = []
        while directories:
            dir = directories.pop()
            if dir != ".":
                pending_rmdirs.append(dir)
            for path in subtree.list_dir(dir):
                path = dir + "/" + path
                stat = subtree.stat(path)
                if S_ISDIR(stat.st_mode):
                    directories.append(path)
                else:
                    files.append(path)
        for file in files:
            subtree.delete(file)
        pending_rmdirs.reverse()
        for dir in pending_rmdirs:
            subtree.rmdir(dir)
        self.rmdir(relpath)

    def __repr__(self):
        return "<{}.{} url={}>".format(
            self.__module__, self.__class__.__name__, self.base
        )

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

    def readlink(self, relpath):
        """Return a string representing the path to which the symbolic link points."""
        raise errors.TransportNotPossible(
            "Dereferencing symlinks is not supported on %s" % self
        )

    def hardlink(self, source, link_name):
        """Create a hardlink pointing to source named link_name."""
        raise errors.TransportNotPossible("Hard links are not supported on %s" % self)

    def symlink(self, source, link_name):
        """Create a symlink pointing to source named link_name."""
        raise errors.TransportNotPossible("Symlinks are not supported on %s" % self)

    def listable(self):
        """Return True if this store supports listing."""
        raise NotImplementedError(self.listable)

    def list_dir(self, relpath):
        """Return a list of all files at the given location.
        WARNING: many transports do not support this, so trying avoid using
        it if at all possible.
        """
        raise errors.TransportNotPossible(
            "Transport %r has not "
            "implemented list_dir "
            "(but must claim to be listable "
            "to trigger this error)." % (self)
        )

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
        server.
        """
        # TODO: Perhaps return a e.g. TransportCharacteristics that can answer
        # several questions about the transport.
        return False

    def _reuse_for(self, other_base):
        # This is really needed for ConnectedTransport only, but it's easier to
        # have Transport refuses to be reused than testing that the reuse
        # should be asked to ConnectedTransport only.
        return None

    def disconnect(self):
        # This is really needed for ConnectedTransport only, but it's easier to
        # have Transport do nothing than testing that the disconnect should be
        # asked to ConnectedTransport only.
        pass

    def _redirected_to(self, source, target):
        """Returns a transport suitable to re-issue a redirected request.

        :param source: The source url as returned by the server.
        :param target: The target url as returned by the server.

        The redirection can be handled only if the relpath involved is not
        renamed by the redirection.

        :returns: A transport
        :raise UnusableRedirect: when redirection can not be provided
        """
        # This returns None by default, meaning the transport can't handle the
        # redirection.
        raise UnusableRedirect(source, target, "transport does not support redirection")


class _SharedConnection:
    """A connection shared between several transports."""

    def __init__(self, connection=None, credentials=None, base=None):
        """Constructor.

        :param connection: An opaque object specific to each transport.

        :param credentials: An opaque object containing the credentials used to
            create the connection.
        """
        self.connection = connection
        self.credentials = credentials
        self.base = base


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
        if not base.endswith("/"):
            base += "/"
        self._parsed_url = self._split_url(base)
        if _from_transport is not None:
            # Copy the password as it does not appear in base and will be lost
            # otherwise. It can appear in the _split_url above if the user
            # provided it on the command line. Otherwise, daughter classes will
            # prompt the user for one when appropriate.
            self._parsed_url.password = _from_transport._parsed_url.password
            self._parsed_url.quoted_password = (
                _from_transport._parsed_url.quoted_password
            )

        base = str(self._parsed_url)

        super().__init__(base)
        if _from_transport is None:
            self._shared_connection = _SharedConnection()
        else:
            self._shared_connection = _from_transport._shared_connection

    @property
    def _user(self):
        return self._parsed_url.user

    @property
    def _password(self):
        return self._parsed_url.password

    @property
    def _host(self):
        return self._parsed_url.host

    @property
    def _port(self):
        return self._parsed_url.port

    @property
    def _path(self):
        return self._parsed_url.path

    @property
    def _scheme(self):
        return self._parsed_url.scheme

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
        return urlutils.URL.from_string(url)

    @staticmethod
    def _unsplit_url(scheme, user, password, host, port, path):
        """Build the full URL for the given already URL encoded path.

        user, password, host and path will be quoted if they contain reserved
        chars.

        Args:
          scheme: protocol
          user: login
          password: associated password
          host: the server address
          port: the associated port
          path: the absolute path on the server

        :return: The corresponding URL.
        """
        netloc = urlutils.quote(host)
        if user is not None:
            # Note that we don't put the password back even if we
            # have one so that it doesn't get accidentally
            # exposed.
            netloc = "{}@{}".format(urlutils.quote(user), netloc)
        if port is not None:
            netloc = "%s:%d" % (netloc, port)
        path = urlutils.escape(path)
        return urlutils.urlparse.urlunparse((scheme, netloc, path, None, None, None))

    def relpath(self, abspath):
        """Return the local path portion from a given absolute path"""
        parsed_url = self._split_url(abspath)
        error = []
        if parsed_url.scheme != self._parsed_url.scheme:
            error.append("scheme mismatch")
        if parsed_url.user != self._parsed_url.user:
            error.append("user name mismatch")
        if parsed_url.host != self._parsed_url.host:
            error.append("host mismatch")
        if parsed_url.port != self._parsed_url.port:
            error.append("port mismatch")
        if not (
            parsed_url.path == self._parsed_url.path[:-1]
            or parsed_url.path.startswith(self._parsed_url.path)
        ):
            error.append("path mismatch")
        if error:
            extra = ", ".join(error)
            raise errors.PathNotChild(abspath, self.base, extra=extra)
        pl = len(self._parsed_url.path)
        return parsed_url.path[pl:].strip("/")

    def abspath(self, relpath):
        """Return the full url to the given relative path.

        Args:
          relpath: the relative path urlencoded

        :returns: the Unicode version of the absolute path for relpath.
        """
        return str(self._parsed_url.clone(relpath))

    def _remote_path(self, relpath):
        """Return the absolute path part of the url to the given relative path.

        This is the path that the remote server expect to receive in the
        requests, daughter classes should redefine this method if needed and
        use the result to build their requests.

        Args:
          relpath: the path relative to the transport base urlencoded.

        :return: the absolute Unicode path on the server,
        """
        return self._parsed_url.clone(relpath).path

    def _get_shared_connection(self):
        """Get the object shared amongst cloned transports.

        This should be used only by classes that needs to extend the sharing
        with objects other than transports.

        Use _get_connection to get the connection itself.
        """
        return self._shared_connection

    def _set_connection(self, connection, credentials=None):
        """Record a newly created connection with its associated credentials.

        Note: To ensure that connection is still shared after a temporary
        failure and a new one needs to be created, daughter classes should
        always call this method to set the connection and do so each time a new
        connection is created.

        Args:
          connection: An opaque object representing the connection used by
            the daughter class.
          credentials: An opaque object representing the credentials
            needed to create the connection.
        """
        self._shared_connection.connection = connection
        self._shared_connection.credentials = credentials
        for hook in self.hooks["post_connect"]:
            hook(self)

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
        try:
            parsed_url = self._split_url(other_base)
        except urlutils.InvalidURL:
            # No hope in trying to reuse an existing transport for an invalid
            # URL
            return None

        transport = None
        # Don't compare passwords, they may be absent from other_base or from
        # self and they don't carry more information than user anyway.
        if (
            parsed_url.scheme == self._parsed_url.scheme
            and parsed_url.user == self._parsed_url.user
            and parsed_url.host == self._parsed_url.host
            and parsed_url.port == self._parsed_url.port
        ):
            path = parsed_url.path
            if not path.endswith("/"):
                # This normally occurs at __init__ time, but it's easier to do
                # it now to avoid creating two transports for the same base.
                path += "/"
            if self._parsed_url.path == path:
                # shortcut, it's really the same transport
                return self
            # We don't call clone here because the intent is different: we
            # build a new transport on a different base (which may be totally
            # unrelated) but we share the connection.
            transport = self.__class__(other_base, _from_transport=self)
        return transport

    def disconnect(self):
        """Disconnect the transport.

        If and when required the transport willl reconnect automatically.
        """
        raise NotImplementedError(self.disconnect)


def get_transport_from_path(path, possible_transports=None):
    """Open a transport for a local path.

    :param path: Local path as byte or unicode string
    :return: Transport object for path
    """
    return get_transport_from_url(urlutils.local_path_to_url(path), possible_transports)


def get_transport_from_url(url, possible_transports=None):
    """Open a transport to access a URL.

    Args:
      base: a URL
      transports: optional reusable transports list. If not None, created
        transports will be added to the list.

    Returns: A new transport optionally sharing its connection with one of
        possible_transports.
    """
    transport = None
    if possible_transports is not None:
        for t in possible_transports:
            t_same_connection = t._reuse_for(url)
            if t_same_connection is not None:
                # Add only new transports
                if t_same_connection not in possible_transports:
                    possible_transports.append(t_same_connection)
                return t_same_connection

    last_err = None
    for proto, factory_list in transport_list_registry.items():
        if proto is not None and url.startswith(proto):
            transport, last_err = _try_transport_factories(url, factory_list)
            if transport:
                if possible_transports is not None:
                    if transport in possible_transports:
                        raise AssertionError()
                    possible_transports.append(transport)
                return transport
    if not urlutils.is_url(url):
        raise urlutils.InvalidURL(path=url)
    raise UnsupportedProtocol(url, last_err)


def get_transport(base, possible_transports=None, purpose=None):
    """Open a transport to access a URL or directory.

    Args:
      base: either a URL or a directory name.
      transports: optional reusable transports list. If not None, created
        transports will be added to the list.
      purpose: Purpose for which the transport will be used
        (e.g. 'read', 'write' or None)

    :return: A new transport optionally sharing its connection with one of
        possible_transports.
    """
    if base is None:
        base = "."
    from ..location import location_to_url

    return get_transport_from_url(
        location_to_url(base, purpose=purpose), possible_transports
    )


def _try_transport_factories(base, factory_list):
    last_err = None
    for factory in factory_list:
        try:
            return factory.get_obj()(base), None
        except errors.DependencyNotPresent as e:
            mutter("failed to instantiate transport %r for %r: %r" % (factory, base, e))
            last_err = e
            continue
    return None, last_err


T = TypeVar("T")


def do_catching_redirections(
    action: Callable[[Transport], T],
    transport: Transport,
    redirected: Callable[[Transport, errors.RedirectRequested, str], Transport],
) -> T:
    """Execute an action with given transport catching redirections.

    This is a facility provided for callers needing to follow redirections
    silently. The silence is relative: it is the caller responsability to
    inform the user about each redirection or only inform the user of a user
    via the exception parameter.

    Args:
      action: A callable, what the caller want to do while catching
                  redirections.
      transport: The initial transport used.
      redirected: A callable receiving the redirected transport and the
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
        except errors.RedirectRequested as e:
            redirection_notice = "{} is{} redirected to {}".format(
                e.source, e.permanently, e.target
            )
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


class Server:
    """A Transport Server.

    The Server interface provides a server for a given transport type.
    """

    def start_server(self):
        """Setup the server to service requests."""

    def stop_server(self):
        """Remove the server and cleanup any resources it owns."""


def open_file(url):
    """Open a file from a URL.

    :param url: URL to open
    :return: A file-like object.
    """
    base, filename = urlutils.split(path)
    transport = get_transport(base)
    return open_file_via_transport(filename, transport)


def open_file_via_transport(filename, transport):
    """Open a file using the transport, follow redirects as necessary."""

    def open_file(transport):
        return transport.get(filename)

    def follow_redirection(transport, e, redirection_notice):
        mutter(redirection_notice)
        base, filename = urlutils.split(e.target)
        redirected_transport = get_transport(base)
        return redirected_transport

    return do_catching_redirections(open_file, transport, follow_redirection)


# None is the default transport, for things with no url scheme
register_transport_proto(
    "file://", help="Access using the standard filesystem (default)"
)
register_lazy_transport("file://", "breezy.transport.local", "LocalTransport")

register_transport_proto(
    "sftp://",
    help="Access using SFTP (most SSH servers provide SFTP).",
    register_netloc=True,
)
register_lazy_transport("sftp://", "breezy.transport.sftp", "SFTPTransport")
# Decorated http transport
register_transport_proto(
    "http+urllib://",
    #                help="Read-only access of branches exported on the web."
    register_netloc=True,
)
register_lazy_transport(
    "http+urllib://", "breezy.transport.http.urllib", "HttpTransport"
)
register_transport_proto(
    "https+urllib://",
    #                help="Read-only access of branches exported on the web using SSL."
    register_netloc=True,
)
register_lazy_transport(
    "https+urllib://", "breezy.transport.http.urllib", "HttpTransport"
)
# Default http transports (last declared wins (if it can be imported))
register_transport_proto(
    "http://", help="Read-only access of branches exported on the web."
)
register_transport_proto(
    "https://", help="Read-only access of branches exported on the web using SSL."
)
# The default http implementation is urllib
register_lazy_transport("http://", "breezy.transport.http.urllib", "HttpTransport")
register_lazy_transport("https://", "breezy.transport.http.urllib", "HttpTransport")

register_transport_proto("gio+", help="Access using any GIO supported protocols.")
register_lazy_transport("gio+", "breezy.transport.gio_transport", "GioTransport")


register_transport_proto("memory://")
register_lazy_transport("memory://", "breezy.transport.memory", "MemoryTransport")

register_transport_proto(
    "readonly+",
    #              help="This modifier converts any transport to be readonly."
)
register_lazy_transport(
    "readonly+", "breezy.transport.readonly", "ReadonlyTransportDecorator"
)

register_transport_proto("fakenfs+")
register_lazy_transport(
    "fakenfs+", "breezy.transport.fakenfs", "FakeNFSTransportDecorator"
)

register_transport_proto("log+")
register_lazy_transport("log+", "breezy.transport.log", "TransportLogDecorator")

register_transport_proto("trace+")
register_lazy_transport("trace+", "breezy.transport.trace", "TransportTraceDecorator")

register_transport_proto("unlistable+")
register_lazy_transport(
    "unlistable+", "breezy.transport.unlistable", "UnlistableTransportDecorator"
)

register_transport_proto("brokenrename+")
register_lazy_transport(
    "brokenrename+", "breezy.transport.brokenrename", "BrokenRenameTransportDecorator"
)

register_transport_proto("vfat+")
register_lazy_transport(
    "vfat+", "breezy.transport.fakevfat", "FakeVFATTransportDecorator"
)

register_transport_proto("nosmart+")
register_lazy_transport(
    "nosmart+", "breezy.transport.nosmart", "NoSmartTransportDecorator"
)

register_transport_proto(
    "bzr://", help="Fast access using the Bazaar smart server.", register_netloc=True
)

register_lazy_transport("bzr://", "breezy.transport.remote", "RemoteTCPTransport")
register_transport_proto("bzr-v2://", register_netloc=True)

register_lazy_transport(
    "bzr-v2://", "breezy.transport.remote", "RemoteTCPTransportV2Only"
)
register_transport_proto(
    "bzr+http://",
    #                help="Fast access using the Bazaar smart server over HTTP."
    register_netloc=True,
)
register_lazy_transport("bzr+http://", "breezy.transport.remote", "RemoteHTTPTransport")
register_transport_proto(
    "bzr+https://",
    #                help="Fast access using the Bazaar smart server over HTTPS."
    register_netloc=True,
)
register_lazy_transport(
    "bzr+https://", "breezy.transport.remote", "RemoteHTTPTransport"
)
register_transport_proto(
    "bzr+ssh://",
    help="Fast access using the Bazaar smart server over SSH.",
    register_netloc=True,
)
register_lazy_transport("bzr+ssh://", "breezy.transport.remote", "RemoteSSHTransport")

register_transport_proto("ssh:")
register_lazy_transport("ssh:", "breezy.transport.remote", "HintingSSHTransport")


transport_server_registry = registry.Registry[str, Callable]()
transport_server_registry.register_lazy(
    "bzr",
    "breezy.bzr.smart.server",
    "serve_bzr",
    help="The Bazaar smart server protocol over TCP. (default port: 4155)",
)
transport_server_registry.default_key = "bzr"
