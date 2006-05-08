import svn.repos
import format
from tests import TestCaseWithSubversionRepository
from bzrlib.bzrdir import BzrDir
from bzrlib.tests.repository_implementations.test_repository import TestCaseWithRepository

class TestRepositoryWorks(TestCaseWithSubversionRepository):
    def setUp(self):
        TestCaseWithSubversionRepository.setUp(self)

    def test_uuid(self):
        bzrdir = self.open_bzrdir()
        self.assertTrue(isinstance(bzrdir, BzrDir))
        #self.assertTrue(isinstance(bzrdir, format.SvnRemoteAccess))
        repository = bzrdir.open_repository()
        self.assertEqual(svn.repos.get_uuid(self.repos), repository.uuid)
