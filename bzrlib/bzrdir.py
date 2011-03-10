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

"""BzrDir logic. The BzrDir is the basic control directory used by bzr.

At format 7 this was split out into Branch, Repository and Checkout control
directories.

Note: This module has a lot of ``open`` functions/methods that return
references to in-memory objects. As a rule, there are no matching ``close``
methods. To free any associated resources, simply stop referencing the
objects returned.
"""

# TODO: Move old formats into a plugin to make this file smaller.

import sys

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
from stat import S_ISDIR

import bzrlib
from bzrlib import (
    config,
    controldir,
    errors,
    graph,
    lockable_files,
    lockdir,
    osutils,
    pyutils,
    remote,
    repository,
    revision as _mod_revision,
    transport as _mod_transport,
    ui,
    urlutils,
    versionedfile,
    win32utils,
    workingtree,
    workingtree_4,
    )
from bzrlib.repofmt import pack_repo
from bzrlib.smart.client import _SmartClient
from bzrlib.transport import (
    do_catching_redirections,
    local,
    )
from bzrlib.weave import (
    WeaveFile,
    Weave,
    )
""")

from bzrlib.trace import (
    note,
    )

from bzrlib import (
    hooks,
    registry,
    )
from bzrlib.symbol_versioning import (
    deprecated_in,
    deprecated_method,
    )


class BzrDir(controldir.ControlDir):
    """A .bzr control diretory.

    BzrDir instances let you create or open any of the things that can be
    found within .bzr - checkouts, branches and repositories.

    :ivar transport:
        the transport which this bzr dir is rooted at (i.e. file:///.../.bzr/)
    :ivar root_transport:
        a transport connected to the directory this bzr was opened from
        (i.e. the parent directory holding the .bzr directory).

    Everything in the bzrdir should have the same file permissions.

    :cvar hooks: An instance of BzrDirHooks.
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

    def check_conversion_target(self, target_format):
        """Check that a bzrdir as a whole can be converted to a new format."""
        # The only current restriction is that the repository content can be 
        # fetched compatibly with the target.
        target_repo_format = target_format.repository_format
        try:
            self.open_repository()._format.check_conversion_target(
                target_repo_format)
        except errors.NoRepositoryPresent:
            # No repo, no problem.
            pass

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

    def clone_on_transport(self, transport, revision_id=None,
        force_new_repo=False, preserve_stacking=False, stacked_on=None,
        create_prefix=False, use_existing_dir=True, no_tree=False):
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
        :param no_tree: If set to true prevents creation of a working tree.
        """
        # Overview: put together a broad description of what we want to end up
        # with; then make as few api calls as possible to do it.

        # We may want to create a repo/branch/tree, if we do so what format
        # would we want for each:
        require_stacking = (stacked_on is not None)
        format = self.cloning_metadir(require_stacking)

        # Figure out what objects we want:
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
                    stacked_on = local_branch.get_stacked_on_url()
                except (errors.UnstackableBranchFormat,
                        errors.UnstackableRepositoryFormat,
                        errors.NotStacked):
                    pass
        # Bug: We create a metadir without knowing if it can support stacking,
        # we should look up the policy needs first, or just use it as a hint,
        # or something.
        if local_repo:
            make_working_trees = local_repo.make_working_trees() and not no_tree
            want_shared = local_repo.is_shared()
            repo_format_name = format.repository_format.network_name()
        else:
            make_working_trees = False
            want_shared = False
            repo_format_name = None

        result_repo, result, require_stacking, repository_policy = \
            format.initialize_on_transport_ex(transport,
            use_existing_dir=use_existing_dir, create_prefix=create_prefix,
            force_new_repo=force_new_repo, stacked_on=stacked_on,
            stack_on_pwd=self.root_transport.base,
            repo_format_name=repo_format_name,
            make_working_trees=make_working_trees, shared_repo=want_shared)
        if repo_format_name:
            try:
                # If the result repository is in the same place as the
                # resulting bzr dir, it will have no content, further if the
                # result is not stacked then we know all content should be
                # copied, and finally if we are copying up to a specific
                # revision_id then we can use the pending-ancestry-result which
                # does not require traversing all of history to describe it.
                if (result_repo.user_url == result.user_url
                    and not require_stacking and
                    revision_id is not None):
                    fetch_spec = graph.PendingAncestryResult(
                        [revision_id], local_repo)
                    result_repo.fetch(local_repo, fetch_spec=fetch_spec)
                else:
                    result_repo.fetch(local_repo, revision_id=revision_id)
            finally:
                result_repo.unlock()
        else:
            if result_repo is not None:
                raise AssertionError('result_repo not None(%r)' % result_repo)
        # 1 if there is a branch present
        #   make sure its content is available in the target repository
        #   clone it.
        if local_branch is not None:
            result_branch = local_branch.clone(result, revision_id=revision_id,
                repository_policy=repository_policy)
        try:
            # Cheaper to check if the target is not local, than to try making
            # the tree and fail.
            result.root_transport.local_abspath('.')
            if result_repo is None or result_repo.make_working_trees():
                self.open_workingtree().clone(result)
        except (errors.NoWorkingTree, errors.NotLocalUrl):
            pass
        return result

    # TODO: This should be given a Transport, and should chdir up; otherwise
    # this will open a new connection.
    def _make_tail(self, url):
        t = _mod_transport.get_transport(url)
        t.ensure_base()

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
            except (errors.NotBranchError, errors.PermissionDenied):
                pass
            else:
                recurse, value = evaluate(bzrdir)
                yield value
            try:
                subdirs = list_current(current_transport)
            except (errors.NoSuchFile, errors.PermissionDenied):
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
                return False, ([], repository)
            return True, (bzrdir.list_branches(), None)
        ret = []
        for branches, repo in BzrDir.find_bzrdirs(transport,
                                                  evaluate=evaluate):
            if repo is not None:
                ret.extend(repo.find_branches())
            if branches is not None:
                ret.extend(branches)
        return ret

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

        This controls whether a new repository is created, and the format of
        that repository, or some existing shared repository used instead.

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
            config = found_bzrdir.get_config()
            stop = False
            stack_on = config.get_default_stack_on()
            if stack_on is not None:
                stack_on_pwd = found_bzrdir.user_url
                stop = True
            # does it have a repository ?
            try:
                repository = found_bzrdir.open_repository()
            except errors.NoRepositoryPresent:
                repository = None
            else:
                if (found_bzrdir.user_url != self.user_url 
                    and not repository.is_shared()):
                    # Don't look higher, can't use a higher shared repo.
                    repository = None
                    stop = True
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
        return policy.acquire_repository()[0]

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
            t = _mod_transport.get_transport(base, possible_transports)
            if not isinstance(t, local.LocalTransport):
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
        t = _mod_transport.get_transport(base)
        if not isinstance(t, local.LocalTransport):
            raise errors.NotLocalUrl(base)
        bzrdir = BzrDir.create_branch_and_repo(base,
                                               force_new_repo=True,
                                               format=format).bzrdir
        return bzrdir.create_workingtree()

    @deprecated_method(deprecated_in((2, 3, 0)))
    def generate_backup_name(self, base):
        return self._available_backup_name(base)

    def _available_backup_name(self, base):
        """Find a non-existing backup file name based on base.

        See bzrlib.osutils.available_backup_name about race conditions.
        """
        return osutils.available_backup_name(base, self.root_transport.has)

    def backup_bzrdir(self):
        """Backup this bzr control directory.

        :return: Tuple with old path name and new path name
        """

        pb = ui.ui_factory.nested_progress_bar()
        try:
            old_path = self.root_transport.abspath('.bzr')
            backup_dir = self._available_backup_name('backup.bzr')
            new_path = self.root_transport.abspath(backup_dir)
            ui.ui_factory.note('making backup of %s\n  to %s'
                               % (old_path, new_path,))
            self.root_transport.copy_tree('.bzr', backup_dir)
            return (old_path, new_path)
        finally:
            pb.finished()

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
            if (found_bzrdir.user_url == next_transport.base):
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
            if found_bzrdir.user_url == self.user_url:
                return repository, True
            elif repository.is_shared():
                return repository, True
            else:
                return None, True

        found_repo = self._find_containing(usable_repository)
        if found_repo is None:
            raise errors.NoRepositoryPresent(self)
        return found_repo

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
            if (st.st_mode & 07777 == 00000):
                # FTP allows stat but does not return dir/file modes
                self._dir_mode = None
                self._file_mode = None
            else:
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

    def get_config(self):
        """Get configuration for this BzrDir."""
        return config.BzrDirConfig(self)

    def _get_config(self):
        """By default, no configuration is available."""
        return None

    def __init__(self, _transport, _format):
        """Initialize a Bzr control dir object.

        Only really common logic should reside here, concrete classes should be
        made with varying behaviours.

        :param _format: the format that is creating this BzrDir instance.
        :param _transport: the transport this dir is based at.
        """
        self._format = _format
        # these are also under the more standard names of 
        # control_transport and user_transport
        self.transport = _transport.clone('.bzr')
        self.root_transport = _transport
        self._mode_check_done = False

    @property 
    def user_transport(self):
        return self.root_transport

    @property
    def control_transport(self):
        return self.transport

    def is_control_filename(self, filename):
        """True if filename is the name of a path which is reserved for bzrdir's.

        :param filename: A filename within the root transport of this bzrdir.

        This is true IF and ONLY IF the filename is part of the namespace reserved
        for bzr control dirs. Currently this is the '.bzr' directory in the root
        of the root_transport. 
        """
        # this might be better on the BzrDirFormat class because it refers to
        # all the possible bzrdir disk formats.
        # This method is tested via the workingtree is_control_filename tests-
        # it was extracted from WorkingTree.is_control_filename. If the method's
        # contract is extended beyond the current trivial implementation, please
        # add new tests for it to the appropriate place.
        return filename == '.bzr' or filename.startswith('.bzr/')

    @staticmethod
    def open_unsupported(base):
        """Open a branch which is not supported."""
        return BzrDir.open(base, _unsupported=True)

    @staticmethod
    def open(base, _unsupported=False, possible_transports=None):
        """Open an existing bzrdir, rooted at 'base' (url).

        :param _unsupported: a private parameter to the BzrDir class.
        """
        t = _mod_transport.get_transport(base, possible_transports)
        return BzrDir.open_from_transport(t, _unsupported=_unsupported)

    @staticmethod
    def open_from_transport(transport, _unsupported=False,
                            _server_formats=True):
        """Open a bzrdir within a particular directory.

        :param transport: Transport containing the bzrdir.
        :param _unsupported: private.
        """
        for hook in BzrDir.hooks['pre_open']:
            hook(transport)
        # Keep initial base since 'transport' may be modified while following
        # the redirections.
        base = transport.base
        def find_format(transport):
            return transport, controldir.ControlDirFormat.find_format(
                transport, _server_formats=_server_formats)

        def redirected(transport, e, redirection_notice):
            redirected_transport = transport._redirected_to(e.source, e.target)
            if redirected_transport is None:
                raise errors.NotBranchError(base)
            note('%s is%s redirected to %s',
                 transport.base, e.permanently, redirected_transport.base)
            return redirected_transport

        try:
            transport, format = do_catching_redirections(find_format,
                                                         transport,
                                                         redirected)
        except errors.TooManyRedirections:
            raise errors.NotBranchError(base)

        BzrDir._check_supported(format, _unsupported)
        return format.open(transport, _found=True)

    @staticmethod
    def open_containing(url, possible_transports=None):
        """Open an existing branch which contains url.

        :param url: url to search from.
        See open_containing_from_transport for more detail.
        """
        transport = _mod_transport.get_transport(url, possible_transports)
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

    def _cloning_metadir(self):
        """Produce a metadir suitable for cloning with.

        :returns: (destination_bzrdir_format, source_repository)
        """
        result_format = self._format.__class__()
        try:
            try:
                branch = self.open_branch(ignore_fallbacks=True)
                source_repository = branch.repository
                result_format._branch_format = branch._format
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
            if isinstance(repo_format, remote.RemoteRepositoryFormat):
                source_repository._ensure_real()
                repo_format = source_repository._real_repository._format
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
        format, repository = self._cloning_metadir()
        if format._workingtree_format is None:
            # No tree in self.
            if repository is None:
                # No repository either
                return format
            # We have a repository, so set a working tree? (Why? This seems to
            # contradict the stated return value in the docstring).
            tree_format = repository._format._matchingbzrdir.workingtree_format
            format.workingtree_format = tree_format.__class__()
        if require_stacking:
            format.require_stacking()
        return format

    @classmethod
    def create(cls, base, format=None, possible_transports=None):
        """Create a new BzrDir at the url 'base'.

        :param format: If supplied, the format of branch to create.  If not
            supplied, the default is used.
        :param possible_transports: If supplied, a list of transports that
            can be reused to share a remote connection.
        """
        if cls is not BzrDir:
            raise AssertionError("BzrDir.create always creates the"
                "default format, not one of %r" % cls)
        t = _mod_transport.get_transport(base, possible_transports)
        t.ensure_base()
        if format is None:
            format = controldir.ControlDirFormat.get_default_format()
        return format.initialize_on_transport(t)

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


class BzrDirHooks(hooks.Hooks):
    """Hooks for BzrDir operations."""

    def __init__(self):
        """Create the default hooks."""
        hooks.Hooks.__init__(self)
        self.create_hook(hooks.HookPoint('pre_open',
            "Invoked before attempting to open a BzrDir with the transport "
            "that the open will use.", (1, 14), None))
        self.create_hook(hooks.HookPoint('post_repo_init',
            "Invoked after a repository has been initialized. "
            "post_repo_init is called with a "
            "bzrlib.bzrdir.RepoInitHookParams.",
            (2, 2), None))

# install the default hooks
BzrDir.hooks = BzrDirHooks()


class RepoInitHookParams(object):
    """Object holding parameters passed to *_repo_init hooks.

    There are 4 fields that hooks may wish to access:

    :ivar repository: Repository created
    :ivar format: Repository format
    :ivar bzrdir: The bzrdir for the repository
    :ivar shared: The repository is shared
    """

    def __init__(self, repository, format, a_bzrdir, shared):
        """Create a group of RepoInitHook parameters.

        :param repository: Repository created
        :param format: Repository format
        :param bzrdir: The bzrdir for the repository
        :param shared: The repository is shared
        """
        self.repository = repository
        self.format = format
        self.bzrdir = a_bzrdir
        self.shared = shared

    def __eq__(self, other):
        return self.__dict__ == other.__dict__

    def __repr__(self):
        if self.repository:
            return "<%s for %s>" % (self.__class__.__name__,
                self.repository)
        else:
            return "<%s for %s>" % (self.__class__.__name__,
                self.bzrdir)


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

    def create_branch(self, name=None, repository=None):
        """See BzrDir.create_branch."""
        return self._format.get_branch_format().initialize(self, name=name,
                repository=repository)

    def destroy_branch(self, name=None):
        """See BzrDir.create_branch."""
        if name is not None:
            raise errors.NoColocatedBranchSupport(self)
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
        # We ignore the conflicts returned by wt.revert since we're about to
        # delete the wt metadata anyway, all that should be left here are
        # detritus. But see bug #634470 about subtree .bzr dirs.
        conflicts = wt.revert(old_tree=empty)
        self.destroy_workingtree_metadata()

    def destroy_workingtree_metadata(self):
        self.transport.delete_tree('checkout')

    def find_branch_format(self, name=None):
        """Find the branch 'format' for this bzrdir.

        This might be a synthetic object for e.g. RemoteBranch and SVN.
        """
        from bzrlib.branch import BranchFormat
        return BranchFormat.find_format(self, name=name)

    def _get_mkdir_mode(self):
        """Figure out the mode to use when creating a bzrdir subdir."""
        temp_control = lockable_files.LockableFiles(self.transport, '',
                                     lockable_files.TransportLock)
        return temp_control._dir_mode

    def get_branch_reference(self, name=None):
        """See BzrDir.get_branch_reference()."""
        from bzrlib.branch import BranchFormat
        format = BranchFormat.find_format(self, name=name)
        return format.get_reference(self, name=name)

    def get_branch_transport(self, branch_format, name=None):
        """See BzrDir.get_branch_transport()."""
        if name is not None:
            raise errors.NoColocatedBranchSupport(self)
        # XXX: this shouldn't implicitly create the directory if it's just
        # promising to get a transport -- mbp 20090727
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

    def has_workingtree(self):
        """Tell if this bzrdir contains a working tree.

        This will still raise an exception if the bzrdir has a workingtree that
        is remote & inaccessible.

        Note: if you're going to open the working tree, you should just go
        ahead and try, and not ask permission first.
        """
        from bzrlib.workingtree import WorkingTreeFormat
        try:
            WorkingTreeFormat.find_format(self)
        except errors.NoWorkingTree:
            return False
        return True

    def needs_format_conversion(self, format):
        """See BzrDir.needs_format_conversion()."""
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
        for branch in self.list_branches():
            if not isinstance(branch._format,
                              format.get_branch_format().__class__):
                # the branch needs an upgrade.
                return True
        try:
            my_wt = self.open_workingtree(recommend_upgrade=False)
            if not isinstance(my_wt._format,
                              format.workingtree_format.__class__):
                # the workingtree needs an upgrade.
                return True
        except (errors.NoWorkingTree, errors.NotLocalUrl):
            pass
        return False

    def open_branch(self, name=None, unsupported=False,
                    ignore_fallbacks=False):
        """See BzrDir.open_branch."""
        format = self.find_branch_format(name=name)
        self._check_supported(format, unsupported)
        return format.open(self, name=name,
            _found=True, ignore_fallbacks=ignore_fallbacks)

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
        return config.TransportConfig(self.transport, 'control.conf')


class BzrProber(controldir.Prober):
    """Prober for formats that use a .bzr/ control directory."""

    formats = registry.FormatRegistry(controldir.network_format_registry)
    """The known .bzr formats."""

    @classmethod
    @deprecated_method(deprecated_in((2, 4, 0)))
    def register_bzrdir_format(klass, format):
        klass.formats.register(format.get_format_string(), format)

    @classmethod
    @deprecated_method(deprecated_in((2, 4, 0)))
    def unregister_bzrdir_format(klass, format):
        klass.formats.remove(format.get_format_string())

    @classmethod
    def probe_transport(klass, transport):
        """Return the .bzrdir style format present in a directory."""
        try:
            format_string = transport.get_bytes(".bzr/branch-format")
        except errors.NoSuchFile:
            raise errors.NotBranchError(path=transport.base)
        try:
            return klass.formats.get(format_string)
        except KeyError:
            raise errors.UnknownFormatError(format=format_string, kind='bzrdir')


controldir.ControlDirFormat.register_prober(BzrProber)


class RemoteBzrProber(controldir.Prober):
    """Prober for remote servers that provide a Bazaar smart server."""

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
            return RemoteBzrDirFormat()


class BzrDirFormat(controldir.ControlDirFormat):
    """ControlDirFormat base class for .bzr/ directories.

    Formats are placed in a dict by their format string for reference
    during bzrdir opening. These should be subclasses of BzrDirFormat
    for consistency.

    Once a format is deprecated, just deprecate the initialize and open
    methods on the format class. Do not deprecate the object, as the
    object will be created every system load.
    """

    _lock_file_name = 'branch-lock'

    # _lock_class must be set in subclasses to the lock type, typ.
    # TransportLock or LockDir

    def get_format_string(self):
        """Return the ASCII format string that identifies this format."""
        raise NotImplementedError(self.get_format_string)

    def initialize_on_transport(self, transport):
        """Initialize a new bzrdir in the base directory of a Transport."""
        try:
            # can we hand off the request to the smart server rather than using
            # vfs calls?
            client_medium = transport.get_smart_medium()
        except errors.NoSmartMedium:
            return self._initialize_on_transport_vfs(transport)
        else:
            # Current RPC's only know how to create bzr metadir1 instances, so
            # we still delegate to vfs methods if the requested format is not a
            # metadir1
            if type(self) != BzrDirMetaFormat1:
                return self._initialize_on_transport_vfs(transport)
            remote_format = RemoteBzrDirFormat()
            self._supply_sub_formats_to(remote_format)
            return remote_format.initialize_on_transport(transport)

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
        :return: repo, bzrdir, require_stacking, repository_policy. repo is
            None if none was created or found, bzrdir is always valid.
            require_stacking is the result of examining the stacked_on
            parameter and any stacking policy found for the target.
        """
        if not vfs_only:
            # Try to hand off to a smart server 
            try:
                client_medium = transport.get_smart_medium()
            except errors.NoSmartMedium:
                pass
            else:
                # TODO: lookup the local format from a server hint.
                remote_dir_format = RemoteBzrDirFormat()
                remote_dir_format._network_name = self.network_name()
                self._supply_sub_formats_to(remote_dir_format)
                return remote_dir_format.initialize_on_transport_ex(transport,
                    use_existing_dir=use_existing_dir, create_prefix=create_prefix,
                    force_new_repo=force_new_repo, stacked_on=stacked_on,
                    stack_on_pwd=stack_on_pwd, repo_format_name=repo_format_name,
                    make_working_trees=make_working_trees, shared_repo=shared_repo)
        # XXX: Refactor the create_prefix/no_create_prefix code into a
        #      common helper function
        # The destination may not exist - if so make it according to policy.
        def make_directory(transport):
            transport.mkdir('.')
            return transport
        def redirected(transport, e, redirection_notice):
            note(redirection_notice)
            return transport._redirected_to(e.source, e.target)
        try:
            transport = do_catching_redirections(make_directory, transport,
                redirected)
        except errors.FileExists:
            if not use_existing_dir:
                raise
        except errors.NoSuchFile:
            if not create_prefix:
                raise
            transport.create_prefix()

        require_stacking = (stacked_on is not None)
        # Now the target directory exists, but doesn't have a .bzr
        # directory. So we need to create it, along with any work to create
        # all of the dependent branches, etc.

        result = self.initialize_on_transport(transport)
        if repo_format_name:
            try:
                # use a custom format
                result._format.repository_format = \
                    repository.network_format_registry.get(repo_format_name)
            except AttributeError:
                # The format didn't permit it to be set.
                pass
            # A repository is desired, either in-place or shared.
            repository_policy = result.determine_repository_policy(
                force_new_repo, stacked_on, stack_on_pwd,
                require_stacking=require_stacking)
            result_repo, is_new_repo = repository_policy.acquire_repository(
                make_working_trees, shared_repo)
            if not require_stacking and repository_policy._require_stacking:
                require_stacking = True
                result._format.require_stacking()
            result_repo.lock_write()
        else:
            result_repo = None
            repository_policy = None
        return result_repo, result, require_stacking, repository_policy

    def _initialize_on_transport_vfs(self, transport):
        """Initialize a new bzrdir using VFS calls.

        :param transport: The transport to create the .bzr directory in.
        :return: A
        """
        # Since we are creating a .bzr directory, inherit the
        # mode from the root directory
        temp_control = lockable_files.LockableFiles(transport,
                            '', lockable_files.TransportLock)
        temp_control._transport.mkdir('.bzr',
                                      # FIXME: RBC 20060121 don't peek under
                                      # the covers
                                      mode=temp_control._dir_mode)
        if sys.platform == 'win32' and isinstance(transport, local.LocalTransport):
            win32utils.set_file_attr_hidden(transport._abspath('.bzr'))
        file_mode = temp_control._file_mode
        del temp_control
        bzrdir_transport = transport.clone('.bzr')
        utf8_files = [('README',
                       "This is a Bazaar control directory.\n"
                       "Do not change any files in this directory.\n"
                       "See http://bazaar.canonical.com/ for more information about Bazaar.\n"),
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

    def open(self, transport, _found=False):
        """Return an instance of this format for the dir transport points at.

        _found is a private parameter, do not use it.
        """
        if not _found:
            found_format = controldir.ControlDirFormat.find_format(transport)
            if not isinstance(found_format, self.__class__):
                raise AssertionError("%s was asked to open %s, but it seems to need "
                        "format %s"
                        % (self, transport, found_format))
            # Allow subclasses - use the found format.
            self._supply_sub_formats_to(found_format)
            return found_format._open(transport)
        return self._open(transport)

    def _open(self, transport):
        """Template method helper for opening BzrDirectories.

        This performs the actual open and any additional logic or parameter
        passing.
        """
        raise NotImplementedError(self._open)

    @classmethod
    def register_format(klass, format):
        """Register a new BzrDir format.
        """
        BzrProber.formats.register(format.get_format_string(), format)
        controldir.ControlDirFormat.register_format(
            format.get_format_string(), format)

    @classmethod
    def register_lazy_format(klass, format_string, module_name, member_name):
        """Lazily register a new BzrDir format.

        :param format_string: Format string
        :param module_name: Name of module with the BzrDirFormat subclass
        :param member_name: Class name of the BzrDirFormat
        """
        BzrProber.formats.register_lazy(format_string, module_name,
            member_name)
        controldir.ControlDirFormat.register_lazy_format(format_string,
            module_name, member_name)

    def _supply_sub_formats_to(self, other_format):
        """Give other_format the same values for sub formats as this has.

        This method is expected to be used when parameterising a
        RemoteBzrDirFormat instance with the parameters from a
        BzrDirMetaFormat1 instance.

        :param other_format: other_format is a format which should be
            compatible with whatever sub formats are supported by self.
        :return: None.
        """

    @classmethod
    def unregister_format(klass, format):
        BzrProber.formats.remove(format.get_format_string())
        controldir.ControlDirFormat.unregister_format(format.get_format_string())


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

    fixed_components = False

    def __init__(self):
        self._workingtree_format = None
        self._branch_format = None
        self._repository_format = None

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
            from bzrlib.branch import format_registry as branch_format_registry
            self._branch_format = branch_format_registry.get_default()
        return self._branch_format

    def set_branch_format(self, format):
        self._branch_format = format

    def require_stacking(self, stack_on=None, possible_transports=None,
            _skip_repo=False):
        """We have a request to stack, try to ensure the formats support it.

        :param stack_on: If supplied, it is the URL to a branch that we want to
            stack on. Check to see if that format supports stacking before
            forcing an upgrade.
        """
        # Stacking is desired. requested by the target, but does the place it
        # points at support stacking? If it doesn't then we should
        # not implicitly upgrade. We check this here.
        new_repo_format = None
        new_branch_format = None

        # a bit of state for get_target_branch so that we don't try to open it
        # 2 times, for both repo *and* branch
        target = [None, False, None] # target_branch, checked, upgrade anyway
        def get_target_branch():
            if target[1]:
                # We've checked, don't check again
                return target
            if stack_on is None:
                # No target format, that means we want to force upgrading
                target[:] = [None, True, True]
                return target
            try:
                target_dir = BzrDir.open(stack_on,
                    possible_transports=possible_transports)
            except errors.NotBranchError:
                # Nothing there, don't change formats
                target[:] = [None, True, False]
                return target
            except errors.JailBreak:
                # JailBreak, JFDI and upgrade anyway
                target[:] = [None, True, True]
                return target
            try:
                target_branch = target_dir.open_branch()
            except errors.NotBranchError:
                # No branch, don't upgrade formats
                target[:] = [None, True, False]
                return target
            target[:] = [target_branch, True, False]
            return target

        if (not _skip_repo and
                 not self.repository_format.supports_external_lookups):
            # We need to upgrade the Repository.
            target_branch, _, do_upgrade = get_target_branch()
            if target_branch is None:
                # We don't have a target branch, should we upgrade anyway?
                if do_upgrade:
                    # stack_on is inaccessible, JFDI.
                    # TODO: bad monkey, hard-coded formats...
                    if self.repository_format.rich_root_data:
                        new_repo_format = pack_repo.RepositoryFormatKnitPack5RichRoot()
                    else:
                        new_repo_format = pack_repo.RepositoryFormatKnitPack5()
            else:
                # If the target already supports stacking, then we know the
                # project is already able to use stacking, so auto-upgrade
                # for them
                new_repo_format = target_branch.repository._format
                if not new_repo_format.supports_external_lookups:
                    # target doesn't, source doesn't, so don't auto upgrade
                    # repo
                    new_repo_format = None
            if new_repo_format is not None:
                self.repository_format = new_repo_format
                note('Source repository format does not support stacking,'
                     ' using format:\n  %s',
                     new_repo_format.get_format_description())

        if not self.get_branch_format().supports_stacking():
            # We just checked the repo, now lets check if we need to
            # upgrade the branch format
            target_branch, _, do_upgrade = get_target_branch()
            if target_branch is None:
                if do_upgrade:
                    # TODO: bad monkey, hard-coded formats...
                    from bzrlib.branch import BzrBranchFormat7
                    new_branch_format = BzrBranchFormat7()
            else:
                new_branch_format = target_branch._format
                if not new_branch_format.supports_stacking():
                    new_branch_format = None
            if new_branch_format is not None:
                # Does support stacking, use its format.
                self.set_branch_format(new_branch_format)
                note('Source branch format does not support stacking,'
                     ' using format:\n  %s',
                     new_branch_format.get_format_description())

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

    def network_name(self):
        return self.get_format_string()

    def _open(self, transport):
        """See BzrDirFormat._open."""
        # Create a new format instance because otherwise initialisation of new
        # metadirs share the global default format object leading to alias
        # problems.
        format = BzrDirMetaFormat1()
        self._supply_sub_formats_to(format)
        return BzrDirMeta1(transport, format)

    def __return_repository_format(self):
        """Circular import protection."""
        if self._repository_format:
            return self._repository_format
        from bzrlib.repository import format_registry
        return format_registry.get_default()

    def _set_repository_format(self, value):
        """Allow changing the repository format for metadir formats."""
        self._repository_format = value

    repository_format = property(__return_repository_format,
        _set_repository_format)

    def _supply_sub_formats_to(self, other_format):
        """Give other_format the same values for sub formats as this has.

        This method is expected to be used when parameterising a
        RemoteBzrDirFormat instance with the parameters from a
        BzrDirMetaFormat1 instance.

        :param other_format: other_format is a format which should be
            compatible with whatever sub formats are supported by self.
        :return: None.
        """
        if getattr(self, '_repository_format', None) is not None:
            other_format.repository_format = self.repository_format
        if self._branch_format is not None:
            other_format._branch_format = self._branch_format
        if self._workingtree_format is not None:
            other_format.workingtree_format = self.workingtree_format

    def __get_workingtree_format(self):
        if self._workingtree_format is None:
            from bzrlib.workingtree import (
                format_registry as wt_format_registry,
                )
            self._workingtree_format = wt_format_registry.get_default()
        return self._workingtree_format

    def __set_workingtree_format(self, wt_format):
        self._workingtree_format = wt_format

    workingtree_format = property(__get_workingtree_format,
                                  __set_workingtree_format)


# Register bzr formats
BzrDirFormat.register_lazy_format(
    "Bazaar-NG branch, format 0.0.4\n", "bzrlib.bzrdir_weave",
    "BzrDirFormat4")
BzrDirFormat.register_lazy_format(
    "Bazaar-NG branch, format 5\n", "bzrlib.bzrdir_weave",
    "BzrDirFormat5")
BzrDirFormat.register_lazy_format(
    "Bazaar-NG branch, format 6\n", "bzrlib.bzrdir_weave",
    "BzrDirFormat6")
__default_format = BzrDirMetaFormat1()
BzrDirFormat.register_format(__default_format)
controldir.ControlDirFormat._default_format = __default_format


class ConvertMetaToMeta(controldir.Converter):
    """Converts the components of metadirs."""

    def __init__(self, target_format):
        """Create a metadir to metadir converter.

        :param target_format: The final metadir format that is desired.
        """
        self.target_format = target_format

    def convert(self, to_convert, pb):
        """See Converter.convert()."""
        self.bzrdir = to_convert
        self.pb = ui.ui_factory.nested_progress_bar()
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
                ui.ui_factory.note('starting repository conversion')
                converter = CopyConverter(self.target_format.repository_format)
                converter.convert(repo, pb)
        for branch in self.bzrdir.list_branches():
            # TODO: conversions of Branch and Tree should be done by
            # InterXFormat lookups/some sort of registry.
            # Avoid circular imports
            from bzrlib import branch as _mod_branch
            old = branch._format.__class__
            new = self.target_format.get_branch_format().__class__
            while old != new:
                if (old == _mod_branch.BzrBranchFormat5 and
                    new in (_mod_branch.BzrBranchFormat6,
                        _mod_branch.BzrBranchFormat7,
                        _mod_branch.BzrBranchFormat8)):
                    branch_converter = _mod_branch.Converter5to6()
                elif (old == _mod_branch.BzrBranchFormat6 and
                    new in (_mod_branch.BzrBranchFormat7,
                            _mod_branch.BzrBranchFormat8)):
                    branch_converter = _mod_branch.Converter6to7()
                elif (old == _mod_branch.BzrBranchFormat7 and
                      new is _mod_branch.BzrBranchFormat8):
                    branch_converter = _mod_branch.Converter7to8()
                else:
                    raise errors.BadConversionTarget("No converter", new,
                        branch._format)
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
                not isinstance(tree, workingtree_4.DirStateWorkingTree) and
                isinstance(self.target_format.workingtree_format,
                    workingtree_4.DirStateWorkingTreeFormat)):
                workingtree_4.Converter3to4().convert(tree)
            if (isinstance(tree, workingtree_4.DirStateWorkingTree) and
                not isinstance(tree, workingtree_4.WorkingTree5) and
                isinstance(self.target_format.workingtree_format,
                    workingtree_4.WorkingTreeFormat5)):
                workingtree_4.Converter4to5().convert(tree)
            if (isinstance(tree, workingtree_4.DirStateWorkingTree) and
                not isinstance(tree, workingtree_4.WorkingTree6) and
                isinstance(self.target_format.workingtree_format,
                    workingtree_4.WorkingTreeFormat6)):
                workingtree_4.Converter4or5to6().convert(tree)
        self.pb.finished()
        return to_convert


# This is not in remote.py because it's relatively small, and needs to be
# registered. Putting it in remote.py creates a circular import problem.
# we can make it a lazy object if the control formats is turned into something
# like a registry.
class RemoteBzrDirFormat(BzrDirMetaFormat1):
    """Format representing bzrdirs accessed via a smart server"""

    supports_workingtrees = False

    def __init__(self):
        BzrDirMetaFormat1.__init__(self)
        # XXX: It's a bit ugly that the network name is here, because we'd
        # like to believe that format objects are stateless or at least
        # immutable,  However, we do at least avoid mutating the name after
        # it's returned.  See <https://bugs.launchpad.net/bzr/+bug/504102>
        self._network_name = None

    def __repr__(self):
        return "%s(_network_name=%r)" % (self.__class__.__name__,
            self._network_name)

    def get_format_description(self):
        if self._network_name:
            real_format = controldir.network_format_registry.get(self._network_name)
            return 'Remote: ' + real_format.get_format_description()
        return 'bzr remote bzrdir'

    def get_format_string(self):
        raise NotImplementedError(self.get_format_string)

    def network_name(self):
        if self._network_name:
            return self._network_name
        else:
            raise AssertionError("No network name set.")

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
        try:
            response = client.call('BzrDirFormat.initialize', path)
        except errors.ErrorFromSmartServer, err:
            remote._translate_error(err, path=path)
        if response[0] != 'ok':
            raise errors.SmartProtocolError('unexpected response code %s' % (response,))
        format = RemoteBzrDirFormat()
        self._supply_sub_formats_to(format)
        return remote.RemoteBzrDir(transport, format)

    def parse_NoneTrueFalse(self, arg):
        if not arg:
            return None
        if arg == 'False':
            return False
        if arg == 'True':
            return True
        raise AssertionError("invalid arg %r" % arg)

    def _serialize_NoneTrueFalse(self, arg):
        if arg is False:
            return 'False'
        if arg:
            return 'True'
        return ''

    def _serialize_NoneString(self, arg):
        return arg or ''

    def initialize_on_transport_ex(self, transport, use_existing_dir=False,
        create_prefix=False, force_new_repo=False, stacked_on=None,
        stack_on_pwd=None, repo_format_name=None, make_working_trees=None,
        shared_repo=False):
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
                    if server_version != '2':
                        do_vfs = True
                    else:
                        do_vfs = False
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
            local_dir_format = BzrDirMetaFormat1()
            self._supply_sub_formats_to(local_dir_format)
            return local_dir_format.initialize_on_transport_ex(transport,
                use_existing_dir=use_existing_dir, create_prefix=create_prefix,
                force_new_repo=force_new_repo, stacked_on=stacked_on,
                stack_on_pwd=stack_on_pwd, repo_format_name=repo_format_name,
                make_working_trees=make_working_trees, shared_repo=shared_repo,
                vfs_only=True)
        return self._initialize_on_transport_ex_rpc(client, path, transport,
            use_existing_dir, create_prefix, force_new_repo, stacked_on,
            stack_on_pwd, repo_format_name, make_working_trees, shared_repo)

    def _initialize_on_transport_ex_rpc(self, client, path, transport,
        use_existing_dir, create_prefix, force_new_repo, stacked_on,
        stack_on_pwd, repo_format_name, make_working_trees, shared_repo):
        args = []
        args.append(self._serialize_NoneTrueFalse(use_existing_dir))
        args.append(self._serialize_NoneTrueFalse(create_prefix))
        args.append(self._serialize_NoneTrueFalse(force_new_repo))
        args.append(self._serialize_NoneString(stacked_on))
        # stack_on_pwd is often/usually our transport
        if stack_on_pwd:
            try:
                stack_on_pwd = transport.relpath(stack_on_pwd)
                if not stack_on_pwd:
                    stack_on_pwd = '.'
            except errors.PathNotChild:
                pass
        args.append(self._serialize_NoneString(stack_on_pwd))
        args.append(self._serialize_NoneString(repo_format_name))
        args.append(self._serialize_NoneTrueFalse(make_working_trees))
        args.append(self._serialize_NoneTrueFalse(shared_repo))
        request_network_name = self._network_name or \
            BzrDirFormat.get_default_format().network_name()
        try:
            response = client.call('BzrDirFormat.initialize_ex_1.16',
                request_network_name, path, *args)
        except errors.UnknownSmartMethod:
            client._medium._remember_remote_is_before((1,16))
            local_dir_format = BzrDirMetaFormat1()
            self._supply_sub_formats_to(local_dir_format)
            return local_dir_format.initialize_on_transport_ex(transport,
                use_existing_dir=use_existing_dir, create_prefix=create_prefix,
                force_new_repo=force_new_repo, stacked_on=stacked_on,
                stack_on_pwd=stack_on_pwd, repo_format_name=repo_format_name,
                make_working_trees=make_working_trees, shared_repo=shared_repo,
                vfs_only=True)
        except errors.ErrorFromSmartServer, err:
            remote._translate_error(err, path=path)
        repo_path = response[0]
        bzrdir_name = response[6]
        require_stacking = response[7]
        require_stacking = self.parse_NoneTrueFalse(require_stacking)
        format = RemoteBzrDirFormat()
        format._network_name = bzrdir_name
        self._supply_sub_formats_to(format)
        bzrdir = remote.RemoteBzrDir(transport, format, _client=client)
        if repo_path:
            repo_format = remote.response_tuple_to_repo_format(response[1:])
            if repo_path == '.':
                repo_path = ''
            if repo_path:
                repo_bzrdir_format = RemoteBzrDirFormat()
                repo_bzrdir_format._network_name = response[5]
                repo_bzr = remote.RemoteBzrDir(transport.clone(repo_path),
                    repo_bzrdir_format)
            else:
                repo_bzr = bzrdir
            final_stack = response[8] or None
            final_stack_pwd = response[9] or None
            if final_stack_pwd:
                final_stack_pwd = urlutils.join(
                    transport.base, final_stack_pwd)
            remote_repo = remote.RemoteRepository(repo_bzr, repo_format)
            if len(response) > 10:
                # Updated server verb that locks remotely.
                repo_lock_token = response[10] or None
                remote_repo.lock_write(repo_lock_token, _skip_rpc=True)
                if repo_lock_token:
                    remote_repo.dont_leave_lock_in_place()
            else:
                remote_repo.lock_write()
            policy = UseExistingRepository(remote_repo, final_stack,
                final_stack_pwd, require_stacking)
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
        return remote.RemoteBzrDir(transport, self)

    def __eq__(self, other):
        if not isinstance(other, RemoteBzrDirFormat):
            return False
        return self.get_format_description() == other.get_format_description()

    def __return_repository_format(self):
        # Always return a RemoteRepositoryFormat object, but if a specific bzr
        # repository format has been asked for, tell the RemoteRepositoryFormat
        # that it should use that for init() etc.
        result = remote.RemoteRepositoryFormat()
        custom_format = getattr(self, '_repository_format', None)
        if custom_format:
            if isinstance(custom_format, remote.RemoteRepositoryFormat):
                return custom_format
            else:
                # We will use the custom format to create repositories over the
                # wire; expose its details like rich_root_data for code to
                # query
                result._custom_format = custom_format
        return result

    def get_branch_format(self):
        result = BzrDirMetaFormat1.get_branch_format(self)
        if not isinstance(result, remote.RemoteBranchFormat):
            new_result = remote.RemoteBranchFormat()
            new_result._custom_format = result
            # cache the result
            self.set_branch_format(new_result)
            result = new_result
        return result

    repository_format = property(__return_repository_format,
        BzrDirMetaFormat1._set_repository_format) #.im_func)


controldir.ControlDirFormat.register_server_prober(RemoteBzrProber)


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
                    branch.user_url)
            except errors.InvalidRebaseURLs:
                stack_on = self._get_full_stack_on()
        try:
            branch.set_stacked_on_url(stack_on)
        except (errors.UnstackableBranchFormat,
                errors.UnstackableRepositoryFormat):
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
            stacked_dir = BzrDir.open(stack_on,
                                      possible_transports=possible_transports)
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

    def acquire_repository(self, make_working_trees=None, shared=False):
        """Acquire a repository for this bzrdir.

        Implementations may create a new repository or use a pre-exising
        repository.
        :param make_working_trees: If creating a repository, set
            make_working_trees to this value (if non-None)
        :param shared: If creating a repository, make it shared if True
        :return: A repository, is_new_flag (True if the repository was
            created).
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
        stack_on = self._get_full_stack_on()
        if stack_on:
            format = self._bzrdir._format
            format.require_stacking(stack_on=stack_on,
                                    possible_transports=[self._bzrdir.root_transport])
            if not self._require_stacking:
                # We have picked up automatic stacking somewhere.
                note('Using default stacking branch %s at %s', self._stack_on,
                    self._stack_on_pwd)
        repository = self._bzrdir.create_repository(shared=shared)
        self._add_fallback(repository,
                           possible_transports=[self._bzrdir.transport])
        if make_working_trees is not None:
            repository.set_make_working_trees(make_working_trees)
        return repository, True


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

        Returns an existing repository to use.
        """
        self._add_fallback(self._repository,
                       possible_transports=[self._repository.bzrdir.transport])
        return self._repository, False


def register_metadir(registry, key,
         repository_format, help, native=True, deprecated=False,
         branch_format=None,
         tree_format=None,
         hidden=False,
         experimental=False,
         alias=False):
    """Register a metadir subformat.

    These all use a BzrDirMetaFormat1 bzrdir, but can be parameterized
    by the Repository/Branch/WorkingTreeformats.

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
            factory = pyutils.get_named_object(mod_name, factory_name)
        except ImportError, e:
            raise ImportError('failed to load %s: %s' % (full_name, e))
        except AttributeError:
            raise AttributeError('no factory %s in module %r'
                % (full_name, sys.modules[mod_name]))
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
    registry.register(key, helper, help, native, deprecated, hidden,
        experimental, alias)

# The pre-0.8 formats have their repository format network name registered in
# repository.py. MetaDir formats have their repository format network name
# inferred from their disk format string.
controldir.format_registry.register_lazy('weave', 
    'bzrlib.bzrdir_weave', 'BzrDirFormat6',
    'Pre-0.8 format.  Slower than knit and does not'
    ' support checkouts or shared repositories.',
    hidden=True,
    deprecated=True)
register_metadir(controldir.format_registry, 'metaweave',
    'bzrlib.repofmt.weaverepo.RepositoryFormat7',
    'Transitional format in 0.8.  Slower than knit.',
    branch_format='bzrlib.branch.BzrBranchFormat5',
    tree_format='bzrlib.workingtree.WorkingTreeFormat3',
    hidden=True,
    deprecated=True)
register_metadir(controldir.format_registry, 'knit',
    'bzrlib.repofmt.knitrepo.RepositoryFormatKnit1',
    'Format using knits.  Recommended for interoperation with bzr <= 0.14.',
    branch_format='bzrlib.branch.BzrBranchFormat5',
    tree_format='bzrlib.workingtree.WorkingTreeFormat3',
    hidden=True,
    deprecated=True)
register_metadir(controldir.format_registry, 'dirstate',
    'bzrlib.repofmt.knitrepo.RepositoryFormatKnit1',
    help='New in 0.15: Fast local operations. Compatible with bzr 0.8 and '
        'above when accessed over the network.',
    branch_format='bzrlib.branch.BzrBranchFormat5',
    # this uses bzrlib.workingtree.WorkingTreeFormat4 because importing
    # directly from workingtree_4 triggers a circular import.
    tree_format='bzrlib.workingtree.WorkingTreeFormat4',
    hidden=True,
    deprecated=True)
register_metadir(controldir.format_registry, 'dirstate-tags',
    'bzrlib.repofmt.knitrepo.RepositoryFormatKnit1',
    help='New in 0.15: Fast local operations and improved scaling for '
        'network operations. Additionally adds support for tags.'
        ' Incompatible with bzr < 0.15.',
    branch_format='bzrlib.branch.BzrBranchFormat6',
    tree_format='bzrlib.workingtree.WorkingTreeFormat4',
    hidden=True,
    deprecated=True)
register_metadir(controldir.format_registry, 'rich-root',
    'bzrlib.repofmt.knitrepo.RepositoryFormatKnit4',
    help='New in 1.0.  Better handling of tree roots.  Incompatible with'
        ' bzr < 1.0.',
    branch_format='bzrlib.branch.BzrBranchFormat6',
    tree_format='bzrlib.workingtree.WorkingTreeFormat4',
    hidden=True,
    deprecated=True)
register_metadir(controldir.format_registry, 'dirstate-with-subtree',
    'bzrlib.repofmt.knitrepo.RepositoryFormatKnit3',
    help='New in 0.15: Fast local operations and improved scaling for '
        'network operations. Additionally adds support for versioning nested '
        'bzr branches. Incompatible with bzr < 0.15.',
    branch_format='bzrlib.branch.BzrBranchFormat6',
    tree_format='bzrlib.workingtree.WorkingTreeFormat4',
    experimental=True,
    hidden=True,
    )
register_metadir(controldir.format_registry, 'pack-0.92',
    'bzrlib.repofmt.pack_repo.RepositoryFormatKnitPack1',
    help='New in 0.92: Pack-based format with data compatible with '
        'dirstate-tags format repositories. Interoperates with '
        'bzr repositories before 0.92 but cannot be read by bzr < 0.92. '
        ,
    branch_format='bzrlib.branch.BzrBranchFormat6',
    tree_format='bzrlib.workingtree.WorkingTreeFormat4',
    )
register_metadir(controldir.format_registry, 'pack-0.92-subtree',
    'bzrlib.repofmt.pack_repo.RepositoryFormatKnitPack3',
    help='New in 0.92: Pack-based format with data compatible with '
        'dirstate-with-subtree format repositories. Interoperates with '
        'bzr repositories before 0.92 but cannot be read by bzr < 0.92. '
        ,
    branch_format='bzrlib.branch.BzrBranchFormat6',
    tree_format='bzrlib.workingtree.WorkingTreeFormat4',
    hidden=True,
    experimental=True,
    )
register_metadir(controldir.format_registry, 'rich-root-pack',
    'bzrlib.repofmt.pack_repo.RepositoryFormatKnitPack4',
    help='New in 1.0: A variant of pack-0.92 that supports rich-root data '
         '(needed for bzr-svn and bzr-git).',
    branch_format='bzrlib.branch.BzrBranchFormat6',
    tree_format='bzrlib.workingtree.WorkingTreeFormat4',
    hidden=True,
    )
register_metadir(controldir.format_registry, '1.6',
    'bzrlib.repofmt.pack_repo.RepositoryFormatKnitPack5',
    help='A format that allows a branch to indicate that there is another '
         '(stacked) repository that should be used to access data that is '
         'not present locally.',
    branch_format='bzrlib.branch.BzrBranchFormat7',
    tree_format='bzrlib.workingtree.WorkingTreeFormat4',
    hidden=True,
    )
register_metadir(controldir.format_registry, '1.6.1-rich-root',
    'bzrlib.repofmt.pack_repo.RepositoryFormatKnitPack5RichRoot',
    help='A variant of 1.6 that supports rich-root data '
         '(needed for bzr-svn and bzr-git).',
    branch_format='bzrlib.branch.BzrBranchFormat7',
    tree_format='bzrlib.workingtree.WorkingTreeFormat4',
    hidden=True,
    )
register_metadir(controldir.format_registry, '1.9',
    'bzrlib.repofmt.pack_repo.RepositoryFormatKnitPack6',
    help='A repository format using B+tree indexes. These indexes '
         'are smaller in size, have smarter caching and provide faster '
         'performance for most operations.',
    branch_format='bzrlib.branch.BzrBranchFormat7',
    tree_format='bzrlib.workingtree.WorkingTreeFormat4',
    hidden=True,
    )
register_metadir(controldir.format_registry, '1.9-rich-root',
    'bzrlib.repofmt.pack_repo.RepositoryFormatKnitPack6RichRoot',
    help='A variant of 1.9 that supports rich-root data '
         '(needed for bzr-svn and bzr-git).',
    branch_format='bzrlib.branch.BzrBranchFormat7',
    tree_format='bzrlib.workingtree.WorkingTreeFormat4',
    hidden=True,
    )
register_metadir(controldir.format_registry, '1.14',
    'bzrlib.repofmt.pack_repo.RepositoryFormatKnitPack6',
    help='A working-tree format that supports content filtering.',
    branch_format='bzrlib.branch.BzrBranchFormat7',
    tree_format='bzrlib.workingtree.WorkingTreeFormat5',
    )
register_metadir(controldir.format_registry, '1.14-rich-root',
    'bzrlib.repofmt.pack_repo.RepositoryFormatKnitPack6RichRoot',
    help='A variant of 1.14 that supports rich-root data '
         '(needed for bzr-svn and bzr-git).',
    branch_format='bzrlib.branch.BzrBranchFormat7',
    tree_format='bzrlib.workingtree.WorkingTreeFormat5',
    )
# The following un-numbered 'development' formats should always just be aliases.
register_metadir(controldir.format_registry, 'development-subtree',
    'bzrlib.repofmt.groupcompress_repo.RepositoryFormat2aSubtree',
    help='Current development format, subtree variant. Can convert data to and '
        'from pack-0.92-subtree (and anything compatible with '
        'pack-0.92-subtree) format repositories. Repositories and branches in '
        'this format can only be read by bzr.dev. Please read '
        'http://doc.bazaar.canonical.com/latest/developers/development-repo.html '
        'before use.',
    branch_format='bzrlib.branch.BzrBranchFormat7',
    tree_format='bzrlib.workingtree.WorkingTreeFormat6',
    experimental=True,
    hidden=True,
    alias=False, # Restore to being an alias when an actual development subtree format is added
                 # This current non-alias status is simply because we did not introduce a
                 # chk based subtree format.
    )
register_metadir(controldir.format_registry, 'development5-subtree',
    'bzrlib.repofmt.pack_repo.RepositoryFormatPackDevelopment2Subtree',
    help='Development format, subtree variant. Can convert data to and '
        'from pack-0.92-subtree (and anything compatible with '
        'pack-0.92-subtree) format repositories. Repositories and branches in '
        'this format can only be read by bzr.dev. Please read '
        'http://doc.bazaar.canonical.com/latest/developers/development-repo.html '
        'before use.',
    branch_format='bzrlib.branch.BzrBranchFormat7',
    tree_format='bzrlib.workingtree.WorkingTreeFormat6',
    experimental=True,
    hidden=True,
    alias=False,
    )

# And the development formats above will have aliased one of the following:

# Finally, the current format.
register_metadir(controldir.format_registry, '2a',
    'bzrlib.repofmt.groupcompress_repo.RepositoryFormat2a',
    help='First format for bzr 2.0 series.\n'
        'Uses group-compress storage.\n'
        'Provides rich roots which are a one-way transition.\n',
        # 'storage in packs, 255-way hashed CHK inventory, bencode revision, group compress, '
        # 'rich roots. Supported by bzr 1.16 and later.',
    branch_format='bzrlib.branch.BzrBranchFormat7',
    tree_format='bzrlib.workingtree.WorkingTreeFormat6',
    experimental=False,
    )

# The following format should be an alias for the rich root equivalent 
# of the default format
register_metadir(controldir.format_registry, 'default-rich-root',
    'bzrlib.repofmt.groupcompress_repo.RepositoryFormat2a',
    branch_format='bzrlib.branch.BzrBranchFormat7',
    tree_format='bzrlib.workingtree.WorkingTreeFormat6',
    alias=True,
    hidden=True,
    help='Same as 2a.')

# The current format that is made on 'bzr init'.
format_name = config.GlobalConfig().get_user_option('default_format')
if format_name is None:
    controldir.format_registry.set_default('2a')
else:
    controldir.format_registry.set_default(format_name)

# XXX 2010-08-20 JRV: There is still a lot of code relying on
# bzrlib.bzrdir.format_registry existing. When BzrDir.create/BzrDir.open/etc
# get changed to ControlDir.create/ControlDir.open/etc this should be removed.
format_registry = controldir.format_registry
