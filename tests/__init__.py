import svn.repos
import os
from bzrlib import osutils
from bzrlib.bzrdir import BzrDir
from bzrlib.tests import TestCaseInTempDir

class TestCaseWithSubversionRepository(TestCaseInTempDir):
    def setUp(self):
        TestCaseInTempDir.setUp(self)

        self.repos_path = os.path.join(self.test_dir, "svn_repos")
        self.repos = svn.repos.create(self.repos_path, '', '', None, None)
        self.repos_url = "file://%s" % self.repos_path

        self.fs = svn.repos.fs(self.repos)

    def open_bzrdir(self):
        return BzrDir.open("svn+"+self.repos_url)
