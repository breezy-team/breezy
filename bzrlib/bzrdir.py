# Copyright (C) 2005, 2006, 2007, 2008 Canonical Ltd
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""BzrDir logic. The BzrDir is the basic control directory used by bzr.

At format 7 this was split out into Branch, Repository and Checkout control
directories.

Note: This module has a lot of ``open`` functions/methods that return
references to in-memory objects. As a rule, there are no matching ``close``
methods. To free any associated resources, simply stop referencing the
objects returned.
"""

# TODO: Move old formats into a plugin to make this file smaller.

from cStringIO import StringIO
import os
import sys

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
from stat import S_ISDIR
import textwrap
from warnings import warn

import bzrlib
from bzrlib import (
    config,
    errors,
    graph,
    lockable_files,
    lockdir,
    osutils,
    registry,
    remote,
    revision as _mod_revision,
    symbol_versioning,
    ui,
    urlutils,
    versionedfile,
    win32utils,
    workingtree,
    workingtree_4,
    xml4,
    xml5,
    )
from bzrlib.osutils import (
    sha_strings,
    sha_string,
    )
from bzrlib.repository import Repository
from bzrlib.smart.client import _SmartClient
from bzrlib.smart import protocol
from bzrlib.store.versioned import WeaveStore
from bzrlib.transactions import WriteTransaction
from bzrlib.transport import (
    do_catching_redirections,
    get_transport,
    )
from bzrlib.weave import Weave
""")

from bzrlib.trace import (
    mutter,
    note,
    )
from bzrlib.transport.local import LocalTransport
from bzrlib.symbol_versioning import (
    deprecated_function,
    deprecated_method,
    )


class BzrDir(object):
    """A .bzr control diretory.
    
    BzrDir instances let you create or open any of the things that can be
    found within .bzr - checkouts, branches and repositories.
    
    :ivar transport:
        the transport which this bzr dir is rooted at (i.e. file:///.../.bzr/)
    :ivar root_transport:
        a transport connected to the directory this bzr was opened from
        (i.e. the parent directory holding the .bzr directory).

    Everything in the bzrdir should have the same file permissions.
    """

    def break_lock(self):
        """Invoke break_lock on the first object in the bzrdir.

        If there is a tree, the tree is opened and break_lock() called.
        Otherwise, branch is tried, and finally repository.
        """
        # XXX: This seems more like a UI function than something that really
        # belongs in this class.
        try:
            thing_to_unlock = self.open_workingtree()
        except (errors.NotLocalUrl, errors.NoWorkingTree):
            try:
                thing_to_unlock = self.open_branch()
            except errors.NotBranchError:
                try:
                    thing_to_unlock = self.open_repository()
                except errors.NoRepositoryPresent:
                    return
        thing_to_unlock.break_lock()

    def can_convert_format(self):
        """Return true if this bzrdir is one whose format we can convert from."""
        return True

    def check_conversion_target(self, target_format):
        target_repo_format = target_format.repository_format
        source_repo_format = self._format.repository_format
        source_repo_format.check_conversion_target(target_repo_format)

    @staticmethod
    def _check_supported(format, allow_unsupported,
        recommend_upgrade=True,
        basedir=None):
        """Give an error or warning on old formats.

        :param format: may be any kind of format - workingtree, branch, 
        or repository.

        :param allow_unsupported: If true, allow opening 
        formats that are strongly deprecated, and which may 
        have limited functionality.

        :param recommend_upgrade: If true (default), warn
        the user through the ui object that they may wish
        to upgrade the object.
        """
        # TODO: perhaps move this into a base Format class; it's not BzrDir
        # specific. mbp 20070323
        if not allow_unsupported and not format.is_supported():
            # see open_downlevel to open legacy branches.
            raise errors.UnsupportedFormatError(format=format)
        if recommend_upgrade \
            and getattr(format, 'upgrade_recommended', False):
            ui.ui_factory.recommend_upgrade(
                format.get_format_description(),
                basedir)

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
                           force_new_repo=False, preserve_stacking=False):
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
        """
        transport.ensure_base()
        result = self.cloning_metadir().initialize_on_transport(transport)
        repository_policy = None
        stack_on = None
        try:
            local_repo = self.find_repository()
        except errors.NoRepositoryPresent:
            local_repo = None
        try:
            local_branch = self.open_branch()
        except errors.NotBranchError:
            local_branch = None
        else:
            # enable fallbacks when branch is not a branch reference
            if local_branch.repository.has_same_location(local_repo):
                local_repo = local_branch.repository
            if preserve_stacking:
                try:
                    stack_on = local_branch.get_stacked_on_url()
                except (errors.UnstackableBranchFormat,
                        errors.UnstackableRepositoryFormat,
                        errors.NotStacked):
                    pass

        if local_repo:
            # may need to copy content in
            repository_policy = result.determine_repository_policy(
                force_new_repo, stack_on, self.root_transport.base)
            make_working_trees = local_repo.make_working_trees()
            result_repo = repository_policy.acquire_repository(
                make_working_trees, local_repo.is_shared())
            result_repo.fetch(local_repo, revision_id=revision_id)
        else:
            result_repo = None
        # 1 if there is a branch present
        #   make sure its content is available in the target repository
        #   clone it.
        if local_branch is not None:
            result_branch = local_branch.clone(result, revision_id=revision_id)
            if repository_policy is not None:
                repository_policy.configure_branch(result_branch)
        if result_repo is None or result_repo.make_working_trees():
            try:
                self.open_workingtree().clone(result)
            except (errors.NoWorkingTree, errors.NotLocalUrl):
                pass
        return result

    # TODO: This should be given a Transport, and should chdir up; otherwise
    # this will open a new connection.
    def _make_tail(self, url):
        t = get_transport(url)
        t.ensure_base()

    @classmethod
    def create(cls, base, format=None, possible_transports=None):
        """Create a new BzrDir at the url 'base'.
        
        :param format: If supplied, the format of branch to create.  If not
            supplied, the default is used.
        :param possible_transports: If supplied, a list of transports that 
            can be reused to share a remote connection.
        """
        if cls is not BzrDir:
            raise AssertionError("BzrDir.create always creates the default"
                " format, not one of %r" % cls)
        t = get_transport(base, possible_transports)
        t.ensure_base()
        if format is None:
            format = BzrDirFormat.get_default_format()
        return format.initialize_on_transport(t)

    @staticmethod
    def find_bzrdirs(transport, evaluate=None, list_current=None):
        """Find bzrdirs recursively from current location.

        This is intended primarily as a building block for more sophisticated
        functionality, like finding trees under a directory, or finding
        branches that use a given repository.
        :param evaluate: An optional callable that yields recurse, value,
            where recurse controls whether this bzrdir is recursed into
            and value is the value to yield.  By default, all bzrdirs
            are recursed into, and the return value is the bzrdir.
        :param list_current: if supplied, use this function to list the current
            directory, instead of Transport.list_dir
        :return: a generator of found bzrdirs, or whatever evaluate returns.
        """
        if list_current is None:
            def list_current(transport):
                return transport.list_dir('')
        if evaluate is None:
            def evaluate(bzrdir):
                return True, bzrdir

        pending = [transport]
        while len(pending) > 0:
            current_transport = pending.pop()
            recurse = True
            try:
                bzrdir = BzrDir.open_from_transport(current_transport)
            except errors.NotBranchError:
                pass
            else:
                recurse, value = evaluate(bzrdir)
                yield value
            try:
                subdirs = list_current(current_transport)
            except errors.NoSuchFile:
                continue
            if recurse:
                for subdir in sorted(subdirs, reverse=True):
                    pending.append(current_transport.clone(subdir))

    @staticmethod
    def find_branches(transport):
        """Find all branches under a transport.

        This will find all branches below the transport, including branches
        inside other branches.  Where possible, it will use
        Repository.find_branches.

        To list all the branches that use a particular Repository, see
        Repository.find_branches
        """
        def evaluate(bzrdir):
            try:
                repository = bzrdir.open_repository()
            except errors.NoRepositoryPresent:
                pass
            else:
                return False, (None, repository)
            try:
                branch = bzrdir.open_branch()
            except errors.NotBranchError:
                return True, (None, None)
            else:
                return True, (branch, None)
        branches = []
        for branch, repo in BzrDir.find_bzrdirs(transport, evaluate=evaluate):
            if repo is not None:
                branches.extend(repo.find_branches())
            if branch is not None:
                branches.append(branch)
        return branches

    def destroy_repository(self):
        """Destroy the repository in this BzrDir"""
        raise NotImplementedError(self.destroy_repository)

    def create_branch(self):
        """Create a branch in this BzrDir.

        The bzrdir's format will control what branch format is created.
        For more control see BranchFormatXX.create(a_bzrdir).
        """
        raise NotImplementedError(self.create_branch)

    def destroy_branch(self):
        """Destroy the branch in this BzrDir"""
        raise NotImplementedError(self.destroy_branch)

    @staticmethod
    def create_branch_and_repo(base, force_new_repo=False, format=None):
        """Create a new BzrDir, Branch and Repository at the url 'base'.

        This will use the current default BzrDirFormat unless one is
        specified, and use whatever 
        repository format that that uses via bzrdir.create_branch and
        create_repository. If a shared repository is available that is used
        preferentially.

        The created Branch object is returned.

        :param base: The URL to create the branch at.
        :param force_new_repo: If True a new repository is always created.
        :param format: If supplied, the format of branch to create.  If not
            supplied, the default is used.
        """
        bzrdir = BzrDir.create(base, format)
        bzrdir._find_or_create_repository(force_new_repo)
        return bzrdir.create_branch()

    def determine_repository_policy(self, force_new_repo=False, stack_on=None,
                                    stack_on_pwd=None, require_stacking=False):
        """Return an object representing a policy to use.

        This controls whether a new repository is created, or a shared
        repository used instead.

        If stack_on is supplied, will not seek a containing shared repo.

        :param force_new_repo: If True, require a new repository to be created.
        :param stack_on: If supplied, the location to stack on.  If not
            supplied, a default_stack_on location may be used.
        :param stack_on_pwd: If stack_on is relative, the location it is
            relative to.
        """
        def repository_policy(found_bzrdir):
            stack_on = None
            stack_on_pwd = None
            stop = False
            # does it have a repository ?
            try:
                repository = found_bzrdir.open_repository()
            except errors.NoRepositoryPresent:
                repository = None
            else:
                if ((found_bzrdir.root_transport.base !=
                     self.root_transport.base) and not repository.is_shared()):
                    repository = None
                else:
                    stop = True
            if not stop:
                return None, False
            if repository:
                return UseExistingRepository(repository, stack_on,
                    stack_on_pwd, require_stacking=require_stacking), True
            else:
                return CreateRepository(self, stack_on, stack_on_pwd,
                    require_stacking=require_stacking), True

        if not force_new_repo:
            if stack_on is None:
                policy = self._find_containing(repository_policy)
                if policy is not None:
                    return policy
            else:
                try:
                    return UseExistingRepository(self.open_repository(),
                        stack_on, stack_on_pwd,
                        require_stacking=require_stacking)
                except errors.NoRepositoryPresent:
                    pass
        return CreateRepository(self, stack_on, stack_on_pwd,
                                require_stacking=require_stacking)

    def _find_or_create_repository(self, force_new_repo):
        """Create a new repository if needed, returning the repository."""
        policy = self.determine_repository_policy(force_new_repo)
        return policy.acquire_repository()

    @staticmethod
    def create_branch_convenience(base, force_new_repo=False,
                                  force_new_tree=None, format=None,
                                  possible_transports=None):
        """Create a new BzrDir, Branch and Repository at the url 'base'.

        This is a convenience function - it will use an existing repository
        if possible, can be told explicitly whether to create a working tree or
        not.

        This will use the current default BzrDirFormat unless one is
        specified, and use whatever 
        repository format that that uses via bzrdir.create_branch and
        create_repository. If a shared repository is available that is used
        preferentially. Whatever repository is used, its tree creation policy
        is followed.

        The created Branch object is returned.
        If a working tree cannot be made due to base not being a file:// url,
        no error is raised unless force_new_tree is True, in which case no 
        data is created on disk and NotLocalUrl is raised.

        :param base: The URL to create the branch at.
        :param force_new_repo: If True a new repository is always created.
        :param force_new_tree: If True or False force creation of a tree or 
                               prevent such creation respectively.
        :param format: Override for the bzrdir format to create.
        :param possible_transports: An optional reusable transports list.
        """
        if force_new_tree:
            # check for non local urls
            t = get_transport(base, possible_transports)
            if not isinstance(t, LocalTransport):
                raise errors.NotLocalUrl(base)
        bzrdir = BzrDir.create(base, format, possible_transports)
        repo = bzrdir._find_or_create_repository(force_new_repo)
        result = bzrdir.create_branch()
        if force_new_tree or (repo.make_working_trees() and
                              force_new_tree is None):
            try:
                bzrdir.create_workingtree()
            except errors.NotLocalUrl:
                pass
        return result

    @staticmethod
    def create_standalone_workingtree(base, format=None):
        """Create a new BzrDir, WorkingTree, Branch and Repository at 'base'.

        'base' must be a local path or a file:// url.

        This will use the current default BzrDirFormat unless one is
        specified, and use whatever 
        repository format that that uses for bzrdirformat.create_workingtree,
        create_branch and create_repository.

        :param format: Override for the bzrdir format to create.
        :return: The WorkingTree object.
        """
        t = get_transport(base)
        if not isinstance(t, LocalTransport):
            raise errors.NotLocalUrl(base)
        bzrdir = BzrDir.create_branch_and_repo(base,
                                               force_new_repo=True,
                                               format=format).bzrdir
        return bzrdir.create_workingtree()

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

    def retire_bzrdir(self, limit=10000):
        """Permanently disable the bzrdir.

        This is done by renaming it to give the user some ability to recover
        if there was a problem.

        This will have horrible consequences if anyone has anything locked or
        in use.
        :param limit: number of times to retry
        """
        i  = 0
        while True:
            try:
                to_path = '.bzr.retired.%d' % i
                self.root_transport.rename('.bzr', to_path)
                note("renamed %s to %s"
                    % (self.root_transport.abspath('.bzr'), to_path))
                return
            except (errors.TransportError, IOError, errors.PathError):
                i += 1
                if i > limit:
                    raise
                else:
                    pass

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

    def _find_containing(self, evaluate):
        """Find something in a containing control directory.

        This method will scan containing control dirs, until it finds what
        it is looking for, decides that it will never find it, or runs out
        of containing control directories to check.

        It is used to implement find_repository and
        determine_repository_policy.

        :param evaluate: A function returning (value, stop).  If stop is True,
            the value will be returned.
        """
        found_bzrdir = self
        while True:
            result, stop = evaluate(found_bzrdir)
            if stop:
                return result
            next_transport = found_bzrdir.root_transport.clone('..')
            if (found_bzrdir.root_transport.base == next_transport.base):
                # top of the file system
                return None
            # find the next containing bzrdir
            try:
                found_bzrdir = BzrDir.open_containing_from_transport(
                    next_transport)[0]
            except errors.NotBranchError:
                return None

    def find_repository(self):
        """Find the repository that should be used.

        This does not require a branch as we use it to find the repo for
        new branches as well as to hook existing branches up to their
        repository.
        """
        def usable_repository(found_bzrdir):
            # does it have a repository ?
            try:
                repository = found_bzrdir.open_repository()
            except errors.NoRepositoryPresent:
                return None, False
            if found_bzrdir.root_transport.base == self.root_transport.base:
                return repository, True
            elif repository.is_shared():
                return repository, True
            else:
                return None, True

        found_repo = self._find_containing(usable_repository)
        if found_repo is None:
            raise errors.NoRepositoryPresent(self)
        return found_repo

    def get_branch_reference(self):
        """Return the referenced URL for the branch in this bzrdir.

        :raises NotBranchError: If there is no Branch.
        :return: The URL the branch in this bzrdir references if it is a
            reference branch, or None for regular branches.
        """
        return None

    def get_branch_transport(self, branch_format):
        """Get the transport for use by branch format in this BzrDir.

        Note that bzr dirs that do not support format strings will raise
        IncompatibleFormat if the branch format they are given has
        a format string, and vice versa.

        If branch_format is None, the transport is returned with no 
        checking. If it is not None, then the returned transport is
        guaranteed to point to an existing directory ready for use.
        """
        raise NotImplementedError(self.get_branch_transport)

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
            st = self.transport.stat('.')
        except errors.TransportNotPossible:
            self._dir_mode = None
            self._file_mode = None
        else:
            # Check the directory mode, but also make sure the created
            # directories and files are read-write for this user. This is
            # mostly a workaround for filesystems which lie about being able to
            # write to a directory (cygwin & win32)
            self._dir_mode = (st.st_mode & 07777) | 00700
            # Remove the sticky and execute bits for files
            self._file_mode = self._dir_mode & ~07111

    def _get_file_mode(self):
        """Return Unix mode for newly created files, or None.
        """
        if not self._mode_check_done:
            self._find_creation_modes()
        return self._file_mode

    def _get_dir_mode(self):
        """Return Unix mode for newly created directories, or None.
        """
        if not self._mode_check_done:
            self._find_creation_modes()
        return self._dir_mode
        
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

    def get_config(self):
        if getattr(self, '_get_config', None) is None:
            return None
        return self._get_config()

    def __init__(self, _transport, _format):
        """Initialize a Bzr control dir object.
        
        Only really common logic should reside here, concrete classes should be
        made with varying behaviours.

        :param _format: the format that is creating this BzrDir instance.
        :param _transport: the transport this dir is based at.
        """
        self._format = _format
        self.transport = _transport.clone('.bzr')
        self.root_transport = _transport
        self._mode_check_done = False

    def is_control_filename(self, filename):
        """True if filename is the name of a path which is reserved for bzrdir's.
        
        :param filename: A filename within the root transport of this bzrdir.

        This is true IF and ONLY IF the filename is part of the namespace reserved
        for bzr control dirs. Currently this is the '.bzr' directory in the root
        of the root_transport. it is expected that plugins will need to extend
        this in the future - for instance to make bzr talk with svn working
        trees.
        """
        # this might be better on the BzrDirFormat class because it refers to 
        # all the possible bzrdir disk formats. 
        # This method is tested via the workingtree is_control_filename tests- 
        # it was extracted from WorkingTree.is_control_filename. If the method's
        # contract is extended beyond the current trivial implementation, please
        # add new tests for it to the appropriate place.
        return filename == '.bzr' or filename.startswith('.bzr/')

    def needs_format_conversion(self, format=None):
        """Return true if this bzrdir needs convert_format run on it.
        
        For instance, if the repository format is out of date but the 
        branch and working tree are not, this should return True.

        :param format: Optional parameter indicating a specific desired
                       format we plan to arrive at.
        """
        raise NotImplementedError(self.needs_format_conversion)

    @staticmethod
    def open_unsupported(base):
        """Open a branch which is not supported."""
        return BzrDir.open(base, _unsupported=True)
        
    @staticmethod
    def open(base, _unsupported=False, possible_transports=None):
        """Open an existing bzrdir, rooted at 'base' (url).
        
        :param _unsupported: a private parameter to the BzrDir class.
        """
        t = get_transport(base, possible_transports=possible_transports)
        return BzrDir.open_from_transport(t, _unsupported=_unsupported)

    @staticmethod
    def open_from_transport(transport, _unsupported=False,
                            _server_formats=True):
        """Open a bzrdir within a particular directory.

        :param transport: Transport containing the bzrdir.
        :param _unsupported: private.
        """
        base = transport.base

        def find_format(transport):
            return transport, BzrDirFormat.find_format(
                transport, _server_formats=_server_formats)

        def redirected(transport, e, redirection_notice):
            qualified_source = e.get_source_url()
            relpath = transport.relpath(qualified_source)
            if not e.target.endswith(relpath):
                # Not redirected to a branch-format, not a branch
                raise errors.NotBranchError(path=e.target)
            target = e.target[:-len(relpath)]
            note('%s is%s redirected to %s',
                 transport.base, e.permanently, target)
            # Let's try with a new transport
            # FIXME: If 'transport' has a qualifier, this should
            # be applied again to the new transport *iff* the
            # schemes used are the same. Uncomment this code
            # once the function (and tests) exist.
            # -- vila20070212
            #target = urlutils.copy_url_qualifiers(original, target)
            return get_transport(target)

        try:
            transport, format = do_catching_redirections(find_format,
                                                         transport,
                                                         redirected)
        except errors.TooManyRedirections:
            raise errors.NotBranchError(base)

        BzrDir._check_supported(format, _unsupported)
        return format.open(transport, _found=True)

    def open_branch(self, unsupported=False):
        """Open the branch object at this BzrDir if one is present.

        If unsupported is True, then no longer supported branch formats can
        still be opened.
        
        TODO: static convenience version of this?
        """
        raise NotImplementedError(self.open_branch)

    @staticmethod
    def open_containing(url, possible_transports=None):
        """Open an existing branch which contains url.
        
        :param url: url to search from.
        See open_containing_from_transport for more detail.
        """
        transport = get_transport(url, possible_transports)
        return BzrDir.open_containing_from_transport(transport)
    
    @staticmethod
    def open_containing_from_transport(a_transport):
        """Open an existing branch which contains a_transport.base.

        This probes for a branch at a_transport, and searches upwards from there.

        Basically we keep looking up until we find the control directory or
        run into the root.  If there isn't one, raises NotBranchError.
        If there is one and it is either an unrecognised format or an unsupported 
        format, UnknownFormatError or UnsupportedFormatError are raised.
        If there is one, it is returned, along with the unused portion of url.

        :return: The BzrDir that contains the path, and a Unicode path 
                for the rest of the URL.
        """
        # this gets the normalised url back. I.e. '.' -> the full path.
        url = a_transport.base
        while True:
            try:
                result = BzrDir.open_from_transport(a_transport)
                return result, urlutils.unescape(a_transport.relpath(url))
            except errors.NotBranchError, e:
                pass
            try:
                new_t = a_transport.clone('..')
            except errors.InvalidURLJoin:
                # reached the root, whatever that may be
                raise errors.NotBranchError(path=url)
            if new_t.base == a_transport.base:
                # reached the root, whatever that may be
                raise errors.NotBranchError(path=url)
            a_transport = new_t

    def _get_tree_branch(self):
        """Return the branch and tree, if any, for this bzrdir.

        Return None for tree if not present or inaccessible.
        Raise NotBranchError if no branch is present.
        :return: (tree, branch)
        """
        try:
            tree = self.open_workingtree()
        except (errors.NoWorkingTree, errors.NotLocalUrl):
            tree = None
            branch = self.open_branch()
        else:
            branch = tree.branch
        return tree, branch

    @classmethod
    def open_tree_or_branch(klass, location):
        """Return the branch and working tree at a location.

        If there is no tree at the location, tree will be None.
        If there is no branch at the location, an exception will be
        raised
        :return: (tree, branch)
        """
        bzrdir = klass.open(location)
        return bzrdir._get_tree_branch()

    @classmethod
    def open_containing_tree_or_branch(klass, location):
        """Return the branch and working tree contained by a location.

        Returns (tree, branch, relpath).
        If there is no tree at containing the location, tree will be None.
        If there is no branch containing the location, an exception will be
        raised
        relpath is the portion of the path that is contained by the branch.
        """
        bzrdir, relpath = klass.open_containing(location)
        tree, branch = bzrdir._get_tree_branch()
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
        BzrDir.

        If no tree, branch or repository is found, a NotBranchError is raised.
        """
        bzrdir, relpath = klass.open_containing(location)
        try:
            tree, branch = bzrdir._get_tree_branch()
        except errors.NotBranchError:
            try:
                repo = bzrdir.find_repository()
                return None, None, repo, relpath
            except (errors.NoRepositoryPresent):
                raise errors.NotBranchError(location)
        return tree, branch, branch.repository, relpath

    def open_repository(self, _unsupported=False):
        """Open the repository object at this BzrDir if one is present.

        This will not follow the Branch object pointer - it's strictly a direct
        open facility. Most client code should use open_branch().repository to
        get at a repository.

        :param _unsupported: a private parameter, not part of the api.
        TODO: static convenience version of this?
        """
        raise NotImplementedError(self.open_repository)

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

    def has_branch(self):
        """Tell if this bzrdir contains a branch.
        
        Note: if you're going to open the branch, you should just go ahead
        and try, and not ask permission first.  (This method just opens the 
        branch and discards it, and that's somewhat expensive.) 
        """
        try:
            self.open_branch()
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

    def _cloning_metadir(self):
        """Produce a metadir suitable for cloning with.
        
        :returns: (destination_bzrdir_format, source_repository)
        """
        result_format = self._format.__class__()
        try:
            try:
                branch = self.open_branch()
                source_repository = branch.repository
            except errors.NotBranchError:
                source_branch = None
                source_repository = self.open_repository()
        except errors.NoRepositoryPresent:
            source_repository = None
        else:
            # XXX TODO: This isinstance is here because we have not implemented
            # the fix recommended in bug # 103195 - to delegate this choice the
            # repository itself.
            repo_format = source_repository._format
            if not isinstance(repo_format, remote.RemoteRepositoryFormat):
                result_format.repository_format = repo_format
        try:
            # TODO: Couldn't we just probe for the format in these cases,
            # rather than opening the whole tree?  It would be a little
            # faster. mbp 20070401
            tree = self.open_workingtree(recommend_upgrade=False)
        except (errors.NoWorkingTree, errors.NotLocalUrl):
            result_format.workingtree_format = None
        else:
            result_format.workingtree_format = tree._format.__class__()
        return result_format, source_repository

    def cloning_metadir(self):
        """Produce a metadir suitable for cloning or sprouting with.

        These operations may produce workingtrees (yes, even though they're
        "cloning" something that doesn't have a tree), so a viable workingtree
        format must be selected.

        :returns: a BzrDirFormat with all component formats either set
            appropriately or set to None if that component should not be 
            created.
        """
        format, repository = self._cloning_metadir()
        if format._workingtree_format is None:
            if repository is None:
                return format
            tree_format = repository._format._matchingbzrdir.workingtree_format
            format.workingtree_format = tree_format.__class__()
        return format

    def checkout_metadir(self):
        return self.cloning_metadir()

    def sprout(self, url, revision_id=None, force_new_repo=False,
               recurse='down', possible_transports=None,
               accelerator_tree=None, hardlink=False, stacked=False):
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
        """
        target_transport = get_transport(url, possible_transports)
        target_transport.ensure_base()
        cloning_format = self.cloning_metadir()
        result = cloning_format.initialize_on_transport(target_transport)
        try:
            source_branch = self.open_branch()
            source_repository = source_branch.repository
            if stacked:
                stacked_branch_url = self.root_transport.base
            else:
                # if a stacked branch wasn't requested, we don't create one
                # even if the origin was stacked
                stacked_branch_url = None
        except errors.NotBranchError:
            source_branch = None
            try:
                source_repository = self.open_repository()
            except errors.NoRepositoryPresent:
                source_repository = None
            stacked_branch_url = None
        repository_policy = result.determine_repository_policy(
            force_new_repo, stacked_branch_url, require_stacking=stacked)
        result_repo = repository_policy.acquire_repository()
        if source_repository is not None:
            # XXX: Isn't this redundant with the copy_content_into used below
            # after creating the branch? -- mbp 20080724
            result_repo.fetch(source_repository, revision_id=revision_id)

        # Create/update the result branch
        format_forced = False
        if ((stacked 
             or repository_policy._require_stacking 
             or repository_policy._stack_on)
            and not result._format.get_branch_format().supports_stacking()):
            # We need to make a stacked branch, but the default format for the
            # target doesn't support stacking.  So force a branch that *can*
            # support stacking. 
            from bzrlib.branch import BzrBranchFormat7
            format = BzrBranchFormat7()
            result_branch = format.initialize(result)
            mutter("using %r for stacking" % (format,))
            format_forced = True
        elif source_branch is None:
            # this is for sprouting a bzrdir without a branch; is that
            # actually useful?
            result_branch = result.create_branch()
        else:
            result_branch = source_branch.sprout(
                result, revision_id=revision_id)
        mutter("created new branch %r" % (result_branch,))
        repository_policy.configure_branch(result_branch)
        if source_branch is not None and format_forced:
            # XXX: this duplicates Branch.sprout(); it probably belongs on an
            # InterBranch method? -- mbp 20080724
            source_branch.copy_content_into(result_branch,
                 revision_id=revision_id)
            result_branch.set_parent(self.root_transport.base)

        # Create/update the result working tree
        if isinstance(target_transport, LocalTransport) and (
            result_repo is None or result_repo.make_working_trees()):
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


class BzrDirPreSplitOut(BzrDir):
    """A common class for the all-in-one formats."""

    def __init__(self, _transport, _format):
        """See BzrDir.__init__."""
        super(BzrDirPreSplitOut, self).__init__(_transport, _format)
        self._control_files = lockable_files.LockableFiles(
                                            self.get_branch_transport(None),
                                            self._format._lock_file_name,
                                            self._format._lock_class)

    def break_lock(self):
        """Pre-splitout bzrdirs do not suffer from stale locks."""
        raise NotImplementedError(self.break_lock)

    def cloning_metadir(self):
        """Produce a metadir suitable for cloning with."""
        return self._format.__class__()

    def clone(self, url, revision_id=None, force_new_repo=False,
              preserve_stacking=False):
        """See BzrDir.clone().

        force_new_repo has no effect, since this family of formats always
        require a new repository.
        preserve_stacking has no effect, since no source branch using this
        family of formats can be stacked, so there is no stacking to preserve.
        """
        from bzrlib.workingtree import WorkingTreeFormat2
        self._make_tail(url)
        result = self._format._initialize_for_clone(url)
        self.open_repository().clone(result, revision_id=revision_id)
        from_branch = self.open_branch()
        from_branch.clone(result, revision_id=revision_id)
        try:
            self.open_workingtree().clone(result)
        except errors.NotLocalUrl:
            # make a new one, this format always has to have one.
            try:
                WorkingTreeFormat2().initialize(result)
            except errors.NotLocalUrl:
                # but we cannot do it for remote trees.
                to_branch = result.open_branch()
                WorkingTreeFormat2()._stub_initialize_remote(to_branch)
        return result

    def create_branch(self):
        """See BzrDir.create_branch."""
        return self.open_branch()

    def destroy_branch(self):
        """See BzrDir.destroy_branch."""
        raise errors.UnsupportedOperation(self.destroy_branch, self)

    def create_repository(self, shared=False):
        """See BzrDir.create_repository."""
        if shared:
            raise errors.IncompatibleFormat('shared repository', self._format)
        return self.open_repository()

    def destroy_repository(self):
        """See BzrDir.destroy_repository."""
        raise errors.UnsupportedOperation(self.destroy_repository, self)

    def create_workingtree(self, revision_id=None, from_branch=None,
                           accelerator_tree=None, hardlink=False):
        """See BzrDir.create_workingtree."""
        # this looks buggy but is not -really-
        # because this format creates the workingtree when the bzrdir is
        # created
        # clone and sprout will have set the revision_id
        # and that will have set it for us, its only
        # specific uses of create_workingtree in isolation
        # that can do wonky stuff here, and that only
        # happens for creating checkouts, which cannot be 
        # done on this format anyway. So - acceptable wart.
        result = self.open_workingtree(recommend_upgrade=False)
        if revision_id is not None:
            if revision_id == _mod_revision.NULL_REVISION:
                result.set_parent_ids([])
            else:
                result.set_parent_ids([revision_id])
        return result

    def destroy_workingtree(self):
        """See BzrDir.destroy_workingtree."""
        raise errors.UnsupportedOperation(self.destroy_workingtree, self)

    def destroy_workingtree_metadata(self):
        """See BzrDir.destroy_workingtree_metadata."""
        raise errors.UnsupportedOperation(self.destroy_workingtree_metadata, 
                                          self)

    def get_branch_transport(self, branch_format):
        """See BzrDir.get_branch_transport()."""
        if branch_format is None:
            return self.transport
        try:
            branch_format.get_format_string()
        except NotImplementedError:
            return self.transport
        raise errors.IncompatibleFormat(branch_format, self._format)

    def get_repository_transport(self, repository_format):
        """See BzrDir.get_repository_transport()."""
        if repository_format is None:
            return self.transport
        try:
            repository_format.get_format_string()
        except NotImplementedError:
            return self.transport
        raise errors.IncompatibleFormat(repository_format, self._format)

    def get_workingtree_transport(self, workingtree_format):
        """See BzrDir.get_workingtree_transport()."""
        if workingtree_format is None:
            return self.transport
        try:
            workingtree_format.get_format_string()
        except NotImplementedError:
            return self.transport
        raise errors.IncompatibleFormat(workingtree_format, self._format)

    def needs_format_conversion(self, format=None):
        """See BzrDir.needs_format_conversion()."""
        # if the format is not the same as the system default,
        # an upgrade is needed.
        if format is None:
            format = BzrDirFormat.get_default_format()
        return not isinstance(self._format, format.__class__)

    def open_branch(self, unsupported=False):
        """See BzrDir.open_branch."""
        from bzrlib.branch import BzrBranchFormat4
        format = BzrBranchFormat4()
        self._check_supported(format, unsupported)
        return format.open(self, _found=True)

    def sprout(self, url, revision_id=None, force_new_repo=False,
               possible_transports=None, accelerator_tree=None,
               hardlink=False, stacked=False):
        """See BzrDir.sprout()."""
        if stacked:
            raise errors.UnstackableBranchFormat(
                self._format, self.root_transport.base)
        from bzrlib.workingtree import WorkingTreeFormat2
        self._make_tail(url)
        result = self._format._initialize_for_clone(url)
        try:
            self.open_repository().clone(result, revision_id=revision_id)
        except errors.NoRepositoryPresent:
            pass
        try:
            self.open_branch().sprout(result, revision_id=revision_id)
        except errors.NotBranchError:
            pass
        # we always want a working tree
        WorkingTreeFormat2().initialize(result,
                                        accelerator_tree=accelerator_tree,
                                        hardlink=hardlink)
        return result


class BzrDir4(BzrDirPreSplitOut):
    """A .bzr version 4 control object.
    
    This is a deprecated format and may be removed after sept 2006.
    """

    def create_repository(self, shared=False):
        """See BzrDir.create_repository."""
        return self._format.repository_format.initialize(self, shared)

    def needs_format_conversion(self, format=None):
        """Format 4 dirs are always in need of conversion."""
        return True

    def open_repository(self):
        """See BzrDir.open_repository."""
        from bzrlib.repofmt.weaverepo import RepositoryFormat4
        return RepositoryFormat4().open(self, _found=True)


class BzrDir5(BzrDirPreSplitOut):
    """A .bzr version 5 control object.

    This is a deprecated format and may be removed after sept 2006.
    """

    def open_repository(self):
        """See BzrDir.open_repository."""
        from bzrlib.repofmt.weaverepo import RepositoryFormat5
        return RepositoryFormat5().open(self, _found=True)

    def open_workingtree(self, _unsupported=False,
            recommend_upgrade=True):
        """See BzrDir.create_workingtree."""
        from bzrlib.workingtree import WorkingTreeFormat2
        wt_format = WorkingTreeFormat2()
        # we don't warn here about upgrades; that ought to be handled for the
        # bzrdir as a whole
        return wt_format.open(self, _found=True)


class BzrDir6(BzrDirPreSplitOut):
    """A .bzr version 6 control object.

    This is a deprecated format and may be removed after sept 2006.
    """

    def open_repository(self):
        """See BzrDir.open_repository."""
        from bzrlib.repofmt.weaverepo import RepositoryFormat6
        return RepositoryFormat6().open(self, _found=True)

    def open_workingtree(self, _unsupported=False,
        recommend_upgrade=True):
        """See BzrDir.create_workingtree."""
        # we don't warn here about upgrades; that ought to be handled for the
        # bzrdir as a whole
        from bzrlib.workingtree import WorkingTreeFormat2
        return WorkingTreeFormat2().open(self, _found=True)


class BzrDirMeta1(BzrDir):
    """A .bzr meta version 1 control object.
    
    This is the first control object where the 
    individual aspects are really split out: there are separate repository,
    workingtree and branch subdirectories and any subset of the three can be
    present within a BzrDir.
    """

    def can_convert_format(self):
        """See BzrDir.can_convert_format()."""
        return True

    def create_branch(self):
        """See BzrDir.create_branch."""
        return self._format.get_branch_format().initialize(self)

    def destroy_branch(self):
        """See BzrDir.create_branch."""
        self.transport.delete_tree('branch')

    def create_repository(self, shared=False):
        """See BzrDir.create_repository."""
        return self._format.repository_format.initialize(self, shared)

    def destroy_repository(self):
        """See BzrDir.destroy_repository."""
        self.transport.delete_tree('repository')

    def create_workingtree(self, revision_id=None, from_branch=None,
                           accelerator_tree=None, hardlink=False):
        """See BzrDir.create_workingtree."""
        return self._format.workingtree_format.initialize(
            self, revision_id, from_branch=from_branch,
            accelerator_tree=accelerator_tree, hardlink=hardlink)

    def destroy_workingtree(self):
        """See BzrDir.destroy_workingtree."""
        wt = self.open_workingtree(recommend_upgrade=False)
        repository = wt.branch.repository
        empty = repository.revision_tree(_mod_revision.NULL_REVISION)
        wt.revert(old_tree=empty)
        self.destroy_workingtree_metadata()

    def destroy_workingtree_metadata(self):
        self.transport.delete_tree('checkout')

    def find_branch_format(self):
        """Find the branch 'format' for this bzrdir.

        This might be a synthetic object for e.g. RemoteBranch and SVN.
        """
        from bzrlib.branch import BranchFormat
        return BranchFormat.find_format(self)

    def _get_mkdir_mode(self):
        """Figure out the mode to use when creating a bzrdir subdir."""
        temp_control = lockable_files.LockableFiles(self.transport, '',
                                     lockable_files.TransportLock)
        return temp_control._dir_mode

    def get_branch_reference(self):
        """See BzrDir.get_branch_reference()."""
        from bzrlib.branch import BranchFormat
        format = BranchFormat.find_format(self)
        return format.get_reference(self)

    def get_branch_transport(self, branch_format):
        """See BzrDir.get_branch_transport()."""
        if branch_format is None:
            return self.transport.clone('branch')
        try:
            branch_format.get_format_string()
        except NotImplementedError:
            raise errors.IncompatibleFormat(branch_format, self._format)
        try:
            self.transport.mkdir('branch', mode=self._get_mkdir_mode())
        except errors.FileExists:
            pass
        return self.transport.clone('branch')

    def get_repository_transport(self, repository_format):
        """See BzrDir.get_repository_transport()."""
        if repository_format is None:
            return self.transport.clone('repository')
        try:
            repository_format.get_format_string()
        except NotImplementedError:
            raise errors.IncompatibleFormat(repository_format, self._format)
        try:
            self.transport.mkdir('repository', mode=self._get_mkdir_mode())
        except errors.FileExists:
            pass
        return self.transport.clone('repository')

    def get_workingtree_transport(self, workingtree_format):
        """See BzrDir.get_workingtree_transport()."""
        if workingtree_format is None:
            return self.transport.clone('checkout')
        try:
            workingtree_format.get_format_string()
        except NotImplementedError:
            raise errors.IncompatibleFormat(workingtree_format, self._format)
        try:
            self.transport.mkdir('checkout', mode=self._get_mkdir_mode())
        except errors.FileExists:
            pass
        return self.transport.clone('checkout')

    def needs_format_conversion(self, format=None):
        """See BzrDir.needs_format_conversion()."""
        if format is None:
            format = BzrDirFormat.get_default_format()
        if not isinstance(self._format, format.__class__):
            # it is not a meta dir format, conversion is needed.
            return True
        # we might want to push this down to the repository?
        try:
            if not isinstance(self.open_repository()._format,
                              format.repository_format.__class__):
                # the repository needs an upgrade.
                return True
        except errors.NoRepositoryPresent:
            pass
        try:
            if not isinstance(self.open_branch()._format,
                              format.get_branch_format().__class__):
                # the branch needs an upgrade.
                return True
        except errors.NotBranchError:
            pass
        try:
            my_wt = self.open_workingtree(recommend_upgrade=False)
            if not isinstance(my_wt._format,
                              format.workingtree_format.__class__):
                # the workingtree needs an upgrade.
                return True
        except (errors.NoWorkingTree, errors.NotLocalUrl):
            pass
        return False

    def open_branch(self, unsupported=False):
        """See BzrDir.open_branch."""
        format = self.find_branch_format()
        self._check_supported(format, unsupported)
        return format.open(self, _found=True)

    def open_repository(self, unsupported=False):
        """See BzrDir.open_repository."""
        from bzrlib.repository import RepositoryFormat
        format = RepositoryFormat.find_format(self)
        self._check_supported(format, unsupported)
        return format.open(self, _found=True)

    def open_workingtree(self, unsupported=False,
            recommend_upgrade=True):
        """See BzrDir.open_workingtree."""
        from bzrlib.workingtree import WorkingTreeFormat
        format = WorkingTreeFormat.find_format(self)
        self._check_supported(format, unsupported,
            recommend_upgrade,
            basedir=self.root_transport.base)
        return format.open(self, _found=True)

    def _get_config(self):
        return config.BzrDirConfig(self.transport)


class BzrDirFormat(object):
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
    """

    _default_format = None
    """The default format used for new .bzr dirs."""

    _formats = {}
    """The known formats."""

    _control_formats = []
    """The registered control formats - .bzr, ....
    
    This is a list of BzrDirFormat objects.
    """

    _control_server_formats = []
    """The registered control server formats, e.g. RemoteBzrDirs.

    This is a list of BzrDirFormat objects.
    """

    _lock_file_name = 'branch-lock'

    # _lock_class must be set in subclasses to the lock type, typ.
    # TransportLock or LockDir

    @classmethod
    def find_format(klass, transport, _server_formats=True):
        """Return the format present at transport."""
        if _server_formats:
            formats = klass._control_server_formats + klass._control_formats
        else:
            formats = klass._control_formats
        for format in formats:
            try:
                return format.probe_transport(transport)
            except errors.NotBranchError:
                # this format does not find a control dir here.
                pass
        raise errors.NotBranchError(path=transport.base)

    @classmethod
    def probe_transport(klass, transport):
        """Return the .bzrdir style format present in a directory."""
        try:
            format_string = transport.get(".bzr/branch-format").read()
        except errors.NoSuchFile:
            raise errors.NotBranchError(path=transport.base)

        try:
            return klass._formats[format_string]
        except KeyError:
            raise errors.UnknownFormatError(format=format_string, kind='bzrdir')

    @classmethod
    def get_default_format(klass):
        """Return the current default format."""
        return klass._default_format

    def get_format_string(self):
        """Return the ASCII format string that identifies this format."""
        raise NotImplementedError(self.get_format_string)

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

    def initialize(self, url, possible_transports=None):
        """Create a bzr control dir at this url and return an opened copy.
        
        Subclasses should typically override initialize_on_transport
        instead of this method.
        """
        return self.initialize_on_transport(get_transport(url,
                                                          possible_transports))

    def initialize_on_transport(self, transport):
        """Initialize a new bzrdir in the base directory of a Transport."""
        # Since we don't have a .bzr directory, inherit the
        # mode from the root directory
        temp_control = lockable_files.LockableFiles(transport,
                            '', lockable_files.TransportLock)
        temp_control._transport.mkdir('.bzr',
                                      # FIXME: RBC 20060121 don't peek under
                                      # the covers
                                      mode=temp_control._dir_mode)
        if sys.platform == 'win32' and isinstance(transport, LocalTransport):
            win32utils.set_file_attr_hidden(transport._abspath('.bzr'))
        file_mode = temp_control._file_mode
        del temp_control
        bzrdir_transport = transport.clone('.bzr')
        utf8_files = [('README',
                       "This is a Bazaar control directory.\n"
                       "Do not change any files in this directory.\n"
                       "See http://bazaar-vcs.org/ for more information about Bazaar.\n"),
                      ('branch-format', self.get_format_string()),
                      ]
        # NB: no need to escape relative paths that are url safe.
        control_files = lockable_files.LockableFiles(bzrdir_transport,
            self._lock_file_name, self._lock_class)
        control_files.create_lock()
        control_files.lock_write()
        try:
            for (filename, content) in utf8_files:
                bzrdir_transport.put_bytes(filename, content,
                    mode=file_mode)
        finally:
            control_files.unlock()
        return self.open(transport, _found=True)

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
    def known_formats(klass):
        """Return all the known formats.
        
        Concrete formats should override _known_formats.
        """
        # There is double indirection here to make sure that control 
        # formats used by more than one dir format will only be probed 
        # once. This can otherwise be quite expensive for remote connections.
        result = set()
        for format in klass._control_formats:
            result.update(format._known_formats())
        return result
    
    @classmethod
    def _known_formats(klass):
        """Return the known format instances for this control format."""
        return set(klass._formats.values())

    def open(self, transport, _found=False):
        """Return an instance of this format for the dir transport points at.
        
        _found is a private parameter, do not use it.
        """
        if not _found:
            found_format = BzrDirFormat.find_format(transport)
            if not isinstance(found_format, self.__class__):
                raise AssertionError("%s was asked to open %s, but it seems to need "
                        "format %s" 
                        % (self, transport, found_format))
        return self._open(transport)

    def _open(self, transport):
        """Template method helper for opening BzrDirectories.

        This performs the actual open and any additional logic or parameter
        passing.
        """
        raise NotImplementedError(self._open)

    @classmethod
    def register_format(klass, format):
        klass._formats[format.get_format_string()] = format

    @classmethod
    def register_control_format(klass, format):
        """Register a format that does not use '.bzr' for its control dir.

        TODO: This should be pulled up into a 'ControlDirFormat' base class
        which BzrDirFormat can inherit from, and renamed to register_format 
        there. It has been done without that for now for simplicity of
        implementation.
        """
        klass._control_formats.append(format)

    @classmethod
    def register_control_server_format(klass, format):
        """Register a control format for client-server environments.

        These formats will be tried before ones registered with
        register_control_format.  This gives implementations that decide to the
        chance to grab it before anything looks at the contents of the format
        file.
        """
        klass._control_server_formats.append(format)

    @classmethod
    def _set_default_format(klass, format):
        """Set default format (for testing behavior of defaults only)"""
        klass._default_format = format

    def __str__(self):
        # Trim the newline
        return self.get_format_string().rstrip()

    @classmethod
    def unregister_format(klass, format):
        del klass._formats[format.get_format_string()]

    @classmethod
    def unregister_control_format(klass, format):
        klass._control_formats.remove(format)


class BzrDirFormat4(BzrDirFormat):
    """Bzr dir format 4.

    This format is a combined format for working tree, branch and repository.
    It has:
     - Format 1 working trees [always]
     - Format 4 branches [always]
     - Format 4 repositories [always]

    This format is deprecated: it indexes texts using a text it which is
    removed in format 5; write support for this format has been removed.
    """

    _lock_class = lockable_files.TransportLock

    def get_format_string(self):
        """See BzrDirFormat.get_format_string()."""
        return "Bazaar-NG branch, format 0.0.4\n"

    def get_format_description(self):
        """See BzrDirFormat.get_format_description()."""
        return "All-in-one format 4"

    def get_converter(self, format=None):
        """See BzrDirFormat.get_converter()."""
        # there is one and only one upgrade path here.
        return ConvertBzrDir4To5()
        
    def initialize_on_transport(self, transport):
        """Format 4 branches cannot be created."""
        raise errors.UninitializableFormat(self)

    def is_supported(self):
        """Format 4 is not supported.

        It is not supported because the model changed from 4 to 5 and the
        conversion logic is expensive - so doing it on the fly was not 
        feasible.
        """
        return False

    def _open(self, transport):
        """See BzrDirFormat._open."""
        return BzrDir4(transport, self)

    def __return_repository_format(self):
        """Circular import protection."""
        from bzrlib.repofmt.weaverepo import RepositoryFormat4
        return RepositoryFormat4()
    repository_format = property(__return_repository_format)


class BzrDirFormat5(BzrDirFormat):
    """Bzr control format 5.

    This format is a combined format for working tree, branch and repository.
    It has:
     - Format 2 working trees [always] 
     - Format 4 branches [always] 
     - Format 5 repositories [always]
       Unhashed stores in the repository.
    """

    _lock_class = lockable_files.TransportLock

    def get_format_string(self):
        """See BzrDirFormat.get_format_string()."""
        return "Bazaar-NG branch, format 5\n"

    def get_format_description(self):
        """See BzrDirFormat.get_format_description()."""
        return "All-in-one format 5"

    def get_converter(self, format=None):
        """See BzrDirFormat.get_converter()."""
        # there is one and only one upgrade path here.
        return ConvertBzrDir5To6()

    def _initialize_for_clone(self, url):
        return self.initialize_on_transport(get_transport(url), _cloning=True)
        
    def initialize_on_transport(self, transport, _cloning=False):
        """Format 5 dirs always have working tree, branch and repository.
        
        Except when they are being cloned.
        """
        from bzrlib.branch import BzrBranchFormat4
        from bzrlib.repofmt.weaverepo import RepositoryFormat5
        from bzrlib.workingtree import WorkingTreeFormat2
        result = (super(BzrDirFormat5, self).initialize_on_transport(transport))
        RepositoryFormat5().initialize(result, _internal=True)
        if not _cloning:
            branch = BzrBranchFormat4().initialize(result)
            try:
                WorkingTreeFormat2().initialize(result)
            except errors.NotLocalUrl:
                # Even though we can't access the working tree, we need to
                # create its control files.
                WorkingTreeFormat2()._stub_initialize_remote(branch)
        return result

    def _open(self, transport):
        """See BzrDirFormat._open."""
        return BzrDir5(transport, self)

    def __return_repository_format(self):
        """Circular import protection."""
        from bzrlib.repofmt.weaverepo import RepositoryFormat5
        return RepositoryFormat5()
    repository_format = property(__return_repository_format)


class BzrDirFormat6(BzrDirFormat):
    """Bzr control format 6.

    This format is a combined format for working tree, branch and repository.
    It has:
     - Format 2 working trees [always] 
     - Format 4 branches [always] 
     - Format 6 repositories [always]
    """

    _lock_class = lockable_files.TransportLock

    def get_format_string(self):
        """See BzrDirFormat.get_format_string()."""
        return "Bazaar-NG branch, format 6\n"

    def get_format_description(self):
        """See BzrDirFormat.get_format_description()."""
        return "All-in-one format 6"

    def get_converter(self, format=None):
        """See BzrDirFormat.get_converter()."""
        # there is one and only one upgrade path here.
        return ConvertBzrDir6ToMeta()
        
    def _initialize_for_clone(self, url):
        return self.initialize_on_transport(get_transport(url), _cloning=True)

    def initialize_on_transport(self, transport, _cloning=False):
        """Format 6 dirs always have working tree, branch and repository.
        
        Except when they are being cloned.
        """
        from bzrlib.branch import BzrBranchFormat4
        from bzrlib.repofmt.weaverepo import RepositoryFormat6
        from bzrlib.workingtree import WorkingTreeFormat2
        result = super(BzrDirFormat6, self).initialize_on_transport(transport)
        RepositoryFormat6().initialize(result, _internal=True)
        if not _cloning:
            branch = BzrBranchFormat4().initialize(result)
            try:
                WorkingTreeFormat2().initialize(result)
            except errors.NotLocalUrl:
                # Even though we can't access the working tree, we need to
                # create its control files.
                WorkingTreeFormat2()._stub_initialize_remote(branch)
        return result

    def _open(self, transport):
        """See BzrDirFormat._open."""
        return BzrDir6(transport, self)

    def __return_repository_format(self):
        """Circular import protection."""
        from bzrlib.repofmt.weaverepo import RepositoryFormat6
        return RepositoryFormat6()
    repository_format = property(__return_repository_format)


class BzrDirMetaFormat1(BzrDirFormat):
    """Bzr meta control format 1

    This is the first format with split out working tree, branch and repository
    disk storage.
    It has:
     - Format 3 working trees [optional]
     - Format 5 branches [optional]
     - Format 7 repositories [optional]
    """

    _lock_class = lockdir.LockDir

    def __init__(self):
        self._workingtree_format = None
        self._branch_format = None

    def __eq__(self, other):
        if other.__class__ is not self.__class__:
            return False
        if other.repository_format != self.repository_format:
            return False
        if other.workingtree_format != self.workingtree_format:
            return False
        return True

    def __ne__(self, other):
        return not self == other

    def get_branch_format(self):
        if self._branch_format is None:
            from bzrlib.branch import BranchFormat
            self._branch_format = BranchFormat.get_default_format()
        return self._branch_format

    def set_branch_format(self, format):
        self._branch_format = format

    def get_converter(self, format=None):
        """See BzrDirFormat.get_converter()."""
        if format is None:
            format = BzrDirFormat.get_default_format()
        if not isinstance(self, format.__class__):
            # converting away from metadir is not implemented
            raise NotImplementedError(self.get_converter)
        return ConvertMetaToMeta(format)

    def get_format_string(self):
        """See BzrDirFormat.get_format_string()."""
        return "Bazaar-NG meta directory, format 1\n"

    def get_format_description(self):
        """See BzrDirFormat.get_format_description()."""
        return "Meta directory format 1"

    def _open(self, transport):
        """See BzrDirFormat._open."""
        return BzrDirMeta1(transport, self)

    def __return_repository_format(self):
        """Circular import protection."""
        if getattr(self, '_repository_format', None):
            return self._repository_format
        from bzrlib.repository import RepositoryFormat
        return RepositoryFormat.get_default_format()

    def __set_repository_format(self, value):
        """Allow changing the repository format for metadir formats."""
        self._repository_format = value

    repository_format = property(__return_repository_format, __set_repository_format)

    def __get_workingtree_format(self):
        if self._workingtree_format is None:
            from bzrlib.workingtree import WorkingTreeFormat
            self._workingtree_format = WorkingTreeFormat.get_default_format()
        return self._workingtree_format

    def __set_workingtree_format(self, wt_format):
        self._workingtree_format = wt_format

    workingtree_format = property(__get_workingtree_format,
                                  __set_workingtree_format)


# Register bzr control format
BzrDirFormat.register_control_format(BzrDirFormat)

# Register bzr formats
BzrDirFormat.register_format(BzrDirFormat4())
BzrDirFormat.register_format(BzrDirFormat5())
BzrDirFormat.register_format(BzrDirFormat6())
__default_format = BzrDirMetaFormat1()
BzrDirFormat.register_format(__default_format)
BzrDirFormat._default_format = __default_format


class Converter(object):
    """Converts a disk format object from one format to another."""

    def convert(self, to_convert, pb):
        """Perform the conversion of to_convert, giving feedback via pb.

        :param to_convert: The disk object to convert.
        :param pb: a progress bar to use for progress information.
        """

    def step(self, message):
        """Update the pb by a step."""
        self.count +=1
        self.pb.update(message, self.count, self.total)


class ConvertBzrDir4To5(Converter):
    """Converts format 4 bzr dirs to format 5."""

    def __init__(self):
        super(ConvertBzrDir4To5, self).__init__()
        self.converted_revs = set()
        self.absent_revisions = set()
        self.text_count = 0
        self.revisions = {}
        
    def convert(self, to_convert, pb):
        """See Converter.convert()."""
        self.bzrdir = to_convert
        self.pb = pb
        self.pb.note('starting upgrade from format 4 to 5')
        if isinstance(self.bzrdir.transport, LocalTransport):
            self.bzrdir.get_workingtree_transport(None).delete('stat-cache')
        self._convert_to_weaves()
        return BzrDir.open(self.bzrdir.root_transport.base)

    def _convert_to_weaves(self):
        self.pb.note('note: upgrade may be faster if all store files are ungzipped first')
        try:
            # TODO permissions
            stat = self.bzrdir.transport.stat('weaves')
            if not S_ISDIR(stat.st_mode):
                self.bzrdir.transport.delete('weaves')
                self.bzrdir.transport.mkdir('weaves')
        except errors.NoSuchFile:
            self.bzrdir.transport.mkdir('weaves')
        # deliberately not a WeaveFile as we want to build it up slowly.
        self.inv_weave = Weave('inventory')
        # holds in-memory weaves for all files
        self.text_weaves = {}
        self.bzrdir.transport.delete('branch-format')
        self.branch = self.bzrdir.open_branch()
        self._convert_working_inv()
        rev_history = self.branch.revision_history()
        # to_read is a stack holding the revisions we still need to process;
        # appending to it adds new highest-priority revisions
        self.known_revisions = set(rev_history)
        self.to_read = rev_history[-1:]
        while self.to_read:
            rev_id = self.to_read.pop()
            if (rev_id not in self.revisions
                and rev_id not in self.absent_revisions):
                self._load_one_rev(rev_id)
        self.pb.clear()
        to_import = self._make_order()
        for i, rev_id in enumerate(to_import):
            self.pb.update('converting revision', i, len(to_import))
            self._convert_one_rev(rev_id)
        self.pb.clear()
        self._write_all_weaves()
        self._write_all_revs()
        self.pb.note('upgraded to weaves:')
        self.pb.note('  %6d revisions and inventories', len(self.revisions))
        self.pb.note('  %6d revisions not present', len(self.absent_revisions))
        self.pb.note('  %6d texts', self.text_count)
        self._cleanup_spare_files_after_format4()
        self.branch._transport.put_bytes(
            'branch-format',
            BzrDirFormat5().get_format_string(),
            mode=self.bzrdir._get_file_mode())

    def _cleanup_spare_files_after_format4(self):
        # FIXME working tree upgrade foo.
        for n in 'merged-patches', 'pending-merged-patches':
            try:
                ## assert os.path.getsize(p) == 0
                self.bzrdir.transport.delete(n)
            except errors.NoSuchFile:
                pass
        self.bzrdir.transport.delete_tree('inventory-store')
        self.bzrdir.transport.delete_tree('text-store')

    def _convert_working_inv(self):
        inv = xml4.serializer_v4.read_inventory(
                self.branch._transport.get('inventory'))
        new_inv_xml = xml5.serializer_v5.write_inventory_to_string(inv, working=True)
        self.branch._transport.put_bytes('inventory', new_inv_xml,
            mode=self.bzrdir._get_file_mode())

    def _write_all_weaves(self):
        controlweaves = WeaveStore(self.bzrdir.transport, prefixed=False)
        weave_transport = self.bzrdir.transport.clone('weaves')
        weaves = WeaveStore(weave_transport, prefixed=False)
        transaction = WriteTransaction()

        try:
            i = 0
            for file_id, file_weave in self.text_weaves.items():
                self.pb.update('writing weave', i, len(self.text_weaves))
                weaves._put_weave(file_id, file_weave, transaction)
                i += 1
            self.pb.update('inventory', 0, 1)
            controlweaves._put_weave('inventory', self.inv_weave, transaction)
            self.pb.update('inventory', 1, 1)
        finally:
            self.pb.clear()

    def _write_all_revs(self):
        """Write all revisions out in new form."""
        self.bzrdir.transport.delete_tree('revision-store')
        self.bzrdir.transport.mkdir('revision-store')
        revision_transport = self.bzrdir.transport.clone('revision-store')
        # TODO permissions
        from bzrlib.xml5 import serializer_v5
        from bzrlib.repofmt.weaverepo import RevisionTextStore
        revision_store = RevisionTextStore(revision_transport,
            serializer_v5, False, versionedfile.PrefixMapper(),
            lambda:True, lambda:True)
        try:
            for i, rev_id in enumerate(self.converted_revs):
                self.pb.update('write revision', i, len(self.converted_revs))
                text = serializer_v5.write_revision_to_string(
                    self.revisions[rev_id])
                key = (rev_id,)
                revision_store.add_lines(key, None, osutils.split_lines(text))
        finally:
            self.pb.clear()
            
    def _load_one_rev(self, rev_id):
        """Load a revision object into memory.

        Any parents not either loaded or abandoned get queued to be
        loaded."""
        self.pb.update('loading revision',
                       len(self.revisions),
                       len(self.known_revisions))
        if not self.branch.repository.has_revision(rev_id):
            self.pb.clear()
            self.pb.note('revision {%s} not present in branch; '
                         'will be converted as a ghost',
                         rev_id)
            self.absent_revisions.add(rev_id)
        else:
            rev = self.branch.repository.get_revision(rev_id)
            for parent_id in rev.parent_ids:
                self.known_revisions.add(parent_id)
                self.to_read.append(parent_id)
            self.revisions[rev_id] = rev

    def _load_old_inventory(self, rev_id):
        old_inv_xml = self.branch.repository.inventory_store.get(rev_id).read()
        inv = xml4.serializer_v4.read_inventory_from_string(old_inv_xml)
        inv.revision_id = rev_id
        rev = self.revisions[rev_id]
        return inv

    def _load_updated_inventory(self, rev_id):
        inv_xml = self.inv_weave.get_text(rev_id)
        inv = xml5.serializer_v5.read_inventory_from_string(inv_xml, rev_id)
        return inv

    def _convert_one_rev(self, rev_id):
        """Convert revision and all referenced objects to new format."""
        rev = self.revisions[rev_id]
        inv = self._load_old_inventory(rev_id)
        present_parents = [p for p in rev.parent_ids
                           if p not in self.absent_revisions]
        self._convert_revision_contents(rev, inv, present_parents)
        self._store_new_inv(rev, inv, present_parents)
        self.converted_revs.add(rev_id)

    def _store_new_inv(self, rev, inv, present_parents):
        new_inv_xml = xml5.serializer_v5.write_inventory_to_string(inv)
        new_inv_sha1 = sha_string(new_inv_xml)
        self.inv_weave.add_lines(rev.revision_id,
                                 present_parents,
                                 new_inv_xml.splitlines(True))
        rev.inventory_sha1 = new_inv_sha1

    def _convert_revision_contents(self, rev, inv, present_parents):
        """Convert all the files within a revision.

        Also upgrade the inventory to refer to the text revision ids."""
        rev_id = rev.revision_id
        mutter('converting texts of revision {%s}',
               rev_id)
        parent_invs = map(self._load_updated_inventory, present_parents)
        entries = inv.iter_entries()
        entries.next()
        for path, ie in entries:
            self._convert_file_version(rev, ie, parent_invs)

    def _convert_file_version(self, rev, ie, parent_invs):
        """Convert one version of one file.

        The file needs to be added into the weave if it is a merge
        of >=2 parents or if it's changed from its parent.
        """
        file_id = ie.file_id
        rev_id = rev.revision_id
        w = self.text_weaves.get(file_id)
        if w is None:
            w = Weave(file_id)
            self.text_weaves[file_id] = w
        text_changed = False
        parent_candiate_entries = ie.parent_candidates(parent_invs)
        heads = graph.Graph(self).heads(parent_candiate_entries.keys())
        # XXX: Note that this is unordered - and this is tolerable because 
        # the previous code was also unordered.
        previous_entries = dict((head, parent_candiate_entries[head]) for head
            in heads)
        self.snapshot_ie(previous_entries, ie, w, rev_id)
        del ie.text_id

    @symbol_versioning.deprecated_method(symbol_versioning.one_one)
    def get_parents(self, revision_ids):
        for revision_id in revision_ids:
            yield self.revisions[revision_id].parent_ids

    def get_parent_map(self, revision_ids):
        """See graph._StackedParentsProvider.get_parent_map"""
        return dict((revision_id, self.revisions[revision_id])
                    for revision_id in revision_ids
                     if revision_id in self.revisions)

    def snapshot_ie(self, previous_revisions, ie, w, rev_id):
        # TODO: convert this logic, which is ~= snapshot to
        # a call to:. This needs the path figured out. rather than a work_tree
        # a v4 revision_tree can be given, or something that looks enough like
        # one to give the file content to the entry if it needs it.
        # and we need something that looks like a weave store for snapshot to 
        # save against.
        #ie.snapshot(rev, PATH, previous_revisions, REVISION_TREE, InMemoryWeaveStore(self.text_weaves))
        if len(previous_revisions) == 1:
            previous_ie = previous_revisions.values()[0]
            if ie._unchanged(previous_ie):
                ie.revision = previous_ie.revision
                return
        if ie.has_text():
            text = self.branch.repository._text_store.get(ie.text_id)
            file_lines = text.readlines()
            w.add_lines(rev_id, previous_revisions, file_lines)
            self.text_count += 1
        else:
            w.add_lines(rev_id, previous_revisions, [])
        ie.revision = rev_id

    def _make_order(self):
        """Return a suitable order for importing revisions.

        The order must be such that an revision is imported after all
        its (present) parents.
        """
        todo = set(self.revisions.keys())
        done = self.absent_revisions.copy()
        order = []
        while todo:
            # scan through looking for a revision whose parents
            # are all done
            for rev_id in sorted(list(todo)):
                rev = self.revisions[rev_id]
                parent_ids = set(rev.parent_ids)
                if parent_ids.issubset(done):
                    # can take this one now
                    order.append(rev_id)
                    todo.remove(rev_id)
                    done.add(rev_id)
        return order


class ConvertBzrDir5To6(Converter):
    """Converts format 5 bzr dirs to format 6."""

    def convert(self, to_convert, pb):
        """See Converter.convert()."""
        self.bzrdir = to_convert
        self.pb = pb
        self.pb.note('starting upgrade from format 5 to 6')
        self._convert_to_prefixed()
        return BzrDir.open(self.bzrdir.root_transport.base)

    def _convert_to_prefixed(self):
        from bzrlib.store import TransportStore
        self.bzrdir.transport.delete('branch-format')
        for store_name in ["weaves", "revision-store"]:
            self.pb.note("adding prefixes to %s" % store_name)
            store_transport = self.bzrdir.transport.clone(store_name)
            store = TransportStore(store_transport, prefixed=True)
            for urlfilename in store_transport.list_dir('.'):
                filename = urlutils.unescape(urlfilename)
                if (filename.endswith(".weave") or
                    filename.endswith(".gz") or
                    filename.endswith(".sig")):
                    file_id, suffix = os.path.splitext(filename)
                else:
                    file_id = filename
                    suffix = ''
                new_name = store._mapper.map((file_id,)) + suffix
                # FIXME keep track of the dirs made RBC 20060121
                try:
                    store_transport.move(filename, new_name)
                except errors.NoSuchFile: # catches missing dirs strangely enough
                    store_transport.mkdir(osutils.dirname(new_name))
                    store_transport.move(filename, new_name)
        self.bzrdir.transport.put_bytes(
            'branch-format',
            BzrDirFormat6().get_format_string(),
            mode=self.bzrdir._get_file_mode())


class ConvertBzrDir6ToMeta(Converter):
    """Converts format 6 bzr dirs to metadirs."""

    def convert(self, to_convert, pb):
        """See Converter.convert()."""
        from bzrlib.repofmt.weaverepo import RepositoryFormat7
        from bzrlib.branch import BzrBranchFormat5
        self.bzrdir = to_convert
        self.pb = pb
        self.count = 0
        self.total = 20 # the steps we know about
        self.garbage_inventories = []
        self.dir_mode = self.bzrdir._get_dir_mode()
        self.file_mode = self.bzrdir._get_file_mode()

        self.pb.note('starting upgrade from format 6 to metadir')
        self.bzrdir.transport.put_bytes(
                'branch-format',
                "Converting to format 6",
                mode=self.file_mode)
        # its faster to move specific files around than to open and use the apis...
        # first off, nuke ancestry.weave, it was never used.
        try:
            self.step('Removing ancestry.weave')
            self.bzrdir.transport.delete('ancestry.weave')
        except errors.NoSuchFile:
            pass
        # find out whats there
        self.step('Finding branch files')
        last_revision = self.bzrdir.open_branch().last_revision()
        bzrcontents = self.bzrdir.transport.list_dir('.')
        for name in bzrcontents:
            if name.startswith('basis-inventory.'):
                self.garbage_inventories.append(name)
        # create new directories for repository, working tree and branch
        repository_names = [('inventory.weave', True),
                            ('revision-store', True),
                            ('weaves', True)]
        self.step('Upgrading repository  ')
        self.bzrdir.transport.mkdir('repository', mode=self.dir_mode)
        self.make_lock('repository')
        # we hard code the formats here because we are converting into
        # the meta format. The meta format upgrader can take this to a 
        # future format within each component.
        self.put_format('repository', RepositoryFormat7())
        for entry in repository_names:
            self.move_entry('repository', entry)

        self.step('Upgrading branch      ')
        self.bzrdir.transport.mkdir('branch', mode=self.dir_mode)
        self.make_lock('branch')
        self.put_format('branch', BzrBranchFormat5())
        branch_files = [('revision-history', True),
                        ('branch-name', True),
                        ('parent', False)]
        for entry in branch_files:
            self.move_entry('branch', entry)

        checkout_files = [('pending-merges', True),
                          ('inventory', True),
                          ('stat-cache', False)]
        # If a mandatory checkout file is not present, the branch does not have
        # a functional checkout. Do not create a checkout in the converted
        # branch.
        for name, mandatory in checkout_files:
            if mandatory and name not in bzrcontents:
                has_checkout = False
                break
        else:
            has_checkout = True
        if not has_checkout:
            self.pb.note('No working tree.')
            # If some checkout files are there, we may as well get rid of them.
            for name, mandatory in checkout_files:
                if name in bzrcontents:
                    self.bzrdir.transport.delete(name)
        else:
            from bzrlib.workingtree import WorkingTreeFormat3
            self.step('Upgrading working tree')
            self.bzrdir.transport.mkdir('checkout', mode=self.dir_mode)
            self.make_lock('checkout')
            self.put_format(
                'checkout', WorkingTreeFormat3())
            self.bzrdir.transport.delete_multi(
                self.garbage_inventories, self.pb)
            for entry in checkout_files:
                self.move_entry('checkout', entry)
            if last_revision is not None:
                self.bzrdir.transport.put_bytes(
                    'checkout/last-revision', last_revision)
        self.bzrdir.transport.put_bytes(
            'branch-format',
            BzrDirMetaFormat1().get_format_string(),
            mode=self.file_mode)
        return BzrDir.open(self.bzrdir.root_transport.base)

    def make_lock(self, name):
        """Make a lock for the new control dir name."""
        self.step('Make %s lock' % name)
        ld = lockdir.LockDir(self.bzrdir.transport,
                             '%s/lock' % name,
                             file_modebits=self.file_mode,
                             dir_modebits=self.dir_mode)
        ld.create()

    def move_entry(self, new_dir, entry):
        """Move then entry name into new_dir."""
        name = entry[0]
        mandatory = entry[1]
        self.step('Moving %s' % name)
        try:
            self.bzrdir.transport.move(name, '%s/%s' % (new_dir, name))
        except errors.NoSuchFile:
            if mandatory:
                raise

    def put_format(self, dirname, format):
        self.bzrdir.transport.put_bytes('%s/format' % dirname,
            format.get_format_string(),
            self.file_mode)


class ConvertMetaToMeta(Converter):
    """Converts the components of metadirs."""

    def __init__(self, target_format):
        """Create a metadir to metadir converter.

        :param target_format: The final metadir format that is desired.
        """
        self.target_format = target_format

    def convert(self, to_convert, pb):
        """See Converter.convert()."""
        self.bzrdir = to_convert
        self.pb = pb
        self.count = 0
        self.total = 1
        self.step('checking repository format')
        try:
            repo = self.bzrdir.open_repository()
        except errors.NoRepositoryPresent:
            pass
        else:
            if not isinstance(repo._format, self.target_format.repository_format.__class__):
                from bzrlib.repository import CopyConverter
                self.pb.note('starting repository conversion')
                converter = CopyConverter(self.target_format.repository_format)
                converter.convert(repo, pb)
        try:
            branch = self.bzrdir.open_branch()
        except errors.NotBranchError:
            pass
        else:
            # TODO: conversions of Branch and Tree should be done by
            # InterXFormat lookups/some sort of registry.
            # Avoid circular imports
            from bzrlib import branch as _mod_branch
            old = branch._format.__class__
            new = self.target_format.get_branch_format().__class__
            while old != new:
                if (old == _mod_branch.BzrBranchFormat5 and
                    new in (_mod_branch.BzrBranchFormat6,
                        _mod_branch.BzrBranchFormat7)):
                    branch_converter = _mod_branch.Converter5to6()
                elif (old == _mod_branch.BzrBranchFormat6 and
                    new == _mod_branch.BzrBranchFormat7):
                    branch_converter = _mod_branch.Converter6to7()
                else:
                    raise errors.BadConversionTarget("No converter", new)
                branch_converter.convert(branch)
                branch = self.bzrdir.open_branch()
                old = branch._format.__class__
        try:
            tree = self.bzrdir.open_workingtree(recommend_upgrade=False)
        except (errors.NoWorkingTree, errors.NotLocalUrl):
            pass
        else:
            # TODO: conversions of Branch and Tree should be done by
            # InterXFormat lookups
            if (isinstance(tree, workingtree.WorkingTree3) and
                not isinstance(tree, workingtree_4.WorkingTree4) and
                isinstance(self.target_format.workingtree_format,
                    workingtree_4.WorkingTreeFormat4)):
                workingtree_4.Converter3to4().convert(tree)
        return to_convert


# This is not in remote.py because it's small, and needs to be registered.
# Putting it in remote.py creates a circular import problem.
# we can make it a lazy object if the control formats is turned into something
# like a registry.
class RemoteBzrDirFormat(BzrDirMetaFormat1):
    """Format representing bzrdirs accessed via a smart server"""

    def get_format_description(self):
        return 'bzr remote bzrdir'
    
    @classmethod
    def probe_transport(klass, transport):
        """Return a RemoteBzrDirFormat object if it looks possible."""
        try:
            medium = transport.get_smart_medium()
        except (NotImplementedError, AttributeError,
                errors.TransportNotPossible, errors.NoSmartMedium,
                errors.SmartProtocolError):
            # no smart server, so not a branch for this format type.
            raise errors.NotBranchError(path=transport.base)
        else:
            # Decline to open it if the server doesn't support our required
            # version (3) so that the VFS-based transport will do it.
            if medium.should_probe():
                try:
                    server_version = medium.protocol_version()
                except errors.SmartProtocolError:
                    # Apparently there's no usable smart server there, even though
                    # the medium supports the smart protocol.
                    raise errors.NotBranchError(path=transport.base)
                if server_version != '2':
                    raise errors.NotBranchError(path=transport.base)
            return klass()

    def initialize_on_transport(self, transport):
        try:
            # hand off the request to the smart server
            client_medium = transport.get_smart_medium()
        except errors.NoSmartMedium:
            # TODO: lookup the local format from a server hint.
            local_dir_format = BzrDirMetaFormat1()
            return local_dir_format.initialize_on_transport(transport)
        client = _SmartClient(client_medium)
        path = client.remote_path_from_transport(transport)
        response = client.call('BzrDirFormat.initialize', path)
        if response[0] != 'ok':
            raise errors.SmartProtocolError('unexpected response code %s' % (response,))
        return remote.RemoteBzrDir(transport)

    def _open(self, transport):
        return remote.RemoteBzrDir(transport)

    def __eq__(self, other):
        if not isinstance(other, RemoteBzrDirFormat):
            return False
        return self.get_format_description() == other.get_format_description()


BzrDirFormat.register_control_server_format(RemoteBzrDirFormat)


class BzrDirFormatInfo(object):

    def __init__(self, native, deprecated, hidden, experimental):
        self.deprecated = deprecated
        self.native = native
        self.hidden = hidden
        self.experimental = experimental


class BzrDirFormatRegistry(registry.Registry):
    """Registry of user-selectable BzrDir subformats.
    
    Differs from BzrDirFormat._control_formats in that it provides sub-formats,
    e.g. BzrDirMeta1 with weave repository.  Also, it's more user-oriented.
    """

    def __init__(self):
        """Create a BzrDirFormatRegistry."""
        self._aliases = set()
        super(BzrDirFormatRegistry, self).__init__()

    def aliases(self):
        """Return a set of the format names which are aliases."""
        return frozenset(self._aliases)

    def register_metadir(self, key,
             repository_format, help, native=True, deprecated=False,
             branch_format=None,
             tree_format=None,
             hidden=False,
             experimental=False,
             alias=False):
        """Register a metadir subformat.

        These all use a BzrDirMetaFormat1 bzrdir, but can be parameterized
        by the Repository format.

        :param repository_format: The fully-qualified repository format class
            name as a string.
        :param branch_format: Fully-qualified branch format class name as
            a string.
        :param tree_format: Fully-qualified tree format class name as
            a string.
        """
        # This should be expanded to support setting WorkingTree and Branch
        # formats, once BzrDirMetaFormat1 supports that.
        def _load(full_name):
            mod_name, factory_name = full_name.rsplit('.', 1)
            try:
                mod = __import__(mod_name, globals(), locals(),
                        [factory_name])
            except ImportError, e:
                raise ImportError('failed to load %s: %s' % (full_name, e))
            try:
                factory = getattr(mod, factory_name)
            except AttributeError:
                raise AttributeError('no factory %s in module %r'
                    % (full_name, mod))
            return factory()

        def helper():
            bd = BzrDirMetaFormat1()
            if branch_format is not None:
                bd.set_branch_format(_load(branch_format))
            if tree_format is not None:
                bd.workingtree_format = _load(tree_format)
            if repository_format is not None:
                bd.repository_format = _load(repository_format)
            return bd
        self.register(key, helper, help, native, deprecated, hidden,
            experimental, alias)

    def register(self, key, factory, help, native=True, deprecated=False,
                 hidden=False, experimental=False, alias=False):
        """Register a BzrDirFormat factory.
        
        The factory must be a callable that takes one parameter: the key.
        It must produce an instance of the BzrDirFormat when called.

        This function mainly exists to prevent the info object from being
        supplied directly.
        """
        registry.Registry.register(self, key, factory, help,
            BzrDirFormatInfo(native, deprecated, hidden, experimental))
        if alias:
            self._aliases.add(key)

    def register_lazy(self, key, module_name, member_name, help, native=True,
        deprecated=False, hidden=False, experimental=False, alias=False):
        registry.Registry.register_lazy(self, key, module_name, member_name,
            help, BzrDirFormatInfo(native, deprecated, hidden, experimental))
        if alias:
            self._aliases.add(key)

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
        output = textwrap.dedent("""\
            These formats can be used for creating branches, working trees, and
            repositories.

            """)
        default_realkey = None
        default_help = self.get_help('default')
        help_pairs = []
        for key in self.keys():
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
                    subsequent_indent='    '))
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
        if len(experimental_pairs) > 0:
            output += "Experimental formats are shown below.\n\n"
            for key, help in experimental_pairs:
                info = self.get_info(key)
                output += wrapped(key, help, info)
        if len(deprecated_pairs) > 0:
            output += "Deprecated formats are shown below.\n\n"
            for key, help in deprecated_pairs:
                info = self.get_info(key)
                output += wrapped(key, help, info)

        return output


class RepositoryAcquisitionPolicy(object):
    """Abstract base class for repository acquisition policies.

    A repository acquisition policy decides how a BzrDir acquires a repository
    for a branch that is being created.  The most basic policy decision is
    whether to create a new repository or use an existing one.
    """
    def __init__(self, stack_on, stack_on_pwd, require_stacking):
        """Constructor.

        :param stack_on: A location to stack on
        :param stack_on_pwd: If stack_on is relative, the location it is
            relative to.
        :param require_stacking: If True, it is a failure to not stack.
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
                stack_on = urlutils.rebase_url(self._stack_on,
                    self._stack_on_pwd,
                    branch.bzrdir.root_transport.base)
            except errors.InvalidRebaseURLs:
                stack_on = self._get_full_stack_on()
        try:
            branch.set_stacked_on_url(stack_on)
        except errors.UnstackableBranchFormat:
            if self._require_stacking:
                raise

    def _get_full_stack_on(self):
        """Get a fully-qualified URL for the stack_on location."""
        if self._stack_on is None:
            return None
        if self._stack_on_pwd is None:
            return self._stack_on
        else:
            return urlutils.join(self._stack_on_pwd, self._stack_on)

    def _add_fallback(self, repository):
        """Add a fallback to the supplied repository, if stacking is set."""
        stack_on = self._get_full_stack_on()
        if stack_on is None:
            return
        stacked_dir = BzrDir.open(stack_on)
        try:
            stacked_repo = stacked_dir.open_branch().repository
        except errors.NotBranchError:
            stacked_repo = stacked_dir.open_repository()
        try:
            repository.add_fallback_repository(stacked_repo)
        except errors.UnstackableRepositoryFormat:
            if self._require_stacking:
                raise

    def acquire_repository(self, make_working_trees=None, shared=False):
        """Acquire a repository for this bzrdir.

        Implementations may create a new repository or use a pre-exising
        repository.
        :param make_working_trees: If creating a repository, set
            make_working_trees to this value (if non-None)
        :param shared: If creating a repository, make it shared if True
        :return: A repository
        """
        raise NotImplemented(RepositoryAcquisitionPolicy.acquire_repository)


class CreateRepository(RepositoryAcquisitionPolicy):
    """A policy of creating a new repository"""

    def __init__(self, bzrdir, stack_on=None, stack_on_pwd=None,
                 require_stacking=False):
        """
        Constructor.
        :param bzrdir: The bzrdir to create the repository on.
        :param stack_on: A location to stack on
        :param stack_on_pwd: If stack_on is relative, the location it is
            relative to.
        """
        RepositoryAcquisitionPolicy.__init__(self, stack_on, stack_on_pwd,
                                             require_stacking)
        self._bzrdir = bzrdir

    def acquire_repository(self, make_working_trees=None, shared=False):
        """Implementation of RepositoryAcquisitionPolicy.acquire_repository

        Creates the desired repository in the bzrdir we already have.
        """
        if self._stack_on or self._require_stacking:
            # we may be coming from a format that doesn't support stacking,
            # but we require it in the destination, so force creation of a new
            # one here.
            #
            # TODO: perhaps this should be treated as a distinct repository
            # acquisition policy?
            repository_format = self._bzrdir._format.repository_format
            if not repository_format.supports_external_lookups:
                # should possibly be controlled by the registry rather than
                # hardcoded here.
                from bzrlib.repofmt import pack_repo
                if repository_format.rich_root_data:
                    repository_format = \
                        pack_repo.RepositoryFormatKnitPack5RichRoot()
                else:
                    repository_format = pack_repo.RepositoryFormatKnitPack5()
                note("using %r for stacking" % (repository_format,))
            repository = repository_format.initialize(self._bzrdir,
                shared=shared)
        else:
            # let bzrdir choose
            repository = self._bzrdir.create_repository(shared=shared)
        self._add_fallback(repository)
        if make_working_trees is not None:
            repository.set_make_working_trees(make_working_trees)
        return repository


class UseExistingRepository(RepositoryAcquisitionPolicy):
    """A policy of reusing an existing repository"""

    def __init__(self, repository, stack_on=None, stack_on_pwd=None,
                 require_stacking=False):
        """Constructor.

        :param repository: The repository to use.
        :param stack_on: A location to stack on
        :param stack_on_pwd: If stack_on is relative, the location it is
            relative to.
        """
        RepositoryAcquisitionPolicy.__init__(self, stack_on, stack_on_pwd,
                                             require_stacking)
        self._repository = repository

    def acquire_repository(self, make_working_trees=None, shared=False):
        """Implementation of RepositoryAcquisitionPolicy.acquire_repository

        Returns an existing repository to use
        """
        self._add_fallback(self._repository)
        return self._repository


format_registry = BzrDirFormatRegistry()
format_registry.register('weave', BzrDirFormat6,
    'Pre-0.8 format.  Slower than knit and does not'
    ' support checkouts or shared repositories.',
    deprecated=True)
format_registry.register_metadir('knit',
    'bzrlib.repofmt.knitrepo.RepositoryFormatKnit1',
    'Format using knits.  Recommended for interoperation with bzr <= 0.14.',
    branch_format='bzrlib.branch.BzrBranchFormat5',
    tree_format='bzrlib.workingtree.WorkingTreeFormat3')
format_registry.register_metadir('metaweave',
    'bzrlib.repofmt.weaverepo.RepositoryFormat7',
    'Transitional format in 0.8.  Slower than knit.',
    branch_format='bzrlib.branch.BzrBranchFormat5',
    tree_format='bzrlib.workingtree.WorkingTreeFormat3',
    deprecated=True)
format_registry.register_metadir('dirstate',
    'bzrlib.repofmt.knitrepo.RepositoryFormatKnit1',
    help='New in 0.15: Fast local operations. Compatible with bzr 0.8 and '
        'above when accessed over the network.',
    branch_format='bzrlib.branch.BzrBranchFormat5',
    # this uses bzrlib.workingtree.WorkingTreeFormat4 because importing
    # directly from workingtree_4 triggers a circular import.
    tree_format='bzrlib.workingtree.WorkingTreeFormat4',
    )
format_registry.register_metadir('dirstate-tags',
    'bzrlib.repofmt.knitrepo.RepositoryFormatKnit1',
    help='New in 0.15: Fast local operations and improved scaling for '
        'network operations. Additionally adds support for tags.'
        ' Incompatible with bzr < 0.15.',
    branch_format='bzrlib.branch.BzrBranchFormat6',
    tree_format='bzrlib.workingtree.WorkingTreeFormat4',
    )
format_registry.register_metadir('rich-root',
    'bzrlib.repofmt.knitrepo.RepositoryFormatKnit4',
    help='New in 1.0.  Better handling of tree roots.  Incompatible with'
        ' bzr < 1.0',
    branch_format='bzrlib.branch.BzrBranchFormat6',
    tree_format='bzrlib.workingtree.WorkingTreeFormat4',
    )
format_registry.register_metadir('dirstate-with-subtree',
    'bzrlib.repofmt.knitrepo.RepositoryFormatKnit3',
    help='New in 0.15: Fast local operations and improved scaling for '
        'network operations. Additionally adds support for versioning nested '
        'bzr branches. Incompatible with bzr < 0.15.',
    branch_format='bzrlib.branch.BzrBranchFormat6',
    tree_format='bzrlib.workingtree.WorkingTreeFormat4',
    experimental=True,
    hidden=True,
    )
format_registry.register_metadir('pack-0.92',
    'bzrlib.repofmt.pack_repo.RepositoryFormatKnitPack1',
    help='New in 0.92: Pack-based format with data compatible with '
        'dirstate-tags format repositories. Interoperates with '
        'bzr repositories before 0.92 but cannot be read by bzr < 0.92. '
        'Previously called knitpack-experimental.  '
        'For more information, see '
        'http://doc.bazaar-vcs.org/latest/developers/packrepo.html.',
    branch_format='bzrlib.branch.BzrBranchFormat6',
    tree_format='bzrlib.workingtree.WorkingTreeFormat4',
    )
format_registry.register_metadir('pack-0.92-subtree',
    'bzrlib.repofmt.pack_repo.RepositoryFormatKnitPack3',
    help='New in 0.92: Pack-based format with data compatible with '
        'dirstate-with-subtree format repositories. Interoperates with '
        'bzr repositories before 0.92 but cannot be read by bzr < 0.92. '
        'Previously called knitpack-experimental.  '
        'For more information, see '
        'http://doc.bazaar-vcs.org/latest/developers/packrepo.html.',
    branch_format='bzrlib.branch.BzrBranchFormat6',
    tree_format='bzrlib.workingtree.WorkingTreeFormat4',
    hidden=True,
    experimental=True,
    )
format_registry.register_metadir('rich-root-pack',
    'bzrlib.repofmt.pack_repo.RepositoryFormatKnitPack4',
    help='New in 1.0: Pack-based format with data compatible with '
        'rich-root format repositories. Incompatible with'
        ' bzr < 1.0',
    branch_format='bzrlib.branch.BzrBranchFormat6',
    tree_format='bzrlib.workingtree.WorkingTreeFormat4',
    )
format_registry.register_metadir('1.6',
    'bzrlib.repofmt.pack_repo.RepositoryFormatKnitPack5',
    help='A branch and pack based repository that supports stacking. ',
    branch_format='bzrlib.branch.BzrBranchFormat7',
    tree_format='bzrlib.workingtree.WorkingTreeFormat4',
    )
format_registry.register_metadir('1.6.1-rich-root',
    'bzrlib.repofmt.pack_repo.RepositoryFormatKnitPack5RichRoot',
    help='A branch and pack based repository that supports stacking '
         'and rich root data (needed for bzr-svn). ',
    branch_format='bzrlib.branch.BzrBranchFormat7',
    tree_format='bzrlib.workingtree.WorkingTreeFormat4',
    )
# The following two formats should always just be aliases.
format_registry.register_metadir('development',
    'bzrlib.repofmt.pack_repo.RepositoryFormatPackDevelopment1',
    help='Current development format. Can convert data to and from pack-0.92 '
        '(and anything compatible with pack-0.92) format repositories. '
        'Repositories and branches in this format can only be read by bzr.dev. '
        'Please read '
        'http://doc.bazaar-vcs.org/latest/developers/development-repo.html '
        'before use.',
    branch_format='bzrlib.branch.BzrBranchFormat7',
    tree_format='bzrlib.workingtree.WorkingTreeFormat4',
    experimental=True,
    alias=True,
    )
format_registry.register_metadir('development-subtree',
    'bzrlib.repofmt.pack_repo.RepositoryFormatPackDevelopment1Subtree',
    help='Current development format, subtree variant. Can convert data to and '
        'from pack-0.92-subtree (and anything compatible with '
        'pack-0.92-subtree) format repositories. Repositories and branches in '
        'this format can only be read by bzr.dev. Please read '
        'http://doc.bazaar-vcs.org/latest/developers/development-repo.html '
        'before use.',
    branch_format='bzrlib.branch.BzrBranchFormat7',
    tree_format='bzrlib.workingtree.WorkingTreeFormat4',
    experimental=True,
    alias=True,
    )
# And the development formats which the will have aliased one of follow:
format_registry.register_metadir('development0',
    'bzrlib.repofmt.pack_repo.RepositoryFormatPackDevelopment0',
    help='Trivial rename of pack-0.92 to provide a development format. '
        'Please read '
        'http://doc.bazaar-vcs.org/latest/developers/development-repo.html '
        'before use.',
    branch_format='bzrlib.branch.BzrBranchFormat6',
    tree_format='bzrlib.workingtree.WorkingTreeFormat4',
    hidden=True,
    experimental=True,
    )
format_registry.register_metadir('development0-subtree',
    'bzrlib.repofmt.pack_repo.RepositoryFormatPackDevelopment0Subtree',
    help='Trivial rename of pack-0.92-subtree to provide a development format. '
        'Please read '
        'http://doc.bazaar-vcs.org/latest/developers/development-repo.html '
        'before use.',
    branch_format='bzrlib.branch.BzrBranchFormat6',
    tree_format='bzrlib.workingtree.WorkingTreeFormat4',
    hidden=True,
    experimental=True,
    )
format_registry.register_metadir('development1',
    'bzrlib.repofmt.pack_repo.RepositoryFormatPackDevelopment1',
    help='A branch and pack based repository that supports stacking. '
        'Please read '
        'http://doc.bazaar-vcs.org/latest/developers/development-repo.html '
        'before use.',
    branch_format='bzrlib.branch.BzrBranchFormat7',
    tree_format='bzrlib.workingtree.WorkingTreeFormat4',
    hidden=True,
    experimental=True,
    )
format_registry.register_metadir('development1-subtree',
    'bzrlib.repofmt.pack_repo.RepositoryFormatPackDevelopment1Subtree',
    help='A branch and pack based repository that supports stacking. '
        'Please read '
        'http://doc.bazaar-vcs.org/latest/developers/development-repo.html '
        'before use.',
    branch_format='bzrlib.branch.BzrBranchFormat7',
    tree_format='bzrlib.workingtree.WorkingTreeFormat4',
    hidden=True,
    experimental=True,
    )
# The current format that is made on 'bzr init'.
format_registry.set_default('pack-0.92')
