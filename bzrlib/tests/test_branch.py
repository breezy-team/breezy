# Copyright (C) 2005, 2006, 2007 Canonical Ltd
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

"""Tests for the Branch facility that are not interface  tests.

For interface tests see tests/branch_implementations/*.py.

For concrete class tests see this file, and for meta-branch tests
also see this file.
"""

from StringIO import StringIO

from bzrlib import (
    branch as _mod_branch,
    bzrdir,
    errors,
    urlutils,
    )
from bzrlib.branch import (
    Branch,
    BranchHooks,
    BranchFormat,
    BranchReferenceFormat,
    BzrBranch5,
    BzrBranchFormat5,
    )
from bzrlib.bzrdir import (BzrDirMetaFormat1, BzrDirMeta1, 
                           BzrDir, BzrDirFormat)
from bzrlib.errors import (NotBranchError,
                           UnknownFormatError,
                           UnknownHook,
                           UnsupportedFormatError,
                           )

from bzrlib.tests import TestCase, TestCaseWithTransport
from bzrlib.transport import get_transport

class TestDefaultFormat(TestCase):

    def test_get_set_default_format(self):
        old_format = BranchFormat.get_default_format()
        # default is 5
        self.assertTrue(isinstance(old_format, BzrBranchFormat5))
        BranchFormat.set_default_format(SampleBranchFormat())
        try:
            # the default branch format is used by the meta dir format
            # which is not the default bzrdir format at this point
            dir = BzrDirMetaFormat1().initialize('memory:///')
            result = dir.create_branch()
            self.assertEqual(result, 'A branch')
        finally:
            BranchFormat.set_default_format(old_format)
        self.assertEqual(old_format, BranchFormat.get_default_format())


class TestBranchFormat5(TestCaseWithTransport):
    """Tests specific to branch format 5"""

    def test_branch_format_5_uses_lockdir(self):
        url = self.get_url()
        bzrdir = BzrDirMetaFormat1().initialize(url)
        bzrdir.create_repository()
        branch = bzrdir.create_branch()
        t = self.get_transport()
        self.log("branch instance is %r" % branch)
        self.assert_(isinstance(branch, BzrBranch5))
        self.assertIsDirectory('.', t)
        self.assertIsDirectory('.bzr/branch', t)
        self.assertIsDirectory('.bzr/branch/lock', t)
        branch.lock_write()
        try:
            self.assertIsDirectory('.bzr/branch/lock/held', t)
        finally:
            branch.unlock()

    def test_set_push_location(self):
        from bzrlib.config import (locations_config_filename,
                                   ensure_config_dir_exists)
        ensure_config_dir_exists()
        fn = locations_config_filename()
        branch = self.make_branch('.', format='knit')
        branch.set_push_location('foo')
        local_path = urlutils.local_path_from_url(branch.base[:-1])
        self.assertFileEqual("[%s]\n"
                             "push_location = foo\n"
                             "push_location:policy = norecurse" % local_path,
                             fn)

    # TODO RBC 20051029 test getting a push location from a branch in a
    # recursive section - that is, it appends the branch name.


class SampleBranchFormat(BranchFormat):
    """A sample format

    this format is initializable, unsupported to aid in testing the 
    open and open_downlevel routines.
    """

    def get_format_string(self):
        """See BzrBranchFormat.get_format_string()."""
        return "Sample branch format."

    def initialize(self, a_bzrdir):
        """Format 4 branches cannot be created."""
        t = a_bzrdir.get_branch_transport(self)
        t.put_bytes('format', self.get_format_string())
        return 'A branch'

    def is_supported(self):
        return False

    def open(self, transport, _found=False):
        return "opened branch."


class TestBzrBranchFormat(TestCaseWithTransport):
    """Tests for the BzrBranchFormat facility."""

    def test_find_format(self):
        # is the right format object found for a branch?
        # create a branch with a few known format objects.
        # this is not quite the same as 
        self.build_tree(["foo/", "bar/"])
        def check_format(format, url):
            dir = format._matchingbzrdir.initialize(url)
            dir.create_repository()
            format.initialize(dir)
            found_format = BranchFormat.find_format(dir)
            self.failUnless(isinstance(found_format, format.__class__))
        check_format(BzrBranchFormat5(), "bar")
        
    def test_find_format_not_branch(self):
        dir = bzrdir.BzrDirMetaFormat1().initialize(self.get_url())
        self.assertRaises(NotBranchError,
                          BranchFormat.find_format,
                          dir)

    def test_find_format_unknown_format(self):
        dir = bzrdir.BzrDirMetaFormat1().initialize(self.get_url())
        SampleBranchFormat().initialize(dir)
        self.assertRaises(UnknownFormatError,
                          BranchFormat.find_format,
                          dir)

    def test_register_unregister_format(self):
        format = SampleBranchFormat()
        # make a control dir
        dir = bzrdir.BzrDirMetaFormat1().initialize(self.get_url())
        # make a branch
        format.initialize(dir)
        # register a format for it.
        BranchFormat.register_format(format)
        # which branch.Open will refuse (not supported)
        self.assertRaises(UnsupportedFormatError, Branch.open, self.get_url())
        self.make_branch_and_tree('foo')
        # but open_downlevel will work
        self.assertEqual(format.open(dir), bzrdir.BzrDir.open(self.get_url()).open_branch(unsupported=True))
        # unregister the format
        BranchFormat.unregister_format(format)
        self.make_branch_and_tree('bar')

    def test_checkout_format(self):
        branch = self.make_repository('repository', shared=True)
        branch = self.make_branch('repository/branch',
            format='metaweave')
        tree = branch.create_checkout('checkout')
        self.assertIs(tree.branch.__class__, _mod_branch.BzrBranch5)


class TestBranch6(TestCaseWithTransport):

    def test_creation(self):
        format = BzrDirMetaFormat1()
        format.set_branch_format(_mod_branch.BzrBranchFormat6())
        branch = self.make_branch('a', format=format)
        self.assertIsInstance(branch, _mod_branch.BzrBranch6)
        branch = self.make_branch('b', format='experimental-branch6')
        self.assertIsInstance(branch, _mod_branch.BzrBranch6)
        branch = _mod_branch.Branch.open('a')
        self.assertIsInstance(branch, _mod_branch.BzrBranch6)

    def test_layout(self):
        branch = self.make_branch('a', format='experimental-branch6')
        self.failUnlessExists('a/.bzr/branch/last-revision')
        self.failIfExists('a/.bzr/branch/revision-history')

    def test_config(self):
        """Ensure that all configuration data is stored in the branch"""
        branch = self.make_branch('a', format='experimental-branch6')
        branch.set_parent('http://bazaar-vcs.org')
        self.failIfExists('a/.bzr/branch/parent')
        self.assertEqual('http://bazaar-vcs.org', branch.get_parent())
        branch.set_push_location('sftp://bazaar-vcs.org')
        config = branch.get_config()._get_branch_data_config()
        self.assertEqual('sftp://bazaar-vcs.org',
                         config.get_user_option('push_location'))
        branch.set_bound_location('ftp://bazaar-vcs.org')
        self.failIfExists('a/.bzr/branch/bound')
        self.assertEqual('ftp://bazaar-vcs.org', branch.get_bound_location())

    def test_set_revision_history(self):
        tree = self.make_branch_and_memory_tree('.',
            format='experimental-branch6')
        tree.lock_write()
        try:
            tree.add('.')
            tree.commit('foo', rev_id='foo')
            tree.commit('bar', rev_id='bar')
            tree.branch.set_revision_history(['foo', 'bar'])
            tree.branch.set_revision_history(['foo'])
            self.assertRaises(errors.NotLefthandHistory,
                              tree.branch.set_revision_history, ['bar'])
        finally:
            tree.unlock()

    def test_append_revision(self):
        tree = self.make_branch_and_tree('branch1',
            format='experimental-branch6')
        tree.lock_write()
        try:
            tree.add('.')
            tree.commit('foo', rev_id='foo')
            tree.commit('bar', rev_id='bar')
            tree.commit('baz', rev_id='baz')
            tree.set_last_revision('bar')
            tree.branch.set_last_revision_info(2, 'bar')
            tree.commit('qux', rev_id='qux')
            tree.add_parent_tree_id('baz')
            tree.commit('qux', rev_id='quxx')
            tree.branch.set_last_revision_info(0, 'null:')
            self.assertRaises(errors.NotLeftParentDescendant,
                              tree.branch.append_revision, 'bar')
            tree.branch.append_revision('foo')
            self.assertRaises(errors.NotLeftParentDescendant,
                              tree.branch.append_revision, 'baz')
            tree.branch.append_revision('bar')
            tree.branch.append_revision('baz')
            self.assertRaises(errors.NotLeftParentDescendant,
                              tree.branch.append_revision, 'quxx')
        finally:
            tree.unlock()


class TestBranchReference(TestCaseWithTransport):
    """Tests for the branch reference facility."""

    def test_create_open_reference(self):
        bzrdirformat = bzrdir.BzrDirMetaFormat1()
        t = get_transport(self.get_url('.'))
        t.mkdir('repo')
        dir = bzrdirformat.initialize(self.get_url('repo'))
        dir.create_repository()
        target_branch = dir.create_branch()
        t.mkdir('branch')
        branch_dir = bzrdirformat.initialize(self.get_url('branch'))
        made_branch = BranchReferenceFormat().initialize(branch_dir, target_branch)
        self.assertEqual(made_branch.base, target_branch.base)
        opened_branch = branch_dir.open_branch()
        self.assertEqual(opened_branch.base, target_branch.base)


class TestHooks(TestCase):

    def test_constructor(self):
        """Check that creating a BranchHooks instance has the right defaults."""
        hooks = BranchHooks()
        self.assertTrue("set_rh" in hooks, "set_rh not in %s" % hooks)
        self.assertTrue("post_push" in hooks, "post_push not in %s" % hooks)
        self.assertTrue("post_commit" in hooks, "post_commit not in %s" % hooks)
        self.assertTrue("post_pull" in hooks, "post_pull not in %s" % hooks)
        self.assertTrue("post_uncommit" in hooks, "post_uncommit not in %s" % hooks)

    def test_installed_hooks_are_BranchHooks(self):
        """The installed hooks object should be a BranchHooks."""
        # the installed hooks are saved in self._preserved_hooks.
        self.assertIsInstance(self._preserved_hooks, BranchHooks)

    def test_install_hook_raises_unknown_hook(self):
        """install_hook should raise UnknownHook if a hook is unknown."""
        hooks = BranchHooks()
        self.assertRaises(UnknownHook, hooks.install_hook, 'silly', None)

    def test_install_hook_appends_known_hook(self):
        """install_hook should append the callable for known hooks."""
        hooks = BranchHooks()
        hooks.install_hook('set_rh', None)
        self.assertEqual(hooks['set_rh'], [None])
