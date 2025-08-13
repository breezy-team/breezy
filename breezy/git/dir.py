# Copyright (C) 2007 Canonical Ltd
# Copyright (C) 2010-2018 Jelmer Vernooij
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

"""An adapter between a Git control dir and a Bazaar ControlDir."""

import contextlib
import os

from dulwich.refs import SymrefLoop

from .. import branch as _mod_branch
from .. import errors as brz_errors
from .. import osutils, trace, urlutils
from ..controldir import (
    BranchReferenceLoop,
    ControlDir,
    ControlDirFormat,
    RepositoryAcquisitionPolicy,
    format_registry,
)
from ..transport import (
    FileExists,
    NoSuchFile,
    do_catching_redirections,
    get_transport_from_path,
)
from .mapping import decode_git_path, encode_git_path
from .push import GitPushResult
from .transportgit import OBJECTDIR, TransportObjectStore


class GitDirConfig:
    """Configuration adapter for Git control directories.

    Provides a simple configuration interface that doesn't support
    stack-on settings for Git repositories.
    """

    def get_default_stack_on(self):
        """Get the default stack-on location.

        Returns:
            None: Git repositories don't support stacking.
        """
        return None

    def set_default_stack_on(self, value):
        """Set the default stack-on location.

        Args:
            value: The stack-on location to set.

        Raises:
            BzrError: Always raised as Git repositories don't support stacking.
        """
        raise brz_errors.BzrError("Cannot set configuration")


class GitControlDirFormat(ControlDirFormat):
    """Base format class for Git control directories.

    This format supports colocated branches and has fixed components.
    """

    colocated_branches = True
    fixed_components = True

    def __eq__(self, other):
        """Check equality with another format.

        Args:
            other: The other format to compare with.

        Returns:
            bool: True if formats are of the same type.
        """
        return type(self) is type(other)

    def is_supported(self):
        """Check if this format is supported.

        Returns:
            bool: Always True for Git formats.
        """
        return True

    def network_name(self):
        """Get the network name for this format.

        Returns:
            bytes: The network identifier 'git'.
        """
        return b"git"


class UseExistingRepository(RepositoryAcquisitionPolicy):
    """A policy of reusing an existing repository."""

    def __init__(
        self, repository, stack_on=None, stack_on_pwd=None, require_stacking=False
    ):
        """Constructor.

        :param repository: The repository to use.
        :param stack_on: A location to stack on
        :param stack_on_pwd: If stack_on is relative, the location it is
            relative to.
        """
        super().__init__(stack_on, stack_on_pwd, require_stacking)
        self._repository = repository

    def acquire_repository(
        self, make_working_trees=None, shared=False, possible_transports=None
    ):
        """Implementation of RepositoryAcquisitionPolicy.acquire_repository.

        Returns an existing repository to use.
        """
        return self._repository, False


class GitDir(ControlDir):
    """An adapter to the '.git' dir used by git."""

    @property
    def control_transport(self):
        return self.transport

    def is_supported(self):
        """Check if this control directory is supported.

        Returns:
            bool: Always True for Git directories.
        """
        return True

    def can_convert_format(self):
        """Check if this directory can be converted to another format.

        Returns:
            bool: Always False for Git directories.
        """
        return False

    def break_lock(self):
        """Break any locks on this control directory.

        Raises:
            NotImplementedError: Git has no global locks to break.
        """
        # There are no global locks, so nothing to break.
        raise NotImplementedError(self.break_lock)

    def cloning_metadir(self, stacked=False):
        """Get the control directory format for cloning.

        Args:
            stacked: Whether to create a stacked branch (ignored for Git).

        Returns:
            ControlDir: A Git control directory format.
        """
        return format_registry.make_controldir("git")

    def checkout_metadir(self, stacked=False):
        """Get the control directory format for checkout.

        Args:
            stacked: Whether to create a stacked branch (ignored for Git).

        Returns:
            ControlDir: A Git control directory format.
        """
        return format_registry.make_controldir("git")

    def _get_selected_ref(self, branch, ref=None):
        """Get the Git ref for the specified branch.

        Args:
            branch: The branch name to get the ref for.
            ref: Explicit ref to use (overrides branch).

        Returns:
            bytes: The Git ref name.

        Raises:
            BzrError: If both branch and ref are specified.
        """
        if ref is not None and branch is not None:
            raise brz_errors.BzrError("can't specify both ref and branch")
        if ref is not None:
            return ref
        if branch is not None:
            from .refs import branch_name_to_ref

            return branch_name_to_ref(branch)
        segment_parameters = getattr(
            self.user_transport, "get_segment_parameters", lambda: {}
        )()
        ref = segment_parameters.get("ref")
        if ref is not None:
            return urlutils.unquote_to_bytes(ref)
        if branch is None and getattr(self, "_get_selected_branch", False):
            branch = self._get_selected_branch()
            if branch is not None:
                from .refs import branch_name_to_ref

                return branch_name_to_ref(branch)
        return b"HEAD"

    def get_config(self):
        """Get the configuration for this control directory.

        Returns:
            GitDirConfig: The configuration object.
        """
        return GitDirConfig()

    def _available_backup_name(self, base):
        """Find an available backup name for the given base name.

        Args:
            base: The base name to find a backup name for.

        Returns:
            str: An available backup name.
        """
        return osutils.available_backup_name(base, self.root_transport.has)

    def retire_controldir(self, limit=10000):
        """Permanently disable the controldir.

        This is done by renaming it to give the user some ability to recover
        if there was a problem.

        This will have horrible consequences if anyone has anything locked or
        in use.
        :param limit: number of times to retry
        """
        i = 0
        while True:
            try:
                to_path = ".git.retired.%d" % i
                self.root_transport.rename(".git", to_path)
                trace.note(
                    "renamed {} to {}".format(
                        self.root_transport.abspath(".git"), to_path
                    )
                )
                return
            except (brz_errors.TransportError, OSError, brz_errors.PathError):
                i += 1
                if i > limit:
                    raise
                else:
                    pass

    def sprout(
        self,
        url,
        revision_id=None,
        force_new_repo=False,
        recurse="down",
        possible_transports=None,
        accelerator_tree=None,
        hardlink=False,
        stacked=False,
        source_branch=None,
        create_tree_if_local=True,
    ):
        from ..repository import InterRepository
        from ..transport import get_transport
        from ..transport.local import LocalTransport

        target_transport = get_transport(url, possible_transports)
        target_transport.ensure_base()
        cloning_format = self.cloning_metadir()
        # Create/update the result branch
        try:
            result = ControlDir.open_from_transport(target_transport)
        except brz_errors.NotBranchError:
            result = cloning_format.initialize_on_transport(target_transport)
        if source_branch is None:
            source_branch = self.open_branch()
        source_repository = self.find_repository()
        try:
            result_repo = result.find_repository()
        except brz_errors.NoRepositoryPresent:
            result_repo = result.create_repository()
        if stacked:
            raise _mod_branch.UnstackableBranchFormat(self._format, self.user_url)
        interrepo = InterRepository.get(source_repository, result_repo)

        if revision_id is not None:
            determine_wants = interrepo.get_determine_wants_revids(
                [revision_id], include_tags=True
            )
        else:
            determine_wants = interrepo.determine_wants_all
        interrepo.fetch_objects(
            determine_wants=determine_wants, mapping=source_branch.mapping
        )
        result_branch = source_branch.sprout(
            result, revision_id=revision_id, repository=result_repo
        )
        if (
            create_tree_if_local
            and result.open_branch(name="").name == result_branch.name
            and isinstance(target_transport, LocalTransport)
            and (result_repo is None or result_repo.make_working_trees())
        ):
            wt = result.create_workingtree(
                accelerator_tree=accelerator_tree,
                hardlink=hardlink,
                from_branch=result_branch,
            )
        else:
            wt = None
        if recurse == "down":
            with contextlib.ExitStack() as stack:
                basis = None
                if wt is not None:
                    basis = wt.basis_tree()
                elif result_branch is not None:
                    basis = result_branch.basis_tree()
                elif source_branch is not None:
                    basis = source_branch.basis_tree()
                if basis is not None:
                    stack.enter_context(basis.lock_read())
                    subtrees = basis.iter_references()
                else:
                    subtrees = []
                for path in subtrees:
                    target = urlutils.join(url, urlutils.escape(path))
                    sublocation = wt.get_reference_info(path)
                    if sublocation is None:
                        trace.warning("Unable to find submodule info for %s", path)
                        continue
                    remote_url = urlutils.join(self.user_url, sublocation)
                    try:
                        subbranch = _mod_branch.Branch.open(
                            remote_url, possible_transports=possible_transports
                        )
                    except brz_errors.NotBranchError as e:
                        trace.warning(
                            "Unable to clone submodule %s from %s: %s",
                            path,
                            remote_url,
                            e,
                        )
                        continue
                    subbranch.controldir.sprout(
                        target,
                        basis.get_reference_revision(path),
                        force_new_repo=force_new_repo,
                        recurse=recurse,
                        stacked=stacked,
                    )
        if getattr(result_repo, "_git", None):
            # Don't leak resources:
            # TODO(jelmer): This shouldn't be git-specific, and possibly
            # just use read locks.
            result_repo._git.object_store.close()
        return result

    def clone_on_transport(
        self,
        transport,
        revision_id=None,
        force_new_repo=False,
        preserve_stacking=False,
        stacked_on=None,
        create_prefix=False,
        use_existing_dir=True,
        no_tree=False,
        tag_selector=None,
    ):
        """See ControlDir.clone_on_transport."""
        from ..repository import InterRepository
        from ..transport.local import LocalTransport
        from .mapping import default_mapping
        from .refs import is_peeled

        if no_tree:
            format = BareLocalGitControlDirFormat()
        else:
            format = LocalGitControlDirFormat()
        if stacked_on is not None:
            raise _mod_branch.UnstackableBranchFormat(format, self.user_url)
        (
            target_repo,
            target_controldir,
            stacking,
            repo_policy,
        ) = format.initialize_on_transport_ex(
            transport,
            use_existing_dir=use_existing_dir,
            create_prefix=create_prefix,
            force_new_repo=force_new_repo,
        )
        target_repo = target_controldir.find_repository()
        target_git_repo = target_repo._git
        source_repo = self.find_repository()
        interrepo = InterRepository.get(source_repo, target_repo)
        if revision_id is not None:
            determine_wants = interrepo.get_determine_wants_revids(
                [revision_id], include_tags=True, tag_selector=tag_selector
            )
        else:
            determine_wants = interrepo.determine_wants_all
        (pack_hint, _, refs) = interrepo.fetch_objects(
            determine_wants, mapping=default_mapping
        )
        for name, val in refs.items():
            if is_peeled(name):
                continue
            if val in target_git_repo.object_store:
                target_git_repo.refs[name] = val
        result_dir = LocalGitDir(transport, target_git_repo, format)
        result_branch = result_dir.open_branch()
        try:
            parent = self.open_branch().get_parent()
        except brz_errors.InaccessibleParent:
            pass
        else:
            if parent:
                result_branch.set_parent(parent)
        if revision_id is not None:
            result_branch.set_last_revision(revision_id)
        if not no_tree and isinstance(result_dir.root_transport, LocalTransport):
            if result_dir.open_repository().make_working_trees():
                try:
                    local_wt = self.open_workingtree()
                except brz_errors.NoWorkingTree:
                    pass
                except brz_errors.NotLocalUrl:
                    result_dir.create_workingtree(revision_id=revision_id)
                else:
                    local_wt.clone(result_dir, revision_id=revision_id)

        return result_dir

    def find_repository(self):
        """Find the repository that should be used.

        This does not require a branch as we use it to find the repo for
        new branches as well as to hook existing branches up to their
        repository.
        """
        return self._gitrepository_class(self._find_commondir())

    def get_refs_container(self):
        """Retrieve the refs container."""
        raise NotImplementedError(self.get_refs_container)

    def determine_repository_policy(
        self,
        force_new_repo=False,
        stack_on=None,
        stack_on_pwd=None,
        require_stacking=False,
    ):
        """Return an object representing a policy to use.

        This controls whether a new repository is created, and the format of
        that repository, or some existing shared repository used instead.

        If stack_on is supplied, will not seek a containing shared repo.

        :param force_new_repo: If True, require a new repository to be created.
        :param stack_on: If supplied, the location to stack on.  If not
            supplied, a default_stack_on location may be used.
        :param stack_on_pwd: If stack_on is relative, the location it is
            relative to.
        """
        return UseExistingRepository(self.find_repository())

    def branch_names(self):
        """Get the names of all branches in this repository.

        Returns:
            list: List of branch names as strings.
        """
        from .refs import ref_to_branch_name

        ret = []
        for ref in self.get_refs_container().keys():
            try:
                branch_name = ref_to_branch_name(ref)
            except UnicodeDecodeError:
                trace.warning("Ignoring branch %r with unicode error ref", ref)
                continue
            except ValueError:
                continue
            ret.append(branch_name)
        return ret

    def get_branches(self):
        """Get all branches in this repository.

        Returns:
            dict: Mapping of branch names to Branch objects.
        """
        from .refs import ref_to_branch_name

        ret = {}
        for ref in self.get_refs_container().keys():
            try:
                branch_name = ref_to_branch_name(ref)
            except UnicodeDecodeError:
                trace.warning("Ignoring branch %r with unicode error ref", ref)
                continue
            except ValueError:
                continue
            ret[branch_name] = self.open_branch(ref=ref)
        return ret

    def list_branches(self):
        """Get a list of all branches in this repository.

        Returns:
            list: List of Branch objects.
        """
        return list(self.get_branches().values())

    def push_branch(
        self,
        source,
        revision_id=None,
        overwrite=False,
        remember=False,
        create_prefix=False,
        lossy=False,
        name=None,
        tag_selector=None,
    ):
        """Push the source branch into this ControlDir."""
        push_result = GitPushResult()
        push_result.workingtree_updated = None
        push_result.master_branch = None
        push_result.source_branch = source
        push_result.stacked_on = None
        from .branch import GitBranch

        if isinstance(source, GitBranch) and lossy:
            raise brz_errors.LossyPushToSameVCS(source.controldir, self)
        target = self.open_branch(name, nascent_ok=True)
        push_result.branch_push_result = source.push(
            target,
            overwrite=overwrite,
            stop_revision=revision_id,
            lossy=lossy,
            tag_selector=tag_selector,
        )
        push_result.new_revid = push_result.branch_push_result.new_revid
        push_result.old_revid = push_result.branch_push_result.old_revid
        try:
            wt = self.open_workingtree()
        except brz_errors.NoWorkingTree:
            push_result.workingtree_updated = None
        else:
            if self.open_branch(name="").name == target.name:
                wt._update_git_tree(
                    old_revision=push_result.old_revid,
                    new_revision=push_result.new_revid,
                )
                push_result.workingtree_updated = True
            else:
                push_result.workingtree_updated = False
        push_result.target_branch = target
        if source.get_push_location() is None or remember:
            source.set_push_location(push_result.target_branch.base)
        return push_result


class LocalGitControlDirFormat(GitControlDirFormat):
    """The .git directory control format for local repositories.

    This format represents a standard Git repository with a working tree.
    """

    bare = False

    @classmethod
    def _known_formats(self):
        return {LocalGitControlDirFormat()}

    @property
    def repository_format(self):
        from .repository import GitRepositoryFormat

        return GitRepositoryFormat()

    @property
    def workingtree_format(self):
        from .workingtree import GitWorkingTreeFormat

        return GitWorkingTreeFormat()

    def get_branch_format(self):
        from .branch import LocalGitBranchFormat

        return LocalGitBranchFormat()

    def open(self, transport, _found=None):
        """Open this directory."""
        from .transportgit import TransportRepo

        def _open(transport):
            try:
                return TransportRepo(
                    transport, self.bare, refs_text=getattr(self, "_refs_text", None)
                )
            except ValueError as e:
                if e.args == ("Expected file to start with 'gitdir: '",):
                    raise brz_errors.NotBranchError(path=transport.base) from e
                raise

        def redirected(transport, e, redirection_notice):
            trace.note(redirection_notice)
            return transport._redirected_to(e.source, e.target)

        gitrepo = do_catching_redirections(_open, transport, redirected)
        if not _found and not gitrepo._controltransport.has("objects"):
            raise brz_errors.NotBranchError(path=transport.base)
        return LocalGitDir(transport, gitrepo, self)

    def get_format_description(self):
        return "Local Git Repository"

    def initialize_on_transport(self, transport):
        from .transportgit import TransportRepo

        git_repo = TransportRepo.init(transport, bare=self.bare)
        return LocalGitDir(transport, git_repo, self)

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
        vfs_only=False,
    ):
        if shared_repo:
            raise brz_errors.SharedRepositoriesUnsupported(self)

        def make_directory(transport):
            transport.mkdir(".")
            return transport

        def redirected(transport, e, redirection_notice):
            trace.note(redirection_notice)
            return transport._redirected_to(e.source, e.target)

        try:
            transport = do_catching_redirections(make_directory, transport, redirected)
        except FileExists:
            if not use_existing_dir:
                raise
        except NoSuchFile:
            if not create_prefix:
                raise
            transport.create_prefix()
        controldir = self.initialize_on_transport(transport)
        if repo_format_name:
            result_repo = controldir.find_repository()
            repository_policy = UseExistingRepository(result_repo)
            result_repo.lock_write()
        else:
            result_repo = None
            repository_policy = None
        return (result_repo, controldir, False, repository_policy)

    def is_supported(self):
        return True

    def supports_transport(self, transport):
        try:
            external_url = transport.external_url()
        except brz_errors.InProcessTransport as err:
            raise brz_errors.NotBranchError(path=transport.base) from err
        return external_url.startswith("file:")

    def is_control_filename(self, filename):
        """Check if a filename is a Git control file.

        Args:
            filename: The filename to check.

        Returns:
            bool: True if the filename is a Git control file.
        """
        return (
            filename == ".git"
            or filename.startswith(".git/")
            or filename.startswith(".git\\")
        )


class BareLocalGitControlDirFormat(LocalGitControlDirFormat):
    """Format for bare Git repositories without working trees.

    This format represents a Git repository that contains only the
    Git data without a working directory.
    """

    bare = True
    supports_workingtrees = False

    def get_format_description(self):
        """Get a human-readable description of this format.

        Returns:
            str: Description of the bare Git format.
        """
        return "Local Git Repository (bare)"

    def is_control_filename(self, filename):
        """Check if a filename is a Git control file.

        Args:
            filename: The filename to check.

        Returns:
            bool: Always False for bare repositories (all files are data).
        """
        return False


class LocalGitDir(GitDir):
    """An adapter to the '.git' dir used by git."""

    def _get_gitrepository_class(self):
        from .repository import LocalGitRepository

        return LocalGitRepository

    def __repr__(self):
        return f"<{self.__class__.__name__} at {self.root_transport.base!r}>"

    _gitrepository_class = property(_get_gitrepository_class)

    @property
    def user_transport(self):
        return self.root_transport

    @property
    def control_transport(self):
        return self._git._controltransport

    def __init__(self, transport, gitrepo, format):
        """Initialize a LocalGitDir.

        Args:
            transport: The transport for accessing the repository.
            gitrepo: The underlying Git repository object.
            format: The control directory format.
        """
        self._format = format
        self.root_transport = transport
        self._mode_check_done = False
        self._git = gitrepo
        if gitrepo.bare:
            self.transport = transport
        else:
            self.transport = transport.clone(".git")
        self._mode_check_done = None

    def _get_symref(self, ref):
        """Get the target of a symbolic reference.

        Args:
            ref: The symbolic reference to follow.

        Returns:
            bytes or None: The target ref, or None if not a symref.
        """
        ref_chain, unused_sha = self._git.refs.follow(ref)
        if len(ref_chain) == 1:
            return None
        return ref_chain[1]

    def set_branch_reference(self, target_branch, name=None):
        """Set a branch to be a reference to another branch.

        Args:
            target_branch: The branch to reference.
            name: Name of the branch to set as a reference.

        Raises:
            BranchReferenceLoop: If setting the reference would create a loop.
            IncompatibleFormat: If the target branch is incompatible.
        """
        ref = self._get_selected_ref(name)
        target_transport = target_branch.controldir.control_transport
        if self.control_transport.base == target_transport.base:
            if ref == target_branch.ref:
                raise BranchReferenceLoop(target_branch)
            self._git.refs.set_symbolic_ref(ref, target_branch.ref)
        else:
            try:
                target_path = target_branch.controldir.control_transport.local_abspath(
                    "."
                )
            except brz_errors.NotLocalUrl as err:
                raise brz_errors.IncompatibleFormat(
                    target_branch._format, self._format
                ) from err
            # TODO(jelmer): Do some consistency checking across branches..
            self.control_transport.put_bytes("commondir", encode_git_path(target_path))
            # TODO(jelmer): Urgh, avoid mucking about with internals.
            self._git._commontransport = (
                target_branch.repository._git._commontransport.clone()
            )
            self._git.object_store = TransportObjectStore(
                self._git._commontransport.clone(OBJECTDIR)
            )
            self._git.refs.transport = self._git._commontransport
            target_ref_chain, unused_sha = target_branch.controldir._git.refs.follow(
                target_branch.ref
            )
            for target_ref in target_ref_chain:
                if target_ref == b"HEAD":
                    continue
                break
            else:
                # Can't create a reference to something that is not a in a repository.
                raise brz_errors.IncompatibleFormat(self.set_branch_reference, self)
            self._git.refs.set_symbolic_ref(ref, target_ref)

    def get_branch_reference(self, name=None):
        """Get the URL of the branch this branch references.

        Args:
            name: Name of the branch to check for references.

        Returns:
            str or None: URL of the referenced branch, or None if not a reference.

        Raises:
            BranchReferenceLoop: If there is a reference loop.
        """
        ref = self._get_selected_ref(name)
        try:
            target_ref = self._get_symref(ref)
        except SymrefLoop as err:
            raise BranchReferenceLoop(self) from err
        if target_ref is not None:
            from .refs import ref_to_branch_name

            try:
                branch_name = ref_to_branch_name(target_ref)
            except ValueError:
                params = {"ref": urlutils.quote(target_ref.decode("utf-8"), "")}
            else:
                if branch_name != "":
                    params = {"branch": urlutils.quote(branch_name, "")}
                else:
                    params = {}
            try:
                commondir = self.control_transport.get_bytes("commondir")
            except NoSuchFile:
                base_url = self.user_url.rstrip("/")
            else:
                base_url = (
                    urlutils.local_path_to_url(  # noqa: B005
                        decode_git_path(commondir)
                    ).rstrip("/.git/")
                    + "/"
                )
            return urlutils.join_segment_parameters(base_url, params)
        return None

    def find_branch_format(self, name=None):
        """Find the format of a branch.

        Args:
            name: Name of the branch (unused for Git).

        Returns:
            LocalGitBranchFormat: The Git branch format.
        """
        from .branch import LocalGitBranchFormat

        return LocalGitBranchFormat()

    def get_branch_transport(self, branch_format, name=None):
        if branch_format is None:
            return self.transport
        if isinstance(branch_format, LocalGitControlDirFormat):
            return self.transport
        raise brz_errors.IncompatibleFormat(branch_format, self._format)

    def get_repository_transport(self, format):
        if format is None:
            return self.transport
        if isinstance(format, LocalGitControlDirFormat):
            return self.transport
        raise brz_errors.IncompatibleFormat(format, self._format)

    def get_workingtree_transport(self, format):
        if format is None:
            return self.transport
        if isinstance(format, LocalGitControlDirFormat):
            return self.transport
        raise brz_errors.IncompatibleFormat(format, self._format)

    def open_branch(
        self,
        name=None,
        unsupported=False,
        ignore_fallbacks=None,
        ref=None,
        possible_transports=None,
        nascent_ok=False,
    ):
        """'create' a branch for this dir."""
        repo = self.find_repository()
        from .branch import LocalGitBranch

        ref = self._get_selected_ref(name, ref)
        if not nascent_ok and ref not in self._git.refs:
            raise brz_errors.NotBranchError(self.root_transport.base, controldir=self)
        try:
            ref_chain, unused_sha = self._git.refs.follow(ref)
        except SymrefLoop as err:
            raise BranchReferenceLoop(self) from err
        controldir = self if ref_chain[-1] == b"HEAD" else self._find_commondir()
        return LocalGitBranch(controldir, repo, ref_chain[-1])

    def destroy_branch(self, name=None):
        refname = self._get_selected_ref(name)
        if refname == b"HEAD":
            # HEAD can't be removed
            raise brz_errors.UnsupportedOperation(self.destroy_branch, self)
        try:
            del self._git.refs[refname]
        except KeyError as err:
            raise brz_errors.NotBranchError(
                self.root_transport.base, controldir=self
            ) from err

    def destroy_repository(self):
        raise brz_errors.UnsupportedOperation(self.destroy_repository, self)

    def destroy_workingtree(self):
        raise brz_errors.UnsupportedOperation(self.destroy_workingtree, self)

    def destroy_workingtree_metadata(self):
        raise brz_errors.UnsupportedOperation(self.destroy_workingtree_metadata, self)

    def needs_format_conversion(self, format=None):
        return not isinstance(self._format, format.__class__)

    def open_repository(self):
        """'open' a repository for this dir."""
        if self.control_transport.has("commondir"):
            raise brz_errors.NoRepositoryPresent(self)
        return self._gitrepository_class(self)

    def has_workingtree(self):
        """Check if this control directory has a working tree.

        Returns:
            bool: True if there is a working tree (not bare).
        """
        return not self._git.bare

    def open_workingtree(self, recommend_upgrade=True, unsupported=False):
        """Open the working tree for this control directory.

        Args:
            recommend_upgrade: Whether to recommend format upgrades.
            unsupported: Whether to allow unsupported working trees.

        Returns:
            GitWorkingTree: The opened working tree.

        Raises:
            NoWorkingTree: If this is a bare repository.
        """
        if not self._git.bare:
            repo = self.find_repository()
            from .workingtree import GitWorkingTree

            branch = self.open_branch(ref=b"HEAD", nascent_ok=True)
            return GitWorkingTree(self, repo, branch)
        loc = urlutils.unescape_for_display(self.root_transport.base, "ascii")
        raise brz_errors.NoWorkingTree(loc)

    def create_repository(self, shared=False):
        from .repository import GitRepositoryFormat

        if shared:
            raise brz_errors.IncompatibleFormat(GitRepositoryFormat(), self._format)
        return self.find_repository()

    def create_branch(
        self, name=None, repository=None, append_revisions_only=None, ref=None
    ):
        refname = self._get_selected_ref(name, ref)
        if refname != b"HEAD" and refname in self._git.refs:
            raise brz_errors.AlreadyBranchError(self.user_url)
        repo = self.open_repository()
        if refname in self._git.refs:
            ref_chain, unused_sha = self._git.refs.follow(self._get_selected_ref(None))
            if ref_chain[0] == b"HEAD":
                refname = ref_chain[1]
        from .branch import LocalGitBranch

        branch = LocalGitBranch(self, repo, refname)
        if append_revisions_only:
            branch.set_append_revisions_only(append_revisions_only)
        return branch

    def backup_bzrdir(self):
        if not self._git.bare:
            self.root_transport.copy_tree(".git", ".git.backup")
            return (
                self.root_transport.abspath(".git"),
                self.root_transport.abspath(".git.backup"),
            )
        else:
            basename = urlutils.basename(self.root_transport.base)
            parent = self.root_transport.clone("..")
            parent.copy_tree(basename, basename + ".backup")

    def create_workingtree(
        self, revision_id=None, from_branch=None, accelerator_tree=None, hardlink=False
    ):
        if self._git.bare:
            raise brz_errors.UnsupportedOperation(self.create_workingtree, self)
        if from_branch is None:
            from_branch = self.open_branch(nascent_ok=True)
        if revision_id is None:
            revision_id = from_branch.last_revision()
        repo = self.find_repository()
        from .workingtree import GitWorkingTree

        wt = GitWorkingTree(self, repo, from_branch)
        wt.set_last_revision(revision_id)
        wt._build_checkout_with_index()
        return wt

    def _find_or_create_repository(self, force_new_repo=None):
        return self.create_repository(shared=False)

    def _find_creation_modes(self):
        """Determine the appropriate modes for files and directories.

        They're always set to be consistent with the base directory,
        assuming that this transport allows setting modes.
        """
        # TODO: Do we need or want an option (maybe a config setting) to turn
        # this off or override it for particular locations? -- mbp 20080512
        if self._mode_check_done:
            return
        self._mode_check_done = True
        try:
            st = self.transport.stat(".")
        except brz_errors.TransportNotPossible:
            self._dir_mode = None
            self._file_mode = None
        else:
            # Check the directory mode, but also make sure the created
            # directories and files are read-write for this user. This is
            # mostly a workaround for filesystems which lie about being able to
            # write to a directory (cygwin & win32)
            if st.st_mode & 0o7777 == 0o0000:
                # FTP allows stat but does not return dir/file modes
                self._dir_mode = None
                self._file_mode = None
            else:
                self._dir_mode = (st.st_mode & 0o7777) | 0o0700
                # Remove the sticky and execute bits for files
                self._file_mode = self._dir_mode & ~0o7111

    def _get_file_mode(self):
        """Return Unix mode for newly created files, or None."""
        if not self._mode_check_done:
            self._find_creation_modes()
        return self._file_mode

    def _get_dir_mode(self):
        """Return Unix mode for newly created directories, or None."""
        if not self._mode_check_done:
            self._find_creation_modes()
        return self._dir_mode

    def get_refs_container(self):
        """Get the Git refs container for this repository.

        Returns:
            RefsContainer: The Git refs container.
        """
        return self._git.refs

    def get_peeled(self, ref):
        """Get the peeled value of a Git reference.

        Args:
            ref: The reference to peel.

        Returns:
            bytes: The SHA-1 of the commit the ref points to.
        """
        return self._git.get_peeled(ref)

    def _find_commondir(self):
        """Find the common directory for Git worktrees.

        Returns:
            ControlDir: The control directory containing the shared Git data.
        """
        try:
            commondir = self.control_transport.get_bytes("commondir")
        except NoSuchFile:
            return self
        else:
            commondir = os.fsdecode(commondir.rstrip(b"/.git/"))
            return ControlDir.open_from_transport(get_transport_from_path(commondir))
