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


"""Black-box tests for bzr branch."""

import os

from bzrlib import branch, bzrdir
from bzrlib.repofmt.knitrepo import RepositoryFormatKnit1
from bzrlib.tests.blackbox import ExternalBase
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
        self.assertEqual('b\n', b.control_files.get_utf8('branch-name').read())
        self.run_bzr('branch a c -r 1')
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

