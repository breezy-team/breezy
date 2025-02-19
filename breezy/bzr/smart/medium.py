# Copyright (C) 2006-2011 Canonical Ltd
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

"""The 'medium' layer for the smart servers and clients.

"Medium" here is the noun meaning "a means of transmission", not the adjective
for "the quality between big and small."

Media carry the bytes of the requests somehow (e.g. via TCP, wrapped in HTTP, or
over SSH), and pass them to and from the protocol logic.  See the overview in
breezy/transport/smart/__init__.py.
"""

import _thread
import errno
import io
import os
import sys
import time

import breezy

from ...lazy_import import lazy_import

lazy_import(
    globals(),
    """
import select
import socket
import weakref

from breezy import (
    debug,
    trace,
    transport,
    ui,
    urlutils,
    )
from breezy.i18n import gettext
from breezy.bzr.smart import client, protocol, request, signals, vfs
from breezy.transport import ssh
""",
)
from ... import errors, osutils

# Throughout this module buffer size parameters are either limited to be at
# most _MAX_READ_SIZE, or are ignored and _MAX_READ_SIZE is used instead.
# For this module's purposes, MAX_SOCKET_CHUNK is a reasonable size for reads
# from non-sockets as well.
_MAX_READ_SIZE = osutils.MAX_SOCKET_CHUNK


class HpssVfsRequestNotAllowed(errors.BzrError):
    _fmt = (
        "VFS requests over the smart server are not allowed. Encountered: "
        "%(method)s, %(arguments)s."
    )

    def __init__(self, method, arguments):
        self.method = method
        self.arguments = arguments


def _get_protocol_factory_for_bytes(bytes):
    """Determine the right protocol factory for 'bytes'.

    This will return an appropriate protocol factory depending on the version
    of the protocol being used, as determined by inspecting the given bytes.
    The bytes should have at least one newline byte (i.e. be a whole line),
    otherwise it's possible that a request will be incorrectly identified as
    version 1.

    Typical use would be::

         factory, unused_bytes = _get_protocol_factory_for_bytes(bytes)
         server_protocol = factory(transport, write_func, root_client_path)
         server_protocol.accept_bytes(unused_bytes)

    :param bytes: a str of bytes of the start of the request.
    :returns: 2-tuple of (protocol_factory, unused_bytes).  protocol_factory is
        a callable that takes three args: transport, write_func,
        root_client_path.  unused_bytes are any bytes that were not part of a
        protocol version marker.
    """
    if bytes.startswith(protocol.MESSAGE_VERSION_THREE):
        protocol_factory = protocol.build_server_protocol_three
        bytes = bytes[len(protocol.MESSAGE_VERSION_THREE) :]
    elif bytes.startswith(protocol.REQUEST_VERSION_TWO):
        protocol_factory = protocol.SmartServerRequestProtocolTwo
        bytes = bytes[len(protocol.REQUEST_VERSION_TWO) :]
    else:
        protocol_factory = protocol.SmartServerRequestProtocolOne
    return protocol_factory, bytes


def _get_line(read_bytes_func):
    """Read bytes using read_bytes_func until a newline byte.

    This isn't particularly efficient, so should only be used when the
    expected size of the line is quite short.

    :returns: a tuple of two strs: (line, excess)
    """
    newline_pos = -1
    bytes = b""
    while newline_pos == -1:
        new_bytes = read_bytes_func(1)
        bytes += new_bytes
        if new_bytes == b"":
            # Ran out of bytes before receiving a complete line.
            return bytes, b""
        newline_pos = bytes.find(b"\n")
    line = bytes[: newline_pos + 1]
    excess = bytes[newline_pos + 1 :]
    return line, excess


class SmartMedium:
    """Base class for smart protocol media, both client- and server-side."""

    def __init__(self):
        self._push_back_buffer = None

    def _push_back(self, data):
        """Return unused bytes to the medium, because they belong to the next
        request(s).

        This sets the _push_back_buffer to the given bytes.
        """
        if not isinstance(data, bytes):
            raise TypeError(data)
        if self._push_back_buffer is not None:
            raise AssertionError(
                "_push_back called when self._push_back_buffer is %r"
                % (self._push_back_buffer,)
            )
        if data == b"":
            return
        self._push_back_buffer = data

    def _get_push_back_buffer(self):
        if self._push_back_buffer == b"":
            raise AssertionError(
                "%s._push_back_buffer should never be the empty string, "
                "which can be confused with EOF" % (self,)
            )
        bytes = self._push_back_buffer
        self._push_back_buffer = None
        return bytes

    def read_bytes(self, desired_count):
        """Read some bytes from this medium.

        :returns: some bytes, possibly more or less than the number requested
            in 'desired_count' depending on the medium.
        """
        if self._push_back_buffer is not None:
            return self._get_push_back_buffer()
        bytes_to_read = min(desired_count, _MAX_READ_SIZE)
        return self._read_bytes(bytes_to_read)

    def _read_bytes(self, count):
        raise NotImplementedError(self._read_bytes)

    def _get_line(self):
        """Read bytes from this request's response until a newline byte.

        This isn't particularly efficient, so should only be used when the
        expected size of the line is quite short.

        :returns: a string of bytes ending in a newline (byte 0x0A).
        """
        line, excess = _get_line(self.read_bytes)
        self._push_back(excess)
        return line

    def _report_activity(self, bytes, direction):
        """Notify that this medium has activity.

        Implementations should call this from all methods that actually do IO.
        Be careful that it's not called twice, if one method is implemented on
        top of another.

        :param bytes: Number of bytes read or written.
        :param direction: 'read' or 'write' or None.
        """
        ui.ui_factory.report_transport_activity(self, bytes, direction)


_bad_file_descriptor = (errno.EBADF,)
if sys.platform == "win32":
    # Given on Windows if you pass a closed socket to select.select. Probably
    # also given if you pass a file handle to select.
    WSAENOTSOCK = 10038
    _bad_file_descriptor += (WSAENOTSOCK,)


class SmartServerStreamMedium(SmartMedium):
    """Handles smart commands coming over a stream.

    The stream may be a pipe connected to sshd, or a tcp socket, or an
    in-process fifo for testing.

    One instance is created for each connected client; it can serve multiple
    requests in the lifetime of the connection.

    The server passes requests through to an underlying backing transport,
    which will typically be a LocalTransport looking at the server's filesystem.

    :ivar _push_back_buffer: a str of bytes that have been read from the stream
        but not used yet, or None if there are no buffered bytes.  Subclasses
        should make sure to exhaust this buffer before reading more bytes from
        the stream.  See also the _push_back method.
    """

    _timer = time.time

    def __init__(self, backing_transport, root_client_path="/", timeout=None):
        """Construct new server.

        :param backing_transport: Transport for the directory served.
        """
        # backing_transport could be passed to serve instead of __init__
        self.backing_transport = backing_transport
        self.root_client_path = root_client_path
        self.finished = False
        if timeout is None:
            raise AssertionError("You must supply a timeout.")
        self._client_timeout = timeout
        self._client_poll_timeout = min(timeout / 10.0, 1.0)
        SmartMedium.__init__(self)

    def serve(self):
        """Serve requests until the client disconnects."""
        # Keep a reference to stderr because the sys module's globals get set to
        # None during interpreter shutdown.
        from sys import stderr

        try:
            while not self.finished:
                server_protocol = self._build_protocol()
                self._serve_one_request(server_protocol)
        except errors.ConnectionTimeout as e:
            trace.note("{}".format(e))
            trace.log_exception_quietly()
            self._disconnect_client()
            # We reported it, no reason to make a big fuss.
            return
        except Exception as e:
            stderr.write("{} terminating on exception {}\n".format(self, e))
            raise
        self._disconnect_client()

    def _stop_gracefully(self):
        """When we finish this message, stop looking for more."""
        trace.mutter("Stopping {}".format(self))
        self.finished = True

    def _disconnect_client(self):
        """Close the current connection. We stopped due to a timeout/etc."""
        # The default implementation is a no-op, because that is all we used to
        # do when disconnecting from a client. I suppose we never had the
        # *server* initiate a disconnect, before

    def _wait_for_bytes_with_timeout(self, timeout_seconds):
        """Wait for more bytes to be read, but timeout if none available.

        This allows us to detect idle connections, and stop trying to read from
        them, without setting the socket itself to non-blocking. This also
        allows us to specify when we watch for idle timeouts.

        :return: Did we timeout? (True if we timed out, False if there is data
            to be read)
        """
        raise NotImplementedError(self._wait_for_bytes_with_timeout)

    def _build_protocol(self):
        """Identifies the version of the incoming request, and returns an
        a protocol object that can interpret it.

        If more bytes than the version prefix of the request are read, they will
        be fed into the protocol before it is returned.

        :returns: a SmartServerRequestProtocol.
        """
        self._wait_for_bytes_with_timeout(self._client_timeout)
        if self.finished:
            # We're stopping, so don't try to do any more work
            return None
        bytes = self._get_line()
        protocol_factory, unused_bytes = _get_protocol_factory_for_bytes(bytes)
        protocol = protocol_factory(
            self.backing_transport, self._write_out, self.root_client_path
        )
        protocol.accept_bytes(unused_bytes)
        return protocol

    def _wait_on_descriptor(self, fd, timeout_seconds):
        """select() on a file descriptor, waiting for nonblocking read()

        This will raise a ConnectionTimeout exception if we do not get a
        readable handle before timeout_seconds.
        :return: None
        """
        t_end = self._timer() + timeout_seconds
        poll_timeout = min(timeout_seconds, self._client_poll_timeout)
        rs = xs = None
        while not rs and not xs and self._timer() < t_end:
            if self.finished:
                return
            try:
                rs, _, xs = select.select([fd], [], [fd], poll_timeout)
            except OSError as e:
                err = getattr(e, "errno", None)
                if err is None and getattr(e, "args", None) is not None:
                    # select.error doesn't have 'errno', it just has args[0]
                    err = e.args[0]
                if err in _bad_file_descriptor:
                    return  # Not a socket indicates read() will fail
                elif err == errno.EINTR:
                    # Interrupted, keep looping.
                    continue
                raise
            except ValueError:
                return  # Socket may already be closed
        if rs or xs:
            return
        raise errors.ConnectionTimeout(
            "disconnecting client after %.1f seconds" % (timeout_seconds,)
        )

    def _serve_one_request(self, protocol):
        """Read one request from input, process, send back a response.

        :param protocol: a SmartServerRequestProtocol.
        """
        if protocol is None:
            return
        try:
            self._serve_one_request_unguarded(protocol)
        except KeyboardInterrupt:
            raise
        except Exception:
            self.terminate_due_to_error()

    def terminate_due_to_error(self):
        """Called when an unhandled exception from the protocol occurs."""
        raise NotImplementedError(self.terminate_due_to_error)

    def _read_bytes(self, desired_count):
        """Get some bytes from the medium.

        :param desired_count: number of bytes we want to read.
        """
        raise NotImplementedError(self._read_bytes)


class SmartServerSocketStreamMedium(SmartServerStreamMedium):
    def __init__(self, sock, backing_transport, root_client_path="/", timeout=None):
        """Constructor.

        :param sock: the socket the server will read from.  It will be put
            into blocking mode.
        """
        SmartServerStreamMedium.__init__(
            self, backing_transport, root_client_path=root_client_path, timeout=timeout
        )
        sock.setblocking(True)
        self.socket = sock
        # Get the getpeername now, as we might be closed later when we care.
        try:
            self._client_info = sock.getpeername()
        except OSError:
            self._client_info = "<unknown>"

    def __str__(self):
        return "{}(client={})".format(self.__class__.__name__, self._client_info)

    def __repr__(self):
        return "{}.{}(client={})".format(
            self.__module__, self.__class__.__name__, self._client_info
        )

    def _serve_one_request_unguarded(self, protocol):
        while protocol.next_read_size():
            # We can safely try to read large chunks.  If there is less data
            # than MAX_SOCKET_CHUNK ready, the socket will just return a
            # short read immediately rather than block.
            bytes = self.read_bytes(osutils.MAX_SOCKET_CHUNK)
            if bytes == b"":
                self.finished = True
                return
            protocol.accept_bytes(bytes)

        self._push_back(protocol.unused_data)

    def _disconnect_client(self):
        """Close the current connection. We stopped due to a timeout/etc."""
        self.socket.close()

    def _wait_for_bytes_with_timeout(self, timeout_seconds):
        """Wait for more bytes to be read, but timeout if none available.

        This allows us to detect idle connections, and stop trying to read from
        them, without setting the socket itself to non-blocking. This also
        allows us to specify when we watch for idle timeouts.

        :return: None, this will raise ConnectionTimeout if we time out before
            data is available.
        """
        return self._wait_on_descriptor(self.socket, timeout_seconds)

    def _read_bytes(self, desired_count):
        return osutils.read_bytes_from_socket(self.socket, self._report_activity)

    def terminate_due_to_error(self):
        # TODO: This should log to a server log file, but no such thing
        # exists yet.  Andrew Bennetts 2006-09-29.
        self.socket.close()
        self.finished = True

    def _write_out(self, bytes):
        tstart = osutils.perf_counter()
        osutils.send_all(self.socket, bytes, self._report_activity)
        if "hpss" in debug.debug_flags:
            thread_id = _thread.get_ident()
            trace.mutter(
                "%12s: [%s] %d bytes to the socket in %.3fs"
                % ("wrote", thread_id, len(bytes), osutils.perf_counter() - tstart)
            )


class SmartServerPipeStreamMedium(SmartServerStreamMedium):
    def __init__(self, in_file, out_file, backing_transport, timeout=None):
        """Construct new server.

        :param in_file: Python file from which requests can be read.
        :param out_file: Python file to write responses.
        :param backing_transport: Transport for the directory served.
        """
        SmartServerStreamMedium.__init__(self, backing_transport, timeout=timeout)
        if sys.platform == "win32":
            # force binary mode for files
            import msvcrt

            for f in (in_file, out_file):
                fileno = getattr(f, "fileno", None)
                if fileno:
                    msvcrt.setmode(fileno(), os.O_BINARY)
        self._in = in_file
        self._out = out_file

    def serve(self):
        """See SmartServerStreamMedium.serve"""
        # This is the regular serve, except it adds signal trapping for soft
        # shutdown.
        stop_gracefully = self._stop_gracefully
        signals.register_on_hangup(id(self), stop_gracefully)
        try:
            return super().serve()
        finally:
            signals.unregister_on_hangup(id(self))

    def _serve_one_request_unguarded(self, protocol):
        while True:
            # We need to be careful not to read past the end of the current
            # request, or else the read from the pipe will block, so we use
            # protocol.next_read_size().
            bytes_to_read = protocol.next_read_size()
            if bytes_to_read == 0:
                # Finished serving this request.
                self._out.flush()
                return
            bytes = self.read_bytes(bytes_to_read)
            if bytes == b"":
                # Connection has been closed.
                self.finished = True
                self._out.flush()
                return
            protocol.accept_bytes(bytes)

    def _disconnect_client(self):
        self._in.close()
        self._out.flush()
        self._out.close()

    def _wait_for_bytes_with_timeout(self, timeout_seconds):
        """Wait for more bytes to be read, but timeout if none available.

        This allows us to detect idle connections, and stop trying to read from
        them, without setting the socket itself to non-blocking. This also
        allows us to specify when we watch for idle timeouts.

        :return: None, this will raise ConnectionTimeout if we time out before
            data is available.
        """
        if getattr(self._in, "fileno", None) is None or sys.platform == "win32":
            # You can't select() file descriptors on Windows.
            return
        try:
            return self._wait_on_descriptor(self._in, timeout_seconds)
        except io.UnsupportedOperation:
            return

    def _read_bytes(self, desired_count):
        return self._in.read(desired_count)

    def terminate_due_to_error(self):
        # TODO: This should log to a server log file, but no such thing
        # exists yet.  Andrew Bennetts 2006-09-29.
        self._out.close()
        self.finished = True

    def _write_out(self, bytes):
        self._out.write(bytes)


class SmartClientMediumRequest:
    """A request on a SmartClientMedium.

    Each request allows bytes to be provided to it via accept_bytes, and then
    the response bytes to be read via read_bytes.

    For instance:
    request.accept_bytes('123')
    request.finished_writing()
    result = request.read_bytes(3)
    request.finished_reading()

    It is up to the individual SmartClientMedium whether multiple concurrent
    requests can exist. See SmartClientMedium.get_request to obtain instances
    of SmartClientMediumRequest, and the concrete Medium you are using for
    details on concurrency and pipelining.
    """

    def __init__(self, medium):
        """Construct a SmartClientMediumRequest for the medium medium."""
        self._medium = medium
        # we track state by constants - we may want to use the same
        # pattern as BodyReader if it gets more complex.
        # valid states are: "writing", "reading", "done"
        self._state = "writing"

    def accept_bytes(self, bytes):
        """Accept bytes for inclusion in this request.

        This method may not be called after finished_writing() has been
        called.  It depends upon the Medium whether or not the bytes will be
        immediately transmitted. Message based Mediums will tend to buffer the
        bytes until finished_writing() is called.

        :param bytes: A bytestring.
        """
        if self._state != "writing":
            raise errors.WritingCompleted(self)
        self._accept_bytes(bytes)

    def _accept_bytes(self, bytes):
        """Helper for accept_bytes.

        Accept_bytes checks the state of the request to determing if bytes
        should be accepted. After that it hands off to _accept_bytes to do the
        actual acceptance.
        """
        raise NotImplementedError(self._accept_bytes)

    def finished_reading(self):
        """Inform the request that all desired data has been read.

        This will remove the request from the pipeline for its medium (if the
        medium supports pipelining) and any further calls to methods on the
        request will raise ReadingCompleted.
        """
        if self._state == "writing":
            raise errors.WritingNotComplete(self)
        if self._state != "reading":
            raise errors.ReadingCompleted(self)
        self._state = "done"
        self._finished_reading()

    def _finished_reading(self):
        """Helper for finished_reading.

        finished_reading checks the state of the request to determine if
        finished_reading is allowed, and if it is hands off to _finished_reading
        to perform the action.
        """
        raise NotImplementedError(self._finished_reading)

    def finished_writing(self):
        """Finish the writing phase of this request.

        This will flush all pending data for this request along the medium.
        After calling finished_writing, you may not call accept_bytes anymore.
        """
        if self._state != "writing":
            raise errors.WritingCompleted(self)
        self._state = "reading"
        self._finished_writing()

    def _finished_writing(self):
        """Helper for finished_writing.

        finished_writing checks the state of the request to determine if
        finished_writing is allowed, and if it is hands off to _finished_writing
        to perform the action.
        """
        raise NotImplementedError(self._finished_writing)

    def read_bytes(self, count):
        """Read bytes from this requests response.

        This method will block and wait for count bytes to be read. It may not
        be invoked until finished_writing() has been called - this is to ensure
        a message-based approach to requests, for compatibility with message
        based mediums like HTTP.
        """
        if self._state == "writing":
            raise errors.WritingNotComplete(self)
        if self._state != "reading":
            raise errors.ReadingCompleted(self)
        return self._read_bytes(count)

    def _read_bytes(self, count):
        """Helper for SmartClientMediumRequest.read_bytes.

        read_bytes checks the state of the request to determing if bytes
        should be read. After that it hands off to _read_bytes to do the
        actual read.

        By default this forwards to self._medium.read_bytes because we are
        operating on the medium's stream.
        """
        return self._medium.read_bytes(count)

    def read_line(self):
        line = self._read_line()
        if not line.endswith(b"\n"):
            # end of file encountered reading from server
            raise errors.ConnectionReset(
                "Unexpected end of message. Please check connectivity "
                "and permissions, and report a bug if problems persist."
            )
        return line

    def _read_line(self):
        """Helper for SmartClientMediumRequest.read_line.

        By default this forwards to self._medium._get_line because we are
        operating on the medium's stream.
        """
        return self._medium._get_line()


class _VfsRefuser:
    """An object that refuses all VFS requests."""

    def __init__(self):
        client._SmartClient.hooks.install_named_hook(
            "call", self.check_vfs, "vfs refuser"
        )

    def check_vfs(self, params):
        try:
            request_method = request.request_handlers.get(params.method)
        except KeyError:
            # A method we don't know about doesn't count as a VFS method.
            return
        if issubclass(request_method, vfs.VfsRequest):
            raise HpssVfsRequestNotAllowed(params.method, params.args)


class _DebugCounter:
    """An object that counts the HPSS calls made to each client medium.

    When a medium is garbage-collected, or failing that when
    breezy.global_state exits, the total number of calls made on that medium
    are reported via trace.note.
    """

    def __init__(self):
        self.counts = weakref.WeakKeyDictionary()
        client._SmartClient.hooks.install_named_hook(
            "call", self.increment_call_count, "hpss call counter"
        )
        breezy.get_global_state().exit_stack.callback(self.flush_all)

    def track(self, medium):
        """Start tracking calls made to a medium.

        This only keeps a weakref to the medium, so shouldn't affect the
        medium's lifetime.
        """
        medium_repr = repr(medium)
        # Add this medium to the WeakKeyDictionary
        self.counts[medium] = dict(count=0, vfs_count=0, medium_repr=medium_repr)
        # Weakref callbacks are fired in reverse order of their association
        # with the referenced object.  So we add a weakref *after* adding to
        # the WeakKeyDict so that we can report the value from it before the
        # entry is removed by the WeakKeyDict's own callback.
        ref = weakref.ref(medium, self.done)

    def increment_call_count(self, params):
        # Increment the count in the WeakKeyDictionary
        value = self.counts[params.medium]
        value["count"] += 1
        try:
            request_method = request.request_handlers.get(params.method)
        except KeyError:
            # A method we don't know about doesn't count as a VFS method.
            return
        if issubclass(request_method, vfs.VfsRequest):
            value["vfs_count"] += 1

    def done(self, ref):
        value = self.counts[ref]
        count, vfs_count, medium_repr = (
            value["count"],
            value["vfs_count"],
            value["medium_repr"],
        )
        # In case this callback is invoked for the same ref twice (by the
        # weakref callback and by the atexit function), set the call count back
        # to 0 so this item won't be reported twice.
        value["count"] = 0
        value["vfs_count"] = 0
        if count != 0:
            trace.note(
                gettext("HPSS calls: {0} ({1} vfs) {2}").format(
                    count, vfs_count, medium_repr
                )
            )

    def flush_all(self):
        for ref in list(self.counts.keys()):
            self.done(ref)


_debug_counter = None
_vfs_refuser = None


class SmartClientMedium(SmartMedium):
    """Smart client is a medium for sending smart protocol requests over."""

    def __init__(self, base):
        super().__init__()
        self.base = base
        self._protocol_version_error = None
        self._protocol_version = None
        self._done_hello = False
        # Be optimistic: we assume the remote end can accept new remote
        # requests until we get an error saying otherwise.
        # _remote_version_is_before tracks the bzr version the remote side
        # can be based on what we've seen so far.
        self._remote_version_is_before = None
        # Install debug hook function if debug flag is set.
        if "hpss" in debug.debug_flags:
            global _debug_counter
            if _debug_counter is None:
                _debug_counter = _DebugCounter()
            _debug_counter.track(self)
        if "hpss_client_no_vfs" in debug.debug_flags:
            global _vfs_refuser
            if _vfs_refuser is None:
                _vfs_refuser = _VfsRefuser()

    def _is_remote_before(self, version_tuple):
        """Is it possible the remote side supports RPCs for a given version?

        Typical use::

            needed_version = (1, 2)
            if medium._is_remote_before(needed_version):
                fallback_to_pre_1_2_rpc()
            else:
                try:
                    do_1_2_rpc()
                except UnknownSmartMethod:
                    medium._remember_remote_is_before(needed_version)
                    fallback_to_pre_1_2_rpc()

        :seealso: _remember_remote_is_before
        """
        if self._remote_version_is_before is None:
            # So far, the remote side seems to support everything
            return False
        return version_tuple >= self._remote_version_is_before

    def _remember_remote_is_before(self, version_tuple):
        """Tell this medium that the remote side is older the given version.

        :seealso: _is_remote_before
        """
        if (
            self._remote_version_is_before is not None
            and version_tuple > self._remote_version_is_before
        ):
            # We have been told that the remote side is older than some version
            # which is newer than a previously supplied older-than version.
            # This indicates that some smart verb call is not guarded
            # appropriately (it should simply not have been tried).
            trace.mutter(
                "_remember_remote_is_before(%r) called, but "
                "_remember_remote_is_before(%r) was called previously.",
                version_tuple,
                self._remote_version_is_before,
            )
            if "hpss" in debug.debug_flags:
                ui.ui_factory.show_warning(
                    "_remember_remote_is_before(%r) called, but "
                    "_remember_remote_is_before(%r) was called previously."
                    % (version_tuple, self._remote_version_is_before)
                )
            return
        self._remote_version_is_before = version_tuple

    def protocol_version(self):
        """Find out if 'hello' smart request works."""
        if self._protocol_version_error is not None:
            raise self._protocol_version_error
        if not self._done_hello:
            try:
                medium_request = self.get_request()
                # Send a 'hello' request in protocol version one, for maximum
                # backwards compatibility.
                client_protocol = protocol.SmartClientRequestProtocolOne(medium_request)
                client_protocol.query_version()
                self._done_hello = True
            except errors.SmartProtocolError as e:
                # Cache the error, just like we would cache a successful
                # result.
                self._protocol_version_error = e
                raise
        return "2"

    def should_probe(self):
        """Should RemoteBzrDirFormat.probe_transport send a smart request on
        this medium?

        Some transports are unambiguously smart-only; there's no need to check
        if the transport is able to carry smart requests, because that's all
        it is for.  In those cases, this method should return False.

        But some HTTP transports can sometimes fail to carry smart requests,
        but still be usuable for accessing remote bzrdirs via plain file
        accesses.  So for those transports, their media should return True here
        so that RemoteBzrDirFormat can determine if it is appropriate for that
        transport.
        """
        return False

    def disconnect(self):
        """If this medium maintains a persistent connection, close it.

        The default implementation does nothing.
        """

    def remote_path_from_transport(self, transport):
        """Convert transport into a path suitable for using in a request.

        Note that the resulting remote path doesn't encode the host name or
        anything but path, so it is only safe to use it in requests sent over
        the medium from the matching transport.
        """
        medium_base = urlutils.join(self.base, "/")
        rel_url = urlutils.relative_url(medium_base, transport.base)
        return urlutils.unquote(rel_url)


class SmartClientStreamMedium(SmartClientMedium):
    """Stream based medium common class.

    SmartClientStreamMediums operate on a stream. All subclasses use a common
    SmartClientStreamMediumRequest for their requests, and should implement
    _accept_bytes and _read_bytes to allow the request objects to send and
    receive bytes.
    """

    def __init__(self, base):
        SmartClientMedium.__init__(self, base)
        self._current_request = None

    def accept_bytes(self, bytes):
        self._accept_bytes(bytes)

    def __del__(self):
        """The SmartClientStreamMedium knows how to close the stream when it is
        finished with it.
        """
        self.disconnect()

    def _flush(self):
        """Flush the output stream.

        This method is used by the SmartClientStreamMediumRequest to ensure that
        all data for a request is sent, to avoid long timeouts or deadlocks.
        """
        raise NotImplementedError(self._flush)

    def get_request(self):
        """See SmartClientMedium.get_request().

        SmartClientStreamMedium always returns a SmartClientStreamMediumRequest
        for get_request.
        """
        return SmartClientStreamMediumRequest(self)

    def reset(self):
        """We have been disconnected, reset current state.

        This resets things like _current_request and connected state.
        """
        self.disconnect()
        self._current_request = None


class SmartSimplePipesClientMedium(SmartClientStreamMedium):
    """A client medium using simple pipes.

    This client does not manage the pipes: it assumes they will always be open.
    """

    def __init__(self, readable_pipe, writeable_pipe, base):
        SmartClientStreamMedium.__init__(self, base)
        self._readable_pipe = readable_pipe
        self._writeable_pipe = writeable_pipe

    def _accept_bytes(self, data):
        """See SmartClientStreamMedium.accept_bytes."""
        try:
            self._writeable_pipe.write(data)
        except OSError as e:
            if e.errno in (errno.EINVAL, errno.EPIPE):
                raise errors.ConnectionReset("Error trying to write to subprocess", e)
            raise
        self._report_activity(len(data), "write")

    def _flush(self):
        """See SmartClientStreamMedium._flush()."""
        # Note: If flush were to fail, we'd like to raise ConnectionReset, etc.
        #       However, testing shows that even when the child process is
        #       gone, this doesn't error.
        self._writeable_pipe.flush()

    def _read_bytes(self, count):
        """See SmartClientStreamMedium._read_bytes."""
        bytes_to_read = min(count, _MAX_READ_SIZE)
        data = self._readable_pipe.read(bytes_to_read)
        self._report_activity(len(data), "read")
        return data


class SSHParams:
    """A set of parameters for starting a remote bzr via SSH."""

    def __init__(
        self, host, port=None, username=None, password=None, bzr_remote_path="bzr"
    ):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.bzr_remote_path = bzr_remote_path


class SmartSSHClientMedium(SmartClientStreamMedium):
    """A client medium using SSH.

    It delegates IO to a SmartSimplePipesClientMedium or
    SmartClientAlreadyConnectedSocketMedium (depending on platform).
    """

    def __init__(self, base, ssh_params, vendor=None):
        """Creates a client that will connect on the first use.

        :param ssh_params: A SSHParams instance.
        :param vendor: An optional override for the ssh vendor to use. See
            breezy.transport.ssh for details on ssh vendors.
        """
        self._real_medium = None
        self._ssh_params = ssh_params
        # for the benefit of progress making a short description of this
        # transport
        self._scheme = "bzr+ssh"
        # SmartClientStreamMedium stores the repr of this object in its
        # _DebugCounter so we have to store all the values used in our repr
        # method before calling the super init.
        SmartClientStreamMedium.__init__(self, base)
        self._vendor = vendor
        self._ssh_connection = None

    def __repr__(self):
        if self._ssh_params.port is None:
            maybe_port = ""
        else:
            maybe_port = ":%s" % self._ssh_params.port
        if self._ssh_params.username is None:
            maybe_user = ""
        else:
            maybe_user = "%s@" % self._ssh_params.username
        return "{}({}://{}{}{}/)".format(
            self.__class__.__name__,
            self._scheme,
            maybe_user,
            self._ssh_params.host,
            maybe_port,
        )

    def _accept_bytes(self, bytes):
        """See SmartClientStreamMedium.accept_bytes."""
        self._ensure_connection()
        self._real_medium.accept_bytes(bytes)

    def disconnect(self):
        """See SmartClientMedium.disconnect()."""
        if self._real_medium is not None:
            self._real_medium.disconnect()
            self._real_medium = None
        if self._ssh_connection is not None:
            self._ssh_connection.close()
            self._ssh_connection = None

    def _ensure_connection(self):
        """Connect this medium if not already connected."""
        if self._real_medium is not None:
            return
        if self._vendor is None:
            vendor = ssh._get_ssh_vendor()
        else:
            vendor = self._vendor
        self._ssh_connection = vendor.connect_ssh(
            self._ssh_params.username,
            self._ssh_params.password,
            self._ssh_params.host,
            self._ssh_params.port,
            command=[
                self._ssh_params.bzr_remote_path,
                "serve",
                "--inet",
                "--directory=/",
                "--allow-writes",
            ],
        )
        io_kind, io_object = self._ssh_connection.get_sock_or_pipes()
        if io_kind == "socket":
            self._real_medium = SmartClientAlreadyConnectedSocketMedium(
                self.base, io_object
            )
        elif io_kind == "pipes":
            read_from, write_to = io_object
            self._real_medium = SmartSimplePipesClientMedium(
                read_from, write_to, self.base
            )
        else:
            raise AssertionError(
                "Unexpected io_kind %r from %r" % (io_kind, self._ssh_connection)
            )
        for hook in transport.Transport.hooks["post_connect"]:
            hook(self)

    def _flush(self):
        """See SmartClientStreamMedium._flush()."""
        self._real_medium._flush()

    def _read_bytes(self, count):
        """See SmartClientStreamMedium.read_bytes."""
        if self._real_medium is None:
            raise errors.MediumNotConnected(self)
        return self._real_medium.read_bytes(count)


# Port 4155 is the default port for bzr://, registered with IANA.
BZR_DEFAULT_INTERFACE = None
BZR_DEFAULT_PORT = 4155


class SmartClientSocketMedium(SmartClientStreamMedium):
    """A client medium using a socket.

    This class isn't usable directly.  Use one of its subclasses instead.
    """

    def __init__(self, base):
        SmartClientStreamMedium.__init__(self, base)
        self._socket = None
        self._connected = False

    def _accept_bytes(self, bytes):
        """See SmartClientMedium.accept_bytes."""
        self._ensure_connection()
        osutils.send_all(self._socket, bytes, self._report_activity)

    def _ensure_connection(self):
        """Connect this medium if not already connected."""
        raise NotImplementedError(self._ensure_connection)

    def _flush(self):
        """See SmartClientStreamMedium._flush().

        For sockets we do no flushing. For TCP sockets we may want to turn off
        TCP_NODELAY and add a means to do a flush, but that can be done in the
        future.
        """

    def _read_bytes(self, count):
        """See SmartClientMedium.read_bytes."""
        if not self._connected:
            raise errors.MediumNotConnected(self)
        return osutils.read_bytes_from_socket(self._socket, self._report_activity)

    def disconnect(self):
        """See SmartClientMedium.disconnect()."""
        if not self._connected:
            return
        self._socket.close()
        self._socket = None
        self._connected = False


class SmartTCPClientMedium(SmartClientSocketMedium):
    """A client medium that creates a TCP connection."""

    def __init__(self, host, port, base):
        """Creates a client that will connect on the first use."""
        SmartClientSocketMedium.__init__(self, base)
        self._host = host
        self._port = port

    def _ensure_connection(self):
        """Connect this medium if not already connected."""
        if self._connected:
            return
        if self._port is None:
            port = BZR_DEFAULT_PORT
        else:
            port = int(self._port)
        try:
            sockaddrs = socket.getaddrinfo(
                self._host, port, socket.AF_UNSPEC, socket.SOCK_STREAM, 0, 0
            )
        except socket.gaierror as xxx_todo_changeme:
            (err_num, err_msg) = xxx_todo_changeme.args
            raise errors.ConnectionError(
                "failed to lookup %s:%d: %s" % (self._host, port, err_msg)
            )
        # Initialize err in case there are no addresses returned:
        last_err = socket.error("no address found for %s" % self._host)
        for family, socktype, proto, canonname, sockaddr in sockaddrs:
            try:
                self._socket = socket.socket(family, socktype, proto)
                self._socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                self._socket.connect(sockaddr)
            except OSError as err:
                if self._socket is not None:
                    self._socket.close()
                self._socket = None
                last_err = err
                continue
            break
        if self._socket is None:
            # socket errors either have a (string) or (errno, string) as their
            # args.
            if isinstance(last_err.args, str):
                err_msg = last_err.args
            else:
                err_msg = last_err.args[1]
            raise errors.ConnectionError(
                "failed to connect to %s:%d: %s" % (self._host, port, err_msg)
            )
        self._connected = True
        for hook in transport.Transport.hooks["post_connect"]:
            hook(self)


class SmartClientAlreadyConnectedSocketMedium(SmartClientSocketMedium):
    """A client medium for an already connected socket.

    Note that this class will assume it "owns" the socket, so it will close it
    when its disconnect method is called.
    """

    def __init__(self, base, sock):
        SmartClientSocketMedium.__init__(self, base)
        self._socket = sock
        self._connected = True

    def _ensure_connection(self):
        # Already connected, by definition!  So nothing to do.
        pass


class TooManyConcurrentRequests(errors.InternalBzrError):
    _fmt = (
        "The medium '%(medium)s' has reached its concurrent request limit."
        " Be sure to finish_writing and finish_reading on the"
        " currently open request."
    )

    def __init__(self, medium):
        self.medium = medium


class SmartClientStreamMediumRequest(SmartClientMediumRequest):
    """A SmartClientMediumRequest that works with an SmartClientStreamMedium."""

    def __init__(self, medium):
        SmartClientMediumRequest.__init__(self, medium)
        # check that we are safe concurrency wise. If some streams start
        # allowing concurrent requests - i.e. via multiplexing - then this
        # assert should be moved to SmartClientStreamMedium.get_request,
        # and the setting/unsetting of _current_request likewise moved into
        # that class : but its unneeded overhead for now. RBC 20060922
        if self._medium._current_request is not None:
            raise TooManyConcurrentRequests(self._medium)
        self._medium._current_request = self

    def _accept_bytes(self, bytes):
        """See SmartClientMediumRequest._accept_bytes.

        This forwards to self._medium._accept_bytes because we are operating
        on the mediums stream.
        """
        self._medium._accept_bytes(bytes)

    def _finished_reading(self):
        """See SmartClientMediumRequest._finished_reading.

        This clears the _current_request on self._medium to allow a new
        request to be created.
        """
        if self._medium._current_request is not self:
            raise AssertionError()
        self._medium._current_request = None

    def _finished_writing(self):
        """See SmartClientMediumRequest._finished_writing.

        This invokes self._medium._flush to ensure all bytes are transmitted.
        """
        self._medium._flush()
