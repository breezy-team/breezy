# Copyright (C) 2005 Canonical Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""BzrDir logic. The BzrDir is the basic control directory used by bzr.

At format 7 this was split out into Branch, Repository and Checkout control
directories.
"""

from copy import deepcopy
from cStringIO import StringIO
from unittest import TestSuite


import bzrlib
import bzrlib.errors as errors
from bzrlib.lockable_files import LockableFiles
from bzrlib.osutils import safe_unicode
from bzrlib.trace import mutter
from bzrlib.symbol_versioning import *
from bzrlib.transport import get_transport
from bzrlib.transport.local import LocalTransport


class BzrDir(object):
    """A .bzr control diretory.
    
    BzrDir instances let you create or open any of the things that can be
    found within .bzr - checkouts, branches and repositories.
    
    transport
        the transport which this bzr dir is rooted at (i.e. file:///.../.bzr/)
    root_transport
        a transport connected to the directory this bzr was opened from.
    """

    def _check_supported(self, format, allow_unsupported):
        """Check whether format is a supported format.

        If allow_unsupported is True, this is a no-op.
        """
        if not allow_unsupported and not format.is_supported():
            raise errors.UnsupportedFormatError(format)

    def clone(self, url, revision_id=None, basis=None, force_new_repo=False):
        """Clone this bzrdir and its contents to url verbatim.

        If urls last component does not exist, it will be created.

        if revision_id is not None, then the clone operation may tune
            itself to download less data.
        :param force_new_repo: Do not use a shared repository for the target 
                               even if one is available.
        """
        self._make_tail(url)
        basis_repo, basis_branch, basis_tree = self._get_basis_components(basis)
        result = self._format.initialize(url)
        try:
            local_repo = self.find_repository()
        except errors.NoRepositoryPresent:
            local_repo = None
        if local_repo:
            # may need to copy content in
            if force_new_repo:
                local_repo.clone(result, revision_id=revision_id, basis=basis_repo)
            else:
                try:
                    result_repo = result.find_repository()
                    # fetch content this dir needs.
                    if basis_repo:
                        # XXX FIXME RBC 20060214 need tests for this when the basis
                        # is incomplete
                        result_repo.fetch(basis_repo, revision_id=revision_id)
                    result_repo.fetch(local_repo, revision_id=revision_id)
                except errors.NoRepositoryPresent:
                    # needed to make one anyway.
                    local_repo.clone(result, revision_id=revision_id, basis=basis_repo)
        # 1 if there is a branch present
        #   make sure its content is available in the target repository
        #   clone it.
        try:
            self.open_branch().clone(result, revision_id=revision_id)
        except errors.NotBranchError:
            pass
        try:
            self.open_workingtree().clone(result, basis=basis_tree)
        except (errors.NoWorkingTree, errors.NotLocalUrl):
            pass
        return result

    def _get_basis_components(self, basis):
        """Retrieve the basis components that are available at basis."""
        if basis is None:
            return None, None, None
        try:
            basis_tree = basis.open_workingtree()
            basis_branch = basis_tree.branch
            basis_repo = basis_branch.repository
        except (errors.NoWorkingTree, errors.NotLocalUrl):
            basis_tree = None
            try:
                basis_branch = basis.open_branch()
                basis_repo = basis_branch.repository
            except errors.NotBranchError:
                basis_branch = None
                try:
                    basis_repo = basis.open_repository()
                except errors.NoRepositoryPresent:
                    basis_repo = None
        return basis_repo, basis_branch, basis_tree

    def _make_tail(self, url):
        segments = url.split('/')
        if segments and segments[-1] not in ('', '.'):
            parent = '/'.join(segments[:-1])
            t = bzrlib.transport.get_transport(parent)
            try:
                t.mkdir(segments[-1])
            except errors.FileExists:
                pass

    @staticmethod
    def create(base):
        """Create a new BzrDir at the url 'base'.
        
        This will call the current default formats initialize with base
        as the only parameter.

        If you need a specific format, consider creating an instance
        of that and calling initialize().
        """
        segments = base.split('/')
        if segments and segments[-1] not in ('', '.'):
            parent = '/'.join(segments[:-1])
            t = bzrlib.transport.get_transport(parent)
            try:
                t.mkdir(segments[-1])
            except errors.FileExists:
                pass
        return BzrDirFormat.get_default_format().initialize(safe_unicode(base))

    def create_branch(self):
        """Create a branch in this BzrDir.

        The bzrdirs format will control what branch format is created.
        For more control see BranchFormatXX.create(a_bzrdir).
        """
        raise NotImplementedError(self.create_branch)

    @staticmethod
    def create_branch_and_repo(base, force_new_repo=False):
        """Create a new BzrDir, Branch and Repository at the url 'base'.

        This will use the current default BzrDirFormat, and use whatever 
        repository format that that uses via bzrdir.create_branch and
        create_repository. If a shared repository is available that is used
        preferentially.

        The created Branch object is returned.

        :param base: The URL to create the branch at.
        :param force_new_repo: If True a new repository is always created.
        """
        bzrdir = BzrDir.create(base)
        if force_new_repo:
            bzrdir.create_repository()
        try:
            repo = bzrdir.find_repository()
        except errors.NoRepositoryPresent:
            bzrdir.create_repository()
        return bzrdir.create_branch()
        
    @staticmethod
    def create_branch_convenience(base, force_new_repo=False, force_new_tree=None):
        """Create a new BzrDir, Branch and Repository at the url 'base'.

        This is a convenience function - it will use an existing repository
        if possible, can be told explicitly whether to create a working tree or
        nor.

        This will use the current default BzrDirFormat, and use whatever 
        repository format that that uses via bzrdir.create_branch and
        create_repository. If a shared repository is available that is used
        preferentially. Whatever repository is used, its tree creation policy
        is followed.

        The created Branch object is returned.
        If a working tree cannot be made due to base not being a file:// url,
        no error is raised.

        :param base: The URL to create the branch at.
        :param force_new_repo: If True a new repository is always created.
        :param force_new_tree: If True or False force creation of a tree or 
                               prevent such creation respectively.
        """
        bzrdir = BzrDir.create(base)
        if force_new_repo:
            bzrdir.create_repository()
        try:
            repo = bzrdir.find_repository()
        except errors.NoRepositoryPresent:
            repo = bzrdir.create_repository()
        result = bzrdir.create_branch()
        if force_new_tree or (repo.make_working_trees() and 
                              force_new_tree is None):
            bzrdir.create_workingtree()
        return result
        
    @staticmethod
    def create_repository(base, shared=False):
        """Create a new BzrDir and Repository at the url 'base'.

        This will use the current default BzrDirFormat, and use whatever 
        repository format that that uses for bzrdirformat.create_repository.

        ;param shared: Create a shared repository rather than a standalone
                       repository.
        The Repository object is returned.

        This must be overridden as an instance method in child classes, where
        it should take no parameters and construct whatever repository format
        that child class desires.
        """
        bzrdir = BzrDir.create(base)
        return bzrdir.create_repository()

    @staticmethod
    def create_standalone_workingtree(base):
        """Create a new BzrDir, WorkingTree, Branch and Repository at 'base'.

        'base' must be a local path or a file:// url.

        This will use the current default BzrDirFormat, and use whatever 
        repository format that that uses for bzrdirformat.create_workingtree,
        create_branch and create_repository.

        The WorkingTree object is returned.
        """
        t = get_transport(safe_unicode(base))
        if not isinstance(t, LocalTransport):
            raise errors.NotLocalUrl(base)
        bzrdir = BzrDir.create_branch_and_repo(safe_unicode(base),
                                               force_new_repo=True).bzrdir
        return bzrdir.create_workingtree()

    def create_workingtree(self, revision_id=None):
        """Create a working tree at this BzrDir.
        
        revision_id: create it as of this revision id.
        """
        raise NotImplementedError(self.create_workingtree)

    def find_repository(self):
        """Find the repository that should be used for a_bzrdir.

        This does not require a branch as we use it to find the repo for
        new branches as well as to hook existing branches up to their
        repository.
        """
        try:
            return self.open_repository()
        except errors.NoRepositoryPresent:
            pass
        next_transport = self.root_transport.clone('..')
        while True:
            try:
                found_bzrdir = BzrDir.open_containing_transport(
                    next_transport)[0]
            except errors.NotBranchError:
                raise errors.NoRepositoryPresent(self)
            try:
                repository = found_bzrdir.open_repository()
            except errors.NoRepositoryPresent:
                next_transport = found_bzrdir.root_transport.clone('..')
                continue
            if ((found_bzrdir.root_transport.base == 
                 self.root_transport.base) or repository.is_shared()):
                return repository
            else:
                raise errors.NoRepositoryPresent(self)
        raise errors.NoRepositoryPresent(self)

    def get_branch_transport(self, branch_format):
        """Get the transport for use by branch format in this BzrDir.

        Note that bzr dirs that do not support format strings will raise
        IncompatibleFormat if the branch format they are given has
        a format string, and vice verca.

        If branch_format is None, the transport is returned with no 
        checking. if it is not None, then the returned transport is
        guaranteed to point to an existing directory ready for use.
        """
        raise NotImplementedError(self.get_branch_transport)
        
    def get_repository_transport(self, repository_format):
        """Get the transport for use by repository format in this BzrDir.

        Note that bzr dirs that do not support format strings will raise
        IncompatibleFormat if the repository format they are given has
        a format string, and vice verca.

        If repository_format is None, the transport is returned with no 
        checking. if it is not None, then the returned transport is
        guaranteed to point to an existing directory ready for use.
        """
        raise NotImplementedError(self.get_repository_transport)
        
    def get_workingtree_transport(self, tree_format):
        """Get the transport for use by workingtree format in this BzrDir.

        Note that bzr dirs that do not support format strings will raise
        IncompatibleFormat if the workingtree format they are given has
        a format string, and vice verca.

        If workingtree_format is None, the transport is returned with no 
        checking. if it is not None, then the returned transport is
        guaranteed to point to an existing directory ready for use.
        """
        raise NotImplementedError(self.get_workingtree_transport)
        
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

    @staticmethod
    def open_unsupported(base):
        """Open a branch which is not supported."""
        return BzrDir.open(base, _unsupported=True)
        
    @staticmethod
    def open(base, _unsupported=False):
        """Open an existing bzrdir, rooted at 'base' (url)
        
        _unsupported is a private parameter to the BzrDir class.
        """
        t = get_transport(base)
        mutter("trying to open %r with transport %r", base, t)
        format = BzrDirFormat.find_format(t)
        if not _unsupported and not format.is_supported():
            # see open_downlevel to open legacy branches.
            raise errors.UnsupportedFormatError(
                    'sorry, format %s not supported' % format,
                    ['use a different bzr version',
                     'or remove the .bzr directory'
                     ' and "bzr init" again'])
        return format.open(t, _found=True)

    def open_branch(self, unsupported=False):
        """Open the branch object at this BzrDir if one is present.

        If unsupported is True, then no longer supported branch formats can
        still be opened.
        
        TODO: static convenience version of this?
        """
        raise NotImplementedError(self.open_branch)

    @staticmethod
    def open_containing(url):
        """Open an existing branch which contains url.
        
        :param url: url to search from.
        See open_containing_transport for more detail.
        """
        return BzrDir.open_containing_transport(get_transport(url))
    
    @staticmethod
    def open_containing_transport(a_transport):
        """Open an existing branch which contains a_transport.base

        This probes for a branch at a_transport, and searches upwards from there.

        Basically we keep looking up until we find the control directory or
        run into the root.  If there isn't one, raises NotBranchError.
        If there is one and it is either an unrecognised format or an unsupported 
        format, UnknownFormatError or UnsupportedFormatError are raised.
        If there is one, it is returned, along with the unused portion of url.
        """
        # this gets the normalised url back. I.e. '.' -> the full path.
        url = a_transport.base
        while True:
            try:
                format = BzrDirFormat.find_format(a_transport)
                return format.open(a_transport), a_transport.relpath(url)
            except errors.NotBranchError, e:
                mutter('not a branch in: %r %s', a_transport.base, e)
            new_t = a_transport.clone('..')
            if new_t.base == a_transport.base:
                # reached the root, whatever that may be
                raise errors.NotBranchError(path=url)
            a_transport = new_t

    def open_repository(self, _unsupported=False):
        """Open the repository object at this BzrDir if one is present.

        This will not follow the Branch object pointer - its strictly a direct
        open facility. Most client code should use open_branch().repository to
        get at a repository.

        _unsupported is a private parameter, not part of the api.
        TODO: static convenience version of this?
        """
        raise NotImplementedError(self.open_repository)

    def open_workingtree(self, _unsupported=False):
        """Open the workingtree object at this BzrDir if one is present.
        
        TODO: static convenience version of this?
        """
        raise NotImplementedError(self.open_workingtree)

    def sprout(self, url, revision_id=None, basis=None, force_new_repo=False):
        """Create a copy of this bzrdir prepared for use as a new line of
        development.

        If urls last component does not exist, it will be created.

        Attributes related to the identity of the source branch like
        branch nickname will be cleaned, a working tree is created
        whether one existed before or not; and a local branch is always
        created.

        if revision_id is not None, then the clone operation may tune
            itself to download less data.
        """
        self._make_tail(url)
        result = self._format.initialize(url)
        basis_repo, basis_branch, basis_tree = self._get_basis_components(basis)
        try:
            source_branch = self.open_branch()
            source_repository = source_branch.repository
        except errors.NotBranchError:
            source_branch = None
            try:
                source_repository = self.open_repository()
            except errors.NoRepositoryPresent:
                # copy the entire basis one if there is one
                # but there is no repository.
                source_repository = basis_repo
        if force_new_repo:
            result_repo = None
        else:
            try:
                result_repo = result.find_repository()
            except errors.NoRepositoryPresent:
                result_repo = None
        if source_repository is None and result_repo is not None:
            pass
        elif source_repository is None and result_repo is None:
            # no repo available, make a new one
            result.create_repository()
        elif source_repository is not None and result_repo is None:
            # have soure, and want to make a new target repo
            source_repository.clone(result,
                                    revision_id=revision_id,
                                    basis=basis_repo)
        else:
            # fetch needed content into target.
            if basis_repo:
                # XXX FIXME RBC 20060214 need tests for this when the basis
                # is incomplete
                result_repo.fetch(basis_repo, revision_id=revision_id)
            result_repo.fetch(source_repository, revision_id=revision_id)
        if source_branch is not None:
            source_branch.sprout(result, revision_id=revision_id)
        else:
            result.create_branch()
        try:
            self.open_workingtree().clone(result,
                                          revision_id=revision_id, 
                                          basis=basis_tree)
        except (errors.NoWorkingTree, errors.NotLocalUrl):
            result.create_workingtree()
        return result


class BzrDirPreSplitOut(BzrDir):
    """A common class for the all-in-one formats."""

    def clone(self, url, revision_id=None, basis=None, force_new_repo=False):
        """See BzrDir.clone()."""
        from bzrlib.workingtree import WorkingTreeFormat2
        self._make_tail(url)
        result = self._format.initialize(url, _cloning=True)
        basis_repo, basis_branch, basis_tree = self._get_basis_components(basis)
        self.open_repository().clone(result, revision_id=revision_id, basis=basis_repo)
        self.open_branch().clone(result, revision_id=revision_id)
        try:
            self.open_workingtree().clone(result, basis=basis_tree)
        except errors.NotLocalUrl:
            # make a new one, this format always has to have one.
            WorkingTreeFormat2().initialize(result)
        return result

    def create_branch(self):
        """See BzrDir.create_branch."""
        return self.open_branch()

    def create_repository(self, shared=False):
        """See BzrDir.create_repository."""
        if shared:
            raise errors.IncompatibleFormat('shared repository', self._format)
        return self.open_repository()

    def create_workingtree(self, revision_id=None):
        """See BzrDir.create_workingtree."""
        # this looks buggy but is not -really-
        # clone and sprout will have set the revision_id
        # and that will have set it for us, its only
        # specific uses of create_workingtree in isolation
        # that can do wonky stuff here, and that only
        # happens for creating checkouts, which cannot be 
        # done on this format anyway. So - acceptable wart.
        result = self.open_workingtree()
        if revision_id is not None:
            result.set_last_revision(revision_id)
        return result

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

    def open_branch(self, unsupported=False):
        """See BzrDir.open_branch."""
        from bzrlib.branch import BzrBranchFormat4
        format = BzrBranchFormat4()
        self._check_supported(format, unsupported)
        return format.open(self, _found=True)

    def sprout(self, url, revision_id=None, basis=None):
        """See BzrDir.sprout()."""
        from bzrlib.workingtree import WorkingTreeFormat2
        self._make_tail(url)
        result = self._format.initialize(url, _cloning=True)
        basis_repo, basis_branch, basis_tree = self._get_basis_components(basis)
        try:
            self.open_repository().clone(result, revision_id=revision_id, basis=basis_repo)
        except errors.NoRepositoryPresent:
            pass
        try:
            self.open_branch().sprout(result, revision_id=revision_id)
        except errors.NotBranchError:
            pass
        try:
            self.open_workingtree().clone(result, basis=basis_tree)
        except (errors.NotBranchError, errors.NotLocalUrl):
            # we always want a working tree
            WorkingTreeFormat2().initialize(result)
        return result


class BzrDir4(BzrDirPreSplitOut):
    """A .bzr version 4 control object.
    
    This is a deprecated format and may be removed after sept 2006.
    """

    def create_repository(self, shared=False):
        """See BzrDir.create_repository."""
        from bzrlib.repository import RepositoryFormat4
        return RepositoryFormat4().initialize(self, shared)

    def open_repository(self):
        """See BzrDir.open_repository."""
        from bzrlib.repository import RepositoryFormat4
        return RepositoryFormat4().open(self, _found=True)


class BzrDir5(BzrDirPreSplitOut):
    """A .bzr version 5 control object.

    This is a deprecated format and may be removed after sept 2006.
    """

    def open_repository(self):
        """See BzrDir.open_repository."""
        from bzrlib.repository import RepositoryFormat5
        return RepositoryFormat5().open(self, _found=True)

    def open_workingtree(self, _unsupported=False):
        """See BzrDir.create_workingtree."""
        from bzrlib.workingtree import WorkingTreeFormat2
        return WorkingTreeFormat2().open(self, _found=True)


class BzrDir6(BzrDirPreSplitOut):
    """A .bzr version 6 control object.

    This is a deprecated format and may be removed after sept 2006.
    """

    def open_repository(self):
        """See BzrDir.open_repository."""
        from bzrlib.repository import RepositoryFormat6
        return RepositoryFormat6().open(self, _found=True)

    def open_workingtree(self, _unsupported=False):
        """See BzrDir.create_workingtree."""
        from bzrlib.workingtree import WorkingTreeFormat2
        return WorkingTreeFormat2().open(self, _found=True)


class BzrDirMeta1(BzrDir):
    """A .bzr meta version 1 control object.
    
    This is the first control object where the 
    individual formats are really split out.
    """

    def create_branch(self):
        """See BzrDir.create_branch."""
        from bzrlib.branch import BranchFormat
        return BranchFormat.get_default_format().initialize(self)

    def create_repository(self, shared=False):
        """See BzrDir.create_repository."""
        from bzrlib.repository import RepositoryFormat
        return RepositoryFormat.get_default_format().initialize(self, shared)

    def create_workingtree(self, revision_id=None):
        """See BzrDir.create_workingtree."""
        from bzrlib.workingtree import WorkingTreeFormat
        return WorkingTreeFormat.get_default_format().initialize(self, revision_id)

    def get_branch_transport(self, branch_format):
        """See BzrDir.get_branch_transport()."""
        if branch_format is None:
            return self.transport.clone('branch')
        try:
            branch_format.get_format_string()
        except NotImplementedError:
            raise errors.IncompatibleFormat(branch_format, self._format)
        try:
            self.transport.mkdir('branch')
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
            self.transport.mkdir('repository')
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
            self.transport.mkdir('checkout')
        except errors.FileExists:
            pass
        return self.transport.clone('checkout')

    def open_branch(self, unsupported=False):
        """See BzrDir.open_branch."""
        from bzrlib.branch import BranchFormat
        format = BranchFormat.find_format(self)
        self._check_supported(format, unsupported)
        return format.open(self, _found=True)

    def open_repository(self, unsupported=False):
        """See BzrDir.open_repository."""
        from bzrlib.repository import RepositoryFormat
        format = RepositoryFormat.find_format(self)
        self._check_supported(format, unsupported)
        return format.open(self, _found=True)

    def open_workingtree(self, unsupported=False):
        """See BzrDir.open_workingtree."""
        from bzrlib.workingtree import WorkingTreeFormat
        format = WorkingTreeFormat.find_format(self)
        self._check_supported(format, unsupported)
        return format.open(self, _found=True)


class BzrDirFormat(object):
    """An encapsulation of the initialization and open routines for a format.

    Formats provide three things:
     * An initialization routine,
     * a format string,
     * an open routine.

    Formats are placed in an dict by their format string for reference 
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

    @classmethod
    def find_format(klass, transport):
        """Return the format registered for URL."""
        try:
            format_string = transport.get(".bzr/branch-format").read()
            return klass._formats[format_string]
        except errors.NoSuchFile:
            raise errors.NotBranchError(path=transport.base)
        except KeyError:
            raise errors.UnknownFormatError(format_string)

    @classmethod
    def get_default_format(klass):
        """Return the current default format."""
        return klass._default_format

    def get_format_string(self):
        """Return the ASCII format string that identifies this format."""
        raise NotImplementedError(self.get_format_string)

    def initialize(self, url):
        """Create a bzr control dir at this url and return an opened copy."""
        # Since we don't have a .bzr directory, inherit the
        # mode from the root directory
        t = get_transport(url)
        temp_control = LockableFiles(t, '')
        temp_control._transport.mkdir('.bzr',
                                      # FIXME: RBC 20060121 dont peek under
                                      # the covers
                                      mode=temp_control._dir_mode)
        file_mode = temp_control._file_mode
        del temp_control
        mutter('created control directory in ' + t.base)
        control = t.clone('.bzr')
        lock_file = 'branch-lock'
        utf8_files = [('README', 
                       "This is a Bazaar-NG control directory.\n"
                       "Do not change any files in this directory.\n"),
                      ('branch-format', self.get_format_string()),
                      ]
        # NB: no need to escape relative paths that are url safe.
        control.put(lock_file, StringIO(), mode=file_mode)
        control_files = LockableFiles(control, lock_file)
        control_files.lock_write()
        try:
            for file, content in utf8_files:
                control_files.put_utf8(file, content)
        finally:
            control_files.unlock()
        return self.open(t, _found=True)

    def is_supported(self):
        """Is this format supported?

        Supported formats must be initializable and openable.
        Unsupported formats may not support initialization or committing or 
        some other features depending on the reason for not being supported.
        """
        return True

    def open(self, transport, _found=False):
        """Return an instance of this format for the dir transport points at.
        
        _found is a private parameter, do not use it.
        """
        if not _found:
            assert isinstance(BzrDirFormat.find_format(transport),
                              self.__class__)
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
    def set_default_format(klass, format):
        klass._default_format = format

    def __str__(self):
        return self.get_format_string()[:-1]

    @classmethod
    def unregister_format(klass, format):
        assert klass._formats[format.get_format_string()] is format
        del klass._formats[format.get_format_string()]


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

    def get_format_string(self):
        """See BzrDirFormat.get_format_string()."""
        return "Bazaar-NG branch, format 0.0.4\n"

    def initialize(self, url):
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


class BzrDirFormat5(BzrDirFormat):
    """Bzr control format 5.

    This format is a combined format for working tree, branch and repository.
    It has:
     - Format 2 working trees [always] 
     - Format 4 branches [always] 
     - Format 5 repositories [always]
       Unhashed stores in the repository.
    """

    def get_format_string(self):
        """See BzrDirFormat.get_format_string()."""
        return "Bazaar-NG branch, format 5\n"

    def initialize(self, url, _cloning=False):
        """Format 5 dirs always have working tree, branch and repository.
        
        Except when they are being cloned.
        """
        from bzrlib.branch import BzrBranchFormat4
        from bzrlib.repository import RepositoryFormat5
        from bzrlib.workingtree import WorkingTreeFormat2
        result = super(BzrDirFormat5, self).initialize(url)
        RepositoryFormat5().initialize(result, _internal=True)
        if not _cloning:
            BzrBranchFormat4().initialize(result)
            WorkingTreeFormat2().initialize(result)
        return result

    def _open(self, transport):
        """See BzrDirFormat._open."""
        return BzrDir5(transport, self)


class BzrDirFormat6(BzrDirFormat):
    """Bzr control format 6.

    This format is a combined format for working tree, branch and repository.
    It has:
     - Format 2 working trees [always] 
     - Format 4 branches [always] 
     - Format 6 repositories [always]
    """

    def get_format_string(self):
        """See BzrDirFormat.get_format_string()."""
        return "Bazaar-NG branch, format 6\n"

    def initialize(self, url, _cloning=False):
        """Format 6 dirs always have working tree, branch and repository.
        
        Except when they are being cloned.
        """
        from bzrlib.branch import BzrBranchFormat4
        from bzrlib.repository import RepositoryFormat6
        from bzrlib.workingtree import WorkingTreeFormat2
        result = super(BzrDirFormat6, self).initialize(url)
        RepositoryFormat6().initialize(result, _internal=True)
        if not _cloning:
            BzrBranchFormat4().initialize(result)
            try:
                WorkingTreeFormat2().initialize(result)
            except errors.NotLocalUrl:
                # emulate pre-check behaviour for working tree and silently 
                # fail.
                pass
        return result

    def _open(self, transport):
        """See BzrDirFormat._open."""
        return BzrDir6(transport, self)


class BzrDirMetaFormat1(BzrDirFormat):
    """Bzr meta control format 1

    This is the first format with split out working tree, branch and repository
    disk storage.
    It has:
     - Format 3 working trees [optional]
     - Format 5 branches [optional]
     - Format 7 repositories [optional]
    """

    def get_format_string(self):
        """See BzrDirFormat.get_format_string()."""
        return "Bazaar-NG meta directory, format 1\n"

    def _open(self, transport):
        """See BzrDirFormat._open."""
        return BzrDirMeta1(transport, self)


BzrDirFormat.register_format(BzrDirFormat4())
BzrDirFormat.register_format(BzrDirFormat5())
BzrDirFormat.register_format(BzrDirMetaFormat1())
__default_format = BzrDirFormat6()
BzrDirFormat.register_format(__default_format)
BzrDirFormat.set_default_format(__default_format)


class BzrDirTestProviderAdapter(object):
    """A tool to generate a suite testing multiple bzrdir formats at once.

    This is done by copying the test once for each transport and injecting
    the transport_server, transport_readonly_server, and bzrdir_format
    classes into each copy. Each copy is also given a new id() to make it
    easy to identify.
    """

    def __init__(self, transport_server, transport_readonly_server, formats):
        self._transport_server = transport_server
        self._transport_readonly_server = transport_readonly_server
        self._formats = formats
    
    def adapt(self, test):
        result = TestSuite()
        for format in self._formats:
            new_test = deepcopy(test)
            new_test.transport_server = self._transport_server
            new_test.transport_readonly_server = self._transport_readonly_server
            new_test.bzrdir_format = format
            def make_new_test_id():
                new_id = "%s(%s)" % (new_test.id(), format.__class__.__name__)
                return lambda: new_id
            new_test.id = make_new_test_id()
            result.addTest(new_test)
        return result


class ScratchDir(BzrDir6):
    """Special test class: a bzrdir that cleans up itself..

    >>> d = ScratchDir()
    >>> base = d.transport.base
    >>> isdir(base)
    True
    >>> b.transport.__del__()
    >>> isdir(base)
    False
    """

    def __init__(self, files=[], dirs=[], transport=None):
        """Make a test branch.

        This creates a temporary directory and runs init-tree in it.

        If any files are listed, they are created in the working copy.
        """
        if transport is None:
            transport = bzrlib.transport.local.ScratchTransport()
            # local import for scope restriction
            BzrDirFormat6().initialize(transport.base)
            super(ScratchDir, self).__init__(transport, BzrDirFormat6())
            self.create_repository()
            self.create_branch()
            self.create_workingtree()
        else:
            super(ScratchDir, self).__init__(transport, BzrDirFormat6())

        # BzrBranch creates a clone to .bzr and then forgets about the
        # original transport. A ScratchTransport() deletes itself and
        # everything underneath it when it goes away, so we need to
        # grab a local copy to prevent that from happening
        self._transport = transport

        for d in dirs:
            self._transport.mkdir(d)
            
        for f in files:
            self._transport.put(f, 'content of %s' % f)

    def clone(self):
        """
        >>> orig = ScratchDir(files=["file1", "file2"])
        >>> os.listdir(orig.base)
        [u'.bzr', u'file1', u'file2']
        >>> clone = orig.clone()
        >>> if os.name != 'nt':
        ...   os.path.samefile(orig.base, clone.base)
        ... else:
        ...   orig.base == clone.base
        ...
        False
        >>> os.listdir(clone.base)
        [u'.bzr', u'file1', u'file2']
        """
        from shutil import copytree
        from bzrlib.osutils import mkdtemp
        base = mkdtemp()
        os.rmdir(base)
        copytree(self.base, base, symlinks=True)
        return ScratchDir(
            transport=bzrlib.transport.local.ScratchTransport(base))
