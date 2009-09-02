# Copyright (C) 2006, 2007 Canonical Ltd
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


import tempfile
import threading

from bzrlib import (
    bzrdir,
    errors,
    registry,
    revision,
    trace,
    urlutils,
    )
from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
from bzrlib.bundle import serializer
""")


jail_info = threading.local()
jail_info.transports = None


def _install_hook():
    bzrdir.BzrDir.hooks.install_named_hook(
        'pre_open', _pre_open_hook, 'checking server jail')


def _pre_open_hook(transport):
    allowed_transports = getattr(jail_info, 'transports', None)
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


class SmartServerRequest(object):
    """Base class for request handlers.

    To define a new request, subclass this class and override the `do` method
    (and if appropriate, `do_body` as well).  Request implementors should take
    care to call `translate_client_path` and `transport_from_client_path` as
    appropriate when dealing with paths received from the client.
    """
    # XXX: rename this class to BaseSmartServerRequestHandler ?  A request
    # *handler* is a different concept to the request.

    def __init__(self, backing_transport, root_client_path='/'):
        """Constructor.

        :param backing_transport: the base transport to be used when performing
            this request.
        :param root_client_path: the client path that maps to the root of
            backing_transport.  This is used to interpret relpaths received
            from the client.  Clients will not be able to refer to paths above
            this root.  If root_client_path is None, then no translation will
            be performed on client paths.  Default is '/'.
        """
        self._backing_transport = backing_transport
        if root_client_path is not None:
            if not root_client_path.startswith('/'):
                root_client_path = '/' + root_client_path
            if not root_client_path.endswith('/'):
                root_client_path += '/'
        self._root_client_path = root_client_path
        self._body_chunks = []

    def _check_enabled(self):
        """Raises DisabledMethod if this method is disabled."""
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

        :param *args: the arguments of the request.
        """
        self._check_enabled()
        return self.do(*args)

    def do_body(self, body_bytes):
        """Called if the client sends a body with the request.

        The do() method is still called, and must have returned None.

        Must return a SmartServerResponse.
        """
        if body_bytes != '':
            raise errors.SmartProtocolError('Request does not expect a body')

    def do_chunk(self, chunk_bytes):
        """Called with each body chunk if the request has a streamed body.

        The do() method is still called, and must have returned None.
        """
        self._body_chunks.append(chunk_bytes)

    def do_end(self):
        """Called when the end of the request has been received."""
        body_bytes = ''.join(self._body_chunks)
        self._body_chunks = None
        return self.do_body(body_bytes)

    def setup_jail(self):
        jail_info.transports = [self._backing_transport]

    def teardown_jail(self):
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
        if self._root_client_path is None:
            # no translation necessary!
            return client_path
        if not client_path.startswith('/'):
            client_path = '/' + client_path
        if client_path + '/' == self._root_client_path:
            return '.'
        if client_path.startswith(self._root_client_path):
            path = client_path[len(self._root_client_path):]
            relpath = urlutils.joinpath('/', path)
            if not relpath.startswith('/'):
                raise ValueError(relpath)
            return '.' + relpath
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


class SmartServerResponse(object):
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
            raise errors.BzrError(
                "'body' and 'body_stream' are mutually exclusive.")
        self.body = body
        self.body_stream = body_stream

    def __eq__(self, other):
        if other is None:
            return False
        return (other.args == self.args and
                other.body == self.body and
                other.body_stream is self.body_stream)

    def __repr__(self):
        return "<%s args=%r body=%r>" % (self.__class__.__name__,
            self.args, self.body)


class FailedSmartServerResponse(SmartServerResponse):
    """A SmartServerResponse for a request which failed."""

    def is_successful(self):
        """FailedSmartServerResponse are not successful."""
        return False


class SuccessfulSmartServerResponse(SmartServerResponse):
    """A SmartServerResponse for a successfully completed request."""

    def is_successful(self):
        """SuccessfulSmartServerResponse are successful."""
        return True


class SmartServerRequestHandler(object):
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

    def __init__(self, backing_transport, commands, root_client_path):
        """Constructor.

        :param backing_transport: a Transport to handle requests for.
        :param commands: a registry mapping command names to SmartServerRequest
            subclasses. e.g. bzrlib.transport.smart.vfs.vfs_commands.
        """
        self._backing_transport = backing_transport
        self._root_client_path = root_client_path
        self._commands = commands
        self.response = None
        self.finished_reading = False
        self._command = None

    def accept_body(self, bytes):
        """Accept body data."""
        if self._command is None:
            # no active command object, so ignore the event.
            return
        self._run_handler_code(self._command.do_chunk, (bytes,), {})

    def end_of_body(self):
        """No more body data will be received."""
        self._run_handler_code(self._command.do_end, (), {})
        # cannot read after this.
        self.finished_reading = True

    def dispatch_command(self, cmd, args):
        """Deprecated compatibility method.""" # XXX XXX
        try:
            command = self._commands.get(cmd)
        except LookupError:
            raise errors.UnknownSmartMethod(cmd)
        self._command = command(self._backing_transport, self._root_client_path)
        self._run_handler_code(self._command.execute, args, {})

    def _run_handler_code(self, callable, args, kwargs):
        """Run some handler specific code 'callable'.

        If a result is returned, it is considered to be the commands response,
        and finished_reading is set true, and its assigned to self.response.

        Any exceptions caught are translated and a response object created
        from them.
        """
        result = self._call_converting_errors(callable, args, kwargs)

        if result is not None:
            self.response = result
            self.finished_reading = True

    def _call_converting_errors(self, callable, args, kwargs):
        """Call callable converting errors to Response objects."""
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
        except Exception, err:
            err_struct = _translate_error(err)
            return FailedSmartServerResponse(err_struct)

    def headers_received(self, headers):
        # Just a no-op at the moment.
        pass

    def args_received(self, args):
        cmd = args[0]
        args = args[1:]
        try:
            command = self._commands.get(cmd)
        except LookupError:
            raise errors.UnknownSmartMethod(cmd)
        self._command = command(self._backing_transport)
        self._run_handler_code(self._command.execute, args, {})

    def end_received(self):
        if self._command is None:
            # no active command object, so ignore the event.
            return
        self._run_handler_code(self._command.do_end, (), {})

    def post_body_error_received(self, error_args):
        # Just a no-op at the moment.
        pass


def _translate_error(err):
    if isinstance(err, errors.NoSuchFile):
        return ('NoSuchFile', err.path)
    elif isinstance(err, errors.FileExists):
        return ('FileExists', err.path)
    elif isinstance(err, errors.DirectoryNotEmpty):
        return ('DirectoryNotEmpty', err.path)
    elif isinstance(err, errors.IncompatibleRepositories):
        return ('IncompatibleRepositories', str(err.source), str(err.target),
            str(err.details))
    elif isinstance(err, errors.ShortReadvError):
        return ('ShortReadvError', err.path, str(err.offset), str(err.length),
                str(err.actual))
    elif isinstance(err, errors.UnstackableRepositoryFormat):
        return (('UnstackableRepositoryFormat', str(err.format), err.url))
    elif isinstance(err, errors.UnstackableBranchFormat):
        return ('UnstackableBranchFormat', str(err.format), err.url)
    elif isinstance(err, errors.NotStacked):
        return ('NotStacked',)
    elif isinstance(err, UnicodeError):
        # If it is a DecodeError, than most likely we are starting
        # with a plain string
        str_or_unicode = err.object
        if isinstance(str_or_unicode, unicode):
            # XXX: UTF-8 might have \x01 (our protocol v1 and v2 seperator
            # byte) in it, so this encoding could cause broken responses.
            # Newer clients use protocol v3, so will be fine.
            val = 'u:' + str_or_unicode.encode('utf-8')
        else:
            val = 's:' + str_or_unicode.encode('base64')
        # This handles UnicodeEncodeError or UnicodeDecodeError
        return (err.__class__.__name__, err.encoding, val, str(err.start),
                str(err.end), err.reason)
    elif isinstance(err, errors.TransportNotPossible):
        if err.msg == "readonly transport":
            return ('ReadOnlyError', )
    elif isinstance(err, errors.ReadError):
        # cannot read the file
        return ('ReadError', err.path)
    elif isinstance(err, errors.PermissionDenied):
        return ('PermissionDenied', err.path, err.extra)
    elif isinstance(err, errors.TokenMismatch):
        return ('TokenMismatch', err.given_token, err.lock_token)
    elif isinstance(err, errors.LockContention):
        return ('LockContention',)
    # Unserialisable error.  Log it, and return a generic error
    trace.log_exception_quietly()
    return ('error', str(err))


class HelloRequest(SmartServerRequest):
    """Answer a version request with the highest protocol version this server
    supports.
    """

    def do(self):
        return SuccessfulSmartServerResponse(('ok', '2'))


class GetBundleRequest(SmartServerRequest):
    """Get a bundle of from the null revision to the specified revision."""

    def do(self, path, revision_id):
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
    # XXX: this request method belongs somewhere else.

    def do(self):
        if self._backing_transport.is_readonly():
            answer = 'yes'
        else:
            answer = 'no'
        return SuccessfulSmartServerResponse((answer,))


request_handlers = registry.Registry()
request_handlers.register_lazy(
    'append', 'bzrlib.smart.vfs', 'AppendRequest')
request_handlers.register_lazy(
    'Branch.get_config_file', 'bzrlib.smart.branch',
    'SmartServerBranchGetConfigFile')
request_handlers.register_lazy(
    'Branch.get_parent', 'bzrlib.smart.branch', 'SmartServerBranchGetParent')
request_handlers.register_lazy(
    'Branch.get_tags_bytes', 'bzrlib.smart.branch',
    'SmartServerBranchGetTagsBytes')
request_handlers.register_lazy(
    'Branch.set_tags_bytes', 'bzrlib.smart.branch',
    'SmartServerBranchSetTagsBytes')
request_handlers.register_lazy(
    'Branch.get_stacked_on_url', 'bzrlib.smart.branch', 'SmartServerBranchRequestGetStackedOnURL')
request_handlers.register_lazy(
    'Branch.last_revision_info', 'bzrlib.smart.branch', 'SmartServerBranchRequestLastRevisionInfo')
request_handlers.register_lazy(
    'Branch.lock_write', 'bzrlib.smart.branch', 'SmartServerBranchRequestLockWrite')
request_handlers.register_lazy( 'Branch.revision_history',
    'bzrlib.smart.branch', 'SmartServerRequestRevisionHistory')
request_handlers.register_lazy( 'Branch.set_config_option',
    'bzrlib.smart.branch', 'SmartServerBranchRequestSetConfigOption')
request_handlers.register_lazy( 'Branch.set_last_revision',
    'bzrlib.smart.branch', 'SmartServerBranchRequestSetLastRevision')
request_handlers.register_lazy(
    'Branch.set_last_revision_info', 'bzrlib.smart.branch',
    'SmartServerBranchRequestSetLastRevisionInfo')
request_handlers.register_lazy(
    'Branch.set_last_revision_ex', 'bzrlib.smart.branch',
    'SmartServerBranchRequestSetLastRevisionEx')
request_handlers.register_lazy(
    'Branch.set_parent_location', 'bzrlib.smart.branch',
    'SmartServerBranchRequestSetParentLocation')
request_handlers.register_lazy(
    'Branch.unlock', 'bzrlib.smart.branch', 'SmartServerBranchRequestUnlock')
request_handlers.register_lazy(
    'BzrDir.cloning_metadir', 'bzrlib.smart.bzrdir',
    'SmartServerBzrDirRequestCloningMetaDir')
request_handlers.register_lazy(
    'BzrDir.create_branch', 'bzrlib.smart.bzrdir',
    'SmartServerRequestCreateBranch')
request_handlers.register_lazy(
    'BzrDir.create_repository', 'bzrlib.smart.bzrdir',
    'SmartServerRequestCreateRepository')
request_handlers.register_lazy(
    'BzrDir.find_repository', 'bzrlib.smart.bzrdir',
    'SmartServerRequestFindRepositoryV1')
request_handlers.register_lazy(
    'BzrDir.find_repositoryV2', 'bzrlib.smart.bzrdir',
    'SmartServerRequestFindRepositoryV2')
request_handlers.register_lazy(
    'BzrDir.find_repositoryV3', 'bzrlib.smart.bzrdir',
    'SmartServerRequestFindRepositoryV3')
request_handlers.register_lazy(
    'BzrDir.get_config_file', 'bzrlib.smart.bzrdir',
    'SmartServerBzrDirRequestConfigFile')
request_handlers.register_lazy(
    'BzrDirFormat.initialize', 'bzrlib.smart.bzrdir',
    'SmartServerRequestInitializeBzrDir')
request_handlers.register_lazy(
    'BzrDirFormat.initialize_ex_1.16', 'bzrlib.smart.bzrdir',
    'SmartServerRequestBzrDirInitializeEx')
request_handlers.register_lazy(
    'BzrDir.open', 'bzrlib.smart.bzrdir', 'SmartServerRequestOpenBzrDir')
request_handlers.register_lazy(
    'BzrDir.open_branch', 'bzrlib.smart.bzrdir',
    'SmartServerRequestOpenBranch')
request_handlers.register_lazy(
    'BzrDir.open_branchV2', 'bzrlib.smart.bzrdir',
    'SmartServerRequestOpenBranchV2')
request_handlers.register_lazy(
    'delete', 'bzrlib.smart.vfs', 'DeleteRequest')
request_handlers.register_lazy(
    'get', 'bzrlib.smart.vfs', 'GetRequest')
request_handlers.register_lazy(
    'get_bundle', 'bzrlib.smart.request', 'GetBundleRequest')
request_handlers.register_lazy(
    'has', 'bzrlib.smart.vfs', 'HasRequest')
request_handlers.register_lazy(
    'hello', 'bzrlib.smart.request', 'HelloRequest')
request_handlers.register_lazy(
    'iter_files_recursive', 'bzrlib.smart.vfs', 'IterFilesRecursiveRequest')
request_handlers.register_lazy(
    'list_dir', 'bzrlib.smart.vfs', 'ListDirRequest')
request_handlers.register_lazy(
    'mkdir', 'bzrlib.smart.vfs', 'MkdirRequest')
request_handlers.register_lazy(
    'move', 'bzrlib.smart.vfs', 'MoveRequest')
request_handlers.register_lazy(
    'put', 'bzrlib.smart.vfs', 'PutRequest')
request_handlers.register_lazy(
    'put_non_atomic', 'bzrlib.smart.vfs', 'PutNonAtomicRequest')
request_handlers.register_lazy(
    'readv', 'bzrlib.smart.vfs', 'ReadvRequest')
request_handlers.register_lazy(
    'rename', 'bzrlib.smart.vfs', 'RenameRequest')
request_handlers.register_lazy(
    'PackRepository.autopack', 'bzrlib.smart.packrepository',
    'SmartServerPackRepositoryAutopack')
request_handlers.register_lazy('Repository.gather_stats',
                               'bzrlib.smart.repository',
                               'SmartServerRepositoryGatherStats')
request_handlers.register_lazy('Repository.get_parent_map',
                               'bzrlib.smart.repository',
                               'SmartServerRepositoryGetParentMap')
request_handlers.register_lazy(
    'Repository.get_revision_graph', 'bzrlib.smart.repository', 'SmartServerRepositoryGetRevisionGraph')
request_handlers.register_lazy(
    'Repository.has_revision', 'bzrlib.smart.repository', 'SmartServerRequestHasRevision')
request_handlers.register_lazy(
    'Repository.insert_stream', 'bzrlib.smart.repository', 'SmartServerRepositoryInsertStream')
request_handlers.register_lazy(
    'Repository.insert_stream_1.19', 'bzrlib.smart.repository', 'SmartServerRepositoryInsertStream_1_19')
request_handlers.register_lazy(
    'Repository.insert_stream_locked', 'bzrlib.smart.repository', 'SmartServerRepositoryInsertStreamLocked')
request_handlers.register_lazy(
    'Repository.is_shared', 'bzrlib.smart.repository', 'SmartServerRepositoryIsShared')
request_handlers.register_lazy(
    'Repository.lock_write', 'bzrlib.smart.repository', 'SmartServerRepositoryLockWrite')
request_handlers.register_lazy(
    'Repository.set_make_working_trees', 'bzrlib.smart.repository',
    'SmartServerRepositorySetMakeWorkingTrees')
request_handlers.register_lazy(
    'Repository.unlock', 'bzrlib.smart.repository', 'SmartServerRepositoryUnlock')
request_handlers.register_lazy(
    'Repository.get_rev_id_for_revno', 'bzrlib.smart.repository',
    'SmartServerRepositoryGetRevIdForRevno')
request_handlers.register_lazy(
    'Repository.get_stream', 'bzrlib.smart.repository',
    'SmartServerRepositoryGetStream')
request_handlers.register_lazy(
    'Repository.get_stream_1.19', 'bzrlib.smart.repository',
    'SmartServerRepositoryGetStream_1_19')
request_handlers.register_lazy(
    'Repository.tarball', 'bzrlib.smart.repository',
    'SmartServerRepositoryTarball')
request_handlers.register_lazy(
    'rmdir', 'bzrlib.smart.vfs', 'RmdirRequest')
request_handlers.register_lazy(
    'stat', 'bzrlib.smart.vfs', 'StatRequest')
request_handlers.register_lazy(
    'Transport.is_readonly', 'bzrlib.smart.request', 'SmartServerIsReadonly')
