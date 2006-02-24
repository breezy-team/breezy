# Copyright (C) 2006 Canonical

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

from StringIO import StringIO

from bzrlib.errors import UnknownSplatFormat, MalformedSplatDict
from bzrlib.splatfile import *
from bzrlib.tests import TestCaseInTempDir

class TestSplatfile(TestCaseInTempDir):
    def test_dump_read(self):
        test_dict = {u'a ': u'b\n', u'c\t': u'd%', '\u1234': '\u0000'}
        dump_dict(file('dumpfile', 'wb'), test_dict)
        new_dict = read_dict(file('dumpfile', 'rb'))
        self.assertEqual(test_dict, new_dict)

    def test_splatfile_format(self):
        test_dict = {u'a': u'b\n', u'c\t': u'd%', '\u1234': '\u0000'}
        pairs = [(u'a', u'b\n'), (u'c\t', u'd%'), ('\u1234', '\u0000')]
        expected = SPLATFILE_1_HEADER + \
            '\na b%0a\nc%09 d%25\n\u1234 \u0000\n'.encode('UTF-8')
        write_splat(file('splatfile', 'wb'), pairs)
        self.assertEqual(file('splatfile', 'rb').read(), expected)
        no_eof_nl = SPLATFILE_1_HEADER + \
            '\na b%0a\nc%09 d%25\n\u1234 \u0000'.encode('UTF-8')
        result = read_dict(StringIO(no_eof_nl))
        self.assertEqual(result, test_dict)
        s = StringIO()
        splat_list = ['a', 'b', 'c']
        write_splat(s, [splat_list])
        s.seek(0)
        [new_list] = read_splat(s)
        self.assertEqual(new_list, splat_list)


    def raises(self, err, splatstring):
        self.assertRaises(err, read_dict, StringIO(splatstring))

    def test_broken_splatfile_dict(self):
        self.raises(UnknownSplatFormat, 'f\n')
        missing_space = SPLATFILE_1_HEADER + \
            '\na b%0a\nc%09d%25\n\u1234 \u0000\n'.encode('UTF-8')
        self.raises(MalformedSplatDict, missing_space)
        extra_space = SPLATFILE_1_HEADER + \
            '\na b %0a\nc%09 d%25\n\u1234 \u0000\n'.encode('UTF-8')
        self.raises(MalformedSplatDict, extra_space)
