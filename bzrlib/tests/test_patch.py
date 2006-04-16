from bzrlib.errors import BinaryFile
from bzrlib.patch import diff3
from bzrlib.tests import TestCaseInTempDir

class TestPatch(TestCaseInTempDir):
    def test_diff3_binaries(self):
        file('this', 'wb').write('a')
        file('other', 'wb').write('a')
        file('base', 'wb').write('\x00')
        self.assertRaises(BinaryFile, diff3, 'unused', 'this', 'other', 'base')


