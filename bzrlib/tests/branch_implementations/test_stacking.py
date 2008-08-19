# Copyright (C) 2008 Canonical Ltd
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

"""Tests for Branch.get_stacked_on_url and set_stacked_on_url."""

from bzrlib import (
    bzrdir,
    errors,
    )
from bzrlib.revision import NULL_REVISION
from bzrlib.tests import TestNotApplicable, KnownFailure
from bzrlib.tests.branch_implementations import TestCaseWithBranch


class TestStacking(TestCaseWithBranch):

    def test_get_set_stacked_on_url(self):
        # branches must either:
        # raise UnstackableBranchFormat or
        # raise UnstackableRepositoryFormat or
        # permit stacking to be done and then return the stacked location.
        branch = self.make_branch('branch')
        target = self.make_branch('target')
        old_format_errors = (
            errors.UnstackableBranchFormat,
            errors.UnstackableRepositoryFormat,
            )
        try:
            branch.set_stacked_on_url(target.base)
        except old_format_errors:
            # if the set failed, so must the get
            self.assertRaises(old_format_errors, branch.get_stacked_on_url)
            return
        # now we have a stacked branch:
        self.assertEqual(target.base, branch.get_stacked_on_url())
        branch.set_stacked_on_url(None)
        self.assertRaises(errors.NotStacked, branch.get_stacked_on_url)

    def test_get_set_stacked_on_relative(self):
        # Branches can be stacked on other branches using relative paths.
        branch = self.make_branch('branch')
        target = self.make_branch('target')
        old_format_errors = (
            errors.UnstackableBranchFormat,
            errors.UnstackableRepositoryFormat,
            )
        try:
            branch.set_stacked_on_url('../target')
        except old_format_errors:
            # if the set failed, so must the get
            self.assertRaises(old_format_errors, branch.get_stacked_on_url)
            return
        self.assertEqual('../target', branch.get_stacked_on_url())

    def assertRevisionInRepository(self, repo_path, revid):
        """Check that a revision is in a repository, disregarding stacking."""
        repo = bzrdir.BzrDir.open(repo_path).open_repository()
        self.assertTrue(repo.has_revision(revid))

    def assertRevisionNotInRepository(self, repo_path, revid):
        """Check that a revision is not in a repository, disregarding stacking."""
        repo = bzrdir.BzrDir.open(repo_path).open_repository()
        self.assertFalse(repo.has_revision(revid))

    def test_get_graph_stacked(self):
        """A stacked repository shows the graph of its parent."""
        trunk_tree = self.make_branch_and_tree('mainline')
        trunk_revid = trunk_tree.commit('mainline')
        # make a new branch, and stack on the existing one.  we don't use
        # sprout(stacked=True) here because if that is buggy and copies data
        # it would cause a false pass of this test.
        new_branch = self.make_branch('new_branch')
        try:
            new_branch.set_stacked_on_url(trunk_tree.branch.base)
        except (errors.UnstackableBranchFormat,
            errors.UnstackableRepositoryFormat), e:
            raise TestNotApplicable(e)
        # reading the graph from the stacked branch's repository should see
        # data from the stacked-on branch
        new_repo = new_branch.repository
        new_repo.lock_read()
        try:
            self.assertEqual(new_repo.get_parent_map([trunk_revid]),
                {trunk_revid: (NULL_REVISION, )})
        finally:
            new_repo.unlock()

    def test_sprout_stacked(self):
        # We have a mainline
        trunk_tree = self.make_branch_and_tree('mainline')
        trunk_revid = trunk_tree.commit('mainline')
        # and make branch from it which is stacked
        try:
            new_dir = trunk_tree.bzrdir.sprout('newbranch', stacked=True)
        except (errors.UnstackableBranchFormat,
            errors.UnstackableRepositoryFormat), e:
            raise TestNotApplicable(e)
        # stacked repository
        self.assertRevisionNotInRepository('newbranch', trunk_revid)
        new_tree = new_dir.open_workingtree()
        new_branch_revid = new_tree.commit('something local')
        self.assertRevisionNotInRepository('mainline', new_branch_revid)
        self.assertRevisionInRepository('newbranch', new_branch_revid)

    def test_unstack_fetches(self):
        """Removing the stacked-on branch pulls across all data"""
        # We have a mainline
        trunk_tree = self.make_branch_and_tree('mainline')
        trunk_revid = trunk_tree.commit('revision on mainline')
        # and make branch from it which is stacked
        try:
            new_dir = trunk_tree.bzrdir.sprout('newbranch', stacked=True)
        except (errors.UnstackableBranchFormat,
            errors.UnstackableRepositoryFormat), e:
            raise TestNotApplicable(e)
        # stacked repository
        self.assertRevisionNotInRepository('newbranch', trunk_revid)
        # now when we unstack that should implicitly fetch, to make sure that
        # the branch will still work
        new_branch = new_dir.open_branch()
        new_branch.set_stacked_on_url(None)
        self.assertRevisionInRepository('newbranch', trunk_revid)
        # of course it's still in the mainline
        self.assertRevisionInRepository('mainline', trunk_revid)
        # and now we're no longer stacked
        self.assertRaises(errors.NotStacked,
            new_branch.get_stacked_on_url)

    def make_stacked_bzrdir(self, in_directory=None):
        """Create a stacked branch and return its bzrdir.

        :param in_directory: If not None, create a directory of this
            name and create the stacking and stacked-on bzrdirs in
            this directory.
        """
        if in_directory is not None:
            self.get_transport().mkdir(in_directory)
            prefix = in_directory + '/'
        else:
            prefix = ''
        tree = self.make_branch_and_tree(prefix + 'stacked-on')
        tree.commit('Added foo')
        stacked_bzrdir = tree.branch.bzrdir.sprout(
            prefix + 'stacked', tree.branch.last_revision(), stacked=True)
        return stacked_bzrdir

    def test_clone_from_stacked_branch_preserve_stacking(self):
        # We can clone from the bzrdir of a stacked branch. If
        # preserve_stacking is True, the cloned branch is stacked on the
        # same branch as the original.
        try:
            stacked_bzrdir = self.make_stacked_bzrdir()
        except (errors.UnstackableBranchFormat,
                errors.UnstackableRepositoryFormat), e:
            # not a testable combination.
            raise TestNotApplicable(e)
        cloned_bzrdir = stacked_bzrdir.clone('cloned', preserve_stacking=True)
        try:
            self.assertEqual(
                stacked_bzrdir.open_branch().get_stacked_on_url(),
                cloned_bzrdir.open_branch().get_stacked_on_url())
        except (errors.UnstackableBranchFormat,
                errors.UnstackableRepositoryFormat):
            pass

    def test_clone_from_branch_stacked_on_relative_url_preserve_stacking(self):
        # If a branch's stacked-on url is relative, we can still clone
        # from it with preserve_stacking True and get a branch stacked
        # on an appropriately adjusted relative url.
        try:
            stacked_bzrdir = self.make_stacked_bzrdir(in_directory='dir')
        except (errors.UnstackableBranchFormat,
                errors.UnstackableRepositoryFormat), e:
            # not a testable combination.
            raise TestNotApplicable(e)
        stacked_bzrdir.open_branch().set_stacked_on_url('../stacked-on')
        cloned_bzrdir = stacked_bzrdir.clone('cloned', preserve_stacking=True)
        self.assertEqual(
            '../dir/stacked-on',
            cloned_bzrdir.open_branch().get_stacked_on_url())

    def test_clone_from_stacked_branch_no_preserve_stacking(self):
        try:
            stacked_bzrdir = self.make_stacked_bzrdir()
        except (errors.UnstackableBranchFormat,
                errors.UnstackableRepositoryFormat), e:
            # not a testable combination.
            raise TestNotApplicable(e)
        cloned_unstacked_bzrdir = stacked_bzrdir.clone('cloned-unstacked',
            preserve_stacking=False)
        unstacked_branch = cloned_unstacked_bzrdir.open_branch()
        self.assertRaises((errors.NotStacked, errors.UnstackableBranchFormat),
                          unstacked_branch.get_stacked_on_url)

    def test_no_op_preserve_stacking(self):
        """With no stacking, preserve_stacking should be a no-op."""
        branch = self.make_branch('source')
        cloned_bzrdir = branch.bzrdir.clone('cloned', preserve_stacking=True)
        self.assertRaises((errors.NotStacked, errors.UnstackableBranchFormat),
                          cloned_bzrdir.open_branch().get_stacked_on_url)

    def test_sprout_stacking_policy_handling(self):
        """Obey policy where possible, ignore otherwise."""
        stack_on = self.make_branch('stack-on')
        parent_bzrdir = self.make_bzrdir('.', format='default')
        parent_bzrdir.get_config().set_default_stack_on('stack-on')
        source = self.make_branch('source')
        target = source.bzrdir.sprout('target').open_branch()
        # XXX: Determining stacking from a containing bzrdir has been
        #      explicitly disabled.
        self.assertRaises((errors.UnstackableBranchFormat, errors.NotStacked),
                          target.get_stacked_on_url)

    def test_clone_stacking_policy_handling(self):
        """Obey policy where possible, ignore otherwise."""
        stack_on = self.make_branch('stack-on')
        parent_bzrdir = self.make_bzrdir('.', format='default')
        parent_bzrdir.get_config().set_default_stack_on('stack-on')
        source = self.make_branch('source')
        target = source.bzrdir.clone('target').open_branch()
        # XXX: Determining stacking from a containing bzrdir has been
        #      explicitly disabled.
        self.assertRaises((errors.UnstackableBranchFormat, errors.NotStacked),
                          target.get_stacked_on_url)

    def prepare_stacked_on_fetch(self):
        stack_on = self.make_branch_and_tree('stack-on')
        stack_on.commit('first commit', rev_id='rev1')
        try:
            stacked_dir = stack_on.bzrdir.sprout('stacked', stacked=True)
        except (errors.UnstackableRepositoryFormat,
                errors.UnstackableBranchFormat):
            raise TestNotApplicable('Format does not support stacking.')
        unstacked = self.make_repository('unstacked')
        return stacked_dir.open_workingtree(), unstacked

    def test_fetch_copies_from_stacked_on(self):
        stacked, unstacked = self.prepare_stacked_on_fetch()
        unstacked.fetch(stacked.branch.repository, 'rev1')
        unstacked.get_revision('rev1')

    def test_fetch_copies_from_stacked_on_and_stacked(self):
        stacked, unstacked = self.prepare_stacked_on_fetch()
        stacked.commit('second commit', rev_id='rev2')
        unstacked.fetch(stacked.branch.repository, 'rev2')
        unstacked.get_revision('rev1')
        unstacked.get_revision('rev2')

    def test_autopack_when_stacked(self):
        # in bzr.dev as of 20080730, autopack was reported to fail in stacked
        # repositories because of problems with text deltas spanning physical
        # repository boundaries.  however, i didn't actually get this test to
        # fail on that code. -- mbp
        # see https://bugs.launchpad.net/bzr/+bug/252821
        if not self.branch_format.supports_stacking():
            raise TestNotApplicable("%r does not support stacking"
                % self.branch_format)
        stack_on = self.make_branch_and_tree('stack-on')
        text_lines = ['line %d blah blah blah\n' % i for i in range(20)]
        self.build_tree_contents([('stack-on/a', ''.join(text_lines))])
        stack_on.add('a')
        stack_on.commit('base commit')
        stacked_dir = stack_on.bzrdir.sprout('stacked', stacked=True)
        stacked_tree = stacked_dir.open_workingtree()
        for i in range(20):
            text_lines[0] = 'changed in %d\n' % i
            self.build_tree_contents([('stacked/a', ''.join(text_lines))])
            stacked_tree.commit('commit %d' % i)
        stacked_tree.branch.repository.pack()
        stacked_tree.branch.check()

    def test_pull_delta_when_stacked(self):
        if not self.branch_format.supports_stacking():
            raise TestNotApplicable("%r does not support stacking"
                % self.branch_format)
        stack_on = self.make_branch_and_tree('stack-on')
        text_lines = ['line %d blah blah blah\n' % i for i in range(20)]
        self.build_tree_contents([('stack-on/a', ''.join(text_lines))])
        stack_on.add('a')
        stack_on.commit('base commit')
        # make a stacked branch from the mainline
        stacked_dir = stack_on.bzrdir.sprout('stacked', stacked=True)
        stacked_tree = stacked_dir.open_workingtree()
        # make a second non-stacked branch from the mainline
        other_dir = stack_on.bzrdir.sprout('other')
        other_tree = other_dir.open_workingtree()
        text_lines[9] = 'changed in other\n'
        self.build_tree_contents([('other/a', ''.join(text_lines))])
        other_tree.commit('commit in other')
        # this should have generated a delta; try to pull that across
        # bug 252821 caused a RevisionNotPresent here...
        stacked_tree.pull(other_tree.branch)
        stacked_tree.branch.repository.pack()
        stacked_tree.branch.check()

    def test_fetch_revisions_with_file_changes(self):
        # Fetching revisions including file changes into a stacked branch
        # works without error.
        # Make the source tree.
        src_tree = self.make_branch_and_tree('src')
        self.build_tree_contents([('src/a', 'content')])
        src_tree.add('a')
        src_tree.commit('first commit')

        # Make the stacked-on branch.
        src_tree.bzrdir.sprout('stacked-on')

        # Make a branch stacked on it.
        target = self.make_branch('target')
        try:
            target.set_stacked_on_url('../stacked-on')
        except (errors.UnstackableRepositoryFormat,
                errors.UnstackableBranchFormat):
            raise TestNotApplicable('Format does not support stacking.')

        # Change the source branch.
        self.build_tree_contents([('src/a', 'new content')])
        src_tree.commit('second commit', rev_id='rev2')

        # Fetch changes to the target.
        target.fetch(src_tree.branch)
        rtree = target.repository.revision_tree('rev2')
        rtree.lock_read()
        self.addCleanup(rtree.unlock)
        self.assertEqual('new content', rtree.get_file_by_path('a').read())
