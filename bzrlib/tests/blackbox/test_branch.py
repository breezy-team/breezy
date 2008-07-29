# Copyright (C) 2005, 2006, 2008 Canonical Ltd
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


"""Black-box tests for bzr branch."""

import os

from bzrlib import (branch, bzrdir, errors, repository)
from bzrlib.repofmt.knitrepo import RepositoryFormatKnit1
from bzrlib.tests.blackbox import ExternalBase
from bzrlib.tests import HardlinkFeature
from bzrlib.tests.test_sftp_transport import TestCaseWithSFTPServer
from bzrlib.workingtree import WorkingTree


class TestBranch(ExternalBase):

    def example_branch(self, path='.'):
        tree = self.make_branch_and_tree(path)
        self.build_tree_contents([(path + '/hello', 'foo')])
        tree.add('hello')
        tree.commit(message='setup')
        self.build_tree_contents([(path + '/goodbye', 'baz')])
        tree.add('goodbye')
        tree.commit(message='setup')

    def test_branch(self):
        """Branch from one branch to another."""
        self.example_branch('a')
        self.run_bzr('branch a b')
        b = branch.Branch.open('b')
        self.run_bzr('branch a c -r 1')
        # previously was erroneously created by branching
        self.assertFalse(b._transport.has('branch-name'))
        b.bzrdir.open_workingtree().commit(message='foo', allow_pointless=True)

    def test_branch_only_copies_history(self):
        # Knit branches should only push the history for the current revision.
        format = bzrdir.BzrDirMetaFormat1()
        format.repository_format = RepositoryFormatKnit1()
        shared_repo = self.make_repository('repo', format=format, shared=True)
        shared_repo.set_make_working_trees(True)

        def make_shared_tree(path):
            shared_repo.bzrdir.root_transport.mkdir(path)
            shared_repo.bzrdir.create_branch_convenience('repo/' + path)
            return WorkingTree.open('repo/' + path)
        tree_a = make_shared_tree('a')
        self.build_tree(['repo/a/file'])
        tree_a.add('file')
        tree_a.commit('commit a-1', rev_id='a-1')
        f = open('repo/a/file', 'ab')
        f.write('more stuff\n')
        f.close()
        tree_a.commit('commit a-2', rev_id='a-2')

        tree_b = make_shared_tree('b')
        self.build_tree(['repo/b/file'])
        tree_b.add('file')
        tree_b.commit('commit b-1', rev_id='b-1')

        self.assertTrue(shared_repo.has_revision('a-1'))
        self.assertTrue(shared_repo.has_revision('a-2'))
        self.assertTrue(shared_repo.has_revision('b-1'))

        # Now that we have a repository with shared files, make sure
        # that things aren't copied out by a 'branch'
        self.run_bzr('branch repo/b branch-b')
        pushed_tree = WorkingTree.open('branch-b')
        pushed_repo = pushed_tree.branch.repository
        self.assertFalse(pushed_repo.has_revision('a-1'))
        self.assertFalse(pushed_repo.has_revision('a-2'))
        self.assertTrue(pushed_repo.has_revision('b-1'))

    def test_branch_hardlink(self):
        self.requireFeature(HardlinkFeature)
        source = self.make_branch_and_tree('source')
        self.build_tree(['source/file1'])
        source.add('file1')
        source.commit('added file')
        self.run_bzr(['branch', 'source', 'target', '--hardlink'])
        source_stat = os.stat('source/file1')
        target_stat = os.stat('target/file1')
        self.assertEqual(source_stat, target_stat)

class TestBranchStacked(ExternalBase):
    """Tests for branch --stacked"""

    def check_shallow_branch(self, branch_revid, stacked_on):
        """Assert that the branch 'newbranch' has been published correctly.
        
        :param stacked_on: url of a branch this one is stacked upon.
        :param branch_revid: a revision id that should be the only 
            revision present in the stacked branch, and it should not be in
            the reference branch.
        """
        new_branch = branch.Branch.open('newbranch')
        # The branch refers to the mainline
        self.assertEqual(stacked_on, new_branch.get_stacked_on_url())
        # and the branch's work was pushed
        self.assertTrue(new_branch.repository.has_revision(branch_revid))
        # The newly committed revision shoud be present in the stacked branch,
        # but not in the stacked-on branch.  Because stacking is set up by the
        # branch object, if we open the stacked branch's repository directly,
        # bypassing the branch, we see only what's in the stacked repository.
        stacked_repo = bzrdir.BzrDir.open('newbranch').open_repository()
        stacked_repo_revisions = set(stacked_repo.all_revision_ids())
        if len(stacked_repo_revisions) != 1:
            self.fail("wrong revisions in stacked repository: %r"
                % (stacked_repo_revisions,))

    def assertRevisionInRepository(self, repo_path, revid):
        """Check that a revision is in a repository, disregarding stacking."""
        repo = bzrdir.BzrDir.open(repo_path).open_repository()
        self.assertTrue(repo.has_revision(revid))

    def assertRevisionNotInRepository(self, repo_path, revid):
        """Check that a revision is not in a repository, disregarding stacking."""
        repo = bzrdir.BzrDir.open(repo_path).open_repository()
        self.assertFalse(repo.has_revision(revid))

    def assertRevisionsInBranchRepository(self, revid_list, branch_path):
        repo = branch.Branch.open(branch_path).repository
        self.assertEqual(set(revid_list),
            repo.has_revisions(revid_list))

    def test_branch_stacked_branch_not_stacked(self):
        """Branching a stacked branch is not stacked by default"""
        # We have a mainline
        trunk_tree = self.make_branch_and_tree('target',
            format='development')
        trunk_tree.commit('mainline')
        # and a branch from it which is stacked
        branch_tree = self.make_branch_and_tree('branch',
            format='development')
        branch_tree.branch.set_stacked_on_url(trunk_tree.branch.base)
        # with some work on it
        branch_tree.commit('moar work plz')
        # branching our local branch gives us a new stacked branch pointing at
        # mainline.
        out, err = self.run_bzr(['branch', 'branch', 'newbranch'])
        self.assertEqual('', out)
        self.assertEqual('Branched 1 revision(s).\n',
            err)
        # it should have preserved the branch format, and so it should be
        # capable of supporting stacking, but not actually have a stacked_on
        # branch configured
        self.assertRaises(errors.NotStacked,
            bzrdir.BzrDir.open('newbranch').open_branch().get_stacked_on_url)

    def test_branch_stacked_branch_stacked(self):
        """Asking to stack on a stacked branch does work"""
        # We have a mainline
        trunk_tree = self.make_branch_and_tree('target',
            format='development')
        trunk_revid = trunk_tree.commit('mainline')
        # and a branch from it which is stacked
        branch_tree = self.make_branch_and_tree('branch',
            format='development')
        branch_tree.branch.set_stacked_on_url(trunk_tree.branch.base)
        # with some work on it
        branch_revid = branch_tree.commit('moar work plz')
        # you can chain branches on from there
        out, err = self.run_bzr(['branch', 'branch', '--stacked', 'branch2'])
        self.assertEqual('', out)
        self.assertEqual('Created new stacked branch referring to %s.\n' %
            branch_tree.branch.base, err)
        self.assertEqual(branch_tree.branch.base,
            branch.Branch.open('branch2').get_stacked_on_url())
        branch2_tree = WorkingTree.open('branch2')
        branch2_revid = branch2_tree.commit('work on second stacked branch')
        self.assertRevisionInRepository('branch2', branch2_revid)
        self.assertRevisionsInBranchRepository(
            [trunk_revid, branch_revid, branch2_revid],
            'branch2')

    def test_branch_stacked(self):
        # We have a mainline
        trunk_tree = self.make_branch_and_tree('mainline',
            format='development')
        original_revid = trunk_tree.commit('mainline')
        self.assertRevisionInRepository('mainline', original_revid)
        # and a branch from it which is stacked
        out, err = self.run_bzr(['branch', '--stacked', 'mainline',
            'newbranch'])
        self.assertEqual('', out)
        self.assertEqual('Created new stacked branch referring to %s.\n' %
            trunk_tree.branch.base, err)
        self.assertRevisionNotInRepository('newbranch', original_revid)
        new_tree = WorkingTree.open('newbranch')
        new_revid = new_tree.commit('new work')
        self.check_shallow_branch(new_revid, trunk_tree.branch.base)

    def test_branch_stacked_from_smart_server(self):
        # We can branch stacking on a smart server
        from bzrlib.smart.server import SmartTCPServer_for_testing
        self.transport_server = SmartTCPServer_for_testing
        trunk = self.make_branch('mainline', format='development')
        out, err = self.run_bzr(
            ['branch', '--stacked', self.get_url('mainline'), 'shallow'])

    def test_branch_stacked_from_non_stacked_format(self):
        """The origin format doesn't support stacking"""
        trunk = self.make_branch('trunk', format='pack-0.92')
        out, err = self.run_bzr(
            ['branch', '--stacked', 'trunk', 'shallow'])


class TestRemoteBranch(TestCaseWithSFTPServer):

    def setUp(self):
        super(TestRemoteBranch, self).setUp()
        tree = self.make_branch_and_tree('branch')
        self.build_tree_contents([('branch/file', 'file content\n')])
        tree.add('file')
        tree.commit('file created')

    def test_branch_local_remote(self):
        self.run_bzr(['branch', 'branch', self.get_url('remote')])
        t = self.get_transport()
        # Ensure that no working tree what created remotely
        self.assertFalse(t.has('remote/file'))

    def test_branch_remote_remote(self):
        # Light cheat: we access the branch remotely
        self.run_bzr(['branch', self.get_url('branch'),
                      self.get_url('remote')])
        t = self.get_transport()
        # Ensure that no working tree what created remotely
        self.assertFalse(t.has('remote/file'))

