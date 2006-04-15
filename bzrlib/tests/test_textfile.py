from StringIO import StringIO

from bzrlib.errors import BinaryFile
from bzrlib.tests import TestCase
from bzrlib.textfile import text_file


class TextFile(TestCase):
    def test_text_file(self):
        s = StringIO('ab' * 2048)
        s.seek(0)
        self.assertEqual(text_file(s).read(), s.getvalue())
        s = StringIO('a' * 1023 + '\x00')
        self.assertRaises(BinaryFile, text_file, s)
        s = StringIO('a' * 1024 + '\x00')
        self.assertEqual(text_file(s).read(), s.getvalue())

