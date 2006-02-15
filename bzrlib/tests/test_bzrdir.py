# (C) 2005 Canonical Ltd

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

"""Tests for the BzrDir facility and any format specific tests.

For interface contract tests, see tests/bzr_dir_implementations.
"""

from StringIO import StringIO

import bzrlib.branch
import bzrlib.bzrdir as bzrdir
import bzrlib.errors as errors
from bzrlib.errors import (NotBranchError,
                           UnknownFormatError,
                           UnsupportedFormatError,
                           )
import bzrlib.repository as repository
from bzrlib.tests import TestCase, TestCaseWithTransport
from bzrlib.transport import get_transport
from bzrlib.transport.http import HttpServer
from bzrlib.transport.memory import MemoryServer
import bzrlib.workingtree as workingtree


class TestDefaultFormat(TestCase):

    def test_get_set_default_format(self):
        old_format = bzrdir.BzrDirFormat.get_default_format()
        # default is BzrDirFormat6
        self.failUnless(isinstance(old_format, bzrdir.BzrDirFormat6))
        bzrdir.BzrDirFormat.set_default_format(SampleBzrDirFormat())
        # creating a bzr dir should now create an instrumented dir.
        try:
            result = bzrdir.BzrDir.create('memory:/')
            self.failUnless(isinstance(result, SampleBzrDir))
        finally:
            bzrdir.BzrDirFormat.set_default_format(old_format)
        self.assertEqual(old_format, bzrdir.BzrDirFormat.get_default_format())


class SampleBranch(bzrlib.branch.Branch):
    """A dummy branch for guess what, dummy use."""

    def __init__(self, dir):
        self.bzrdir = dir


class SampleBzrDir(bzrdir.BzrDir):
    """A sample BzrDir implementation to allow testing static methods."""

    def create_repository(self):
        """See BzrDir.create_repository."""
        return "A repository"

    def open_repository(self):
        """See BzrDir.open_repository."""
        return "A repository"

    def create_branch(self):
        """See BzrDir.create_branch."""
        return SampleBranch(self)

    def create_workingtree(self):
        """See BzrDir.create_workingtree."""
        return "A tree"


class SampleBzrDirFormat(bzrdir.BzrDirFormat):
    """A sample format

    this format is initializable, unsupported to aid in testing the 
    open and open_downlevel routines.
    """

    def get_format_string(self):
        """See BzrDirFormat.get_format_string()."""
        return "Sample .bzr dir format."

    def initialize(self, url):
        """Create a bzr dir."""
        t = get_transport(url)
        t.mkdir('.bzr')
        t.put('.bzr/branch-format', StringIO(self.get_format_string()))
        return SampleBzrDir(t, self)

    def is_supported(self):
        return False

    def open(self, transport, _found=None):
        return "opened branch."


class TestBzrDirFormat(TestCaseWithTransport):
    """Tests for the BzrDirFormat facility."""

    def test_find_format(self):
        # is the right format object found for a branch?
        # create a branch with a few known format objects.
        # this is not quite the same as 
        t = get_transport(self.get_url())
        self.build_tree(["foo/", "bar/"], transport=t)
        def check_format(format, url):
            format.initialize(url)
            t = get_transport(url)
            found_format = bzrdir.BzrDirFormat.find_format(t)
            self.failUnless(isinstance(found_format, format.__class__))
        check_format(bzrdir.BzrDirFormat5(), "foo")
        check_format(bzrdir.BzrDirFormat6(), "bar")
        
    def test_find_format_nothing_there(self):
        self.assertRaises(NotBranchError,
                          bzrdir.BzrDirFormat.find_format,
                          get_transport('.'))

    def test_find_format_unknown_format(self):
        t = get_transport(self.get_url())
        t.mkdir('.bzr')
        t.put('.bzr/branch-format', StringIO())
        self.assertRaises(UnknownFormatError,
                          bzrdir.BzrDirFormat.find_format,
                          get_transport('.'))

    def test_register_unregister_format(self):
        format = SampleBzrDirFormat()
        url = self.get_url()
        # make a bzrdir
        format.initialize(url)
        # register a format for it.
        bzrdir.BzrDirFormat.register_format(format)
        # which bzrdir.Open will refuse (not supported)
        self.assertRaises(UnsupportedFormatError, bzrdir.BzrDir.open, url)
        # but open_downlevel will work
        t = get_transport(url)
        self.assertEqual(format.open(t), bzrdir.BzrDir.open_unsupported(url))
        # unregister the format
        bzrdir.BzrDirFormat.unregister_format(format)
        # now open_downlevel should fail too.
        self.assertRaises(UnknownFormatError, bzrdir.BzrDir.open_unsupported, url)

    def test_create_repository(self):
        format = SampleBzrDirFormat()
        old_format = bzrdir.BzrDirFormat.get_default_format()
        bzrdir.BzrDirFormat.set_default_format(format)
        try:
            repo = bzrdir.BzrDir.create_repository(self.get_url())
            self.assertEqual('A repository', repo)
        finally:
            bzrdir.BzrDirFormat.set_default_format(old_format)

    def test_create_repository_under_shared(self):
        # an explicit create_repository always does so.
        # we trust the format is right from the 'create_repository test'
        old_format = bzrdir.BzrDirFormat.get_default_format()
        bzrdir.BzrDirFormat.set_default_format(bzrdir.BzrDirMetaFormat1())
        try:
            self.make_repository('.', shared=True)
            repo = bzrdir.BzrDir.create_repository(self.get_url('child'))
            self.assertTrue(isinstance(repo, repository.Repository))
            self.assertTrue(repo.bzrdir.root_transport.base.endswith('child/'))
        finally:
            bzrdir.BzrDirFormat.set_default_format(old_format)

    def test_create_branch_and_repo_uses_default(self):
        format = SampleBzrDirFormat()
        old_format = bzrdir.BzrDirFormat.get_default_format()
        bzrdir.BzrDirFormat.set_default_format(format)
        try:
            branch = bzrdir.BzrDir.create_branch_and_repo(self.get_url())
            self.assertTrue(isinstance(branch, SampleBranch))
        finally:
            bzrdir.BzrDirFormat.set_default_format(old_format)

    def test_create_branch_and_repo_under_shared(self):
        # creating a branch and repo in a shared repo uses the
        # shared repository
        old_format = bzrdir.BzrDirFormat.get_default_format()
        bzrdir.BzrDirFormat.set_default_format(bzrdir.BzrDirMetaFormat1())
        try:
            self.make_repository('.', shared=True)
            branch = bzrdir.BzrDir.create_branch_and_repo(self.get_url('child'))
            self.assertRaises(errors.NoRepositoryPresent,
                              branch.bzrdir.open_repository)
        finally:
            bzrdir.BzrDirFormat.set_default_format(old_format)

    def test_create_branch_and_repo_under_shared_force_new(self):
        # creating a branch and repo in a shared repo can be forced to 
        # make a new repo
        old_format = bzrdir.BzrDirFormat.get_default_format()
        bzrdir.BzrDirFormat.set_default_format(bzrdir.BzrDirMetaFormat1())
        try:
            self.make_repository('.', shared=True)
            branch = bzrdir.BzrDir.create_branch_and_repo(self.get_url('child'),
                                                          force_new_repo=True)
            branch.bzrdir.open_repository()
        finally:
            bzrdir.BzrDirFormat.set_default_format(old_format)

    def test_create_standalone_working_tree(self):
        format = SampleBzrDirFormat()
        old_format = bzrdir.BzrDirFormat.get_default_format()
        bzrdir.BzrDirFormat.set_default_format(format)
        try:
            # note this is deliberately readonly, as this failure should 
            # occur before any writes.
            self.assertRaises(errors.NotLocalUrl,
                              bzrdir.BzrDir.create_standalone_workingtree,
                              self.get_readonly_url())
            tree = bzrdir.BzrDir.create_standalone_workingtree('.')
            self.assertEqual('A tree', tree)
        finally:
            bzrdir.BzrDirFormat.set_default_format(old_format)

    def test_create_standalone_working_tree_under_shared_repo(self):
        # create standalone working tree always makes a repo.
        old_format = bzrdir.BzrDirFormat.get_default_format()
        bzrdir.BzrDirFormat.set_default_format(bzrdir.BzrDirMetaFormat1())
        try:
            self.make_repository('.', shared=True)
            # note this is deliberately readonly, as this failure should 
            # occur before any writes.
            self.assertRaises(errors.NotLocalUrl,
                              bzrdir.BzrDir.create_standalone_workingtree,
                              self.get_readonly_url('child'))
            tree = bzrdir.BzrDir.create_standalone_workingtree('child')
            tree.bzrdir.open_repository()
        finally:
            bzrdir.BzrDirFormat.set_default_format(old_format)

    def test_create_branch_convenience(self):
        # outside a repo the default conveniencec output is a repo+branch_tree
        old_format = bzrdir.BzrDirFormat.get_default_format()
        bzrdir.BzrDirFormat.set_default_format(bzrdir.BzrDirMetaFormat1())
        try:
            branch = bzrdir.BzrDir.create_branch_convenience('.')
            branch.bzrdir.open_workingtree()
            branch.bzrdir.open_repository()
        finally:
            bzrdir.BzrDirFormat.set_default_format(old_format)

    def test_create_branch_convenience_under_shared_repo(self):
        # inside a repo the default convenience output is a branch+ follow the
        # repo tree policy
        old_format = bzrdir.BzrDirFormat.get_default_format()
        bzrdir.BzrDirFormat.set_default_format(bzrdir.BzrDirMetaFormat1())
        try:
            self.make_repository('.', shared=True)
            branch = bzrdir.BzrDir.create_branch_convenience('child')
            branch.bzrdir.open_workingtree()
            self.assertRaises(errors.NoRepositoryPresent,
                              branch.bzrdir.open_repository)
        finally:
            bzrdir.BzrDirFormat.set_default_format(old_format)
            
    def test_create_branch_convenience_under_shared_repo_force_no_tree(self):
        # inside a repo the default convenience output is a branch+ follow the
        # repo tree policy but we can override that
        old_format = bzrdir.BzrDirFormat.get_default_format()
        bzrdir.BzrDirFormat.set_default_format(bzrdir.BzrDirMetaFormat1())
        try:
            self.make_repository('.', shared=True)
            branch = bzrdir.BzrDir.create_branch_convenience('child',
                force_new_tree=False)
            self.assertRaises(errors.NoWorkingTree,
                              branch.bzrdir.open_workingtree)
            self.assertRaises(errors.NoRepositoryPresent,
                              branch.bzrdir.open_repository)
        finally:
            bzrdir.BzrDirFormat.set_default_format(old_format)
            
    def test_create_branch_convenience_under_shared_repo_no_tree_policy(self):
        # inside a repo the default convenience output is a branch+ follow the
        # repo tree policy
        old_format = bzrdir.BzrDirFormat.get_default_format()
        bzrdir.BzrDirFormat.set_default_format(bzrdir.BzrDirMetaFormat1())
        try:
            repo = self.make_repository('.', shared=True)
            repo.set_make_working_trees(False)
            branch = bzrdir.BzrDir.create_branch_convenience('child')
            self.assertRaises(errors.NoWorkingTree,
                              branch.bzrdir.open_workingtree)
            self.assertRaises(errors.NoRepositoryPresent,
                              branch.bzrdir.open_repository)
        finally:
            bzrdir.BzrDirFormat.set_default_format(old_format)

    def test_create_branch_convenience_under_shared_repo_no_tree_policy_force_tree(self):
        # inside a repo the default convenience output is a branch+ follow the
        # repo tree policy but we can override that
        old_format = bzrdir.BzrDirFormat.get_default_format()
        bzrdir.BzrDirFormat.set_default_format(bzrdir.BzrDirMetaFormat1())
        try:
            repo = self.make_repository('.', shared=True)
            repo.set_make_working_trees(False)
            branch = bzrdir.BzrDir.create_branch_convenience('child',
                force_new_tree=True)
            branch.bzrdir.open_workingtree()
            self.assertRaises(errors.NoRepositoryPresent,
                              branch.bzrdir.open_repository)
        finally:
            bzrdir.BzrDirFormat.set_default_format(old_format)

    def test_create_branch_convenience_under_shared_repo_force_new_repo(self):
        # inside a repo the default convenience output is overridable to give
        # repo+branch+tree
        old_format = bzrdir.BzrDirFormat.get_default_format()
        bzrdir.BzrDirFormat.set_default_format(bzrdir.BzrDirMetaFormat1())
        try:
            self.make_repository('.', shared=True)
            branch = bzrdir.BzrDir.create_branch_convenience('child',
                force_new_repo=True)
            branch.bzrdir.open_repository()
            branch.bzrdir.open_workingtree()
        finally:
            bzrdir.BzrDirFormat.set_default_format(old_format)


class ChrootedTests(TestCaseWithTransport):
    """A support class that provides readonly urls outside the local namespace.

    This is done by checking if self.transport_server is a MemoryServer. if it
    is then we are chrooted already, if it is not then an HttpServer is used
    for readonly urls.
    """

    def setUp(self):
        super(ChrootedTests, self).setUp()
        if not self.transport_server == MemoryServer:
            self.transport_readonly_server = HttpServer

    def test_open_containing(self):
        self.assertRaises(NotBranchError, bzrdir.BzrDir.open_containing,
                          self.get_readonly_url(''))
        self.assertRaises(NotBranchError, bzrdir.BzrDir.open_containing,
                          self.get_readonly_url('g/p/q'))
        control = bzrdir.BzrDir.create(self.get_url())
        branch, relpath = bzrdir.BzrDir.open_containing(self.get_readonly_url(''))
        self.assertEqual('', relpath)
        branch, relpath = bzrdir.BzrDir.open_containing(self.get_readonly_url('g/p/q'))
        self.assertEqual('g/p/q', relpath)

    def test_open_containing_transport(self):
        self.assertRaises(NotBranchError, bzrdir.BzrDir.open_containing_transport,
                          get_transport(self.get_readonly_url('')))
        self.assertRaises(NotBranchError, bzrdir.BzrDir.open_containing_transport,
                          get_transport(self.get_readonly_url('g/p/q')))
        control = bzrdir.BzrDir.create(self.get_url())
        branch, relpath = bzrdir.BzrDir.open_containing_transport(
            get_transport(self.get_readonly_url('')))
        self.assertEqual('', relpath)
        branch, relpath = bzrdir.BzrDir.open_containing_transport(
            get_transport(self.get_readonly_url('g/p/q')))
        self.assertEqual('g/p/q', relpath)


class TestMeta1DirFormat(TestCaseWithTransport):
    """Tests specific to the meta1 dir format."""

    def test_right_base_dirs(self):
        dir = bzrdir.BzrDirMetaFormat1().initialize(self.get_url())
        t = dir.transport
        branch_base = t.clone('branch').base
        self.assertEqual(branch_base, dir.get_branch_transport(None).base)
        self.assertEqual(branch_base,
                         dir.get_branch_transport(bzrlib.branch.BzrBranchFormat5()).base)
        repository_base = t.clone('repository').base
        self.assertEqual(repository_base, dir.get_repository_transport(None).base)
        self.assertEqual(repository_base,
                         dir.get_repository_transport(repository.RepositoryFormat7()).base)
        checkout_base = t.clone('checkout').base
        self.assertEqual(checkout_base, dir.get_workingtree_transport(None).base)
        self.assertEqual(checkout_base,
                         dir.get_workingtree_transport(workingtree.WorkingTreeFormat3()).base)


class TestFormat6(TestCaseWithTransport):
    """Tests specific to the version 6 bzrdir format."""

    def test_same_lockfiles_between_tree_repo_branch(self):
        # this checks that only a single lockfiles instance is created 
        # for format 6 objects
        dir = bzrdir.BzrDirFormat6().initialize(self.get_url())
        def check_dir_components_use_same_lock(dir):
            ctrl_1 = dir.open_repository().control_files
            ctrl_2 = dir.open_branch().control_files
            ctrl_3 = dir.open_workingtree()._control_files
            self.assertTrue(ctrl_1 is ctrl_2)
            self.assertTrue(ctrl_2 is ctrl_3)
        check_dir_components_use_same_lock(dir)
        # and if we open it normally.
        dir = bzrdir.BzrDir.open(self.get_url())
        check_dir_components_use_same_lock(dir)
