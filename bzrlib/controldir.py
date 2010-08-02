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
from bzrlib import (
    errors,
    graph,
    revision as _mod_revision,
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

class ControlDir(object):
    """A control directory."""

    def can_convert_format(self):
        """Return true if this bzrdir is one whose format we can convert from."""
        return True

    def list_branches(self):
        """Return a sequence of all branches local to this control directory.

        """
        try:
            return [self.open_branch()]
        except (errors.NotBranchError, errors.NoRepositoryPresent):
            return []

    def is_control_filename(self, filename):
        """True if filename is the name of a path which is reserved for bzrdir's.

        :param filename: A filename within the root transport of this bzrdir.

        This is true IF and ONLY IF the filename is part of the namespace reserved
        for bzr control dirs. Currently this is the '.bzr' directory in the root
        of the root_transport. it is expected that plugins will need to extend
        this in the future - for instance to make bzr talk with svn working
        trees.
        """
        raise NotImplementedError(self.is_control_filename)

    def needs_format_conversion(self, format=None):
        """Return true if this bzrdir needs convert_format run on it.

        For instance, if the repository format is out of date but the
        branch and working tree are not, this should return True.

        :param format: Optional parameter indicating a specific desired
                       format we plan to arrive at.
        """
        raise NotImplementedError(self.needs_format_conversion)

    def destroy_repository(self):
        """Destroy the repository in this BzrDir"""
        raise NotImplementedError(self.destroy_repository)

    def create_branch(self, name=None):
        """Create a branch in this BzrDir.

        :param name: Name of the colocated branch to create, None for
            the default branch.

        The bzrdir's format will control what branch format is created.
        For more control see BranchFormatXX.create(a_bzrdir).
        """
        raise NotImplementedError(self.create_branch)

    def destroy_branch(self, name=None):
        """Destroy a branch in this BzrDir.

        :param name: Name of the branch to destroy, None for the default 
            branch.
        """
        raise NotImplementedError(self.destroy_branch)

    def create_workingtree(self, revision_id=None, from_branch=None,
        accelerator_tree=None, hardlink=False):
        """Create a working tree at this BzrDir.

        :param revision_id: create it as of this revision id.
        :param from_branch: override bzrdir branch (for lightweight checkouts)
        :param accelerator_tree: A tree which can be used for retrieving file
            contents more quickly than the revision tree, i.e. a workingtree.
            The revision tree will be used for cases where accelerator_tree's
            content is different.
        """
        raise NotImplementedError(self.create_workingtree)

    def destroy_workingtree(self):
        """Destroy the working tree at this BzrDir.

        Formats that do not support this may raise UnsupportedOperation.
        """
        raise NotImplementedError(self.destroy_workingtree)

    def destroy_workingtree_metadata(self):
        """Destroy the control files for the working tree at this BzrDir.

        The contents of working tree files are not affected.
        Formats that do not support this may raise UnsupportedOperation.
        """
        raise NotImplementedError(self.destroy_workingtree_metadata)

    def get_branch_reference(self, name=None):
        """Return the referenced URL for the branch in this bzrdir.

        :param name: Optional colocated branch name
        :raises NotBranchError: If there is no Branch.
        :raises NoColocatedBranchSupport: If a branch name was specified
            but colocated branches are not supported.
        :return: The URL the branch in this bzrdir references if it is a
            reference branch, or None for regular branches.
        """
        if name is not None:
            raise errors.NoColocatedBranchSupport(self)
        return None

    def get_branch_transport(self, branch_format, name=None):
        """Get the transport for use by branch format in this BzrDir.

        Note that bzr dirs that do not support format strings will raise
        IncompatibleFormat if the branch format they are given has
        a format string, and vice versa.

        If branch_format is None, the transport is returned with no
        checking. If it is not None, then the returned transport is
        guaranteed to point to an existing directory ready for use.
        """
        raise NotImplementedError(self.get_branch_transport)

    def get_repository_transport(self, repository_format):
        """Get the transport for use by repository format in this BzrDir.

        Note that bzr dirs that do not support format strings will raise
        IncompatibleFormat if the repository format they are given has
        a format string, and vice versa.

        If repository_format is None, the transport is returned with no
        checking. If it is not None, then the returned transport is
        guaranteed to point to an existing directory ready for use.
        """
        raise NotImplementedError(self.get_repository_transport)

    def get_workingtree_transport(self, tree_format):
        """Get the transport for use by workingtree format in this BzrDir.

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
        """Open the branch object at this BzrDir if one is present.

        If unsupported is True, then no longer supported branch formats can
        still be opened.

        TODO: static convenience version of this?
        """
        raise NotImplementedError(self.open_branch)

    def open_repository(self, _unsupported=False):
        """Open the repository object at this BzrDir if one is present.

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
        """Open the workingtree object at this BzrDir if one is present.

        :param recommend_upgrade: Optional keyword parameter, when True (the
            default), emit through the ui module a recommendation that the user
            upgrade the working tree when the workingtree being opened is old
            (but still fully supported).
        :param from_branch: override bzrdir branch (for lightweight checkouts)
        """
        raise NotImplementedError(self.open_workingtree)

    def has_branch(self, name=None):
        """Tell if this bzrdir contains a branch.

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
        """Tell if this bzrdir contains a working tree.

        This will still raise an exception if the bzrdir has a workingtree that
        is remote & inaccessible.

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
        :returns: a BzrDirFormat with all component formats either set
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
        """Create a copy of this bzrdir prepared for use as a new line of
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
        target_transport = get_transport(url, possible_transports)
        target_transport.ensure_base()
        cloning_format = self.cloning_metadir(stacked)
        # Create/update the result branch
        result = cloning_format.initialize_on_transport(target_transport)
        # if a stacked branch wasn't requested, we don't create one
        # even if the origin was stacked
        stacked_branch_url = None
        if source_branch is not None:
            if stacked:
                stacked_branch_url = self.root_transport.base
            source_repository = source_branch.repository
        else:
            try:
                source_branch = self.open_branch()
                source_repository = source_branch.repository
                if stacked:
                    stacked_branch_url = self.root_transport.base
            except errors.NotBranchError:
                source_branch = None
                try:
                    source_repository = self.open_repository()
                except errors.NoRepositoryPresent:
                    source_repository = None
        repository_policy = result.determine_repository_policy(
            force_new_repo, stacked_branch_url, require_stacking=stacked)
        result_repo, is_new_repo = repository_policy.acquire_repository()
        is_stacked = stacked or (len(result_repo._fallback_repositories) != 0)
        if is_new_repo and revision_id is not None and not is_stacked:
            fetch_spec = graph.PendingAncestryResult(
                [revision_id], source_repository)
        else:
            fetch_spec = None
        if source_repository is not None:
            # Fetch while stacked to prevent unstacked fetch from
            # Branch.sprout.
            if fetch_spec is None:
                result_repo.fetch(source_repository, revision_id=revision_id)
            else:
                result_repo.fetch(source_repository, fetch_spec=fetch_spec)

        if source_branch is None:
            # this is for sprouting a bzrdir without a branch; is that
            # actually useful?
            # Not especially, but it's part of the contract.
            result_branch = result.create_branch()
        else:
            result_branch = source_branch.sprout(result,
                revision_id=revision_id, repository_policy=repository_policy)
        mutter("created new branch %r" % (result_branch,))

        # Create/update the result working tree
        if (create_tree_if_local and
            isinstance(target_transport, local.LocalTransport) and
            (result_repo is None or result_repo.make_working_trees())):
            wt = result.create_workingtree(accelerator_tree=accelerator_tree,
                hardlink=hardlink)
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
            if wt is not None:
                basis = wt.basis_tree()
                basis.lock_read()
                subtrees = basis.iter_references()
            elif result_branch is not None:
                basis = result_branch.basis_tree()
                basis.lock_read()
                subtrees = basis.iter_references()
            elif source_branch is not None:
                basis = source_branch.basis_tree()
                basis.lock_read()
                subtrees = basis.iter_references()
            else:
                subtrees = []
                basis = None
            try:
                for path, file_id in subtrees:
                    target = urlutils.join(url, urlutils.escape(path))
                    sublocation = source_branch.reference_parent(file_id, path)
                    sublocation.bzrdir.sprout(target,
                        basis.get_reference_revision(file_id, path),
                        force_new_repo=force_new_repo, recurse=recurse,
                        stacked=stacked)
            finally:
                if basis is not None:
                    basis.unlock()
        return result

    def push_branch(self, source, revision_id=None, overwrite=False, 
        remember=False, create_prefix=False):
        """Push the source branch into this BzrDir."""
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


class ControlDirFormat(object):
    """An encapsulation of the initialization and open routines for a format.

    Formats provide three things:
     * An initialization routine,
     * a format string,
     * an open routine.

    Formats are placed in a dict by their format string for reference
    during bzrdir opening. These should be subclasses of BzrDirFormat
    for consistency.

    Once a format is deprecated, just deprecate the initialize and open
    methods on the format class. Do not deprecate the object, as the
    object will be created every system load.

    :cvar colocated_branches: Whether this formats supports colocated branches.
    """

    _default_format = None
    """The default format used for new .bzr dirs."""

    _formats = []
    """The registered control formats - .bzr, ....

    This is a list of ControlDirFormat objects.
    """

    _server_formats = []
    """The registered control server formats, e.g. RemoteBzrDirs.

    This is a list of ControlDirFormat objects.
    """

    colocated_branches = False
    """Whether co-located branches are supported for this control dir format.
    """

    def get_format_description(self):
        """Return the short description for this format."""
        raise NotImplementedError(self.get_format_description)

    def get_converter(self, format=None):
        """Return the converter to use to convert bzrdirs needing converts.

        This returns a bzrlib.bzrdir.Converter object.

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

        TODO: This should be pulled up into a 'ControlDirFormat' base class
        which BzrDirFormat can inherit from, and renamed to register_format
        there. It has been done without that for now for simplicity of
        implementation.
        """
        klass._formats.append(format)

    @classmethod
    def register_server_format(klass, format):
        """Register a control format for client-server environments.

        These formats will be tried before ones registered with
        register_control_format.  This gives implementations that decide to the
        chance to grab it before anything looks at the contents of the format
        file.
        """
        klass._server_formats.append(format)

    def __str__(self):
        # Trim the newline
        return self.get_format_description().rstrip()

    @classmethod
    def unregister_format(klass, format):
        klass._formats.remove(format)

    @classmethod
    def known_formats(klass):
        """Return all the known formats.

        Concrete formats should override _known_formats.
        """
        # There is double indirection here to make sure that control
        # formats used by more than one dir format will only be probed
        # once. This can otherwise be quite expensive for remote connections.
        result = set()
        for format in klass._formats:
            result.update(format._known_formats())
        return result

    @classmethod
    def find_format(klass, transport, _server_formats=True):
        """Return the format present at transport."""
        if _server_formats:
            formats = klass._server_formats + klass._formats
        else:
            formats = klass._formats
        for format in formats:
            try:
                return format.probe_transport(transport)
            except errors.NotBranchError:
                # this format does not find a control dir here.
                pass
        raise errors.NotBranchError(path=transport.base)


