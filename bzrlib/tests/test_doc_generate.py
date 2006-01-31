from bzrlib.tests import TestCaseInTempDir
from bzrlib.branch import Branch
import tools.doc_generate

class TestDocGenerate(TestCaseInTempDir):
    def test_generate_manpage(self):
        """Simple smoke test for doc_generate"""
        infogen_mod = tools.doc_generate.get_module("man")

