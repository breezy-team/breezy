import os
import shutil
import tempfile
from unittest import TestCase

from breezy import osutils


class TestCaseInTempDir(TestCase):
    """Minimal TestCase that runs in a temporary directory.
    
    Only implements the functionality actually needed by vcsgraph tests.
    """

    def setUp(self):
        super().setUp()
        self.test_dir = tempfile.mkdtemp(prefix='vcsgraph_test_')
        self.original_dir = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.original_dir)
        shutil.rmtree(self.test_dir)
        super().tearDown()

    def assertPathExists(self, path):
        """Fail unless path exists."""
        self.assertTrue(osutils.lexists(path), f"{path} does not exist")

    def assertPathDoesNotExist(self, path):
        """Fail if path exists."""
        self.assertFalse(osutils.lexists(path), f"{path} exists")


__all__ = ["TestCaseInTempDir"]