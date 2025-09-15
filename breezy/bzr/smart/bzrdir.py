# Copyright (C) 2006-2010 Canonical Ltd
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

"""Server-side bzrdir related request implmentations."""

import fastbencode as bencode

from ... import branch, errors, repository, urlutils
from ...controldir import network_format_registry
from .. import BzrProber
from ..bzrdir import BzrDir, BzrDirFormat
from .request import (
    FailedSmartServerResponse,
    SmartServerRequest,
    SuccessfulSmartServerResponse,
)


class SmartServerRequestOpenBzrDir(SmartServerRequest):
    """Handle requests to check if a BzrDir exists at a given path.

    This smart server request checks whether a BzrDir is present at the specified
    path without opening it fully.
    """

    def do(self, path):
        """Check if a BzrDir exists at the specified path.

        Args:
            path: The path to check for a BzrDir.

        Returns:
            SuccessfulSmartServerResponse with "yes" if a BzrDir exists,
            "no" otherwise.
        """
        try:
            t = self.transport_from_client_path(path)
        except errors.PathNotChild:
            # The client is trying to ask about a path that they have no access
            # to.
            # Ideally we'd return a FailedSmartServerResponse here rather than
            # a "successful" negative, but we want to be compatibile with
            # clients that don't anticipate errors from this method.
            answer = b"no"
        else:
            bzr_prober = BzrProber()
            try:
                bzr_prober.probe_transport(t)
            except (errors.NotBranchError, errors.UnknownFormatError):
                answer = b"no"
            else:
                answer = b"yes"
        return SuccessfulSmartServerResponse((answer,))


class SmartServerRequestOpenBzrDir_2_1(SmartServerRequest):
    """Handle requests to check if a BzrDir exists and has a working tree.

    This is version 2.1 of the OpenBzrDir request that additionally checks
    if the BzrDir has a working tree.
    """

    def do(self, path):
        """Is there a BzrDir present, and if so does it have a working tree?

        New in 2.1.
        """
        try:
            t = self.transport_from_client_path(path)
        except errors.PathNotChild:
            # The client is trying to ask about a path that they have no access
            # to.
            return SuccessfulSmartServerResponse((b"no",))
        try:
            bd = BzrDir.open_from_transport(t)
        except errors.NotBranchError:
            answer = (b"no",)
        else:
            answer = (b"yes",)
            if bd.has_workingtree():
                answer += (b"yes",)
            else:
                answer += (b"no",)
        return SuccessfulSmartServerResponse(answer)


class SmartServerRequestBzrDir(SmartServerRequest):
    """Base class for smart server requests that operate on a BzrDir.

    This class provides common functionality for opening a BzrDir and
    delegating to subclass-specific request handlers.
    """

    def do(self, path, *args):
        """Open a BzrDir at path, and return `self.do_bzrdir_request(*args)`."""
        try:
            self._bzrdir = BzrDir.open_from_transport(
                self.transport_from_client_path(path)
            )
        except errors.NotBranchError:
            return FailedSmartServerResponse((b"nobranch",))
        return self.do_bzrdir_request(*args)

    def _boolean_to_yes_no(self, a_boolean):
        """Convert a boolean value to bytes 'yes' or 'no'.

        Args:
            a_boolean: Boolean value to convert.

        Returns:
            b'yes' if True, b'no' if False.
        """
        if a_boolean:
            return b"yes"
        else:
            return b"no"

    def _format_to_capabilities(self, repo_format):
        """Convert repository format capabilities to yes/no byte strings.

        Args:
            repo_format: Repository format object to extract capabilities from.

        Returns:
            Tuple of (rich_root, tree_ref, external_lookup) as byte strings.
        """
        rich_root = self._boolean_to_yes_no(repo_format.rich_root_data)
        tree_ref = self._boolean_to_yes_no(repo_format.supports_tree_reference)
        external_lookup = self._boolean_to_yes_no(repo_format.supports_external_lookups)
        return rich_root, tree_ref, external_lookup

    def _repo_relpath(self, current_transport, repository):
        """Get the relative path for repository from current_transport."""
        # the relpath of the bzrdir in the found repository gives us the
        # path segments to pop-out.
        relpath = repository.user_transport.relpath(current_transport.base)
        segments = [".."] * len(relpath.split("/")) if len(relpath) else []
        return "/".join(segments)


class SmartServerBzrDirRequestDestroyBranch(SmartServerRequestBzrDir):
    """Handle requests to destroy a branch in a BzrDir.

    New in version 2.5.0.
    """

    def do_bzrdir_request(self, name=None):
        """Destroy the branch with the specified name.

        New in 2.5.0.
        :return: On success, 'ok'.
        """
        try:
            self._bzrdir.destroy_branch(
                name.decode("utf-8") if name is not None else None
            )
        except errors.NotBranchError:
            return FailedSmartServerResponse((b"nobranch",))
        return SuccessfulSmartServerResponse((b"ok",))


class SmartServerBzrDirRequestHasWorkingTree(SmartServerRequestBzrDir):
    """Handle requests to check if a BzrDir has a working tree.

    New in version 2.5.0.
    """

    def do_bzrdir_request(self, name=None):
        """Check whether there is a working tree present.

        New in 2.5.0.

        :return: If there is a working tree present, 'yes'.
            Otherwise 'no'.
        """
        if self._bzrdir.has_workingtree():
            return SuccessfulSmartServerResponse((b"yes",))
        else:
            return SuccessfulSmartServerResponse((b"no",))


class SmartServerBzrDirRequestDestroyRepository(SmartServerRequestBzrDir):
    """Handle requests to destroy a repository in a BzrDir.

    New in version 2.5.0.
    """

    def do_bzrdir_request(self, name=None):
        """Destroy the repository.

        New in 2.5.0.

        :return: On success, 'ok'.
        """
        try:
            self._bzrdir.destroy_repository()
        except errors.NoRepositoryPresent:
            return FailedSmartServerResponse((b"norepository",))
        return SuccessfulSmartServerResponse((b"ok",))


class SmartServerBzrDirRequestCloningMetaDir(SmartServerRequestBzrDir):
    """Handle requests for cloning metadata directory format information.

    New in version 1.13. Returns the format that should be used when
    cloning from this directory.
    """

    def do_bzrdir_request(self, require_stacking):
        """Get the format that should be used when cloning from this dir.

        New in 1.13.

        :return: on success, a 3-tuple of network names for (control,
            repository, branch) directories, where '' signifies "not present".
            If this BzrDir contains a branch reference then this will fail with
            BranchReference; clients should resolve branch references before
            calling this RPC.
        """
        try:
            branch_ref = self._bzrdir.get_branch_reference()
        except errors.NotBranchError:
            branch_ref = None
        if branch_ref is not None:
            # The server shouldn't try to resolve references, and it quite
            # possibly can't reach them anyway.  The client needs to resolve
            # the branch reference to determine the cloning_metadir.
            return FailedSmartServerResponse((b"BranchReference",))
        require_stacking = require_stacking == b"True"
        control_format = self._bzrdir.cloning_metadir(require_stacking=require_stacking)
        control_name = control_format.network_name()
        if not control_format.fixed_components:
            branch_name = (b"branch", control_format.get_branch_format().network_name())
            repository_name = control_format.repository_format.network_name()
        else:
            # Only MetaDir has delegated formats today.
            branch_name = (b"branch", b"")
            repository_name = b""
        return SuccessfulSmartServerResponse(
            (control_name, repository_name, branch_name)
        )


class SmartServerBzrDirRequestCheckoutMetaDir(SmartServerRequestBzrDir):
    """Get the format to use for checkouts.

    New in 2.5.

    :return: on success, a 3-tuple of network names for (control,
        repository, branch) directories, where '' signifies "not present".
        If this BzrDir contains a branch reference then this will fail with
        BranchReference; clients should resolve branch references before
        calling this RPC (they should not try to create a checkout of a
        checkout).
    """

    def do_bzrdir_request(self):
        """Get the format to use for checkouts.

        Returns:
            SuccessfulSmartServerResponse with a 3-tuple of network names for
            (control, repository, branch) directories, where '' signifies "not present".

        Raises:
            FailedSmartServerResponse with 'BranchReference' if this BzrDir contains
            a branch reference.
        """
        try:
            branch_ref = self._bzrdir.get_branch_reference()
        except errors.NotBranchError:
            branch_ref = None
        if branch_ref is not None:
            # The server shouldn't try to resolve references, and it quite
            # possibly can't reach them anyway.  The client needs to resolve
            # the branch reference to determine the cloning_metadir.
            return FailedSmartServerResponse((b"BranchReference",))
        control_format = self._bzrdir.checkout_metadir()
        control_name = control_format.network_name()
        if not control_format.fixed_components:
            branch_name = control_format.get_branch_format().network_name()
            repo_name = control_format.repository_format.network_name()
        else:
            branch_name = b""
            repo_name = b""
        return SuccessfulSmartServerResponse((control_name, repo_name, branch_name))


class SmartServerRequestCreateBranch(SmartServerRequestBzrDir):
    """Handle requests to create a new branch in a BzrDir.

    This is the initial version introduced in version 1.13.
    """

    def do(self, path, network_name):
        """Create a branch in the bzr dir at path.

        This operates precisely like 'bzrdir.create_branch'.

        If a bzrdir is not present, an exception is propogated
        rather than 'no branch' because these are different conditions (and
        this method should only be called after establishing that a bzr dir
        exists anyway).

        This is the initial version of this method introduced to the smart
        server for 1.13.

        :param path: The path to the bzrdir.
        :param network_name: The network name of the branch type to create.
        :return: ('ok', branch_format, repo_path, rich_root, tree_ref,
            external_lookup, repo_format)
        """
        bzrdir = BzrDir.open_from_transport(self.transport_from_client_path(path))
        format = branch.network_format_registry.get(network_name)
        bzrdir.branch_format = format
        result = format.initialize(bzrdir, name="")
        rich_root, tree_ref, external_lookup = self._format_to_capabilities(
            result.repository._format
        )
        branch_format = result._format.network_name()
        repo_format = result.repository._format.network_name()
        repo_path = self._repo_relpath(bzrdir.root_transport, result.repository)
        # branch format, repo relpath, rich_root, tree_ref, external_lookup,
        # repo_network_name
        return SuccessfulSmartServerResponse(
            (
                b"ok",
                branch_format,
                repo_path,
                rich_root,
                tree_ref,
                external_lookup,
                repo_format,
            )
        )


class SmartServerRequestCreateRepository(SmartServerRequestBzrDir):
    """Handle requests to create a new repository in a BzrDir.

    This is the initial version introduced in version 1.13.
    """

    def do(self, path, network_name, shared):
        """Create a repository in the bzr dir at path.

        This operates precisely like 'bzrdir.create_repository'.

        If a bzrdir is not present, an exception is propagated
        rather than 'no branch' because these are different conditions (and
        this method should only be called after establishing that a bzr dir
        exists anyway).

        This is the initial version of this method introduced to the smart
        server for 1.13.

        :param path: The path to the bzrdir.
        :param network_name: The network name of the repository type to create.
        :param shared: The value to pass create_repository for the shared
            parameter.
        :return: (ok, rich_root, tree_ref, external_lookup, network_name)
        """
        bzrdir = BzrDir.open_from_transport(self.transport_from_client_path(path))
        shared = shared == b"True"
        format = repository.network_format_registry.get(network_name)
        bzrdir.repository_format = format
        result = format.initialize(bzrdir, shared=shared)
        rich_root, tree_ref, external_lookup = self._format_to_capabilities(
            result._format
        )
        return SuccessfulSmartServerResponse(
            (b"ok", rich_root, tree_ref, external_lookup, result._format.network_name())
        )


class SmartServerRequestFindRepository(SmartServerRequestBzrDir):
    """Base class for requests to find a repository from a given path.

    This class provides common functionality for finding repositories
    and extracting their format information.
    """

    def _find(self, path):
        """Try to find a repository from path upwards.

        This operates precisely like 'bzrdir.find_repository'.

        :return: (relpath, rich_root, tree_ref, external_lookup, network_name).
            All are strings, relpath is a / prefixed path, the next three are
            either 'yes' or 'no', and the last is a repository format network
            name.
        :raises errors.NoRepositoryPresent: When there is no repository
            present.
        """
        bzrdir = BzrDir.open_from_transport(self.transport_from_client_path(path))
        repository = bzrdir.find_repository()
        path = self._repo_relpath(bzrdir.root_transport, repository)
        rich_root, tree_ref, external_lookup = self._format_to_capabilities(
            repository._format
        )
        network_name = repository._format.network_name()
        return path, rich_root, tree_ref, external_lookup, network_name


class SmartServerRequestFindRepositoryV1(SmartServerRequestFindRepository):
    """Version 1 of the find repository request.

    This is the initial version introduced with the smart server.
    Modern clients will try the V2 method that adds support for the
    supports_external_lookups attribute.
    """

    def do(self, path):
        """Try to find a repository from path upwards.

        This operates precisely like 'bzrdir.find_repository'.

        If a bzrdir is not present, an exception is propagated
        rather than 'no branch' because these are different conditions.

        This is the initial version of this method introduced with the smart
        server. Modern clients will try the V2 method that adds support for the
        supports_external_lookups attribute.

        :return: norepository or ok, relpath.
        """
        try:
            path, rich_root, tree_ref, _external_lookup, _name = self._find(path)
            return SuccessfulSmartServerResponse(
                (b"ok", path.encode("utf-8"), rich_root, tree_ref)
            )
        except errors.NoRepositoryPresent:
            return FailedSmartServerResponse((b"norepository",))


class SmartServerRequestFindRepositoryV2(SmartServerRequestFindRepository):
    """Version 2 of the find repository request.

    This is the second edition introduced in bzr 1.3, which returns
    information about the supports_external_lookups format attribute.
    """

    def do(self, path):
        """Try to find a repository from path upwards.

        This operates precisely like 'bzrdir.find_repository'.

        If a bzrdir is not present, an exception is propagated
        rather than 'no branch' because these are different conditions.

        This is the second edition of this method introduced in bzr 1.3, which
        returns information about the supports_external_lookups format
        attribute too.

        :return: norepository or ok, relpath, rich_root, tree_ref,
            external_lookup.
        """
        try:
            path, rich_root, tree_ref, external_lookup, _name = self._find(path)
            return SuccessfulSmartServerResponse(
                (b"ok", path.encode("utf-8"), rich_root, tree_ref, external_lookup)
            )
        except errors.NoRepositoryPresent:
            return FailedSmartServerResponse((b"norepository",))


class SmartServerRequestFindRepositoryV3(SmartServerRequestFindRepository):
    """Version 3 of the find repository request.

    This is the third edition introduced in bzr 1.13, which returns
    information about the network name of the repository format.
    """

    def do(self, path):
        """Try to find a repository from path upwards.

        This operates precisely like 'bzrdir.find_repository'.

        If a bzrdir is not present, an exception is propogated
        rather than 'no branch' because these are different conditions.

        This is the third edition of this method introduced in bzr 1.13, which
        returns information about the network name of the repository format.

        :return: norepository or ok, relpath, rich_root, tree_ref,
            external_lookup, network_name.
        """
        try:
            path, rich_root, tree_ref, external_lookup, name = self._find(path)
            return SuccessfulSmartServerResponse(
                (
                    b"ok",
                    path.encode("utf-8"),
                    rich_root,
                    tree_ref,
                    external_lookup,
                    name,
                )
            )
        except errors.NoRepositoryPresent:
            return FailedSmartServerResponse((b"norepository",))


class SmartServerBzrDirRequestConfigFile(SmartServerRequestBzrDir):
    """Handle requests to get configuration file contents from a BzrDir.

    Returns the raw configuration file bytes without UTF-8 decoding.
    """

    def do_bzrdir_request(self):
        """Get the configuration bytes for a config file in bzrdir.

        The body is not utf8 decoded - it is the literal bytestream from disk.
        """
        config = self._bzrdir._get_config()
        content = b"" if config is None else config._get_config_file().read()
        return SuccessfulSmartServerResponse((), content)


class SmartServerBzrDirRequestGetBranches(SmartServerRequestBzrDir):
    """Handle requests to get all branches in a control directory.

    Returns a bencoded dictionary with branch information, similar to
    the return value of the open branch request.
    """

    def do_bzrdir_request(self):
        """Get the branches in a control directory.

        The body is a bencoded dictionary, with values similar to the return
        value of the open branch request.
        """
        branch_names = self._bzrdir.branch_names()
        ret = {}
        for name in branch_names:
            if name is None:
                name = b""
            branch_ref = self._bzrdir.get_branch_reference(name=name)
            if branch_ref is not None:
                branch_ref = urlutils.relative_url(self._bzrdir.user_url, branch_ref)
                value = (b"ref", branch_ref.encode("utf-8"))
            else:
                b = self._bzrdir.open_branch(name=name, ignore_fallbacks=True)
                value = (b"branch", b._format.network_name())
            ret[name.encode("utf-8")] = value
        return SuccessfulSmartServerResponse((b"success",), bencode.bencode(ret))


class SmartServerRequestInitializeBzrDir(SmartServerRequest):
    """Handle requests to initialize a new BzrDir at a given path.

    Uses the server's default format for initialization.
    """

    def do(self, path):
        """Initialize a bzrdir at path.

        The default format of the server is used.
        :return: SmartServerResponse(('ok', ))
        """
        target_transport = self.transport_from_client_path(path)
        BzrDirFormat.get_default_format().initialize_on_transport(target_transport)
        return SuccessfulSmartServerResponse((b"ok",))


class SmartServerRequestBzrDirInitializeEx(SmartServerRequestBzrDir):
    """Handle extended BzrDir initialization requests.

    New in version 1.16. Replaces BzrDirFormat.initialize_ex verb from 1.15.
    Provides comprehensive initialization options including stacking,
    repository formats, and working tree creation.
    """

    def parse_NoneTrueFalse(self, arg):
        """Parse a byte string argument to None, True, or False.

        Args:
            arg: Byte string argument to parse. Empty string maps to None,
                b'True' maps to True, b'False' maps to False.

        Returns:
            None, True, or False based on the input.

        Raises:
            AssertionError: If the argument is not a valid value.
        """
        if not arg:
            return None
        if arg == b"False":
            return False
        if arg == b"True":
            return True
        raise AssertionError(f"invalid arg {arg!r}")

    def parse_NoneBytestring(self, arg):
        """Parse a byte string argument, returning None for empty strings.

        Args:
            arg: Byte string argument to parse.

        Returns:
            The argument itself if non-empty, None otherwise.
        """
        return arg or None

    def parse_NoneString(self, arg):
        """Parse a byte string argument to a Unicode string or None.

        Args:
            arg: Byte string argument to parse.

        Returns:
            The argument decoded as UTF-8 if non-empty, None otherwise.
        """
        if not arg:
            return None
        return arg.decode("utf-8")

    def _serialize_NoneTrueFalse(self, arg):
        """Serialize None, True, or False to appropriate byte strings.

        Args:
            arg: Value to serialize (None, True, or False).

        Returns:
            b'False' for False, b'' for None/falsy values, b'True' for True.
        """
        if arg is False:
            return b"False"
        if not arg:
            return b""
        return b"True"

    def do(
        self,
        bzrdir_network_name,
        path,
        use_existing_dir,
        create_prefix,
        force_new_repo,
        stacked_on,
        stack_on_pwd,
        repo_format_name,
        make_working_trees,
        shared_repo,
    ):
        """Initialize a bzrdir at path as per
        BzrDirFormat.initialize_on_transport_ex.

        New in 1.16.  (Replaces BzrDirFormat.initialize_ex verb from 1.15).

        :return: return SuccessfulSmartServerResponse((repo_path, rich_root,
            tree_ref, external_lookup, repo_network_name,
            repo_bzrdir_network_name, bzrdir_format_network_name,
            NoneTrueFalse(stacking), final_stack, final_stack_pwd,
            repo_lock_token))
        """
        target_transport = self.transport_from_client_path(path)
        format = network_format_registry.get(bzrdir_network_name)
        use_existing_dir = self.parse_NoneTrueFalse(use_existing_dir)
        create_prefix = self.parse_NoneTrueFalse(create_prefix)
        force_new_repo = self.parse_NoneTrueFalse(force_new_repo)
        stacked_on = self.parse_NoneString(stacked_on)
        stack_on_pwd = self.parse_NoneString(stack_on_pwd)
        make_working_trees = self.parse_NoneTrueFalse(make_working_trees)
        shared_repo = self.parse_NoneTrueFalse(shared_repo)
        if stack_on_pwd == b".":
            stack_on_pwd = target_transport.base.encode("utf-8")
        repo_format_name = self.parse_NoneBytestring(repo_format_name)
        repo, bzrdir, stacking, repository_policy = format.initialize_on_transport_ex(
            target_transport,
            use_existing_dir=use_existing_dir,
            create_prefix=create_prefix,
            force_new_repo=force_new_repo,
            stacked_on=stacked_on,
            stack_on_pwd=stack_on_pwd,
            repo_format_name=repo_format_name,
            make_working_trees=make_working_trees,
            shared_repo=shared_repo,
        )
        if repo is None:
            repo_path = ""
            repo_name = b""
            rich_root = tree_ref = external_lookup = b""
            repo_bzrdir_name = b""
            final_stack = None
            final_stack_pwd = None
            repo_lock_token = b""
        else:
            repo_path = self._repo_relpath(bzrdir.root_transport, repo)
            if repo_path == "":
                repo_path = "."
            rich_root, tree_ref, external_lookup = self._format_to_capabilities(
                repo._format
            )
            repo_name = repo._format.network_name()
            repo_bzrdir_name = repo.controldir._format.network_name()
            final_stack = repository_policy._stack_on
            final_stack_pwd = repository_policy._stack_on_pwd
            # It is returned locked, but we need to do the lock to get the lock
            # token.
            repo.unlock()
            repo_lock_token = repo.lock_write().repository_token or b""
            if repo_lock_token:
                repo.leave_lock_in_place()
            repo.unlock()
        final_stack = final_stack or ""
        final_stack_pwd = final_stack_pwd or ""

        # We want this to be relative to the bzrdir.
        if final_stack_pwd:
            final_stack_pwd = urlutils.relative_url(
                target_transport.base, final_stack_pwd
            )

        # Can't meaningfully return a root path.
        if final_stack.startswith("/"):
            client_path = self._root_client_path + final_stack[1:]
            final_stack = urlutils.relative_url(self._root_client_path, client_path)
            final_stack_pwd = "."

        return SuccessfulSmartServerResponse(
            (
                repo_path.encode("utf-8"),
                rich_root,
                tree_ref,
                external_lookup,
                repo_name,
                repo_bzrdir_name,
                bzrdir._format.network_name(),
                self._serialize_NoneTrueFalse(stacking),
                final_stack.encode("utf-8"),
                final_stack_pwd.encode("utf-8"),
                repo_lock_token,
            )
        )


class SmartServerRequestOpenBranch(SmartServerRequestBzrDir):
    """Handle requests to open a branch and return reference or format info.

    This is the initial version of the open branch request.
    """

    def do_bzrdir_request(self):
        """Open a branch at path and return the branch reference or branch."""
        try:
            reference_url = self._bzrdir.get_branch_reference()
            if reference_url is None:
                reference_url = ""
            return SuccessfulSmartServerResponse((b"ok", reference_url.encode("utf-8")))
        except errors.NotBranchError:
            return FailedSmartServerResponse((b"nobranch",))


class SmartServerRequestOpenBranchV2(SmartServerRequestBzrDir):
    """Version 2 of the open branch request.

    Returns either branch format information or branch reference URL.
    """

    def do_bzrdir_request(self):
        """Open a branch at path and return the reference or format."""
        try:
            reference_url = self._bzrdir.get_branch_reference()
            if reference_url is None:
                br = self._bzrdir.open_branch(ignore_fallbacks=True)
                format = br._format.network_name()
                return SuccessfulSmartServerResponse((b"branch", format))
            else:
                return SuccessfulSmartServerResponse(
                    (b"ref", reference_url.encode("utf-8"))
                )
        except errors.NotBranchError:
            return FailedSmartServerResponse((b"nobranch",))


class SmartServerRequestOpenBranchV3(SmartServerRequestBzrDir):
    """Version 3 of the open branch request.

    Introduced in version 2.1. Enhanced error reporting compared to V2,
    can return additional explanation information with 'nobranch' responses.
    """

    def do_bzrdir_request(self):
        """Open a branch at path and return the reference or format.

        This version introduced in 2.1.

        Differences to SmartServerRequestOpenBranchV2:
          * can return 2-element ('nobranch', extra), where 'extra' is a string
            with an explanation like 'location is a repository'.  Previously
            a 'nobranch' response would never have more than one element.
        """
        try:
            reference_url = self._bzrdir.get_branch_reference()
            if reference_url is None:
                br = self._bzrdir.open_branch(ignore_fallbacks=True)
                format = br._format.network_name()
                return SuccessfulSmartServerResponse((b"branch", format))
            else:
                return SuccessfulSmartServerResponse(
                    (b"ref", reference_url.encode("utf-8"))
                )
        except errors.NotBranchError as e:
            # Stringify the exception so that its .detail attribute will be
            # filled out.
            str(e)
            resp = (b"nobranch",)
            detail = e.detail
            if detail:
                if detail.startswith(": "):
                    detail = detail[2:]
                resp += (detail.encode("utf-8"),)
            return FailedSmartServerResponse(resp)
