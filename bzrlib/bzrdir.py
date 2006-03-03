# Copyright (C) 2005, 2006 Canonical Ltd

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
import os
from cStringIO import StringIO
from unittest import TestSuite

import bzrlib
import bzrlib.errors as errors
from bzrlib.lockable_files import LockableFiles, TransportLock
from bzrlib.osutils import safe_unicode
from bzrlib.osutils import (
                            abspath,
                            pathjoin,
                            safe_unicode,
                            sha_strings,
                            sha_string,
                            )
from bzrlib.store.text import TextStore
from bzrlib.store.weave import WeaveStore
from bzrlib.symbol_versioning import *
from bzrlib.trace import mutter
from bzrlib.transactions import PassThroughTransaction
from bzrlib.transport import get_transport
from bzrlib.transport.local import LocalTransport
from bzrlib.weave import Weave
from bzrlib.weavefile import read_weave, write_weave
from bzrlib.xml4 import serializer_v4
from bzrlib.xml5 import serializer_v5


class BzrDir(object):
    """A .bzr control diretory.
    
    BzrDir instances let you create or open any of the things that can be
    found within .bzr - checkouts, branches and repositories.
    
    transport
        the transport which this bzr dir is rooted at (i.e. file:///.../.bzr/)
    root_transport
        a transport connected to the directory this bzr was opened from.
    """

    def can_convert_format(self):
        """Return true if this bzrdir is one whose format we can convert from."""
        return True

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
        bzrdir._find_or_create_repository(force_new_repo)
        return bzrdir.create_branch()

    def _find_or_create_repository(self, force_new_repo):
        """Create a new repository if needed, returning the repository."""
        if force_new_repo:
            return self.create_repository()
        try:
            return self.find_repository()
        except errors.NoRepositoryPresent:
            return self.create_repository()
        
    @staticmethod
    def create_branch_convenience(base, force_new_repo=False, force_new_tree=None):
        """Create a new BzrDir, Branch and Repository at the url 'base'.

        This is a convenience function - it will use an existing repository
        if possible, can be told explicitly whether to create a working tree or
        not.

        This will use the current default BzrDirFormat, and use whatever 
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
        """
        if force_new_tree:
            # check for non local urls
            t = get_transport(safe_unicode(base))
            if not isinstance(t, LocalTransport):
                raise errors.NotLocalUrl(base)
        bzrdir = BzrDir.create(base)
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
                found_bzrdir = BzrDir.open_containing_from_transport(
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
        See open_containing_from_transport for more detail.
        """
        return BzrDir.open_containing_from_transport(get_transport(url))
    
    @staticmethod
    def open_containing_from_transport(a_transport):
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

    def __init__(self, _transport, _format):
        """See BzrDir.__init__."""
        super(BzrDirPreSplitOut, self).__init__(_transport, _format)
        self._control_files = LockableFiles(self.get_branch_transport(None),
                                            'branch-lock',
                                            TransportLock)

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
        return self._format.repository_format.initialize(self, shared)

    def needs_format_conversion(self, format=None):
        """Format 4 dirs are always in need of conversion."""
        return True

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

    def can_convert_format(self):
        """See BzrDir.can_convert_format()."""
        return True

    def create_branch(self):
        """See BzrDir.create_branch."""
        from bzrlib.branch import BranchFormat
        return BranchFormat.get_default_format().initialize(self)

    def create_repository(self, shared=False):
        """See BzrDir.create_repository."""
        return self._format.repository_format.initialize(self, shared)

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
        # currently there are no other possible conversions for meta1 formats.
        return False

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

    def get_converter(self, format=None):
        """Return the converter to use to convert bzrdirs needing converts.

        This returns a bzrlib.bzrdir.Converter object.

        This should return the best upgrader to step this format towards the
        current default format. In the case of plugins we can/shouold provide
        some means for them to extend the range of returnable converters.

        :param format: Optional format to override the default foramt of the 
                       library.
        """
        raise NotImplementedError(self.get_converter)

    def initialize(self, url):
        """Create a bzr control dir at this url and return an opened copy."""
        # Since we don't have a .bzr directory, inherit the
        # mode from the root directory
        t = get_transport(url)
        temp_control = LockableFiles(t, '', TransportLock)
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
        control_files = LockableFiles(control, lock_file, TransportLock)
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

    def get_converter(self, format=None):
        """See BzrDirFormat.get_converter()."""
        # there is one and only one upgrade path here.
        return ConvertBzrDir4To5()
        
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

    def __return_repository_format(self):
        """Circular import protection."""
        from bzrlib.repository import RepositoryFormat4
        return RepositoryFormat4(self)
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

    def get_format_string(self):
        """See BzrDirFormat.get_format_string()."""
        return "Bazaar-NG branch, format 5\n"

    def get_converter(self, format=None):
        """See BzrDirFormat.get_converter()."""
        # there is one and only one upgrade path here.
        return ConvertBzrDir5To6()
        
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

    def __return_repository_format(self):
        """Circular import protection."""
        from bzrlib.repository import RepositoryFormat5
        return RepositoryFormat5(self)
    repository_format = property(__return_repository_format)


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

    def get_converter(self, format=None):
        """See BzrDirFormat.get_converter()."""
        # there is one and only one upgrade path here.
        return ConvertBzrDir6ToMeta()
        
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

    def __return_repository_format(self):
        """Circular import protection."""
        from bzrlib.repository import RepositoryFormat6
        return RepositoryFormat6(self)
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
        """Allow changint the repository format for metadir formats."""
        self._repository_format = value
    repository_format = property(__return_repository_format, __set_repository_format)


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
        self.branch.control_files.put_utf8('branch-format', BzrDirFormat5().get_format_string())

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
        inv = serializer_v4.read_inventory(self.branch.control_files.get('inventory'))
        new_inv_xml = serializer_v5.write_inventory_to_string(inv)
        # FIXME inventory is a working tree change.
        self.branch.control_files.put('inventory', new_inv_xml)

    def _write_all_weaves(self):
        controlweaves = WeaveStore(self.bzrdir.transport, prefixed=False)
        weave_transport = self.bzrdir.transport.clone('weaves')
        weaves = WeaveStore(weave_transport, prefixed=False)
        transaction = PassThroughTransaction()

        controlweaves.put_weave('inventory', self.inv_weave, transaction)
        i = 0
        try:
            for file_id, file_weave in self.text_weaves.items():
                self.pb.update('writing weave', i, len(self.text_weaves))
                weaves.put_weave(file_id, file_weave, transaction)
                i += 1
        finally:
            self.pb.clear()

    def _write_all_revs(self):
        """Write all revisions out in new form."""
        self.bzrdir.transport.delete_tree('revision-store')
        self.bzrdir.transport.mkdir('revision-store')
        revision_transport = self.bzrdir.transport.clone('revision-store')
        # TODO permissions
        revision_store = TextStore(revision_transport,
                                   prefixed=False,
                                   compressed=True)
        try:
            for i, rev_id in enumerate(self.converted_revs):
                self.pb.update('write revision', i, len(self.converted_revs))
                rev_tmp = StringIO()
                serializer_v5.write_revision(self.revisions[rev_id], rev_tmp)
                rev_tmp.seek(0)
                revision_store.add(rev_tmp, rev_id)
        finally:
            self.pb.clear()
            
    def _load_one_rev(self, rev_id):
        """Load a revision object into memory.

        Any parents not either loaded or abandoned get queued to be
        loaded."""
        self.pb.update('loading revision',
                       len(self.revisions),
                       len(self.known_revisions))
        if not self.branch.repository.revision_store.has_id(rev_id):
            self.pb.clear()
            self.pb.note('revision {%s} not present in branch; '
                         'will be converted as a ghost',
                         rev_id)
            self.absent_revisions.add(rev_id)
        else:
            rev_xml = self.branch.repository.revision_store.get(rev_id).read()
            rev = serializer_v4.read_revision_from_string(rev_xml)
            for parent_id in rev.parent_ids:
                self.known_revisions.add(parent_id)
                self.to_read.append(parent_id)
            self.revisions[rev_id] = rev

    def _load_old_inventory(self, rev_id):
        assert rev_id not in self.converted_revs
        old_inv_xml = self.branch.repository.inventory_store.get(rev_id).read()
        inv = serializer_v4.read_inventory_from_string(old_inv_xml)
        rev = self.revisions[rev_id]
        if rev.inventory_sha1:
            assert rev.inventory_sha1 == sha_string(old_inv_xml), \
                'inventory sha mismatch for {%s}' % rev_id
        return inv

    def _load_updated_inventory(self, rev_id):
        assert rev_id in self.converted_revs
        inv_xml = self.inv_weave.get_text(rev_id)
        inv = serializer_v5.read_inventory_from_string(inv_xml)
        return inv

    def _convert_one_rev(self, rev_id):
        """Convert revision and all referenced objects to new format."""
        rev = self.revisions[rev_id]
        inv = self._load_old_inventory(rev_id)
        present_parents = [p for p in rev.parent_ids
                           if p not in self.absent_revisions]
        self._convert_revision_contents(rev, inv, present_parents)
        self._store_new_weave(rev, inv, present_parents)
        self.converted_revs.add(rev_id)

    def _store_new_weave(self, rev, inv, present_parents):
        # the XML is now updated with text versions
        if __debug__:
            for file_id in inv:
                ie = inv[file_id]
                if ie.kind == 'root_directory':
                    continue
                assert hasattr(ie, 'revision'), \
                    'no revision on {%s} in {%s}' % \
                    (file_id, rev.revision_id)
        new_inv_xml = serializer_v5.write_inventory_to_string(inv)
        new_inv_sha1 = sha_string(new_inv_xml)
        self.inv_weave.add(rev.revision_id, 
                           present_parents,
                           new_inv_xml.splitlines(True),
                           new_inv_sha1)
        rev.inventory_sha1 = new_inv_sha1

    def _convert_revision_contents(self, rev, inv, present_parents):
        """Convert all the files within a revision.

        Also upgrade the inventory to refer to the text revision ids."""
        rev_id = rev.revision_id
        mutter('converting texts of revision {%s}',
               rev_id)
        parent_invs = map(self._load_updated_inventory, present_parents)
        for file_id in inv:
            ie = inv[file_id]
            self._convert_file_version(rev, ie, parent_invs)

    def _convert_file_version(self, rev, ie, parent_invs):
        """Convert one version of one file.

        The file needs to be added into the weave if it is a merge
        of >=2 parents or if it's changed from its parent.
        """
        if ie.kind == 'root_directory':
            return
        file_id = ie.file_id
        rev_id = rev.revision_id
        w = self.text_weaves.get(file_id)
        if w is None:
            w = Weave(file_id)
            self.text_weaves[file_id] = w
        text_changed = False
        previous_entries = ie.find_previous_heads(parent_invs, w)
        for old_revision in previous_entries:
                # if this fails, its a ghost ?
                assert old_revision in self.converted_revs 
        self.snapshot_ie(previous_entries, ie, w, rev_id)
        del ie.text_id
        assert getattr(ie, 'revision', None) is not None

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
        parent_indexes = map(w.lookup, previous_revisions)
        if ie.has_text():
            text = self.branch.repository.text_store.get(ie.text_id)
            file_lines = text.readlines()
            assert sha_strings(file_lines) == ie.text_sha1
            assert sum(map(len, file_lines)) == ie.text_size
            w.add(rev_id, parent_indexes, file_lines, ie.text_sha1)
            self.text_count += 1
        else:
            w.add(rev_id, parent_indexes, [], None)
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
        from bzrlib.store import hash_prefix
        self.bzrdir.transport.delete('branch-format')
        for store_name in ["weaves", "revision-store"]:
            self.pb.note("adding prefixes to %s" % store_name) 
            store_transport = self.bzrdir.transport.clone(store_name)
            for filename in store_transport.list_dir('.'):
                if (filename.endswith(".weave") or
                    filename.endswith(".gz") or
                    filename.endswith(".sig")):
                    file_id = os.path.splitext(filename)[0]
                else:
                    file_id = filename
                prefix_dir = hash_prefix(file_id)
                # FIXME keep track of the dirs made RBC 20060121
                try:
                    store_transport.move(filename, prefix_dir + '/' + filename)
                except errors.NoSuchFile: # catches missing dirs strangely enough
                    store_transport.mkdir(prefix_dir)
                    store_transport.move(filename, prefix_dir + '/' + filename)
        self.bzrdir._control_files.put_utf8('branch-format', BzrDirFormat6().get_format_string())


class ConvertBzrDir6ToMeta(Converter):
    """Converts format 6 bzr dirs to metadirs."""

    def convert(self, to_convert, pb):
        """See Converter.convert()."""
        self.bzrdir = to_convert
        self.pb = pb
        self.count = 0
        self.total = 20 # the steps we know about
        self.garbage_inventories = []

        self.pb.note('starting upgrade from format 6 to metadir')
        self.bzrdir._control_files.put_utf8('branch-format', "Converting to format 6")
        # its faster to move specific files around than to open and use the apis...
        # first off, nuke ancestry.weave, it was never used.
        try:
            self.step('Removing ancestry.weave')
            self.bzrdir.transport.delete('ancestry.weave')
        except errors.NoSuchFile:
            pass
        # find out whats there
        self.step('Finding branch files')
        last_revision = self.bzrdir.open_workingtree().last_revision()
        bzrcontents = self.bzrdir.transport.list_dir('.')
        for name in bzrcontents:
            if name.startswith('basis-inventory.'):
                self.garbage_inventories.append(name)
        # create new directories for repository, working tree and branch
        dir_mode = self.bzrdir._control_files._dir_mode
        self.file_mode = self.bzrdir._control_files._file_mode
        repository_names = [('inventory.weave', True),
                            ('revision-store', True),
                            ('weaves', True)]
        self.step('Upgrading repository  ')
        self.bzrdir.transport.mkdir('repository', mode=dir_mode)
        self.make_lock('repository')
        # we hard code the formats here because we are converting into
        # the meta format. The meta format upgrader can take this to a 
        # future format within each component.
        self.put_format('repository', bzrlib.repository.RepositoryFormat7())
        for entry in repository_names:
            self.move_entry('repository', entry)

        self.step('Upgrading branch      ')
        self.bzrdir.transport.mkdir('branch', mode=dir_mode)
        self.make_lock('branch')
        self.put_format('branch', bzrlib.branch.BzrBranchFormat5())
        branch_files = [('revision-history', True),
                        ('branch-name', True),
                        ('parent', False)]
        for entry in branch_files:
            self.move_entry('branch', entry)

        self.step('Upgrading working tree')
        self.bzrdir.transport.mkdir('checkout', mode=dir_mode)
        self.make_lock('checkout')
        self.put_format('checkout', bzrlib.workingtree.WorkingTreeFormat3())
        self.bzrdir.transport.delete_multi(self.garbage_inventories, self.pb)
        checkout_files = [('pending-merges', True),
                          ('inventory', True),
                          ('stat-cache', False)]
        for entry in checkout_files:
            self.move_entry('checkout', entry)
        if last_revision is not None:
            self.bzrdir._control_files.put_utf8('checkout/last-revision',
                                                last_revision)
        self.bzrdir._control_files.put_utf8('branch-format', BzrDirMetaFormat1().get_format_string())
        return BzrDir.open(self.bzrdir.root_transport.base)

    def make_lock(self, name):
        """Make a lock for the new control dir name."""
        self.step('Make %s lock' % name)
        self.bzrdir.transport.put('%s/lock' % name, StringIO(), mode=self.file_mode)

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
        self.bzrdir._control_files.put_utf8('%s/format' % dirname, format.get_format_string())


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
        return to_convert
