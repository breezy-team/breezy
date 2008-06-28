from bzrlib.tests import TestCase
from bzrlib.plugins.stats.classify import classify_filename, classify_delta


class TestClassify(TestCase):
    def test_classify_code(self):
        self.assertEquals("code", classify_filename("foo/bar.c"))

    def test_classify_documentation(self):
        self.assertEquals("documentation", classify_filename("bla.html"))

    def test_classify_translation(self):
        self.assertEquals("translation", classify_filename("nl.po"))

    def test_classify_art(self):
        self.assertEquals("art", classify_filename("icon.png"))

    def test_classify_unknown(self):
        self.assertEquals(None, classify_filename("something.bar"))

    def test_classify_doc_hardcoded(self):
        self.assertEquals("documentation", classify_filename("README"))
