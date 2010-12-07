# Copyright (C) 2010 Canonical Ltd
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

"""ControlDir is the basic control directory class.

The ControlDir class is the base for the control directory used
by all bzr and foreign formats. For the ".bzr" implementation,
see bzrlib.bzrdir.BzrDir.

"""

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
import textwrap

from bzrlib import (
    cleanup,
    errors,
    graph,
    registry,
    repository,
    revision as _mod_revision,
    symbol_versioning,
    urlutils,
    )
from bzrlib.push import (
    PushResult,
    )
from bzrlib.trace import (
    mutter,
    )
from bzrlib.transport import (
    get_transport,
    local,
    )

""")


class ControlComponent(object):
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
    def control_transport(self):
        raise NotImplementedError

    @property
    def control_url(self):
        return self.control_transport.base

    @property
    def user_transport(self):
        raise NotImplementedError

    @property
    def user_url(self):
        return self.user_transport.base


class _TargetRepoKinds(object):
    """An enum-like set of constants."""
    
    PREEXISTING = 'preexisting'
    STACKED = 'stacked'
    EMPTY = 'empty'


class FetchSpecFactory(object):
    """A helper for building the best fetch spec for a sprout call.

    Factors that go into determining the sort of fetch to perform:
     * did the caller specify any revision IDs?
     * did the caller specify a source branch (need to fetch the tip + tags)
     * is there an existing target repo (don't need to refetch revs it
       already has)
     * target is stacked?  (similar to pre-existing target repo: even if
       the target itself is new don't want to refetch existing revs)

    :ivar source_branch: the source branch if one specified, else None.
    :ivar source_branch_stop_revision: fetch up to this revision of
        source_branch, rather than its tip.
    :ivar source_repo: the source repository if one found, else None.
    :ivar target_repo: the target repository acquired by sprout.
    :ivar target_repo_kind: one of the _TargetRepoKinds constants.
    """

    def __init__(self):
        self.explicit_rev_ids = set()
        self.source_branch = None
        self.source_branch_stop_revision = None
        self.source_repo = None
        self.target_repo = None
        self.target_repo_kind = None

    def add_revision_ids(self, revision_ids):
        """Add revision_ids to the set of revision_ids to be fetched."""
        self.explicit_rev_ids.update(revision_ids)
        
    def make_fetch_spec(self):
        """Build a SearchResult or PendingAncestryResult or etc."""
        if self.target_repo_kind is None or self.source_repo is None:
            raise AssertionError(
                'Incomplete FetchSpecFactory: %r' % (self.__dict__,))
        if len(self.explicit_rev_ids) == 0 and self.source_branch is None:
            # Caller hasn't specified any revisions or source branch
            if self.target_repo_kind == _TargetRepoKinds.EMPTY:
                return graph.EverythingResult(self.source_repo)
            else:
                # We want everything not already in the target (or target's
                # fallbacks).
                return graph.EverythingNotInOther(
                    self.target_repo, self.source_repo)
        heads_to_fetch = set(self.explicit_rev_ids)
        tags_to_fetch = set()
        if self.source_branch is not None:
            try:
                tags_to_fetch.update(
                    self.source_branch.tags.get_reverse_tag_dict())
            except errors.TagsNotSupported:
                pass
            if self.source_branch_stop_revision is not None:
                heads_to_fetch.add(self.source_branch_stop_revision)
            else:
                heads_to_fetch.add(self.source_branch.last_revision())
        if self.target_repo_kind == _TargetRepoKinds.EMPTY:
            # PendingAncestryResult does not raise errors if a requested head
            # is absent.  Ideally it would support the
            # required_ids/if_present_ids distinction, but in practice
            # heads_to_fetch will almost certainly be present so this doesn't
            # matter much.
            all_heads = heads_to_fetch.union(tags_to_fetch)
            return graph.PendingAncestryResult(all_heads, self.source_repo)
        return graph.NotInOtherForRevs(self.target_repo, self.source_repo,
            required_ids=heads_to_fetch, if_present_ids=tags_to_fetch)


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

    def can_convert_format(self):
        """Return true if this controldir is one whose format we can convert
        from."""
        return True

    def list_branches(self):
        """Return a sequence of all branches local to this control directory.

        """
        try:
            return [self.open_branch()]
        except (errors.NotBranchError, errors.NoRepositoryPresent):
            return []

    def is_control_filename(self, filename):
        """True if filename is the name of a path which is reserved for
        controldirs.

        :param filename: A filename within the root transport of this
            controldir.

        This is true IF and ONLY IF the filename is part of the namespace reserved
        for bzr control dirs. Currently this is the '.bzr' directory in the root
        of the root_transport. it is expected that plugins will need to extend
        this in the future - for instance to make bzr talk with svn working
        trees.
        """
        raise NotImplementedError(self.is_control_filename)

    def needs_format_conversion(self, format=None):
        """Return true if this controldir needs convert_format run on it.

        For instance, if the repository format is out of date but the
        branch and working tree are not, this should return True.

        :param format: Optional parameter indicating a specific desired
                       format we plan to arrive at.
        """
        raise NotImplementedError(self.needs_format_conversion)

    def destroy_repository(self):
        """Destroy the repository in this ControlDir."""
        raise NotImplementedError(self.destroy_repository)

    def create_branch(self, name=None, repository=None):
        """Create a branch in this ControlDir.

        :param name: Name of the colocated branch to create, None for
            the default branch.

        The controldirs format will control what branch format is created.
        For more control see BranchFormatXX.create(a_controldir).
        """
        raise NotImplementedError(self.create_branch)

    def destroy_branch(self, name=None):
        """Destroy a branch in this ControlDir.

        :param name: Name of the branch to destroy, None for the default 
            branch.
        """
        raise NotImplementedError(self.destroy_branch)

    def create_workingtree(self, revision_id=None, from_branch=None,
        accelerator_tree=None, hardlink=False):
        """Create a working tree at this ControlDir.

        :param revision_id: create it as of this revision id.
        :param from_branch: override controldir branch 
            (for lightweight checkouts)
        :param accelerator_tree: A tree which can be used for retrieving file
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

    def get_branch_reference(self, name=None):
        """Return the referenced URL for the branch in this controldir.

        :param name: Optional colocated branch name
        :raises NotBranchError: If there is no Branch.
        :raises NoColocatedBranchSupport: If a branch name was specified
            but colocated branches are not supported.
        :return: The URL the branch in this controldir references if it is a
            reference branch, or None for regular branches.
        """
        if name is not None:
            raise errors.NoColocatedBranchSupport(self)
        return None

    def get_branch_transport(self, branch_format, name=None):
        """Get the transport for use by branch format in this ControlDir.

        Note that bzr dirs that do not support format strings will raise
        IncompatibleFormat if the branch format they are given has
        a format string, and vice versa.

        If branch_format is None, the transport is returned with no
        checking. If it is not None, then the returned transport is
        guaranteed to point to an existing directory ready for use.
        """
        raise NotImplementedError(self.get_branch_transport)

    def get_repository_transport(self, repository_format):
        """Get the transport for use by repository format in this ControlDir.

        Note that bzr dirs that do not support format strings will raise
        IncompatibleFormat if the repository format they are given has
        a format string, and vice versa.

        If repository_format is None, the transport is returned with no
        checking. If it is not None, then the returned transport is
        guaranteed to point to an existing directory ready for use.
        """
        raise NotImplementedError(self.get_repository_transport)

    def get_workingtree_transport(self, tree_format):
        """Get the transport for use by workingtree format in this ControlDir.

        Note that bzr dirs that do not support format strings will raise
        IncompatibleFormat if the workingtree format they are given has a
        format string, and vice versa.

        If workingtree_format is None, the transport is returned with no
        checking. If it is not None, then the returned transport is
        guaranteed to point to an existing directory ready for use.
        """
        raise NotImplementedError(self.get_workingtree_transport)

    def open_branch(self, name=None, unsupported=False,
                    ignore_fallbacks=False):
        """Open the branch object at this ControlDir if one is present.

        If unsupported is True, then no longer supported branch formats can
        still be opened.

        TODO: static convenience version of this?
        """
        raise NotImplementedError(self.open_branch)

    def open_repository(self, _unsupported=False):
        """Open the repository object at this ControlDir if one is present.

        This will not follow the Branch object pointer - it's strictly a direct
        open facility. Most client code should use open_branch().repository to
        get at a repository.

        :param _unsupported: a private parameter, not part of the api.
        TODO: static convenience version of this?
        """
        raise NotImplementedError(self.open_repository)

    def find_repository(self):
        """Find the repository that should be used.

        This does not require a branch as we use it to find the repo for
        new branches as well as to hook existing branches up to their
        repository.
        """
        raise NotImplementedError(self.find_repository)

    def open_workingtree(self, _unsupported=False,
                         recommend_upgrade=True, from_branch=None):
        """Open the workingtree object at this ControlDir if one is present.

        :param recommend_upgrade: Optional keyword parameter, when True (the
            default), emit through the ui module a recommendation that the user
            upgrade the working tree when the workingtree being opened is old
            (but still fully supported).
        :param from_branch: override controldir branch (for lightweight
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
            self.open_branch(name)
            return True
        except errors.NotBranchError:
            return False

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
        """Produce a metadir suitable for checkouts of this controldir."""
        return self.cloning_metadir()

    def sprout(self, url, revision_id=None, force_new_repo=False,
               recurse='down', possible_transports=None,
               accelerator_tree=None, hardlink=False, stacked=False,
               source_branch=None, create_tree_if_local=True):
        """Create a copy of this controldir prepared for use as a new line of
        development.

        If url's last component does not exist, it will be created.

        Attributes related to the identity of the source branch like
        branch nickname will be cleaned, a working tree is created
        whether one existed before or not; and a local branch is always
        created.

        if revision_id is not None, then the clone operation may tune
            itself to download less data.
        :param accelerator_tree: A tree which can be used for retrieving file
            contents more quickly than the revision tree, i.e. a workingtree.
            The revision tree will be used for cases where accelerator_tree's
            content is different.
        :param hardlink: If true, hard-link files from accelerator_tree,
            where possible.
        :param stacked: If true, create a stacked branch referring to the
            location of this control directory.
        :param create_tree_if_local: If true, a working-tree will be created
            when working locally.
        """
        operation = cleanup.OperationWithCleanups(self._sprout)
        return operation.run(url, revision_id=revision_id,
            force_new_repo=force_new_repo, recurse=recurse,
            possible_transports=possible_transports,
            accelerator_tree=accelerator_tree, hardlink=hardlink,
            stacked=stacked, source_branch=source_branch,
            create_tree_if_local=create_tree_if_local)

    def _sprout(self, op, url, revision_id=None, force_new_repo=False,
               recurse='down', possible_transports=None,
               accelerator_tree=None, hardlink=False, stacked=False,
               source_branch=None, create_tree_if_local=True):
        add_cleanup = op.add_cleanup
        fetch_spec_factory = FetchSpecFactory()
        if revision_id is not None:
            fetch_spec_factory.add_revision_ids([revision_id])
            fetch_spec_factory.source_branch_stop_revision = revision_id
        target_transport = get_transport(url, possible_transports)
        target_transport.ensure_base()
        cloning_format = self.cloning_metadir(stacked)
        # Create/update the result branch
        result = cloning_format.initialize_on_transport(target_transport)
        source_branch, source_repository = self._find_source_repo(
            add_cleanup, source_branch)
        fetch_spec_factory.source_branch = source_branch
        # if a stacked branch wasn't requested, we don't create one
        # even if the origin was stacked
        if stacked and source_branch is not None:
            stacked_branch_url = self.root_transport.base
        else:
            stacked_branch_url = None
        repository_policy = result.determine_repository_policy(
            force_new_repo, stacked_branch_url, require_stacking=stacked)
        result_repo, is_new_repo = repository_policy.acquire_repository()
        add_cleanup(result_repo.lock_write().unlock)
        fetch_spec_factory.source_repo = source_repository
        fetch_spec_factory.target_repo = result_repo
        if stacked or (len(result_repo._fallback_repositories) != 0):
            fetch_spec_factory.target_repo_kind = _TargetRepoKinds.STACKED
        elif is_new_repo:
            fetch_spec_factory.target_repo_kind = _TargetRepoKinds.EMPTY
        else:
            fetch_spec_factory.target_repo_kind = _TargetRepoKinds.PREEXISTING
        if source_repository is not None:
            fetch_spec = fetch_spec_factory.make_fetch_spec()
            result_repo.fetch(source_repository, fetch_spec=fetch_spec)

        if source_branch is None:
            # this is for sprouting a controldir without a branch; is that
            # actually useful?
            # Not especially, but it's part of the contract.
            result_branch = result.create_branch()
        else:
            result_branch = source_branch.sprout(result,
                revision_id=revision_id, repository_policy=repository_policy,
                repository=result_repo)
        mutter("created new branch %r" % (result_branch,))

        # Create/update the result working tree
        if (create_tree_if_local and
            isinstance(target_transport, local.LocalTransport) and
            (result_repo is None or result_repo.make_working_trees())):
            wt = result.create_workingtree(accelerator_tree=accelerator_tree,
                hardlink=hardlink, from_branch=result_branch)
            wt.lock_write()
            try:
                if wt.path2id('') is None:
                    try:
                        wt.set_root_id(self.open_workingtree.get_root_id())
                    except errors.NoWorkingTree:
                        pass
            finally:
                wt.unlock()
        else:
            wt = None
        if recurse == 'down':
            basis = None
            if wt is not None:
                basis = wt.basis_tree()
            elif result_branch is not None:
                basis = result_branch.basis_tree()
            elif source_branch is not None:
                basis = source_branch.basis_tree()
            if basis is not None:
                add_cleanup(basis.lock_read().unlock)
                subtrees = basis.iter_references()
            else:
                subtrees = []
            for path, file_id in subtrees:
                target = urlutils.join(url, urlutils.escape(path))
                sublocation = source_branch.reference_parent(file_id, path)
                sublocation.bzrdir.sprout(target,
                    basis.get_reference_revision(file_id, path),
                    force_new_repo=force_new_repo, recurse=recurse,
                    stacked=stacked)
        return result

    def _find_source_repo(self, add_cleanup, source_branch):
        """Find the source branch and repo for a sprout operation.
        
        This is helper intended for use by _sprout.

        :returns: (source_branch, source_repository).  Either or both may be
            None.  If not None, they will be read-locked (and their unlock(s)
            scheduled via the add_cleanup param).
        """
        if source_branch is not None:
            add_cleanup(source_branch.lock_read().unlock)
            return source_branch, source_branch.repository
        try:
            source_branch = self.open_branch()
            source_repository = source_branch.repository
        except errors.NotBranchError:
            source_branch = None
            try:
                source_repository = self.open_repository()
            except errors.NoRepositoryPresent:
                source_repository = None
            else:
                add_cleanup(source_repository.lock_read().unlock)
        else:
            add_cleanup(source_branch.lock_read().unlock)
        return source_branch, source_repository

    def push_branch(self, source, revision_id=None, overwrite=False, 
        remember=False, create_prefix=False):
        """Push the source branch into this ControlDir."""
        br_to = None
        # If we can open a branch, use its direct repository, otherwise see
        # if there is a repository without a branch.
        try:
            br_to = self.open_branch()
        except errors.NotBranchError:
            # Didn't find a branch, can we find a repository?
            repository_to = self.find_repository()
        else:
            # Found a branch, so we must have found a repository
            repository_to = br_to.repository

        push_result = PushResult()
        push_result.source_branch = source
        if br_to is None:
            # We have a repository but no branch, copy the revisions, and then
            # create a branch.
            repository_to.fetch(source.repository, revision_id=revision_id)
            br_to = source.clone(self, revision_id=revision_id)
            if source.get_push_location() is None or remember:
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
                source.set_push_location(br_to.base)
            try:
                tree_to = self.open_workingtree()
            except errors.NotLocalUrl:
                push_result.branch_push_result = source.push(br_to, 
                    overwrite, stop_revision=revision_id)
                push_result.workingtree_updated = False
            except errors.NoWorkingTree:
                push_result.branch_push_result = source.push(br_to,
                    overwrite, stop_revision=revision_id)
                push_result.workingtree_updated = None # Not applicable
            else:
                tree_to.lock_write()
                try:
                    push_result.branch_push_result = source.push(
                        tree_to.branch, overwrite, stop_revision=revision_id)
                    tree_to.update()
                finally:
                    tree_to.unlock()
                push_result.workingtree_updated = True
            push_result.old_revno = push_result.branch_push_result.old_revno
            push_result.old_revid = push_result.branch_push_result.old_revid
            push_result.target_branch = \
                push_result.branch_push_result.target_branch
        return push_result

    def _get_tree_branch(self, name=None):
        """Return the branch and tree, if any, for this bzrdir.

        :param name: Name of colocated branch to open.

        Return None for tree if not present or inaccessible.
        Raise NotBranchError if no branch is present.
        :return: (tree, branch)
        """
        try:
            tree = self.open_workingtree()
        except (errors.NoWorkingTree, errors.NotLocalUrl):
            tree = None
            branch = self.open_branch(name=name)
        else:
            if name is not None:
                branch = self.open_branch(name=name)
            else:
                branch = tree.branch
        return tree, branch

    def get_config(self):
        """Get configuration for this ControlDir."""
        raise NotImplementedError(self.get_config)

    def check_conversion_target(self, target_format):
        """Check that a bzrdir as a whole can be converted to a new format."""
        raise NotImplementedError(self.check_conversion_target)

    def clone(self, url, revision_id=None, force_new_repo=False,
              preserve_stacking=False):
        """Clone this bzrdir and its contents to url verbatim.

        :param url: The url create the clone at.  If url's last component does
            not exist, it will be created.
        :param revision_id: The tip revision-id to use for any branch or
            working tree.  If not None, then the clone operation may tune
            itself to download less data.
        :param force_new_repo: Do not use a shared repository for the target
                               even if one is available.
        :param preserve_stacking: When cloning a stacked branch, stack the
            new branch on top of the other branch's stacked-on branch.
        """
        return self.clone_on_transport(get_transport(url),
                                       revision_id=revision_id,
                                       force_new_repo=force_new_repo,
                                       preserve_stacking=preserve_stacking)

    def clone_on_transport(self, transport, revision_id=None,
        force_new_repo=False, preserve_stacking=False, stacked_on=None,
        create_prefix=False, use_existing_dir=True):
        """Clone this bzrdir and its contents to transport verbatim.

        :param transport: The transport for the location to produce the clone
            at.  If the target directory does not exist, it will be created.
        :param revision_id: The tip revision-id to use for any branch or
            working tree.  If not None, then the clone operation may tune
            itself to download less data.
        :param force_new_repo: Do not use a shared repository for the target,
                               even if one is available.
        :param preserve_stacking: When cloning a stacked branch, stack the
            new branch on top of the other branch's stacked-on branch.
        :param create_prefix: Create any missing directories leading up to
            to_transport.
        :param use_existing_dir: Use an existing directory if one exists.
        """
        raise NotImplementedError(self.clone_on_transport)


class ControlDirFormat(object):
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

    :cvar colocated_branches: Whether this formats supports colocated branches.
    :cvar supports_workingtrees: This control directory can co-exist with a
        working tree.
    """

    _default_format = None
    """The default format used for new control directories."""

    _formats = []
    """The registered control formats - .bzr, ....

    This is a list of ControlDirFormat objects.
    """

    _server_probers = []
    """The registered server format probers, e.g. RemoteBzrProber.

    This is a list of Prober-derived classes.
    """

    _probers = []
    """The registered format probers, e.g. BzrProber.

    This is a list of Prober-derived classes.
    """

    colocated_branches = False
    """Whether co-located branches are supported for this control dir format.
    """

    supports_workingtrees = True

    def get_format_description(self):
        """Return the short description for this format."""
        raise NotImplementedError(self.get_format_description)

    def get_converter(self, format=None):
        """Return the converter to use to convert controldirs needing converts.

        This returns a bzrlib.controldir.Converter object.

        This should return the best upgrader to step this format towards the
        current default format. In the case of plugins we can/should provide
        some means for them to extend the range of returnable converters.

        :param format: Optional format to override the default format of the
                       library.
        """
        raise NotImplementedError(self.get_converter)

    def is_supported(self):
        """Is this format supported?

        Supported formats must be initializable and openable.
        Unsupported formats may not support initialization or committing or
        some other features depending on the reason for not being supported.
        """
        return True

    def same_model(self, target_format):
        return (self.repository_format.rich_root_data ==
            target_format.rich_root_data)

    @classmethod
    def register_format(klass, format):
        """Register a format that does not use '.bzr' for its control dir.

        """
        klass._formats.append(format)

    @classmethod
    def register_prober(klass, prober):
        """Register a prober that can look for a control dir.

        """
        klass._probers.append(prober)

    @classmethod
    def unregister_prober(klass, prober):
        """Unregister a prober.

        """
        klass._probers.remove(prober)

    @classmethod
    def register_server_prober(klass, prober):
        """Register a control format prober for client-server environments.

        These probers will be used before ones registered with
        register_prober.  This gives implementations that decide to the
        chance to grab it before anything looks at the contents of the format
        file.
        """
        klass._server_probers.append(prober)

    def __str__(self):
        # Trim the newline
        return self.get_format_description().rstrip()

    @classmethod
    def unregister_format(klass, format):
        klass._formats.remove(format)

    @classmethod
    def known_formats(klass):
        """Return all the known formats.
        """
        return set(klass._formats)

    @classmethod
    def find_format(klass, transport, _server_formats=True):
        """Return the format present at transport."""
        if _server_formats:
            _probers = klass._server_probers + klass._probers
        else:
            _probers = klass._probers
        for prober_kls in _probers:
            prober = prober_kls()
            try:
                return prober.probe_transport(transport)
            except errors.NotBranchError:
                # this format does not find a control dir here.
                pass
        raise errors.NotBranchError(path=transport.base)

    def initialize(self, url, possible_transports=None):
        """Create a control dir at this url and return an opened copy.

        While not deprecated, this method is very specific and its use will
        lead to many round trips to setup a working environment. See
        initialize_on_transport_ex for a [nearly] all-in-one method.

        Subclasses should typically override initialize_on_transport
        instead of this method.
        """
        return self.initialize_on_transport(get_transport(url,
                                                          possible_transports))
    def initialize_on_transport(self, transport):
        """Initialize a new controldir in the base directory of a Transport."""
        raise NotImplementedError(self.initialize_on_transport)

    def initialize_on_transport_ex(self, transport, use_existing_dir=False,
        create_prefix=False, force_new_repo=False, stacked_on=None,
        stack_on_pwd=None, repo_format_name=None, make_working_trees=None,
        shared_repo=False, vfs_only=False):
        """Create this format on transport.

        The directory to initialize will be created.

        :param force_new_repo: Do not use a shared repository for the target,
                               even if one is available.
        :param create_prefix: Create any missing directories leading up to
            to_transport.
        :param use_existing_dir: Use an existing directory if one exists.
        :param stacked_on: A url to stack any created branch on, None to follow
            any target stacking policy.
        :param stack_on_pwd: If stack_on is relative, the location it is
            relative to.
        :param repo_format_name: If non-None, a repository will be
            made-or-found. Should none be found, or if force_new_repo is True
            the repo_format_name is used to select the format of repository to
            create.
        :param make_working_trees: Control the setting of make_working_trees
            for a new shared repository when one is made. None to use whatever
            default the format has.
        :param shared_repo: Control whether made repositories are shared or
            not.
        :param vfs_only: If True do not attempt to use a smart server
        :return: repo, controldir, require_stacking, repository_policy. repo is
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

    def open(self, transport, _found=False):
        """Return an instance of this format for the dir transport points at.
        """
        raise NotImplementedError(self.open)

    @classmethod
    def _set_default_format(klass, format):
        """Set default format (for testing behavior of defaults only)"""
        klass._default_format = format

    @classmethod
    def get_default_format(klass):
        """Return the current default format."""
        return klass._default_format


class Prober(object):
    """Abstract class that can be used to detect a particular kind of 
    control directory.

    At the moment this just contains a single method to probe a particular 
    transport, but it may be extended in the future to e.g. avoid 
    multiple levels of probing for Subversion repositories.
    """

    def probe_transport(self, transport):
        """Return the controldir style format present in a directory.

        :raise UnknownFormatError: If a control dir was found but is
            in an unknown format.
        :raise NotBranchError: If no control directory was found.
        :return: A ControlDirFormat instance.
        """
        raise NotImplementedError(self.probe_transport)


class ControlDirFormatInfo(object):

    def __init__(self, native, deprecated, hidden, experimental):
        self.deprecated = deprecated
        self.native = native
        self.hidden = hidden
        self.experimental = experimental


class ControlDirFormatRegistry(registry.Registry):
    """Registry of user-selectable ControlDir subformats.

    Differs from ControlDirFormat._formats in that it provides sub-formats,
    e.g. ControlDirMeta1 with weave repository.  Also, it's more user-oriented.
    """

    def __init__(self):
        """Create a ControlDirFormatRegistry."""
        self._aliases = set()
        self._registration_order = list()
        super(ControlDirFormatRegistry, self).__init__()

    def aliases(self):
        """Return a set of the format names which are aliases."""
        return frozenset(self._aliases)

    def register(self, key, factory, help, native=True, deprecated=False,
                 hidden=False, experimental=False, alias=False):
        """Register a ControlDirFormat factory.

        The factory must be a callable that takes one parameter: the key.
        It must produce an instance of the ControlDirFormat when called.

        This function mainly exists to prevent the info object from being
        supplied directly.
        """
        registry.Registry.register(self, key, factory, help,
            ControlDirFormatInfo(native, deprecated, hidden, experimental))
        if alias:
            self._aliases.add(key)
        self._registration_order.append(key)

    def register_lazy(self, key, module_name, member_name, help, native=True,
        deprecated=False, hidden=False, experimental=False, alias=False):
        registry.Registry.register_lazy(self, key, module_name, member_name,
            help, ControlDirFormatInfo(native, deprecated, hidden, experimental))
        if alias:
            self._aliases.add(key)
        self._registration_order.append(key)

    def set_default(self, key):
        """Set the 'default' key to be a clone of the supplied key.

        This method must be called once and only once.
        """
        registry.Registry.register(self, 'default', self.get(key),
            self.get_help(key), info=self.get_info(key))
        self._aliases.add('default')

    def set_default_repository(self, key):
        """Set the FormatRegistry default and Repository default.

        This is a transitional method while Repository.set_default_format
        is deprecated.
        """
        if 'default' in self:
            self.remove('default')
        self.set_default(key)
        format = self.get('default')()

    def make_bzrdir(self, key):
        return self.get(key)()

    def help_topic(self, topic):
        output = ""
        default_realkey = None
        default_help = self.get_help('default')
        help_pairs = []
        for key in self._registration_order:
            if key == 'default':
                continue
            help = self.get_help(key)
            if help == default_help:
                default_realkey = key
            else:
                help_pairs.append((key, help))

        def wrapped(key, help, info):
            if info.native:
                help = '(native) ' + help
            return ':%s:\n%s\n\n' % (key,
                textwrap.fill(help, initial_indent='    ',
                    subsequent_indent='    ',
                    break_long_words=False))
        if default_realkey is not None:
            output += wrapped(default_realkey, '(default) %s' % default_help,
                              self.get_info('default'))
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
            other_output += \
                "No experimental formats are available.\n\n"
        if len(deprecated_pairs) > 0:
            other_output += "\nDeprecated formats are shown below.\n\n"
            for key, help in deprecated_pairs:
                info = self.get_info(key)
                other_output += wrapped(key, help, info)
        else:
            other_output += \
                "\nNo deprecated formats are available.\n\n"
        other_output += \
                "\nSee :doc:`formats-help` for more about storage formats."

        if topic == 'other-formats':
            return other_output
        else:
            return output


# Please register new formats after old formats so that formats
# appear in chronological order and format descriptions can build
# on previous ones.
format_registry = ControlDirFormatRegistry()

network_format_registry = registry.FormatRegistry()
"""Registry of formats indexed by their network name.

The network name for a ControlDirFormat is an identifier that can be used when
referring to formats with smart server operations. See
ControlDirFormat.network_name() for more detail.
"""
