# Copyright (C) 2010, 2011, 2012 Canonical Ltd
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

__docformat__ = "google"

"""ControlDir is the basic control directory class.

The ControlDir class is the base for the control directory used
by all bzr and foreign formats. For the ".bzr" implementation,
see breezy.bzrdir.BzrDir.

"""

from typing import TYPE_CHECKING, Optional, cast

from .lazy_import import lazy_import

lazy_import(
    globals(),
    """
import textwrap

from breezy import (
    branch as _mod_branch,
    ui,
    urlutils,
    )

from breezy.i18n import gettext
""",
)

import contextlib

from . import errors, hooks, registry, trace
from . import revision as _mod_revision
from . import transport as _mod_transport

if TYPE_CHECKING:
    from .branch import Branch
    from .repository import Repository
    from .workingtree import WorkingTree


class MustHaveWorkingTree(errors.BzrError):
    _fmt = "Branching '%(url)s'(%(format)s) must create a working tree."

    def __init__(self, format, url):
        errors.BzrError.__init__(self, format=format, url=url)


class BranchReferenceLoop(errors.BzrError):
    _fmt = "Can not create branch reference that points at branch itself."

    def __init__(self, branch):
        errors.BzrError.__init__(self, branch=branch)


class NoColocatedBranchSupport(errors.BzrError):
    _fmt = "%(controldir)r does not support co-located branches."

    def __init__(self, controldir):
        self.controldir = controldir


class ControlComponent:
    """Abstract base class for control directory components.

    This provides interfaces that are common across controldirs,
    repositories, branches, and workingtree control directories.

    They all expose two urls and transports: the *user* URL is the
    one that stops above the control directory (eg .bzr) and that
    should normally be used in messages, and the *control* URL is
    under that in eg .bzr/checkout and is used to read the control
    files.

    This can be used as a mixin and is intended to fit with
    foreign formats.
    """

    @property
    def control_transport(self) -> _mod_transport.Transport:
        raise NotImplementedError

    @property
    def control_url(self) -> str:
        return self.control_transport.base

    @property
    def user_transport(self) -> _mod_transport.Transport:
        raise NotImplementedError

    @property
    def user_url(self) -> str:
        return self.user_transport.base

    _format: "ControlComponentFormat"


class ControlDir(ControlComponent):
    """A control directory.

    While this represents a generic control directory, there are a few
    features that are present in this interface that are currently only
    supported by one of its implementations, BzrDir.

    These features (bound branches, stacked branches) are currently only
    supported by Bazaar, but could be supported by other version control
    systems as well. Implementations are required to raise the appropriate
    exceptions when an operation is requested that is not supported.

    This also makes life easier for API users who can rely on the
    implementation always allowing a particular feature to be requested but
    raising an exception when it is not supported, rather than requiring the
    API users to check for magic attributes to see what features are supported.
    """

    hooks: hooks.Hooks

    root_transport: _mod_transport.Transport
    user_transport: _mod_transport.Transport

    def can_convert_format(self):
        """Return true if this controldir is one whose format we can convert
        from.
        """
        return True

    def list_branches(self) -> list["Branch"]:
        """Return a sequence of all branches local to this control directory."""
        return list(self.get_branches().values())

    def branch_names(self) -> list[str]:
        """List all branch names in this control directory.

        Returns: List of branch names
        """
        try:
            self.get_branch_reference()
        except (errors.NotBranchError, errors.NoRepositoryPresent):
            return []
        else:
            return [""]

    def get_branches(self) -> dict[str, "Branch"]:
        """Get all branches in this control directory, as a dictionary.

        Returns: Dictionary mapping branch names to instances.
        """
        try:
            return {"": self.open_branch()}
        except (errors.NotBranchError, errors.NoRepositoryPresent):
            return {}

    def is_control_filename(self, filename):
        """True if filename is the name of a path which is reserved for
        controldirs.

        Args:
          filename: A filename within the root transport of this
            controldir.

        This is true IF and ONLY IF the filename is part of the namespace reserved
        for bzr control dirs. Currently this is the '.bzr' directory in the root
        of the root_transport. it is expected that plugins will need to extend
        this in the future - for instance to make bzr talk with svn working
        trees.
        """
        return self._format.is_control_filename(filename)

    def needs_format_conversion(self, format=None):
        """Return true if this controldir needs convert_format run on it.

        For instance, if the repository format is out of date but the
        branch and working tree are not, this should return True.

        Args:
          format: Optional parameter indicating a specific desired
                       format we plan to arrive at.
        """
        raise NotImplementedError(self.needs_format_conversion)

    def create_repository(self, shared: bool = False) -> "Repository":
        """Create a new repository in this control directory.

        Args:
          shared: If a shared repository should be created

        Returns: The newly created repository
        """
        raise NotImplementedError(self.create_repository)

    def destroy_repository(self) -> None:
        """Destroy the repository in this ControlDir."""
        raise NotImplementedError(self.destroy_repository)

    def create_branch(
        self,
        name: Optional[str] = None,
        repository: Optional["Repository"] = None,
        append_revisions_only: Optional[bool] = None,
    ) -> "Branch":
        """Create a branch in this ControlDir.

        Args:
          name: Name of the colocated branch to create, None for
            the user selected branch or "" for the active branch.
          append_revisions_only: Whether this branch should only allow
            appending new revisions to its history.

        The controldirs format will control what branch format is created.
        For more control see BranchFormatXX.create(a_controldir).
        """
        raise NotImplementedError(self.create_branch)

    def destroy_branch(self, name: Optional[str] = None) -> None:
        """Destroy a branch in this ControlDir.

        Args:
          name: Name of the branch to destroy, None for the
            user selected branch or "" for the active branch.

        Raises:
          NotBranchError: When the branch does not exist
        """
        raise NotImplementedError(self.destroy_branch)

    def create_workingtree(
        self, revision_id=None, from_branch=None, accelerator_tree=None, hardlink=False
    ) -> "WorkingTree":
        """Create a working tree at this ControlDir.

        Args:
          revision_id: create it as of this revision id.
          from_branch: override controldir branch
            (for lightweight checkouts)
          accelerator_tree: A tree which can be used for retrieving file
            contents more quickly than the revision tree, i.e. a workingtree.
            The revision tree will be used for cases where accelerator_tree's
            content is different.
        """
        raise NotImplementedError(self.create_workingtree)

    def destroy_workingtree(self):
        """Destroy the working tree at this ControlDir.

        Formats that do not support this may raise UnsupportedOperation.
        """
        raise NotImplementedError(self.destroy_workingtree)

    def destroy_workingtree_metadata(self):
        """Destroy the control files for the working tree at this ControlDir.

        The contents of working tree files are not affected.
        Formats that do not support this may raise UnsupportedOperation.
        """
        raise NotImplementedError(self.destroy_workingtree_metadata)

    def find_branch_format(self, name=None):
        """Find the branch 'format' for this controldir.

        This might be a synthetic object for e.g. RemoteBranch and SVN.
        """
        raise NotImplementedError(self.find_branch_format)

    def get_branch_reference(self, name=None):
        """Return the referenced URL for the branch in this controldir.

        Args:
          name: Optional colocated branch name

        Raises:
          NotBranchError: If there is no Branch.
          NoColocatedBranchSupport: If a branch name was specified
            but colocated branches are not supported.

        Returns:
          The URL the branch in this controldir references if it is a
          reference branch, or None for regular branches.
        """
        if name is not None:
            raise NoColocatedBranchSupport(self)
        return None

    def set_branch_reference(self, target_branch, name=None):
        """Set the referenced URL for the branch in this controldir.

        Args:
          name: Optional colocated branch name
          target_branch: Branch to reference

        Raises:
          NoColocatedBranchSupport: If a branch name was specified
            but colocated branches are not supported.

        Returns:
          The referencing branch
        """
        raise NotImplementedError(self.set_branch_reference)

    def open_branch(
        self,
        name=None,
        unsupported=False,
        ignore_fallbacks=False,
        possible_transports=None,
    ) -> "Branch":
        """Open the branch object at this ControlDir if one is present.

        Args:
          unsupported: if True, then no longer supported branch formats can
            still be opened.
          ignore_fallbacks: Whether to open fallback repositories
          possible_transports: Transports to use for opening e.g.
            fallback repositories.
        """
        raise NotImplementedError(self.open_branch)

    def open_repository(self, _unsupported=False) -> "Repository":
        """Open the repository object at this ControlDir if one is present.

        This will not follow the Branch object pointer - it's strictly a direct
        open facility. Most client code should use open_branch().repository to
        get at a repository.

        Args:
          _unsupported: a private parameter, not part of the api.
        """
        raise NotImplementedError(self.open_repository)

    def find_repository(self) -> "Repository":
        """Find the repository that should be used.

        This does not require a branch as we use it to find the repo for
        new branches as well as to hook existing branches up to their
        repository.
        """
        raise NotImplementedError(self.find_repository)

    def open_workingtree(
        self, unsupported=False, recommend_upgrade=True, from_branch=None
    ) -> "WorkingTree":
        """Open the workingtree object at this ControlDir if one is present.

        Args:
          recommend_upgrade: Optional keyword parameter, when True (the
            default), emit through the ui module a recommendation that the user
            upgrade the working tree when the workingtree being opened is old
            (but still fully supported).
          from_branch: override controldir branch (for lightweight
            checkouts)
        """
        raise NotImplementedError(self.open_workingtree)

    def has_branch(self, name=None):
        """Tell if this controldir contains a branch.

        Note: if you're going to open the branch, you should just go ahead
        and try, and not ask permission first.  (This method just opens the
        branch and discards it, and that's somewhat expensive.)
        """
        try:
            self.open_branch(name, ignore_fallbacks=True)
            return True
        except errors.NotBranchError:
            return False

    def _get_selected_branch(self):
        """Return the name of the branch selected by the user.

        Returns: Name of the branch selected by the user, or "".
        """
        branch = self.root_transport.get_segment_parameters().get("branch")
        if branch is None:
            branch = ""
        return urlutils.unescape(branch)

    def has_workingtree(self):
        """Tell if this controldir contains a working tree.

        This will still raise an exception if the controldir has a workingtree
        that is remote & inaccessible.

        Note: if you're going to open the working tree, you should just go ahead
        and try, and not ask permission first.  (This method just opens the
        workingtree and discards it, and that's somewhat expensive.)
        """
        try:
            self.open_workingtree(recommend_upgrade=False)
            return True
        except errors.NoWorkingTree:
            return False

    def cloning_metadir(self, require_stacking=False):
        """Produce a metadir suitable for cloning or sprouting with.

        These operations may produce workingtrees (yes, even though they're
        "cloning" something that doesn't have a tree), so a viable workingtree
        format must be selected.

        :require_stacking: If True, non-stackable formats will be upgraded
            to similar stackable formats.
        :returns: a ControlDirFormat with all component formats either set
            appropriately or set to None if that component should not be
            created.
        """
        raise NotImplementedError(self.cloning_metadir)

    def checkout_metadir(self):
        """Produce a metadir suitable for checkouts of this controldir.

        :returns: A ControlDirFormat with all component formats
            either set appropriately or set to None if that component
            should not be created.
        """
        return self.cloning_metadir()

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
        lossy=False,
    ):
        """Create a copy of this controldir prepared for use as a new line of
        development.

        If url's last component does not exist, it will be created.

        Attributes related to the identity of the source branch like
        branch nickname will be cleaned, a working tree is created
        whether one existed before or not; and a local branch is always
        created.

        Args:
          revision_id: if revision_id is not None, then the clone
            operation may tune itself to download less data.
          accelerator_tree: A tree which can be used for retrieving file
            contents more quickly than the revision tree, i.e. a workingtree.
            The revision tree will be used for cases where accelerator_tree's
            content is different.
          hardlink: If true, hard-link files from accelerator_tree,
            where possible.
          stacked: If true, create a stacked branch referring to the
            location of this control directory.
          create_tree_if_local: If true, a working-tree will be created
            when working locally.
        """
        raise NotImplementedError(self.sprout)

    def push_branch(
        self,
        source,
        revision_id=None,
        overwrite=False,
        remember=False,
        create_prefix=False,
        lossy=False,
        tag_selector=None,
        name=None,
    ):
        """Push the source branch into this ControlDir."""
        from .push import PushResult

        # If we can open a branch, use its direct repository, otherwise see
        # if there is a repository without a branch.
        try:
            br_to = self.open_branch(name=name)
        except errors.NotBranchError:
            # Didn't find a branch, can we find a repository?
            repository_to = self.find_repository()
            br_to = None
        else:
            # Found a branch, so we must have found a repository
            repository_to = br_to.repository

        push_result = PushResult()
        push_result.source_branch = source
        if br_to is None:
            # We have a repository but no branch, copy the revisions, and then
            # create a branch.
            if revision_id is None:
                # No revision supplied by the user, default to the branch
                # revision
                revision_id = source.last_revision()
            repository_to.fetch(source.repository, revision_id=revision_id)
            br_to = source.sprout(
                self,
                revision_id=revision_id,
                lossy=lossy,
                tag_selector=tag_selector,
                name=name,
            )
            if source.get_push_location() is None or remember:
                # FIXME: Should be done only if we succeed ? -- vila 2012-01-18
                source.set_push_location(br_to.base)
            push_result.stacked_on = None
            push_result.branch_push_result = None
            push_result.old_revno = None
            push_result.old_revid = _mod_revision.NULL_REVISION
            push_result.target_branch = br_to
            push_result.master_branch = None
            push_result.workingtree_updated = False
        else:
            # We have successfully opened the branch, remember if necessary:
            if source.get_push_location() is None or remember:
                # FIXME: Should be done only if we succeed ? -- vila 2012-01-18
                source.set_push_location(br_to.base)
            try:
                tree_to = self.open_workingtree()
            except errors.NotLocalUrl:
                push_result.branch_push_result = source.push(
                    br_to,
                    overwrite=overwrite,
                    stop_revision=revision_id,
                    lossy=lossy,
                    tag_selector=tag_selector,
                )
                push_result.workingtree_updated = False
            except errors.NoWorkingTree:
                push_result.branch_push_result = source.push(
                    br_to,
                    overwrite=overwrite,
                    stop_revision=revision_id,
                    lossy=lossy,
                    tag_selector=tag_selector,
                )
                push_result.workingtree_updated = None  # Not applicable
            else:
                if br_to.name == tree_to.branch.name:
                    with tree_to.lock_write():
                        push_result.branch_push_result = source.push(
                            tree_to.branch,
                            overwrite=overwrite,
                            stop_revision=revision_id,
                            lossy=lossy,
                            tag_selector=tag_selector,
                        )
                        tree_to.update()
                    push_result.workingtree_updated = True
                else:
                    push_result.branch_push_result = source.push(
                        br_to,
                        overwrite=overwrite,
                        stop_revision=revision_id,
                        lossy=lossy,
                        tag_selector=tag_selector,
                    )
                    push_result.workingtree_updated = None  # Not applicable
            push_result.old_revno = push_result.branch_push_result.old_revno
            push_result.old_revid = push_result.branch_push_result.old_revid
            push_result.target_branch = push_result.branch_push_result.target_branch
        return push_result

    def _get_tree_branch(self, name=None):
        """Return the branch and tree, if any, for this controldir.

        Args:
          name: Name of colocated branch to open.

        Return None for tree if not present or inaccessible.
        Raise NotBranchError if no branch is present.

        Returns: (tree, branch)
        """
        try:
            tree = self.open_workingtree()
        except (errors.NoWorkingTree, errors.NotLocalUrl):
            tree = None
            branch = self.open_branch(name=name)
        else:
            branch = self.open_branch(name=name) if name is not None else tree.branch
        return tree, branch

    def get_config(self):
        """Get configuration for this ControlDir."""
        raise NotImplementedError(self.get_config)

    def check_conversion_target(self, target_format):
        """Check that a controldir as a whole can be converted to a new format."""
        raise NotImplementedError(self.check_conversion_target)

    def clone(
        self,
        url,
        revision_id=None,
        force_new_repo=False,
        preserve_stacking=False,
        tag_selector=None,
    ):
        """Clone this controldir and its contents to url verbatim.

        Args:
          url: The url create the clone at.  If url's last component does
            not exist, it will be created.
          revision_id: The tip revision-id to use for any branch or
            working tree.  If not None, then the clone operation may tune
            itself to download less data.
          force_new_repo: Do not use a shared repository for the target
                               even if one is available.
          preserve_stacking: When cloning a stacked branch, stack the
            new branch on top of the other branch's stacked-on branch.
        """
        return self.clone_on_transport(
            _mod_transport.get_transport(url),
            revision_id=revision_id,
            force_new_repo=force_new_repo,
            preserve_stacking=preserve_stacking,
            tag_selector=tag_selector,
        )

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
        """Clone this controldir and its contents to transport verbatim.

        Args:
          transport: The transport for the location to produce the clone
            at.  If the target directory does not exist, it will be created.
          revision_id: The tip revision-id to use for any branch or
            working tree.  If not None, then the clone operation may tune
            itself to download less data.
          force_new_repo: Do not use a shared repository for the target,
                               even if one is available.
          preserve_stacking: When cloning a stacked branch, stack the
            new branch on top of the other branch's stacked-on branch.
          create_prefix: Create any missing directories leading up to
            to_transport.
          use_existing_dir: Use an existing directory if one exists.
          no_tree: If set to true prevents creation of a working tree.
        """
        raise NotImplementedError(self.clone_on_transport)

    @classmethod
    def find_controldirs(klass, transport, evaluate=None, list_current=None):
        """Find control dirs recursively from current location.

        This is intended primarily as a building block for more sophisticated
        functionality, like finding trees under a directory, or finding
        branches that use a given repository.

        Args:
          evaluate: An optional callable that yields recurse, value,
            where recurse controls whether this controldir is recursed into
            and value is the value to yield.  By default, all bzrdirs
            are recursed into, and the return value is the controldir.
          list_current: if supplied, use this function to list the current
            directory, instead of Transport.list_dir

        Returns:
          a generator of found bzrdirs, or whatever evaluate returns.
        """
        if list_current is None:

            def list_current(transport):
                return transport.list_dir("")

        if evaluate is None:

            def evaluate(controldir):
                return True, controldir

        pending = [transport]
        while len(pending) > 0:
            current_transport = pending.pop()
            recurse = True
            try:
                controldir = klass.open_from_transport(current_transport)
            except (
                errors.NotBranchError,
                errors.PermissionDenied,
                errors.UnknownFormatError,
            ):
                pass
            else:
                recurse, value = evaluate(controldir)
                yield value
            try:
                subdirs = list_current(current_transport)
            except (_mod_transport.NoSuchFile, errors.PermissionDenied):
                continue
            if recurse:
                for subdir in sorted(subdirs, reverse=True):
                    pending.append(current_transport.clone(subdir))

    @classmethod
    def find_branches(klass, transport):
        """Find all branches under a transport.

        This will find all branches below the transport, including branches
        inside other branches.  Where possible, it will use
        Repository.find_branches.

        To list all the branches that use a particular Repository, see
        Repository.find_branches
        """

        def evaluate(controldir):
            try:
                repository = controldir.open_repository()
            except errors.NoRepositoryPresent:
                pass
            else:
                return False, ([], repository)
            return True, (controldir.list_branches(), None)

        ret = []
        for branches, repo in klass.find_controldirs(transport, evaluate=evaluate):
            if repo is not None:
                ret.extend(repo.find_branches())
            if branches is not None:
                ret.extend(branches)
        return ret

    @classmethod
    def create_branch_and_repo(
        klass, base, force_new_repo=False, format=None
    ) -> "Branch":
        """Create a new ControlDir, Branch and Repository at the url 'base'.

        This will use the current default ControlDirFormat unless one is
        specified, and use whatever
        repository format that that uses via controldir.create_branch and
        create_repository. If a shared repository is available that is used
        preferentially.

        The created Branch object is returned.

        Args:
          base: The URL to create the branch at.
          force_new_repo: If True a new repository is always created.
          format: If supplied, the format of branch to create.  If not
            supplied, the default is used.
        """
        controldir = klass.create(base, format)
        controldir._find_or_create_repository(force_new_repo)
        return cast("Branch", controldir.create_branch())

    @classmethod
    def create_branch_convenience(
        klass,
        base,
        force_new_repo=False,
        force_new_tree=None,
        format=None,
        possible_transports=None,
    ):
        """Create a new ControlDir, Branch and Repository at the url 'base'.

        This is a convenience function - it will use an existing repository
        if possible, can be told explicitly whether to create a working tree or
        not.

        This will use the current default ControlDirFormat unless one is
        specified, and use whatever
        repository format that that uses via ControlDir.create_branch and
        create_repository. If a shared repository is available that is used
        preferentially. Whatever repository is used, its tree creation policy
        is followed.

        The created Branch object is returned.
        If a working tree cannot be made due to base not being a file:// url,
        no error is raised unless force_new_tree is True, in which case no
        data is created on disk and NotLocalUrl is raised.

        Args:
          base: The URL to create the branch at.
          force_new_repo: If True a new repository is always created.
          force_new_tree: If True or False force creation of a tree or
                               prevent such creation respectively.
          format: Override for the controldir format to create.
          possible_transports: An optional reusable transports list.
        """
        if force_new_tree:
            from breezy.transport import local

            # check for non local urls
            t = _mod_transport.get_transport(base, possible_transports)
            if not isinstance(t, local.LocalTransport):
                raise errors.NotLocalUrl(base)
        controldir = klass.create(base, format, possible_transports)
        repo = controldir._find_or_create_repository(force_new_repo)
        result = controldir.create_branch()
        if force_new_tree or (repo.make_working_trees() and force_new_tree is None):
            with contextlib.suppress(errors.NotLocalUrl):
                controldir.create_workingtree()
        return result

    @classmethod
    def create_standalone_workingtree(klass, base, format=None) -> "WorkingTree":
        """Create a new ControlDir, WorkingTree, Branch and Repository at 'base'.

        'base' must be a local path or a file:// url.

        This will use the current default ControlDirFormat unless one is
        specified, and use whatever
        repository format that that uses for bzrdirformat.create_workingtree,
        create_branch and create_repository.

        Args:
          format: Override for the controldir format to create.

        Returns: The WorkingTree object.
        """
        t = _mod_transport.get_transport(base)
        from breezy.transport import local

        if not isinstance(t, local.LocalTransport):
            raise errors.NotLocalUrl(base)
        controldir = klass.create_branch_and_repo(
            base, force_new_repo=True, format=format
        ).controldir
        return controldir.create_workingtree()

    @classmethod
    def open_unsupported(klass, base):
        """Open a branch which is not supported."""
        return klass.open(base, _unsupported=True)

    @classmethod
    def open(
        klass, base, possible_transports=None, probers=None, _unsupported=False
    ) -> "ControlDir":
        """Open an existing controldir, rooted at 'base' (url).

        Args:
          _unsupported: a private parameter to the ControlDir class.
        """
        t = _mod_transport.get_transport(base, possible_transports)
        return klass.open_from_transport(t, probers=probers, _unsupported=_unsupported)

    @classmethod
    def open_from_transport(
        klass, transport: _mod_transport.Transport, _unsupported=False, probers=None
    ) -> "ControlDir":
        """Open a controldir within a particular directory.

        Args:
          transport: Transport containing the controldir.
          _unsupported: private.
        """
        for hook in klass.hooks["pre_open"]:
            hook(transport)
        # Keep initial base since 'transport' may be modified while following
        # the redirections.
        base = transport.base

        def find_format(transport):
            return transport, ControlDirFormat.find_format(transport, probers=probers)

        def redirected(transport, e, redirection_notice):
            redirected_transport = transport._redirected_to(e.source, e.target)
            if redirected_transport is None:
                raise errors.NotBranchError(base)
            trace.note(
                gettext("{0} is{1} redirected to {2}").format(
                    transport.base, e.permanently, redirected_transport.base
                )
            )
            return redirected_transport

        try:
            transport, format = _mod_transport.do_catching_redirections(
                find_format, transport, redirected
            )
        except errors.TooManyRedirections as e:
            raise errors.NotBranchError(base) from e

        format.check_support_status(_unsupported)
        return cast("ControlDir", format.open(transport, _found=True))

    @classmethod
    def open_containing(klass, url, possible_transports=None):
        """Open an existing branch which contains url.

        Args:
          url: url to search from.

        See open_containing_from_transport for more detail.
        """
        transport = _mod_transport.get_transport(url, possible_transports)
        return klass.open_containing_from_transport(transport)

    @classmethod
    def open_containing_from_transport(klass, a_transport, probers=None):
        """Open an existing branch which contains a_transport.base.

        This probes for a branch at a_transport, and searches upwards from there.

        Basically we keep looking up until we find the control directory or
        run into the root.  If there isn't one, raises NotBranchError.
        If there is one and it is either an unrecognised format or an unsupported
        format, UnknownFormatError or UnsupportedFormatError are raised.
        If there is one, it is returned, along with the unused portion of url.

        Returns: The ControlDir that contains the path, and a Unicode path
                for the rest of the URL.
        """
        # this gets the normalised url back. I.e. '.' -> the full path.
        url = a_transport.base
        while True:
            try:
                result = klass.open_from_transport(a_transport, probers=probers)
                return result, urlutils.unescape(a_transport.relpath(url))
            except errors.NotBranchError:
                pass
            except errors.PermissionDenied:
                pass
            try:
                new_t = a_transport.clone("..")
            except urlutils.InvalidURLJoin as e:
                # reached the root, whatever that may be
                raise errors.NotBranchError(path=url) from e
            if new_t.base == a_transport.base:
                # reached the root, whatever that may be
                raise errors.NotBranchError(path=url)
            a_transport = new_t

    @classmethod
    def open_tree_or_branch(klass, location, name=None):
        """Return the branch and working tree at a location.

        If there is no tree at the location, tree will be None.
        If there is no branch at the location, an exception will be
        raised
        Returns: (tree, branch)
        """
        controldir = klass.open(location)
        return controldir._get_tree_branch(name=name)

    @classmethod
    def open_containing_tree_or_branch(klass, location, possible_transports=None):
        """Return the branch and working tree contained by a location.

        Returns (tree, branch, relpath).
        If there is no tree at containing the location, tree will be None.
        If there is no branch containing the location, an exception will be
        raised
        relpath is the portion of the path that is contained by the branch.
        """
        controldir, relpath = klass.open_containing(
            location, possible_transports=possible_transports
        )
        tree, branch = controldir._get_tree_branch()
        return tree, branch, relpath

    @classmethod
    def open_containing_tree_branch_or_repository(klass, location):
        """Return the working tree, branch and repo contained by a location.

        Returns (tree, branch, repository, relpath).
        If there is no tree containing the location, tree will be None.
        If there is no branch containing the location, branch will be None.
        If there is no repository containing the location, repository will be
        None.
        relpath is the portion of the path that is contained by the innermost
        ControlDir.

        If no tree, branch or repository is found, a NotBranchError is raised.
        """
        controldir, relpath = klass.open_containing(location)
        try:
            tree, branch = controldir._get_tree_branch()
        except errors.NotBranchError:
            try:
                repo = controldir.find_repository()
                return None, None, repo, relpath
            except errors.NoRepositoryPresent as e:
                raise errors.NotBranchError(location) from e
        return tree, branch, branch.repository, relpath

    @classmethod
    def create(klass, base, format=None, possible_transports=None):
        """Create a new ControlDir at the url 'base'.

        Args:
          format: If supplied, the format of branch to create.  If not
            supplied, the default is used.
          possible_transports: If supplied, a list of transports that
            can be reused to share a remote connection.
        """
        if klass is not ControlDir:
            raise AssertionError(
                "ControlDir.create always creates the"
                "default format, not one of {!r}".format(klass)
            )
        t = _mod_transport.get_transport(base, possible_transports)
        t.ensure_base()
        if format is None:
            format = ControlDirFormat.get_default_format()
        return format.initialize_on_transport(t)


class ControlDirHooks(hooks.Hooks):
    """Hooks for ControlDir operations."""

    def __init__(self):
        """Create the default hooks."""
        hooks.Hooks.__init__(self, "breezy.controldir", "ControlDir.hooks")
        self.add_hook(
            "pre_open",
            "Invoked before attempting to open a ControlDir with the transport "
            "that the open will use.",
            (1, 14),
        )
        self.add_hook(
            "post_repo_init",
            "Invoked after a repository has been initialized. "
            "post_repo_init is called with a "
            "breezy.controldir.RepoInitHookParams.",
            (2, 2),
        )


# install the default hooks
ControlDir.hooks = ControlDirHooks()  # type: ignore


class ControlComponentFormat:
    """A component that can live inside of a control directory."""

    upgrade_recommended = False

    def get_format_description(self):
        """Return the short description for this format."""
        raise NotImplementedError(self.get_format_description)

    def is_supported(self):
        """Is this format supported?

        Supported formats must be initializable and openable.
        Unsupported formats may not support initialization or committing or
        some other features depending on the reason for not being supported.
        """
        return True

    def check_support_status(
        self, allow_unsupported, recommend_upgrade=True, basedir=None
    ):
        """Give an error or warning on old formats.

        Args:
          allow_unsupported: If true, allow opening
            formats that are strongly deprecated, and which may
            have limited functionality.

          recommend_upgrade: If true (default), warn
            the user through the ui object that they may wish
            to upgrade the object.
        """
        if not allow_unsupported and not self.is_supported():
            # see open_downlevel to open legacy branches.
            raise errors.UnsupportedFormatError(format=self)
        if recommend_upgrade and self.upgrade_recommended:
            ui.ui_factory.recommend_upgrade(self.get_format_description(), basedir)

    @classmethod
    def get_format_string(cls):
        raise NotImplementedError(cls.get_format_string)


class ControlComponentFormatRegistry(
    registry.FormatRegistry[ControlComponentFormat, None]
):
    """A registry for control components (branch, workingtree, repository)."""

    def __init__(self, other_registry=None):
        super().__init__(other_registry)
        self._extra_formats = []

    def register(self, format):
        """Register a new format."""
        super().register(format.get_format_string(), format)

    def remove(self, format):
        """Remove a registered format."""
        super().remove(format.get_format_string())

    def register_extra(self, format):
        """Register a format that can not be used in a metadir.

        This is mainly useful to allow custom repository formats, such as older
        Bazaar formats and foreign formats, to be tested.
        """
        self._extra_formats.append(registry._ObjectGetter(format))

    def remove_extra(self, format):
        """Remove an extra format."""
        self._extra_formats.remove(registry._ObjectGetter(format))

    def register_extra_lazy(self, module_name, member_name):
        """Register a format lazily."""
        self._extra_formats.append(registry._LazyObjectGetter(module_name, member_name))

    def _get_extra(self):
        """Return getters for extra formats, not usable in meta directories."""
        return [getter.get_obj for getter in self._extra_formats]

    def _get_all_lazy(self):
        """Return getters for all formats, even those not usable in metadirs."""
        result = [self._dict[name].get_obj for name in self.keys()]
        result.extend(self._get_extra())
        return result

    def _get_all(self):
        """Return all formats, even those not usable in metadirs."""
        result = []
        for getter in self._get_all_lazy():
            fmt = getter()
            if callable(fmt):
                fmt = fmt()
            result.append(fmt)
        return result

    def _get_all_modules(self):
        """Return a set of the modules providing objects."""
        modules = set()
        for name in self.keys():
            modules.add(self._get_module(name))
        for getter in self._extra_formats:
            modules.add(getter.get_module())
        return modules


class Converter:
    """Converts a disk format object from one format to another."""

    def convert(self, to_convert, pb):
        """Perform the conversion of to_convert, giving feedback via pb.

        Args:
          to_convert: The disk object to convert.
          pb: a progress bar to use for progress information.
        """

    def step(self, message):
        """Update the pb by a step."""
        self.count += 1
        self.pb.update(message, self.count, self.total)


class ControlDirFormat:
    """An encapsulation of the initialization and open routines for a format.

    Formats provide three things:
     * An initialization routine,
     * a format string,
     * an open routine.

    Formats are placed in a dict by their format string for reference
    during controldir opening. These should be subclasses of ControlDirFormat
    for consistency.

    Once a format is deprecated, just deprecate the initialize and open
    methods on the format class. Do not deprecate the object, as the
    object will be created every system load.

    Attributes:
      colocated_branches: Whether this formats supports colocated branches.
      supports_workingtrees: This control directory can co-exist with a
                                 working tree.
    """

    _default_format: Optional["ControlDirFormat"] = None
    """The default format used for new control directories."""

    _probers: list[type["Prober"]] = []
    """The registered format probers, e.g. BzrProber.

    This is a list of Prober-derived classes.
    """

    colocated_branches = False
    """Whether co-located branches are supported for this control dir format.
    """

    supports_workingtrees = True
    """Whether working trees can exist in control directories of this format.
    """

    fixed_components = False
    """Whether components can not change format independent of the control dir.
    """

    upgrade_recommended = False
    """Whether an upgrade from this format is recommended."""

    def get_format_description(self):
        """Return the short description for this format."""
        raise NotImplementedError(self.get_format_description)

    def get_converter(self, format=None):
        """Return the converter to use to convert controldirs needing converts.

        This returns a breezy.controldir.Converter object.

        This should return the best upgrader to step this format towards the
        current default format. In the case of plugins we can/should provide
        some means for them to extend the range of returnable converters.

        Args:
          format: Optional format to override the default format of the
                       library.
        """
        raise NotImplementedError(self.get_converter)

    def is_supported(self):
        """Is this format supported?

        Supported formats must be openable.
        Unsupported formats may not support initialization or committing or
        some other features depending on the reason for not being supported.
        """
        return True

    def is_initializable(self):
        """Whether new control directories of this format can be initialized."""
        return self.is_supported()

    def check_support_status(
        self, allow_unsupported, recommend_upgrade=True, basedir=None
    ):
        """Give an error or warning on old formats.

        Args:
          allow_unsupported: If true, allow opening
            formats that are strongly deprecated, and which may
            have limited functionality.

          recommend_upgrade: If true (default), warn
            the user through the ui object that they may wish
            to upgrade the object.
        """
        if not allow_unsupported and not self.is_supported():
            # see open_downlevel to open legacy branches.
            raise errors.UnsupportedFormatError(format=self)
        if recommend_upgrade and self.upgrade_recommended:
            ui.ui_factory.recommend_upgrade(self.get_format_description(), basedir)

    def same_model(self, target_format):
        return self.repository_format.rich_root_data == target_format.rich_root_data

    @classmethod
    def register_prober(klass, prober: type["Prober"]):
        """Register a prober that can look for a control dir."""
        klass._probers.append(prober)

    @classmethod
    def unregister_prober(klass, prober: type["Prober"]):
        """Unregister a prober."""
        klass._probers.remove(prober)

    def __str__(self):
        # Trim the newline
        return self.get_format_description().rstrip()

    @classmethod
    def all_probers(klass) -> list[type["Prober"]]:
        return klass._probers

    @classmethod
    def known_formats(klass):
        """Return all the known formats."""
        result = []
        for prober_kls in klass.all_probers():
            result.extend(prober_kls.known_formats())
        return result

    @classmethod
    def find_format(
        klass,
        transport: _mod_transport.Transport,
        probers: Optional[list[type["Prober"]]] = None,
    ) -> "ControlDirFormat":
        """Return the format present at transport."""
        if probers is None:
            probers = sorted(
                klass.all_probers(), key=lambda prober: prober.priority(transport)
            )
        for prober_kls in probers:
            prober = prober_kls()
            try:
                return prober.probe_transport(transport)
            except errors.NotBranchError:
                # this format does not find a control dir here.
                pass
        raise errors.NotBranchError(path=transport.base)

    def initialize(self, url: str, possible_transports=None):
        """Create a control dir at this url and return an opened copy.

        While not deprecated, this method is very specific and its use will
        lead to many round trips to setup a working environment. See
        initialize_on_transport_ex for a [nearly] all-in-one method.

        Subclasses should typically override initialize_on_transport
        instead of this method.
        """
        return self.initialize_on_transport(
            _mod_transport.get_transport(url, possible_transports)
        )

    def initialize_on_transport(self, transport: _mod_transport.Transport):
        """Initialize a new controldir in the base directory of a Transport."""
        raise NotImplementedError(self.initialize_on_transport)

    def initialize_on_transport_ex(
        self,
        transport: _mod_transport.Transport,
        use_existing_dir: bool = False,
        create_prefix: bool = False,
        force_new_repo: bool = False,
        stacked_on=None,
        stack_on_pwd=None,
        repo_format_name=None,
        make_working_trees=None,
        shared_repo=False,
        vfs_only=False,
    ):
        """Create this format on transport.

        The directory to initialize will be created.

        Args:
          force_new_repo: Do not use a shared repository for the target,
                               even if one is available.
          create_prefix: Create any missing directories leading up to
            to_transport.
          use_existing_dir: Use an existing directory if one exists.
          stacked_on: A url to stack any created branch on, None to follow
            any target stacking policy.
          stack_on_pwd: If stack_on is relative, the location it is
            relative to.
          repo_format_name: If non-None, a repository will be
            made-or-found. Should none be found, or if force_new_repo is True
            the repo_format_name is used to select the format of repository to
            create.
          make_working_trees: Control the setting of make_working_trees
            for a new shared repository when one is made. None to use whatever
            default the format has.
          shared_repo: Control whether made repositories are shared or
            not.
          vfs_only: If True do not attempt to use a smart server

        Returns: repo, controldir, require_stacking, repository_policy. repo is
            None if none was created or found, controldir is always valid.
            require_stacking is the result of examining the stacked_on
            parameter and any stacking policy found for the target.
        """
        raise NotImplementedError(self.initialize_on_transport_ex)

    def network_name(self):
        """A simple byte string uniquely identifying this format for RPC calls.

        Bzr control formats use this disk format string to identify the format
        over the wire. Its possible that other control formats have more
        complex detection requirements, so we permit them to use any unique and
        immutable string they desire.
        """
        raise NotImplementedError(self.network_name)

    def open(self, transport: _mod_transport.Transport, _found=False) -> "ControlDir":
        """Return an instance of this format for the dir transport points at."""
        raise NotImplementedError(self.open)

    @classmethod
    def _set_default_format(klass, format):
        """Set default format (for testing behavior of defaults only)."""
        klass._default_format = format

    @classmethod
    def get_default_format(klass):
        """Return the current default format."""
        return klass._default_format

    def supports_transport(self, transport):
        """Check if this format can be opened over a particular transport."""
        raise NotImplementedError(self.supports_transport)

    @classmethod
    def is_control_filename(klass, filename):
        """True if filename is the name of a path which is reserved for
        controldirs.

        Args:
          filename: A filename within the root transport of this
            controldir.

        This is true IF and ONLY IF the filename is part of the namespace reserved
        for bzr control dirs. Currently this is the '.bzr' directory in the root
        of the root_transport. it is expected that plugins will need to extend
        this in the future - for instance to make bzr talk with svn working
        trees.
        """
        raise NotImplementedError(cls.is_control_filename)


class Prober:
    """Abstract class that can be used to detect a particular kind of
    control directory.

    At the moment this just contains a single method to probe a particular
    transport, but it may be extended in the future to e.g. avoid
    multiple levels of probing for Subversion repositories.

    See BzrProber and RemoteBzrProber in breezy.bzrdir for the
    probers that detect .bzr/ directories and Bazaar smart servers,
    respectively.

    Probers should be registered using the register_prober methods on
    ControlDirFormat.
    """

    def probe_transport(self, transport) -> "ControlDirFormat":
        """Return the controldir style format present in a directory.

        :raise UnknownFormatError: If a control dir was found but is
            in an unknown format.
        :raise NotBranchError: If no control directory was found.
        Returns: A ControlDirFormat instance.
        """
        raise NotImplementedError(self.probe_transport)

    @classmethod
    def known_formats(klass) -> set["ControlDirFormat"]:
        """Return the control dir formats known by this prober.

        Multiple probers can return the same formats, so this should
        return a set.

        Returns: A set of known formats.
        """
        raise NotImplementedError(klass.known_formats)

    @classmethod
    def priority(klass, transport: _mod_transport.Transport) -> int:
        """Priority of this prober.

        A lower value means the prober gets checked first.

        Other conventions:

        -10: This is a "server" prober
        0: No priority set
        10: This is a regular file-based prober
        100: This is a prober for an unsupported format
        """
        return 0


class ControlDirFormatInfo:
    def __init__(self, native, deprecated, hidden, experimental):
        self.deprecated = deprecated
        self.native = native
        self.hidden = hidden
        self.experimental = experimental


class ControlDirFormatRegistry(registry.Registry[str, ControlDirFormat, None]):
    """Registry of user-selectable ControlDir subformats.

    Differs from ControlDirFormat._formats in that it provides sub-formats,
    e.g. BzrDirMeta1 with weave repository.  Also, it's more user-oriented.
    """

    def __init__(self):
        """Create a ControlDirFormatRegistry."""
        self._registration_order = []
        super().__init__()

    def register(
        self,
        key,
        factory,
        help,
        native=True,
        deprecated=False,
        hidden=False,
        experimental=False,
    ):
        """Register a ControlDirFormat factory.

        The factory must be a callable that takes one parameter: the key.
        It must produce an instance of the ControlDirFormat when called.

        This function mainly exists to prevent the info object from being
        supplied directly.
        """
        registry.Registry.register(
            self,
            key,
            factory,
            help,
            ControlDirFormatInfo(native, deprecated, hidden, experimental),
        )
        self._registration_order.append(key)

    def register_alias(self, key, target, hidden=False):
        """Register a format alias.

        Args:
          key: Alias name
          target: Target format
          hidden: Whether the alias is hidden
        """
        info = self.get_info(target)
        registry.Registry.register_alias(
            self,
            key,
            target,
            ControlDirFormatInfo(
                native=info.native,
                deprecated=info.deprecated,
                hidden=hidden,
                experimental=info.experimental,
            ),
        )

    def register_lazy(
        self,
        key,
        module_name,
        member_name,
        help,
        native=True,
        deprecated=False,
        hidden=False,
        experimental=False,
    ):
        registry.Registry.register_lazy(
            self,
            key,
            module_name,
            member_name,
            help,
            ControlDirFormatInfo(native, deprecated, hidden, experimental),
        )
        self._registration_order.append(key)

    def set_default(self, key):
        """Set the 'default' key to be a clone of the supplied key.

        This method must be called once and only once.
        """
        self.register_alias("default", key)

    def set_default_repository(self, key):
        """Set the FormatRegistry default and Repository default.

        This is a transitional method while Repository.set_default_format
        is deprecated.
        """
        if "default" in self:
            self.remove("default")
        self.set_default(key)
        self.get("default")()

    def make_controldir(self, key):
        return self.get(key)()

    def help_topic(self, topic):
        output = ""
        default_realkey = None
        default_help = self.get_help("default")
        help_pairs = []
        for key in self._registration_order:
            if key == "default":
                continue
            help = self.get_help(key)
            if help == default_help:
                default_realkey = key
            else:
                help_pairs.append((key, help))

        def wrapped(key, help, info):
            if info.native:
                help = "(native) " + help
            return ":{}:\n{}\n\n".format(
                key,
                textwrap.fill(
                    help,
                    initial_indent="    ",
                    subsequent_indent="    ",
                    break_long_words=False,
                ),
            )

        if default_realkey is not None:
            output += wrapped(
                default_realkey, f"(default) {default_help}", self.get_info("default")
            )
        deprecated_pairs = []
        experimental_pairs = []
        for key, help in help_pairs:
            info = self.get_info(key)
            if info.hidden:
                continue
            elif info.deprecated:
                deprecated_pairs.append((key, help))
            elif info.experimental:
                experimental_pairs.append((key, help))
            else:
                output += wrapped(key, help, info)
        output += "\nSee :doc:`formats-help` for more about storage formats."
        other_output = ""
        if len(experimental_pairs) > 0:
            other_output += "Experimental formats are shown below.\n\n"
            for key, help in experimental_pairs:
                info = self.get_info(key)
                other_output += wrapped(key, help, info)
        else:
            other_output += "No experimental formats are available.\n\n"
        if len(deprecated_pairs) > 0:
            other_output += "\nDeprecated formats are shown below.\n\n"
            for key, help in deprecated_pairs:
                info = self.get_info(key)
                other_output += wrapped(key, help, info)
        else:
            other_output += "\nNo deprecated formats are available.\n\n"
        other_output += "\nSee :doc:`formats-help` for more about storage formats."

        if topic == "other-formats":
            return other_output
        else:
            return output


class RepoInitHookParams:
    """Object holding parameters passed to ``*_repo_init`` hooks.

    There are 4 fields that hooks may wish to access:

    Attributes:
      repository: Repository created
      format: Repository format
      bzrdir: The controldir for the repository
      shared: The repository is shared
    """

    def __init__(self, repository, format, controldir, shared):
        """Create a group of RepoInitHook parameters.

        Args:
          repository: Repository created
          format: Repository format
          controldir: The controldir for the repository
          shared: The repository is shared
        """
        self.repository = repository
        self.format = format
        self.controldir = controldir
        self.shared = shared

    def __eq__(self, other):
        return self.__dict__ == other.__dict__

    def __repr__(self):
        if self.repository:
            return f"<{self.__class__.__name__} for {self.repository}>"
        else:
            return f"<{self.__class__.__name__} for {self.controldir}>"


def is_control_filename(filename):
    """Check if filename is used for control directories."""
    # TODO(jelmer): Instead, have a function that returns all control
    # filenames.
    for _key, format in format_registry.items():
        if format().is_control_filename(filename):
            return True
    else:
        return False


class RepositoryAcquisitionPolicy:
    """Abstract base class for repository acquisition policies.

    A repository acquisition policy decides how a ControlDir acquires a repository
    for a branch that is being created.  The most basic policy decision is
    whether to create a new repository or use an existing one.
    """

    def __init__(self, stack_on, stack_on_pwd, require_stacking):
        """Constructor.

        Args:
          stack_on: A location to stack on
          stack_on_pwd: If stack_on is relative, the location it is
            relative to.
          require_stacking: If True, it is a failure to not stack.
        """
        self._stack_on = stack_on
        self._stack_on_pwd = stack_on_pwd
        self._require_stacking = require_stacking

    def configure_branch(self, branch):
        """Apply any configuration data from this policy to the branch.

        Default implementation sets repository stacking.
        """
        if self._stack_on is None:
            return
        if self._stack_on_pwd is None:
            stack_on = self._stack_on
        else:
            try:
                stack_on = urlutils.rebase_url(
                    self._stack_on, self._stack_on_pwd, branch.user_url
                )
            except urlutils.InvalidRebaseURLs:
                stack_on = self._get_full_stack_on()
        try:
            branch.set_stacked_on_url(stack_on)
        except (
            _mod_branch.UnstackableBranchFormat,
            errors.UnstackableRepositoryFormat,
        ):
            if self._require_stacking:
                raise

    def requires_stacking(self):
        """Return True if this policy requires stacking."""
        return self._stack_on is not None and self._require_stacking

    def _get_full_stack_on(self):
        """Get a fully-qualified URL for the stack_on location."""
        if self._stack_on is None:
            return None
        if self._stack_on_pwd is None:
            return self._stack_on
        else:
            return urlutils.join(self._stack_on_pwd, self._stack_on)

    def _add_fallback(self, repository, possible_transports=None):
        """Add a fallback to the supplied repository, if stacking is set."""
        stack_on = self._get_full_stack_on()
        if stack_on is None:
            return
        try:
            stacked_dir = ControlDir.open(
                stack_on, possible_transports=possible_transports
            )
        except errors.JailBreak:
            # We keep the stacking details, but we are in the server code so
            # actually stacking is not needed.
            return
        try:
            stacked_repo = stacked_dir.open_branch().repository
        except errors.NotBranchError:
            stacked_repo = stacked_dir.open_repository()
        try:
            repository.add_fallback_repository(stacked_repo)
        except errors.UnstackableRepositoryFormat:
            if self._require_stacking:
                raise
        else:
            self._require_stacking = True

    def acquire_repository(
        self, make_working_trees=None, shared=False, possible_transports=None
    ):
        """Acquire a repository for this controlrdir.

        Implementations may create a new repository or use a pre-exising
        repository.

        Args:
          make_working_trees: If creating a repository, set
            make_working_trees to this value (if non-None)
          shared: If creating a repository, make it shared if True
        Returns:
          A repository, is_new_flag (True if the repository was created).
        """
        raise NotImplementedError(RepositoryAcquisitionPolicy.acquire_repository)


# Please register new formats after old formats so that formats
# appear in chronological order and format descriptions can build
# on previous ones.
format_registry = ControlDirFormatRegistry()

network_format_registry = registry.FormatRegistry[ControlDirFormat, None]()
"""Registry of formats indexed by their network name.

The network name for a ControlDirFormat is an identifier that can be used when
referring to formats with smart server operations. See
ControlDirFormat.network_name() for more detail.
"""
