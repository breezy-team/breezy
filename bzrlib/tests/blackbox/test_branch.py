# Copyright (C) 2005, 2006, 2008, 2009 Canonical Ltd
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


"""Black-box tests for bzr branch."""

import os

from bzrlib import (
    branch,
    bzrdir,
    errors,
    repository,
    revision as _mod_revision,
    )
from bzrlib.repofmt.knitrepo import RepositoryFormatKnit1
from bzrlib.tests.blackbox import ExternalBase
from bzrlib.tests import (
    KnownFailure,
    HardlinkFeature,
    )
from bzrlib.tests.test_sftp_transport import TestCaseWithSFTPServer
from bzrlib.urlutils import local_path_to_url, strip_trailing_slash
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

    def test_branch_switch_no_branch(self):
        # No branch in the current directory:
        #  => new branch will be created, but switch fails
        self.example_branch('a')
        self.make_repository('current')
        self.run_bzr_error(['No WorkingTree exists for'],
            'branch --switch ../a ../b', working_dir='current')
        a = branch.Branch.open('a')
        b = branch.Branch.open('b')
        self.assertEqual(a.last_revision(), b.last_revision())

    def test_branch_switch_no_wt(self):
        # No working tree in the current directory:
        #  => new branch will be created, but switch fails and the current
        #     branch is unmodified
        self.example_branch('a')
        self.make_branch('current')
        self.run_bzr_error(['No WorkingTree exists for'],
            'branch --switch ../a ../b', working_dir='current')
        a = branch.Branch.open('a')
        b = branch.Branch.open('b')
        self.assertEqual(a.last_revision(), b.last_revision())
        work = branch.Branch.open('current')
        self.assertEqual(work.last_revision(), _mod_revision.NULL_REVISION)

    def test_branch_switch_no_checkout(self):
        # Standalone branch in the current directory:
        #  => new branch will be created, but switch fails and the current
        #     branch is unmodified
        self.example_branch('a')
        self.make_branch_and_tree('current')
        self.run_bzr_error(['Cannot switch a branch, only a checkout'],
            'branch --switch ../a ../b', working_dir='current')
        a = branch.Branch.open('a')
        b = branch.Branch.open('b')
        self.assertEqual(a.last_revision(), b.last_revision())
        work = branch.Branch.open('current')
        self.assertEqual(work.last_revision(), _mod_revision.NULL_REVISION)

    def test_branch_switch_checkout(self):
        # Checkout in the current directory:
        #  => new branch will be created and checkout bound to the new branch
        self.example_branch('a')
        self.run_bzr('checkout a current')
        out, err = self.run_bzr('branch --switch ../a ../b', working_dir='current')
        a = branch.Branch.open('a')
        b = branch.Branch.open('b')
        self.assertEqual(a.last_revision(), b.last_revision())
        work = WorkingTree.open('current')
        self.assertEndsWith(work.branch.get_bound_location(), '/b/')
        self.assertContainsRe(err, "Switched to branch: .*/b/")

    def test_branch_switch_lightweight_checkout(self):
        # Lightweight checkout in the current directory:
        #  => new branch will be created and lightweight checkout pointed to
        #     the new branch
        self.example_branch('a')
        self.run_bzr('checkout --lightweight a current')
        out, err = self.run_bzr('branch --switch ../a ../b', working_dir='current')
        a = branch.Branch.open('a')
        b = branch.Branch.open('b')
        self.assertEqual(a.last_revision(), b.last_revision())
        work = WorkingTree.open('current')
        self.assertEndsWith(work.branch.base, '/b/')
        self.assertContainsRe(err, "Switched to branch: .*/b/")

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
        out, err = self.run_bzr(['branch', 'source', 'target', '--hardlink'])
        source_stat = os.stat('source/file1')
        target_stat = os.stat('target/file1')
        same_file = (source_stat == target_stat)
        if same_file:
            pass
        else:
            # https://bugs.edge.launchpad.net/bzr/+bug/408193
            self.assertContainsRe(err, "hardlinking working copy files is "
                "not currently supported")
            raise KnownFailure("--hardlink doesn't work in formats "
                "that support content filtering (#408193)")

    def test_branch_standalone(self):
        shared_repo = self.make_repository('repo', shared=True)
        self.example_branch('source')
        self.run_bzr('branch --standalone source repo/target')
        b = branch.Branch.open('repo/target')
        expected_repo_path = os.path.abspath('repo/target/.bzr/repository')
        self.assertEqual(strip_trailing_slash(b.repository.base),
            strip_trailing_slash(local_path_to_url(expected_repo_path)))

    def test_branch_no_tree(self):
        self.example_branch('source')
        self.run_bzr('branch --no-tree source target')
        self.failIfExists('target/hello')
        self.failIfExists('target/goodbye')

    def test_branch_into_existing_dir(self):
        self.example_branch('a')
        # existing dir with similar files but no .bzr dir
        self.build_tree_contents([('b/',)])
        self.build_tree_contents([('b/hello', 'bar')])  # different content
        self.build_tree_contents([('b/goodbye', 'baz')])# same content
        # fails without --use-existing-dir
        out,err = self.run_bzr('branch a b', retcode=3)
        self.assertEqual('', out)
        self.assertEqual('bzr: ERROR: Target directory "b" already exists.\n',
            err)
        # force operation
        self.run_bzr('branch a b --use-existing-dir')
        # check conflicts
        self.failUnlessExists('b/hello.moved')
        self.failIfExists('b/godbye.moved')
        # we can't branch into branch
        out,err = self.run_bzr('branch a b --use-existing-dir', retcode=3)
        self.assertEqual('', out)
        self.assertEqual('bzr: ERROR: Already a branch: "b".\n', err)


class TestBranchStacked(ExternalBase):
    """Tests for branch --stacked"""

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
            format='1.9')
        trunk_tree.commit('mainline')
        # and a branch from it which is stacked
        branch_tree = self.make_branch_and_tree('branch',
            format='1.9')
        branch_tree.branch.set_stacked_on_url(trunk_tree.branch.base)
        # with some work on it
        work_tree = trunk_tree.branch.bzrdir.sprout('local').open_workingtree()
        work_tree.commit('moar work plz')
        work_tree.branch.push(branch_tree.branch)
        # branching our local branch gives us a new stacked branch pointing at
        # mainline.
        out, err = self.run_bzr(['branch', 'branch', 'newbranch'])
        self.assertEqual('', out)
        self.assertEqual('Branched 2 revision(s).\n',
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
            format='1.9')
        trunk_revid = trunk_tree.commit('mainline')
        # and a branch from it which is stacked
        branch_tree = self.make_branch_and_tree('branch',
            format='1.9')
        branch_tree.branch.set_stacked_on_url(trunk_tree.branch.base)
        # with some work on it
        work_tree = trunk_tree.branch.bzrdir.sprout('local').open_workingtree()
        branch_revid = work_tree.commit('moar work plz')
        work_tree.branch.push(branch_tree.branch)
        # you can chain branches on from there
        out, err = self.run_bzr(['branch', 'branch', '--stacked', 'branch2'])
        self.assertEqual('', out)
        self.assertEqual('Created new stacked branch referring to %s.\n' %
            branch_tree.branch.base, err)
        self.assertEqual(branch_tree.branch.base,
            branch.Branch.open('branch2').get_stacked_on_url())
        branch2_tree = WorkingTree.open('branch2')
        branch2_revid = work_tree.commit('work on second stacked branch')
        work_tree.branch.push(branch2_tree.branch)
        self.assertRevisionInRepository('branch2', branch2_revid)
        self.assertRevisionsInBranchRepository(
            [trunk_revid, branch_revid, branch2_revid],
            'branch2')

    def test_branch_stacked(self):
        # We have a mainline
        trunk_tree = self.make_branch_and_tree('mainline',
            format='1.9')
        original_revid = trunk_tree.commit('mainline')
        self.assertRevisionInRepository('mainline', original_revid)
        # and a branch from it which is stacked
        out, err = self.run_bzr(['branch', '--stacked', 'mainline',
            'newbranch'])
        self.assertEqual('', out)
        self.assertEqual('Created new stacked branch referring to %s.\n' %
            trunk_tree.branch.base, err)
        self.assertRevisionNotInRepository('newbranch', original_revid)
        new_branch = branch.Branch.open('newbranch')
        self.assertEqual(trunk_tree.branch.base, new_branch.get_stacked_on_url())

    def test_branch_stacked_from_smart_server(self):
        # We can branch stacking on a smart server
        from bzrlib.smart.server import SmartTCPServer_for_testing
        self.transport_server = SmartTCPServer_for_testing
        trunk = self.make_branch('mainline', format='1.9')
        out, err = self.run_bzr(
            ['branch', '--stacked', self.get_url('mainline'), 'shallow'])

    def test_branch_stacked_from_non_stacked_format(self):
        """The origin format doesn't support stacking"""
        trunk = self.make_branch('trunk', format='pack-0.92')
        out, err = self.run_bzr(
            ['branch', '--stacked', 'trunk', 'shallow'])
        # We should notify the user that we upgraded their format
        self.assertEqualDiff(
            'Source repository format does not support stacking, using format:\n'
            '  Packs 5 (adds stacking support, requires bzr 1.6)\n'
            'Source branch format does not support stacking, using format:\n'
            '  Branch format 7\n'
            'Created new stacked branch referring to %s.\n' % (trunk.base,),
            err)

    def test_branch_stacked_from_rich_root_non_stackable(self):
        trunk = self.make_branch('trunk', format='rich-root-pack')
        out, err = self.run_bzr(
            ['branch', '--stacked', 'trunk', 'shallow'])
        # We should notify the user that we upgraded their format
        self.assertEqualDiff(
            'Source repository format does not support stacking, using format:\n'
            '  Packs 5 rich-root (adds stacking support, requires bzr 1.6.1)\n'
            'Source branch format does not support stacking, using format:\n'
            '  Branch format 7\n'
            'Created new stacked branch referring to %s.\n' % (trunk.base,),
            err)


class TestSmartServerBranching(ExternalBase):

    def test_branch_from_trivial_branch_to_same_server_branch_acceptance(self):
        self.setup_smart_server_with_call_log()
        t = self.make_branch_and_tree('from')
        for count in range(9):
            t.commit(message='commit %d' % count)
        self.reset_smart_call_log()
        out, err = self.run_bzr(['branch', self.get_url('from'),
            self.get_url('target')])
        # This figure represent the amount of work to perform this use case. It
        # is entirely ok to reduce this number if a test fails due to rpc_count
        # being too low. If rpc_count increases, more network roundtrips have
        # become necessary for this use case. Please do not adjust this number
        # upwards without agreement from bzr's network support maintainers.
        self.assertLength(38, self.hpss_calls)

    def test_branch_from_trivial_branch_streaming_acceptance(self):
        self.setup_smart_server_with_call_log()
        t = self.make_branch_and_tree('from')
        for count in range(9):
            t.commit(message='commit %d' % count)
        self.reset_smart_call_log()
        out, err = self.run_bzr(['branch', self.get_url('from'),
            'local-target'])
        # This figure represent the amount of work to perform this use case. It
        # is entirely ok to reduce this number if a test fails due to rpc_count
        # being too low. If rpc_count increases, more network roundtrips have
        # become necessary for this use case. Please do not adjust this number
        # upwards without agreement from bzr's network support maintainers.
        self.assertLength(10, self.hpss_calls)

    def test_branch_from_trivial_stacked_branch_streaming_acceptance(self):
        self.setup_smart_server_with_call_log()
        t = self.make_branch_and_tree('trunk')
        for count in range(8):
            t.commit(message='commit %d' % count)
        tree2 = t.branch.bzrdir.sprout('feature', stacked=True
            ).open_workingtree()
        local_tree = t.branch.bzrdir.sprout('local-working').open_workingtree()
        local_tree.commit('feature change')
        local_tree.branch.push(tree2.branch)
        self.reset_smart_call_log()
        out, err = self.run_bzr(['branch', self.get_url('feature'),
            'local-target'])
        # This figure represent the amount of work to perform this use case. It
        # is entirely ok to reduce this number if a test fails due to rpc_count
        # being too low. If rpc_count increases, more network roundtrips have
        # become necessary for this use case. Please do not adjust this number
        # upwards without agreement from bzr's network support maintainers.
        self.assertLength(15, self.hpss_calls)


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

