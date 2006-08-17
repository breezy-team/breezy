import os
from bzrlib.tests.test_sftp_transport import TestCaseWithSFTPServer
from bzrlib.benchmarks import Benchmark
from bzrlib import bzrdir
import bzrlib.transport
import bzrlib.transport.http
from bzrlib.workingtree import WorkingTree
from bzrlib.tests import test_sftp_transport

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
        test_sftp_transport.set_transport(self) 
         
    def test_branch(self):
        os.mkdir("a")
        tree, files = self.create_with_commits(100, 100, "a")
        self.time(bzrdir.BzrDir.open(self.get_url('a')).sprout, "b")

    def test_pull_1(self):
        os.mkdir("a")
        tree, files = self.create_with_commits(100, 100, "a")
        rbzrdir = bzrdir.BzrDir.open(self.get_url('a'))
        b2 = tree.bzrdir.sprout("b") # branch
        # change a few files and commit
        self.commit_some_revisions(tree, files, 1, 20)
        self.time(b2.open_branch().pull, rbzrdir.open_branch())
        
    def test_pull_100(self):
        os.mkdir("a")
        tree, files = self.create_with_commits(100, 100, "a")
        rbzrdir = bzrdir.BzrDir.open(self.get_url('a'))
        b2 = tree.bzrdir.sprout("b") # branch
        # change a few files and commit
        self.commit_some_revisions(tree, files, 100, 20)
        self.time(b2.open_branch().pull, rbzrdir.open_branch())

    def create_commit_and_push(self, num_push_revisions):
        os.mkdir("a")
        tree, files = self.create_with_commits(100, 100, "a")
        rbzrdir = bzrdir.BzrDir.open(self.get_url('a'))
        b2 = rbzrdir.sprout("b") # branch
        wtree = b2.open_workingtree()
        # change a few files and commit
        self.commit_some_revisions(
            wtree, ["b/%i" for i in range(100)], 
            num_commits=num_push_revisions,
            changes_per_commit=20)
        self.time(rbzrdir.open_branch().pull, wtree.branch)

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

