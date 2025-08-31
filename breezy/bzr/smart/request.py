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

"""Infrastructure for server-side request handlers.

Interesting module attributes:
    * The request_handlers registry maps verb names to SmartServerRequest
      classes.
    * The jail_info threading.local() object is used to prevent accidental
      opening of BzrDirs outside of the backing transport, or any other
      transports placed in jail_info.transports.  The jail_info is reset on
      every call into a request handler (which can happen an arbitrary number
      of times during a request).
"""

# XXX: The class names are a little confusing: the protocol will instantiate a
# SmartServerRequestHandler, whose dispatch_command method creates an instance
# of a SmartServerRequest subclass.

import threading
from _thread import get_ident

from vcsgraph.errors import GhostRevisionsHaveNoRevno

from ... import branch as _mod_branch
from ... import debug, errors, osutils, registry, revision, trace, urlutils
from ... import transport as _mod_transport

jail_info = threading.local()
jail_info.transports = None


class DisabledMethod(errors.InternalBzrError):
    """Exception raised when a smart server method is disabled.

    This exception is used to indicate that a particular smart server
    request handler method has been disabled and cannot be used.

    Attributes:
        class_name: The name of the disabled method class.
    """

    _fmt = "The smart server method '%(class_name)s' is disabled."

    def __init__(self, class_name):
        """Initialize DisabledMethod exception.

        Args:
            class_name: The name of the disabled method class.
        """
        errors.BzrError.__init__(self)
        self.class_name = class_name


def _install_hook():
    """Install the pre-open hook for jail security.

    This function installs a hook that will be called before opening
    any BzrDir, to ensure that the server jail restrictions are enforced.
    """
    from breezy.bzr import bzrdir

    bzrdir.BzrDir.hooks.install_named_hook(
        "pre_open", _pre_open_hook, "checking server jail"
    )


def _pre_open_hook(transport):
    """Hook function to check if a transport is within the allowed jail.

    This function is called before opening a BzrDir to ensure that the
    transport being accessed is within the allowed jail boundaries. If the
    transport is outside the jail, a JailBreak error is raised.

    Args:
        transport: The transport being opened.

    Raises:
        JailBreak: If the transport is outside the allowed jail.
    """
    allowed_transports = getattr(jail_info, "transports", None)
    if allowed_transports is None:
        return
    abspath = transport.base
    for allowed_transport in allowed_transports:
        try:
            allowed_transport.relpath(abspath)
        except errors.PathNotChild:
            continue
        else:
            return
    raise errors.JailBreak(abspath)


_install_hook()


class SmartServerRequest:
    """Base class for request handlers.

    To define a new request, subclass this class and override the `do` method
    (and if appropriate, `do_body` as well).  Request implementors should take
    care to call `translate_client_path` and `transport_from_client_path` as
    appropriate when dealing with paths received from the client.
    """

    # XXX: rename this class to BaseSmartServerRequestHandler ?  A request
    # *handler* is a different concept to the request.

    def __init__(self, backing_transport, root_client_path="/", jail_root=None):
        """Constructor.

        :param backing_transport: the base transport to be used when performing
            this request.
        :param root_client_path: the client path that maps to the root of
            backing_transport.  This is used to interpret relpaths received
            from the client.  Clients will not be able to refer to paths above
            this root.  If root_client_path is None, then no translation will
            be performed on client paths.  Default is '/'.
        :param jail_root: if specified, the root of the BzrDir.open jail to use
            instead of backing_transport.
        """
        self._backing_transport = backing_transport
        if jail_root is None:
            jail_root = backing_transport
        self._jail_root = jail_root
        if root_client_path is not None:
            if not root_client_path.startswith("/"):
                root_client_path = "/" + root_client_path
            if not root_client_path.endswith("/"):
                root_client_path += "/"
        self._root_client_path = root_client_path
        self._body_chunks = []

    def _check_enabled(self):
        """Check if this request method is enabled.

        Subclasses can override this method to implement specific
        enabling/disabling logic. By default, all methods are enabled.

        Raises:
            DisabledMethod: If this method has been disabled.
        """
        pass

    def do(self, *args):
        """Mandatory extension point for SmartServerRequest subclasses.

        Subclasses must implement this.

        This should return a SmartServerResponse if this command expects to
        receive no body.
        """
        raise NotImplementedError(self.do)

    def execute(self, *args):
        """Public entry point to execute this request.

        It will return a SmartServerResponse if the command does not expect a
        body.

        :param args: the arguments of the request.
        """
        self._check_enabled()
        return self.do(*args)

    def do_body(self, body_bytes):
        """Called if the client sends a body with the request.

        The do() method is still called, and must have returned None.

        Must return a SmartServerResponse.
        """
        if body_bytes != b"":
            raise errors.SmartProtocolError("Request does not expect a body")

    def do_chunk(self, chunk_bytes):
        """Process a chunk of streamed body data.

        This method is called for each chunk of data when the request
        has a streamed body. The chunks are accumulated and will be
        processed together when do_end() is called.

        The do() method is still called first, and must have returned None
        to indicate that a body is expected.

        Args:
            chunk_bytes: A chunk of body data as bytes.
        """
        self._body_chunks.append(chunk_bytes)

    def do_end(self):
        """Handle the end of a request with a body.

        This method is called when all chunks of a request body have been
        received. It concatenates all the chunks and passes them to do_body().

        Returns:
            SmartServerResponse: The response from processing the complete body.
        """
        body_bytes = b"".join(self._body_chunks)
        self._body_chunks = None
        return self.do_body(body_bytes)

    def setup_jail(self):
        """Set up the jail for this request.

        This method configures the jail to restrict file access to only
        the paths under self._jail_root. This prevents the request from
        accessing files outside its designated area.
        """
        jail_info.transports = [self._jail_root]

    def teardown_jail(self):
        """Tear down the jail after request processing.

        This method removes the jail restrictions that were set up by
        setup_jail(), allowing normal file access again.
        """
        jail_info.transports = None

    def translate_client_path(self, client_path):
        """Translate a path received from a network client into a local
        relpath.

        All paths received from the client *must* be translated.

        :param client_path: the path from the client.
        :returns: a relpath that may be used with self._backing_transport
            (unlike the untranslated client_path, which must not be used with
            the backing transport).
        """
        client_path = client_path.decode("utf-8")
        if self._root_client_path is None:
            # no translation necessary!
            return client_path
        if not client_path.startswith("/"):
            client_path = "/" + client_path
        if client_path + "/" == self._root_client_path:
            return "."
        if client_path.startswith(self._root_client_path):
            path = client_path[len(self._root_client_path) :]
            relpath = urlutils.joinpath("/", path)
            if not relpath.startswith("/"):
                raise ValueError(relpath)
            return urlutils.escape("." + relpath)
        else:
            raise errors.PathNotChild(client_path, self._root_client_path)

    def transport_from_client_path(self, client_path):
        """Get a backing transport corresponding to the location referred to by
        a network client.

        :seealso: translate_client_path
        :returns: a transport cloned from self._backing_transport
        """
        relpath = self.translate_client_path(client_path)
        return self._backing_transport.clone(relpath)


class SmartServerResponse:
    """A response to a client request.

    This base class should not be used. Instead use
    SuccessfulSmartServerResponse and FailedSmartServerResponse as appropriate.
    """

    def __init__(self, args, body=None, body_stream=None):
        """Constructor.

        :param args: tuple of response arguments.
        :param body: string of a response body.
        :param body_stream: iterable of bytestrings to be streamed to the
            client.
        """
        self.args = args
        if body is not None and body_stream is not None:
            raise errors.BzrError("'body' and 'body_stream' are mutually exclusive.")
        self.body = body
        self.body_stream = body_stream

    def __eq__(self, other):
        """Compare two SmartServerResponse objects for equality.

        Args:
            other: Another object to compare with.

        Returns:
            bool: True if the responses are equal, False otherwise.
        """
        if other is None:
            return False
        return (
            other.args == self.args
            and other.body == self.body
            and other.body_stream is self.body_stream
        )

    def __repr__(self):
        """Return a string representation of the response.

        Returns:
            str: A string representation showing the class name, args, and body.
        """
        return f"<{self.__class__.__name__} args={self.args!r} body={self.body!r}>"


class FailedSmartServerResponse(SmartServerResponse):
    """A SmartServerResponse for a request which failed."""

    def is_successful(self):
        """Check if this response represents a successful operation.

        Returns:
            bool: Always False for failed responses.
        """
        return False


class SuccessfulSmartServerResponse(SmartServerResponse):
    """A SmartServerResponse for a successfully completed request."""

    def is_successful(self):
        """Check if this response represents a successful operation.

        Returns:
            bool: Always True for successful responses.
        """
        return True


class SmartServerRequestHandler:
    """Protocol logic for smart server.

    This doesn't handle serialization at all, it just processes requests and
    creates responses.
    """

    # IMPORTANT FOR IMPLEMENTORS: It is important that SmartServerRequestHandler
    # not contain encoding or decoding logic to allow the wire protocol to vary
    # from the object protocol: we will want to tweak the wire protocol separate
    # from the object model, and ideally we will be able to do that without
    # having a SmartServerRequestHandler subclass for each wire protocol, rather
    # just a Protocol subclass.

    # TODO: Better way of representing the body for commands that take it,
    # and allow it to be streamed into the server.

    def __init__(self, backing_transport, commands, root_client_path, jail_root=None):
        """Constructor.

        :param backing_transport: a Transport to handle requests for.
        :param commands: a registry mapping command names to SmartServerRequest
            subclasses. e.g. breezy.transport.smart.vfs.vfs_commands.
        """
        self._backing_transport = backing_transport
        self._root_client_path = root_client_path
        self._commands = commands
        if jail_root is None:
            jail_root = backing_transport
        self._jail_root = jail_root
        self.response = None
        self.finished_reading = False
        self._command = None
        if debug.debug_flag_enabled("hpss"):
            self._request_start_time = osutils.perf_counter()
            self._thread_id = get_ident()

    def _trace(self, action, message, extra_bytes=None, include_time=False):
        """Log trace information for debugging.

        This method logs debugging information about request processing when
        the 'hpss' debug flag is enabled. It includes thread ID, timing
        information, and optional byte data.

        Args:
            action: The action being performed (e.g., 'accept body', 'end').
            message: The main message to log.
            extra_bytes: Optional bytes to include in the trace (truncated to 40 chars).
            include_time: If True, include elapsed time since request start.
        """
        # It is a bit of a shame that this functionality overlaps with that of
        # ProtocolThreeRequester._trace. However, there is enough difference
        # that just putting it in a helper doesn't help a lot. And some state
        # is taken from the instance.
        if include_time:
            t = f"{osutils.perf_counter() - self._request_start_time:5.3f}s "
        else:
            t = ""
        if extra_bytes is None:
            extra = ""
        else:
            extra = " " + repr(extra_bytes[:40])
            if len(extra) > 33:
                extra = extra[:29] + extra[-1] + "..."
        trace.mutter("%12s: [%s] %s%s%s" % (action, self._thread_id, t, message, extra))

    def accept_body(self, bytes):
        """Accept and process body data for the current request.

        This method is called when body data is received for a request.
        It passes the data to the current command's do_chunk method.

        Args:
            bytes: The body data received.
        """
        if self._command is None:
            # no active command object, so ignore the event.
            return
        self._run_handler_code(self._command.do_chunk, (bytes,), {})
        if debug.debug_flag_enabled("hpss"):
            self._trace("accept body", f"{len(bytes)} bytes", bytes)

    def end_of_body(self):
        """Handle the end of body data reception.

        This method is called when all body data has been received.
        It triggers the command's do_end method and marks the request
        as finished reading.
        """
        self._run_handler_code(self._command.do_end, (), {})
        # cannot read after this.
        self.finished_reading = True
        if debug.debug_flag_enabled("hpss"):
            self._trace("end of body", "", include_time=True)

    def _run_handler_code(self, callable, args, kwargs):
        """Execute handler code with error handling.

        This method runs the specified callable with the given arguments,
        catching and converting any exceptions into response objects.
        If the callable returns a result, it becomes the response and
        marks the request as finished.

        Args:
            callable: The function or method to call.
            args: Positional arguments for the callable.
            kwargs: Keyword arguments for the callable.
        """
        result = self._call_converting_errors(callable, args, kwargs)

        if result is not None:
            self.response = result
            self.finished_reading = True

    def _call_converting_errors(self, callable, args, kwargs):
        """Call a function and convert exceptions to response objects.

        This method sets up the jail, calls the specified function, and
        ensures the jail is torn down afterwards. Any exceptions (except
        KeyboardInterrupt and SystemExit) are caught and converted to
        FailedSmartServerResponse objects.

        Args:
            callable: The function or method to call.
            args: Positional arguments for the callable.
            kwargs: Keyword arguments for the callable.

        Returns:
            The result of the callable, or a FailedSmartServerResponse
            if an exception occurred.
        """
        # XXX: most of this error conversion is VFS-related, and thus ought to
        # be in SmartServerVFSRequestHandler somewhere.
        try:
            self._command.setup_jail()
            try:
                return callable(*args, **kwargs)
            finally:
                self._command.teardown_jail()
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as err:
            err_struct = _translate_error(err)
            return FailedSmartServerResponse(err_struct)

    def headers_received(self, headers):
        """Handle receipt of request headers.

        Currently this is a no-op that only logs the headers when
        debugging is enabled.

        Args:
            headers: The headers received with the request.
        """
        # Just a no-op at the moment.
        if debug.debug_flag_enabled("hpss"):
            self._trace("headers", repr(headers))

    def args_received(self, args):
        """Process received request arguments.

        This method looks up the appropriate command handler based on the
        first argument (the command name), creates an instance of it, and
        executes it with the remaining arguments.

        Args:
            args: Tuple of arguments, where args[0] is the command name
                  and args[1:] are the command arguments.

        Raises:
            UnknownSmartMethod: If the command is not recognized.
        """
        cmd = args[0]
        args = args[1:]
        try:
            command = self._commands.get(cmd)
        except LookupError as e:
            if debug.debug_flag_enabled("hpss"):
                self._trace("hpss unknown request", cmd, repr(args)[1:-1])
            raise errors.UnknownSmartMethod(cmd) from e
        if debug.debug_flag_enabled("hpss"):
            from . import vfs

            if issubclass(command, vfs.VfsRequest):
                action = "hpss vfs req"
            else:
                action = "hpss request"
            self._trace(action, f"{cmd} {repr(args)[1:-1]}")
        self._command = command(
            self._backing_transport, self._root_client_path, self._jail_root
        )
        self._run_handler_code(self._command.execute, args, {})

    def end_received(self):
        """Handle the end of request marker.

        This method is called when an end-of-request marker is received.
        It triggers the command's do_end method if a command is active.
        """
        if self._command is None:
            # no active command object, so ignore the event.
            return
        self._run_handler_code(self._command.do_end, (), {})
        if debug.debug_flag_enabled("hpss"):
            self._trace("end", "", include_time=True)

    def post_body_error_received(self, error_args):
        """Handle post-body error notifications.

        This method is called when an error occurs after the body has
        been sent. Currently it's a no-op.

        Args:
            error_args: Arguments describing the error.
        """
        # Just a no-op at the moment.
        pass


def _translate_error(err):
    """Translate Python exceptions into smart protocol error tuples.

    This function converts various exception types into tuples that can
    be serialized and sent over the smart protocol. The first element
    of the tuple is always the error type name as bytes.

    Args:
        err: The exception to translate.

    Returns:
        tuple: A tuple representing the error in a format suitable for
               the smart protocol. The exact format depends on the error type.
    """
    if isinstance(err, _mod_transport.NoSuchFile):
        return (b"NoSuchFile", err.path.encode("utf-8"))
    elif isinstance(err, _mod_transport.FileExists):
        return (b"FileExists", err.path.encode("utf-8"))
    elif isinstance(err, errors.DirectoryNotEmpty):
        return (b"DirectoryNotEmpty", err.path.encode("utf-8"))
    elif isinstance(err, errors.IncompatibleRepositories):
        return (
            b"IncompatibleRepositories",
            str(err.source),
            str(err.target),
            str(err.details),
        )
    elif isinstance(err, errors.ShortReadvError):
        return (
            b"ShortReadvError",
            err.path.encode("utf-8") if err.path is not None else None,
            str(err.offset).encode("ascii") if err.offset is not None else None,
            str(err.length).encode("ascii") if err.length is not None else None,
            str(err.actual).encode("ascii") if err.actual is not None else None,
        )
    elif isinstance(err, errors.RevisionNotPresent):
        return (b"RevisionNotPresent", err.revision_id, err.file_id)
    elif isinstance(err, errors.UnstackableRepositoryFormat):
        return (
            b"UnstackableRepositoryFormat",
            str(err.format).encode("utf-8"),
            err.url.encode("utf-8"),
        )
    elif isinstance(err, _mod_branch.UnstackableBranchFormat):
        return (
            b"UnstackableBranchFormat",
            str(err.format).encode("utf-8"),
            err.url.encode("utf-8"),
        )
    elif isinstance(err, errors.NotStacked):
        return (b"NotStacked",)
    elif isinstance(err, errors.BzrCheckError):
        return (b"BzrCheckError", err.msg.encode("utf-8"))
    elif isinstance(err, UnicodeError):
        # If it is a DecodeError, than most likely we are starting
        # with a plain string
        str_or_unicode = err.object
        if isinstance(str_or_unicode, str):
            # XXX: UTF-8 might have \x01 (our protocol v1 and v2 seperator
            # byte) in it, so this encoding could cause broken responses.
            # Newer clients use protocol v3, so will be fine.
            val = "u:" + str_or_unicode.encode("utf-8")
        else:
            val = "s:" + str_or_unicode.encode("base64")
        # This handles UnicodeEncodeError or UnicodeDecodeError
        return (
            err.__class__.__name__,
            err.encoding,
            val,
            str(err.start),
            str(err.end),
            err.reason,
        )
    elif isinstance(err, errors.TransportNotPossible):
        if err.msg == "readonly transport":
            return (b"ReadOnlyError",)
    elif isinstance(err, errors.ReadError):
        # cannot read the file
        return (b"ReadError", err.path)
    elif isinstance(err, errors.PermissionDenied):
        return (
            b"PermissionDenied",
            err.path.encode("utf-8"),
            err.extra.encode("utf-8"),
        )
    elif isinstance(err, errors.TokenMismatch):
        return (b"TokenMismatch", err.given_token, err.lock_token)
    elif isinstance(err, errors.LockContention):
        return (b"LockContention",)
    elif isinstance(err, GhostRevisionsHaveNoRevno):
        return (b"GhostRevisionsHaveNoRevno", err.revision_id, err.ghost_revision_id)
    elif isinstance(err, urlutils.InvalidURL):
        return (b"InvalidURL", err.path.encode("utf-8"), err.extra.encode("utf-8"))
    elif isinstance(err, MemoryError):
        # GZ 2011-02-24: Copy breezy.trace -Dmem_dump functionality here?
        return (b"MemoryError",)
    elif isinstance(err, errors.AlreadyControlDirError):
        return (b"AlreadyControlDir", err.path)
    # Unserialisable error.  Log it, and return a generic error
    trace.log_exception_quietly()
    return (
        b"error",
        trace._qualified_exception_name(err.__class__, True).encode("utf-8"),
        str(err).encode("utf-8"),
    )


class HelloRequest(SmartServerRequest):
    """Answer a version request with the highest protocol version this server
    supports.
    """

    def do(self):
        """Respond to a hello request with the protocol version.

        Returns:
            SuccessfulSmartServerResponse: Response containing 'ok' and
                                          the protocol version '2'.
        """
        return SuccessfulSmartServerResponse((b"ok", b"2"))


class GetBundleRequest(SmartServerRequest):
    """Get a bundle of from the null revision to the specified revision."""

    def do(self, path, revision_id):
        """Generate a bundle from the null revision to the specified revision.

        This method creates a bundle containing all the changes needed to
        recreate the repository state up to the specified revision.

        Args:
            path: The path to the repository.
            revision_id: The target revision ID for the bundle.

        Returns:
            SuccessfulSmartServerResponse: Response containing the bundle data.
        """
        import tempfile

        from breezy.bzr import bzrdir
        from breezy.bzr.bundle import serializer

        # open transport relative to our base
        t = self.transport_from_client_path(path)
        control, extra_path = bzrdir.BzrDir.open_containing_from_transport(t)
        repo = control.open_repository()
        tmpf = tempfile.TemporaryFile()
        base_revision = revision.NULL_REVISION
        serializer.write_bundle(repo, revision_id, base_revision, tmpf)
        tmpf.seek(0)
        return SuccessfulSmartServerResponse((), tmpf.read())


class SmartServerIsReadonly(SmartServerRequest):
    """Request handler to check if the transport is read-only.

    This handler checks whether the backing transport is read-only
    and returns 'yes' or 'no' accordingly.
    """

    # XXX: this request method belongs somewhere else.

    def do(self):
        """Check if the backing transport is read-only.

        Returns:
            SuccessfulSmartServerResponse: Response containing either
                                          b'yes' or b'no'.
        """
        answer = b"yes" if self._backing_transport.is_readonly() else b"no"
        return SuccessfulSmartServerResponse((answer,))


# In the 'info' attribute, we store whether this request is 'safe' to retry if
# we get a disconnect while reading the response. It can have the values:
#   read    This is purely a read request, so retrying it is perfectly ok.
#   idem    An idempotent write request. Something like 'put' where if you put
#           the same bytes twice you end up with the same final bytes.
#   semi    This is a request that isn't strictly idempotent, but doesn't
#           result in corruption if it is retried. This is for things like
#           'lock' and 'unlock'. If you call lock, it updates the disk
#           structure. If you fail to read the response, you won't be able to
#           use the lock, because you don't have the lock token. Calling lock
#           again will fail, because the lock is already taken. However, we
#           can't tell if the server received our request or not. If it didn't,
#           then retrying the request is fine, as it will actually do what we
#           want. If it did, we will interrupt the current operation, but we
#           are no worse off than interrupting the current operation because of
#           a ConnectionReset.
#   semivfs Similar to semi, but specific to a Virtual FileSystem request.
#   stream  This is a request that takes a stream that cannot be restarted if
#           consumed. This request is 'safe' in that if we determine the
#           connection is closed before we consume the stream, we can try
#           again.
#   mutate  State is updated in a way that replaying that request results in a
#           different state. For example 'append' writes more bytes to a given
#           file. If append succeeds, it moves the file pointer.
request_handlers = registry.Registry[bytes, SmartServerRequest, str]()
request_handlers.register_lazy(
    b"append", "breezy.bzr.smart.vfs", "AppendRequest", info="mutate"
)
request_handlers.register_lazy(
    b"Branch.break_lock",
    "breezy.bzr.smart.branch",
    "SmartServerBranchBreakLock",
    info="idem",
)
request_handlers.register_lazy(
    b"Branch.get_config_file",
    "breezy.bzr.smart.branch",
    "SmartServerBranchGetConfigFile",
    info="read",
)
request_handlers.register_lazy(
    b"Branch.get_parent",
    "breezy.bzr.smart.branch",
    "SmartServerBranchGetParent",
    info="read",
)
request_handlers.register_lazy(
    b"Branch.put_config_file",
    "breezy.bzr.smart.branch",
    "SmartServerBranchPutConfigFile",
    info="idem",
)
request_handlers.register_lazy(
    b"Branch.get_tags_bytes",
    "breezy.bzr.smart.branch",
    "SmartServerBranchGetTagsBytes",
    info="read",
)
request_handlers.register_lazy(
    b"Branch.set_tags_bytes",
    "breezy.bzr.smart.branch",
    "SmartServerBranchSetTagsBytes",
    info="idem",
)
request_handlers.register_lazy(
    b"Branch.heads_to_fetch",
    "breezy.bzr.smart.branch",
    "SmartServerBranchHeadsToFetch",
    info="read",
)
request_handlers.register_lazy(
    b"Branch.get_stacked_on_url",
    "breezy.bzr.smart.branch",
    "SmartServerBranchRequestGetStackedOnURL",
    info="read",
)
request_handlers.register_lazy(
    b"Branch.get_physical_lock_status",
    "breezy.bzr.smart.branch",
    "SmartServerBranchRequestGetPhysicalLockStatus",
    info="read",
)
request_handlers.register_lazy(
    b"Branch.last_revision_info",
    "breezy.bzr.smart.branch",
    "SmartServerBranchRequestLastRevisionInfo",
    info="read",
)
request_handlers.register_lazy(
    b"Branch.lock_write",
    "breezy.bzr.smart.branch",
    "SmartServerBranchRequestLockWrite",
    info="semi",
)
request_handlers.register_lazy(
    b"Branch.revision_history",
    "breezy.bzr.smart.branch",
    "SmartServerRequestRevisionHistory",
    info="read",
)
request_handlers.register_lazy(
    b"Branch.set_config_option",
    "breezy.bzr.smart.branch",
    "SmartServerBranchRequestSetConfigOption",
    info="idem",
)
request_handlers.register_lazy(
    b"Branch.set_config_option_dict",
    "breezy.bzr.smart.branch",
    "SmartServerBranchRequestSetConfigOptionDict",
    info="idem",
)
request_handlers.register_lazy(
    b"Branch.set_last_revision",
    "breezy.bzr.smart.branch",
    "SmartServerBranchRequestSetLastRevision",
    info="idem",
)
request_handlers.register_lazy(
    b"Branch.set_last_revision_info",
    "breezy.bzr.smart.branch",
    "SmartServerBranchRequestSetLastRevisionInfo",
    info="idem",
)
request_handlers.register_lazy(
    b"Branch.set_last_revision_ex",
    "breezy.bzr.smart.branch",
    "SmartServerBranchRequestSetLastRevisionEx",
    info="idem",
)
request_handlers.register_lazy(
    b"Branch.set_parent_location",
    "breezy.bzr.smart.branch",
    "SmartServerBranchRequestSetParentLocation",
    info="idem",
)
request_handlers.register_lazy(
    b"Branch.unlock",
    "breezy.bzr.smart.branch",
    "SmartServerBranchRequestUnlock",
    info="semi",
)
request_handlers.register_lazy(
    b"Branch.revision_id_to_revno",
    "breezy.bzr.smart.branch",
    "SmartServerBranchRequestRevisionIdToRevno",
    info="read",
)
request_handlers.register_lazy(
    b"Branch.get_all_reference_info",
    "breezy.bzr.smart.branch",
    "SmartServerBranchRequestGetAllReferenceInfo",
    info="read",
)
request_handlers.register_lazy(
    b"BzrDir.checkout_metadir",
    "breezy.bzr.smart.bzrdir",
    "SmartServerBzrDirRequestCheckoutMetaDir",
    info="read",
)
request_handlers.register_lazy(
    b"BzrDir.cloning_metadir",
    "breezy.bzr.smart.bzrdir",
    "SmartServerBzrDirRequestCloningMetaDir",
    info="read",
)
request_handlers.register_lazy(
    b"BzrDir.create_branch",
    "breezy.bzr.smart.bzrdir",
    "SmartServerRequestCreateBranch",
    info="semi",
)
request_handlers.register_lazy(
    b"BzrDir.create_repository",
    "breezy.bzr.smart.bzrdir",
    "SmartServerRequestCreateRepository",
    info="semi",
)
request_handlers.register_lazy(
    b"BzrDir.find_repository",
    "breezy.bzr.smart.bzrdir",
    "SmartServerRequestFindRepositoryV1",
    info="read",
)
request_handlers.register_lazy(
    b"BzrDir.find_repositoryV2",
    "breezy.bzr.smart.bzrdir",
    "SmartServerRequestFindRepositoryV2",
    info="read",
)
request_handlers.register_lazy(
    b"BzrDir.find_repositoryV3",
    "breezy.bzr.smart.bzrdir",
    "SmartServerRequestFindRepositoryV3",
    info="read",
)
request_handlers.register_lazy(
    b"BzrDir.get_branches",
    "breezy.bzr.smart.bzrdir",
    "SmartServerBzrDirRequestGetBranches",
    info="read",
)
request_handlers.register_lazy(
    b"BzrDir.get_config_file",
    "breezy.bzr.smart.bzrdir",
    "SmartServerBzrDirRequestConfigFile",
    info="read",
)
request_handlers.register_lazy(
    b"BzrDir.destroy_branch",
    "breezy.bzr.smart.bzrdir",
    "SmartServerBzrDirRequestDestroyBranch",
    info="semi",
)
request_handlers.register_lazy(
    b"BzrDir.destroy_repository",
    "breezy.bzr.smart.bzrdir",
    "SmartServerBzrDirRequestDestroyRepository",
    info="semi",
)
request_handlers.register_lazy(
    b"BzrDir.has_workingtree",
    "breezy.bzr.smart.bzrdir",
    "SmartServerBzrDirRequestHasWorkingTree",
    info="read",
)
request_handlers.register_lazy(
    b"BzrDirFormat.initialize",
    "breezy.bzr.smart.bzrdir",
    "SmartServerRequestInitializeBzrDir",
    info="semi",
)
request_handlers.register_lazy(
    b"BzrDirFormat.initialize_ex_1.16",
    "breezy.bzr.smart.bzrdir",
    "SmartServerRequestBzrDirInitializeEx",
    info="semi",
)
request_handlers.register_lazy(
    b"BzrDir.open",
    "breezy.bzr.smart.bzrdir",
    "SmartServerRequestOpenBzrDir",
    info="read",
)
request_handlers.register_lazy(
    b"BzrDir.open_2.1",
    "breezy.bzr.smart.bzrdir",
    "SmartServerRequestOpenBzrDir_2_1",
    info="read",
)
request_handlers.register_lazy(
    b"BzrDir.open_branch",
    "breezy.bzr.smart.bzrdir",
    "SmartServerRequestOpenBranch",
    info="read",
)
request_handlers.register_lazy(
    b"BzrDir.open_branchV2",
    "breezy.bzr.smart.bzrdir",
    "SmartServerRequestOpenBranchV2",
    info="read",
)
request_handlers.register_lazy(
    b"BzrDir.open_branchV3",
    "breezy.bzr.smart.bzrdir",
    "SmartServerRequestOpenBranchV3",
    info="read",
)
request_handlers.register_lazy(
    b"delete", "breezy.bzr.smart.vfs", "DeleteRequest", info="semivfs"
)
request_handlers.register_lazy(
    b"get", "breezy.bzr.smart.vfs", "GetRequest", info="read"
)
request_handlers.register_lazy(
    b"get_bundle", "breezy.bzr.smart.request", "GetBundleRequest", info="read"
)
request_handlers.register_lazy(
    b"has", "breezy.bzr.smart.vfs", "HasRequest", info="read"
)
request_handlers.register_lazy(
    b"hello", "breezy.bzr.smart.request", "HelloRequest", info="read"
)
request_handlers.register_lazy(
    b"iter_files_recursive",
    "breezy.bzr.smart.vfs",
    "IterFilesRecursiveRequest",
    info="read",
)
request_handlers.register_lazy(
    b"list_dir", "breezy.bzr.smart.vfs", "ListDirRequest", info="read"
)
request_handlers.register_lazy(
    b"mkdir", "breezy.bzr.smart.vfs", "MkdirRequest", info="semivfs"
)
request_handlers.register_lazy(
    b"move", "breezy.bzr.smart.vfs", "MoveRequest", info="semivfs"
)
request_handlers.register_lazy(
    b"put", "breezy.bzr.smart.vfs", "PutRequest", info="idem"
)
request_handlers.register_lazy(
    b"put_non_atomic", "breezy.bzr.smart.vfs", "PutNonAtomicRequest", info="idem"
)
request_handlers.register_lazy(
    b"readv", "breezy.bzr.smart.vfs", "ReadvRequest", info="read"
)
request_handlers.register_lazy(
    b"rename", "breezy.bzr.smart.vfs", "RenameRequest", info="semivfs"
)
request_handlers.register_lazy(
    b"Repository.add_signature_text",
    "breezy.bzr.smart.repository",
    "SmartServerRepositoryAddSignatureText",
    info="idem",
)
request_handlers.register_lazy(
    b"Repository.annotate_file_revision",
    "breezy.bzr.smart.repository",
    "SmartServerRepositoryAnnotateFileRevision",
    info="read",
)
request_handlers.register_lazy(
    b"Repository.all_revision_ids",
    "breezy.bzr.smart.repository",
    "SmartServerRepositoryAllRevisionIds",
    info="read",
)
request_handlers.register_lazy(
    b"PackRepository.autopack",
    "breezy.bzr.smart.packrepository",
    "SmartServerPackRepositoryAutopack",
    info="idem",
)
request_handlers.register_lazy(
    b"Repository.break_lock",
    "breezy.bzr.smart.repository",
    "SmartServerRepositoryBreakLock",
    info="idem",
)
request_handlers.register_lazy(
    b"Repository.gather_stats",
    "breezy.bzr.smart.repository",
    "SmartServerRepositoryGatherStats",
    info="read",
)
request_handlers.register_lazy(
    b"Repository.get_parent_map",
    "breezy.bzr.smart.repository",
    "SmartServerRepositoryGetParentMap",
    info="read",
)
request_handlers.register_lazy(
    b"Repository.get_revision_graph",
    "breezy.bzr.smart.repository",
    "SmartServerRepositoryGetRevisionGraph",
    info="read",
)
request_handlers.register_lazy(
    b"Repository.get_revision_signature_text",
    "breezy.bzr.smart.repository",
    "SmartServerRepositoryGetRevisionSignatureText",
    info="read",
)
request_handlers.register_lazy(
    b"Repository.has_revision",
    "breezy.bzr.smart.repository",
    "SmartServerRequestHasRevision",
    info="read",
)
request_handlers.register_lazy(
    b"Repository.has_signature_for_revision_id",
    "breezy.bzr.smart.repository",
    "SmartServerRequestHasSignatureForRevisionId",
    info="read",
)
request_handlers.register_lazy(
    b"Repository.insert_stream",
    "breezy.bzr.smart.repository",
    "SmartServerRepositoryInsertStream",
    info="stream",
)
request_handlers.register_lazy(
    b"Repository.insert_stream_1.19",
    "breezy.bzr.smart.repository",
    "SmartServerRepositoryInsertStream_1_19",
    info="stream",
)
request_handlers.register_lazy(
    b"Repository.insert_stream_locked",
    "breezy.bzr.smart.repository",
    "SmartServerRepositoryInsertStreamLocked",
    info="stream",
)
request_handlers.register_lazy(
    b"Repository.is_shared",
    "breezy.bzr.smart.repository",
    "SmartServerRepositoryIsShared",
    info="read",
)
request_handlers.register_lazy(
    b"Repository.iter_files_bytes",
    "breezy.bzr.smart.repository",
    "SmartServerRepositoryIterFilesBytes",
    info="read",
)
request_handlers.register_lazy(
    b"Repository.lock_write",
    "breezy.bzr.smart.repository",
    "SmartServerRepositoryLockWrite",
    info="semi",
)
request_handlers.register_lazy(
    b"Repository.make_working_trees",
    "breezy.bzr.smart.repository",
    "SmartServerRepositoryMakeWorkingTrees",
    info="read",
)
request_handlers.register_lazy(
    b"Repository.set_make_working_trees",
    "breezy.bzr.smart.repository",
    "SmartServerRepositorySetMakeWorkingTrees",
    info="idem",
)
request_handlers.register_lazy(
    b"Repository.unlock",
    "breezy.bzr.smart.repository",
    "SmartServerRepositoryUnlock",
    info="semi",
)
request_handlers.register_lazy(
    b"Repository.get_physical_lock_status",
    "breezy.bzr.smart.repository",
    "SmartServerRepositoryGetPhysicalLockStatus",
    info="read",
)
request_handlers.register_lazy(
    b"Repository.get_rev_id_for_revno",
    "breezy.bzr.smart.repository",
    "SmartServerRepositoryGetRevIdForRevno",
    info="read",
)
request_handlers.register_lazy(
    b"Repository.get_stream",
    "breezy.bzr.smart.repository",
    "SmartServerRepositoryGetStream",
    info="read",
)
request_handlers.register_lazy(
    b"Repository.get_stream_1.19",
    "breezy.bzr.smart.repository",
    "SmartServerRepositoryGetStream_1_19",
    info="read",
)
request_handlers.register_lazy(
    b"Repository.get_stream_for_missing_keys",
    "breezy.bzr.smart.repository",
    "SmartServerRepositoryGetStreamForMissingKeys",
    info="read",
)
request_handlers.register_lazy(
    b"Repository.iter_revisions",
    "breezy.bzr.smart.repository",
    "SmartServerRepositoryIterRevisions",
    info="read",
)
request_handlers.register_lazy(
    b"Repository.pack",
    "breezy.bzr.smart.repository",
    "SmartServerRepositoryPack",
    info="idem",
)
request_handlers.register_lazy(
    b"Repository.start_write_group",
    "breezy.bzr.smart.repository",
    "SmartServerRepositoryStartWriteGroup",
    info="semi",
)
request_handlers.register_lazy(
    b"Repository.commit_write_group",
    "breezy.bzr.smart.repository",
    "SmartServerRepositoryCommitWriteGroup",
    info="semi",
)
request_handlers.register_lazy(
    b"Repository.abort_write_group",
    "breezy.bzr.smart.repository",
    "SmartServerRepositoryAbortWriteGroup",
    info="semi",
)
request_handlers.register_lazy(
    b"Repository.check_write_group",
    "breezy.bzr.smart.repository",
    "SmartServerRepositoryCheckWriteGroup",
    info="read",
)
request_handlers.register_lazy(
    b"Repository.reconcile",
    "breezy.bzr.smart.repository",
    "SmartServerRepositoryReconcile",
    info="idem",
)
request_handlers.register_lazy(
    b"Repository.revision_archive",
    "breezy.bzr.smart.repository",
    "SmartServerRepositoryRevisionArchive",
    info="read",
)
request_handlers.register_lazy(
    b"Repository.tarball",
    "breezy.bzr.smart.repository",
    "SmartServerRepositoryTarball",
    info="read",
)
request_handlers.register_lazy(
    b"VersionedFileRepository.get_serializer_format",
    "breezy.bzr.smart.repository",
    "SmartServerRepositoryGetSerializerFormat",
    info="read",
)
request_handlers.register_lazy(
    b"VersionedFileRepository.get_inventories",
    "breezy.bzr.smart.repository",
    "SmartServerRepositoryGetInventories",
    info="read",
)
request_handlers.register_lazy(
    b"rmdir", "breezy.bzr.smart.vfs", "RmdirRequest", info="semivfs"
)
request_handlers.register_lazy(
    b"stat", "breezy.bzr.smart.vfs", "StatRequest", info="read"
)
request_handlers.register_lazy(
    b"Transport.is_readonly",
    "breezy.bzr.smart.request",
    "SmartServerIsReadonly",
    info="read",
)
