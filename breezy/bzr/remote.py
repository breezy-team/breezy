"""Remote bzr operations using the smart protocol.

This module provides classes for working with remote bzr repositories,
branches, and control directories over the smart protocol.
"""

# Copyright (C) 2006-2012 Canonical Ltd
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

import bz2
import contextlib
import os
import re
import zlib
from typing import Callable, Optional

import fastbencode as bencode

from .. import (
    branch,
    controldir,
    debug,
    errors,
    gpg,
    graph,
    lock,
    lockdir,
    osutils,
    registry,
    ui,
    urlutils,
)
from .. import bzr as _mod_bzr
from .. import config as _mod_config
from .. import repository as _mod_repository
from .. import revision as _mod_revision
from .. import transport as _mod_transport
from ..branch import BranchWriteLockResult
from ..decorators import only_raises
from ..errors import NoSuchRevision, SmartProtocolError
from ..i18n import gettext
from ..repository import RepositoryWriteLockResult, _LazyListJoin
from ..revision import NULL_REVISION, RevisionID
from ..trace import log_exception_quietly, mutter, note, warning
from . import branch as bzrbranch
from . import bzrdir as _mod_bzrdir
from . import inventory_delta, vf_repository, vf_search
from . import testament as _mod_testament
from .branch import BranchReferenceFormat
from .inventory import Inventory
from .inventory_delta import InventoryDelta
from .inventorytree import InventoryRevisionTree
from .lockable_files import LockableFiles
from .serializer import revision_format_registry
from .smart import client, vfs
from .smart import repository as smart_repo
from .smart.client import _SmartClient

_DEFAULT_SEARCH_DEPTH = 100


class UnknownErrorFromSmartServer(errors.BzrError):
    """An ErrorFromSmartServer could not be translated into a typical breezy
    error.

    This is distinct from ErrorFromSmartServer so that it is possible to
    distinguish between the following two cases:

     - ErrorFromSmartServer was uncaught.  This is logic error in the client
       and so should provoke a traceback to the user.
     - ErrorFromSmartServer was caught but its error_tuple could not be
       translated.  This is probably because the server sent us garbage, and
       should not provoke a traceback.
    """

    _fmt = "Server sent an unexpected error: %(error_tuple)r"

    internal_error = False

    def __init__(self, error_from_smart_server):
        """Constructor.

        :param error_from_smart_server: An ErrorFromSmartServer instance.
        """
        self.error_from_smart_server = error_from_smart_server
        self.error_tuple = error_from_smart_server.error_tuple


class _RpcHelper:
    """Mixin class that helps with issuing RPCs."""

    def _call(self, method, *args, **err_context):
        """Make a remote procedure call to the smart server.

        Args:
            method: The name of the method to call on the smart server.
            *args: Arguments to pass to the remote method.
            **err_context: Additional context for error translation.

        Returns:
            The result of the remote procedure call.

        Raises:
            Various errors as translated from ErrorFromSmartServer.
        """
        try:
            return self._client.call(method, *args)
        except errors.ErrorFromSmartServer as err:
            self._translate_error(err, **err_context)

    def _call_expecting_body(self, method, *args, **err_context):
        """Make a remote procedure call expecting a response body.

        Args:
            method: The name of the method to call on the smart server.
            *args: Arguments to pass to the remote method.
            **err_context: Additional context for error translation.

        Returns:
            Tuple of (response_args, response_body) from the remote call.

        Raises:
            Various errors as translated from ErrorFromSmartServer.
        """
        try:
            return self._client.call_expecting_body(method, *args)
        except errors.ErrorFromSmartServer as err:
            self._translate_error(err, **err_context)

    def _call_with_body_bytes(self, method, args, body_bytes, **err_context):
        """Make a remote procedure call with a request body.

        Args:
            method: The name of the method to call on the smart server.
            args: Arguments to pass to the remote method.
            body_bytes: The body data to send with the request.
            **err_context: Additional context for error translation.

        Returns:
            The result of the remote procedure call.

        Raises:
            Various errors as translated from ErrorFromSmartServer.
        """
        try:
            return self._client.call_with_body_bytes(method, args, body_bytes)
        except errors.ErrorFromSmartServer as err:
            self._translate_error(err, **err_context)

    def _call_with_body_bytes_expecting_body(
        self, method, args, body_bytes, **err_context
    ):
        """Make a remote procedure call with request body, expecting response body.

        Args:
            method: The name of the method to call on the smart server.
            args: Arguments to pass to the remote method.
            body_bytes: The body data to send with the request.
            **err_context: Additional context for error translation.

        Returns:
            Tuple of (response_args, response_body) from the remote call.

        Raises:
            Various errors as translated from ErrorFromSmartServer.
        """
        try:
            return self._client.call_with_body_bytes_expecting_body(
                method, args, body_bytes
            )
        except errors.ErrorFromSmartServer as err:
            self._translate_error(err, **err_context)


def response_tuple_to_repo_format(response):
    """Convert a response tuple describing a repository format to a format."""
    format = RemoteRepositoryFormat()
    format._rich_root_data = response[0] == b"yes"
    format._supports_tree_reference = response[1] == b"yes"
    format._supports_external_lookups = response[2] == b"yes"
    format._network_name = response[3]
    return format


# Note that RemoteBzrDirProber lives in breezy.bzrdir so breezy.bzr.remote
# does not have to be imported unless a remote format is involved.


class RemoteBzrDirFormat(_mod_bzrdir.BzrDirMetaFormat1):
    """Format representing bzrdirs accessed via a smart server."""

    supports_workingtrees = False

    colocated_branches = False

    def __init__(self):
        """Initialize a RemoteBzrDirFormat instance.

        Creates a new remote bzrdir format that can be used to access
        bzr directories over a smart server connection.
        """
        _mod_bzrdir.BzrDirMetaFormat1.__init__(self)
        # XXX: It's a bit ugly that the network name is here, because we'd
        # like to believe that format objects are stateless or at least
        # immutable,  However, we do at least avoid mutating the name after
        # it's returned.  See <https://bugs.launchpad.net/bzr/+bug/504102>
        self._network_name = None

    def __repr__(self):
        """Return a string representation of this format.

        Returns:
            A string showing the class name and network name.
        """
        return f"{self.__class__.__name__}(_network_name={self._network_name!r})"

    def get_format_description(self):
        """Get a human-readable description of this format.

        Returns:
            A string describing the format, prefixed with 'Remote: ' if
            a network name is available, otherwise 'bzr remote bzrdir'.
        """
        if self._network_name:
            try:
                real_format = controldir.network_format_registry.get(self._network_name)
            except KeyError:
                pass
            else:
                return "Remote: " + real_format.get_format_description()
        return "bzr remote bzrdir"

    def get_format_string(self):
        """Get the format string for this format.

        Raises:
            NotImplementedError: Remote formats don't have format strings.
        """
        raise NotImplementedError(self.get_format_string)

    def network_name(self):
        """Get the network name for this format.

        Returns:
            The network name string if set.

        Raises:
            AssertionError: If no network name has been set.
        """
        if self._network_name:
            return self._network_name
        else:
            raise AssertionError("No network name set.")

    def initialize_on_transport(self, transport):
        """Initialize a new bzrdir on the given transport.

        Args:
            transport: The transport to initialize the bzrdir on.

        Returns:
            A RemoteBzrDir instance representing the newly initialized directory.

        Raises:
            SmartProtocolError: If the server returns an unexpected response.
        """
        try:
            # hand off the request to the smart server
            client_medium = transport.get_smart_medium()
        except errors.NoSmartMedium:
            # TODO: lookup the local format from a server hint.
            local_dir_format = _mod_bzrdir.BzrDirMetaFormat1()
            return local_dir_format.initialize_on_transport(transport)
        client = _SmartClient(client_medium)
        path = client.remote_path_from_transport(transport)
        try:
            response = client.call(b"BzrDirFormat.initialize", path)
        except errors.ErrorFromSmartServer as err:
            _translate_error(err, path=path)
        if response[0] != b"ok":
            raise errors.SmartProtocolError(f"unexpected response code {response}")
        format = RemoteBzrDirFormat()
        self._supply_sub_formats_to(format)
        return RemoteBzrDir(transport, format)

    def parse_NoneTrueFalse(self, arg):
        """Parse a bytes argument into None, True, or False.

        Args:
            arg: Bytes object that should be empty, b'True', or b'False'.

        Returns:
            None if arg is empty/falsy, True if arg is b'True',
            False if arg is b'False'.

        Raises:
            AssertionError: If arg is not a recognized value.
        """
        if not arg:
            return None
        if arg == b"False":
            return False
        if arg == b"True":
            return True
        raise AssertionError(f"invalid arg {arg!r}")

    def _serialize_NoneTrueFalse(self, arg):
        """Serialize None, True, or False into bytes format.

        Args:
            arg: None, True, or False value to serialize.

        Returns:
            b'False' if arg is False, b'True' if arg is truthy,
            empty bytes if arg is None.
        """
        if arg is False:
            return b"False"
        if arg:
            return b"True"
        return b""

    def _serialize_NoneString(self, arg):
        """Serialize a None or string value into bytes format.

        Args:
            arg: None or bytes/string value to serialize.

        Returns:
            The original arg if truthy, otherwise empty bytes.
        """
        return arg or b""

    def initialize_on_transport_ex(
        self,
        transport,
        use_existing_dir=False,
        create_prefix=False,
        force_new_repo=False,
        stacked_on=None,
        stack_on_pwd=None,
        repo_format_name=None,
        make_working_trees=None,
        shared_repo=False,
    ):
        """Initialize a bzrdir with advanced options.

        Args:
            transport: The transport to initialize on.
            use_existing_dir: If True, use an existing directory.
            create_prefix: If True, create parent directories as needed.
            force_new_repo: If True, force creation of a new repository.
            stacked_on: URL to stack the new branch on.
            stack_on_pwd: Path to stack on relative to pwd.
            repo_format_name: Name of repository format to use.
            make_working_trees: Whether repository should make working trees.
            shared_repo: If True, create a shared repository.

        Returns:
            Tuple of (repository, bzrdir, require_stacking, repository_policy).
        """
        try:
            # hand off the request to the smart server
            client_medium = transport.get_smart_medium()
        except errors.NoSmartMedium:
            do_vfs = True
        else:
            # Decline to open it if the server doesn't support our required
            # version (3) so that the VFS-based transport will do it.
            if client_medium.should_probe():
                try:
                    server_version = client_medium.protocol_version()
                    do_vfs = server_version != "2"
                except errors.SmartProtocolError:
                    # Apparently there's no usable smart server there, even though
                    # the medium supports the smart protocol.
                    do_vfs = True
            else:
                do_vfs = False
        if not do_vfs:
            client = _SmartClient(client_medium)
            path = client.remote_path_from_transport(transport)
            if client_medium._is_remote_before((1, 16)):
                do_vfs = True
        if do_vfs:
            # TODO: lookup the local format from a server hint.
            local_dir_format = _mod_bzrdir.BzrDirMetaFormat1()
            self._supply_sub_formats_to(local_dir_format)
            return local_dir_format.initialize_on_transport_ex(
                transport,
                use_existing_dir=use_existing_dir,
                create_prefix=create_prefix,
                force_new_repo=force_new_repo,
                stacked_on=stacked_on,
                stack_on_pwd=stack_on_pwd,
                repo_format_name=repo_format_name,
                make_working_trees=make_working_trees,
                shared_repo=shared_repo,
                vfs_only=True,
            )
        return self._initialize_on_transport_ex_rpc(
            client,
            path,
            transport,
            use_existing_dir,
            create_prefix,
            force_new_repo,
            stacked_on,
            stack_on_pwd,
            repo_format_name,
            make_working_trees,
            shared_repo,
        )

    def _initialize_on_transport_ex_rpc(
        self,
        client,
        path,
        transport,
        use_existing_dir,
        create_prefix,
        force_new_repo,
        stacked_on,
        stack_on_pwd,
        repo_format_name,
        make_working_trees,
        shared_repo,
    ):
        """Make the RPC call to initialize a bzrdir with extended options.

        Args:
            client: The smart client to use for the RPC call.
            path: Path on the server to initialize.
            transport: The transport being used.
            use_existing_dir: Whether to use an existing directory.
            create_prefix: Whether to create parent directories.
            force_new_repo: Whether to force creation of a new repository.
            stacked_on: URL to stack on.
            stack_on_pwd: Path to stack on relative to pwd.
            repo_format_name: Repository format name to use.
            make_working_trees: Whether repository should make working trees.
            shared_repo: Whether to create a shared repository.

        Returns:
            Tuple of (repository, bzrdir, require_stacking, repository_policy).
        """
        args = []
        args.append(self._serialize_NoneTrueFalse(use_existing_dir))
        args.append(self._serialize_NoneTrueFalse(create_prefix))
        args.append(self._serialize_NoneTrueFalse(force_new_repo))
        args.append(self._serialize_NoneString(stacked_on))
        # stack_on_pwd is often/usually our transport
        if stack_on_pwd:
            try:
                stack_on_pwd = transport.relpath(stack_on_pwd).encode("utf-8")
                if not stack_on_pwd:
                    stack_on_pwd = b"."
            except errors.PathNotChild:
                pass
        args.append(self._serialize_NoneString(stack_on_pwd))
        args.append(self._serialize_NoneString(repo_format_name))
        args.append(self._serialize_NoneTrueFalse(make_working_trees))
        args.append(self._serialize_NoneTrueFalse(shared_repo))
        request_network_name = (
            self._network_name
            or _mod_bzrdir.BzrDirFormat.get_default_format().network_name()
        )
        try:
            response = client.call(
                b"BzrDirFormat.initialize_ex_1.16", request_network_name, path, *args
            )
        except errors.UnknownSmartMethod:
            client._medium._remember_remote_is_before((1, 16))
            local_dir_format = _mod_bzrdir.BzrDirMetaFormat1()
            self._supply_sub_formats_to(local_dir_format)
            return local_dir_format.initialize_on_transport_ex(
                transport,
                use_existing_dir=use_existing_dir,
                create_prefix=create_prefix,
                force_new_repo=force_new_repo,
                stacked_on=stacked_on,
                stack_on_pwd=stack_on_pwd,
                repo_format_name=repo_format_name,
                make_working_trees=make_working_trees,
                shared_repo=shared_repo,
                vfs_only=True,
            )
        except errors.ErrorFromSmartServer as err:
            _translate_error(err, path=path.decode("utf-8"))
        repo_path = response[0]
        bzrdir_name = response[6]
        require_stacking = response[7]
        require_stacking = self.parse_NoneTrueFalse(require_stacking)
        format = RemoteBzrDirFormat()
        format._network_name = bzrdir_name
        self._supply_sub_formats_to(format)
        bzrdir = RemoteBzrDir(transport, format, _client=client)
        if repo_path:
            repo_format = response_tuple_to_repo_format(response[1:])
            if repo_path == b".":
                repo_path = b""
            repo_path = repo_path.decode("utf-8")
            if repo_path:
                repo_bzrdir_format = RemoteBzrDirFormat()
                repo_bzrdir_format._network_name = response[5]
                repo_bzr = RemoteBzrDir(transport.clone(repo_path), repo_bzrdir_format)
            else:
                repo_bzr = bzrdir
            final_stack = response[8] or None
            if final_stack:
                final_stack = final_stack.decode("utf-8")
            final_stack_pwd = response[9] or None
            if final_stack_pwd:
                final_stack_pwd = urlutils.join(
                    transport.base, final_stack_pwd.decode("utf-8")
                )
            remote_repo = RemoteRepository(repo_bzr, repo_format)
            if len(response) > 10:
                # Updated server verb that locks remotely.
                repo_lock_token = response[10] or None
                remote_repo.lock_write(repo_lock_token, _skip_rpc=True)
                if repo_lock_token:
                    remote_repo.dont_leave_lock_in_place()
            else:
                remote_repo.lock_write()
            policy = _mod_bzrdir.UseExistingRepository(
                remote_repo, final_stack, final_stack_pwd, require_stacking
            )
            policy.acquire_repository()
        else:
            remote_repo = None
            policy = None
        bzrdir._format.set_branch_format(self.get_branch_format())
        if require_stacking:
            # The repo has already been created, but we need to make sure that
            # we'll make a stackable branch.
            bzrdir._format.require_stacking(_skip_repo=True)
        return remote_repo, bzrdir, require_stacking, policy

    def _open(self, transport):
        """Open a bzrdir on the given transport.

        Args:
            transport: The transport to open the bzrdir on.

        Returns:
            A RemoteBzrDir instance.
        """
        return RemoteBzrDir(transport, self)

    def __eq__(self, other):
        """Check if this format is equal to another format.

        Args:
            other: Another format object to compare with.

        Returns:
            True if the formats are equivalent, False otherwise.
        """
        if not isinstance(other, RemoteBzrDirFormat):
            return False
        return self.get_format_description() == other.get_format_description()

    def __return_repository_format(self):
        """Return the repository format for this bzrdir format.

        Always returns a RemoteRepositoryFormat object, but if a specific
        bzr repository format has been requested, configures the
        RemoteRepositoryFormat to use that for initialization.

        Returns:
            A RemoteRepositoryFormat instance.
        """
        # Always return a RemoteRepositoryFormat object, but if a specific bzr
        # repository format has been asked for, tell the RemoteRepositoryFormat
        # that it should use that for init() etc.
        result = RemoteRepositoryFormat()
        custom_format = getattr(self, "_repository_format", None)
        if custom_format:
            if isinstance(custom_format, RemoteRepositoryFormat):
                return custom_format
            else:
                # We will use the custom format to create repositories over the
                # wire; expose its details like rich_root_data for code to
                # query
                result._custom_format = custom_format
        return result

    def get_branch_format(self):
        """Get the branch format for this bzrdir format.

        Returns:
            A RemoteBranchFormat instance, wrapping the underlying format
            if necessary.
        """
        result = _mod_bzrdir.BzrDirMetaFormat1.get_branch_format(self)
        if not isinstance(result, RemoteBranchFormat):
            new_result = RemoteBranchFormat()
            new_result._custom_format = result
            # cache the result
            self.set_branch_format(new_result)
            result = new_result
        return result

    repository_format = property(
        __return_repository_format, _mod_bzrdir.BzrDirMetaFormat1._set_repository_format
    )  # .im_func)


class RemoteControlStore(_mod_config.IniFileStore):
    """Control store which attempts to use HPSS calls to retrieve control store.

    Note that this is specific to bzr-based formats.
    """

    def __init__(self, bzrdir):
        """Initialize a RemoteControlStore.

        Args:
            bzrdir: The bzrdir this store is associated with.
        """
        super().__init__()
        self.controldir = bzrdir
        self._real_store = None

    def lock_write(self, token=None):
        """Lock the store for writing.

        Args:
            token: Optional lock token for resuming an existing lock.

        Returns:
            A lock token that can be used to resume the lock later.
        """
        self._ensure_real()
        return self._real_store.lock_write(token)

    def unlock(self):
        """Unlock the store.

        Returns:
            The result of unlocking the underlying store.
        """
        self._ensure_real()
        return self._real_store.unlock()

    def save(self):
        """Save the configuration store.

        Ensures the store is locked during the save operation.
        """
        with self.lock_write():
            # We need to be able to override the undecorated implementation
            self.save_without_locking()

    def save_without_locking(self):
        """Save the configuration store without acquiring a lock.

        Should only be called when the store is already locked.
        """
        super().save()

    def _ensure_real(self):
        """Ensure that the real (local) control store is available.

        This method makes sure that the control directory has been realized
        as a local object and creates the real control store if it doesn't
        already exist.
        """
        self.controldir._ensure_real()
        if self._real_store is None:
            self._real_store = _mod_config.ControlStore(self.controldir)

    def external_url(self):
        """Get the external URL for this configuration store.

        Returns:
            The URL where the control.conf file can be accessed.
        """
        return urlutils.join(self.branch.user_url, "control.conf")

    def _load_content(self):
        """Load the configuration content from the remote server.

        This method attempts to load configuration content using the smart
        server protocol. If the smart server doesn't support the required
        method, it falls back to using the local VFS-based store.

        Returns:
            The raw bytes of the configuration content.

        Raises:
            UnexpectedSmartServerResponse: If the server returns an unexpected response.
        """
        path = self.controldir._path_for_remote_call(self.controldir._client)
        try:
            response, handler = self.controldir._call_expecting_body(
                b"BzrDir.get_config_file", path
            )
        except errors.UnknownSmartMethod:
            self._ensure_real()
            return self._real_store._load_content()
        if len(response) and response[0] != b"ok":
            raise errors.UnexpectedSmartServerResponse(response)
        return handler.read_body_bytes()

    def _save_content(self, content):
        """Save configuration content to the remote server.

        Currently this method falls back to using the local VFS-based store
        because the smart server protocol doesn't support writing to control
        directories yet.

        Args:
            content: The raw bytes of configuration content to save.

        Returns:
            The result of saving the content via the real store.

        Note:
            This is a known limitation - ideally this should use an HPSS call
            but it's not currently possible to write lock control directories.
        """
        # FIXME JRV 2011-11-22: Ideally this should use a
        # HPSS call too, but at the moment it is not possible
        # to write lock control directories.
        self._ensure_real()
        return self._real_store._save_content(content)


class RemoteBzrDir(_mod_bzrdir.BzrDir, _RpcHelper):
    """Control directory on a remote server, accessed via bzr:// or similar."""

    @property
    def user_transport(self):
        """Get the user transport for this bzrdir.

        Returns:
            The root transport.
        """
        return self.root_transport

    @property
    def control_transport(self):
        """Get the control transport for this bzrdir.

        Returns:
            The control transport.
        """
        return self.transport

    def __init__(self, transport, format, _client=None, _force_probe=False):
        """Construct a RemoteBzrDir.

        :param _client: Private parameter for testing. Disables probing and the
            use of a real bzrdir.
        """
        _mod_bzrdir.BzrDir.__init__(self, transport, format)
        # this object holds a delegated bzrdir that uses file-level operations
        # to talk to the other side
        self._real_bzrdir = None
        self._has_working_tree = None
        # 1-shot cache for the call pattern 'create_branch; open_branch' - see
        # create_branch for details.
        self._next_open_branch_result = None

        if _client is None:
            medium = transport.get_smart_medium()
            self._client = client._SmartClient(medium)
        else:
            self._client = _client
            if not _force_probe:
                return

        self._probe_bzrdir()

    def __repr__(self):
        """Return a string representation of this RemoteBzrDir.

        Returns:
            A string showing the class name and client.
        """
        return f"{self.__class__.__name__}({self._client!r})"

    def _probe_bzrdir(self):
        """Probe the remote bzrdir to determine its capabilities.

        Uses the appropriate RPC method based on the server's capabilities.
        """
        medium = self._client._medium
        path = self._path_for_remote_call(self._client)
        if medium._is_remote_before((2, 1)):
            self._rpc_open(path)
            return
        try:
            self._rpc_open_2_1(path)
            return
        except errors.UnknownSmartMethod:
            medium._remember_remote_is_before((2, 1))
            self._rpc_open(path)

    def _rpc_open_2_1(self, path):
        """Open a bzrdir using the BzrDir.open_2.1 RPC method.

        Args:
            path: Path to the bzrdir on the remote server.

        Raises:
            NotBranchError: If the path is not a branch.
            UnexpectedSmartServerResponse: If the server response is malformed.
        """
        response = self._call(b"BzrDir.open_2.1", path)
        if response == (b"no",):
            raise errors.NotBranchError(path=self.root_transport.base)
        elif response[0] == b"yes":
            if response[1] == b"yes":
                self._has_working_tree = True
            elif response[1] == b"no":
                self._has_working_tree = False
            else:
                raise errors.UnexpectedSmartServerResponse(response)
        else:
            raise errors.UnexpectedSmartServerResponse(response)

    def _rpc_open(self, path):
        """Open a bzrdir using the legacy BzrDir.open RPC method.

        Args:
            path: Path to the bzrdir on the remote server.

        Raises:
            NotBranchError: If the path is not a branch.
            UnexpectedSmartServerResponse: If the server response is malformed.
        """
        response = self._call(b"BzrDir.open", path)
        if response not in [(b"yes",), (b"no",)]:
            raise errors.UnexpectedSmartServerResponse(response)
        if response == (b"no",):
            raise errors.NotBranchError(path=self.root_transport.base)

    def _ensure_real(self):
        """Ensure that there is a _real_bzrdir set.

        Used before calls to self._real_bzrdir.
        """
        if not self._real_bzrdir:
            if debug.debug_flag_enabled("hpssvfs"):
                import traceback

                warning(
                    "VFS BzrDir access triggered\n%s", "".join(traceback.format_stack())
                )
            self._real_bzrdir = _mod_bzrdir.BzrDir.open_from_transport(
                self.root_transport, probers=[_mod_bzr.BzrProber]
            )
            self._format._network_name = self._real_bzrdir._format.network_name()

    def _translate_error(self, err, **context):
        """Translate an ErrorFromSmartServer into a more specific error.

        Args:
            err: The ErrorFromSmartServer to translate.
            **context: Additional context for error translation.
        """
        _translate_error(err, bzrdir=self, **context)

    def break_lock(self):
        """Break any existing locks on this bzrdir.

        Clears the branch cache to prevent aliasing problems.
        """
        # Prevent aliasing problems in the next_open_branch_result cache.
        # See create_branch for rationale.
        self._next_open_branch_result = None
        return _mod_bzrdir.BzrDir.break_lock(self)

    def _vfs_checkout_metadir(self):
        """Get checkout metadir using VFS fallback.

        This method is used when the remote server doesn't support the
        smart protocol for retrieving checkout metadir information.

        Returns:
            The checkout metadir format from the real bzrdir.
        """
        self._ensure_real()
        return self._real_bzrdir.checkout_metadir()

    def checkout_metadir(self):
        """Retrieve the controldir format to use for checkouts of this one."""
        medium = self._client._medium
        if medium._is_remote_before((2, 5)):
            return self._vfs_checkout_metadir()
        path = self._path_for_remote_call(self._client)
        try:
            response = self._client.call(b"BzrDir.checkout_metadir", path)
        except errors.UnknownSmartMethod:
            medium._remember_remote_is_before((2, 5))
            return self._vfs_checkout_metadir()
        if len(response) != 3:
            raise errors.UnexpectedSmartServerResponse(response)
        control_name, repo_name, branch_name = response
        try:
            format = controldir.network_format_registry.get(control_name)
        except KeyError as e:
            raise errors.UnknownFormatError(kind="control", format=control_name) from e
        if repo_name:
            try:
                repo_format = _mod_repository.network_format_registry.get(repo_name)
            except KeyError as e:
                raise errors.UnknownFormatError(
                    kind="repository", format=repo_name
                ) from e
            format.repository_format = repo_format
        if branch_name:
            try:
                format.set_branch_format(
                    branch.network_format_registry.get(branch_name)
                )
            except KeyError as e:
                raise errors.UnknownFormatError(
                    kind="branch", format=branch_name
                ) from e
        return format

    def _vfs_cloning_metadir(self, require_stacking=False):
        """Get cloning metadir using VFS fallback.

        Args:
            require_stacking: Whether the cloned directory must support stacking.

        Returns:
            The cloning metadir format from the real bzrdir.
        """
        self._ensure_real()
        return self._real_bzrdir.cloning_metadir(require_stacking=require_stacking)

    def cloning_metadir(self, require_stacking=False):
        """Get the controldir format for cloning this bzrdir.

        Args:
            require_stacking: Whether the cloned directory must support stacking.

        Returns:
            A controldir format suitable for cloning this directory.

        Raises:
            UnexpectedSmartServerResponse: If the server response is malformed.
        """
        medium = self._client._medium
        if medium._is_remote_before((1, 13)):
            return self._vfs_cloning_metadir(require_stacking=require_stacking)
        verb = b"BzrDir.cloning_metadir"
        stacking = b"True" if require_stacking else b"False"
        path = self._path_for_remote_call(self._client)
        try:
            response = self._call(verb, path, stacking)
        except errors.UnknownSmartMethod:
            medium._remember_remote_is_before((1, 13))
            return self._vfs_cloning_metadir(require_stacking=require_stacking)
        except UnknownErrorFromSmartServer as err:
            if err.error_tuple != (b"BranchReference",):
                raise
            # We need to resolve the branch reference to determine the
            # cloning_metadir.  This causes unnecessary RPCs to open the
            # referenced branch (and bzrdir, etc) but only when the caller
            # didn't already resolve the branch reference.
            referenced_branch = self.open_branch()
            return referenced_branch.controldir.cloning_metadir()
        if len(response) != 3:
            raise errors.UnexpectedSmartServerResponse(response)
        control_name, repo_name, branch_info = response
        if len(branch_info) != 2:
            raise errors.UnexpectedSmartServerResponse(response)
        branch_ref, branch_name = branch_info
        try:
            format = controldir.network_format_registry.get(control_name)
        except KeyError as e:
            raise errors.UnknownFormatError(kind="control", format=control_name) from e

        if repo_name:
            try:
                format.repository_format = _mod_repository.network_format_registry.get(
                    repo_name
                )
            except KeyError as e:
                raise errors.UnknownFormatError(
                    kind="repository", format=repo_name
                ) from e
        if branch_ref == b"ref":
            # XXX: we need possible_transports here to avoid reopening the
            # connection to the referenced location
            ref_bzrdir = _mod_bzrdir.BzrDir.open(branch_name)
            branch_format = ref_bzrdir.cloning_metadir().get_branch_format()
            format.set_branch_format(branch_format)
        elif branch_ref == b"branch":
            if branch_name:
                try:
                    branch_format = branch.network_format_registry.get(branch_name)
                except KeyError as e:
                    raise errors.UnknownFormatError(
                        kind="branch", format=branch_name
                    ) from e
                format.set_branch_format(branch_format)
        else:
            raise errors.UnexpectedSmartServerResponse(response)
        return format

    def create_repository(self, shared=False):
        """Create a new repository in this bzrdir.

        Creates a new repository using the repository format associated
        with this bzrdir format. The repository can optionally be shared.

        Args:
            shared: If True, create a shared repository that can be used
                   by multiple branches. Defaults to False.

        Returns:
            A Repository object (either RemoteRepository or the result
            of opening the created repository).

        Note:
            Delegates to the format object to handle format-specific
            initialization details.
        """
        # as per meta1 formats - just delegate to the format object which may
        # be parameterised.
        result = self._format.repository_format.initialize(self, shared)
        if not isinstance(result, RemoteRepository):
            return self.open_repository()
        else:
            return result

    def destroy_repository(self):
        """See BzrDir.destroy_repository."""
        path = self._path_for_remote_call(self._client)
        try:
            response = self._call(b"BzrDir.destroy_repository", path)
        except errors.UnknownSmartMethod:
            self._ensure_real()
            self._real_bzrdir.destroy_repository()
            return
        if response[0] != b"ok":
            raise SmartProtocolError(f"unexpected response code {response}")

    def create_branch(self, name=None, repository=None, append_revisions_only=None):
        """Create a new branch in this bzrdir.

        Creates a new branch using the branch format associated with
        this bzrdir format. Optionally associates it with a specific
        repository.

        Args:
            name: Name of the branch to create. If None, uses the default
                 branch name. Non-empty names raise NoColocatedBranchSupport.
            repository: Optional repository to associate with the branch.
                       If None, the default repository will be used.
            append_revisions_only: If True, the branch will only allow
                                  appending new revisions (no rebasing).

        Returns:
            A Branch object (either RemoteBranch or a wrapped branch).

        Raises:
            NoColocatedBranchSupport: If a non-empty branch name is provided.

        Note:
            The result is cached to optimize subsequent open_branch() calls.
        """
        if name is None:
            name = self._get_selected_branch()
        if name != "":
            raise controldir.NoColocatedBranchSupport(self)
        # as per meta1 formats - just delegate to the format object which may
        # be parameterised.
        real_branch = self._format.get_branch_format().initialize(
            self,
            name=name,
            repository=repository,
            append_revisions_only=append_revisions_only,
        )
        if not isinstance(real_branch, RemoteBranch):
            if not isinstance(repository, RemoteRepository):
                raise AssertionError(
                    f"need a RemoteRepository to use with RemoteBranch, got {repository!r}"
                )
            result = RemoteBranch(self, repository, real_branch, name=name)
        else:
            result = real_branch
        # BzrDir.clone_on_transport() uses the result of create_branch but does
        # not return it to its callers; we save approximately 8% of our round
        # trips by handing the branch we created back to the first caller to
        # open_branch rather than probing anew. Long term we need a API in
        # bzrdir that doesn't discard result objects (like result_branch).
        # RBC 20090225
        self._next_open_branch_result = result
        return result

    def destroy_branch(self, name=None):
        """See BzrDir.destroy_branch."""
        if name is None:
            name = self._get_selected_branch()
        if name != "":
            raise controldir.NoColocatedBranchSupport(self)
        path = self._path_for_remote_call(self._client)
        try:
            args = (name,) if name != "" else ()
            response = self._call(b"BzrDir.destroy_branch", path, *args)
        except errors.UnknownSmartMethod:
            self._ensure_real()
            self._real_bzrdir.destroy_branch(name=name)
            self._next_open_branch_result = None
            return
        self._next_open_branch_result = None
        if response[0] != b"ok":
            raise SmartProtocolError(f"unexpected response code {response}")

    def create_workingtree(
        self, revision_id=None, from_branch=None, accelerator_tree=None, hardlink=False
    ):
        """Create a working tree at this location.

        Args:
            revision_id: Revision to check out.
            from_branch: Branch to check out from.
            accelerator_tree: Tree to use for acceleration.
            hardlink: Use hardlinks when possible.

        Raises:
            NotLocalUrl: Remote locations cannot have working trees.
        """
        raise errors.NotLocalUrl(self.transport.base)

    def find_branch_format(self, name=None):
        """Find the branch 'format' for this bzrdir.

        This might be a synthetic object for e.g. RemoteBranch and SVN.
        """
        b = self.open_branch(name=name)
        return b._format

    def branch_names(self):
        """Get the names of all branches in this bzrdir.

        Retrieves a list of branch names present in this bzrdir.
        For most repository formats, this will just be the default
        branch, but some formats support multiple named branches.

        Returns:
            A list of branch names as strings.

        Raises:
            UnexpectedSmartServerResponse: If the server returns an unexpected response.

        Note:
            Falls back to VFS if the server doesn't support the smart method.
        """
        path = self._path_for_remote_call(self._client)
        try:
            response, handler = self._call_expecting_body(b"BzrDir.get_branches", path)
        except errors.UnknownSmartMethod:
            self._ensure_real()
            return self._real_bzrdir.branch_names()
        if response[0] != b"success":
            raise errors.UnexpectedSmartServerResponse(response)
        body = bencode.bdecode(handler.read_body_bytes())
        ret = []
        for name, _value in body.items():
            name = name.decode("utf-8")
            ret.append(name)
        return ret

    def get_branches(self, possible_transports=None, ignore_fallbacks=False):
        """Get all branches in this bzrdir as a dictionary.

        Retrieves all branches in this bzrdir, returning them as a
        dictionary mapping branch names to branch objects.

        Args:
            possible_transports: Optional list of transport objects that
                               can be used for efficiency.
            ignore_fallbacks: If True, don't open fallback repositories
                            for the branches.

        Returns:
            A dictionary mapping branch names (strings) to Branch objects.

        Raises:
            UnexpectedSmartServerResponse: If the server returns an unexpected response.

        Note:
            Falls back to VFS if the server doesn't support the smart method.
        """
        path = self._path_for_remote_call(self._client)
        try:
            response, handler = self._call_expecting_body(b"BzrDir.get_branches", path)
        except errors.UnknownSmartMethod:
            self._ensure_real()
            return self._real_bzrdir.get_branches()
        if response[0] != b"success":
            raise errors.UnexpectedSmartServerResponse(response)
        body = bencode.bdecode(handler.read_body_bytes())
        ret = {}
        for name, value in body.items():
            name = name.decode("utf-8")
            ret[name] = self._open_branch(
                name,
                value[0].decode("ascii"),
                value[1],
                possible_transports=possible_transports,
                ignore_fallbacks=ignore_fallbacks,
            )
        return ret

    def set_branch_reference(self, target_branch, name=None):
        """See BzrDir.set_branch_reference()."""
        if name is None:
            name = self._get_selected_branch()
        if name != "":
            raise controldir.NoColocatedBranchSupport(self)
        self._ensure_real()
        return self._real_bzrdir.set_branch_reference(target_branch, name=name)

    def get_branch_reference(self, name=None):
        """See BzrDir.get_branch_reference()."""
        if name is None:
            name = self._get_selected_branch()
        if name != "":
            raise controldir.NoColocatedBranchSupport(self)
        response = self._get_branch_reference()
        if response[0] == "ref":
            return response[1].decode("utf-8")
        else:
            return None

    def _get_branch_reference(self):
        """Get branch reference information.

        :return: Tuple with (kind, location_or_format)
            if kind == 'ref', then location_or_format contains a location
            otherwise, it contains a format name
        """
        path = self._path_for_remote_call(self._client)
        medium = self._client._medium
        candidate_calls = [
            (b"BzrDir.open_branchV3", (2, 1)),
            (b"BzrDir.open_branchV2", (1, 13)),
            (b"BzrDir.open_branch", None),
        ]
        for verb, required_version in candidate_calls:
            if required_version and medium._is_remote_before(required_version):
                continue
            try:
                response = self._call(verb, path)
            except errors.UnknownSmartMethod:
                if required_version is None:
                    raise
                medium._remember_remote_is_before(required_version)
            else:
                break
        if verb == b"BzrDir.open_branch":
            if response[0] != b"ok":
                raise errors.UnexpectedSmartServerResponse(response)
            if response[1] != b"":
                return ("ref", response[1])
            else:
                return ("branch", b"")
        if response[0] not in (b"ref", b"branch"):
            raise errors.UnexpectedSmartServerResponse(response)
        return (response[0].decode("ascii"), response[1])

    def _get_tree_branch(self, name=None):
        """See BzrDir._get_tree_branch()."""
        return None, self.open_branch(name=name)

    def _open_branch(
        self,
        name,
        kind,
        location_or_format,
        ignore_fallbacks=False,
        possible_transports=None,
    ):
        if kind == "ref":
            # a branch reference, use the existing BranchReference logic.
            format = BranchReferenceFormat()
            ref_loc = urlutils.join(self.user_url, location_or_format.decode("utf-8"))
            return format.open(
                self,
                name=name,
                _found=True,
                location=ref_loc,
                ignore_fallbacks=ignore_fallbacks,
                possible_transports=possible_transports,
            )
        branch_format_name = location_or_format
        if not branch_format_name:
            branch_format_name = None
        format = RemoteBranchFormat(network_name=branch_format_name)
        return RemoteBranch(
            self,
            self.find_repository(),
            format=format,
            setup_stacking=not ignore_fallbacks,
            name=name,
            possible_transports=possible_transports,
        )

    def open_branch(
        self,
        name=None,
        unsupported=False,
        ignore_fallbacks=False,
        possible_transports=None,
    ):
        """Open the branch at this location.

        Args:
            name: Name of colocated branch to open.
            unsupported: Allow opening unsupported branches.
            ignore_fallbacks: Ignore fallback repositories.
            possible_transports: Transports to reuse.

        Returns:
            RemoteBranch: The opened branch.

        Raises:
            NoColocatedBranchSupport: When requesting colocated branch.
            NotImplementedError: When unsupported flag is used.
        """
        if name is None:
            name = self._get_selected_branch()
        if name != "":
            raise controldir.NoColocatedBranchSupport(self)
        if unsupported:
            raise NotImplementedError("unsupported flag support not implemented yet.")
        if self._next_open_branch_result is not None:
            # See create_branch for details.
            result = self._next_open_branch_result
            self._next_open_branch_result = None
            return result
        response = self._get_branch_reference()
        return self._open_branch(
            name,
            response[0],
            response[1],
            possible_transports=possible_transports,
            ignore_fallbacks=ignore_fallbacks,
        )

    def _open_repo_v1(self, path):
        """Open repository using the legacy v1 find_repository method.

        This is a fallback method for older servers that don't support
        external references.

        Args:
            path: Path to the bzrdir on the remote server.

        Returns:
            Tuple of (response, repository) from the remote call.

        Raises:
            UnexpectedSmartServerResponse: If the server response is malformed.
        """
        verb = b"BzrDir.find_repository"
        response = self._call(verb, path)
        if response[0] != b"ok":
            raise errors.UnexpectedSmartServerResponse(response)
        # servers that only support the v1 method don't support external
        # references either.
        self._ensure_real()
        repo = self._real_bzrdir.open_repository()
        response = response + (b"no", repo._format.network_name())
        return response, repo

    def _open_repo_v2(self, path):
        """Open repository using the v2 find_repositoryV2 method.

        Args:
            path: Path to the bzrdir on the remote server.

        Returns:
            Tuple of (response, repository) from the remote call.

        Raises:
            UnexpectedSmartServerResponse: If the server response is malformed.
        """
        verb = b"BzrDir.find_repositoryV2"
        response = self._call(verb, path)
        if response[0] != b"ok":
            raise errors.UnexpectedSmartServerResponse(response)
        self._ensure_real()
        repo = self._real_bzrdir.open_repository()
        response = response + (repo._format.network_name(),)
        return response, repo

    def _open_repo_v3(self, path):
        """Open repository using the v3 find_repositoryV3 method.

        This is the most recent method that supports all repository features.

        Args:
            path: Path to the bzrdir on the remote server.

        Returns:
            Tuple of (response, None) from the remote call.

        Raises:
            UnknownSmartMethod: If the server doesn't support v3 method.
            UnexpectedSmartServerResponse: If the server response is malformed.
        """
        verb = b"BzrDir.find_repositoryV3"
        medium = self._client._medium
        if medium._is_remote_before((1, 13)):
            raise errors.UnknownSmartMethod(verb)
        try:
            response = self._call(verb, path)
        except errors.UnknownSmartMethod:
            medium._remember_remote_is_before((1, 13))
            raise
        if response[0] != b"ok":
            raise errors.UnexpectedSmartServerResponse(response)
        return response, None

    def open_repository(self):
        """Open the repository in this bzrdir.

        Tries different versions of the repository opening protocol
        until one succeeds.

        Returns:
            A RemoteRepository instance.

        Raises:
            NoRepositoryPresent: If no repository is present in this bzrdir.
            UnknownSmartMethod: If no supported repository method is available.
            SmartProtocolError: If the response format is incorrect.
        """
        path = self._path_for_remote_call(self._client)
        response = None
        for probe in [self._open_repo_v3, self._open_repo_v2, self._open_repo_v1]:
            try:
                response, real_repo = probe(path)
                break
            except errors.UnknownSmartMethod:
                pass
        if response is None:
            raise errors.UnknownSmartMethod(b"BzrDir.find_repository{3,2,}")
        if response[0] != b"ok":
            raise errors.UnexpectedSmartServerResponse(response)
        if len(response) != 6:
            raise SmartProtocolError(f"incorrect response length {response}")
        if response[1] == b"":
            # repo is at this dir.
            format = response_tuple_to_repo_format(response[2:])
            # Used to support creating a real format instance when needed.
            format._creating_bzrdir = self
            remote_repo = RemoteRepository(self, format)
            format._creating_repo = remote_repo
            if real_repo is not None:
                remote_repo._set_real_repository(real_repo)
            return remote_repo
        else:
            raise errors.NoRepositoryPresent(self)

    def has_workingtree(self):
        """Check if this bzrdir has a working tree.

        Returns:
            True if a working tree is present, False otherwise.

        Raises:
            SmartProtocolError: If the server response is unexpected.
        """
        if self._has_working_tree is None:
            path = self._path_for_remote_call(self._client)
            try:
                response = self._call(b"BzrDir.has_workingtree", path)
            except errors.UnknownSmartMethod:
                self._ensure_real()
                self._has_working_tree = self._real_bzrdir.has_workingtree()
            else:
                if response[0] not in (b"yes", b"no"):
                    raise SmartProtocolError(f"unexpected response code {response}")
                self._has_working_tree = response[0] == b"yes"
        return self._has_working_tree

    def open_workingtree(self, recommend_upgrade=True):
        """Open the working tree in this bzrdir.

        Args:
            recommend_upgrade: Whether to recommend upgrading (ignored).

        Raises:
            NotLocalUrl: If this bzrdir has a working tree (remote working trees not supported).
            NoWorkingTree: If this bzrdir doesn't have a working tree.
        """
        if self.has_workingtree():
            raise errors.NotLocalUrl(self.root_transport)
        else:
            raise errors.NoWorkingTree(self.root_transport.base)

    def _path_for_remote_call(self, client):
        """Return the path to be used for this bzrdir in a remote call."""
        remote_path = client.remote_path_from_transport(self.root_transport)
        remote_path = remote_path.decode("utf-8")
        base_url, segment_parameters = urlutils.split_segment_parameters_raw(
            remote_path
        )
        base_url = base_url.encode("utf-8")
        return base_url

    def get_branch_transport(self, branch_format, name=None):
        """Get the transport for accessing branch data.

        Args:
            branch_format: The branch format to get transport for.
            name: Optional name of the branch.

        Returns:
            A transport for accessing the branch data.
        """
        self._ensure_real()
        return self._real_bzrdir.get_branch_transport(branch_format, name=name)

    def get_repository_transport(self, repository_format):
        """Get the transport for accessing repository data.

        Args:
            repository_format: The repository format to get transport for.

        Returns:
            A transport for accessing the repository data.
        """
        self._ensure_real()
        return self._real_bzrdir.get_repository_transport(repository_format)

    def get_workingtree_transport(self, workingtree_format):
        """Get the transport for accessing working tree data.

        Args:
            workingtree_format: The working tree format to get transport for.

        Returns:
            A transport for accessing the working tree data.
        """
        self._ensure_real()
        return self._real_bzrdir.get_workingtree_transport(workingtree_format)

    def can_convert_format(self):
        """Upgrading of remote bzrdirs is not supported yet."""
        return False

    def needs_format_conversion(self, format):
        """Upgrading of remote bzrdirs is not supported yet."""
        return False

    def _get_config(self):
        """Get the configuration for this bzrdir.

        Returns:
            A RemoteBzrDirConfig instance.
        """
        return RemoteBzrDirConfig(self)

    def _get_config_store(self):
        """Get the configuration store for this bzrdir.

        Returns:
            A RemoteControlStore instance.
        """
        return RemoteControlStore(self)


class RemoteInventoryTree(InventoryRevisionTree):
    def __init__(self, repository, inv, revision_id):
        """Initialize a RemoteInventoryTree.

        Args:
            repository: The repository containing the tree data.
            inv: The inventory for this revision tree.
            revision_id: The revision ID this tree represents.
        """
        super().__init__(repository, inv, revision_id)

    def archive(
        self,
        format,
        name,
        root=None,
        subdir=None,
        force_mtime=None,
        recurse_nested=False,
    ):
        """Create an archive of this tree.

        Args:
            format: Archive format to create.
            name: Name/path of archive to create.
            root: Root directory in archive.
            subdir: Subdirectory to archive.
            force_mtime: Force modification time for entries.
            recurse_nested: Recurse into nested trees.
        """
        if recurse_nested:
            # For now, just fall back to non-HPSS mode if nested trees are involved.
            return super().archive(
                format,
                name,
                root,
                subdir,
                force_mtime=force_mtime,
                recurse_nested=recurse_nested,
            )
        ret = self._repository._revision_archive(
            self.get_revision_id(), format, name, root, subdir, force_mtime=force_mtime
        )
        if ret is None:
            return super().archive(
                format,
                name,
                root,
                subdir,
                force_mtime=force_mtime,
                recurse_nested=recurse_nested,
            )
        return ret

    def annotate_iter(self, path, default_revision=_mod_revision.CURRENT_REVISION):
        """Return an iterator of revision_id, line tuples.

        For working trees (and mutable trees in general), the special
        revision_id 'current:' will be used for lines that are new in this
        tree, e.g. uncommitted changes.
        :param default_revision: For lines that don't match a basis, mark them
            with this revision id. Not all implementations will make use of
            this value.
        """
        ret = self._repository._annotate_file_revision(
            self.get_revision_id(),
            path,
            file_id=None,
            default_revision=default_revision,
        )
        if ret is None:
            return super().annotate_iter(path, default_revision=default_revision)
        return ret


class RemoteRepositoryFormat(vf_repository.VersionedFileRepositoryFormat):
    """Format for repositories accessed over a _SmartClient.

    Instances of this repository are represented by RemoteRepository
    instances.

    The RemoteRepositoryFormat is parameterized during construction
    to reflect the capabilities of the real, remote format. Specifically
    the attributes rich_root_data and supports_tree_reference are set
    on a per instance basis, and are not set (and should not be) at
    the class level.

    :ivar _custom_format: If set, a specific concrete repository format that
        will be used when initializing a repository with this
        RemoteRepositoryFormat.
    :ivar _creating_repo: If set, the repository object that this
        RemoteRepositoryFormat was created for: it can be called into
        to obtain data like the network name.
    """

    _matchingcontroldir = RemoteBzrDirFormat()
    supports_full_versioned_files = True
    supports_leaving_lock = True
    supports_overriding_transport = False
    supports_ghosts = False

    def __init__(self):
        """Initialize a RemoteRepositoryFormat.

        Sets up the format with default values for various capability flags
        that will be determined by probing the remote repository.
        """
        _mod_repository.RepositoryFormat.__init__(self)
        self._custom_format = None
        self._network_name = None
        self._creating_bzrdir = None
        self._revision_graph_can_have_wrong_parents = None
        self._supports_chks = None
        self._supports_external_lookups = None
        self._supports_tree_reference = None
        self._supports_funky_characters = None
        self._supports_nesting_repositories = None
        self._rich_root_data = None

    def __repr__(self):
        """Return a string representation of this format.

        Returns:
            A string showing the class name and network name.
        """
        return f"{self.__class__.__name__}(_network_name={self._network_name!r})"

    @property
    def fast_deltas(self):
        """Whether this repository format supports fast deltas.

        Returns:
            True if fast deltas are supported.
        """
        self._ensure_real()
        return self._custom_format.fast_deltas

    @property
    def rich_root_data(self):
        """Whether this repository format supports rich root data.

        Returns:
            True if rich root data is supported.
        """
        if self._rich_root_data is None:
            self._ensure_real()
            self._rich_root_data = self._custom_format.rich_root_data
        return self._rich_root_data

    @property
    def supports_chks(self):
        """Whether this repository format supports CHK inventories.

        Returns:
            True if CHK inventories are supported.
        """
        if self._supports_chks is None:
            self._ensure_real()
            self._supports_chks = self._custom_format.supports_chks
        return self._supports_chks

    @property
    def supports_external_lookups(self):
        """Whether this repository format supports external lookups.

        Returns:
            True if external lookups are supported.
        """
        if self._supports_external_lookups is None:
            self._ensure_real()
            self._supports_external_lookups = (
                self._custom_format.supports_external_lookups
            )
        return self._supports_external_lookups

    @property
    def supports_funky_characters(self):
        """Whether this repository format supports funky characters in filenames.

        Returns:
            True if funky characters are supported.
        """
        if self._supports_funky_characters is None:
            self._ensure_real()
            self._supports_funky_characters = (
                self._custom_format.supports_funky_characters
            )
        return self._supports_funky_characters

    @property
    def supports_nesting_repositories(self):
        """Whether this repository format supports nested repositories.

        Returns:
            True if nested repositories are supported.
        """
        if self._supports_nesting_repositories is None:
            self._ensure_real()
            self._supports_nesting_repositories = (
                self._custom_format.supports_nesting_repositories
            )
        return self._supports_nesting_repositories

    @property
    def supports_tree_reference(self):
        """Whether this repository format supports tree references.

        Returns:
            True if tree references are supported.
        """
        if self._supports_tree_reference is None:
            self._ensure_real()
            self._supports_tree_reference = self._custom_format.supports_tree_reference
        return self._supports_tree_reference

    @property
    def revision_graph_can_have_wrong_parents(self):
        """Whether the revision graph might have wrong parents.

        This indicates if the repository format allows for revision graphs
        where the parent relationships might be incorrect or incomplete.

        Returns:
            True if the revision graph can have wrong parents.
        """
        if self._revision_graph_can_have_wrong_parents is None:
            self._ensure_real()
            self._revision_graph_can_have_wrong_parents = (
                self._custom_format.revision_graph_can_have_wrong_parents
            )
        return self._revision_graph_can_have_wrong_parents

    def _vfs_initialize(self, a_controldir, shared):
        """Helper for common code in initialize."""
        if self._custom_format:
            # Custom format requested
            result = self._custom_format.initialize(a_controldir, shared=shared)
        elif self._creating_bzrdir is not None:
            # Use the format that the repository we were created to back
            # has.
            prior_repo = self._creating_bzrdir.open_repository()
            prior_repo._ensure_real()
            result = prior_repo._real_repository._format.initialize(
                a_controldir, shared=shared
            )
        else:
            # assume that a_bzr is a RemoteBzrDir but the smart server didn't
            # support remote initialization.
            # We delegate to a real object at this point (as RemoteBzrDir
            # delegate to the repository format which would lead to infinite
            # recursion if we just called a_controldir.create_repository.
            a_controldir._ensure_real()
            result = a_controldir._real_bzrdir.create_repository(shared=shared)
        if not isinstance(result, RemoteRepository):
            return self.open(a_controldir)
        else:
            return result

    def initialize(self, a_controldir, shared=False):
        """Initialize a repository in the given control directory.

        Args:
            a_controldir: The control directory to initialize the repository in.
            shared: Whether to create a shared repository.

        Returns:
            A RemoteRepository instance representing the new repository.
        """
        # Being asked to create on a non RemoteBzrDir:
        if not isinstance(a_controldir, RemoteBzrDir):
            return self._vfs_initialize(a_controldir, shared)
        medium = a_controldir._client._medium
        if medium._is_remote_before((1, 13)):
            return self._vfs_initialize(a_controldir, shared)
        # Creating on a remote bzr dir.
        # 1) get the network name to use.
        if self._custom_format:
            network_name = self._custom_format.network_name()
        elif self._network_name:
            network_name = self._network_name
        else:
            # Select the current breezy default and ask for that.
            reference_bzrdir_format = controldir.format_registry.get("default")()
            reference_format = reference_bzrdir_format.repository_format
            network_name = reference_format.network_name()
        # 2) try direct creation via RPC
        path = a_controldir._path_for_remote_call(a_controldir._client)
        verb = b"BzrDir.create_repository"
        shared_str = b"True" if shared else b"False"
        try:
            response = a_controldir._call(verb, path, network_name, shared_str)
        except errors.UnknownSmartMethod:
            # Fallback - use vfs methods
            medium._remember_remote_is_before((1, 13))
            return self._vfs_initialize(a_controldir, shared)
        else:
            # Turn the response into a RemoteRepository object.
            format = response_tuple_to_repo_format(response[1:])
            # Used to support creating a real format instance when needed.
            format._creating_bzrdir = a_controldir
            remote_repo = RemoteRepository(a_controldir, format)
            format._creating_repo = remote_repo
            return remote_repo

    def open(self, a_controldir):
        """Open the repository in the given control directory.

        Args:
            a_controldir: The control directory containing the repository.

        Returns:
            A RemoteRepository instance.

        Raises:
            AssertionError: If a_controldir is not a RemoteBzrDir.
        """
        if not isinstance(a_controldir, RemoteBzrDir):
            raise AssertionError(f"{a_controldir!r} is not a RemoteBzrDir")
        return a_controldir.open_repository()

    def _ensure_real(self):
        """Ensure that a real (local) repository format is available.

        This method makes sure we have access to the underlying concrete
        repository format by looking it up in the network format registry.

        Raises:
            UnknownFormatError: If the network name is not recognized.
        """
        if self._custom_format is None:
            try:
                self._custom_format = _mod_repository.network_format_registry.get(
                    self._network_name
                )
            except KeyError as e:
                raise errors.UnknownFormatError(
                    kind="repository", format=self._network_name
                ) from e

    @property
    def _fetch_order(self):
        """The order preference for fetching data.

        Returns:
            The fetch order from the underlying format.
        """
        self._ensure_real()
        return self._custom_format._fetch_order

    @property
    def _fetch_uses_deltas(self):
        """Whether fetching uses delta compression.

        Returns:
            True if the format uses deltas for fetching.
        """
        self._ensure_real()
        return self._custom_format._fetch_uses_deltas

    @property
    def _fetch_reconcile(self):
        """Whether fetching requires reconciliation.

        Returns:
            True if the format requires reconciliation during fetch.
        """
        self._ensure_real()
        return self._custom_format._fetch_reconcile

    def get_format_description(self):
        """Get a human-readable description of this repository format.

        Returns:
            A string describing the format, prefixed with 'Remote: '.
        """
        self._ensure_real()
        return "Remote: " + self._custom_format.get_format_description()

    def __eq__(self, other):
        """Check if this format is equal to another format.

        Args:
            other: Another format object to compare with.

        Returns:
            True if both objects are instances of the same class.
        """
        return self.__class__ is other.__class__

    def network_name(self):
        """Get the network name for this repository format.

        Returns:
            The network name string for this format.
        """
        if self._network_name:
            return self._network_name
        self._creating_repo._ensure_real()
        return self._creating_repo._real_repository._format.network_name()

    @property
    def pack_compresses(self):
        """Whether this format compresses pack data.

        Returns:
            True if the format compresses pack data.
        """
        self._ensure_real()
        return self._custom_format.pack_compresses

    @property
    def _revision_serializer(self):
        """Get the revision serializer for this format.

        Returns:
            The revision serializer from the underlying format.
        """
        self._ensure_real()
        return self._custom_format._revision_serializer

    @property
    def _inventory_serializer(self):
        """Get the inventory serializer for this format.

        Returns:
            The inventory serializer from the underlying format.
        """
        self._ensure_real()
        return self._custom_format._inventory_serializer


class RemoteRepository(_mod_repository.Repository, _RpcHelper, lock._RelockDebugMixin):
    """Repository accessed over rpc.

    For the moment most operations are performed using local transport-backed
    Repository objects.
    """

    _format: RemoteRepositoryFormat
    _real_repository: Optional[_mod_repository.Repository]

    def __init__(
        self,
        remote_bzrdir: RemoteBzrDir,
        format: RemoteRepositoryFormat,
        real_repository: Optional[_mod_repository.Repository] = None,
        _client=None,
    ):
        """Create a RemoteRepository instance.

        :param remote_bzrdir: The bzrdir hosting this repository.
        :param format: The RemoteFormat object to use.
        :param real_repository: If not None, a local implementation of the
            repository logic for the repository, usually accessing the data
            via the VFS.
        :param _client: Private testing parameter - override the smart client
            to be used by the repository.
        """
        if real_repository:
            self._real_repository = real_repository
        else:
            self._real_repository = None
        self.controldir = remote_bzrdir
        if _client is None:
            self._client = remote_bzrdir._client
        else:
            self._client = _client
        self._format = format
        self._lock_mode = None
        self._lock_token = None
        self._write_group_tokens = None
        self._lock_count = 0
        self._leave_lock = False
        # Cache of revision parents; misses are cached during read locks, and
        # write locks when no _real_repository has been set.
        self._unstacked_provider = graph.CachingParentsProvider(
            get_parent_map=self._get_parent_map_rpc
        )
        self._unstacked_provider.disable_cache()
        # For tests:
        # These depend on the actual remote format, so force them off for
        # maximum compatibility. XXX: In future these should depend on the
        # remote repository instance, but this is irrelevant until we perform
        # reconcile via an RPC call.
        self._reconcile_does_inventory_gc = False
        self._reconcile_fixes_text_parents = False
        self._reconcile_backsup_inventory = False
        self.base = self.controldir.transport.base
        # Additional places to query for data.
        self._fallback_repositories = []

    @property
    def user_transport(self):
        """Get the user transport for this repository."""
        return self.controldir.user_transport

    @property
    def control_transport(self):
        """Get the control transport for this repository."""
        # XXX: Normally you shouldn't directly get at the remote repository
        # transport, but I'm not sure it's worth making this method
        # optional -- mbp 2010-04-21
        return self.controldir.get_repository_transport(None)

    def __str__(self):
        """Return string representation of this repository."""
        return f"{self.__class__.__name__}({self.base})"

    __repr__ = __str__

    def abort_write_group(self, suppress_errors=False):
        """Complete a write group on the decorated repository.

        Smart methods perform operations in a single step so this API
        is not really applicable except as a compatibility thunk
        for older plugins that don't use e.g. the CommitBuilder
        facility.

        :param suppress_errors: see Repository.abort_write_group.
        """
        if self._real_repository:
            self._ensure_real()
            return self._real_repository.abort_write_group(
                suppress_errors=suppress_errors
            )
        if not self.is_in_write_group():
            if suppress_errors:
                mutter("(suppressed) not in write group")
                return
            raise errors.BzrError("not in write group")
        path = self.controldir._path_for_remote_call(self._client)
        try:
            response = self._call(
                b"Repository.abort_write_group",
                path,
                self._lock_token,
                [token.encode("utf-8") for token in self._write_group_tokens],
            )
        except Exception as exc:
            self._write_group = None
            if not suppress_errors:
                raise
            mutter("abort_write_group failed")
            log_exception_quietly()
            note(gettext("bzr: ERROR (ignored): %s"), exc)
        else:
            if response != (b"ok",):
                raise errors.UnexpectedSmartServerResponse(response)
            self._write_group_tokens = None

    @property
    def chk_bytes(self):
        """Decorate the real repository for now.

        In the long term a full blown network facility is needed to avoid
        creating a real repository object locally.
        """
        self._ensure_real()
        return self._real_repository.chk_bytes

    def commit_write_group(self):
        """Complete a write group on the decorated repository.

        Smart methods perform operations in a single step so this API
        is not really applicable except as a compatibility thunk
        for older plugins that don't use e.g. the CommitBuilder
        facility.
        """
        if self._real_repository:
            self._ensure_real()
            return self._real_repository.commit_write_group()
        if not self.is_in_write_group():
            raise errors.BzrError("not in write group")
        path = self.controldir._path_for_remote_call(self._client)
        response = self._call(
            b"Repository.commit_write_group",
            path,
            self._lock_token,
            [token.encode("utf-8") for token in self._write_group_tokens],
        )
        if response != (b"ok",):
            raise errors.UnexpectedSmartServerResponse(response)
        self._write_group_tokens = None
        # Refresh data after writing to the repository.
        self.refresh_data()

    def resume_write_group(self, tokens):
        """Resume a write group with the given tokens.

        Continues a write group operation that was previously suspended,
        using the provided tokens to restore the write group state.

        Args:
            tokens: List of tokens representing the suspended write group state.
                   Each token is a string identifier for a write group component.

        Returns:
            None

        Raises:
            UnexpectedSmartServerResponse: If the server response is malformed.
            UnknownSmartMethod: If the server doesn't support this operation,
                               in which case the operation falls back to VFS.
        """
        if self._real_repository:
            return self._real_repository.resume_write_group(tokens)
        path = self.controldir._path_for_remote_call(self._client)
        try:
            response = self._call(
                b"Repository.check_write_group",
                path,
                self._lock_token,
                [token.encode("utf-8") for token in tokens],
            )
        except errors.UnknownSmartMethod:
            self._ensure_real()
            return self._real_repository.resume_write_group(tokens)
        if response != (b"ok",):
            raise errors.UnexpectedSmartServerResponse(response)
        self._write_group_tokens = tokens

    def suspend_write_group(self):
        """Suspend the current write group and return its tokens.

        Temporarily halts a write group operation and returns tokens that
        can be used later to resume the write group with resume_write_group().

        Returns:
            List of tokens representing the suspended write group state.
            Each token is a string identifier for a write group component.
            Returns an empty list if no write group is active.
        """
        if self._real_repository:
            return self._real_repository.suspend_write_group()
        ret = self._write_group_tokens or []
        self._write_group_tokens = None
        return ret

    def get_missing_parent_inventories(self, check_for_missing_texts=True):
        """Return inventories from the ancestry that are not present.

        This method identifies inventory objects that are referenced by
        the repository's revision history but are not actually stored
        in the repository.

        Args:
            check_for_missing_texts: If True, also verify that the text
                                   objects referenced by inventories are present.
                                   Defaults to True.

        Returns:
            A collection of inventory keys that are missing from the repository.
            The exact type depends on the underlying repository implementation.

        Note:
            This method requires VFS access and will trigger _ensure_real().
        """
        self._ensure_real()
        return self._real_repository.get_missing_parent_inventories(
            check_for_missing_texts=check_for_missing_texts
        )

    def _get_rev_id_for_revno_vfs(self, revno, known_pair):
        """VFS fallback for getting revision ID from revision number.

        This is a private fallback method used when the smart server
        doesn't support the Repository.get_rev_id_for_revno RPC or
        when working with older server versions.

        Args:
            revno: The revision number to look up.
            known_pair: A (revno, revid) pair representing a known point
                       in the revision history for optimization.

        Returns:
            Same as get_rev_id_for_revno(): A tuple (found, result) where
            found is a boolean and result is either the revision_id (if found)
            or a (revno, revid) pair of a known point (if not found).

        Note:
            This method requires VFS access and will trigger _ensure_real().
        """
        self._ensure_real()
        return self._real_repository.get_rev_id_for_revno(revno, known_pair)

    def get_rev_id_for_revno(self, revno, known_pair):
        """See Repository.get_rev_id_for_revno."""
        path = self.controldir._path_for_remote_call(self._client)
        try:
            if self._client._medium._is_remote_before((1, 17)):
                return self._get_rev_id_for_revno_vfs(revno, known_pair)
            response = self._call(
                b"Repository.get_rev_id_for_revno", path, revno, known_pair
            )
        except errors.UnknownSmartMethod:
            self._client._medium._remember_remote_is_before((1, 17))
            return self._get_rev_id_for_revno_vfs(revno, known_pair)
        except UnknownErrorFromSmartServer as e:
            # Older versions of Bazaar/Breezy (<< 3.0.0) would raise a
            # ValueError instead of returning revno-outofbounds
            if len(e.error_tuple) < 3:
                raise
            if e.error_tuple[:2] != (b"error", b"ValueError"):
                raise
            m = re.match(
                rb"requested revno \(([0-9]+)\) is later than given "
                rb"known revno \(([0-9]+)\)",
                e.error_tuple[2],
            )
            if not m:
                raise
            raise errors.RevnoOutOfBounds(int(m.group(1)), (0, int(m.group(2)))) from e
        if response[0] == b"ok":
            return True, response[1]
        elif response[0] == b"history-incomplete":
            known_pair = response[1:3]
            for fallback in self._fallback_repositories:
                found, result = fallback.get_rev_id_for_revno(revno, known_pair)
                if found:
                    return True, result
                else:
                    known_pair = result
            # Not found in any fallbacks
            return False, known_pair
        else:
            raise errors.UnexpectedSmartServerResponse(response)

    def _ensure_real(self):
        """Ensure that there is a _real_repository set.

        Used before calls to self._real_repository.

        Note that _ensure_real causes many roundtrips to the server which are
        not desirable, and prevents the use of smart one-roundtrip RPC's to
        perform complex operations (such as accessing parent data, streaming
        revisions etc). Adding calls to _ensure_real should only be done when
        bringing up new functionality, adding fallbacks for smart methods that
        require a fallback path, and never to replace an existing smart method
        invocation. If in doubt chat to the bzr network team.
        """
        if self._real_repository is None:
            if debug.debug_flag_enabled("hpssvfs"):
                import traceback

                warning(
                    "VFS Repository access triggered\n%s",
                    "".join(traceback.format_stack()),
                )
            self._unstacked_provider.missing_keys.clear()
            self.controldir._ensure_real()
            self._set_real_repository(self.controldir._real_bzrdir.open_repository())

    def _translate_error(self, err, **context):
        self.controldir._translate_error(err, repository=self, **context)

    def find_text_key_references(self):
        """Find the text key references within the repository.

        :return: A dictionary mapping text keys ((fileid, revision_id) tuples)
            to whether they were referred to by the inventory of the
            revision_id that they contain. The inventory texts from all present
            revision ids are assessed to generate this report.
        """
        self._ensure_real()
        return self._real_repository.find_text_key_references()

    def _generate_text_key_index(self):
        """Generate a new text key index for the repository.

        This is an expensive function that will take considerable time to run.

        :return: A dict mapping (file_id, revision_id) tuples to a list of
            parents, also (file_id, revision_id) tuples.
        """
        self._ensure_real()
        return self._real_repository._generate_text_key_index()

    def _get_revision_graph(self, revision_id: RevisionID):
        """Private method for using with old (< 1.2) servers to fallback."""
        if revision_id is None:
            revision_id = b""
        elif _mod_revision.is_null(revision_id):
            return {}

        path = self.controldir._path_for_remote_call(self._client)
        response = self._call_expecting_body(
            b"Repository.get_revision_graph", path, revision_id
        )
        response_tuple, response_handler = response
        if response_tuple[0] != b"ok":
            raise errors.UnexpectedSmartServerResponse(response_tuple)
        coded = response_handler.read_body_bytes()
        if coded == b"":
            # no revisions in this repository!
            return {}
        lines = coded.split(b"\n")
        revision_graph = {}
        for line in lines:
            d = tuple(line.split())
            revision_graph[d[0]] = d[1:]

        return revision_graph

    def _get_sink(self):
        """See Repository._get_sink()."""
        return RemoteStreamSink(self)

    def _get_source(self, to_format):
        """Get a source for converting to the specified format.

        Args:
            to_format: Target format for conversion.

        Returns:
            Source object for format conversion.
        """
        """Return a source for streaming from this repository."""
        return RemoteStreamSource(self, to_format)

    def get_file_graph(self):
        """Get a graph of file text relationships.

        Creates a graph object that can be used to traverse the relationships
        between different versions of file texts in the repository.

        Returns:
            A Graph object representing file text relationships, with the
            repository's text store as the parent provider.
        """
        with self.lock_read():
            return graph.Graph(self.texts)

    def has_revision(self, revision_id):
        """Check if a revision is present in this repository.

        Args:
            revision_id: The revision ID to check.

        Returns:
            bool: True if the revision is present.
        """
        """True if this repository has a copy of the revision."""
        # Copy of breezy.repository.Repository.has_revision
        with self.lock_read():
            return revision_id in self.has_revisions((revision_id,))

    def has_revisions(self, revision_ids):
        """Check which revisions are present in this repository.

        Args:
            revision_ids: Iterable of revision IDs to check.

        Returns:
            Set of revision IDs that are present.
        """
        """Probe to find out the presence of multiple revisions.

        :param revision_ids: An iterable of revision_ids.
        :return: A set of the revision_ids that were present.
        """
        with self.lock_read():
            # Copy of breezy.repository.Repository.has_revisions
            parent_map = self.get_parent_map(revision_ids)
            result = set(parent_map)
            if _mod_revision.NULL_REVISION in revision_ids:
                result.add(_mod_revision.NULL_REVISION)
            return result

    def _has_same_fallbacks(self, other_repo):
        """Returns true if the repositories have the same fallbacks."""
        # XXX: copied from Repository; it should be unified into a base class
        # <https://bugs.launchpad.net/bzr/+bug/401622>
        my_fb = self._fallback_repositories
        other_fb = other_repo._fallback_repositories
        if len(my_fb) != len(other_fb):
            return False
        return all(f.has_same_location(g) for f, g in zip(my_fb, other_fb))

    def has_same_location(self, other):
        """Check if this repository has the same location as another.

        Compares this repository with another to determine if they refer
        to the same physical location, taking into account both the class
        type and the transport base URL.

        Args:
            other: Another repository object to compare with.

        Returns:
            True if both repositories have the same class and transport base,
            False otherwise.

        Note:
            TODO: Move to RepositoryBase and unify with the regular Repository
            one; unfortunately the tests rely on slightly different behaviour at
            present -- mbp 20090710
        """
        # TODO: Move to RepositoryBase and unify with the regular Repository
        # one; unfortunately the tests rely on slightly different behaviour at
        # present -- mbp 20090710
        return (
            self.__class__ is other.__class__
            and self.controldir.transport.base == other.controldir.transport.base
        )

    def get_graph(self, other_repository=None):
        """Return the graph for this repository format."""
        parents_provider = self._make_parents_provider(other_repository)
        return graph.Graph(parents_provider)

    def get_known_graph_ancestry(self, revision_ids):
        """Return the known graph for a set of revision ids and their ancestors."""
        with self.lock_read():
            revision_graph = {
                key: value
                for key, value in self.get_graph().iter_ancestry(revision_ids)
                if value is not None
            }
            revision_graph = _mod_repository._strip_NULL_ghosts(revision_graph)
            return graph.KnownGraph(revision_graph)

    def gather_stats(self, revid=None, committers=None):
        """See Repository.gather_stats()."""
        path = self.controldir._path_for_remote_call(self._client)
        # revid can be None to indicate no revisions, not just NULL_REVISION
        fmt_revid = b"" if revid is None or _mod_revision.is_null(revid) else revid
        fmt_committers = b"no" if committers is None or not committers else b"yes"
        response_tuple, response_handler = self._call_expecting_body(
            b"Repository.gather_stats", path, fmt_revid, fmt_committers
        )
        if response_tuple[0] != b"ok":
            raise errors.UnexpectedSmartServerResponse(response_tuple)

        body = response_handler.read_body_bytes()
        result = {}
        for line in body.split(b"\n"):
            if not line:
                continue
            key, val_text = line.split(b":")
            key = key.decode("ascii")
            if key in ("revisions", "size", "committers"):
                result[key] = int(val_text)
            elif key in ("firstrev", "latestrev"):
                values = val_text.split(b" ")[1:]
                result[key] = (float(values[0]), int(values[1]))

        return result

    def find_branches(self, using=False):
        """See Repository.find_branches()."""
        # should be an API call to the server.
        self._ensure_real()
        return self._real_repository.find_branches(using=using)

    def get_physical_lock_status(self):
        """See Repository.get_physical_lock_status()."""
        path = self.controldir._path_for_remote_call(self._client)
        try:
            response = self._call(b"Repository.get_physical_lock_status", path)
        except errors.UnknownSmartMethod:
            self._ensure_real()
            return self._real_repository.get_physical_lock_status()
        if response[0] not in (b"yes", b"no"):
            raise errors.UnexpectedSmartServerResponse(response)
        return response[0] == b"yes"

    def is_in_write_group(self):
        """Return True if there is an open write group.

        write groups are only applicable locally for the smart server..
        """
        if self._write_group_tokens is not None:
            return True
        if self._real_repository:
            return self._real_repository.is_in_write_group()

    def is_locked(self):
        """Check if the repository is locked.

        Returns:
            True if the repository has any active locks, False otherwise.
        """
        return self._lock_count >= 1

    def is_shared(self):
        """See Repository.is_shared()."""
        path = self.controldir._path_for_remote_call(self._client)
        response = self._call(b"Repository.is_shared", path)
        if response[0] not in (b"yes", b"no"):
            raise SmartProtocolError(f"unexpected response code {response}")
        return response[0] == b"yes"

    def is_write_locked(self):
        """Check if the repository is write locked.

        Returns:
            True if the repository is locked for writing, False otherwise.
        """
        return self._lock_mode == "w"

    def _warn_if_deprecated(self, branch=None):
        """Warn if this repository format is deprecated.

        Args:
            branch: Optional branch to check for deprecation.

        Note:
            For remote repositories, deprecation checking is delegated
            to the real repository or done remotely.
        """
        # If we have a real repository, the check will be done there, if we
        # don't the check will be done remotely.
        pass

    def lock_read(self):
        """Lock the repository for read operations.

        :return: A breezy.lock.LogicalLockResult.
        """
        # wrong eventually - want a local lock cache context
        if not self._lock_mode:
            self._note_lock("r")
            self._lock_mode = "r"
            self._lock_count = 1
            self._unstacked_provider.enable_cache(cache_misses=True)
            if self._real_repository is not None:
                self._real_repository.lock_read()
            for repo in self._fallback_repositories:
                repo.lock_read()
        else:
            self._lock_count += 1
        return lock.LogicalLockResult(self.unlock)

    def _remote_lock_write(self, token):
        path = self.controldir._path_for_remote_call(self._client)
        if token is None:
            token = b""
        err_context = {"token": token}
        response = self._call(b"Repository.lock_write", path, token, **err_context)
        if response[0] == b"ok":
            ok, token = response
            return token
        else:
            raise errors.UnexpectedSmartServerResponse(response)

    def lock_write(self, token=None, _skip_rpc=False):
        """Lock the repository for write operations.

        Acquires a write lock on the repository, optionally using a provided
        token to resume a previous lock state.

        Args:
            token: Optional lock token to resume a previous lock state.
                  If None, a new write lock will be acquired.
            _skip_rpc: Private parameter to skip the RPC call for testing.
                      Should not be used by regular code.

        Returns:
            A RepositoryWriteLockResult containing the unlock method and
            the lock token (if any).

        Raises:
            ReadOnlyError: If attempting to acquire write lock while already
                          read-locked.
            TokenMismatch: If the provided token doesn't match the expected token.
            UnexpectedSmartServerResponse: If the server returns an unexpected response.
        """
        if not self._lock_mode:
            self._note_lock("w")
            if _skip_rpc:
                if self._lock_token is not None and token != self._lock_token:
                    raise errors.TokenMismatch(token, self._lock_token)
                self._lock_token = token
            else:
                self._lock_token = self._remote_lock_write(token)
            # if self._lock_token is None, then this is something like packs or
            # svn where we don't get to lock the repo, or a weave style repository
            # where we cannot lock it over the wire and attempts to do so will
            # fail.
            if self._real_repository is not None:
                self._real_repository.lock_write(token=self._lock_token)
            if token is not None:
                self._leave_lock = True
            else:
                self._leave_lock = False
            self._lock_mode = "w"
            self._lock_count = 1
            cache_misses = self._real_repository is None
            self._unstacked_provider.enable_cache(cache_misses=cache_misses)
            for repo in self._fallback_repositories:
                # Writes don't affect fallback repos
                repo.lock_read()
        elif self._lock_mode == "r":
            raise errors.ReadOnlyError(self)
        else:
            self._lock_count += 1
        return RepositoryWriteLockResult(self.unlock, self._lock_token or None)

    def leave_lock_in_place(self):
        """Configure the repository to leave the lock in place on unlock.

        This prevents the lock from being automatically released when
        unlock() is called, which is useful for operations that need
        to maintain locks across multiple method calls.

        Raises:
            NotImplementedError: If the repository doesn't have a lock token.
        """
        if not self._lock_token:
            raise NotImplementedError(self.leave_lock_in_place)
        self._leave_lock = True

    def dont_leave_lock_in_place(self):
        """Configure the repository to release the lock on unlock.

        This restores the default behavior where the lock is automatically
        released when unlock() is called.

        Raises:
            NotImplementedError: If the repository doesn't have a lock token.
        """
        if not self._lock_token:
            raise NotImplementedError(self.dont_leave_lock_in_place)
        self._leave_lock = False

    def _set_real_repository(self, repository: _mod_repository.Repository):
        """Set the _real_repository for this repository.

        :param repository: The repository to fallback to for non-hpss
            implemented operations.
        """
        if self._real_repository is not None:
            # Replacing an already set real repository.
            # We cannot do this [currently] if the repository is locked -
            # synchronised state might be lost.
            if self.is_locked():
                raise AssertionError("_real_repository is already set")
        if isinstance(repository, RemoteRepository):
            raise AssertionError()
        self._real_repository = repository
        # three code paths happen here:
        # 1) old servers, RemoteBranch.open() calls _ensure_real before setting
        # up stacking. In this case self._fallback_repositories is [], and the
        # real repo is already setup. Preserve the real repo and
        # RemoteRepository.add_fallback_repository will avoid adding
        # duplicates.
        # 2) new servers, RemoteBranch.open() sets up stacking, and when
        # ensure_real is triggered from a branch, the real repository to
        # set already has a matching list with separate instances, but
        # as they are also RemoteRepositories we don't worry about making the
        # lists be identical.
        # 3) new servers, RemoteRepository.ensure_real is triggered before
        # RemoteBranch.ensure real, in this case we get a repo with no fallbacks
        # and need to populate it.
        if self._fallback_repositories and len(
            self._real_repository._fallback_repositories
        ) != len(self._fallback_repositories):
            if len(self._real_repository._fallback_repositories):
                raise AssertionError(
                    "cannot cleanly remove existing _fallback_repositories"
                )
        for fb in self._fallback_repositories:
            self._real_repository.add_fallback_repository(fb)
        if self._lock_mode == "w":
            # if we are already locked, the real repository must be able to
            # acquire the lock with our token.
            self._real_repository.lock_write(self._lock_token)
        elif self._lock_mode == "r":
            self._real_repository.lock_read()
        if self._write_group_tokens is not None:
            # if we are already in a write group, resume it
            self._real_repository.resume_write_group(self._write_group_tokens)
            self._write_group_tokens = None

    def start_write_group(self):
        """Start a write group on the decorated repository.

        Smart methods perform operations in a single step so this API
        is not really applicable except as a compatibility thunk
        for older plugins that don't use e.g. the CommitBuilder
        facility.
        """
        if self._real_repository:
            self._ensure_real()
            return self._real_repository.start_write_group()
        if not self.is_write_locked():
            raise errors.NotWriteLocked(self)
        if self._write_group_tokens is not None:
            raise errors.BzrError("already in a write group")
        path = self.controldir._path_for_remote_call(self._client)
        try:
            response = self._call(
                b"Repository.start_write_group", path, self._lock_token
            )
        except (errors.UnknownSmartMethod, errors.UnsuspendableWriteGroup):
            self._ensure_real()
            return self._real_repository.start_write_group()
        if response[0] != b"ok":
            raise errors.UnexpectedSmartServerResponse(response)
        self._write_group_tokens = [token.decode("utf-8") for token in response[1]]

    def _unlock(self, token):
        path = self.controldir._path_for_remote_call(self._client)
        if not token:
            # with no token the remote repository is not persistently locked.
            return
        err_context = {"token": token}
        response = self._call(b"Repository.unlock", path, token, **err_context)
        if response == (b"ok",):
            return
        else:
            raise errors.UnexpectedSmartServerResponse(response)

    @only_raises(errors.LockNotHeld, errors.LockBroken)
    def unlock(self):
        """Release any locks held on this repository.

        Decrements the lock count and releases the actual lock when
        the count reaches zero. For write locks, this may involve
        calling the server to release the remote lock.

        Returns:
            None

        Raises:
            LockNotHeld: If no lock is currently held.
            LockBroken: If the lock has been broken by another process.
        """
        if not self._lock_count:
            return lock.cant_unlock_not_held(self)
        self._lock_count -= 1
        if self._lock_count > 0:
            return
        self._unstacked_provider.disable_cache()
        old_mode = self._lock_mode
        self._lock_mode = None
        try:
            # The real repository is responsible at present for raising an
            # exception if it's in an unfinished write group.  However, it
            # normally will *not* actually remove the lock from disk - that's
            # done by the server on receiving the Repository.unlock call.
            # This is just to let the _real_repository stay up to date.
            if self._real_repository is not None:
                self._real_repository.unlock()
            elif self._write_group_tokens is not None:
                self.abort_write_group()
        finally:
            # The rpc-level lock should be released even if there was a
            # problem releasing the vfs-based lock.
            if old_mode == "w":
                # Only write-locked repositories need to make a remote method
                # call to perform the unlock.
                old_token = self._lock_token
                self._lock_token = None
                if not self._leave_lock:
                    self._unlock(old_token)
        # Fallbacks are always 'lock_read()' so we don't pay attention to
        # self._leave_lock
        for repo in self._fallback_repositories:
            repo.unlock()

    def break_lock(self):
        """Break any existing locks on this repository.

        Raises:
            UnexpectedSmartServerResponse: If the server returns an unexpected response.
        """
        # should hand off to the network
        path = self.controldir._path_for_remote_call(self._client)
        try:
            response = self._call(b"Repository.break_lock", path)
        except errors.UnknownSmartMethod:
            self._ensure_real()
            return self._real_repository.break_lock()
        if response != (b"ok",):
            raise errors.UnexpectedSmartServerResponse(response)

    def _get_tarball(self, compression):
        """Return a TemporaryFile containing a repository tarball.

        Returns None if the server does not support sending tarballs.
        """
        import tempfile

        path = self.controldir._path_for_remote_call(self._client)
        try:
            response, protocol = self._call_expecting_body(
                b"Repository.tarball", path, compression.encode("ascii")
            )
        except errors.UnknownSmartMethod:
            protocol.cancel_read_body()
            return None
        if response[0] == b"ok":
            # Extract the tarball and return it
            t = tempfile.NamedTemporaryFile()
            # TODO: rpc layer should read directly into it...
            t.write(protocol.read_body_bytes())
            t.seek(0)
            return t
        raise errors.UnexpectedSmartServerResponse(response)

    def sprout(self, to_bzrdir, revision_id=None):
        """Create a descendent repository for new development.

        Unlike clone, this does not copy the settings of the repository.
        """
        with self.lock_read():
            dest_repo = self._create_sprouting_repo(to_bzrdir, shared=False)
            dest_repo.fetch(self, revision_id=revision_id)
            return dest_repo

    def _create_sprouting_repo(self, a_controldir, shared):
        if not isinstance(a_controldir._format, self.controldir._format.__class__):
            # use target default format.
            dest_repo = a_controldir.create_repository()
        else:
            # Most control formats need the repository to be specifically
            # created, but on some old all-in-one formats it's not needed
            try:
                dest_repo = self._format.initialize(a_controldir, shared=shared)
            except errors.UninitializableFormat:
                dest_repo = a_controldir.open_repository()
        return dest_repo

    # These methods are just thin shims to the VFS object for now.

    def revision_tree(self, revision_id):
        """Get the revision tree for a specific revision.

        Creates a revision tree object representing the state of files
        and directories at a particular revision.

        Args:
            revision_id: The revision ID to create a tree for.

        Returns:
            An InventoryRevisionTree for the specified revision.
            For NULL_REVISION, returns an empty tree.
        """
        with self.lock_read():
            if revision_id == _mod_revision.NULL_REVISION:
                return InventoryRevisionTree(
                    self, Inventory(root_id=None), _mod_revision.NULL_REVISION
                )
            else:
                return list(self.revision_trees([revision_id]))[0]

    def get_serializer_format(self):
        """Get the serializer format for this repository."""
        path = self.controldir._path_for_remote_call(self._client)
        try:
            response = self._call(
                b"VersionedFileRepository.get_serializer_format", path
            )
        except errors.UnknownSmartMethod:
            self._ensure_real()
            return self._real_repository.get_serializer_format()
        if response[0] != b"ok":
            raise errors.UnexpectedSmartServerResponse(response)
        return response[1]

    def get_commit_builder(
        self,
        branch,
        parents,
        config,
        timestamp=None,
        timezone=None,
        committer=None,
        revprops=None,
        revision_id=None,
        lossy=False,
    ):
        """Obtain a CommitBuilder for this repository.

        :param branch: Branch to commit to.
        :param parents: Revision ids of the parents of the new revision.
        :param config: Configuration to use.
        :param timestamp: Optional timestamp recorded for commit.
        :param timezone: Optional timezone for timestamp.
        :param committer: Optional committer to set for commit.
        :param revprops: Optional dictionary of revision properties.
        :param revision_id: Optional revision id.
        :param lossy: Whether to discard data that can not be natively
            represented, when pushing to a foreign VCS
        """
        if self._fallback_repositories and not self._format.supports_chks:
            raise errors.BzrError(
                "Cannot commit directly to a stacked branch"
                " in pre-2a formats. See "
                "https://bugs.launchpad.net/bzr/+bug/375013 for details."
            )
        commit_builder_kls = vf_repository.VersionedFileCommitBuilder
        result = commit_builder_kls(
            self,
            parents,
            config,
            timestamp,
            timezone,
            committer,
            revprops,
            revision_id,
            lossy,
        )
        self.start_write_group()
        return result

    def add_fallback_repository(self, repository):
        """Add a repository to use for looking up data not held locally.

        :param repository: A repository.
        """
        if not self._format.supports_external_lookups:
            raise errors.UnstackableRepositoryFormat(
                self._format.network_name(), self.base
            )
        # We need to accumulate additional repositories here, to pass them in
        # on various RPC's.
        #
        # Make the check before we lock: this raises an exception.
        self._check_fallback_repository(repository)
        if self.is_locked():
            # We will call fallback.unlock() when we transition to the unlocked
            # state, so always add a lock here. If a caller passes us a locked
            # repository, they are responsible for unlocking it later.
            repository.lock_read()
        self._fallback_repositories.append(repository)
        # If self._real_repository was parameterised already (e.g. because a
        # _real_branch had its get_stacked_on_url method called), then the
        # repository to be added may already be in the _real_repositories list.
        if self._real_repository is not None:
            fallback_locations = [
                repo.user_url for repo in self._real_repository._fallback_repositories
            ]
            if repository.user_url not in fallback_locations:
                self._real_repository.add_fallback_repository(repository)

    def _check_fallback_repository(self, repository):
        """Check that this repository can fallback to repository safely.

        Raise an error if not.

        :param repository: A repository to fallback to.
        """
        return _mod_repository.InterRepository._assert_same_model(self, repository)

    def add_inventory(self, revid, inv, parents):
        """Add an inventory to the repository.

        Args:
            revid: Revision ID for the inventory.
            inv: Inventory to add.
            parents: Parent inventories.
        """
        self._ensure_real()
        return self._real_repository.add_inventory(revid, inv, parents)

    def add_inventory_by_delta(
        self,
        basis_revision_id,
        delta,
        new_revision_id,
        parents,
        basis_inv=None,
        propagate_caches=False,
    ):
        """Add an inventory by delta to the repository.

        Args:
            basis_revision_id: Revision ID of basis inventory.
            delta: Inventory delta to apply.
            new_revision_id: Revision ID for new inventory.
            parents: Parent revision IDs.
            basis_inv: Optional basis inventory.
            propagate_caches: Whether to propagate caches.
        """
        self._ensure_real()
        return self._real_repository.add_inventory_by_delta(
            basis_revision_id,
            delta,
            new_revision_id,
            parents,
            basis_inv=basis_inv,
            propagate_caches=propagate_caches,
        )

    def add_revision(self, revision_id, rev, inv=None):
        """Add a revision to the repository.

        Args:
            revision_id: The revision ID to add.
            rev: The revision object to add.
            inv: Optional inventory for the revision.
        """
        _mod_revision.check_not_reserved_id(revision_id)
        key = (revision_id,)
        # check inventory present
        if not self.inventories.get_parent_map([key]):
            if inv is None:
                raise errors.WeaveRevisionNotPresent(revision_id, self.inventories)
            else:
                # yes, this is not suitable for adding with ghosts.
                rev.inventory_sha1 = self.add_inventory(
                    revision_id, inv, rev.parent_ids
                )
        else:
            rev.inventory_sha1 = self.inventories.get_sha1s([key])[key]
        self._add_revision(rev)

    def _add_revision(self, rev):
        if self._real_repository is not None:
            return self._real_repository._add_revision(rev)
        lines = self._revision_serializer.write_revision_to_lines(rev)
        key = (rev.revision_id,)
        parents = tuple((parent,) for parent in rev.parent_ids)
        self._write_group_tokens, missing_keys = self._get_sink().insert_stream(
            [
                (
                    "revisions",
                    [
                        ChunkedContentFactory(
                            key, parents, None, lines, chunks_are_lines=True
                        )
                    ],
                )
            ],
            self._format,
            self._write_group_tokens,
        )

    def get_inventory(self, revision_id):
        """Get the inventory for a specific revision.

        Retrieves the inventory object that describes the file and directory
        structure for a given revision.

        Args:
            revision_id: The revision ID to get the inventory for.

        Returns:
            An Inventory object for the specified revision.

        Raises:
            NoSuchRevision: If the revision_id is not present in the repository.
        """
        with self.lock_read():
            return list(self.iter_inventories([revision_id]))[0]

    def _iter_inventories_rpc(self, revision_ids, ordering):
        if ordering is None:
            ordering = "unordered"
        path = self.controldir._path_for_remote_call(self._client)
        body = b"\n".join(revision_ids)
        response_tuple, response_handler = self._call_with_body_bytes_expecting_body(
            b"VersionedFileRepository.get_inventories",
            (path, ordering.encode("ascii")),
            body,
        )
        if response_tuple[0] != b"ok":
            raise errors.UnexpectedSmartServerResponse(response_tuple)
        deserializer = inventory_delta.InventoryDeltaDeserializer()
        byte_stream = response_handler.read_streamed_body()
        decoded = smart_repo._byte_stream_to_stream(byte_stream)
        if decoded is None:
            # no results whatsoever
            return
        src_format, stream = decoded
        if src_format.network_name() != self._format.network_name():
            raise AssertionError(
                "Mismatched RemoteRepository and stream src {!r}, {!r}".format(
                    src_format.network_name(), self._format.network_name()
                )
            )
        # ignore the src format, it's not really relevant
        prev_inv = Inventory(root_id=None, revision_id=_mod_revision.NULL_REVISION)
        # there should be just one substream, with inventory deltas
        try:
            substream_kind, substream = next(stream)
        except StopIteration:
            return
        if substream_kind != "inventory-deltas":
            raise AssertionError(f"Unexpected stream {substream_kind!r} received")
        for record in substream:
            (
                parent_id,
                new_id,
                versioned_root,
                tree_references,
                invdelta,
            ) = deserializer.parse_text_bytes(record.get_bytes_as("lines"))
            invdelta = InventoryDelta(invdelta)
            if parent_id != prev_inv.revision_id:
                raise AssertionError(
                    f"invalid base {parent_id!r} != {prev_inv.revision_id!r}"
                )
            inv = prev_inv.create_by_apply_delta(invdelta, new_id)
            yield inv, inv.revision_id
            prev_inv = inv

    def _iter_inventories_vfs(self, revision_ids, ordering=None):
        self._ensure_real()
        return self._real_repository._iter_inventories(revision_ids, ordering)

    def iter_inventories(self, revision_ids, ordering=None):
        """Get many inventories by revision_ids.

        This will buffer some or all of the texts used in constructing the
        inventories in memory, but will only parse a single inventory at a
        time.

        :param revision_ids: The expected revision ids of the inventories.
        :param ordering: optional ordering, e.g. 'topological'.  If not
            specified, the order of revision_ids will be preserved (by
            buffering if necessary).
        :return: An iterator of inventories.
        """
        if (None in revision_ids) or (_mod_revision.NULL_REVISION in revision_ids):
            raise ValueError("cannot get null revision inventory")
        for inv, revid in self._iter_inventories(revision_ids, ordering):
            if inv is None:
                raise errors.NoSuchRevision(self, revid)
            yield inv

    def _iter_inventories(self, revision_ids, ordering=None):
        if len(revision_ids) == 0:
            return
        missing = set(revision_ids)
        if ordering is None:
            order_as_requested = True
            invs = {}
            order = list(revision_ids)
            order.reverse()
            next_revid = order.pop()
        else:
            order_as_requested = False
            if ordering != "unordered" and self._fallback_repositories:
                raise ValueError(f"unsupported ordering {ordering!r}")
        iter_inv_fns = [self._iter_inventories_rpc] + [
            fallback._iter_inventories for fallback in self._fallback_repositories
        ]
        try:
            for iter_inv in iter_inv_fns:
                request = [revid for revid in revision_ids if revid in missing]
                for inv, revid in iter_inv(request, ordering):
                    if inv is None:
                        continue
                    missing.remove(inv.revision_id)
                    if ordering != "unordered":
                        invs[revid] = inv
                    else:
                        yield inv, revid
                if order_as_requested:
                    # Yield as many results as we can while preserving order.
                    while next_revid in invs:
                        inv = invs.pop(next_revid)
                        yield inv, inv.revision_id
                        try:
                            next_revid = order.pop()
                        except IndexError:
                            # We still want to fully consume the stream, just
                            # in case it is not actually finished at this point
                            next_revid = None
                            break
        except errors.UnknownSmartMethod:
            for inv, revid in self._iter_inventories_vfs(revision_ids, ordering):
                yield inv, revid
            return
        # Report missing
        if order_as_requested:
            if next_revid is not None:
                yield None, next_revid
            while order:
                revid = order.pop()
                yield invs.get(revid), revid
        else:
            while missing:
                yield None, missing.pop()

    def get_revision(self, revision_id):
        """Get a single revision object by its ID.

        Retrieves the revision metadata including the author, committer,
        timestamp, commit message, and parent relationships.

        Args:
            revision_id: The revision ID to retrieve.

        Returns:
            A Revision object containing the revision metadata.

        Raises:
            NoSuchRevision: If the revision_id is not present in the repository.
        """
        with self.lock_read():
            return self.get_revisions([revision_id])[0]

    def get_transaction(self):
        """Get the current transaction for this repository."""
        self._ensure_real()
        return self._real_repository.get_transaction()

    def clone(self, a_controldir, revision_id=None):
        """Clone this repository to a target control directory.

        Args:
            a_controldir: Target control directory.
            revision_id: Revision to clone up to.
        """
        with self.lock_read():
            dest_repo = self._create_sprouting_repo(
                a_controldir, shared=self.is_shared()
            )
            self.copy_content_into(dest_repo, revision_id)
            return dest_repo

    def make_working_trees(self):
        """See Repository.make_working_trees."""
        path = self.controldir._path_for_remote_call(self._client)
        try:
            response = self._call(b"Repository.make_working_trees", path)
        except errors.UnknownSmartMethod:
            self._ensure_real()
            return self._real_repository.make_working_trees()
        if response[0] not in (b"yes", b"no"):
            raise SmartProtocolError(f"unexpected response code {response}")
        return response[0] == b"yes"

    def refresh_data(self):
        """Re-read any data needed to synchronise with disk.

        This method is intended to be called after another repository instance
        (such as one used by a smart server) has inserted data into the
        repository. On all repositories this will work outside of write groups.
        Some repository formats (pack and newer for breezy native formats)
        support refresh_data inside write groups. If called inside a write
        group on a repository that does not support refreshing in a write group
        IsInWriteGroupError will be raised.
        """
        if self._real_repository is not None:
            self._real_repository.refresh_data()
        # Refresh the parents cache for this object
        self._unstacked_provider.disable_cache()
        self._unstacked_provider.enable_cache()

    def revision_ids_to_search_result(self, result_set):
        """Convert a set of revision ids to a graph SearchResult."""
        result_parents = set()
        for parents in self.get_graph().get_parent_map(result_set).values():
            result_parents.update(parents)
        included_keys = result_set.intersection(result_parents)
        start_keys = result_set.difference(included_keys)
        exclude_keys = result_parents.difference(result_set)
        result = vf_search.SearchResult(
            start_keys, exclude_keys, len(result_set), result_set
        )
        return result

    def search_missing_revision_ids(
        self,
        other,
        find_ghosts=True,
        revision_ids=None,
        if_present_ids=None,
        limit=None,
    ):
        """Return the revision ids that other has that this does not.

        These are returned in topological order.

        revision_id: only return revision ids included by revision_id.
        """
        with self.lock_read():
            inter_repo = _mod_repository.InterRepository.get(other, self)
            return inter_repo.search_missing_revision_ids(
                find_ghosts=find_ghosts,
                revision_ids=revision_ids,
                if_present_ids=if_present_ids,
                limit=limit,
            )

    def fetch(
        self, source, revision_id=None, find_ghosts=False, fetch_spec=None, lossy=False
    ):
        """Fetch revisions from another repository.

        Args:
            source: Source repository to fetch from.
            revision_id: Specific revision to fetch.
            find_ghosts: Whether to find ghost revisions.
            fetch_spec: Specification of what to fetch.
            lossy: Whether lossy fetch is allowed.
        """
        # No base implementation to use as RemoteRepository is not a subclass
        # of Repository; so this is a copy of Repository.fetch().
        if fetch_spec is not None and revision_id is not None:
            raise AssertionError("fetch_spec and revision_id are mutually exclusive.")
        if self.is_in_write_group():
            raise errors.InternalBzrError("May not fetch while in a write group.")
        # fast path same-url fetch operations
        if (
            self.has_same_location(source)
            and fetch_spec is None
            and self._has_same_fallbacks(source)
        ):
            # check that last_revision is in 'from' and then return a
            # no-operation.
            if revision_id is not None and not _mod_revision.is_null(revision_id):
                self.get_revision(revision_id)
            return _mod_repository.FetchResult(0)
        # if there is no specific appropriate InterRepository, this will get
        # the InterRepository base class, which raises an
        # IncompatibleRepositories when asked to fetch.
        inter = _mod_repository.InterRepository.get(source, self)
        if fetch_spec is not None and not getattr(inter, "supports_fetch_spec", False):
            raise errors.UnsupportedOperation(f"fetch_spec not supported for {inter!r}")
        return inter.fetch(
            revision_id=revision_id,
            find_ghosts=find_ghosts,
            fetch_spec=fetch_spec,
            lossy=lossy,
        )

    def create_bundle(self, target, base, fileobj, format=None):
        """Create a bundle for the given target and base.

        Args:
            target: Target revision ID.
            base: Base revision ID.
            fileobj: File object to write bundle to.
            format: Bundle format to use.
        """
        self._ensure_real()
        self._real_repository.create_bundle(target, base, fileobj, format)

    def fileids_altered_by_revision_ids(self, revision_ids):
        """Get file IDs altered by the given revision IDs.

        Args:
            revision_ids: List of revision IDs to check.

        Returns:
            Set of file IDs that were altered.
        """
        self._ensure_real()
        return self._real_repository.fileids_altered_by_revision_ids(revision_ids)

    def _get_versioned_file_checker(self, revisions, revision_versions_cache):
        self._ensure_real()
        return self._real_repository._get_versioned_file_checker(
            revisions, revision_versions_cache
        )

    def _iter_files_bytes_rpc(self, desired_files, absent):
        path = self.controldir._path_for_remote_call(self._client)
        lines = []
        identifiers = []
        for file_id, revid, identifier in desired_files:
            lines.append(b"".join([file_id, b"\0", revid]))
            identifiers.append(identifier)
        (response_tuple, response_handler) = self._call_with_body_bytes_expecting_body(
            b"Repository.iter_files_bytes", (path,), b"\n".join(lines)
        )
        if response_tuple != (b"ok",):
            response_handler.cancel_read_body()
            raise errors.UnexpectedSmartServerResponse(response_tuple)
        byte_stream = response_handler.read_streamed_body()

        def decompress_stream(start, byte_stream, unused):
            decompressor = zlib.decompressobj()
            yield decompressor.decompress(start)
            while decompressor.unused_data == b"":
                try:
                    data = next(byte_stream)
                except StopIteration:
                    break
                yield decompressor.decompress(data)
            yield decompressor.flush()
            unused.append(decompressor.unused_data)

        unused = b""
        while True:
            while b"\n" not in unused:
                try:
                    unused += next(byte_stream)
                except StopIteration:
                    return
            header, rest = unused.split(b"\n", 1)
            args = header.split(b"\0")
            if args[0] == b"absent":
                absent[identifiers[int(args[3])]] = (args[1], args[2])
                unused = rest
                continue
            elif args[0] == b"ok":
                idx = int(args[1])
            else:
                raise errors.UnexpectedSmartServerResponse(args)
            unused_chunks = []
            yield (
                identifiers[idx],
                decompress_stream(rest, byte_stream, unused_chunks),
            )
            unused = b"".join(unused_chunks)

    def iter_files_bytes(self, desired_files):
        """See Repository.iter_file_bytes."""
        try:
            absent = {}
            for identifier, bytes_iterator in self._iter_files_bytes_rpc(
                desired_files, absent
            ):
                yield identifier, bytes_iterator
            for fallback in self._fallback_repositories:
                if not absent:
                    break
                desired_files = [
                    (key[0], key[1], identifier) for identifier, key in absent.items()
                ]
                for identifier, bytes_iterator in fallback.iter_files_bytes(
                    desired_files
                ):
                    del absent[identifier]
                    yield identifier, bytes_iterator
            if absent:
                # There may be more missing items, but raise an exception
                # for just one.
                missing_identifier = next(iter(absent))
                missing_key = absent[missing_identifier]
                raise errors.RevisionNotPresent(
                    revision_id=missing_key[1], file_id=missing_key[0]
                )
        except errors.UnknownSmartMethod:
            self._ensure_real()
            for identifier, bytes_iterator in self._real_repository.iter_files_bytes(
                desired_files
            ):
                yield identifier, bytes_iterator

    def get_cached_parent_map(self, revision_ids):
        """See breezy.CachingParentsProvider.get_cached_parent_map."""
        return self._unstacked_provider.get_cached_parent_map(revision_ids)

    def get_parent_map(self, revision_ids):
        """See breezy.Graph.get_parent_map()."""
        return self._make_parents_provider().get_parent_map(revision_ids)

    def _get_parent_map_rpc(self, keys):
        """Helper for get_parent_map that performs the RPC."""
        medium = self._client._medium
        if medium._is_remote_before((1, 2)):
            # We already found out that the server can't understand
            # Repository.get_parent_map requests, so just fetch the whole
            # graph.
            #
            # Note that this reads the whole graph, when only some keys are
            # wanted.  On this old server there's no way (?) to get them all
            # in one go, and the user probably will have seen a warning about
            # the server being old anyhow.
            rg = self._get_revision_graph(None)
            # There is an API discrepancy between get_parent_map and
            # get_revision_graph. Specifically, a "key:()" pair in
            # get_revision_graph just means a node has no parents. For
            # "get_parent_map" it means the node is a ghost. So fix up the
            # graph to correct this.
            #   https://bugs.launchpad.net/bzr/+bug/214894
            # There is one other "bug" which is that ghosts in
            # get_revision_graph() are not returned at all. But we won't worry
            # about that for now.
            for node_id, parent_ids in rg.items():
                if parent_ids == ():
                    rg[node_id] = (NULL_REVISION,)
            rg[NULL_REVISION] = ()
            return rg

        keys = set(keys)
        if None in keys:
            raise ValueError("get_parent_map(None) is not valid")
        if NULL_REVISION in keys:
            keys.discard(NULL_REVISION)
            found_parents = {NULL_REVISION: ()}
            if not keys:
                return found_parents
        else:
            found_parents = {}
        # TODO(Needs analysis): We could assume that the keys being requested
        # from get_parent_map are in a breadth first search, so typically they
        # will all be depth N from some common parent, and we don't have to
        # have the server iterate from the root parent, but rather from the
        # keys we're searching; and just tell the server the keyspace we
        # already have; but this may be more traffic again.

        # Transform self._parents_map into a search request recipe.
        # TODO: Manage this incrementally to avoid covering the same path
        # repeatedly. (The server will have to on each request, but the less
        # work done the better).
        #
        # Negative caching notes:
        # new server sends missing when a request including the revid
        # 'include-missing:' is present in the request.
        # missing keys are serialised as missing:X, and we then call
        # provider.note_missing(X) for-all X
        parents_map = self._unstacked_provider.get_cached_map()
        if parents_map is None:
            # Repository is not locked, so there's no cache.
            parents_map = {}
        if _DEFAULT_SEARCH_DEPTH <= 0:
            (start_set, stop_keys, key_count) = vf_search.search_result_from_parent_map(
                parents_map, self._unstacked_provider.missing_keys
            )
        else:
            (
                start_set,
                stop_keys,
                key_count,
            ) = vf_search.limited_search_result_from_parent_map(
                parents_map,
                self._unstacked_provider.missing_keys,
                keys,
                depth=_DEFAULT_SEARCH_DEPTH,
            )
        recipe = ("manual", start_set, stop_keys, key_count)
        body = self._serialise_search_recipe(recipe)
        path = self.controldir._path_for_remote_call(self._client)
        for key in keys:
            if not isinstance(key, bytes):
                raise ValueError(f"key {key!r} not a bytes string")
        verb = b"Repository.get_parent_map"
        args = (path, b"include-missing:") + tuple(keys)
        try:
            response = self._call_with_body_bytes_expecting_body(verb, args, body)
        except errors.UnknownSmartMethod:
            # Server does not support this method, so get the whole graph.
            # Worse, we have to force a disconnection, because the server now
            # doesn't realise it has a body on the wire to consume, so the
            # only way to recover is to abandon the connection.
            warning(
                "Server is too old for fast get_parent_map, reconnecting.  "
                "(Upgrade the server to Bazaar 1.2 to avoid this)"
            )
            medium.disconnect()
            # To avoid having to disconnect repeatedly, we keep track of the
            # fact the server doesn't understand remote methods added in 1.2.
            medium._remember_remote_is_before((1, 2))
            # Recurse just once and we should use the fallback code.
            return self._get_parent_map_rpc(keys)
        response_tuple, response_handler = response
        if response_tuple[0] not in [b"ok"]:
            response_handler.cancel_read_body()
            raise errors.UnexpectedSmartServerResponse(response_tuple)
        if response_tuple[0] == b"ok":
            coded = bz2.decompress(response_handler.read_body_bytes())
            if coded == b"":
                # no revisions found
                return {}
            lines = coded.split(b"\n")
            revision_graph = {}
            for line in lines:
                d = tuple(line.split())
                if len(d) > 1:
                    revision_graph[d[0]] = d[1:]
                else:
                    # No parents:
                    if d[0].startswith(b"missing:"):
                        revid = d[0][8:]
                        self._unstacked_provider.note_missing_key(revid)
                    else:
                        # no parents - so give the Graph result
                        # (NULL_REVISION,).
                        revision_graph[d[0]] = (NULL_REVISION,)
            return revision_graph

    def get_signature_text(self, revision_id):
        """Get the signature text for a revision.

        Args:
            revision_id: The revision ID to get signature for.

        Returns:
            bytes: The signature text.
        """
        with self.lock_read():
            path = self.controldir._path_for_remote_call(self._client)
            try:
                response_tuple, response_handler = self._call_expecting_body(
                    b"Repository.get_revision_signature_text", path, revision_id
                )
            except errors.UnknownSmartMethod:
                self._ensure_real()
                return self._real_repository.get_signature_text(revision_id)
            except errors.NoSuchRevision as err:
                for fallback in self._fallback_repositories:
                    try:
                        return fallback.get_signature_text(revision_id)
                    except errors.NoSuchRevision:
                        pass
                raise err
            else:
                if response_tuple[0] != b"ok":
                    raise errors.UnexpectedSmartServerResponse(response_tuple)
                return response_handler.read_body_bytes()

    def _get_inventory_xml(self, revision_id):
        """Get the inventory XML for a revision.

        Args:
            revision_id: The revision ID to get inventory for.

        Returns:
            str: The inventory XML.
        """
        with self.lock_read():
            # This call is used by older working tree formats,
            # which stored a serialized basis inventory.
            self._ensure_real()
            return self._real_repository._get_inventory_xml(revision_id)

    def reconcile(self, other=None, thorough=False):
        """Reconcile this repository.

        Args:
            other: Other repository to reconcile with.
            thorough: Whether to perform thorough reconciliation.

        Returns:
            ReconcileResult: Result of the reconciliation.
        """
        from ..reconcile import ReconcileResult

        with self.lock_write():
            path = self.controldir._path_for_remote_call(self._client)
            try:
                response, handler = self._call_expecting_body(
                    b"Repository.reconcile", path, self._lock_token
                )
            except (errors.UnknownSmartMethod, errors.TokenLockingNotSupported):
                self._ensure_real()
                return self._real_repository.reconcile(other=other, thorough=thorough)
            if response != (b"ok",):
                raise errors.UnexpectedSmartServerResponse(response)
            body = handler.read_body_bytes()
            result = ReconcileResult()
            result.garbage_inventories = None
            result.inconsistent_parents = None
            result.aborted = None
            for line in body.split(b"\n"):
                if not line:
                    continue
                key, val_text = line.split(b":")
                if key == b"garbage_inventories":
                    result.garbage_inventories = int(val_text)
                elif key == b"inconsistent_parents":
                    result.inconsistent_parents = int(val_text)
                else:
                    mutter(f"unknown reconcile key {key!r}")
            return result

    def all_revision_ids(self):
        """Get all revision IDs in this repository.

        Returns:
            Set of all revision IDs in the repository.
        """
        path = self.controldir._path_for_remote_call(self._client)
        try:
            response_tuple, response_handler = self._call_expecting_body(
                b"Repository.all_revision_ids", path
            )
        except errors.UnknownSmartMethod:
            self._ensure_real()
            return self._real_repository.all_revision_ids()
        if response_tuple != (b"ok",):
            raise errors.UnexpectedSmartServerResponse(response_tuple)
        revids = set(response_handler.read_body_bytes().splitlines())
        for fallback in self._fallback_repositories:
            revids.update(set(fallback.all_revision_ids()))
        return list(revids)

    def _filtered_revision_trees(self, revision_ids, file_ids):
        """Return Tree for a revision on this branch with only some files.

        :param revision_ids: a sequence of revision-ids;
          a revision-id may not be None or b'null:'
        :param file_ids: if not None, the result is filtered
          so that only those file-ids, their parents and their
          children are included.
        """
        inventories = self.iter_inventories(revision_ids)
        for inv in inventories:
            # Should we introduce a FilteredRevisionTree class rather
            # than pre-filter the inventory here?
            filtered_inv = inv.filter(file_ids)
            yield InventoryRevisionTree(self, filtered_inv, filtered_inv.revision_id)

    def get_revision_delta(self, revision_id):
        """Get the delta for a revision.

        Args:
            revision_id: The revision ID to get delta for.

        Returns:
            TreeDelta: The delta for the revision.
        """
        with self.lock_read():
            r = self.get_revision(revision_id)
            return list(self.get_revision_deltas([r]))[0]

    def revision_trees(self, revision_ids):
        """Get revision trees for the given revision IDs.

        Args:
            revision_ids: Iterable of revision IDs.

        Yields:
            RevisionTree: Trees for each revision ID.
        """
        with self.lock_read():
            inventories = self.iter_inventories(revision_ids)
            for inv in inventories:
                yield RemoteInventoryTree(self, inv, inv.revision_id)

    def get_revision_reconcile(self, revision_id):
        """Get revision reconcile information.

        Args:
            revision_id: The revision ID to reconcile.
        """
        with self.lock_read():
            self._ensure_real()
            return self._real_repository.get_revision_reconcile(revision_id)

    def check(self, revision_ids=None, callback_refs=None, check_repo=True):
        """Check the repository for consistency.

        Args:
            revision_ids: Specific revision IDs to check.
            callback_refs: Callback references for progress.
            check_repo: Whether to check the repository structure.

        Returns:
            CheckResult: Result of the consistency check.
        """
        with self.lock_read():
            self._ensure_real()
            return self._real_repository.check(
                revision_ids=revision_ids,
                callback_refs=callback_refs,
                check_repo=check_repo,
            )

    def copy_content_into(self, destination, revision_id=None):
        """Copy content from this repository into destination.

        Args:
            destination: Destination repository.
            revision_id: Specific revision to copy up to.
        """
        """Make a complete copy of the content in self into destination.

        This is a destructive operation! Do not use it on existing
        repositories.
        """
        interrepo = _mod_repository.InterRepository.get(self, destination)
        return interrepo.copy_content(revision_id)

    def _copy_repository_tarball(self, to_bzrdir, revision_id=None):
        # get a tarball of the remote repository, and copy from that into the
        # destination
        import tarfile

        # TODO: Maybe a progress bar while streaming the tarball?
        note(gettext("Copying repository content as tarball..."))
        tar_file = self._get_tarball("bz2")
        if tar_file is None:
            return None
        destination = to_bzrdir.create_repository()
        with (
            tarfile.open("repository", fileobj=tar_file, mode="r|bz2") as tar,
            osutils.TemporaryDirectory() as tmpdir,
        ):
            members = tar.getmembers()
            if any(m.name.startswith("/") or ".." in m.name for m in members):
                raise AssertionError("Tarball contains absolute paths")
            tar.extractall(tmpdir, members=members)  # noqa: S202
            tmp_bzrdir = _mod_bzrdir.BzrDir.open(tmpdir)
            tmp_repo = tmp_bzrdir.open_repository()
            tmp_repo.copy_content_into(destination, revision_id)
        return destination
        # TODO: Suggestion from john: using external tar is much faster than
        # python's tarfile library, but it may not work on windows.

    @property
    def inventories(self):
        """Decorate the real repository for now.

        In the long term a full blown network facility is needed to
        avoid creating a real repository object locally.
        """
        self._ensure_real()
        return self._real_repository.inventories

    def pack(self, hint=None, clean_obsolete_packs=False):
        """Compress the data within the repository."""
        if hint is None:
            body = b""
        else:
            body = b"".join([l.encode("ascii") + b"\n" for l in hint])
        with self.lock_write():
            path = self.controldir._path_for_remote_call(self._client)
            try:
                response, handler = self._call_with_body_bytes_expecting_body(
                    b"Repository.pack",
                    (path, self._lock_token, str(clean_obsolete_packs).encode("ascii")),
                    body,
                )
            except errors.UnknownSmartMethod:
                self._ensure_real()
                return self._real_repository.pack(
                    hint=hint, clean_obsolete_packs=clean_obsolete_packs
                )
            handler.cancel_read_body()
            if response != (b"ok",):
                raise errors.UnexpectedSmartServerResponse(response)

    @property
    def revisions(self):
        """Decorate the real repository for now.

        In the long term a full blown network facility is needed.
        """
        self._ensure_real()
        return self._real_repository.revisions

    def set_make_working_trees(self, new_value):
        """Set whether this repository should make working trees.

        Args:
            new_value: True to make working trees, False otherwise.
        """
        new_value_str = b"True" if new_value else b"False"
        path = self.controldir._path_for_remote_call(self._client)
        try:
            response = self._call(
                b"Repository.set_make_working_trees", path, new_value_str
            )
        except errors.UnknownSmartMethod:
            self._ensure_real()
            self._real_repository.set_make_working_trees(new_value)
        else:
            if response[0] != b"ok":
                raise errors.UnexpectedSmartServerResponse(response)

    @property
    def signatures(self):
        """Decorate the real repository for now.

        In the long term a full blown network facility is needed to avoid
        creating a real repository object locally.
        """
        self._ensure_real()
        return self._real_repository.signatures

    def sign_revision(self, revision_id, gpg_strategy):
        """Sign a revision with the given GPG strategy.

        Args:
            revision_id: The revision ID to sign.
            gpg_strategy: GPG strategy to use for signing.
        """
        with self.lock_write():
            testament = _mod_testament.Testament.from_revision(self, revision_id)
            plaintext = testament.as_short_text()
            self.store_revision_signature(gpg_strategy, plaintext, revision_id)

    @property
    def texts(self):
        """Decorate the real repository for now.

        In the long term a full blown network facility is needed to avoid
        creating a real repository object locally.
        """
        self._ensure_real()
        return self._real_repository.texts

    def _iter_revisions_rpc(self, revision_ids):
        body = b"\n".join(revision_ids)
        path = self.controldir._path_for_remote_call(self._client)
        response_tuple, response_handler = self._call_with_body_bytes_expecting_body(
            b"Repository.iter_revisions", (path,), body
        )
        if response_tuple[0] != b"ok":
            raise errors.UnexpectedSmartServerResponse(response_tuple)
        serializer_format = response_tuple[1].decode("ascii")
        serializer = revision_format_registry.get(serializer_format)
        byte_stream = response_handler.read_streamed_body()
        decompressor = zlib.decompressobj()
        chunks = []
        for bytes in byte_stream:
            chunks.append(decompressor.decompress(bytes))
            if decompressor.unused_data != b"":
                chunks.append(decompressor.flush())
                yield serializer.read_revision_from_string(b"".join(chunks))
                unused = decompressor.unused_data
                decompressor = zlib.decompressobj()
                chunks = [decompressor.decompress(unused)]
        chunks.append(decompressor.flush())
        text = b"".join(chunks)
        if text != b"":
            yield serializer.read_revision_from_string(b"".join(chunks))

    def iter_revisions(self, revision_ids):
        """Iterate over revision objects for the given revision IDs.

        Args:
            revision_ids: Iterable of revision IDs.

        Yields:
            Revision: Revision objects for each ID.
        """
        for rev_id in revision_ids:
            if not rev_id or not isinstance(rev_id, bytes):
                raise errors.InvalidRevisionId(revision_id=rev_id, branch=self)
        with self.lock_read():
            try:
                missing = set(revision_ids)
                for rev in self._iter_revisions_rpc(revision_ids):
                    missing.remove(rev.revision_id)
                    yield (rev.revision_id, rev)
                for fallback in self._fallback_repositories:
                    if not missing:
                        break
                    for revid, rev in fallback.iter_revisions(missing):
                        if rev is not None:
                            yield (revid, rev)
                            missing.remove(revid)
                for revid in missing:
                    yield (revid, None)
            except errors.UnknownSmartMethod:
                self._ensure_real()
                yield from self._real_repository.iter_revisions(revision_ids)

    def supports_rich_root(self):
        """Check if this repository supports rich root trees.

        Returns:
            bool: True if rich root is supported.
        """
        return self._format.rich_root_data

    @property
    def _revision_serializer(self):
        return self._format._revision_serializer

    @property
    def _inventory_serializer(self):
        return self._format._inventory_serializer

    def store_revision_signature(self, gpg_strategy, plaintext, revision_id):
        """Store a revision signature.

        Args:
            gpg_strategy: GPG strategy to use.
            plaintext: Plaintext to sign.
            revision_id: Revision ID for the signature.
        """
        with self.lock_write():
            signature = gpg_strategy.sign(plaintext, gpg.MODE_CLEAR)
            self.add_signature_text(revision_id, signature)

    def add_signature_text(self, revision_id, signature):
        """Add signature text for a revision.

        Args:
            revision_id: The revision ID to add signature for.
            signature: The signature text to add.
        """
        if self._real_repository:
            # If there is a real repository the write group will
            # be in the real repository as well, so use that:
            self._ensure_real()
            return self._real_repository.add_signature_text(revision_id, signature)
        path = self.controldir._path_for_remote_call(self._client)
        response, handler = self._call_with_body_bytes_expecting_body(
            b"Repository.add_signature_text",
            (path, self._lock_token, revision_id)
            + tuple([token.encode("utf-8") for token in self._write_group_tokens]),
            signature,
        )
        handler.cancel_read_body()
        self.refresh_data()
        if response[0] != b"ok":
            raise errors.UnexpectedSmartServerResponse(response)
        self._write_group_tokens = [token.decode("utf-8") for token in response[1:]]

    def has_signature_for_revision_id(self, revision_id):
        """Check if a signature exists for the given revision.

        Args:
            revision_id: The revision ID to check.

        Returns:
            bool: True if signature exists.
        """
        path = self.controldir._path_for_remote_call(self._client)
        try:
            response = self._call(
                b"Repository.has_signature_for_revision_id", path, revision_id
            )
        except errors.UnknownSmartMethod:
            self._ensure_real()
            return self._real_repository.has_signature_for_revision_id(revision_id)
        if response[0] not in (b"yes", b"no"):
            raise SmartProtocolError(f"unexpected response code {response}")
        if response[0] == b"yes":
            return True
        for fallback in self._fallback_repositories:
            if fallback.has_signature_for_revision_id(revision_id):
                return True
        return False

    def verify_revision_signature(self, revision_id, gpg_strategy):
        """Verify the signature for a revision.

        Args:
            revision_id: The revision ID to verify.
            gpg_strategy: GPG strategy to use for verification.

        Returns:
            Tuple of (status, key) for signature verification.
        """
        with self.lock_read():
            if not self.has_signature_for_revision_id(revision_id):
                return gpg.SIGNATURE_NOT_SIGNED, None
            signature = self.get_signature_text(revision_id)

            testament = _mod_testament.Testament.from_revision(self, revision_id)

            (status, key, signed_plaintext) = gpg_strategy.verify(signature)
            if testament.as_short_text() != signed_plaintext:
                return gpg.SIGNATURE_NOT_VALID, None
            return (status, key)

    def item_keys_introduced_by(self, revision_ids, _files_pb=None):
        """Get item keys introduced by the given revisions.

        Args:
            revision_ids: Iterable of revision IDs.
            _files_pb: Progress bar for files.

        Returns:
            Dictionary mapping file IDs to keys.
        """
        self._ensure_real()
        return self._real_repository.item_keys_introduced_by(
            revision_ids, _files_pb=_files_pb
        )

    def _find_inconsistent_revision_parents(self, revisions_iterator=None):
        """Find revisions with inconsistent parent information.

        Args:
            revisions_iterator: Iterator over revisions to check.

        Returns:
            List of inconsistent revision IDs.
        """
        self._ensure_real()
        return self._real_repository._find_inconsistent_revision_parents(
            revisions_iterator
        )

    def _check_for_inconsistent_revision_parents(self):
        """Check for inconsistent revision parents in the repository.

        Returns:
            List of inconsistent revision parent issues.
        """
        self._ensure_real()
        return self._real_repository._check_for_inconsistent_revision_parents()

    def _make_parents_provider(self, other=None):
        providers = [self._unstacked_provider]
        if other is not None:
            providers.insert(0, other)
        return graph.StackedParentsProvider(
            _LazyListJoin(providers, self._fallback_repositories)
        )

    def _serialise_search_recipe(self, recipe):
        """Serialise a graph search recipe.

        :param recipe: A search recipe (start, stop, count).
        :return: Serialised bytes.
        """
        start_keys = b" ".join(recipe[1])
        stop_keys = b" ".join(recipe[2])
        count = str(recipe[3]).encode("ascii")
        return b"\n".join((start_keys, stop_keys, count))

    def _serialise_search_result(self, search_result):
        parts = search_result.get_network_struct()
        return b"\n".join(parts)

    def autopack(self):
        """Automatically pack the repository if needed."""
        path = self.controldir._path_for_remote_call(self._client)
        try:
            response = self._call(b"PackRepository.autopack", path)
        except errors.UnknownSmartMethod:
            self._ensure_real()
            self._real_repository._pack_collection.autopack()
            return
        self.refresh_data()
        if response[0] != b"ok":
            raise errors.UnexpectedSmartServerResponse(response)

    def _revision_archive(
        self, revision_id, format, name, root, subdir, force_mtime=None
    ):
        path = self.controldir._path_for_remote_call(self._client)
        format = format or ""
        root = root or ""
        subdir = subdir or ""
        force_mtime = int(force_mtime) if force_mtime is not None else None
        try:
            response, protocol = self._call_expecting_body(
                b"Repository.revision_archive",
                path,
                revision_id,
                format.encode("ascii"),
                os.path.basename(name).encode("utf-8"),
                root.encode("utf-8"),
                subdir.encode("utf-8"),
                force_mtime,
            )
        except errors.UnknownSmartMethod:
            return None
        if response[0] == b"ok":
            return iter([protocol.read_body_bytes()])
        raise errors.UnexpectedSmartServerResponse(response)

    def _annotate_file_revision(self, revid, tree_path, file_id, default_revision):
        path = self.controldir._path_for_remote_call(self._client)
        tree_path = tree_path.encode("utf-8")
        file_id = file_id or b""
        default_revision = default_revision or b""
        try:
            response, handler = self._call_expecting_body(
                b"Repository.annotate_file_revision",
                path,
                revid,
                tree_path,
                file_id,
                default_revision,
            )
        except errors.UnknownSmartMethod:
            return None
        if response[0] != b"ok":
            raise errors.UnexpectedSmartServerResponse(response)
        return map(tuple, bencode.bdecode(handler.read_body_bytes()))


class RemoteStreamSink(vf_repository.StreamSink):
    def _insert_real(self, stream, src_format, resume_tokens):
        self.target_repo._ensure_real()
        sink = self.target_repo._real_repository._get_sink()
        result = sink.insert_stream(stream, src_format, resume_tokens)
        if not result:
            self.target_repo.autopack()
        return result

    def insert_missing_keys(self, source, missing_keys):
        """Insert missing keys from source repository.

        Args:
            source: Source repository to get missing keys from.
            missing_keys: Keys that are missing and need to be inserted.
        """
        if (
            isinstance(source, RemoteStreamSource)
            and source.from_repository._client._medium
            == self.target_repo._client._medium
        ):
            # Streaming from and to the same medium is tricky, since we don't support
            # more than one concurrent request. For now, just force VFS.
            stream = source._get_real_stream_for_missing_keys(missing_keys)
        else:
            stream = source.get_stream_for_missing_keys(missing_keys)
        return self.insert_stream_without_locking(stream, self.target_repo._format)

    def insert_stream(self, stream, src_format, resume_tokens):
        """Insert a stream of repository data into the target repository.

        This method efficiently transfers repository data by streaming it
        to the remote repository, using the most appropriate protocol
        version available.

        Args:
            stream: An iterator of (substream_type, substream) tuples containing
                   the repository data to transfer.
            src_format: The format of the source repository.
            resume_tokens: List of tokens from a previous partial transfer
                          that can be used to resume the operation.

        Returns:
            List of resume tokens if the transfer is incomplete, or empty list
            if the transfer completed successfully.

        Raises:
            UnknownSmartMethod: If the server doesn't support streaming methods.
            UnexpectedSmartServerResponse: If the server returns an unexpected response.
        """
        target = self.target_repo
        target._unstacked_provider.missing_keys.clear()
        candidate_calls = [(b"Repository.insert_stream_1.19", (1, 19))]
        if target._lock_token:
            candidate_calls.append((b"Repository.insert_stream_locked", (1, 14)))
            lock_args = (target._lock_token or b"",)
        else:
            candidate_calls.append((b"Repository.insert_stream", (1, 13)))
            lock_args = ()
        client = target._client
        medium = client._medium
        path = target.controldir._path_for_remote_call(client)
        # Probe for the verb to use with an empty stream before sending the
        # real stream to it.  We do this both to avoid the risk of sending a
        # large request that is then rejected, and because we don't want to
        # implement a way to buffer, rewind, or restart the stream.
        found_verb = False
        for verb, required_version in candidate_calls:
            if medium._is_remote_before(required_version):
                continue
            if resume_tokens:
                # We've already done the probing (and set _is_remote_before) on
                # a previous insert.
                found_verb = True
                break
            byte_stream = smart_repo._stream_to_byte_stream([], src_format)
            try:
                response = client.call_with_body_stream(
                    (verb, path, b"") + lock_args, byte_stream
                )
            except errors.UnknownSmartMethod:
                medium._remember_remote_is_before(required_version)
            else:
                found_verb = True
                break
        if not found_verb:
            # Have to use VFS.
            return self._insert_real(stream, src_format, resume_tokens)
        self._last_inv_record = None
        self._last_substream = None
        if required_version < (1, 19):
            # Remote side doesn't support inventory deltas.  Wrap the stream to
            # make sure we don't send any.  If the stream contains inventory
            # deltas we'll interrupt the smart insert_stream request and
            # fallback to VFS.
            stream = self._stop_stream_if_inventory_delta(stream)
        byte_stream = smart_repo._stream_to_byte_stream(stream, src_format)
        resume_tokens = b" ".join([token.encode("utf-8") for token in resume_tokens])
        response = client.call_with_body_stream(
            (verb, path, resume_tokens) + lock_args, byte_stream
        )
        if response[0][0] not in (b"ok", b"missing-basis"):
            raise errors.UnexpectedSmartServerResponse(response)
        if self._last_substream is not None:
            # The stream included an inventory-delta record, but the remote
            # side isn't new enough to support them.  So we need to send the
            # rest of the stream via VFS.
            self.target_repo.refresh_data()
            return self._resume_stream_with_vfs(response, src_format)
        if response[0][0] == b"missing-basis":
            tokens, missing_keys = bencode.bdecode_as_tuple(response[0][1])
            resume_tokens = [token.decode("utf-8") for token in tokens]
            return resume_tokens, {
                (entry[0].decode("utf-8"),) + entry[1:] for entry in missing_keys
            }
        else:
            self.target_repo.refresh_data()
            return [], set()

    def _resume_stream_with_vfs(self, response, src_format):
        """Resume sending a stream via VFS, first resending the record and
        substream that couldn't be sent via an insert_stream verb.
        """
        if response[0][0] == b"missing-basis":
            tokens, missing_keys = bencode.bdecode_as_tuple(response[0][1])
            tokens = [token.decode("utf-8") for token in tokens]
            # Ignore missing_keys, we haven't finished inserting yet
        else:
            tokens = []

        def resume_substream():
            # Yield the substream that was interrupted.
            yield from self._last_substream
            self._last_substream = None

        def resume_stream():
            # Finish sending the interrupted substream
            yield ("inventory-deltas", resume_substream())
            # Then simply continue sending the rest of the stream.
            yield from self._last_stream

        return self._insert_real(resume_stream(), src_format, tokens)

    def _stop_stream_if_inventory_delta(self, stream):
        """Normally this just lets the original stream pass-through unchanged.

        However if any 'inventory-deltas' substream occurs it will stop
        streaming, and store the interrupted substream and stream in
        self._last_substream and self._last_stream so that the stream can be
        resumed by _resume_stream_with_vfs.
        """
        stream_iter = iter(stream)
        for substream_kind, substream in stream_iter:
            if substream_kind == "inventory-deltas":
                self._last_substream = substream
                self._last_stream = stream_iter
                return
            else:
                yield substream_kind, substream


class RemoteStreamSource(vf_repository.StreamSource):
    """Stream data from a remote server."""

    def get_stream(self, search):
        """Get a stream of revision data matching the search.

        Args:
            search: Search specification for revisions.

        Returns:
            Stream of revision data.
        """
        """Get a stream of repository data based on the search criteria.

        Retrieves repository data (revisions, inventories, texts) that match
        the search criteria, returning it as a stream suitable for transfer
        to another repository.

        Args:
            search: A search object defining which revisions and associated
                   data should be included in the stream.

        Returns:
            An iterator of (substream_type, substream) tuples containing
            the requested repository data.

        Note:
            For repositories with fallback repositories and topological
            fetch order, this delegates to the VFS implementation.
        """
        if (
            self.from_repository._fallback_repositories
            and self.to_format._fetch_order == "topological"
        ):
            return self._real_stream(self.from_repository, search)
        sources = []
        seen = set()
        repos = [self.from_repository]
        while repos:
            repo = repos.pop(0)
            if repo in seen:
                continue
            seen.add(repo)
            repos.extend(repo._fallback_repositories)
            sources.append(repo)
        return self.missing_parents_chain(search, sources)

    def _get_real_stream_for_missing_keys(self, missing_keys):
        self.from_repository._ensure_real()
        real_repo = self.from_repository._real_repository
        real_source = real_repo._get_source(self.to_format)
        return real_source.get_stream_for_missing_keys(missing_keys)

    def get_stream_for_missing_keys(self, missing_keys):
        """Get a stream containing data for the specified missing keys.

        Retrieves repository data for keys that are known to be missing
        from the target repository, optimizing the transfer by only
        sending the required data.

        Args:
            missing_keys: An iterable of (key_type, key_id) tuples representing
                         the specific data items that need to be transferred.

        Returns:
            An iterator of (substream_type, substream) tuples containing
            the data for the missing keys.

        Note:
            Falls back to VFS implementation for non-RemoteRepository sources
            or when the server doesn't support the required protocol version.
        """
        if not isinstance(self.from_repository, RemoteRepository):
            return self._get_real_stream_for_missing_keys(missing_keys)
        client = self.from_repository._client
        medium = client._medium
        if medium._is_remote_before((3, 0)):
            return self._get_real_stream_for_missing_keys(missing_keys)
        path = self.from_repository.controldir._path_for_remote_call(client)
        args = (path, self.to_format.network_name())
        search_bytes = b"\n".join(
            [b"%s\t%s" % (key[0].encode("utf-8"), key[1]) for key in missing_keys]
        )
        try:
            (
                response,
                handler,
            ) = self.from_repository._call_with_body_bytes_expecting_body(
                b"Repository.get_stream_for_missing_keys", args, search_bytes
            )
        except (errors.UnknownSmartMethod, errors.UnknownFormatError):
            return self._get_real_stream_for_missing_keys(missing_keys)
        if response[0] != b"ok":
            raise errors.UnexpectedSmartServerResponse(response)
        byte_stream = handler.read_streamed_body()
        src_format, stream = smart_repo._byte_stream_to_stream(
            byte_stream, self._record_counter
        )
        if src_format.network_name() != self.from_repository._format.network_name():
            raise AssertionError(
                "Mismatched RemoteRepository and stream src {!r}, {!r}".format(
                    src_format.network_name(), repo._format.network_name()
                )
            )
        return stream

    def _real_stream(self, repo, search):
        """Get a stream for search from repo.

        This never called RemoteStreamSource.get_stream, and is a helper
        for RemoteStreamSource._get_stream to allow getting a stream
        reliably whether fallback back because of old servers or trying
        to stream from a non-RemoteRepository (which the stacked support
        code will do).
        """
        source = repo._get_source(self.to_format)
        if isinstance(source, RemoteStreamSource):
            repo._ensure_real()
            source = repo._real_repository._get_source(self.to_format)
        return source.get_stream(search)

    def _get_stream(self, repo, search):
        """Core worker to get a stream from repo for search.

        This is used by both get_stream and the stacking support logic. It
        deliberately gets a stream for repo which does not need to be
        self.from_repository. In the event that repo is not Remote, or
        cannot do a smart stream, a fallback is made to the generic
        repository._get_stream() interface, via self._real_stream.

        In the event of stacking, streams from _get_stream will not
        contain all the data for search - this is normal (see get_stream).

        :param repo: A repository.
        :param search: A search.
        """
        # Fallbacks may be non-smart
        if not isinstance(repo, RemoteRepository):
            return self._real_stream(repo, search)
        client = repo._client
        medium = client._medium
        path = repo.controldir._path_for_remote_call(client)
        search_bytes = repo._serialise_search_result(search)
        args = (path, self.to_format.network_name())
        candidate_verbs = [
            (b"Repository.get_stream_1.19", (1, 19)),
            (b"Repository.get_stream", (1, 13)),
        ]

        found_verb = False
        for verb, version in candidate_verbs:
            if medium._is_remote_before(version):
                continue
            try:
                response = repo._call_with_body_bytes_expecting_body(
                    verb, args, search_bytes
                )
            except errors.UnknownSmartMethod:
                medium._remember_remote_is_before(version)
            except UnknownErrorFromSmartServer as e:
                if isinstance(search, vf_search.EverythingResult):
                    error_verb = e.error_from_smart_server.error_verb
                    if error_verb == b"BadSearch":
                        # Pre-2.4 servers don't support this sort of search.
                        # XXX: perhaps falling back to VFS on BadSearch is a
                        # good idea in general?  It might provide a little bit
                        # of protection against client-side bugs.
                        medium._remember_remote_is_before((2, 4))
                        break
                raise
            else:
                response_tuple, response_handler = response
                found_verb = True
                break
        if not found_verb:
            return self._real_stream(repo, search)
        if response_tuple[0] != b"ok":
            raise errors.UnexpectedSmartServerResponse(response_tuple)
        byte_stream = response_handler.read_streamed_body()
        src_format, stream = smart_repo._byte_stream_to_stream(
            byte_stream, self._record_counter
        )
        if src_format.network_name() != repo._format.network_name():
            raise AssertionError(
                "Mismatched RemoteRepository and stream src {!r}, {!r}".format(
                    src_format.network_name(), repo._format.network_name()
                )
            )
        return stream

    def missing_parents_chain(self, search, sources):
        """Chain multiple streams together to handle stacking.

        :param search: The overall search to satisfy with streams.
        :param sources: A list of Repository objects to query.
        """
        self.from_revision_serialiser = (
            self.from_repository._format._revision_serializer
        )
        self.seen_revs = set()
        self.referenced_revs = set()
        # If there are heads in the search, or the key count is > 0, we are not
        # done.
        while not search.is_empty() and len(sources) > 1:
            source = sources.pop(0)
            stream = self._get_stream(source, search)
            for kind, substream in stream:
                if kind != "revisions":
                    yield kind, substream
                else:
                    yield kind, self.missing_parents_rev_handler(substream)
            search = search.refine(self.seen_revs, self.referenced_revs)
            self.seen_revs = set()
            self.referenced_revs = set()
        if not search.is_empty():
            for kind, stream in self._get_stream(sources[0], search):
                yield kind, stream

    def missing_parents_rev_handler(self, substream):
        """Handle revisions with missing parents in substream.

        Args:
            substream: Substream containing revision data.

        Yields:
            Content with missing parent handling.
        """
        for content in substream:
            revision_bytes = content.get_bytes_as("fulltext")
            revision = self.from_revision_serialiser.read_revision_from_string(
                revision_bytes
            )
            self.seen_revs.add(content.key[-1])
            self.referenced_revs.update(revision.parent_ids)
            yield content


class RemoteBranchLockableFiles(LockableFiles):
    """A 'LockableFiles' implementation that talks to a smart server.

    This is not a public interface class.
    """

    def __init__(self, bzrdir, _client):
        """Initialize RemoteBranchLockableFiles.

        Args:
            bzrdir: The branch directory.
            _client: Smart protocol client.
        """
        self.controldir = bzrdir
        self._client = _client
        self._need_find_modes = True
        LockableFiles.__init__(
            self, bzrdir.get_branch_transport(None), "lock", lockdir.LockDir
        )

    def _find_modes(self):
        # RemoteBranches don't let the client set the mode of control files.
        self._dir_mode = None
        self._file_mode = None


class RemoteBranchFormat(branch.BranchFormat):
    def __init__(self, network_name=None):
        super().__init__()
        self._matchingcontroldir = RemoteBzrDirFormat()
        self._matchingcontroldir.set_branch_format(self)
        self._custom_format = None
        self._network_name = network_name

    def __eq__(self, other):
        """Check equality with another RemoteBranchFormat."""
        return isinstance(other, RemoteBranchFormat) and self.__dict__ == other.__dict__

    def _ensure_real(self):
        if self._custom_format is None:
            try:
                self._custom_format = branch.network_format_registry.get(
                    self._network_name
                )
            except KeyError as e:
                raise errors.UnknownFormatError(
                    kind="branch", format=self._network_name
                ) from e

    def get_format_description(self):
        """Get a description of the repository format.

        Returns:
            str: Description of the repository format.
        """
        self._ensure_real()
        return "Remote: " + self._custom_format.get_format_description()

    def network_name(self):
        """Get the network name for this repository format.

        Returns:
            bytes: The network name.
        """
        return self._network_name

    def open(self, a_controldir, name=None, ignore_fallbacks=False):
        """Open a branch in the given control directory.

        Args:
            a_controldir: Control directory to open branch in.
            name: Name of colocated branch.
            ignore_fallbacks: Whether to ignore fallback branches.

        Returns:
            RemoteBranch: The opened branch.
        """
        return a_controldir.open_branch(name=name, ignore_fallbacks=ignore_fallbacks)

    def _vfs_initialize(
        self, a_controldir, name, append_revisions_only, repository=None
    ):
        # Initialisation when using a local bzrdir object, or a non-vfs init
        # method is not available on the server.
        # self._custom_format is always set - the start of initialize ensures
        # that.
        if isinstance(a_controldir, RemoteBzrDir):
            a_controldir._ensure_real()
            result = self._custom_format.initialize(
                a_controldir._real_bzrdir,
                name=name,
                append_revisions_only=append_revisions_only,
                repository=repository,
            )
        else:
            # We assume the bzrdir is parameterised; it may not be.
            result = self._custom_format.initialize(
                a_controldir,
                name=name,
                append_revisions_only=append_revisions_only,
                repository=repository,
            )
        if isinstance(a_controldir, RemoteBzrDir) and not isinstance(
            result, RemoteBranch
        ):
            result = RemoteBranch(
                a_controldir, a_controldir.find_repository(), result, name=name
            )
        return result

    def initialize(
        self, a_controldir, name=None, repository=None, append_revisions_only=None
    ):
        """Initialize a new branch in the control directory.

        Args:
            a_controldir: Control directory to initialize branch in.
            name: Name for colocated branch.
            repository: Repository to use for the branch.
            append_revisions_only: Whether branch should be append-only.

        Returns:
            RemoteBranch: The newly initialized branch.
        """
        if name is None:
            name = a_controldir._get_selected_branch()
        # 1) get the network name to use.
        if self._custom_format:
            network_name = self._custom_format.network_name()
        else:
            # Select the current breezy default and ask for that.
            reference_bzrdir_format = controldir.format_registry.get("default")()
            reference_format = reference_bzrdir_format.get_branch_format()
            self._custom_format = reference_format
            network_name = reference_format.network_name()
        # Being asked to create on a non RemoteBzrDir:
        if not isinstance(a_controldir, RemoteBzrDir):
            return self._vfs_initialize(
                a_controldir,
                name=name,
                append_revisions_only=append_revisions_only,
                repository=repository,
            )
        medium = a_controldir._client._medium
        if medium._is_remote_before((1, 13)):
            return self._vfs_initialize(
                a_controldir,
                name=name,
                append_revisions_only=append_revisions_only,
                repository=repository,
            )
        # Creating on a remote bzr dir.
        # 2) try direct creation via RPC
        path = a_controldir._path_for_remote_call(a_controldir._client)
        if name != "":
            # XXX JRV20100304: Support creating colocated branches
            raise controldir.NoColocatedBranchSupport(self)
        verb = b"BzrDir.create_branch"
        try:
            response = a_controldir._call(verb, path, network_name)
        except errors.UnknownSmartMethod:
            # Fallback - use vfs methods
            medium._remember_remote_is_before((1, 13))
            return self._vfs_initialize(
                a_controldir,
                name=name,
                append_revisions_only=append_revisions_only,
                repository=repository,
            )
        if response[0] != b"ok":
            raise errors.UnexpectedSmartServerResponse(response)
        # Turn the response into a RemoteRepository object.
        format = RemoteBranchFormat(network_name=response[1])
        repo_format = response_tuple_to_repo_format(response[3:])
        repo_path = response[2].decode("utf-8")
        if repository is not None:
            remote_repo_url = urlutils.join(a_controldir.user_url, repo_path)
            url_diff = urlutils.relative_url(repository.user_url, remote_repo_url)
            if url_diff != ".":
                raise AssertionError(
                    f"repository.user_url {repository.user_url!r} does not match URL from server "
                    f"response ({a_controldir.user_url!r} + {repo_path!r})"
                )
            remote_repo = repository
        else:
            if repo_path == "":
                repo_bzrdir = a_controldir
            else:
                repo_bzrdir = RemoteBzrDir(
                    a_controldir.root_transport.clone(repo_path),
                    a_controldir._format,
                    a_controldir._client,
                )
            remote_repo = RemoteRepository(repo_bzrdir, repo_format)
        remote_branch = RemoteBranch(
            a_controldir, remote_repo, format=format, setup_stacking=False, name=name
        )
        if append_revisions_only:
            remote_branch.set_append_revisions_only(append_revisions_only)
        # XXX: We know this is a new branch, so it must have revno 0, revid
        # NULL_REVISION. Creating the branch locked would make this be unable
        # to be wrong; here its simply very unlikely to be wrong. RBC 20090225
        remote_branch._last_revision_info_cache = 0, NULL_REVISION
        return remote_branch

    def make_tags(self, branch):
        """Create tags for the given branch.

        Args:
            branch: Branch to create tags for.

        Returns:
            Tags object for the branch.
        """
        self._ensure_real()
        return self._custom_format.make_tags(branch)

    def supports_tags(self):
        """Check if this format supports tags.

        Returns:
            bool: True if tags are supported.
        """
        # Remote branches might support tags, but we won't know until we
        # access the real remote branch.
        self._ensure_real()
        return self._custom_format.supports_tags()

    def supports_stacking(self):
        """Check if this format supports stacking.

        Returns:
            bool: True if stacking is supported.
        """
        self._ensure_real()
        return self._custom_format.supports_stacking()

    def supports_set_append_revisions_only(self):
        """Check if this format supports setting append_revisions_only.

        Returns:
            bool: True if append_revisions_only can be set.
        """
        self._ensure_real()
        return self._custom_format.supports_set_append_revisions_only()

    @property
    def supports_reference_locations(self):
        """Check if this format supports reference locations."""
        self._ensure_real()
        return self._custom_format.supports_reference_locations

    def stores_revno(self):
        """Check if this format stores revision numbers.

        Returns:
            bool: True if revision numbers are stored.
        """
        return True

    def _use_default_local_heads_to_fetch(self):
        # If the branch format is a metadir format *and* its heads_to_fetch
        # implementation is not overridden vs the base class, we can use the
        # base class logic rather than use the heads_to_fetch RPC.  This is
        # usually cheaper in terms of net round trips, as the last-revision and
        # tags info fetched is cached and would be fetched anyway.
        self._ensure_real()
        if isinstance(self._custom_format, bzrbranch.BranchFormatMetadir):
            branch_class = self._custom_format._branch_class()
            heads_to_fetch_impl = branch_class.heads_to_fetch
            if heads_to_fetch_impl is branch.Branch.heads_to_fetch:
                return True
        return False


class RemoteBranchStore(_mod_config.IniFileStore):
    """Branch store which attempts to use HPSS calls to retrieve branch store.

    Note that this is specific to bzr-based formats.
    """

    def __init__(self, branch):
        super().__init__()
        self.branch = branch
        self.id = "branch"
        self._real_store = None

    def external_url(self):
        """Get the external URL for this configuration.

        Returns:
            str: The external URL for branch.conf.
        """
        return urlutils.join(self.branch.user_url, "branch.conf")

    def _load_content(self):
        path = self.branch._remote_path()
        try:
            response, handler = self.branch._call_expecting_body(
                b"Branch.get_config_file", path
            )
        except errors.UnknownSmartMethod:
            self._ensure_real()
            return self._real_store._load_content()
        if len(response) and response[0] != b"ok":
            raise errors.UnexpectedSmartServerResponse(response)
        return handler.read_body_bytes()

    def _save_content(self, content):
        path = self.branch._remote_path()
        try:
            response, handler = self.branch._call_with_body_bytes_expecting_body(
                b"Branch.put_config_file",
                (path, self.branch._lock_token, self.branch._repo_lock_token),
                content,
            )
        except errors.UnknownSmartMethod:
            self._ensure_real()
            return self._real_store._save_content(content)
        handler.cancel_read_body()
        if response != (b"ok",):
            raise errors.UnexpectedSmartServerResponse(response)

    def _ensure_real(self):
        self.branch._ensure_real()
        if self._real_store is None:
            self._real_store = _mod_config.BranchStore(self.branch)


class RemoteBranch(branch.Branch, _RpcHelper, lock._RelockDebugMixin):
    """Branch stored on a server accessed by HPSS RPC.

    At the moment most operations are mapped down to simple file operations.
    """

    _real_branch: Optional["bzrbranch.BzrBranch"]
    _format: RemoteBranchFormat
    repository: RemoteRepository

    @property
    def control_transport(self) -> _mod_transport.Transport:
        """Get the control transport for this branch."""
        return self._transport  # type: ignore

    def __init__(
        self,
        remote_bzrdir: RemoteBzrDir,
        remote_repository: RemoteRepository,
        real_branch: Optional["bzrbranch.BzrBranch"] = None,
        _client=None,
        format=None,
        setup_stacking: bool = True,
        name: Optional[str] = None,
        possible_transports: Optional[list[_mod_transport.Transport]] = None,
    ):
        """Create a RemoteBranch instance.

        :param real_branch: An optional local implementation of the branch
            format, usually accessing the data via the VFS.
        :param _client: Private parameter for testing.
        :param format: A RemoteBranchFormat object, None to create one
            automatically. If supplied it should have a network_name already
            supplied.
        :param setup_stacking: If True make an RPC call to determine the
            stacked (or not) status of the branch. If False assume the branch
            is not stacked.
        :param name: Colocated branch name
        """
        # We intentionally don't call the parent class's __init__, because it
        # will try to assign to self.tags, which is a property in this subclass.
        # And the parent's __init__ doesn't do much anyway.
        self.controldir = remote_bzrdir
        self.name = name
        if _client is not None:
            self._client = _client
        else:
            self._client = remote_bzrdir._client
        self.repository = remote_repository
        if real_branch is not None:
            self._real_branch = real_branch
            # Give the remote repository the matching real repo.
            real_repo: _mod_repository.Repository = real_branch.repository
            if isinstance(real_repo, RemoteRepository):
                real_repo._ensure_real()
                real_repo = real_repo._real_repository  # type: ignore
            self.repository._set_real_repository(real_repo)
            # Give the branch the remote repository to let fast-pathing happen.
            real_branch.repository = self.repository
        else:
            self._real_branch = None
        # Fill out expected attributes of branch for breezy API users.
        self._clear_cached_state()
        # TODO: deprecate self.base in favor of user_url
        self.base = self.controldir.user_url
        self._name = name
        self._control_files = None
        self._lock_mode = None
        self._lock_token = None
        self._repo_lock_token = None
        self._lock_count = 0
        self._leave_lock = False
        self.conf_store = None
        # Setup a format: note that we cannot call _ensure_real until all the
        # attributes above are set: This code cannot be moved higher up in this
        # function.
        if format is None:
            self._format = RemoteBranchFormat()
            if self._real_branch is not None:
                self._format._network_name = self._real_branch._format.network_name()
        else:
            self._format = format
        # when we do _ensure_real we may need to pass ignore_fallbacks to the
        # branch.open_branch method.
        self._real_ignore_fallbacks = not setup_stacking
        if not self._format._network_name:
            # Did not get from open_branchV2 - old server.
            self._ensure_real()
            if not self._real_branch:
                raise AssertionError
            self._format._network_name = self._real_branch._format.network_name()
        self.tags = self._format.make_tags(self)
        # The base class init is not called, so we duplicate this:
        hooks = branch.Branch.hooks["open"]
        for hook in hooks:
            hook(self)
        self._is_stacked = False
        if setup_stacking:
            self._setup_stacking(possible_transports)

    def _setup_stacking(self, possible_transports):
        # configure stacking into the remote repository, by reading it from
        # the vfs branch.
        try:
            fallback_url = self.get_stacked_on_url()
        except (
            errors.NotStacked,
            branch.UnstackableBranchFormat,
            errors.UnstackableRepositoryFormat,
        ):
            return
        self._is_stacked = True
        if possible_transports is None:
            possible_transports = []
        else:
            possible_transports = list(possible_transports)
        possible_transports.append(self.controldir.root_transport)
        self._activate_fallback_location(
            fallback_url, possible_transports=possible_transports
        )

    def _get_config(self):
        return RemoteBranchConfig(self)

    def _get_config_store(self):
        if self.conf_store is None:
            self.conf_store = RemoteBranchStore(self)
        return self.conf_store

    def store_uncommitted(self, creator):
        self._ensure_real()
        if self._real_branch is None:
            raise AssertionError
        return self._real_branch.store_uncommitted(creator)

    def get_unshelver(self, tree):
        self._ensure_real()
        if self._real_branch is None:
            raise AssertionError
        return self._real_branch.get_unshelver(tree)

    def _get_real_transport(self) -> _mod_transport.Transport:
        # if we try vfs access, return the real branch's vfs transport
        self._ensure_real()
        if self._real_branch is None:
            raise AssertionError
        return self._real_branch._transport

    _transport = property(_get_real_transport)

    def __str__(self):
        """Return string representation of this branch."""
        return f"{self.__class__.__name__}({self.base})"

    __repr__ = __str__

    def _ensure_real(self):
        """Ensure that there is a _real_branch set.

        Used before calls to self._real_branch.
        """
        if self._real_branch is None:
            if not vfs.vfs_enabled():
                raise AssertionError(
                    "smart server vfs must be enabled to use vfs implementation"
                )
            self.controldir._ensure_real()
            self._real_branch = self.controldir._real_bzrdir.open_branch(
                ignore_fallbacks=self._real_ignore_fallbacks, name=self._name
            )
            # The remote branch and the real branch shares the same store. If
            # we don't, there will always be cases where one of the stores
            # doesn't see an update made on the other.
            self._real_branch.conf_store = self.conf_store
            if self.repository._real_repository is None:
                # Give the remote repository the matching real repo.
                real_repo = self._real_branch.repository
                if isinstance(real_repo, RemoteRepository):
                    real_repo._ensure_real()
                    real_repo = real_repo._real_repository
                self.repository._set_real_repository(real_repo)
            # Give the real branch the remote repository to let fast-pathing
            # happen.
            self._real_branch.repository = self.repository
            if self._lock_mode == "r":
                self._real_branch.lock_read()
            elif self._lock_mode == "w":
                self._real_branch.lock_write(token=self._lock_token)

    def _translate_error(self, err, **context):
        self.repository._translate_error(err, branch=self, **context)

    def _clear_cached_state(self):
        super()._clear_cached_state()
        self._tags_bytes = None
        if self._real_branch is not None:
            self._real_branch._clear_cached_state()

    def _clear_cached_state_of_remote_branch_only(self):
        """Like _clear_cached_state, but doesn't clear the cache of
        self._real_branch.

        This is useful when falling back to calling a method of
        self._real_branch that changes state.  In that case the underlying
        branch changes, so we need to invalidate this RemoteBranch's cache of
        it.  However, there's no need to invalidate the _real_branch's cache
        too, in fact doing so might harm performance.
        """
        super()._clear_cached_state()

    @property
    def control_files(self):
        # Defer actually creating RemoteBranchLockableFiles until its needed,
        # because it triggers an _ensure_real that we otherwise might not need.
        if self._control_files is None:
            self._control_files = RemoteBranchLockableFiles(
                self.controldir, self._client
            )
        return self._control_files

    def get_physical_lock_status(self):
        """See Branch.get_physical_lock_status()."""
        try:
            response = self._client.call(
                b"Branch.get_physical_lock_status", self._remote_path()
            )
        except errors.UnknownSmartMethod:
            self._ensure_real()
            return self._real_branch.get_physical_lock_status()
        if response[0] not in (b"yes", b"no"):
            raise errors.UnexpectedSmartServerResponse(response)
        return response[0] == b"yes"

    def get_stacked_on_url(self):
        """Get the URL this branch is stacked against.

        :raises NotStacked: If the branch is not stacked.
        :raises UnstackableBranchFormat: If the branch does not support
            stacking.
        :raises UnstackableRepositoryFormat: If the repository does not support
            stacking.
        """
        try:
            # there may not be a repository yet, so we can't use
            # self._translate_error, so we can't use self._call either.
            response = self._client.call(
                b"Branch.get_stacked_on_url", self._remote_path()
            )
        except errors.ErrorFromSmartServer as err:
            # there may not be a repository yet, so we can't call through
            # its _translate_error
            _translate_error(err, branch=self)
        except errors.UnknownSmartMethod:
            self._ensure_real()
            return self._real_branch.get_stacked_on_url()
        if response[0] != b"ok":
            raise errors.UnexpectedSmartServerResponse(response)
        return response[1].decode("utf-8")

    def _check_stackable_repo(self) -> None:
        if not self.repository._format.supports_external_lookups:
            raise errors.UnstackableRepositoryFormat(
                self.repository._format, self.repository.user_url
            )

    def _unstack(self):
        """Change a branch to be unstacked, copying data as needed.

        Don't call this directly, use set_stacked_on_url(None).
        """
        with ui.ui_factory.nested_progress_bar():
            # The basic approach here is to fetch the tip of the branch,
            # including all available ghosts, from the existing stacked
            # repository into a new repository object without the fallbacks.
            #
            # XXX: See <https://launchpad.net/bugs/397286> - this may not be
            # correct for CHKMap repostiories
            old_repository = self.repository
            if len(old_repository._fallback_repositories) != 1:
                raise AssertionError(
                    "can't cope with fallback repositories "
                    "of {!r} (fallbacks: {!r})".format(
                        old_repository, old_repository._fallback_repositories
                    )
                )
            # Open the new repository object.
            # Repositories don't offer an interface to remove fallback
            # repositories today; take the conceptually simpler option and just
            # reopen it.  We reopen it starting from the URL so that we
            # get a separate connection for RemoteRepositories and can
            # stream from one of them to the other.  This does mean doing
            # separate SSH connection setup, but unstacking is not a
            # common operation so it's tolerable.
            new_bzrdir = controldir.ControlDir.open(self.controldir.root_transport.base)
            new_repository = new_bzrdir.find_repository()
            if new_repository._fallback_repositories:
                raise AssertionError(
                    f"didn't expect {self.repository!r} to have fallback_repositories"
                )
            # Replace self.repository with the new repository.
            # Do our best to transfer the lock state (i.e. lock-tokens and
            # lock count) of self.repository to the new repository.
            lock_token = old_repository.lock_write().repository_token
            self.repository = new_repository
            # Remote branches can have a second reference to the old
            # repository that need to be replaced.
            if self._real_branch is not None:
                self._real_branch.repository = new_repository
            self.repository.lock_write(token=lock_token)
            if lock_token is not None:
                old_repository.leave_lock_in_place()
            old_repository.unlock()
            if lock_token is not None:
                # XXX: self.repository.leave_lock_in_place() before this
                # function will not be preserved.  Fortunately that doesn't
                # affect the current default format (2a), and would be a
                # corner-case anyway.
                #  - Andrew Bennetts, 2010/06/30
                self.repository.dont_leave_lock_in_place()
            old_lock_count = 0
            while True:
                try:
                    old_repository.unlock()
                except errors.LockNotHeld:
                    break
                old_lock_count += 1
            if old_lock_count == 0:
                raise AssertionError(
                    "old_repository should have been locked at least once."
                )
            for _i in range(old_lock_count - 1):
                self.repository.lock_write()
            # Fetch from the old repository into the new.
            with old_repository.lock_read():
                # XXX: If you unstack a branch while it has a working tree
                # with a pending merge, the pending-merged revisions will no
                # longer be present.  You can (probably) revert and remerge.
                try:
                    tags_to_fetch = set(self.tags.get_reverse_tag_dict())
                except errors.TagsNotSupported:
                    tags_to_fetch = set()
                fetch_spec = vf_search.NotInOtherForRevs(
                    self.repository,
                    old_repository,
                    required_ids=[self.last_revision()],
                    if_present_ids=tags_to_fetch,
                    find_ghosts=True,
                ).execute()
                self.repository.fetch(old_repository, fetch_spec=fetch_spec)

    def set_stacked_on_url(self, url):
        if not self._format.supports_stacking():
            raise UnstackableBranchFormat(self._format, self.user_url)
        with self.lock_write():
            # XXX: Changing from one fallback repository to another does not
            # check that all the data you need is present in the new fallback.
            # Possibly it should.
            self._check_stackable_repo()
            if not url:
                try:
                    self.get_stacked_on_url()
                except (
                    errors.NotStacked,
                    UnstackableBranchFormat,
                    errors.UnstackableRepositoryFormat,
                ):
                    return
                self._unstack()
            else:
                self._activate_fallback_location(
                    url, possible_transports=[self.controldir.root_transport]
                )
            # write this out after the repository is stacked to avoid setting a
            # stacked config that doesn't work.
            self._set_config_location("stacked_on_location", url)
        # We need the stacked_on_url to be visible both locally (to not query
        # it repeatedly) and remotely (so smart verbs can get it server side)
        # Without the following line,
        # breezy.tests.per_branch.test_create_clone.TestCreateClone
        # .test_create_clone_on_transport_stacked_hooks_get_stacked_branch
        # fails for remote branches -- vila 2012-01-04
        self.conf_store.save_changes()
        if not url:
            self._is_stacked = False
        else:
            self._is_stacked = True

    def _vfs_get_tags_bytes(self):
        self._ensure_real()
        return self._real_branch._get_tags_bytes()

    def _get_tags_bytes(self):
        with self.lock_read():
            if self._tags_bytes is None:
                self._tags_bytes = self._get_tags_bytes_via_hpss()
            return self._tags_bytes

    def _get_tags_bytes_via_hpss(self):
        medium = self._client._medium
        if medium._is_remote_before((1, 13)):
            return self._vfs_get_tags_bytes()
        try:
            response = self._call(b"Branch.get_tags_bytes", self._remote_path())
        except errors.UnknownSmartMethod:
            medium._remember_remote_is_before((1, 13))
            return self._vfs_get_tags_bytes()
        return response[0]

    def _vfs_set_tags_bytes(self, bytes):
        self._ensure_real()
        return self._real_branch._set_tags_bytes(bytes)

    def _set_tags_bytes(self, bytes):
        if self.is_locked():
            self._tags_bytes = bytes
        medium = self._client._medium
        if medium._is_remote_before((1, 18)):
            self._vfs_set_tags_bytes(bytes)
            return
        try:
            args = (self._remote_path(), self._lock_token, self._repo_lock_token)
            self._call_with_body_bytes(b"Branch.set_tags_bytes", args, bytes)
        except errors.UnknownSmartMethod:
            medium._remember_remote_is_before((1, 18))
            self._vfs_set_tags_bytes(bytes)

    def lock_read(self):
        """Lock the branch for read operations.

        :return: A breezy.lock.LogicalLockResult.
        """
        self.repository.lock_read()
        if not self._lock_mode:
            self._note_lock("r")
            self._lock_mode = "r"
            self._lock_count = 1
            if self._real_branch is not None:
                self._real_branch.lock_read()
        else:
            self._lock_count += 1
        return lock.LogicalLockResult(self.unlock)

    def _remote_lock_write(self, token):
        if token is None:
            branch_token = repo_token = b""
        else:
            branch_token = token
            repo_token = self.repository.lock_write().repository_token
            self.repository.unlock()
        err_context = {"token": token}
        try:
            response = self._call(
                b"Branch.lock_write",
                self._remote_path(),
                branch_token,
                repo_token or b"",
                **err_context,
            )
        except errors.LockContention as e:
            # The LockContention from the server doesn't have any
            # information about the lock_url. We re-raise LockContention
            # with valid lock_url.
            raise errors.LockContention(
                "(remote lock)", self.repository.base.split(".bzr/")[0]
            ) from e
        if response[0] != b"ok":
            raise errors.UnexpectedSmartServerResponse(response)
        ok, branch_token, repo_token = response
        return branch_token, repo_token

    def lock_write(self, token=None):
        if not self._lock_mode:
            self._note_lock("w")
            # Lock the branch and repo in one remote call.
            remote_tokens = self._remote_lock_write(token)
            self._lock_token, self._repo_lock_token = remote_tokens
            if not self._lock_token:
                raise SmartProtocolError("Remote server did not return a token!")
            # Tell the self.repository object that it is locked.
            self.repository.lock_write(self._repo_lock_token, _skip_rpc=True)

            if self._real_branch is not None:
                self._real_branch.lock_write(token=self._lock_token)
            if token is not None:
                self._leave_lock = True
            else:
                self._leave_lock = False
            self._lock_mode = "w"
            self._lock_count = 1
        elif self._lock_mode == "r":
            raise errors.ReadOnlyError(self)
        else:
            if token is not None:
                # A token was given to lock_write, and we're relocking, so
                # check that the given token actually matches the one we
                # already have.
                if token != self._lock_token:
                    raise errors.TokenMismatch(token, self._lock_token)
            self._lock_count += 1
            # Re-lock the repository too.
            self.repository.lock_write(self._repo_lock_token)
        return BranchWriteLockResult(self.unlock, self._lock_token or None)

    def _unlock(self, branch_token, repo_token):
        err_context = {"token": str((branch_token, repo_token))}
        response = self._call(
            b"Branch.unlock",
            self._remote_path(),
            branch_token,
            repo_token or b"",
            **err_context,
        )
        if response == (b"ok",):
            return
        raise errors.UnexpectedSmartServerResponse(response)

    @only_raises(errors.LockNotHeld, errors.LockBroken)
    def unlock(self):
        try:
            self._lock_count -= 1
            if not self._lock_count:
                if self.conf_store is not None:
                    self.conf_store.save_changes()
                self._clear_cached_state()
                mode = self._lock_mode
                self._lock_mode = None
                if self._real_branch is not None:
                    if not self._leave_lock and mode == "w" and self._repo_lock_token:
                        # If this RemoteBranch will remove the physical lock
                        # for the repository, make sure the _real_branch
                        # doesn't do it first.  (Because the _real_branch's
                        # repository is set to be the RemoteRepository.)
                        self._real_branch.repository.leave_lock_in_place()
                    self._real_branch.unlock()
                if mode != "w":
                    # Only write-locked branched need to make a remote method
                    # call to perform the unlock.
                    return
                if not self._lock_token:
                    raise AssertionError("Locked, but no token!")
                branch_token = self._lock_token
                repo_token = self._repo_lock_token
                self._lock_token = None
                self._repo_lock_token = None
                if not self._leave_lock:
                    self._unlock(branch_token, repo_token)
        finally:
            self.repository.unlock()

    def break_lock(self):
        try:
            response = self._call(b"Branch.break_lock", self._remote_path())
        except errors.UnknownSmartMethod:
            self._ensure_real()
            return self._real_branch.break_lock()
        if response != (b"ok",):
            raise errors.UnexpectedSmartServerResponse(response)

    def leave_lock_in_place(self):
        if not self._lock_token:
            raise NotImplementedError(self.leave_lock_in_place)
        self._leave_lock = True

    def dont_leave_lock_in_place(self):
        if not self._lock_token:
            raise NotImplementedError(self.dont_leave_lock_in_place)
        self._leave_lock = False

    def get_rev_id(self, revno, history=None):
        if revno == 0:
            return _mod_revision.NULL_REVISION
        with self.lock_read():
            last_revision_info = self.last_revision_info()
            if revno < 0:
                raise errors.RevnoOutOfBounds(revno, (0, last_revision_info[0]))
            ok, result = self.repository.get_rev_id_for_revno(revno, last_revision_info)
            if ok:
                return result
            missing_parent = result[1]
            # Either the revision named by the server is missing, or its parent
            # is.  Call get_parent_map to determine which, so that we report a
            # useful error.
            parent_map = self.repository.get_parent_map([missing_parent])
            if missing_parent in parent_map:
                missing_parent = parent_map[missing_parent]
            raise errors.NoSuchRevision(self, missing_parent)

    def _read_last_revision_info(self):
        response = self._call(b"Branch.last_revision_info", self._remote_path())
        if response[0] != b"ok":
            raise SmartProtocolError(f"unexpected response code {response}")
        revno = int(response[1])
        last_revision = response[2]
        return (revno, last_revision)

    def _gen_revision_history(self):
        """See Branch._gen_revision_history()."""
        if self._is_stacked:
            self._ensure_real()
            return self._real_branch._gen_revision_history()
        response_tuple, response_handler = self._call_expecting_body(
            b"Branch.revision_history", self._remote_path()
        )
        if response_tuple[0] != b"ok":
            raise errors.UnexpectedSmartServerResponse(response_tuple)
        result = response_handler.read_body_bytes().split(b"\x00")
        if result == [""]:
            return []
        return result

    def _remote_path(self):
        return self.controldir._path_for_remote_call(self._client)

    def _set_last_revision_descendant(
        self,
        revision_id,
        other_branch,
        allow_diverged=False,
        allow_overwrite_descendant=False,
    ):
        # This performs additional work to meet the hook contract; while its
        # undesirable, we have to synthesise the revno to call the hook, and
        # not calling the hook is worse as it means changes can't be prevented.
        # Having calculated this though, we can't just call into
        # set_last_revision_info as a simple call, because there is a set_rh
        # hook that some folk may still be using.
        old_revno, old_revid = self.last_revision_info()
        history = self._lefthand_history(revision_id)
        self._run_pre_change_branch_tip_hooks(len(history), revision_id)
        err_context = {"other_branch": other_branch}
        response = self._call(
            b"Branch.set_last_revision_ex",
            self._remote_path(),
            self._lock_token,
            self._repo_lock_token,
            revision_id,
            int(allow_diverged),
            int(allow_overwrite_descendant),
            **err_context,
        )
        self._clear_cached_state()
        if len(response) != 3 and response[0] != b"ok":
            raise errors.UnexpectedSmartServerResponse(response)
        new_revno, new_revision_id = response[1:]
        self._last_revision_info_cache = new_revno, new_revision_id
        self._run_post_change_branch_tip_hooks(old_revno, old_revid)
        if self._real_branch is not None:
            cache = new_revno, new_revision_id
            self._real_branch._last_revision_info_cache = cache

    def _set_last_revision(self, revision_id):
        old_revno, old_revid = self.last_revision_info()
        # This performs additional work to meet the hook contract; while its
        # undesirable, we have to synthesise the revno to call the hook, and
        # not calling the hook is worse as it means changes can't be prevented.
        # Having calculated this though, we can't just call into
        # set_last_revision_info as a simple call, because there is a set_rh
        # hook that some folk may still be using.
        history = self._lefthand_history(revision_id)
        self._run_pre_change_branch_tip_hooks(len(history), revision_id)
        self._clear_cached_state()
        response = self._call(
            b"Branch.set_last_revision",
            self._remote_path(),
            self._lock_token,
            self._repo_lock_token,
            revision_id,
        )
        if response != (b"ok",):
            raise errors.UnexpectedSmartServerResponse(response)
        self._run_post_change_branch_tip_hooks(old_revno, old_revid)

    def _get_parent_location(self):
        medium = self._client._medium
        if medium._is_remote_before((1, 13)):
            return self._vfs_get_parent_location()
        try:
            response = self._call(b"Branch.get_parent", self._remote_path())
        except errors.UnknownSmartMethod:
            medium._remember_remote_is_before((1, 13))
            return self._vfs_get_parent_location()
        if len(response) != 1:
            raise errors.UnexpectedSmartServerResponse(response)
        parent_location = response[0]
        if parent_location == b"":
            return None
        return parent_location.decode("utf-8")

    def _vfs_get_parent_location(self):
        self._ensure_real()
        return self._real_branch._get_parent_location()

    def _set_parent_location(self, url):
        medium = self._client._medium
        if medium._is_remote_before((1, 15)):
            return self._vfs_set_parent_location(url)
        try:
            call_url = url or ""
            if isinstance(call_url, str):
                call_url = call_url.encode("utf-8")
            response = self._call(
                b"Branch.set_parent_location",
                self._remote_path(),
                self._lock_token,
                self._repo_lock_token,
                call_url,
            )
        except errors.UnknownSmartMethod:
            medium._remember_remote_is_before((1, 15))
            return self._vfs_set_parent_location(url)
        if response != ():
            raise errors.UnexpectedSmartServerResponse(response)

    def _vfs_set_parent_location(self, url):
        self._ensure_real()
        return self._real_branch._set_parent_location(url)

    def pull(self, source, overwrite=False, stop_revision=None, **kwargs):
        with self.lock_write():
            self._clear_cached_state_of_remote_branch_only()
            self._ensure_real()
            return self._real_branch.pull(
                source,
                overwrite=overwrite,
                stop_revision=stop_revision,
                _override_hook_target=self,
                **kwargs,
            )

    def push(
        self,
        target,
        overwrite=False,
        stop_revision=None,
        lossy=False,
        tag_selector=None,
    ):
        with self.lock_read():
            self._ensure_real()
            return self._real_branch.push(
                target,
                overwrite=overwrite,
                stop_revision=stop_revision,
                lossy=lossy,
                _override_hook_source_branch=self,
                tag_selector=tag_selector,
            )

    def peek_lock_mode(self):
        return self._lock_mode

    def is_locked(self):
        return self._lock_count >= 1

    def revision_id_to_dotted_revno(self, revision_id):
        """Given a revision id, return its dotted revno.

        :return: a tuple like (1,) or (400,1,3).
        """
        with self.lock_read():
            try:
                response = self._call(
                    b"Branch.revision_id_to_revno", self._remote_path(), revision_id
                )
            except errors.UnknownSmartMethod:
                self._ensure_real()
                return self._real_branch.revision_id_to_dotted_revno(revision_id)
            except UnknownErrorFromSmartServer as e:
                # Deal with older versions of bzr/brz that didn't explicitly
                # wrap GhostRevisionsHaveNoRevno.
                if e.error_tuple[1] == b"GhostRevisionsHaveNoRevno":
                    (revid, ghost_revid) = re.findall(b"{([^}]+)}", e.error_tuple[2])
                    raise errors.GhostRevisionsHaveNoRevno(revid, ghost_revid) from e
                raise
            if response[0] == b"ok":
                return tuple([int(x) for x in response[1:]])
            else:
                raise errors.UnexpectedSmartServerResponse(response)

    def revision_id_to_revno(self, revision_id):
        """Given a revision id on the branch mainline, return its revno.

        :return: an integer
        """
        with self.lock_read():
            try:
                response = self._call(
                    b"Branch.revision_id_to_revno", self._remote_path(), revision_id
                )
            except errors.UnknownSmartMethod:
                self._ensure_real()
                return self._real_branch.revision_id_to_revno(revision_id)
            if response[0] == b"ok":
                if len(response) == 2:
                    return int(response[1])
                raise NoSuchRevision(self, revision_id)
            else:
                raise errors.UnexpectedSmartServerResponse(response)

    def set_last_revision_info(self, revno, revision_id):
        with self.lock_write():
            # XXX: These should be returned by the set_last_revision_info verb
            old_revno, old_revid = self.last_revision_info()
            self._run_pre_change_branch_tip_hooks(revno, revision_id)
            if not revision_id or not isinstance(revision_id, bytes):
                raise errors.InvalidRevisionId(revision_id=revision_id, branch=self)
            try:
                response = self._call(
                    b"Branch.set_last_revision_info",
                    self._remote_path(),
                    self._lock_token,
                    self._repo_lock_token,
                    str(revno).encode("ascii"),
                    revision_id,
                )
            except errors.UnknownSmartMethod:
                self._ensure_real()
                self._clear_cached_state_of_remote_branch_only()
                self._real_branch.set_last_revision_info(revno, revision_id)
                self._last_revision_info_cache = revno, revision_id
                return
            if response == (b"ok",):
                self._clear_cached_state()
                self._last_revision_info_cache = revno, revision_id
                self._run_post_change_branch_tip_hooks(old_revno, old_revid)
                # Update the _real_branch's cache too.
                if self._real_branch is not None:
                    cache = self._last_revision_info_cache
                    self._real_branch._last_revision_info_cache = cache
            else:
                raise errors.UnexpectedSmartServerResponse(response)

    def generate_revision_history(self, revision_id, last_rev=None, other_branch=None):
        with self.lock_write():
            medium = self._client._medium
            if not medium._is_remote_before((1, 6)):
                # Use a smart method for 1.6 and above servers
                try:
                    self._set_last_revision_descendant(
                        revision_id,
                        other_branch,
                        allow_diverged=True,
                        allow_overwrite_descendant=True,
                    )
                    return
                except errors.UnknownSmartMethod:
                    medium._remember_remote_is_before((1, 6))
            self._clear_cached_state_of_remote_branch_only()
            graph = self.repository.get_graph()
            (last_revno, last_revid) = self.last_revision_info()
            known_revision_ids = [
                (last_revid, last_revno),
                (_mod_revision.NULL_REVISION, 0),
            ]
            if last_rev is not None and not graph.is_ancestor(last_rev, revision_id):
                # our previous tip is not merged into stop_revision
                raise errors.DivergedBranches(self, other_branch)
            revno = graph.find_distance_to_null(revision_id, known_revision_ids)
            self.set_last_revision_info(revno, revision_id)

    def set_push_location(self, location):
        self._set_config_location("push_location", location)

    def heads_to_fetch(self):
        if self._format._use_default_local_heads_to_fetch():
            # We recognise this format, and its heads-to-fetch implementation
            # is the default one (tip + tags).  In this case it's cheaper to
            # just use the default implementation rather than a special RPC as
            # the tip and tags data is cached.
            return branch.Branch.heads_to_fetch(self)
        medium = self._client._medium
        if medium._is_remote_before((2, 4)):
            return self._vfs_heads_to_fetch()
        try:
            return self._rpc_heads_to_fetch()
        except errors.UnknownSmartMethod:
            medium._remember_remote_is_before((2, 4))
            return self._vfs_heads_to_fetch()

    def _rpc_heads_to_fetch(self):
        response = self._call(b"Branch.heads_to_fetch", self._remote_path())
        if len(response) != 2:
            raise errors.UnexpectedSmartServerResponse(response)
        must_fetch, if_present_fetch = response
        return set(must_fetch), set(if_present_fetch)

    def _vfs_heads_to_fetch(self):
        self._ensure_real()
        return self._real_branch.heads_to_fetch()

    def reconcile(self, thorough=True):
        """Make sure the data stored in this branch is consistent."""
        from .reconcile import BranchReconciler

        with self.lock_write():
            reconciler = BranchReconciler(self, thorough=thorough)
            return reconciler.reconcile()

    def get_reference_info(self, file_id):
        """Get the tree_path and branch_location for a tree reference."""
        if not self._format.supports_reference_locations:
            raise errors.UnsupportedOperation(self.get_reference_info, self)
        return self._get_all_reference_info().get(file_id, (None, None))

    def set_reference_info(self, file_id, branch_location, tree_path=None):
        """Set the branch location to use for a tree reference."""
        if not self._format.supports_reference_locations:
            raise errors.UnsupportedOperation(self.set_reference_info, self)
        self._ensure_real()
        self._real_branch.set_reference_info(file_id, branch_location, tree_path)

    def _set_all_reference_info(self, reference_info):
        if not self._format.supports_reference_locations:
            raise errors.UnsupportedOperation(self.set_reference_info, self)
        self._ensure_real()
        self._real_branch._set_all_reference_info(reference_info)

    def _get_all_reference_info(self):
        if not self._format.supports_reference_locations:
            return {}
        try:
            response, handler = self._call_expecting_body(
                b"Branch.get_all_reference_info", self._remote_path()
            )
        except errors.UnknownSmartMethod:
            self._ensure_real()
            return self._real_branch._get_all_reference_info()
        if len(response) and response[0] != b"ok":
            raise errors.UnexpectedSmartServerResponse(response)
        ret = {}
        for f, u, p in bencode.bdecode(handler.read_body_bytes()):
            ret[f] = (u.decode("utf-8"), p.decode("utf-8") if p else None)
        return ret

    def reference_parent(self, file_id, path, possible_transports=None):
        """Return the parent branch for a tree-reference.

        :param path: The path of the nested tree in the tree
        :return: A branch associated with the nested tree
        """
        branch_location = self.get_reference_info(file_id)[0]
        if branch_location is None:
            try:
                return branch.Branch.open_from_transport(
                    self.controldir.root_transport.clone(path),
                    possible_transports=possible_transports,
                )
            except errors.NotBranchError:
                return None
        return branch.Branch.open(
            urlutils.join(
                urlutils.strip_segment_parameters(self.user_url), branch_location
            ),
            possible_transports=possible_transports,
        )


class RemoteConfig:
    """A Config that reads and writes from smart verbs.

    It is a low-level object that considers config data to be name/value pairs
    that may be associated with a section. Assigning meaning to the these
    values is done at higher levels like breezy.config.TreeConfig.
    """

    def get_option(self, name, section=None, default=None):
        """Return the value associated with a named option.

        :param name: The name of the value
        :param section: The section the option is in (if any)
        :param default: The value to return if the value is not set
        :return: The value or default value
        """
        try:
            configobj = self._get_configobj()
            section_obj = None
            if section is None:
                section_obj = configobj
            else:
                with contextlib.suppress(KeyError):
                    section_obj = configobj[section]
            value = default if section_obj is None else section_obj.get(name, default)
        except errors.UnknownSmartMethod:
            value = self._vfs_get_option(name, section, default)
        for hook in _mod_config.OldConfigHooks["get"]:
            hook(self, name, value)
        return value

    def _response_to_configobj(self, response):
        if len(response[0]) and response[0][0] != b"ok":
            raise errors.UnexpectedSmartServerResponse(response)
        lines = response[1].read_body_bytes().splitlines()
        conf = _mod_config.ConfigObj(lines, encoding="utf-8")
        for hook in _mod_config.OldConfigHooks["load"]:
            hook(self)
        return conf


class RemoteBranchConfig(RemoteConfig):
    """A RemoteConfig for Branches."""

    def __init__(self, branch):
        self._branch = branch

    def _get_configobj(self):
        path = self._branch._remote_path()
        response = self._branch._client.call_expecting_body(
            b"Branch.get_config_file", path
        )
        return self._response_to_configobj(response)

    def set_option(self, value, name, section=None):
        """Set the value associated with a named option.

        :param value: The value to set
        :param name: The name of the value to set
        :param section: The section the option is in (if any)
        """
        medium = self._branch._client._medium
        if medium._is_remote_before((1, 14)):
            return self._vfs_set_option(value, name, section)
        if isinstance(value, dict):
            if medium._is_remote_before((2, 2)):
                return self._vfs_set_option(value, name, section)
            return self._set_config_option_dict(value, name, section)
        else:
            return self._set_config_option(value, name, section)

    def _set_config_option(self, value, name, section):
        if isinstance(value, (bool, int)):
            value = str(value)
        elif isinstance(value, str):
            pass
        else:
            raise TypeError(value)
        try:
            path = self._branch._remote_path()
            response = self._branch._client.call(
                b"Branch.set_config_option",
                path,
                self._branch._lock_token,
                self._branch._repo_lock_token,
                value.encode("utf-8"),
                name.encode("utf-8"),
                (section or "").encode("utf-8"),
            )
        except errors.UnknownSmartMethod:
            medium = self._branch._client._medium
            medium._remember_remote_is_before((1, 14))
            return self._vfs_set_option(value, name, section)
        if response != ():
            raise errors.UnexpectedSmartServerResponse(response)

    def _serialize_option_dict(self, option_dict):
        utf8_dict = {}
        for key, value in option_dict.items():
            if isinstance(key, str):
                key = key.encode("utf8")
            if isinstance(value, str):
                value = value.encode("utf8")
            utf8_dict[key] = value
        return bencode.bencode(utf8_dict)

    def _set_config_option_dict(self, value, name, section):
        try:
            path = self._branch._remote_path()
            serialised_dict = self._serialize_option_dict(value)
            response = self._branch._client.call(
                b"Branch.set_config_option_dict",
                path,
                self._branch._lock_token,
                self._branch._repo_lock_token,
                serialised_dict,
                name.encode("utf-8"),
                (section or "").encode("utf-8"),
            )
        except errors.UnknownSmartMethod:
            medium = self._branch._client._medium
            medium._remember_remote_is_before((2, 2))
            return self._vfs_set_option(value, name, section)
        if response != ():
            raise errors.UnexpectedSmartServerResponse(response)

    def _real_object(self):
        self._branch._ensure_real()
        return self._branch._real_branch

    def _vfs_set_option(self, value, name, section=None):
        return self._real_object()._get_config().set_option(value, name, section)


class RemoteBzrDirConfig(RemoteConfig):
    """A RemoteConfig for BzrDirs."""

    def __init__(self, bzrdir):
        self._bzrdir = bzrdir

    def _get_configobj(self):
        medium = self._bzrdir._client._medium
        verb = b"BzrDir.get_config_file"
        if medium._is_remote_before((1, 15)):
            raise errors.UnknownSmartMethod(verb)
        path = self._bzrdir._path_for_remote_call(self._bzrdir._client)
        response = self._bzrdir._call_expecting_body(verb, path)
        return self._response_to_configobj(response)

    def _vfs_get_option(self, name, section, default):
        return self._real_object()._get_config().get_option(name, section, default)

    def set_option(self, value, name, section=None):
        """Set the value associated with a named option.

        :param value: The value to set
        :param name: The name of the value to set
        :param section: The section the option is in (if any)
        """
        return self._real_object()._get_config().set_option(value, name, section)

    def _real_object(self):
        self._bzrdir._ensure_real()
        return self._bzrdir._real_bzrdir


error_translators = registry.Registry[bytes, Callable, None]()
no_context_error_translators = registry.Registry[bytes, Callable, None]()


def _translate_error(err, **context):
    """Translate an ErrorFromSmartServer into a more useful error.

    Possible context keys:
      - branch
      - repository
      - bzrdir
      - token
      - other_branch
      - path

    If the error from the server doesn't match a known pattern, then
    UnknownErrorFromSmartServer is raised.
    """

    def find(name):
        try:
            return context[name]
        except KeyError:
            mutter("Missing key '%s' in context %r", name, context)
            raise err from None

    def get_path():
        """Get the path from the context if present, otherwise use first error
        arg.
        """
        try:
            return context["path"]
        except KeyError:
            try:
                return err.error_args[0].decode("utf-8")
            except IndexError:
                mutter("Missing key 'path' in context %r", context)
                raise err from None

    if not isinstance(err.error_verb, bytes):
        raise TypeError(err.error_verb)
    try:
        translator = error_translators.get(err.error_verb)
    except KeyError:
        pass
    else:
        raise translator(err, find, get_path)
    try:
        translator = no_context_error_translators.get(err.error_verb)
    except KeyError:
        raise UnknownErrorFromSmartServer(err) from err
    else:
        raise translator(err)


error_translators.register(
    b"NoSuchRevision",
    lambda err, find, get_path: NoSuchRevision(find("branch"), err.error_args[0]),
)
error_translators.register(
    b"nosuchrevision",
    lambda err, find, get_path: NoSuchRevision(find("repository"), err.error_args[0]),
)
error_translators.register(
    b"revno-outofbounds",
    lambda err, find, get_path: errors.RevnoOutOfBounds(
        err.error_args[0], (err.error_args[1], err.error_args[2])
    ),
)


def _translate_nobranch_error(err, find, get_path):
    """Translate a 'nobranch' error from the smart server.

    Args:
        err: The ErrorFromSmartServer to translate.
        find: Function to find context objects.
        get_path: Function to get the path.

    Returns:
        A NotBranchError with appropriate path and detail.
    """
    extra = err.error_args[0].decode("utf-8") if len(err.error_args) >= 1 else None
    return errors.NotBranchError(path=find("bzrdir").root_transport.base, detail=extra)


error_translators.register(b"nobranch", _translate_nobranch_error)
error_translators.register(
    b"norepository",
    lambda err, find, get_path: errors.NoRepositoryPresent(find("bzrdir")),
)
error_translators.register(
    b"UnlockableTransport",
    lambda err, find, get_path: errors.UnlockableTransport(
        find("bzrdir").root_transport
    ),
)
error_translators.register(
    b"TokenMismatch",
    lambda err, find, get_path: errors.TokenMismatch(find("token"), "(remote token)"),
)
error_translators.register(
    b"Diverged",
    lambda err, find, get_path: errors.DivergedBranches(
        find("branch"), find("other_branch")
    ),
)
error_translators.register(
    b"NotStacked", lambda err, find, get_path: errors.NotStacked(branch=find("branch"))
)


def _translate_PermissionDenied(err, find, get_path):
    path = get_path()
    extra = err.error_args[1].decode("utf-8") if len(err.error_args) >= 2 else None
    return errors.PermissionDenied(path, extra=extra)


error_translators.register(b"PermissionDenied", _translate_PermissionDenied)
error_translators.register(
    b"ReadError", lambda err, find, get_path: errors.ReadError(get_path())
)
error_translators.register(
    b"NoSuchFile", lambda err, find, get_path: _mod_transport.NoSuchFile(get_path())
)
error_translators.register(
    b"TokenLockingNotSupported",
    lambda err, find, get_path: errors.TokenLockingNotSupported(find("repository")),
)
error_translators.register(
    b"UnsuspendableWriteGroup",
    lambda err, find, get_path: errors.UnsuspendableWriteGroup(
        repository=find("repository")
    ),
)
error_translators.register(
    b"UnresumableWriteGroup",
    lambda err, find, get_path: errors.UnresumableWriteGroup(
        repository=find("repository"),
        write_groups=err.error_args[0],
        reason=err.error_args[1],
    ),
)
error_translators.register(
    b"AlreadyControlDir",
    lambda err, find, get_path: errors.AlreadyControlDirError(get_path()),
)

no_context_error_translators.register(
    b"GhostRevisionsHaveNoRevno",
    lambda err: errors.GhostRevisionsHaveNoRevno(*err.error_args),
)
no_context_error_translators.register(
    b"IncompatibleRepositories",
    lambda err: errors.IncompatibleRepositories(
        err.error_args[0].decode("utf-8"),
        err.error_args[1].decode("utf-8"),
        err.error_args[2].decode("utf-8"),
    ),
)
no_context_error_translators.register(
    b"LockContention", lambda err: errors.LockContention("(remote lock)")
)
no_context_error_translators.register(
    b"LockFailed",
    lambda err: errors.LockFailed(
        err.error_args[0].decode("utf-8"), err.error_args[1].decode("utf-8")
    ),
)
no_context_error_translators.register(
    b"TipChangeRejected",
    lambda err: errors.TipChangeRejected(err.error_args[0].decode("utf8")),
)
no_context_error_translators.register(
    b"UnstackableBranchFormat",
    lambda err: branch.UnstackableBranchFormat(*err.error_args),
)
no_context_error_translators.register(
    b"UnstackableRepositoryFormat",
    lambda err: errors.UnstackableRepositoryFormat(*err.error_args),
)
no_context_error_translators.register(
    b"FileExists",
    lambda err: _mod_transport.FileExists(err.error_args[0].decode("utf-8")),
)
no_context_error_translators.register(
    b"DirectoryNotEmpty",
    lambda err: errors.DirectoryNotEmpty(err.error_args[0].decode("utf-8")),
)
no_context_error_translators.register(
    b"UnknownFormat",
    lambda err: errors.UnknownFormatError(
        err.error_args[0].decode("ascii"), err.error_args[0].decode("ascii")
    ),
)
no_context_error_translators.register(
    b"InvalidURL",
    lambda err: urlutils.InvalidURL(
        err.error_args[0].decode("utf-8"), err.error_args[1].decode("utf-8")
    ),
)


def _translate_short_readv_error(err):
    args = err.error_args
    return errors.ShortReadvError(
        args[0].decode("utf-8"),
        int(args[1].decode("ascii")),
        int(args[2].decode("ascii")),
        int(args[3].decode("ascii")),
    )


no_context_error_translators.register(b"ShortReadvError", _translate_short_readv_error)


def _translate_unicode_error(err):
    encoding = err.error_args[0].decode("ascii")
    val = err.error_args[1].decode("utf-8")
    start = int(err.error_args[2].decode("ascii"))
    end = int(err.error_args[3].decode("ascii"))
    reason = err.error_args[4].decode("utf-8")
    if val.startswith("u:"):
        val = val[2:].decode("utf-8")
    elif val.startswith("s:"):
        val = val[2:].decode("base64")
    if err.error_verb == "UnicodeDecodeError":
        raise UnicodeDecodeError(encoding, val, start, end, reason)
    elif err.error_verb == "UnicodeEncodeError":
        raise UnicodeEncodeError(encoding, val, start, end, reason)


no_context_error_translators.register(b"UnicodeEncodeError", _translate_unicode_error)
no_context_error_translators.register(b"UnicodeDecodeError", _translate_unicode_error)
no_context_error_translators.register(
    b"ReadOnlyError", lambda err: errors.TransportNotPossible("readonly transport")
)
no_context_error_translators.register(
    b"MemoryError",
    lambda err: errors.BzrError(
        "remote server out of memory\n"
        "Retry non-remotely, or contact the server admin for details."
    ),
)
no_context_error_translators.register(
    b"RevisionNotPresent",
    lambda err: errors.RevisionNotPresent(
        err.error_args[0].decode("utf-8"), err.error_args[1].decode("utf-8")
    ),
)

no_context_error_translators.register(
    b"BzrCheckError",
    lambda err: errors.BzrCheckError(msg=err.error_args[0].decode("utf-8")),
)
