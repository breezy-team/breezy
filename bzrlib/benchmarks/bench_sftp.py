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
    """A benchmark base class that provides a sftp server on localhost."""

    def setUp(self):
        if not paramiko_loaded:
            raise TestSkipped('you must have paramiko to run this test')
        super(SFTPBenchmark, self).setUp()
        test_sftp_transport.set_transport(self) 
         
    def create_with_commits(self, num_files, num_commits, directory_name='.'):
        """Create a tree with many commits.
        
        No files change are included.
        """
        files = ["%s/%s" % (directory_name, i) for i in range(num_files)]
        for fn in files:
            f = open(fn, "w")
            f.write("some content\n")
            f.close()
        tree = bzrdir.BzrDir.create_standalone_workingtree(directory_name)
        for i in range(num_files):
            tree.add(str(i))
        tree.lock_write()
        tree.branch.lock_write()
        tree.branch.repository.lock_write()
        try:
            tree.commit('initial commit')
            for i in range(num_commits):
                fn = files[i % len(files)]
                f = open(fn, "w")
                f.write("\n".join([str(j) for j in (range(i) + [i, i, i])]))
                f.close()
                tree.commit("changing file %s" % fn)
        finally:
            try:
                try:
                    tree.branch.repository.unlock()
                finally:
                    tree.branch.unlock()
            finally:
                tree.unlock()
        return tree, files

    def commit_some_revisions(self, tree, files, num_commits):
        for j in range(num_commits):
            for i in range(20):
                fn = files[i]
                f = open(fn, "w")
                f.write("\n".join([str(k) for k in (range(i) + [i, i, i])]))
                f.close()
            tree.commit("new revision")

    def test_branch(self):
        os.mkdir("a")
        t, files = self.create_with_commits(100, 100, "a")

        self.time(bzrdir.BzrDir.open(self.get_url('a')).sprout, "b")

    def test_pull_1(self):
        os.mkdir("a")
        t, files = self.create_with_commits(100, 100, "a")
        rbzrdir = bzrdir.BzrDir.open(self.get_url('a'))
        b2 = rbzrdir.sprout("b") # branch
        # change a few files and commit
        self.commit_some_revisions(t, files, 1)
        self.time(b2.open_branch().pull, rbzrdir.open_branch())
        
    def test_pull_100(self):
        os.mkdir("a")
        t, files = self.create_with_commits(100, 100, "a")
        rbzrdir = bzrdir.BzrDir.open(self.get_url('a'))
        b2 = rbzrdir.sprout("b") # branch
        # change a few files and commit
        self.commit_some_revisions(t, files, 100)
        self.time(b2.open_branch().pull, rbzrdir.open_branch())

    def create_commit_and_push(self, num_push_revisions):
        os.mkdir("a")
        t, files = self.create_with_commits(100, 100, "a")
        rbzrdir = bzrdir.BzrDir.open(self.get_url('a'))
        b2 = rbzrdir.sprout("b") # branch
        # change a few files and commit
        self.commit_some_revisions(
            b2.open_workingtree(), ["b/%i" for i in range(100)], 
            num_commits=num_push_revisions)
        self.time(rbzrdir.open_branch().pull, b2.open_branch())

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

    def time(self, *args, **kwargs):
        """ Time the operation as usual but add the simulated time of the
        SocketDelay"""
        from bzrlib.transport.sftp import SocketDelay
        start_time = SocketDelay.simulated_time
        super(SFTPSlowSocketBenchmark, self).time(*args, **kwargs)
        self._benchtime += SocketDelay.simulated_time - start_time

