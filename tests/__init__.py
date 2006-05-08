import svn.repos
from bzrlib import osutils
from bzrlib.bzrdir import BzrDir
from bzrlib.tests import TestCaseInTempDir

class TestCaseWithSubversionRepository(TestCaseInTempDir):
    def setUp(self):
        super(TestCaseInTempDir, self).setUp()

        self.repos_path = "svn_repos"
        self.repos = svn.repos.create(self.repos_path, '', '', None, None)
        self.repos_url = "svn+file://%s" % self.repos_path

    def open_bzrdir(self):
        return BzrDir.open(self.repos_url)
