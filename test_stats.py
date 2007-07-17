from bzrlib.tests import TestCase
from bzrlib.plugins.stats import extract_fullname


class TestFullnameExtractor(TestCase):
    def test_standard(self):
        self.assertEquals("John Doe", 
            extract_fullname("John Doe <joe@example.com>"))

    def test_only_email(self):
        self.assertEquals("",
            extract_fullname("joe@example.com"))

    def test_only_fullname(self):
        self.assertEquals("John Doe",
            extract_fullname("John Doe"))

