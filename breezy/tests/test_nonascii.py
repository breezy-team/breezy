# Copyright (C) 2005, 2006, 2008, 2009, 2011 Canonical Ltd
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Test that various operations work in a non-ASCII environment."""

import os
import sys
from unicodedata import normalize

from .. import osutils
from ..osutils import pathjoin
from . import TestCase, TestCaseWithTransport, TestSkipped


class NonAsciiTest(TestCaseWithTransport):

    def test_add_in_nonascii_branch(self):
        """Test adding in a non-ASCII branch."""
        br_dir = u"\u1234"
        try:
            wt = self.make_branch_and_tree(br_dir)
        except UnicodeEncodeError:
            raise TestSkipped("filesystem can't accomodate nonascii names")
            return
        with open(pathjoin(br_dir, "a"), "w") as f:
            f.write("hello")
        wt.add(["a"], ids=[b"a-id"])


a_circle_c = u'\xe5'
a_circle_d = u'a\u030a'
a_dots_c = u'\xe4'
a_dots_d = u'a\u0308'
z_umlat_c = u'\u017d'
z_umlat_d = u'Z\u030c'
squared_c = u'\xbc'  # This gets mapped to '2' if we use NFK[CD]
squared_d = u'\xbc'
quarter_c = u'\xb2'  # Gets mapped to u'1\u20444' (1/4) if we use NFK[CD]
quarter_d = u'\xb2'


class TestNormalization(TestCase):
    """Verify that we have our normalizations correct."""

    def test_normalize(self):
        self.assertEqual(a_circle_d, normalize('NFD', a_circle_c))
        self.assertEqual(a_circle_c, normalize('NFC', a_circle_d))
        self.assertEqual(a_dots_d, normalize('NFD', a_dots_c))
        self.assertEqual(a_dots_c, normalize('NFC', a_dots_d))
        self.assertEqual(z_umlat_d, normalize('NFD', z_umlat_c))
        self.assertEqual(z_umlat_c, normalize('NFC', z_umlat_d))
        self.assertEqual(squared_d, normalize('NFC', squared_c))
        self.assertEqual(squared_c, normalize('NFD', squared_d))
        self.assertEqual(quarter_d, normalize('NFC', quarter_c))
        self.assertEqual(quarter_c, normalize('NFD', quarter_d))


class NormalizedFilename(TestCaseWithTransport):
    """Test normalized_filename and associated helpers"""

    def test__accessible_normalized_filename(self):
        anf = osutils._accessible_normalized_filename
        # normalized_filename should allow plain ascii strings
        # not just unicode strings
        self.assertEqual((u'ascii', True), anf('ascii'))
        self.assertEqual((a_circle_c, True), anf(a_circle_c))
        self.assertEqual((a_circle_c, True), anf(a_circle_d))
        self.assertEqual((a_dots_c, True), anf(a_dots_c))
        self.assertEqual((a_dots_c, True), anf(a_dots_d))
        self.assertEqual((z_umlat_c, True), anf(z_umlat_c))
        self.assertEqual((z_umlat_c, True), anf(z_umlat_d))
        self.assertEqual((squared_c, True), anf(squared_c))
        self.assertEqual((squared_c, True), anf(squared_d))
        self.assertEqual((quarter_c, True), anf(quarter_c))
        self.assertEqual((quarter_c, True), anf(quarter_d))

    def test__inaccessible_normalized_filename(self):
        inf = osutils._inaccessible_normalized_filename
        # normalized_filename should allow plain ascii strings
        # not just unicode strings
        self.assertEqual((u'ascii', True), inf('ascii'))
        self.assertEqual((a_circle_c, True), inf(a_circle_c))
        self.assertEqual((a_circle_c, False), inf(a_circle_d))
        self.assertEqual((a_dots_c, True), inf(a_dots_c))
        self.assertEqual((a_dots_c, False), inf(a_dots_d))
        self.assertEqual((z_umlat_c, True), inf(z_umlat_c))
        self.assertEqual((z_umlat_c, False), inf(z_umlat_d))
        self.assertEqual((squared_c, True), inf(squared_c))
        self.assertEqual((squared_c, True), inf(squared_d))
        self.assertEqual((quarter_c, True), inf(quarter_c))
        self.assertEqual((quarter_c, True), inf(quarter_d))

    def test_functions(self):
        if osutils.normalizes_filenames():
            self.assertEqual(osutils.normalized_filename,
                             osutils._accessible_normalized_filename)
        else:
            self.assertEqual(osutils.normalized_filename,
                             osutils._inaccessible_normalized_filename)

    def test_platform(self):
        # With FAT32 and certain encodings on win32
        # a_circle_c and a_dots_c actually map to the same file
        # adding a suffix kicks in the 'preserving but insensitive'
        # route, and maintains the right files
        files = [a_circle_c + '.1', a_dots_c + '.2', z_umlat_c + '.3']
        try:
            self.build_tree(files)
        except UnicodeError:
            raise TestSkipped("filesystem cannot create unicode files")

        if sys.platform == 'darwin':
            expected = sorted(
                [a_circle_d + '.1', a_dots_d + '.2', z_umlat_d + '.3'])
        else:
            expected = sorted(files)

        present = sorted(os.listdir(u'.'))
        self.assertEqual(expected, present)

    def test_access_normalized(self):
        # We should always be able to access files created with
        # normalized filenames
        # With FAT32 and certain encodings on win32
        # a_circle_c and a_dots_c actually map to the same file
        # adding a suffix kicks in the 'preserving but insensitive'
        # route, and maintains the right files
        files = [a_circle_c + '.1', a_dots_c + '.2', z_umlat_c + '.3',
                 squared_c + '.4', quarter_c + '.5']
        try:
            self.build_tree(files, line_endings='native')
        except UnicodeError:
            raise TestSkipped("filesystem cannot create unicode files")

        for fname in files:
            # We should get an exception if we can't open the file at
            # this location.
            path, can_access = osutils.normalized_filename(fname)

            self.assertEqual(path, fname)
            self.assertTrue(can_access)

            with open(path, 'rb') as f:
                # Check the contents
                shouldbe = b'contents of %s%s' % (path.encode('utf8'),
                                                  os.linesep.encode('utf-8'))
                actual = f.read()
            self.assertEqual(shouldbe, actual,
                             'contents of %r is incorrect: %r != %r'
                             % (path, shouldbe, actual))

    def test_access_non_normalized(self):
        # Sometimes we can access non-normalized files by their normalized
        # path, verify that normalized_filename returns the right info
        files = [a_circle_d + '.1', a_dots_d + '.2', z_umlat_d + '.3']

        try:
            self.build_tree(files)
        except UnicodeError:
            raise TestSkipped("filesystem cannot create unicode files")

        for fname in files:
            # We should get an exception if we can't open the file at
            # this location.
            path, can_access = osutils.normalized_filename(fname)

            self.assertNotEqual(path, fname)

            # We should always be able to access them from the name
            # they were created with
            f = open(fname, 'rb')
            f.close()

            # And normalized_filename sholud tell us correctly if we can
            # access them by an alternate name
            if can_access:
                f = open(path, 'rb')
                f.close()
            else:
                self.assertRaises(IOError, open, path, 'rb')
