# Copyright (C) 2005, 2006 Canonical Ltd
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

"""Tests for the BzrDir facility and any format specific tests.

For interface contract tests, see tests/bzr_dir_implementations.
"""

from StringIO import StringIO

from bzrlib import (
    help_topics,
    )
import bzrlib.branch
import bzrlib.bzrdir as bzrdir
import bzrlib.errors as errors
from bzrlib.errors import (NotBranchError,
                           UnknownFormatError,
                           UnsupportedFormatError,
                           )
import bzrlib.repository as repository
from bzrlib.tests import TestCase, TestCaseWithTransport
from bzrlib.tests.HttpServer import HttpServer
from bzrlib.transport import get_transport
from bzrlib.transport.memory import MemoryServer
import bzrlib.workingtree as workingtree


class TestDefaultFormat(TestCase):

    def test_get_set_default_format(self):
        old_format = bzrdir.BzrDirFormat.get_default_format()
        # default is BzrDirFormat6
        self.failUnless(isinstance(old_format, bzrdir.BzrDirMetaFormat1))
        bzrdir.BzrDirFormat.set_default_format(SampleBzrDirFormat())
        # creating a bzr dir should now create an instrumented dir.
        try:
            result = bzrdir.BzrDir.create('memory:///')
            self.failUnless(isinstance(result, SampleBzrDir))
        finally:
            bzrdir.BzrDirFormat.set_default_format(old_format)
        self.assertEqual(old_format, bzrdir.BzrDirFormat.get_default_format())


class TestFormatRegistry(TestCase):

    def make_format_registry(self):
        my_format_registry = bzrdir.BzrDirFormatRegistry()
        my_format_registry.register('weave', bzrdir.BzrDirFormat6,
            'Pre-0.8 format.  Slower and does not support checkouts or shared'
            ' repositories', deprecated=True)
        my_format_registry.register_lazy('lazy', 'bzrlib.bzrdir', 
            'BzrDirFormat6', 'Format registered lazily', deprecated=True)
        my_format_registry.register_metadir('knit', 'RepositoryFormatKnit1',
            'Format using knits')
        my_format_registry.set_default('knit')
        my_format_registry.register_metadir('metaweave', 'RepositoryFormat7',
            'Transitional format in 0.8.  Slower than knit.', deprecated=True)
        my_format_registry.register_metadir('experimental-knit2', 
                                            'RepositoryFormatKnit2',
            'Experimental successor to knit.  Use at your own risk.')
        return my_format_registry

    def test_format_registry(self):
        my_format_registry = self.make_format_registry()
        my_bzrdir = my_format_registry.make_bzrdir('lazy')
        self.assertIsInstance(my_bzrdir, bzrdir.BzrDirFormat6)
        my_bzrdir = my_format_registry.make_bzrdir('weave')
        self.assertIsInstance(my_bzrdir, bzrdir.BzrDirFormat6)
        my_bzrdir = my_format_registry.make_bzrdir('default')
        self.assertIsInstance(my_bzrdir.repository_format, 
            repository.RepositoryFormatKnit1)
        my_bzrdir = my_format_registry.make_bzrdir('knit')
        self.assertIsInstance(my_bzrdir.repository_format, 
            repository.RepositoryFormatKnit1)
        my_bzrdir = my_format_registry.make_bzrdir('metaweave')
        self.assertIsInstance(my_bzrdir.repository_format, 
            repository.RepositoryFormat7)

    def test_get_help(self):
        my_format_registry = self.make_format_registry()
        self.assertEqual('Format registered lazily',
                         my_format_registry.get_help('lazy'))
        self.assertEqual('Format using knits', 
                         my_format_registry.get_help('knit'))
        self.assertEqual('Format using knits', 
                         my_format_registry.get_help('default'))
        self.assertEqual('Pre-0.8 format.  Slower and does not support'
                         ' checkouts or shared repositories', 
                         my_format_registry.get_help('weave'))
        
    def test_help_topic(self):
        topics = help_topics.HelpTopicRegistry()
        topics.register('formats', self.make_format_registry().help_topic, 
                        'Directory formats')
        topic = topics.get_detail('formats')
        new, deprecated = topic.split('Deprecated formats')
        self.assertContainsRe(new, 'Bazaar directory formats')
        self.assertContainsRe(new, 
            '  knit/default:\n    \(native\) Format using knits\n')
        self.assertContainsRe(deprecated, 
            '  lazy:\n    \(native\) Format registered lazily\n')

    def test_set_default_repository(self):
        default_factory = bzrdir.format_registry.get('default')
        old_default = [k for k, v in bzrdir.format_registry.iteritems()
                       if v == default_factory and k != 'default'][0]
        bzrdir.format_registry.set_default_repository('metaweave')
        try:
            self.assertIs(bzrdir.format_registry.get('metaweave'),
                          bzrdir.format_registry.get('default'))
            self.assertIs(
                repository.RepositoryFormat.get_default_format().__class__,
                repository.RepositoryFormat7)
        finally:
            bzrdir.format_registry.set_default_repository(old_default)

class SampleBranch(bzrlib.branch.Branch):
    """A dummy branch for guess what, dummy use."""

    def __init__(self, dir):
        self.bzrdir = dir


class SampleBzrDir(bzrdir.BzrDir):
    """A sample BzrDir implementation to allow testing static methods."""

    def create_repository(self, shared=False):
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
        t.put_bytes('.bzr/branch-format', self.get_format_string())
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
        t.put_bytes('.bzr/branch-format', '')
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
        # which bzrdir.open_containing will refuse (not supported)
        self.assertRaises(UnsupportedFormatError, bzrdir.BzrDir.open_containing, url)
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

    def test_create_repository_shared(self):
        old_format = bzrdir.BzrDirFormat.get_default_format()
        repo = bzrdir.BzrDir.create_repository('.', shared=True)
        self.assertTrue(repo.is_shared())

    def test_create_repository_nonshared(self):
        old_format = bzrdir.BzrDirFormat.get_default_format()
        repo = bzrdir.BzrDir.create_repository('.')
        self.assertFalse(repo.is_shared())

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
        # outside a repo the default convenience output is a repo+branch_tree
        old_format = bzrdir.BzrDirFormat.get_default_format()
        bzrdir.BzrDirFormat.set_default_format(bzrdir.BzrDirMetaFormat1())
        try:
            branch = bzrdir.BzrDir.create_branch_convenience('.')
            branch.bzrdir.open_workingtree()
            branch.bzrdir.open_repository()
        finally:
            bzrdir.BzrDirFormat.set_default_format(old_format)

    def test_create_branch_convenience_root(self):
        """Creating a branch at the root of a fs should work."""
        self.transport_server = MemoryServer
        # outside a repo the default convenience output is a repo+branch_tree
        old_format = bzrdir.BzrDirFormat.get_default_format()
        bzrdir.BzrDirFormat.set_default_format(bzrdir.BzrDirMetaFormat1())
        try:
            branch = bzrdir.BzrDir.create_branch_convenience(self.get_url())
            self.assertRaises(errors.NoWorkingTree,
                              branch.bzrdir.open_workingtree)
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

    def test_open_containing_from_transport(self):
        self.assertRaises(NotBranchError, bzrdir.BzrDir.open_containing_from_transport,
                          get_transport(self.get_readonly_url('')))
        self.assertRaises(NotBranchError, bzrdir.BzrDir.open_containing_from_transport,
                          get_transport(self.get_readonly_url('g/p/q')))
        control = bzrdir.BzrDir.create(self.get_url())
        branch, relpath = bzrdir.BzrDir.open_containing_from_transport(
            get_transport(self.get_readonly_url('')))
        self.assertEqual('', relpath)
        branch, relpath = bzrdir.BzrDir.open_containing_from_transport(
            get_transport(self.get_readonly_url('g/p/q')))
        self.assertEqual('g/p/q', relpath)

    def test_open_from_transport(self):
        # transport pointing at bzrdir should give a bzrdir with root transport
        # set to the given transport
        control = bzrdir.BzrDir.create(self.get_url())
        transport = get_transport(self.get_url())
        opened_bzrdir = bzrdir.BzrDir.open_from_transport(transport)
        self.assertEqual(transport.base, opened_bzrdir.root_transport.base)
        self.assertIsInstance(opened_bzrdir, bzrdir.BzrDir)
        
    def test_open_from_transport_no_bzrdir(self):
        transport = get_transport(self.get_url())
        self.assertRaises(NotBranchError, bzrdir.BzrDir.open_from_transport,
                          transport)

    def test_open_from_transport_bzrdir_in_parent(self):
        control = bzrdir.BzrDir.create(self.get_url())
        transport = get_transport(self.get_url())
        transport.mkdir('subdir')
        transport = transport.clone('subdir')
        self.assertRaises(NotBranchError, bzrdir.BzrDir.open_from_transport,
                          transport)


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

    def test_meta1dir_uses_lockdir(self):
        """Meta1 format uses a LockDir to guard the whole directory, not a file."""
        dir = bzrdir.BzrDirMetaFormat1().initialize(self.get_url())
        t = dir.transport
        self.assertIsDirectory('branch-lock', t)

        
class TestFormat5(TestCaseWithTransport):
    """Tests specific to the version 5 bzrdir format."""

    def test_same_lockfiles_between_tree_repo_branch(self):
        # this checks that only a single lockfiles instance is created 
        # for format 5 objects
        dir = bzrdir.BzrDirFormat5().initialize(self.get_url())
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
    
    def test_can_convert(self):
        # format 5 dirs are convertable
        dir = bzrdir.BzrDirFormat5().initialize(self.get_url())
        self.assertTrue(dir.can_convert_format())
    
    def test_needs_conversion(self):
        # format 5 dirs need a conversion if they are not the default.
        # and they start of not the default.
        old_format = bzrdir.BzrDirFormat.get_default_format()
        bzrdir.BzrDirFormat.set_default_format(bzrdir.BzrDirFormat5())
        try:
            dir = bzrdir.BzrDirFormat5().initialize(self.get_url())
            self.assertFalse(dir.needs_format_conversion())
        finally:
            bzrdir.BzrDirFormat.set_default_format(old_format)
        self.assertTrue(dir.needs_format_conversion())


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
    
    def test_can_convert(self):
        # format 6 dirs are convertable
        dir = bzrdir.BzrDirFormat6().initialize(self.get_url())
        self.assertTrue(dir.can_convert_format())
    
    def test_needs_conversion(self):
        # format 6 dirs need an conversion if they are not the default.
        old_format = bzrdir.BzrDirFormat.get_default_format()
        bzrdir.BzrDirFormat.set_default_format(bzrdir.BzrDirMetaFormat1())
        try:
            dir = bzrdir.BzrDirFormat6().initialize(self.get_url())
            self.assertTrue(dir.needs_format_conversion())
        finally:
            bzrdir.BzrDirFormat.set_default_format(old_format)


class NotBzrDir(bzrlib.bzrdir.BzrDir):
    """A non .bzr based control directory."""

    def __init__(self, transport, format):
        self._format = format
        self.root_transport = transport
        self.transport = transport.clone('.not')


class NotBzrDirFormat(bzrlib.bzrdir.BzrDirFormat):
    """A test class representing any non-.bzr based disk format."""

    def initialize_on_transport(self, transport):
        """Initialize a new .not dir in the base directory of a Transport."""
        transport.mkdir('.not')
        return self.open(transport)

    def open(self, transport):
        """Open this directory."""
        return NotBzrDir(transport, self)

    @classmethod
    def _known_formats(self):
        return set([NotBzrDirFormat()])

    @classmethod
    def probe_transport(self, transport):
        """Our format is present if the transport ends in '.not/'."""
        if transport.has('.not'):
            return NotBzrDirFormat()


class TestNotBzrDir(TestCaseWithTransport):
    """Tests for using the bzrdir api with a non .bzr based disk format.
    
    If/when one of these is in the core, we can let the implementation tests
    verify this works.
    """

    def test_create_and_find_format(self):
        # create a .notbzr dir 
        format = NotBzrDirFormat()
        dir = format.initialize(self.get_url())
        self.assertIsInstance(dir, NotBzrDir)
        # now probe for it.
        bzrlib.bzrdir.BzrDirFormat.register_control_format(format)
        try:
            found = bzrlib.bzrdir.BzrDirFormat.find_format(
                get_transport(self.get_url()))
            self.assertIsInstance(found, NotBzrDirFormat)
        finally:
            bzrlib.bzrdir.BzrDirFormat.unregister_control_format(format)

    def test_included_in_known_formats(self):
        bzrlib.bzrdir.BzrDirFormat.register_control_format(NotBzrDirFormat)
        try:
            formats = bzrlib.bzrdir.BzrDirFormat.known_formats()
            for format in formats:
                if isinstance(format, NotBzrDirFormat):
                    return
            self.fail("No NotBzrDirFormat in %s" % formats)
        finally:
            bzrlib.bzrdir.BzrDirFormat.unregister_control_format(NotBzrDirFormat)


class NonLocalTests(TestCaseWithTransport):
    """Tests for bzrdir static behaviour on non local paths."""

    def setUp(self):
        super(NonLocalTests, self).setUp()
        self.transport_server = MemoryServer
    
    def test_create_branch_convenience(self):
        # outside a repo the default convenience output is a repo+branch_tree
        old_format = bzrdir.BzrDirFormat.get_default_format()
        bzrdir.BzrDirFormat.set_default_format(bzrdir.BzrDirMetaFormat1())
        try:
            branch = bzrdir.BzrDir.create_branch_convenience(self.get_url('foo'))
            self.assertRaises(errors.NoWorkingTree,
                              branch.bzrdir.open_workingtree)
            branch.bzrdir.open_repository()
        finally:
            bzrdir.BzrDirFormat.set_default_format(old_format)

    def test_create_branch_convenience_force_tree_not_local_fails(self):
        # outside a repo the default convenience output is a repo+branch_tree
        old_format = bzrdir.BzrDirFormat.get_default_format()
        bzrdir.BzrDirFormat.set_default_format(bzrdir.BzrDirMetaFormat1())
        try:
            self.assertRaises(errors.NotLocalUrl,
                bzrdir.BzrDir.create_branch_convenience,
                self.get_url('foo'),
                force_new_tree=True)
            t = get_transport(self.get_url('.'))
            self.assertFalse(t.has('foo'))
        finally:
            bzrdir.BzrDirFormat.set_default_format(old_format)

    def test_clone(self):
        # clone into a nonlocal path works
        old_format = bzrdir.BzrDirFormat.get_default_format()
        bzrdir.BzrDirFormat.set_default_format(bzrdir.BzrDirMetaFormat1())
        try:
            branch = bzrdir.BzrDir.create_branch_convenience('local')
        finally:
            bzrdir.BzrDirFormat.set_default_format(old_format)
        branch.bzrdir.open_workingtree()
        result = branch.bzrdir.clone(self.get_url('remote'))
        self.assertRaises(errors.NoWorkingTree,
                          result.open_workingtree)
        result.open_branch()
        result.open_repository()

