from StringIO import StringIO

from bzrlib.errors import BinaryFile
from bzrlib.tests import TestCase, TestCaseInTempDir
from bzrlib.textfile import *


class TextFile(TestCase):
    def test_text_file(self):
        s = StringIO('ab' * 2048)
        self.assertEqual(text_file(s).read(), s.getvalue())
        s = StringIO('a' * 1023 + '\x00')
        self.assertRaises(BinaryFile, text_file, s)
        s = StringIO('a' * 1024 + '\x00')
        self.assertEqual(text_file(s).read(), s.getvalue())

    def test_check_text_lines(self):
        lines = ['ab' * 2048]
        check_text_lines(lines)
        lines = ['a' * 1023 + '\x00']
        self.assertRaises(BinaryFile, check_text_lines, lines)
        lines = ['a' * 1024 + '\x00']
        check_text_lines(lines)

class TextPath(TestCaseInTempDir):
    def test_text_file(self):
        file('boo', 'wb').write('ab' * 2048)
        check_text_path('boo')
        file('boo', 'wb').write('a' * 1023 + '\x00')
        self.assertRaises(BinaryFile, check_text_path, 'boo')
        file('boo', 'wb').write('a' * 1024 + '\x00')
        check_text_path('boo')
