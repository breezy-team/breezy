import svn
import format
from tests import TestCaseWithSubversionRepository
from bzrlib.bzrdir import BzrDir
from bzrlib.tests.repository_implementations.test_repository import TestCaseWithRepository

class TestRepositoryWorks(TestCaseWithSubversionRepository):
    def setUp(self):
        TestCaseWithSubversionRepository.setUp(self)

    def test_url(self):
        """ Test repository URL is kept """
        bzrdir = self.open_bzrdir()
        self.assertTrue(isinstance(bzrdir, BzrDir))
        repository = bzrdir.open_repository()
        self.assertEqual(repository.url, self.repos_url)

    def test_uuid(self):
        """ Test UUID is retrieved correctly """
        bzrdir = self.open_bzrdir()
        self.assertTrue(isinstance(bzrdir, BzrDir))
        repository = bzrdir.open_repository()
        self.assertEqual(svn.fs.get_uuid(self.fs), repository.uuid)
