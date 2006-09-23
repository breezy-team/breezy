# Copyright (C) 2006 by Canonical Ltd
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as published by
# the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Tests for bzr performance over SFTP"""

import os

from bzrlib import (
    bzrdir,
    )
from bzrlib.benchmarks import Benchmark
from bzrlib.tests import test_sftp_transport, TestSkipped

try:
    import paramiko
    paramiko_loaded = True
except ImportError:
    paramiko_loaded = False


class SFTPBenchmark(Benchmark):
    """Benchmark branch, push and pull across a local sftp connection."""

    def setUp(self):
        super(SFTPBenchmark, self).setUp()
        if not paramiko_loaded:
            raise TestSkipped('you must have paramiko to run this test')
        test_sftp_transport.set_test_transport_to_sftp(self)
         
    def test_branch(self):
        os.mkdir("a")
        tree, files = self.create_with_commits(100, 100, "a")
        self.time(bzrdir.BzrDir.open(self.get_url('a')).sprout, "b")

    def create_commit_and_pull(self, num_pull_revisions):
        os.mkdir("a")
        tree, files = self.create_with_commits(100, 100, "a")
        rbzrdir = bzrdir.BzrDir.open(self.get_url('a'))
        b2 = tree.bzrdir.sprout("b") # branch
        # change a few files and commit
        self.commit_some_revisions(tree, files, num_pull_revisions, 20)
        self.time(b2.open_branch().pull, rbzrdir.open_branch())

    def test_pull_1(self):
        self.create_commit_and_pull(1)
        
    def test_pull_10(self):
        self.create_commit_and_pull(10)

    def test_pull_100(self):
        self.create_commit_and_pull(100)

    def create_commit_and_push(self, num_push_revisions):
        os.mkdir("a")
        tree, files = self.create_with_commits(100, 100, "a")
        rbzrdir = bzrdir.BzrDir.open(self.get_url('a'))
        b2 = tree.bzrdir.sprout("b") # branch
        wtree = b2.open_workingtree()
        # change a few files and commit
        self.commit_some_revisions(
            wtree, ["b/%i" for i in range(100)],
            num_commits=num_push_revisions,
            changes_per_commit=20)
        self.time(rbzrdir.open_branch().pull, wtree.branch)

    def test_initial_push(self):
        os.mkdir('a')
        tree, files = self.create_with_commits(100, 100, "a")
        self.time(tree.bzrdir.clone, self.get_url('b'),
                  revision_id=tree.last_revision())

    def test_push_1(self):
        self.create_commit_and_push(1)

    def test_push_10(self):
        self.create_commit_and_push(10)

    def test_push_100(self):
        self.create_commit_and_push(100)


class SFTPSlowSocketBenchmark(SFTPBenchmark):
    def setUp(self):
        super(SFTPSlowSocketBenchmark, self).setUp()
        self.get_server().add_latency = 0.03

